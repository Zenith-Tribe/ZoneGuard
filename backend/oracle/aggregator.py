"""
backend/oracle/aggregator.py — ChainOracle Network consensus engine (Innovation 03)

Implements threshold consensus for three oracle streams:
  S1 Environmental: 3 of 4 nodes must agree (OpenWeatherMap + IMD + AccuWeather + IoT)
  S2 Mobility:      2 of 3 nodes must agree (OSRM + Google Mobility + BBMP sensors)
  S3 Economic:      2 of 3 nodes must agree (Amazon proxy + Dunzo proxy + e-commerce density)

"Agreement" means the numerical values from two nodes are within a configurable
tolerance of each other (not just that they all returned successfully). This prevents
a compromised node from submitting wildly different data and still being counted.

All oracle readings are cryptographically signed. The aggregator verifies signatures
before including a reading in the consensus calculation.

Circuit breaker: if a source fails CIRCUIT_BREAKER_THRESHOLD consecutive times,
it is marked DEGRADED and excluded from the quorum denominator, so consensus
can still be reached with the remaining healthy nodes.

Output:
  ConsensusResult with status ACCEPTED | INSUFFICIENT_CONSENSUS | ALL_NODES_FAILED
  On ACCEPTED: aggregated_value contains the median-merged normalised reading.
  On INSUFFICIENT_CONSENSUS: signal_fusion should treat that signal as UNKNOWN,
  which downgrades confidence by one level (HIGH→MEDIUM, MEDIUM→LOW, etc).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from typing import Optional

from oracle.models import (
    ConsensusResult,
    ConsensusStatus,
    FailedOracleReading,
    NodeHealth,
    OracleNodeHealth,
    OracleReading,
    OracleStream,
    S1NormalisedReading,
    S2NormalisedReading,
    S3NormalisedReading,
)
from oracle.oracle_health import OracleHealthMonitor

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

# Agreement tolerance: two readings "agree" if their key metrics are within this %
S1_AGREEMENT_TOLERANCE_PCT   = 20.0   # e.g. rainfall readings within 20%
S2_AGREEMENT_TOLERANCE_PCT   = 25.0   # mobility index within 25%
S3_AGREEMENT_TOLERANCE_PCT   = 30.0   # order volume index within 30%

# Circuit breaker
CIRCUIT_BREAKER_THRESHOLD    = 3      # consecutive failures before node excluded

# Thresholds (mirrored from signal_fusion; can be overridden by GovernanceChaincode)
DEFAULT_S1_THRESHOLD = 3  # of 4 nodes
DEFAULT_S2_THRESHOLD = 2  # of 3 nodes
DEFAULT_S3_THRESHOLD = 2  # of 3 nodes

# HMAC secret for signature verification (loaded from env)
import os
ORACLE_HMAC_SECRET = os.getenv("ORACLE_HMAC_SECRET", "dev-secret-change-in-production")


# ─── Aggregator ───────────────────────────────────────────────────────────────

class OracleAggregator:
    """
    Polls all source nodes for a given stream, verifies signatures,
    applies circuit-breaker exclusions, and returns a ConsensusResult.
    """

    def __init__(self, health_monitor: Optional[OracleHealthMonitor] = None):
        self._health = health_monitor or OracleHealthMonitor()
        # Governance-injected thresholds (updated by GovernanceChaincode)
        self._thresholds = {
            OracleStream.S1_ENVIRONMENTAL: DEFAULT_S1_THRESHOLD,
            OracleStream.S2_MOBILITY:      DEFAULT_S2_THRESHOLD,
            OracleStream.S3_ECONOMIC:      DEFAULT_S3_THRESHOLD,
        }

    def update_threshold(self, stream: OracleStream, threshold: int) -> None:
        """Called by GovernanceChaincode integration when a parameter vote passes."""
        old = self._thresholds[stream]
        self._thresholds[stream] = threshold
        logger.info(f"OracleAggregator: threshold for {stream} updated {old} → {threshold}")

    # ── Public entry points ───────────────────────────────────────────────────

    async def get_s1_consensus(self, lat: float, lng: float) -> ConsensusResult:
        """Fetch and consensus-check all S1 Environmental oracle nodes."""
        from oracle.sources.weather_sources import (
            fetch_openweathermap,
            fetch_imd,
            fetch_accuweather,
            fetch_iot_environmental,
        )

        sources = [
            ("openweathermap", fetch_openweathermap),
            ("imd",            fetch_imd),
            ("accuweather",    fetch_accuweather),
            ("iot_env",        fetch_iot_environmental),
        ]
        readings = await self._fetch_all(sources, OracleStream.S1_ENVIRONMENTAL, lat=lat, lng=lng)
        return await self._consensus_s1(readings)

    async def get_s2_consensus(self, lat: float, lng: float, zone_id: str) -> ConsensusResult:
        """Fetch and consensus-check all S2 Mobility oracle nodes."""
        from oracle.sources.mobility_sources import (
            fetch_osrm,
            fetch_google_mobility,
            fetch_bbmp_sensors,
        )

        sources = [
            ("osrm",            fetch_osrm),
            ("google_mobility", fetch_google_mobility),
            ("bbmp_sensors",    fetch_bbmp_sensors),
        ]
        readings = await self._fetch_all(sources, OracleStream.S2_MOBILITY, lat=lat, lng=lng, zone_id=zone_id)
        return await self._consensus_s2(readings)

    async def get_s3_consensus(self, zone_id: str) -> ConsensusResult:
        """Fetch and consensus-check all S3 Economic oracle nodes."""
        from oracle.sources.economic_sources import (
            fetch_amazon_flex_proxy,
            fetch_dunzo_zomato_proxy,
            fetch_ecommerce_density,
        )

        sources = [
            ("amazon_flex",       fetch_amazon_flex_proxy),
            ("dunzo_zomato",      fetch_dunzo_zomato_proxy),
            ("ecommerce_density", fetch_ecommerce_density),
        ]
        readings = await self._fetch_all(sources, OracleStream.S3_ECONOMIC, zone_id=zone_id)
        return await self._consensus_s3(readings)

    # ── Fetching ──────────────────────────────────────────────────────────────

    async def _fetch_all(
        self,
        sources: list[tuple[str, callable]],
        stream: OracleStream,
        **kwargs,
    ) -> list[OracleReading | FailedOracleReading]:
        """
        Concurrently fetch from all sources. Circuit-breaker: skip OFFLINE sources.
        Returns mixed list of successful OracleReadings and FailedOracleReadings.
        """
        tasks = []
        skipped = []
        for source_id, fetch_fn in sources:
            node_health = self._health.get_node_health(source_id, stream)
            if node_health and node_health.health == NodeHealth.OFFLINE:
                logger.warning(f"OracleAggregator: skipping OFFLINE source {source_id} for {stream}")
                skipped.append(source_id)
                continue
            tasks.append(self._timed_fetch(source_id, stream, fetch_fn, **kwargs))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        readings = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                source_id = sources[i][0]
                logger.warning(f"OracleAggregator: {source_id} raised exception: {result}")
                readings.append(FailedOracleReading(
                    source_id=source_id,
                    stream=stream,
                    error_detail=str(result),
                ))
                self._health.record_failure(source_id, stream)
            else:
                readings.append(result)
                self._health.record_success(
                    result.source_id, stream, latency_ms=result.latency_ms
                )

        # Record skipped as offline in health (no latency penalty, just counts)
        for source_id in skipped:
            readings.append(FailedOracleReading(
                source_id=source_id,
                stream=stream,
                error_detail="Circuit breaker: source marked OFFLINE",
            ))

        return readings

    async def _timed_fetch(
        self,
        source_id: str,
        stream: OracleStream,
        fetch_fn: callable,
        **kwargs,
    ) -> OracleReading:
        """Wrap a source fetch with timing and signature generation."""
        t0 = time.monotonic()
        try:
            raw_data = await fetch_fn(**kwargs)
            latency_ms = (time.monotonic() - t0) * 1000

            reading = OracleReading(
                source_id=source_id,
                stream=stream,
                data=raw_data,
                timestamp=datetime.now(timezone.utc),
                signature=self._sign(source_id, stream, raw_data),
                latency_ms=latency_ms,
                success=True,
            )
            return reading
        except Exception:
            raise

    # ── Signature ─────────────────────────────────────────────────────────────

    def _sign(self, source_id: str, stream: OracleStream, data: dict) -> str:
        """Generate HMAC-SHA256 signature for a reading."""
        payload = json.dumps({
            "source_id": source_id,
            "stream": stream.value,
            "data": data,
        }, sort_keys=True).encode()
        return hmac.new(
            ORACLE_HMAC_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

    def _verify_signature(self, reading: OracleReading) -> bool:
        """Verify that a reading's signature matches its content."""
        expected = self._sign(reading.source_id, reading.stream, reading.data)
        return hmac.compare_digest(expected, reading.signature)

    # ── S1 Consensus ──────────────────────────────────────────────────────────

    async def _consensus_s1(self, readings: list) -> ConsensusResult:
        """
        S1 Environmental: requires 3/4 nodes to produce values within
        S1_AGREEMENT_TOLERANCE_PCT of each other on rainfall, AQI, and temperature.
        """
        stream = OracleStream.S1_ENVIRONMENTAL
        threshold = self._thresholds[stream]

        # Separate successful from failed
        successful = [r for r in readings if r.success and isinstance(r, OracleReading)]
        failed = [r for r in readings if not r.success]

        # Verify signatures — exclude tampered readings
        verified = []
        for r in successful:
            if self._verify_signature(r):
                verified.append(r)
            else:
                logger.error(f"OracleAggregator: INVALID SIGNATURE from {r.source_id} — excluded from consensus")
                failed.append(FailedOracleReading(
                    source_id=r.source_id,
                    stream=stream,
                    error_detail="Signature verification failed — possible tampering",
                ))

        if len(verified) == 0:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.ALL_NODES_FAILED,
                nodes_polled=len(readings),
                nodes_agreed=0,
                threshold_required=threshold,
                failed_sources=[r.source_id for r in readings],
            )

        # Normalise all readings to S1NormalisedReading
        normalised = []
        for r in verified:
            try:
                norm = self._normalise_s1(r)
                normalised.append((r.source_id, norm))
            except Exception as exc:
                logger.warning(f"OracleAggregator: S1 normalisation failed for {r.source_id}: {exc}")
                failed.append(FailedOracleReading(
                    source_id=r.source_id,
                    stream=stream,
                    error_detail=f"Normalisation error: {exc}",
                ))

        if len(normalised) < threshold:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(normalised),
                threshold_required=threshold,
                failed_sources=[r.source_id for r in failed],
                degraded_nodes=self._health.get_degraded_sources(stream),
            )

        # Find agreeing cluster using median as reference
        rainfalls = [n.rainfall_mm_hr for _, n in normalised]
        aqis = [n.aqi for _, n in normalised]
        temps = [n.temperature_c for _, n in normalised]

        median_rain = statistics.median(rainfalls)
        median_aqi  = statistics.median(aqis)
        median_temp = statistics.median(temps)

        agreeing = []
        dissenting = []
        for source_id, norm in normalised:
            rain_ok = self._within_tolerance(norm.rainfall_mm_hr, median_rain, S1_AGREEMENT_TOLERANCE_PCT)
            aqi_ok  = self._within_tolerance(norm.aqi, median_aqi, S1_AGREEMENT_TOLERANCE_PCT)
            temp_ok = self._within_tolerance(norm.temperature_c, median_temp, S1_AGREEMENT_TOLERANCE_PCT)

            if rain_ok and aqi_ok and temp_ok:
                agreeing.append((source_id, norm))
            else:
                dissenting.append(source_id)
                logger.warning(
                    f"OracleAggregator: S1 source {source_id} dissenting — "
                    f"rain={norm.rainfall_mm_hr:.1f}(ref={median_rain:.1f}) "
                    f"aqi={norm.aqi:.0f}(ref={median_aqi:.0f}) "
                    f"temp={norm.temperature_c:.1f}(ref={median_temp:.1f})"
                )

        if len(agreeing) < threshold:
            logger.warning(
                f"OracleAggregator: S1 INSUFFICIENT_CONSENSUS — "
                f"{len(agreeing)}/{len(normalised)} agree, need {threshold}"
            )
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(agreeing),
                threshold_required=threshold,
                agreeing_sources=[s for s, _ in agreeing],
                dissenting_sources=dissenting,
                failed_sources=[r.source_id for r in failed],
            )

        # Aggregate the agreeing readings (median merge)
        agg_rain  = statistics.median([n.rainfall_mm_hr for _, n in agreeing])
        agg_aqi   = statistics.median([n.aqi for _, n in agreeing])
        agg_temp  = statistics.median([n.temperature_c for _, n in agreeing])
        agg_humid = statistics.median([n.humidity for _, n in agreeing])
        agg_wind  = statistics.median([n.wind_speed_mps for _, n in agreeing])

        aggregated = {
            "rainfall_mm_hr": round(agg_rain, 2),
            "aqi":            round(agg_aqi, 1),
            "temperature_c":  round(agg_temp, 1),
            "humidity":       round(agg_humid, 1),
            "wind_speed_mps": round(agg_wind, 2),
            "source":         "oracle_consensus",
            "agreeing_nodes": [s for s, _ in agreeing],
        }

        consensus_ref = self._compute_consensus_ref([r for r in verified if r.source_id in [s for s, _ in agreeing]])

        logger.info(
            f"OracleAggregator: S1 ACCEPTED — "
            f"{len(agreeing)}/{len(readings)} nodes agree. "
            f"rain={agg_rain:.1f}mm aqi={agg_aqi:.0f} temp={agg_temp:.1f}°C"
        )

        return ConsensusResult(
            stream=stream,
            status=ConsensusStatus.ACCEPTED,
            aggregated_value=aggregated,
            agreeing_sources=[s for s, _ in agreeing],
            dissenting_sources=dissenting,
            failed_sources=[r.source_id for r in failed],
            nodes_polled=len(readings),
            nodes_agreed=len(agreeing),
            threshold_required=threshold,
            consensus_ref=consensus_ref,
            readings=verified,
        )

    # ── S2 Consensus ──────────────────────────────────────────────────────────

    async def _consensus_s2(self, readings: list) -> ConsensusResult:
        """S2 Mobility: 2/3 nodes must agree on mobility_index within tolerance."""
        stream = OracleStream.S2_MOBILITY
        threshold = self._thresholds[stream]

        successful = [r for r in readings if r.success and isinstance(r, OracleReading)]
        failed = [r for r in readings if not r.success]
        verified = [r for r in successful if self._verify_signature(r)]

        normalised = []
        for r in verified:
            try:
                norm = self._normalise_s2(r)
                normalised.append((r.source_id, norm))
            except Exception as exc:
                logger.warning(f"OracleAggregator: S2 normalisation failed for {r.source_id}: {exc}")

        if len(normalised) < threshold:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(normalised),
                threshold_required=threshold,
                failed_sources=[r.source_id for r in failed],
            )

        median_mobility = statistics.median([n.mobility_index for _, n in normalised])
        agreeing = [
            (s, n) for s, n in normalised
            if self._within_tolerance(n.mobility_index, median_mobility, S2_AGREEMENT_TOLERANCE_PCT)
        ]
        dissenting = [s for s, n in normalised if s not in [a for a, _ in agreeing]]

        if len(agreeing) < threshold:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(agreeing),
                threshold_required=threshold,
                agreeing_sources=[s for s, _ in agreeing],
                dissenting_sources=dissenting,
                failed_sources=[r.source_id for r in failed],
            )

        agg_mobility = statistics.median([n.mobility_index for _, n in agreeing])
        aggregated = {
            "mobility_index":   round(agg_mobility, 2),
            "source":           "oracle_consensus",
            "agreeing_nodes":   [s for s, _ in agreeing],
        }

        logger.info(
            f"OracleAggregator: S2 ACCEPTED — "
            f"{len(agreeing)}/{len(readings)} nodes agree. mobility_index={agg_mobility:.1f}"
        )

        return ConsensusResult(
            stream=stream,
            status=ConsensusStatus.ACCEPTED,
            aggregated_value=aggregated,
            agreeing_sources=[s for s, _ in agreeing],
            dissenting_sources=dissenting,
            failed_sources=[r.source_id for r in failed],
            nodes_polled=len(readings),
            nodes_agreed=len(agreeing),
            threshold_required=threshold,
            consensus_ref=self._compute_consensus_ref(verified),
        )

    # ── S3 Consensus ──────────────────────────────────────────────────────────

    async def _consensus_s3(self, readings: list) -> ConsensusResult:
        """S3 Economic: 2/3 nodes must agree on order_volume_index within tolerance."""
        stream = OracleStream.S3_ECONOMIC
        threshold = self._thresholds[stream]

        successful = [r for r in readings if r.success and isinstance(r, OracleReading)]
        failed = [r for r in readings if not r.success]
        verified = [r for r in successful if self._verify_signature(r)]

        normalised = []
        for r in verified:
            try:
                norm = self._normalise_s3(r)
                normalised.append((r.source_id, norm))
            except Exception as exc:
                logger.warning(f"OracleAggregator: S3 normalisation failed for {r.source_id}: {exc}")

        if len(normalised) < threshold:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(normalised),
                threshold_required=threshold,
                failed_sources=[r.source_id for r in failed],
            )

        median_orders = statistics.median([n.order_volume_index for _, n in normalised])
        agreeing = [
            (s, n) for s, n in normalised
            if self._within_tolerance(n.order_volume_index, median_orders, S3_AGREEMENT_TOLERANCE_PCT)
        ]
        dissenting = [s for s, n in normalised if s not in [a for a, _ in agreeing]]

        if len(agreeing) < threshold:
            return ConsensusResult(
                stream=stream,
                status=ConsensusStatus.INSUFFICIENT_CONSENSUS,
                nodes_polled=len(readings),
                nodes_agreed=len(agreeing),
                threshold_required=threshold,
                agreeing_sources=[s for s, _ in agreeing],
                dissenting_sources=dissenting,
                failed_sources=[r.source_id for r in failed],
            )

        agg_orders = statistics.median([n.order_volume_index for _, n in agreeing])
        aggregated = {
            "order_volume_index": round(agg_orders, 2),
            "source":             "oracle_consensus",
            "agreeing_nodes":     [s for s, _ in agreeing],
        }

        logger.info(
            f"OracleAggregator: S3 ACCEPTED — "
            f"{len(agreeing)}/{len(readings)} nodes agree. order_volume_index={agg_orders:.1f}"
        )

        return ConsensusResult(
            stream=stream,
            status=ConsensusStatus.ACCEPTED,
            aggregated_value=aggregated,
            agreeing_sources=[s for s, _ in agreeing],
            dissenting_sources=dissenting,
            failed_sources=[r.source_id for r in failed],
            nodes_polled=len(readings),
            nodes_agreed=len(agreeing),
            threshold_required=threshold,
            consensus_ref=self._compute_consensus_ref(verified),
        )

    # ── Normalisation helpers ─────────────────────────────────────────────────

    def _normalise_s1(self, reading: OracleReading) -> S1NormalisedReading:
        """Map a raw source dict to a normalised S1 reading. Handles OWM, IMD, AccuWeather schemas."""
        d = reading.data
        source = reading.source_id

        if source == "openweathermap":
            return S1NormalisedReading(
                rainfall_mm_hr=d.get("rainfall_mm_hr", 0.0),
                temperature_c=d.get("temperature_c", 30.0),
                aqi=d.get("aqi", 100.0),
                humidity=d.get("humidity", 60.0),
                wind_speed_mps=d.get("wind_speed", 5.0),
                description=d.get("description", ""),
                source_id=source,
            )
        elif source == "imd":
            # IMD returns: rainfall_mm (cumulative), temp_c, rh_pct, wind_kmph, aqi_index (1-6)
            imd_aqi_map = {1: 25, 2: 75, 3: 150, 4: 250, 5: 350, 6: 450}
            return S1NormalisedReading(
                rainfall_mm_hr=d.get("rainfall_mm", 0.0),  # IMD reports hourly cumulative
                temperature_c=d.get("temp_c", 30.0),
                aqi=float(imd_aqi_map.get(d.get("aqi_index", 2), 75)),
                humidity=d.get("rh_pct", 60.0),
                wind_speed_mps=d.get("wind_kmph", 15.0) / 3.6,  # kmph → m/s
                source_id=source,
            )
        elif source == "accuweather":
            # AccuWeather: PrecipitationSummary.Past1Hour.Metric.Value, Temperature.Metric.Value
            return S1NormalisedReading(
                rainfall_mm_hr=d.get("precipitation_mm_1h", 0.0),
                temperature_c=d.get("temperature_c", 30.0),
                aqi=d.get("aqi_value", 100.0),  # AccuWeather uses 0-500 directly
                humidity=d.get("relative_humidity", 60.0),
                wind_speed_mps=d.get("wind_speed_ms", 5.0),
                source_id=source,
            )
        elif source == "iot_env":
            # IoT sensors: direct metric readings
            return S1NormalisedReading(
                rainfall_mm_hr=d.get("rain_mm_hr", 0.0),
                temperature_c=d.get("temp_c", 30.0),
                aqi=d.get("aqi", 100.0),
                humidity=d.get("humidity_pct", 60.0),
                wind_speed_mps=d.get("wind_ms", 5.0),
                source_id=source,
            )
        else:
            raise ValueError(f"Unknown S1 source: {source}")

    def _normalise_s2(self, reading: OracleReading) -> S2NormalisedReading:
        d = reading.data
        source = reading.source_id

        if source == "osrm":
            # OSRM: duration ratio vs free-flow → mobility index
            delay_pct = d.get("delay_pct", 0.0)  # 0 = no delay, 100 = full stop
            mobility_index = max(0.0, 100.0 - delay_pct)
            return S2NormalisedReading(
                mobility_index=mobility_index,
                avg_speed_kmh=d.get("avg_speed_kmh"),
                route_delay_pct=delay_pct,
                source_id=source,
            )
        elif source == "google_mobility":
            # Google: mobility_change_pct from baseline (-100 to +100)
            change_pct = d.get("mobility_change_pct", 0.0)
            mobility_index = max(0.0, min(100.0, 100.0 + change_pct))
            return S2NormalisedReading(
                mobility_index=mobility_index,
                congestion_level=d.get("congestion_level"),
                source_id=source,
            )
        elif source == "bbmp_sensors":
            # BBMP: direct mobility_score 0–100
            return S2NormalisedReading(
                mobility_index=d.get("mobility_score", 100.0),
                avg_speed_kmh=d.get("avg_speed_kmh"),
                source_id=source,
            )
        else:
            raise ValueError(f"Unknown S2 source: {source}")

    def _normalise_s3(self, reading: OracleReading) -> S3NormalisedReading:
        d = reading.data
        source = reading.source_id

        if source == "amazon_flex":
            # Amazon Flex proxy: orders_vs_baseline_pct (100 = normal)
            return S3NormalisedReading(
                order_volume_index=d.get("orders_vs_baseline_pct", 100.0),
                active_riders_pct=d.get("active_riders_pct"),
                source_id=source,
            )
        elif source == "dunzo_zomato":
            # Dunzo/Zomato: order_index 0–200 (100 = baseline)
            return S3NormalisedReading(
                order_volume_index=d.get("order_index", 100.0),
                delivery_density=d.get("delivery_density_per_km2"),
                source_id=source,
            )
        elif source == "ecommerce_density":
            # E-commerce density sensor: delivery_density → index
            density = d.get("delivery_density", 1.0)
            baseline_density = d.get("baseline_density", 1.0)
            index = (density / max(baseline_density, 0.001)) * 100
            return S3NormalisedReading(
                order_volume_index=round(index, 2),
                delivery_density=density,
                source_id=source,
            )
        else:
            raise ValueError(f"Unknown S3 source: {source}")

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _within_tolerance(value: float, reference: float, tolerance_pct: float) -> bool:
        """Return True if value is within ±tolerance_pct% of reference."""
        if reference == 0:
            return abs(value) < 0.01  # both effectively zero
        diff_pct = abs(value - reference) / abs(reference) * 100
        return diff_pct <= tolerance_pct

    @staticmethod
    def _compute_consensus_ref(readings: list[OracleReading]) -> str:
        """SHA-256 fingerprint of all agreeing oracle readings concatenated."""
        combined = "".join(sorted(r.content_hash() for r in readings))
        return hashlib.sha256(combined.encode()).hexdigest()


# ─── Singleton ────────────────────────────────────────────────────────────────

_aggregator: Optional[OracleAggregator] = None


def get_aggregator() -> OracleAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = OracleAggregator()
    return _aggregator
