"""
backend/oracle/sources/crowd_oracle.py — S4 Crowd oracle source adapters

Three independent data sources for S4 Crowd signals:
  1. WhatsApp Business API — rider check-in aggregation
  2. Amazon Flex App In-App Pulse — Flex platform rider activity
  3. Manual Survey / ZoneGuard App — self-reported inactivity

Each adapter returns a raw dict matching its native schema.
Normalisation to S4NormalisedReading happens in the aggregator.

All adapters follow the contract:
  async def fetch_*(zone_id: str, **kwargs) -> dict

Env vars:
  WHATSAPP_BUSINESS_API_KEY — WhatsApp Business Cloud API key
  FLEX_APP_API_KEY           — Amazon Flex partner API key
  (manual_survey is always simulated for hackathon)
"""

import logging
import os
import random

import httpx

logger = logging.getLogger(__name__)

WHATSAPP_BUSINESS_API_KEY = os.getenv("WHATSAPP_BUSINESS_API_KEY", "")
FLEX_APP_API_KEY          = os.getenv("FLEX_APP_API_KEY", "")

# ─── Zone rider baselines ────────────────────────────────────────────────────
# Expected total riders per zone (seeded from historical data; updated weekly)
# In production these come from the database / Redis cache.
_BASELINE_RIDERS: dict[str, int] = {
    "BLR-CENTRAL":     45,
    "BLR-KORAMANGALA": 35,
    "BLR-INDIRANAGAR": 30,
    "BLR-WHITEFIELD":  40,
    "DEFAULT":         38,
}

WHATSAPP_BUSINESS_BASE = "https://graph.facebook.com/v18.0"
FLEX_APP_BASE          = "https://flex.amazon.in/partner/v1"


# ─── WhatsApp Business API ───────────────────────────────────────────────────

