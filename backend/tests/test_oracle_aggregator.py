"""Tests for ChainOracle Network — OracleAggregator consensus engine."""

import pytest
from unittest.mock import AsyncMock, patch

from oracle.aggregator import OracleAggregator
from oracle.models import ConsensusStatus, OracleStream


@pytest.fixture
def aggregator():
    """Fresh OracleAggregator instance with a clean health monitor."""
    return OracleAggregator()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _owm_reading(rain=70.0, temp=32.0, aqi=120, humidity=65, wind=5.0):
    """OpenWeatherMap-schema dict."""
    return {
        "rainfall_mm_hr": rain,
        "temperature_c": temp,
        "aqi": aqi,
        "humidity": humidity,
        "wind_speed": wind,
        "description": "heavy rain",
    }


def _imd_reading(rain=72.0, temp=31.5, aqi_index=3, rh=68, wind_kmph=18.0):
    """IMD-schema dict."""
    return {
        "rainfall_mm": rain,
        "temp_c": temp,
        "rh_pct": rh,
        "wind_kmph": wind_kmph,
        "aqi_index": aqi_index,
        "station_id": "BLR-TEST",
        "obs_time": "",
    }


def _accuweather_reading(precip=68.0, temp=33.0, aqi=130, rh=62, wind_ms=4.5):
    """AccuWeather-schema dict."""
    return {
        "precipitation_mm_1h": precip,
        "temperature_c": temp,
        "relative_humidity": rh,
        "wind_speed_ms": wind_ms,
        "aqi_value": aqi,
        "location_key": "TEST",
    }


def _iot_reading(rain=71.0, temp=31.0, aqi=115, humidity=66, wind=4.8):
    """IoT sensor schema dict."""
    return {
        "rain_mm_hr": rain,
        "temp_c": temp,
        "humidity_pct": humidity,
        "aqi": aqi,
        "wind_ms": wind,
        "sensor_id": "TEST-BLR",
        "distance_km": 0,
    }


def _mobility_osrm(delay=40.0, speed=25.0):
    return {"delay_pct": delay, "avg_speed_kmh": speed, "samples": 3, "zone_id": "BLR-TEST"}


def _mobility_google(change=-35.0, congestion=0.35):
    return {"mobility_change_pct": change, "congestion_level": congestion, "duration_s": 1200, "baseline_duration_s": 900}


def _mobility_bbmp(score=62.0, speed=24.0):
    return {"mobility_score": score, "avg_speed_kmh": speed, "vehicle_density": 50, "monitored_junctions": 8, "zone_id": "BLR-TEST"}


def _economic_amazon(orders_pct=85.0, riders_pct=90.0):
    return {"orders_vs_baseline_pct": orders_pct, "active_riders_pct": riders_pct, "zone_id": "BLR-TEST"}


def _economic_dunzo(order_index=82.0, density=3.5):
    return {"order_index": order_index, "delivery_density_per_km2": density, "sources_used": 2, "zone_id": "BLR-TEST"}


def _economic_ecommerce(density=3.0, baseline=3.5):
    return {"delivery_density": density, "baseline_density": baseline, "zone_id": "BLR-TEST"}


def _crowd_data(inactivity=45.0, total=40, inactive=18, response_rate=80.0):
    return {
        "inactivity_pct": inactivity,
        "total_riders": total,
        "inactive_riders": inactive,
        "response_rate": response_rate,
    }


# ─── Test 1: S1 consensus — 3 of 4 agree ────────────────────────────────────

