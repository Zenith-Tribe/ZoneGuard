"""
backend/oracle/sources/economic_sources.py — S3 Economic oracle source adapters

Three independent data sources for S3 Economic signals:
  1. Amazon Flex Proxy — scrapes/polls zone-level order availability signals
  2. Dunzo/Zomato Proxy — public API endpoints for delivery activity
  3. E-commerce Density — derived metric from multiple platform activity signals

Each adapter returns a raw dict normalised by the aggregator to S3NormalisedReading.

Contract: async def fetch_*(zone_id: str, **kwargs) -> dict

NOTE: Amazon Flex does not expose a public API. This adapter uses a proxy pattern:
  - An authorised Amazon Flex partner API (if available via AMAZON_FLEX_PROXY_URL)
  - Or a rider-reported signal aggregator (from the app's existing check-in data)
  - Falls back to simulation in dev/test

Env vars:
  AMAZON_FLEX_PROXY_URL   — internal service that proxies Flex order signals
  DUNZO_API_KEY           — Dunzo API key (or Swiggy/Zomato equivalent)
  ZOMATO_API_KEY          — Zomato API key
  ECOMMERCE_DENSITY_URL   — aggregated density signal service
"""

import asyncio
import logging
import os
import random
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

AMAZON_FLEX_PROXY_URL  = os.getenv("AMAZON_FLEX_PROXY_URL", "")
DUNZO_API_KEY          = os.getenv("DUNZO_API_KEY", "")
ZOMATO_API_KEY         = os.getenv("ZOMATO_API_KEY", "")
ECOMMERCE_DENSITY_URL  = os.getenv("ECOMMERCE_DENSITY_URL", "")

# 7-day rolling baselines per zone (seeded from historical data; updated weekly)
# In production these come from the database / Redis cache.
_BASELINE_ORDERS: dict[str, float] = {
    "BLR-CENTRAL":     120.0,
    "BLR-KORAMANGALA": 95.0,
    "BLR-INDIRANAGAR": 85.0,
    "BLR-WHITEFIELD":  110.0,
    "DEFAULT":         100.0,
}


# ─── Amazon Flex Proxy ────────────────────────────────────────────────────────

