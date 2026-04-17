# MERGED BY SESSION 7 — Patches from sessions: 4
# Session 4 adds: get_rl_recommendation(), _get_or_create_rl_agent(), _rl_agent_cache
# Existing calculate_risk_score() and calculate_zone_premium() are UNCHANGED.

"""
ZoneRisk Scorer — Weighted rule-based risk model.

5 factors with transparent weights:
- disruption_freq (35%): historical disruption frequency for the zone
- imd_forecast (25%): IMD seasonal forecast severity
- rider_tenure (15%): rider's tenure in weeks (lower = higher risk)
- zone_class (15%): zone classification risk level
- claim_history (10%): recent claim volume for the zone

Output: risk score 0-100 → premium tier (₹39/₹89/₹139/₹225)
"""

PREMIUM_TIERS = {
    (0, 30): {"premium": 39, "tier": "low", "max_payout": 1430},
    (30, 55): {"premium": 89, "tier": "medium", "max_payout": 4290},
    (55, 75): {"premium": 139, "tier": "high", "max_payout": 7150},
    (75, 101): {"premium": 225, "tier": "flood-prone", "max_payout": 11440},
}

ZONE_CLASS_SCORES = {
    "low": 20,
    "medium": 50,
    "high": 70,
    "flood-prone": 90,
}


def calculate_risk_score(
    disruption_freq: int,
    imd_forecast_severity: float,
    rider_tenure_weeks: int,
    zone_classification: str,
    recent_claims_7d: int,
    total_zone_riders: int,
) -> dict:
    """Calculate zone risk score with full factor breakdown."""

    disrupt_score = min(100, (disruption_freq / 10) * 100)
    imd_score = min(100, imd_forecast_severity)
    tenure_score = max(0, 100 - (min(rider_tenure_weeks, 52) / 52 * 100))
    zone_score = ZONE_CLASS_SCORES.get(zone_classification, 50)
    claim_rate = (recent_claims_7d / max(total_zone_riders, 1)) * 100
    claim_score = min(100, claim_rate * 10)

    weights = {
        "disruption_freq": 0.35,
        "imd_forecast": 0.25,
        "rider_tenure": 0.15,
        "zone_class": 0.15,
        "claim_history": 0.10,
    }

    scores = {
        "disruption_freq": disrupt_score,
        "imd_forecast": imd_score,
        "rider_tenure": tenure_score,
        "zone_class": zone_score,
        "claim_history": claim_score,
    }

    total_score = sum(scores[k] * weights[k] for k in weights)
    total_score = round(min(100, max(0, total_score)))

    tier_info = {"premium": 49, "tier": "medium", "max_payout": 2200}
    for (low, high), info in PREMIUM_TIERS.items():
        if low <= total_score < high:
            tier_info = info
            break

    factor_breakdown = {}
    for k in weights:
        contribution = round(scores[k] * weights[k], 1)
        factor_breakdown[k] = {
            "weight": weights[k],
            "raw_score": round(scores[k], 1),
            "contribution": contribution,
            "contribution_inr": round(contribution * tier_info["premium"] / 100, 1),
        }

    return {
        "risk_score": total_score,
        "premium": tier_info["premium"],
        "tier": tier_info["tier"],
        "max_payout": tier_info["max_payout"],
        "factor_breakdown": factor_breakdown,
    }


def calculate_zone_premium(zone_data: dict, rider_tenure_weeks: int = 0) -> dict:
    """Convenience function for zone-based premium calculation."""
    return calculate_risk_score(
        disruption_freq=zone_data.get("historical_disruptions", 3),
        imd_forecast_severity=zone_data.get("imd_severity", 40),
        rider_tenure_weeks=rider_tenure_weeks,
        zone_classification=zone_data.get("risk_tier", "medium"),
        recent_claims_7d=zone_data.get("recent_claims", 2),
        total_zone_riders=zone_data.get("active_riders", 100),
    )


# ======================================================================
# Session 4 — AdaptPremium PPO (Innovation 13) shadow mode wrapper
# ======================================================================

