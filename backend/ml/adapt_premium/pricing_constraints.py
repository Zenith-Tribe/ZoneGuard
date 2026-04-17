"""
pricing_constraints.py — IRDAI Floor/Ceiling Enforcement and Fairness Bands.

IRDAI (Insurance Regulatory and Development Authority of India) Compliance:
  • Minimum premium floor: ₹39 (low tier) — cannot go below
  • Maximum premium ceiling: ₹225 (flood-prone tier)
  • Maximum weekly adjustment: ±15% per decision step
  • Maximum 4-week cumulative change: ±30%
  • Fairness constraint: no individual rider's premium can exceed the zone
    average by more than 25% (prevents adverse risk profiling)

Rider-level pricing (secondary objective):
  Within IRDAI fairness bands, riders can receive personalised premiums
  based on tenure, claim history, and telematics.

  Personalisation delta: ±20% around zone premium (within IRDAI band).
  Protected attributes (NO differential pricing allowed):
    • Gender, religion, caste, language, region of origin
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IRDAI Constants
# ---------------------------------------------------------------------------

PREMIUM_FLOOR_INR = 39.0        # ₹39 absolute minimum
PREMIUM_CEILING_INR = 225.0     # ₹225 absolute maximum
MAX_SINGLE_STEP_DELTA = 0.15    # ±15% per weekly step
MAX_4WEEK_CUMULATIVE = 0.30     # ±30% over 4 weeks
RIDER_FAIRNESS_BAND = 0.25      # rider premium ≤ zone_avg × 1.25

# Approved tier breaks (these define valid price points for new tier buckets)
APPROVED_PREMIUM_TIERS = [39, 89, 139, 225]


# ---------------------------------------------------------------------------
# IRDAIConstraints
# ---------------------------------------------------------------------------

class IRDAIConstraints:
    """
    Validates and enforces IRDAI premium adjustment constraints.

    Usage:
        constraints = IRDAIConstraints(zone_type="flood-prone")
        safe_delta, was_clipped = constraints.validate_delta(
            current_premium=139.0, proposed_delta=0.20  # would be clipped to 0.15
        )
    """

    def __init__(self, zone_type: str = "medium") -> None:
        self.zone_type = zone_type
        self._weekly_deltas: list[float] = []   # rolling 4-week history
        self._violation_log: list[dict] = []

    def validate_delta(
        self,
        current_premium: float,
        proposed_delta: float,
    ) -> tuple[float, bool]:
        """
        Validate a proposed premium change delta against IRDAI rules.

        Args:
            current_premium:  Current zone premium in ₹.
            proposed_delta:   Proposed fractional change (e.g. 0.10 = +10%).

        Returns:
            (safe_delta, was_clipped)
              safe_delta:   Validated delta (may be reduced or zeroed).
              was_clipped:  True if the proposed delta was modified.
        """
        original_delta = proposed_delta
        clipped = False

        # Rule 1: Single-step cap
        if abs(proposed_delta) > MAX_SINGLE_STEP_DELTA:
            proposed_delta = MAX_SINGLE_STEP_DELTA * (1 if proposed_delta > 0 else -1)
            clipped = True
            self._log_violation("single_step_cap", original_delta, proposed_delta)

        # Rule 2: 4-week cumulative cap
        recent_4w = self._weekly_deltas[-3:] + [proposed_delta]
        cumulative = sum(recent_4w)
        if abs(cumulative) > MAX_4WEEK_CUMULATIVE:
            # Clip proposed_delta so cumulative stays within band
            prior_sum = sum(self._weekly_deltas[-3:])
            remaining = MAX_4WEEK_CUMULATIVE * (1 if proposed_delta > 0 else -1) - prior_sum
            if abs(remaining) < abs(proposed_delta):
                proposed_delta = remaining
                clipped = True
                self._log_violation("4week_cumulative_cap", original_delta, proposed_delta)

        # Rule 3: Absolute floor/ceiling
        new_premium = current_premium * (1.0 + proposed_delta)
        if new_premium < PREMIUM_FLOOR_INR:
            proposed_delta = (PREMIUM_FLOOR_INR / current_premium) - 1.0
            clipped = True
            self._log_violation("floor_breach", original_delta, proposed_delta)
        elif new_premium > PREMIUM_CEILING_INR:
            proposed_delta = (PREMIUM_CEILING_INR / current_premium) - 1.0
            clipped = True
            self._log_violation("ceiling_breach", original_delta, proposed_delta)

        # Record this week's delta
        self._weekly_deltas.append(proposed_delta)
        if len(self._weekly_deltas) > 52:  # keep 1 year of history
            self._weekly_deltas.pop(0)

        if clipped:
            logger.debug(
                "IRDAIConstraints[%s]: delta clipped %.3f → %.3f",
                self.zone_type, original_delta, proposed_delta,
            )

        return round(proposed_delta, 4), clipped

    def _log_violation(
        self, rule: str, original: float, adjusted: float
    ) -> None:
        self._violation_log.append({
            "rule": rule,
            "original_delta": round(original, 4),
            "adjusted_delta": round(adjusted, 4),
        })

    def get_violation_summary(self) -> dict:
        """Return constraint violation statistics for audit log."""
        from collections import Counter
        counts = Counter(v["rule"] for v in self._violation_log)
        return {
            "total_violations": len(self._violation_log),
            "by_rule": dict(counts),
            "recent_5": self._violation_log[-5:],
        }

    def reset_history(self) -> None:
        """Reset weekly history (call at start of each episode)."""
        self._weekly_deltas = []


# ---------------------------------------------------------------------------
# Rider-level personalised pricing
# ---------------------------------------------------------------------------

class RiderPricingEngine:
    """
    Compute personalised rider-level premiums within IRDAI fairness bands.

    Personalisation factors (ALL must be risk-based, not demographic):
      +  tenure_bonus:     riders > 52 weeks get up to -10% discount
      +  claim_loading:    riders with 2+ claims in 90 days get up to +15% loading
      +  velocity_loading: claim velocity 7d > 2 → +10% loading
      -  Protected:        gender, religion, caste, language, origin → NEVER used
    """

    TENURE_DISCOUNT_WEEKS = 52       # Tenure for max discount
    MAX_TENURE_DISCOUNT = 0.10       # 10% discount for established riders
    MAX_CLAIM_LOADING = 0.15         # 15% loading for frequent claimers
    MAX_VELOCITY_LOADING = 0.10      # 10% loading for recent high velocity
    FAIRNESS_CAP = RIDER_FAIRNESS_BAND  # 25% above zone average max

    def calculate_rider_premium(
        self,
        zone_premium: float,
        tenure_weeks: int,
        claims_90d: int,
        claim_velocity_7d: int,
        rider_id: Optional[str] = None,
    ) -> dict:
        """
        Compute a personalised premium for a single rider.

        Args:
            zone_premium:     Current zone base premium (₹).
            tenure_weeks:     Rider's tenure in weeks.
            claims_90d:       Number of claims in last 90 days.
            claim_velocity_7d: Claims in last 7 days.
            rider_id:         For logging only (not used in pricing logic).

        Returns:
            Dict with personalised_premium, adjustment, factors, fairness_compliant.
        """
        adjustment = 0.0
        factors: list[str] = []

        # Tenure discount
        tenure_ratio = min(1.0, tenure_weeks / self.TENURE_DISCOUNT_WEEKS)
        tenure_discount = -tenure_ratio * self.MAX_TENURE_DISCOUNT
        adjustment += tenure_discount
        if tenure_discount < -0.02:
            factors.append(f"tenure_discount={tenure_discount*100:.1f}%")

        # Claim loading
        if claims_90d >= 2:
            claim_load = min(self.MAX_CLAIM_LOADING, (claims_90d - 1) * 0.05)
            adjustment += claim_load
            factors.append(f"claim_loading=+{claim_load*100:.1f}%")

        # Velocity loading
        if claim_velocity_7d > 2:
            vel_load = min(self.MAX_VELOCITY_LOADING, (claim_velocity_7d - 2) * 0.03)
            adjustment += vel_load
            factors.append(f"velocity_loading=+{vel_load*100:.1f}%")

        # Apply adjustment
        personalised = zone_premium * (1.0 + adjustment)

        # IRDAI Fairness cap: cannot exceed zone_premium × (1 + FAIRNESS_CAP)
        fairness_ceiling = zone_premium * (1.0 + self.FAIRNESS_CAP)
        fairness_compliant = personalised <= fairness_ceiling
        if not fairness_compliant:
            personalised = fairness_ceiling
            factors.append(f"fairness_cap_applied (max={fairness_ceiling:.0f})")
            logger.debug("RiderPricingEngine: fairness cap applied for rider %s.", rider_id)

        # Absolute floor/ceiling
        personalised = float(max(PREMIUM_FLOOR_INR, min(PREMIUM_CEILING_INR, personalised)))

        return {
            "zone_premium": round(zone_premium, 2),
            "personalised_premium": round(personalised, 2),
            "adjustment_pct": round(adjustment * 100, 2),
            "factors": factors,
            "fairness_compliant": fairness_compliant,
            "irdai_floor": PREMIUM_FLOOR_INR,
            "irdai_ceiling": PREMIUM_CEILING_INR,
        }