class TestS1Consensus3of4Agree:

    @pytest.mark.asyncio
    async def test_s1_consensus_3_of_4_agree(self, aggregator):
        """
        Mock 4 weather sources returning similar values.
        Verify ConsensusStatus.ACCEPTED when 3+ sources agree within tolerance.
        """
        with (
            patch("oracle.sources.weather_sources.fetch_openweathermap", new_callable=AsyncMock,
                  return_value=_owm_reading(rain=70, temp=32, aqi=120)),
            patch("oracle.sources.weather_sources.fetch_imd", new_callable=AsyncMock,
                  return_value=_imd_reading(rain=72, temp=31.5, aqi_index=3)),
            patch("oracle.sources.weather_sources.fetch_accuweather", new_callable=AsyncMock,
                  return_value=_accuweather_reading(precip=68, temp=33, aqi=130)),
            patch("oracle.sources.weather_sources.fetch_iot_environmental", new_callable=AsyncMock,
                  return_value=_iot_reading(rain=71, temp=31, aqi=115)),
        ):
            result = await aggregator.get_s1_consensus(lat=12.97, lng=77.59)

        assert result.status == ConsensusStatus.ACCEPTED
        assert result.nodes_agreed >= 3
        assert result.aggregated_value is not None
        assert "rainfall_mm_hr" in result.aggregated_value
        assert "aqi" in result.aggregated_value
        assert "temperature_c" in result.aggregated_value
        assert result.consensus_ref is not None


# ─── Test 2: S1 consensus — insufficient (wildly different values) ───────────

class TestS1ConsensusInsufficient:

    @pytest.mark.asyncio
    async def test_s1_consensus_insufficient(self, aggregator):
        """
        Mock 4 sources where values are wildly different from each other.
        Verify INSUFFICIENT_CONSENSUS since <3 can agree within tolerance.
        """
        with (
            patch("oracle.sources.weather_sources.fetch_openweathermap", new_callable=AsyncMock,
                  return_value=_owm_reading(rain=10.0, temp=25.0, aqi=50)),
            patch("oracle.sources.weather_sources.fetch_imd", new_callable=AsyncMock,
                  return_value=_imd_reading(rain=90.0, temp=42.0, aqi_index=6)),
            patch("oracle.sources.weather_sources.fetch_accuweather", new_callable=AsyncMock,
                  return_value=_accuweather_reading(precip=2.0, temp=18.0, aqi=450)),
            patch("oracle.sources.weather_sources.fetch_iot_environmental", new_callable=AsyncMock,
                  return_value=_iot_reading(rain=50.0, temp=35.0, aqi=200)),
        ):
            result = await aggregator.get_s1_consensus(lat=12.97, lng=77.59)

        assert result.status == ConsensusStatus.INSUFFICIENT_CONSENSUS
        assert result.aggregated_value is None


# ─── Test 3: S2 consensus — mobility within tolerance ────────────────────────

class TestS2ConsensusWithinTolerance:

    @pytest.mark.asyncio
    async def test_s2_consensus_within_tolerance(self, aggregator):
        """
        Mock 3 mobility sources returning values within 25% of each other.
        Verify ConsensusStatus.ACCEPTED.
        """
        # OSRM: delay_pct=40 => mobility_index = 100-40 = 60
        # Google: mobility_change_pct=-35 => mobility_index = 100+(-35) = 65
        # BBMP: mobility_score=62 => mobility_index = 62
        # Median ~62, all within 25% of 62
        with (
            patch("oracle.sources.mobility_sources.fetch_osrm", new_callable=AsyncMock,
                  return_value=_mobility_osrm(delay=40.0, speed=25.0)),
            patch("oracle.sources.mobility_sources.fetch_google_mobility", new_callable=AsyncMock,
                  return_value=_mobility_google(change=-35.0, congestion=0.35)),
            patch("oracle.sources.mobility_sources.fetch_bbmp_sensors", new_callable=AsyncMock,
                  return_value=_mobility_bbmp(score=62.0, speed=24.0)),
        ):
            result = await aggregator.get_s2_consensus(lat=12.97, lng=77.59, zone_id="BLR-TEST")

        assert result.status == ConsensusStatus.ACCEPTED
        assert result.nodes_agreed >= 2
        assert result.aggregated_value is not None
        assert "mobility_index" in result.aggregated_value


# ─── Test 4: S3 consensus — circuit breaker on failed source ─────────────────