async def fetch_whatsapp_checkins(zone_id: str, **kwargs) -> dict:
    """
    Fetch rider check-in aggregation via WhatsApp Business Cloud API.

    Riders respond to automated WhatsApp check-in prompts with a simple
    "active" / "inactive" reply. This adapter polls the check-in aggregation
    endpoint to get zone-level inactivity stats.

    Returns:
      inactive_riders, total_riders, inactivity_pct, response_rate,
      checkin_window_minutes, source

    Falls back to simulation if WHATSAPP_BUSINESS_API_KEY is not set.
    """
    if not WHATSAPP_BUSINESS_API_KEY:
        logger.warning("fetch_whatsapp_checkins: WHATSAPP_BUSINESS_API_KEY not set, returning simulated data")
        return _simulated_whatsapp(zone_id)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{WHATSAPP_BUSINESS_BASE}/checkin/aggregate",
                params={"zone_id": zone_id, "window_minutes": 30},
                headers={
                    "Authorization": f"Bearer {WHATSAPP_BUSINESS_API_KEY}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            total = data.get("total_riders", 0)
            inactive = data.get("inactive_count", 0)
            responded = data.get("responded_count", total)

            inactivity_pct = (inactive / max(total, 1)) * 100
            response_rate = (responded / max(total, 1)) * 100

            return {
                "inactive_riders":        inactive,
                "total_riders":           total,
                "inactivity_pct":         round(inactivity_pct, 2),
                "response_rate":          round(response_rate, 2),
                "checkin_window_minutes": data.get("window_minutes", 30),
                "source":                 "whatsapp_business",
            }
        except Exception as exc:
            logger.warning(f"fetch_whatsapp_checkins: request failed: {exc}")
            raise


def _simulated_whatsapp(zone_id: str) -> dict:
    rng = random.Random(hash(zone_id) % 2**32)
    total = _BASELINE_RIDERS.get(zone_id, _BASELINE_RIDERS["DEFAULT"])
    # Normal conditions: 10-25% inactivity; disruption: 40-80%
    inactivity_pct = rng.uniform(10, 25)
    inactive = int(round(total * inactivity_pct / 100))
    response_rate = rng.uniform(65, 95)

    return {
        "inactive_riders":        inactive,
        "total_riders":           total,
        "inactivity_pct":         round(inactivity_pct, 2),
        "response_rate":          round(response_rate, 2),
        "checkin_window_minutes": 30,
        "source":                 "whatsapp_business",
    }


# ─── Amazon Flex App In-App Pulse ────────────────────────────────────────────

async def fetch_flex_app_pulse(zone_id: str, **kwargs) -> dict:
    """
    Fetch rider activity pulse from the Amazon Flex in-app platform.

    The Flex app tracks rider states: online (idle), delivering, or offline.
    A rider is considered "inactive" if they are offline during operating hours
    (6am-10pm window). This adapter calls the Flex partner analytics endpoint
    for zone-level activity breakdown.

    Returns:
      inactive_riders, total_riders, inactivity_pct, online_riders,
      delivering_riders, source

    Falls back to simulation if FLEX_APP_API_KEY is not set.
    """
    if not FLEX_APP_API_KEY:
        logger.warning("fetch_flex_app_pulse: FLEX_APP_API_KEY not set, returning simulated data")
        return _simulated_flex_pulse(zone_id)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{FLEX_APP_BASE}/zone/{zone_id}/rider-activity",
                params={"window_minutes": 60},
                headers={
                    "X-Api-Key": FLEX_APP_API_KEY,
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

            total = data.get("total_riders", 0)
            online = data.get("online_riders", 0)
            delivering = data.get("delivering_riders", 0)
            inactive = max(0, total - online - delivering)

            inactivity_pct = (inactive / max(total, 1)) * 100

            return {
                "inactive_riders":    inactive,
                "total_riders":       total,
                "inactivity_pct":     round(inactivity_pct, 2),
                "online_riders":      online,
                "delivering_riders":  delivering,
                "source":             "flex_app_pulse",
            }
        except Exception as exc:
            logger.warning(f"fetch_flex_app_pulse: request failed: {exc}")
            raise


def _simulated_flex_pulse(zone_id: str) -> dict:
    rng = random.Random(hash(zone_id) % 2**32)
    total = _BASELINE_RIDERS.get(zone_id, _BASELINE_RIDERS["DEFAULT"])
    # Normal conditions: 10-25% inactivity; disruption: 40-80%
    inactivity_pct = rng.uniform(10, 25)
    inactive = int(round(total * inactivity_pct / 100))
    # Distribute active riders between online (idle) and delivering
    active = total - inactive
    delivering = int(round(active * rng.uniform(0.4, 0.7)))
    online = active - delivering

    return {
        "inactive_riders":    inactive,
        "total_riders":       total,
        "inactivity_pct":     round(inactivity_pct, 2),
        "online_riders":      online,
        "delivering_riders":  delivering,
        "source":             "flex_app_pulse",
    }


# ─── Manual Survey / ZoneGuard App ───────────────────────────────────────────

async def fetch_manual_survey(zone_id: str, **kwargs) -> dict:
    """
    Fetch self-reported inactivity data from the ZoneGuard app's manual survey.

    Riders voluntarily report their work status through the app. Responses are
    aggregated per zone over a rolling 60-minute window. Each response includes
    a confidence score (1-5) indicating how certain the rider is about zone-wide
    conditions (not just personal inactivity).

    This adapter is always simulated for the hackathon — no external API needed.

    Returns:
      inactive_riders, total_riders, inactivity_pct, survey_responses,
      avg_confidence, source
    """
    logger.info(f"fetch_manual_survey: returning simulated survey data for zone {zone_id}")
    return _simulated_manual_survey(zone_id)


def _simulated_manual_survey(zone_id: str) -> dict:
    rng = random.Random(hash(zone_id) % 2**32)
    total = _BASELINE_RIDERS.get(zone_id, _BASELINE_RIDERS["DEFAULT"])
    # Surveys typically have lower response rates
    survey_responses = int(round(total * rng.uniform(0.3, 0.7)))
    # Normal conditions: 10-25% inactivity; disruption: 40-80%
    inactivity_pct = rng.uniform(10, 25)
    inactive = int(round(total * inactivity_pct / 100))
    avg_confidence = round(rng.uniform(3.0, 4.8), 1)

    return {
        "inactive_riders":  inactive,
        "total_riders":     total,
        "inactivity_pct":   round(inactivity_pct, 2),
        "survey_responses": survey_responses,
        "avg_confidence":   avg_confidence,
        "source":           "manual_survey",
    }


# ─── Required import for concurrent calls ─────────────────────────────────────
import asyncio
