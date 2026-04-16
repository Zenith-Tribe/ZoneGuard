"""
ZoneTwin — Per-zone lightweight counterfactual simulation.

Uses historical baselines to answer:
"At this rainfall level, how many riders historically went dark?"

Returns (p10, p50, p90) expected inactivity percentiles for grounding
fraud checks and claim validation.

Phase 3 Update: Added Predictive Hedge Bot logic for Sunday-night 
disruption forecasting.
"""

import random
import math


# Historical baselines per zone (simulated from IMD + rider data)
ZONE_BASELINES = {
    "hsr": {
        "avg_rainfall_mm": 28, "avg_mobility": 88, "avg_inactivity_pct": 8,
        "disruption_rainfall_threshold": 55, "flood_correlation": 0.82,
    },
    "koramangala": {
        "avg_rainfall_mm": 25, "avg_mobility": 91, "avg_inactivity_pct": 6,
        "disruption_rainfall_threshold": 58, "flood_correlation": 0.75,
    },
    "whitefield": {
        "avg_rainfall_mm": 18, "avg_mobility": 93, "avg_inactivity_pct": 4,
        "disruption_rainfall_threshold": 70, "flood_correlation": 0.45,
    },
    "indiranagar": {
        "avg_rainfall_mm": 22, "avg_mobility": 90, "avg_inactivity_pct": 7,
        "disruption_rainfall_threshold": 60, "flood_correlation": 0.68,
    },
    "electronic-city": {
        "avg_rainfall_mm": 20, "avg_mobility": 92, "avg_inactivity_pct": 5,
        "disruption_rainfall_threshold": 65, "flood_correlation": 0.52,
    },
    "bellandur": {
        "avg_rainfall_mm": 35, "avg_mobility": 78, "avg_inactivity_pct": 15,
        "disruption_rainfall_threshold": 45, "flood_correlation": 0.94,
    },
    "btm-layout": {
        "avg_rainfall_mm": 30, "avg_mobility": 84, "avg_inactivity_pct": 10,
        "disruption_rainfall_threshold": 50, "flood_correlation": 0.80,
    },
    "jp-nagar": {
        "avg_rainfall_mm": 27, "avg_mobility": 86, "avg_inactivity_pct": 9,
        "disruption_rainfall_threshold": 52, "flood_correlation": 0.77,
    },
    "yelahanka": {
        "avg_rainfall_mm": 15, "avg_mobility": 95, "avg_inactivity_pct": 3,
        "disruption_rainfall_threshold": 72, "flood_correlation": 0.35,
    },
    "hebbal": {
        "avg_rainfall_mm": 26, "avg_mobility": 85, "avg_inactivity_pct": 11,
        "disruption_rainfall_threshold": 54, "flood_correlation": 0.78,
    },
}


def counterfactual_inactivity(zone_id: str, rainfall_mm: float, aqi: float = 100) -> dict:
    """
    Given current conditions, estimate expected rider inactivity
    based on historical zone behavior.

    Returns p10/p50/p90 percentiles for expected inactivity %.
    """
    baseline = ZONE_BASELINES.get(zone_id, ZONE_BASELINES["hsr"])

    # How severe is current rainfall relative to zone's disruption threshold?
    rainfall_ratio = rainfall_mm / max(baseline["disruption_rainfall_threshold"], 1)

    # Logistic curve: maps rainfall_ratio to expected inactivity multiplier
    # At ratio=1 (threshold), expect ~40-50% inactivity
    # At ratio=2 (2x threshold), expect ~70-80% inactivity
    base_inactivity = baseline["avg_inactivity_pct"]
    multiplier = 1 + (baseline["flood_correlation"] * 10 * (1 / (1 + math.exp(-3 * (rainfall_ratio - 0.8)))))

    # AQI contribution
    if aqi > 300:
        multiplier += 0.5
    elif aqi > 200:
        multiplier += 0.2

    expected_median = min(90, base_inactivity * multiplier)

    # Simulate percentile spread based on zone's historical variance
    variance = max(5, expected_median * 0.25)
    p10 = max(0, round(expected_median - 1.28 * variance, 1))
    p50 = round(expected_median, 1)
    p90 = min(100, round(expected_median + 1.28 * variance, 1))

    return {
        "zone_id": zone_id,
        "conditions": {"rainfall_mm": rainfall_mm, "aqi": aqi},
        "expected_inactivity": {"p10": p10, "p50": p50, "p90": p90},
        "historical_baseline": {
            "avg_inactivity_pct": baseline["avg_inactivity_pct"],
            "disruption_threshold_mm": baseline["disruption_rainfall_threshold"],
            "flood_correlation": baseline["flood_correlation"],
        },
        "interpretation": _interpret(p50, rainfall_mm, baseline),
    }


def _interpret(expected_pct: float, rainfall: float, baseline: dict) -> str:
    if expected_pct > 50:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, historically {expected_pct:.0f}% of riders "
            f"went dark in this zone. This is consistent with a major disruption event."
        )
    elif expected_pct > 25:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, historically {expected_pct:.0f}% of riders "
            f"reported inactivity. Moderate disruption expected."
        )
    else:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, only {expected_pct:.0f}% rider inactivity "
            f"expected historically. Current conditions are within normal range."
        )


def get_predictive_hedge_opportunity(zone_id: str) -> dict:
    """
    Phase 3: Sunday-night predictive nudge logic.
    Analyzes upcoming 72-hour forecast trends to allow riders to 'lock' 
    earnings protection before a high-probability disruption.
    """
    # Simulate high-confidence predictive forecast for demo purposes
    # In production, this would pull from a Monday-recalc Prophet/XGB model.
    prob = random.uniform(0.68, 0.92) 
    
    return {
        "zone_id": zone_id,
        "disruption_probability": round(prob, 2),
        "hedge_recommended": prob > 0.6,
        "lock_premium_multiplier": 0.85,  # 15% discount for locking early
        "payout_guarantee_multiplier": 1.1, # 10% bonus for pre-emptive hedging
        "message": f"Phase 3 Predictive Alert: {zone_id} has a {int(prob*100)}% flood risk this Wednesday. Lock earnings now?",
        "timestamp": "2026-03-22T21:00:00Z"
    }
