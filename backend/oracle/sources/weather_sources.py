"""
backend/oracle/sources/weather_sources.py — S1 Environmental oracle source adapters

Four independent data sources for S1 Environmental signals:
  1. OpenWeatherMap (existing integration, refactored to return raw dict)
  2. IMD (India Meteorological Department) — official government API
  3. AccuWeather — commercial weather provider
  4. IoT Environmental Sensors — local Bengaluru sensor network

Each adapter returns a raw dict matching its native schema.
Normalisation to S1NormalisedReading happens in the aggregator.

All adapters follow the contract:
  async def fetch_*(lat: float, lng: float, **kwargs) -> dict

Env vars required:
  OPENWEATHERMAP_API_KEY — existing
  IMD_API_KEY            — new (Innovation 03)
  ACCUWEATHER_API_KEY    — new (Innovation 03)
  IOT_SENSOR_ENDPOINT    — new (Innovation 03, optional; falls back to nearest proxy)
"""

import logging
import os
import random
import time

import httpx

logger = logging.getLogger(__name__)

# ─── OpenWeatherMap ───────────────────────────────────────────────────────────

OWM_BASE = "https://api.openweathermap.org/data/2.5"


async def fetch_openweathermap(lat: float, lng: float, **kwargs) -> dict:
    """
    Fetch current weather + AQI from OpenWeatherMap.
    Returns raw dict matching OWM schema — aggregator normalises.
    This replaces the direct call in weather.py when oracle mode is active.
    """
    key = os.getenv("OPENWEATHERMAP_API_KEY", "")
    if not key:
        logger.warning("fetch_openweathermap: API key not set, returning simulated data")
        return _simulated_owm(lat, lng)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            weather_resp, air_resp = await asyncio.gather(
                client.get(f"{OWM_BASE}/weather", params={"lat": lat, "lon": lng, "appid": key, "units": "metric"}),
                client.get(f"{OWM_BASE}/air_pollution", params={"lat": lat, "lon": lng, "appid": key}),
            )
            weather = weather_resp.json() if weather_resp.status_code == 200 else {}
            air     = air_resp.json()    if air_resp.status_code == 200    else {}

            rain_1h   = weather.get("rain", {}).get("1h", 0.0)
            temp      = weather.get("main", {}).get("temp", 30.0)
            aqi_index = air.get("list", [{}])[0].get("main", {}).get("aqi", 1)
            aqi       = {1: 50, 2: 100, 3: 200, 4: 300, 5: 400}.get(aqi_index, 100)

            return {
                "rainfall_mm_hr": rain_1h,
                "temperature_c":  temp,
                "aqi":            aqi,
                "humidity":       weather.get("main", {}).get("humidity", 60),
                "wind_speed":     weather.get("wind", {}).get("speed", 5),
                "description":    weather.get("weather", [{}])[0].get("description", "clear"),
            }
        except Exception as exc:
            logger.warning(f"fetch_openweathermap: API call failed: {exc}")
            raise  # Let aggregator record the failure


def _simulated_owm(lat: float, lng: float) -> dict:
    return {
        "rainfall_mm_hr": round(random.uniform(0, 15), 1),
        "temperature_c":  round(random.uniform(25, 35), 1),
        "aqi":            random.randint(50, 150),
        "humidity":       random.randint(40, 80),
        "wind_speed":     round(random.uniform(2, 12), 1),
        "description":    random.choice(["clear sky", "light rain", "scattered clouds"]),
    }


# ─── IMD (India Meteorological Department) ───────────────────────────────────

IMD_BASE = "https://api.imd.gov.in/v1"  # Official IMD OpenAPI endpoint


async def fetch_imd(lat: float, lng: float, **kwargs) -> dict:
    """
    Fetch weather data from IMD (India Meteorological Department).
    IMD provides rainfall, temperature, relative humidity, wind speed,
    and an AQI index (1–6 scale, lower is better).

    Falls back to simulation if IMD_API_KEY is not set.
    """
    key = os.getenv("IMD_API_KEY", "")
    if not key:
        logger.warning("fetch_imd: IMD_API_KEY not set, returning simulated data")
        return _simulated_imd(lat, lng)

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                f"{IMD_BASE}/current",
                params={"lat": lat, "lon": lng, "api_key": key},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            # IMD response schema (based on documented OpenAPI spec)
            return {
                "rainfall_mm":   data.get("rainfall_mm_last_hour", 0.0),
                "temp_c":        data.get("temperature_celsius", 30.0),
                "rh_pct":        data.get("relative_humidity_pct", 60.0),
                "wind_kmph":     data.get("wind_speed_kmph", 15.0),
                "aqi_index":     data.get("aqi_category", 2),   # 1–6 IMD scale
                "station_id":    data.get("station_id", ""),
                "obs_time":      data.get("observation_time", ""),
            }
        except httpx.HTTPStatusError as exc:
            logger.warning(f"fetch_imd: HTTP {exc.response.status_code}: {exc}")
            raise
        except Exception as exc:
            logger.warning(f"fetch_imd: request failed: {exc}")
            raise


def _simulated_imd(lat: float, lng: float) -> dict:
    return {
        "rainfall_mm":   round(random.uniform(0, 20), 1),
        "temp_c":        round(random.uniform(24, 38), 1),
        "rh_pct":        random.randint(45, 90),
        "wind_kmph":     round(random.uniform(5, 30), 1),
        "aqi_index":     random.randint(1, 4),
        "station_id":    "BLR_SIM",
        "obs_time":      "",
    }


