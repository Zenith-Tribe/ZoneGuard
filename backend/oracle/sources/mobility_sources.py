"""
backend/oracle/sources/mobility_sources.py — S2 Mobility oracle source adapters

Three independent data sources for S2 Mobility signals:
  1. OSRM (Open Source Routing Machine) — route duration analysis
  2. Google Maps Mobility API — real-time congestion & mobility index
  3. BBMP Traffic Sensors — Bengaluru city traffic sensor network

Each adapter returns a raw dict normalised by the aggregator to S2NormalisedReading.

Contract: async def fetch_*(lat: float, lng: float, zone_id: str, **kwargs) -> dict

Env vars required:
  OSRM_ENDPOINT          — existing (mobility.py was empty, so we define the base here)
  GOOGLE_MOBILITY_API_KEY — new (Innovation 03)
  BBMP_SENSOR_ENDPOINT    — new (Innovation 03, optional; falls back to simulation)
"""

import asyncio
import logging
import os
import random
import time

import httpx

logger = logging.getLogger(__name__)

# ─── Zone bounding boxes for Bengaluru delivery zones ────────────────────────
# Used to construct OSRM route samples across the zone area.
# Format: zone_id → (min_lat, min_lng, max_lat, max_lng)
ZONE_BOUNDS: dict[str, tuple] = {
    "BLR-CENTRAL":   (12.970, 77.580, 12.990, 77.610),
    "BLR-KORAMANGALA": (12.920, 77.610, 12.940, 77.640),
    "BLR-INDIRANAGAR": (12.970, 77.630, 12.990, 77.660),
    "BLR-WHITEFIELD": (12.960, 77.730, 12.990, 77.760),
    "DEFAULT":        (12.900, 77.550, 13.050, 77.700),
}

OSRM_ENDPOINT          = os.getenv("OSRM_ENDPOINT", "http://router.project-osrm.org")
GOOGLE_MOBILITY_KEY    = os.getenv("GOOGLE_MOBILITY_API_KEY", "")
BBMP_ENDPOINT          = os.getenv("BBMP_SENSOR_ENDPOINT", "")


# ─── OSRM ────────────────────────────────────────────────────────────────────