async def fetch_amazon_flex_proxy(zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Fetch Amazon Flex order activity signals via the internal proxy service.

    The proxy aggregates:
      - Offer availability rate (% of poll windows where offers were available)
      - Active rider count vs expected
      - Estimated package volume index

    These are combined into orders_vs_baseline_pct (100 = normal).

    Falls back to rider check-in data model if proxy is unavailable.
    """
    if not AMAZON_FLEX_PROXY_URL:
        logger.warning("fetch_amazon_flex_proxy: AMAZON_FLEX_PROXY_URL not set, using simulation")
        return _simulated_amazon_flex(zone_id)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(
                f"{AMAZON_FLEX_PROXY_URL}/zone/{zone_id}/activity",
                params={"window_minutes": 60},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

            baseline = _BASELINE_ORDERS.get(zone_id, _BASELINE_ORDERS["DEFAULT"])
            current_orders = data.get("estimated_order_volume", baseline)
            orders_vs_baseline = (current_orders / max(baseline, 1)) * 100

            return {
                "orders_vs_baseline_pct": round(orders_vs_baseline, 2),
                "active_riders_pct":      data.get("active_riders_pct", 100.0),
                "offer_availability_pct": data.get("offer_availability_pct", 100.0),
                "estimated_order_volume": current_orders,
                "zone_id":                zone_id,
                "window_minutes":         60,
            }
        except Exception as exc:
            logger.warning(f"fetch_amazon_flex_proxy: request failed: {exc}")
            raise


def _simulated_amazon_flex(zone_id: str) -> dict:
    baseline = _BASELINE_ORDERS.get(zone_id, 100.0)
    variation = random.uniform(0.4, 1.2)
    current = baseline * variation
    return {
        "orders_vs_baseline_pct": round((current / baseline) * 100, 2),
        "active_riders_pct":      round(random.uniform(30, 110), 1),
        "offer_availability_pct": round(random.uniform(20, 100), 1),
        "estimated_order_volume": round(current, 1),
        "zone_id":                zone_id,
        "window_minutes":         60,
    }


# ─── Dunzo / Zomato Proxy ─────────────────────────────────────────────────────

# Dunzo and Zomato both provide partner APIs for hyperlocal delivery analytics.
# We call both and return a merged index.

DUNZO_BASE  = "https://api.dunzo.in/partner/v1"   # Dunzo Partner API
ZOMATO_BASE = "https://api.zomato.com/v2.1"        # Zomato Public API


async def fetch_dunzo_zomato_proxy(zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Fetch hyperlocal delivery activity from Dunzo and/or Zomato partner APIs.
    Returns a merged order_index (100 = normal baseline activity).

    If both APIs are available, returns their average.
    If only one is available, uses it with a confidence flag.
    Falls back to simulation if neither key is set.
    """
    has_dunzo  = bool(DUNZO_API_KEY)
    has_zomato = bool(ZOMATO_API_KEY)

    if not has_dunzo and not has_zomato:
        logger.warning("fetch_dunzo_zomato_proxy: no API keys set, using simulation")
        return _simulated_dunzo_zomato(zone_id)

    indices = []
    densities = []

    async with httpx.AsyncClient(timeout=12) as client:
        if has_dunzo:
            try:
                dunzo_resp = await client.get(
                    f"{DUNZO_BASE}/analytics/zone",
                    params={"zone_id": zone_id, "granularity": "hourly"},
                    headers={"Authorization": f"Bearer {DUNZO_API_KEY}"},
                )
                if dunzo_resp.status_code == 200:
                    dunzo_data = dunzo_resp.json()
                    index = dunzo_data.get("activity_index", 100.0)  # 0–200 scale
                    density = dunzo_data.get("orders_per_km2", 0.0)
                    indices.append(index)
                    densities.append(density)
                    logger.debug(f"fetch_dunzo_zomato_proxy: Dunzo index={index} for {zone_id}")
            except Exception as exc:
                logger.warning(f"fetch_dunzo_zomato_proxy: Dunzo call failed: {exc}")

        if has_zomato:
            try:
                zomato_resp = await client.get(
                    f"{ZOMATO_BASE}/delivery/zone_activity",
                    params={"zone": zone_id},
                    headers={"user-key": ZOMATO_API_KEY},
                )
                if zomato_resp.status_code == 200:
                    zomato_data = zomato_resp.json()
                    index = zomato_data.get("delivery_index", 100.0)
                    density = zomato_data.get("active_deliveries_per_km2", 0.0)
                    indices.append(index)
                    densities.append(density)
                    logger.debug(f"fetch_dunzo_zomato_proxy: Zomato index={index} for {zone_id}")
            except Exception as exc:
                logger.warning(f"fetch_dunzo_zomato_proxy: Zomato call failed: {exc}")

    if not indices:
        # Both APIs failed despite having keys — raise so aggregator records failure
        raise RuntimeError("Both Dunzo and Zomato API calls failed")

    merged_index = sum(indices) / len(indices)
    merged_density = sum(densities) / len(densities) if densities else 0.0

    return {
        "order_index":              round(merged_index, 2),
        "delivery_density_per_km2": round(merged_density, 4),
        "sources_used":             len(indices),
        "zone_id":                  zone_id,
    }


def _simulated_dunzo_zomato(zone_id: str) -> dict:
    index = random.uniform(20, 160)
    return {
        "order_index":              round(index, 2),
        "delivery_density_per_km2": round(random.uniform(0.5, 8.0), 4),
        "sources_used":             2,
        "zone_id":                  zone_id,
    }


# ─── E-commerce Density ───────────────────────────────────────────────────────

async def fetch_ecommerce_density(zone_id: str = "DEFAULT", **kwargs) -> dict:
    """
    Fetch derived e-commerce delivery density signals.

    This adapter calls an internal aggregation service (ECOMMERCE_DENSITY_URL)
    that combines multiple platform signals into a normalised density score:
      - delivery_density: active deliveries per km² in this zone right now
      - baseline_density: 7-day rolling average at this hour-of-week
      The aggregator computes: order_volume_index = (density / baseline) × 100

    Falls back to simulation if ECOMMERCE_DENSITY_URL is not set.
    This is an [ENHANCEMENT] node — its data is supplementary to Amazon/Dunzo.
    """
    if not ECOMMERCE_DENSITY_URL:
        logger.info("fetch_ecommerce_density: ECOMMERCE_DENSITY_URL not set, using simulation")
        return _simulated_ecommerce_density(zone_id)

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            resp = await client.get(
                f"{ECOMMERCE_DENSITY_URL}/zone/{zone_id}",
                params={"include_baseline": "true"},
            )
            resp.raise_for_status()
            data = resp.json()

            return {
                "delivery_density":   data.get("active_deliveries_per_km2", 1.0),
                "baseline_density":   data.get("baseline_density_per_km2", 1.0),
                "platform_breakdown": data.get("by_platform", {}),
                "zone_id":            zone_id,
                "computed_at":        datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.warning(f"fetch_ecommerce_density: request failed: {exc}")
            raise


def _simulated_ecommerce_density(zone_id: str) -> dict:
    baseline = random.uniform(2.0, 6.0)
    variation = random.uniform(0.3, 1.3)
    density = baseline * variation
    return {
        "delivery_density":   round(density, 4),
        "baseline_density":   round(baseline, 4),
        "platform_breakdown": {"amazon": 0.5, "dunzo": 0.3, "zomato": 0.2},
        "zone_id":            zone_id,
        "computed_at":        datetime.now(timezone.utc).isoformat(),
    }