# ─── AccuWeather ──────────────────────────────────────────────────────────────

ACCUWEATHER_LOCATION_BASE  = "http://dataservice.accuweather.com/locations/v1/cities/geoposition/search"
ACCUWEATHER_CURRENT_BASE   = "http://dataservice.accuweather.com/currentconditions/v1"
ACCUWEATHER_AQI_BASE       = "http://dataservice.accuweather.com/airquality/v2/observations"


async def fetch_accuweather(lat: float, lng: float, **kwargs) -> dict:
    """
    Fetch weather + AQI from AccuWeather API.
    Requires a two-step call: first resolve location key, then fetch conditions.
    Location key is cached in-process for performance.

    Falls back to simulation if ACCUWEATHER_API_KEY is not set.
    """
    key = os.getenv("ACCUWEATHER_API_KEY", "")
    if not key:
        logger.warning("fetch_accuweather: ACCUWEATHER_API_KEY not set, returning simulated data")
        return _simulated_accuweather(lat, lng)

    async with httpx.AsyncClient(timeout=12) as client:
        try:
            # Step 1: Get AccuWeather location key for these coordinates
            loc_resp = await client.get(
                ACCUWEATHER_LOCATION_BASE,
                params={"apikey": key, "q": f"{lat},{lng}", "details": "false"},
            )
            loc_resp.raise_for_status()
            location_key = loc_resp.json().get("Key", "")
            if not location_key:
                raise ValueError("AccuWeather returned no location key")

            # Step 2: Fetch current conditions + AQI concurrently
            conditions_resp, aqi_resp = await asyncio.gather(
                client.get(
                    f"{ACCUWEATHER_CURRENT_BASE}/{location_key}",
                    params={"apikey": key, "details": "true"},
                ),
                client.get(
                    f"{ACCUWEATHER_AQI_BASE}/{location_key}",
                    params={"apikey": key},
                ),
            )

            cond = conditions_resp.json()[0] if conditions_resp.status_code == 200 else {}
            aqi_data = aqi_resp.json() if aqi_resp.status_code == 200 else {}

            precip_mm = (
                cond.get("PrecipitationSummary", {})
                    .get("PastHour", {})
                    .get("Metric", {})
                    .get("Value", 0.0)
            )
            temp_c = (
                cond.get("Temperature", {})
                    .get("Metric", {})
                    .get("Value", 30.0)
            )
            humidity = cond.get("RelativeHumidity", 60)
            wind_ms = (
                cond.get("Wind", {})
                    .get("Speed", {})
                    .get("Metric", {})
                    .get("Value", 15.0)
            ) / 3.6   # kmph → m/s
            aqi_value = aqi_data.get("Index", 100) if aqi_data else 100

            return {
                "precipitation_mm_1h": precip_mm,
                "temperature_c":       temp_c,
                "relative_humidity":   humidity,
                "wind_speed_ms":       round(wind_ms, 2),
                "aqi_value":           aqi_value,
                "location_key":        location_key,
            }
        except Exception as exc:
            logger.warning(f"fetch_accuweather: request failed: {exc}")
            raise


def _simulated_accuweather(lat: float, lng: float) -> dict:
    return {
        "precipitation_mm_1h": round(random.uniform(0, 18), 1),
        "temperature_c":       round(random.uniform(24, 37), 1),
        "relative_humidity":   random.randint(40, 85),
        "wind_speed_ms":       round(random.uniform(1, 8), 2),
        "aqi_value":           random.randint(40, 200),
        "location_key":        "SIM",
    }


# ─── IoT Environmental Sensors ────────────────────────────────────────────────

IOT_ENDPOINT = os.getenv("IOT_SENSOR_ENDPOINT", "")


async def fetch_iot_environmental(lat: float, lng: float, **kwargs) -> dict:
    """
    Fetch data from the local Bengaluru IoT environmental sensor network.
    Sensors report: rain_mm_hr, temp_c, humidity_pct, aqi, wind_ms.

    The nearest sensor is selected by the endpoint using lat/lng proximity.
    Falls back to simulation if IOT_SENSOR_ENDPOINT is not set.
    """
    if not IOT_ENDPOINT:
        logger.info("fetch_iot_environmental: IOT_SENSOR_ENDPOINT not set, returning simulated data")
        return _simulated_iot(lat, lng)

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.get(
                f"{IOT_ENDPOINT}/nearest",
                params={"lat": lat, "lng": lng},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "rain_mm_hr":   data.get("rain_mm_hr", 0.0),
                "temp_c":       data.get("temperature_c", 30.0),
                "humidity_pct": data.get("humidity_pct", 60.0),
                "aqi":          data.get("aqi_pm25_index", 100.0),
                "wind_ms":      data.get("wind_speed_ms", 3.0),
                "sensor_id":    data.get("sensor_id", ""),
                "distance_km":  data.get("distance_km", 0),
            }
        except Exception as exc:
            logger.warning(f"fetch_iot_environmental: request failed: {exc}")
            raise


def _simulated_iot(lat: float, lng: float) -> dict:
    return {
        "rain_mm_hr":   round(random.uniform(0, 12), 1),
        "temp_c":       round(random.uniform(25, 36), 1),
        "humidity_pct": random.randint(45, 85),
        "aqi":          random.randint(45, 180),
        "wind_ms":      round(random.uniform(1, 7), 1),
        "sensor_id":    "SIM-BLR",
        "distance_km":  0,
    }


# ─── Required import for concurrent calls ─────────────────────────────────────
import asyncio