async def fetch_osrm(lat: float, lng: float, zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Compute mobility index from OSRM route durations vs. free-flow baseline.

    Strategy: sample N reference routes within the zone bounding box.
    Compare current duration with OSRM's free-flow estimate (using shortest vs fastest).
    delay_pct = ((current_duration - free_flow_duration) / free_flow_duration) × 100
    mobility_index = 100 - delay_pct (clamped 0–100)

    Falls back to simulation if OSRM endpoint is unreachable.
    """
    bounds = ZONE_BOUNDS.get(zone_id, ZONE_BOUNDS["DEFAULT"])
    min_lat, min_lng, max_lat, max_lng = bounds

    # Sample 3 representative routes across the zone
    sample_routes = [
        # (origin_lat, origin_lng, dest_lat, dest_lng)
        (min_lat, min_lng, max_lat, max_lng),
        (min_lat + (max_lat - min_lat) * 0.3, min_lng, max_lat, min_lng + (max_lng - min_lng) * 0.7),
        (min_lat, min_lng + (max_lng - min_lng) * 0.3, max_lat, max_lng),
    ]

    async with httpx.AsyncClient(timeout=12) as client:
        delay_pcts = []
        speeds = []

        for orig_lat, orig_lng, dest_lat, dest_lng in sample_routes:
            try:
                # OSRM route endpoint: returns duration + distance
                route_resp = await client.get(
                    f"{OSRM_ENDPOINT}/route/v1/driving/{orig_lng},{orig_lat};{dest_lng},{dest_lat}",
                    params={"overview": "false", "alternatives": "false"},
                )
                if route_resp.status_code != 200:
                    continue

                route_data = route_resp.json()
                routes = route_data.get("routes", [])
                if not routes:
                    continue

                current_duration = routes[0].get("duration", 0)  # seconds
                distance_m       = routes[0].get("distance", 1)  # meters

                if current_duration <= 0 or distance_m <= 0:
                    continue

                # Free-flow speed for Bengaluru urban: ~40 kmph
                free_flow_speed_ms = 40 / 3.6
                free_flow_duration = distance_m / free_flow_speed_ms

                delay_pct = ((current_duration - free_flow_duration) / max(free_flow_duration, 1)) * 100
                delay_pct = max(0.0, min(100.0, delay_pct))
                delay_pcts.append(delay_pct)

                # Avg speed from this route
                avg_speed_ms = distance_m / max(current_duration, 1)
                speeds.append(avg_speed_ms * 3.6)  # → kmph

            except Exception as exc:
                logger.warning(f"fetch_osrm: route sample failed: {exc}")
                continue

        if not delay_pcts:
            logger.warning("fetch_osrm: all route samples failed, using simulation")
            return _simulated_osrm(zone_id)

        avg_delay = sum(delay_pcts) / len(delay_pcts)
        avg_speed = sum(speeds) / len(speeds) if speeds else 25.0
        mobility_index = max(0.0, 100.0 - avg_delay)

        return {
            "delay_pct":     round(avg_delay, 2),
            "avg_speed_kmh": round(avg_speed, 1),
            "mobility_index_computed": round(mobility_index, 2),  # for reference; aggregator normalises
            "samples":       len(delay_pcts),
            "zone_id":       zone_id,
        }


def _simulated_osrm(zone_id: str) -> dict:
    delay = random.uniform(0, 60)
    return {
        "delay_pct":     round(delay, 2),
        "avg_speed_kmh": round(random.uniform(10, 45), 1),
        "samples":       3,
        "zone_id":       zone_id,
    }


# ─── Google Maps Mobility ─────────────────────────────────────────────────────

GOOGLE_PLACES_BASE = "https://maps.googleapis.com/maps/api"


async def fetch_google_mobility(lat: float, lng: float, zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Fetch real-time mobility data from Google Maps Platform.

    Uses the Distance Matrix API to compute travel time ratio between
    current conditions and historical baseline (departure_time=now vs best_guess).
    The ratio is converted to a mobility_change_pct.

    Falls back to simulation if GOOGLE_MOBILITY_API_KEY is not set.
    """
    if not GOOGLE_MOBILITY_KEY:
        logger.warning("fetch_google_mobility: GOOGLE_MOBILITY_API_KEY not set, using simulation")
        return _simulated_google_mobility(lat, lng)

    bounds = ZONE_BOUNDS.get(zone_id, ZONE_BOUNDS["DEFAULT"])
    min_lat, min_lng, max_lat, max_lng = bounds
    centre_lat = (min_lat + max_lat) / 2
    centre_lng = (min_lng + max_lng) / 2

    # Sample origin → centre and centre → edge
    origins      = f"{lat},{lng}"
    destinations = f"{centre_lat},{centre_lng}"

    async with httpx.AsyncClient(timeout=12) as client:
        try:
            resp = await client.get(
                f"{GOOGLE_PLACES_BASE}/distancematrix/json",
                params={
                    "origins":          origins,
                    "destinations":     destinations,
                    "key":              GOOGLE_MOBILITY_KEY,
                    "departure_time":   "now",
                    "traffic_model":    "best_guess",
                    "mode":             "driving",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            elements = data.get("rows", [{}])[0].get("elements", [{}])
            elem = elements[0] if elements else {}

            if elem.get("status") != "OK":
                raise ValueError(f"Google API element status: {elem.get('status')}")

            duration_in_traffic = elem.get("duration_in_traffic", {}).get("value", 0)  # seconds
            duration_baseline   = elem.get("duration", {}).get("value", 1)             # seconds

            if duration_baseline <= 0:
                raise ValueError("Zero baseline duration from Google")

            # mobility_change_pct: negative means slower than baseline
            delay_ratio = (duration_in_traffic - duration_baseline) / duration_baseline
            mobility_change_pct = -delay_ratio * 100  # positive = faster, negative = congested

            # Google congestion: duration ratio as proxy
            congestion_level = min(1.0, max(0.0, delay_ratio))

            return {
                "mobility_change_pct": round(mobility_change_pct, 2),
                "congestion_level":    round(congestion_level, 4),
                "duration_s":          duration_in_traffic,
                "baseline_duration_s": duration_baseline,
                "zone_id":             zone_id,
            }
        except Exception as exc:
            logger.warning(f"fetch_google_mobility: request failed: {exc}")
            raise


def _simulated_google_mobility(lat: float, lng: float) -> dict:
    change = random.uniform(-60, 10)
    return {
        "mobility_change_pct": round(change, 2),
        "congestion_level":    round(random.uniform(0, 0.8), 4),
        "duration_s":          random.randint(600, 2400),
        "baseline_duration_s": 900,
    }


# ─── BBMP Traffic Sensors ─────────────────────────────────────────────────────

async def fetch_bbmp_sensors(lat: float, lng: float, zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Fetch real-time traffic data from BBMP (Bruhat Bengaluru Mahanagara Palike)
    traffic sensor network.

    BBMP sensors are installed at major junctions and report:
      - mobility_score (0–100): direct mobility index
      - avg_speed_kmh: average vehicle speed at monitored junctions
      - vehicle_density: vehicles per km of road

    Falls back to simulation if BBMP_SENSOR_ENDPOINT is not set.
    Note: BBMP sensor API is under development; this adapter uses the documented
    prototype spec from Bengaluru Smart City project.
    """
    if not BBMP_ENDPOINT:
        logger.info("fetch_bbmp_sensors: BBMP_SENSOR_ENDPOINT not set, using simulation")
        return _simulated_bbmp(zone_id)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{BBMP_ENDPOINT}/zone/{zone_id}/mobility",
                params={"lat": lat, "lng": lng},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "mobility_score":    data.get("mobility_score", 100.0),
                "avg_speed_kmh":     data.get("avg_speed_kmh", 30.0),
                "vehicle_density":   data.get("vehicles_per_km", 0),
                "monitored_junctions": data.get("junction_count", 0),
                "zone_id":           zone_id,
                "sensor_timestamp":  data.get("timestamp", ""),
            }
        except Exception as exc:
            logger.warning(f"fetch_bbmp_sensors: request failed: {exc}")
            raise


def _simulated_bbmp(zone_id: str) -> dict:
    score = random.uniform(20, 100)
    return {
        "mobility_score":      round(score, 1),
        "avg_speed_kmh":       round(score * 0.4, 1),
        "vehicle_density":     random.randint(10, 80),
        "monitored_junctions": random.randint(3, 12),
        "zone_id":             zone_id,
        "sensor_timestamp":    "",
    }