class TestS3ConsensusCircuitBreaker:

    @pytest.mark.asyncio
    async def test_s3_consensus_circuit_breaker(self, aggregator):
        """
        Mock one source raising an exception, verify it is recorded as failed
        and consensus still works with the remaining 2 sources.
        """
        with (
            patch("oracle.sources.economic_sources.fetch_amazon_flex_proxy", new_callable=AsyncMock,
                  side_effect=RuntimeError("Connection timeout")),
            patch("oracle.sources.economic_sources.fetch_dunzo_zomato_proxy", new_callable=AsyncMock,
                  return_value=_economic_dunzo(order_index=82.0)),
            patch("oracle.sources.economic_sources.fetch_ecommerce_density", new_callable=AsyncMock,
                  return_value=_economic_ecommerce(density=3.0, baseline=3.5)),
        ):
            result = await aggregator.get_s3_consensus(zone_id="BLR-TEST")

        assert result.status == ConsensusStatus.ACCEPTED
        assert result.nodes_agreed >= 2
        assert "amazon_flex" in result.failed_sources
        assert result.aggregated_value is not None
        assert "order_volume_index" in result.aggregated_value


# ─── Test 5: S4 consensus — crowd inactivity_pct aggregation ────────────────

class TestS4ConsensusCrowd:

    @pytest.mark.asyncio
    async def test_s4_consensus_crowd(self, aggregator):
        """
        Mock 3 crowd sources, verify S4_CROWD consensus with inactivity_pct aggregation.
        """
        with (
            patch("oracle.sources.crowd_oracle.fetch_whatsapp_checkins", new_callable=AsyncMock,
                  return_value=_crowd_data(inactivity=45.0, total=40, inactive=18, response_rate=80.0)),
            patch("oracle.sources.crowd_oracle.fetch_flex_app_pulse", new_callable=AsyncMock,
                  return_value=_crowd_data(inactivity=42.0, total=40, inactive=17, response_rate=90.0)),
            patch("oracle.sources.crowd_oracle.fetch_manual_survey", new_callable=AsyncMock,
                  return_value=_crowd_data(inactivity=48.0, total=40, inactive=19, response_rate=60.0)),
        ):
            result = await aggregator.get_s4_consensus(zone_id="BLR-TEST")

        assert result.stream == OracleStream.S4_CROWD
        assert result.status == ConsensusStatus.ACCEPTED
        assert result.nodes_agreed >= 2
        assert result.aggregated_value is not None
        assert "inactivity_pct" in result.aggregated_value
        assert "inactive_riders" in result.aggregated_value
        assert "total_riders" in result.aggregated_value
        # All 3 values (42, 45, 48) are within 15% of the median (45),
        # so all 3 should agree
        assert result.nodes_agreed == 3


# ─── Test 6: Signature verification rejects tampered data ────────────────────

class TestSignatureVerification:

    def test_signature_verification_rejects_tampered(self, aggregator):
        """
        Create an OracleReading with a valid signature, then modify the data.
        Verify _verify_signature returns False for the tampered reading.
        """
        from oracle.models import OracleReading, OracleStream
        from datetime import datetime, timezone

        source_id = "openweathermap"
        stream = OracleStream.S1_ENVIRONMENTAL
        original_data = {"rainfall_mm_hr": 70.0, "temperature_c": 32.0, "aqi": 120}

        # Generate a valid signature
        valid_signature = aggregator._sign(source_id, stream, original_data)

        reading = OracleReading(
            source_id=source_id,
            stream=stream,
            data=original_data,
            timestamp=datetime.now(timezone.utc),
            signature=valid_signature,
            latency_ms=50.0,
            success=True,
        )

        # Verify the original reading passes
        assert aggregator._verify_signature(reading) is True

        # Tamper with the data
        tampered_data = {"rainfall_mm_hr": 0.0, "temperature_c": 25.0, "aqi": 50}
        tampered_reading = OracleReading(
            source_id=source_id,
            stream=stream,
            data=tampered_data,
            timestamp=reading.timestamp,
            signature=valid_signature,  # same signature, different data
            latency_ms=50.0,
            success=True,
        )

        # Verify the tampered reading fails
        assert aggregator._verify_signature(tampered_reading) is False