def get_rl_recommendation(
    zone_data: dict,
    rider_tenure_weeks: int = 0,
    loss_ratios_4w: list | None = None,
    churn_rate: float = 0.05,
    enrolled_riders: int = 100,
    imd_seasonal: float = 0.5,
    pool_funded_ratio: float = 1.2,
) -> dict:
    """
    Run the AdaptPremium PPO agent alongside the existing rule-based scorer
    in shadow mode and log the comparison.

    When ADAPT_PREMIUM_SHADOW_MODE=true (default):
      - Existing rule-based premium is returned unchanged.
      - RL recommendation is appended under `rl_shadow_recommendation`.

    When ADAPT_PREMIUM_SHADOW_MODE=false:
      - RL premium replaces rule-based premium with IRDAI constraints enforced.

    Args:
        zone_data:            Dict passed to calculate_zone_premium().
        rider_tenure_weeks:   Rider's tenure (for personalisation).
        loss_ratios_4w:       4-week rolling loss ratio history.
        churn_rate:           Current weekly churn rate.
        enrolled_riders:      Enrolled rider count.
        imd_seasonal:         IMD 90-day forecast severity (0-1).
        pool_funded_ratio:    Pool balance / expected annual claims.

    Returns:
        Result dict from calculate_zone_premium() with optional
        `rl_shadow_recommendation` field appended.
    """
    import os
    import logging

    logger = logging.getLogger(__name__)

    rule_based_result = calculate_zone_premium(zone_data, rider_tenure_weeks)

    try:
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent

        zone_id = zone_data.get("zone_id", "unknown")
        zone_type = zone_data.get("risk_tier", "medium")
        current_premium = float(rule_based_result["premium"])

        agent = _get_or_create_rl_agent(zone_id, zone_type, current_premium)

        recommendation = agent.get_recommendation(
            zone_data=zone_data,
            rider_tenure_weeks=rider_tenure_weeks,
            loss_ratios_4w=loss_ratios_4w,
            churn_rate=churn_rate,
            enrolled_riders=enrolled_riders,
            imd_seasonal=imd_seasonal,
            pool_funded_ratio=pool_funded_ratio,
        )

        shadow_mode = os.getenv("ADAPT_PREMIUM_SHADOW_MODE", "true").lower() == "true"

        if shadow_mode:
            rule_based_result["rl_shadow_recommendation"] = recommendation.get(
                "rl_shadow_recommendation", {}
            )
            logger.info(
                "get_rl_recommendation[%s]: shadow comparison — "
                "rule=₹%.0f rl=₹%.0f delta=%s%%",
                zone_id,
                rule_based_result["premium"],
                recommendation.get("rl_shadow_recommendation", {}).get("recommended_premium", current_premium),
                recommendation.get("rl_shadow_recommendation", {}).get("delta_pct", 0),
            )
            return rule_based_result
        else:
            return recommendation

    except ImportError:
        logger.warning(
            "get_rl_recommendation: AdaptPremium not available "
            "(stable-baselines3 not installed). Returning rule-based result."
        )
        return rule_based_result
    except Exception as e:
        logger.error(
            "get_rl_recommendation: unexpected error (%s). "
            "Returning rule-based result.", e
        )
        return rule_based_result


# Module-level RL agent cache — one per zone, initialised lazily
_rl_agent_cache: dict = {}


def _get_or_create_rl_agent(
    zone_id: str,
    zone_type: str,
    initial_premium: float,
) -> object:
    """Retrieve or create a cached AdaptPremiumAgent for a zone."""
    import os

    if zone_id not in _rl_agent_cache:
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent
        agent = AdaptPremiumAgent(
            zone_id=zone_id,
            zone_type=zone_type,
            initial_premium=initial_premium,
        )
        model_path = os.getenv("PPO_MODEL_PATH", "/models/adapt_ppo")
        agent.load(f"{model_path}/{zone_id}_ppo")
        _rl_agent_cache[zone_id] = agent

    return _rl_agent_cache[zone_id]
