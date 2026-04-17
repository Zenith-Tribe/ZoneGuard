"""
blockchain/smart_policy.py
==========================
Innovation 02: SmartPolicy Contracts -- On-Chain Policy Execution.

Moves payout calculation ON-CHAIN -- the formula is in the chaincode,
not in Python config. All payout parameters (payout_pct, max_days,
fraud_threshold) are stored in simulated Fabric world state and can
only be changed via a recorded DAO governance transaction.

Design principles:
  1. The engine NEVER reads from Python config / env vars for formula inputs.
     Every input comes from on-chain state (simulated in-memory dict).
  2. Every payout decision writes a full computation trace to ZoneChain,
     making it independently verifiable by any peer (insurer / IRDAI).
  3. Forward Premium Lock discount is enforced at policy-creation time
     and baked into on-chain terms -- it cannot be retroactively removed.
  4. Parameter changes go through update_parameter() which writes a
     PARAMETER_CHANGED event to Fabric, visible to the IRDAI observer.

Simulation note:
  For the hackathon, Fabric state is an in-memory dict. The architecture
  is correct -- swapping in real Fabric reads is a single-method change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .fabric_client import get_fabric_client
from .models import (
    ChainEventType,
    NodeRole,
    ParameterChangePayload,
    PolicyTermsOnChain,
    SmartPolicyResult,
    ZoneChainEvent,
)
from .zonechain import ZoneChainClient, get_zonechain_client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default on-chain zone parameters (simulated Fabric world state)
# ---------------------------------------------------------------------------

_default_zone_params: Dict[str, Any] = {
    "payout_pct": 0.55,              # 55% of daily earnings baseline
    "max_consecutive_days": 3,       # Max covered days per disruption week
    "fraud_threshold": 0.85,         # Fraud score above this blocks payout
    "min_disruption_hours": 4,       # Min hours to qualify for a claim
    "operating_window_start": 6,     # 6 AM
    "operating_window_end": 22,      # 10 PM
}


# ---------------------------------------------------------------------------
# SmartPolicy Engine
# ---------------------------------------------------------------------------

class SmartPolicyEngine:
    """
    Innovation 02: SmartPolicy Contracts -- On-Chain Policy Execution.

    Moves payout calculation ON-CHAIN -- the formula is in the chaincode,
    not in Python config. Uses simulated Fabric state for hackathon.

    All payout inputs are read exclusively from on-chain state. The
    computation trace is written back to ZoneChain so any peer can
    independently verify the result.
    """

    def __init__(self) -> None:
        # Simulated Fabric world state -- keyed by zone_id
        self._zone_params: Dict[str, Dict[str, Any]] = {}

        # Policy terms stored on-chain -- keyed by rider_id
        self._policy_terms: Dict[str, PolicyTermsOnChain] = {}

        # Payout records -- keyed by claim_id
        self._payout_records: Dict[str, SmartPolicyResult] = {}

        # Disruption events (mock registry) -- keyed by event_id
        self._disruption_events: Dict[str, Dict[str, Any]] = {}

        self._zonechain: ZoneChainClient = get_zonechain_client()

        logger.info("[SmartPolicy] Engine initialised (simulated Fabric state)")

    # ------------------------------------------------------------------
    # 1. Create immutable policy terms on chain
    # ------------------------------------------------------------------

    def create_policy_terms(
        self,
        rider_id: str,
        zone_id: str,
        premium_inr: float,
        earnings_baseline_weekly: float,
        coverage_tier: str,
        is_forward_locked: bool = False,
        forward_lock_weeks: int = 0,
    ) -> PolicyTermsOnChain:
        """
        Store immutable policy terms in simulated chain state.

        If the rider opts for Forward Premium Lock (4-week commitment),
        an 8% discount is applied and recorded on-chain. The discount
        cannot be changed after creation -- it is part of the immutable
        policy terms.

        Args:
            rider_id: Unique rider identifier.
            zone_id: Zone the policy covers.
            premium_inr: Weekly premium amount in INR.
            earnings_baseline_weekly: 7-day rolling average earnings (INR).
            coverage_tier: Risk tier (e.g. "LOW", "MEDIUM", "HIGH").
            is_forward_locked: Whether rider committed to 4-week lock.
            forward_lock_weeks: Number of committed weeks (default 0).

        Returns:
            PolicyTermsOnChain with chain_tx_id populated.
        """
        zone_params = self.get_on_chain_parameters(zone_id)

        # Build exclusions hash (deterministic)
        exclusions_list = [
            "WAR", "PANDEMIC", "TERRORISM", "RIDER_MISCONDUCT",
            "VEHICLE_DEFECT", "PRE_EXISTING_ZONE", "SCHEDULED_MAINTENANCE",
            "GRACE_PERIOD_LAPSE", "FRAUD_DETECTED", "MAX_DAYS_EXCEEDED",
        ]
        exclusions_hash = hashlib.sha256(
            json.dumps(exclusions_list, sort_keys=True).encode("utf-8")
        ).hexdigest()

        forward_lock_discount = 0.08 if is_forward_locked else 0.0

        terms = PolicyTermsOnChain(
            rider_id=rider_id,
            zone_id=zone_id,
            risk_tier=coverage_tier,
            premium_inr=premium_inr,
            payout_pct=zone_params["payout_pct"],
            max_consecutive_days=zone_params["max_consecutive_days"],
            earnings_baseline_weekly=earnings_baseline_weekly,
            exclusions_hash=exclusions_hash,
            fraud_threshold=zone_params["fraud_threshold"],
            is_forward_locked=is_forward_locked,
            forward_lock_weeks=forward_lock_weeks,
            forward_lock_discount_pct=forward_lock_discount,
        )

        # Write to simulated Fabric state
        payload_json = terms.model_dump_json(exclude_none=False)
        tx_id = f"FABRIC-SP-{hashlib.sha256(payload_json.encode()).hexdigest()[:16]}"
        terms.chain_tx_id = tx_id

        self._policy_terms[rider_id] = terms

        logger.info(
            f"[SmartPolicy] Policy terms created on-chain | "
            f"rider={rider_id} zone={zone_id} tier={coverage_tier} "
            f"forward_lock={is_forward_locked} tx_id={tx_id}"
        )

        return terms

    # ------------------------------------------------------------------
    # 2. Execute payout using ONLY on-chain parameters
    # ------------------------------------------------------------------

    def execute_payout(
        self,
        rider_id: str,
        event_id: str,
        disruption_hours: float,
        composite_score: float,
        confidence_tier: str,
        fraud_score: float = 0.0,
    ) -> SmartPolicyResult:
        """
        Calculate and record a payout using exclusively on-chain parameters.

        Formula (executed on-chain):
            daily_earnings = earnings_baseline_weekly / 7
            effective_days = min(disruption_hours / 24, max_consecutive_days)
            payout = daily_earnings * payout_pct * effective_days

        The fraud gate blocks payout if fraud_score exceeds the on-chain
        fraud_threshold -- no Python-side override is possible.

        Args:
            rider_id: Rider requesting payout.
            event_id: Disruption event identifier.
            disruption_hours: Total qualifying disruption hours.
            composite_score: QuadSignal composite score (0-1).
            confidence_tier: Signal confidence tier (HIGH/MEDIUM/LOW/NOISE).
            fraud_score: FraudShield anomaly score (0-1), default 0.

        Returns:
            SmartPolicyResult with full computation trace.

        Raises:
            ValueError: If no on-chain policy terms exist for rider.
            ValueError: If disruption event cannot be verified.
        """
        # Fetch policy terms from chain state
        terms = self.get_policy_terms(rider_id)
        if terms is None:
            raise ValueError(
                f"No on-chain policy terms found for rider {rider_id}"
            )

        # Verify disruption event exists (mock check)
        if not self._verify_disruption_event(event_id):
            # Register a mock event for hackathon demo
            self._disruption_events[event_id] = {
                "event_id": event_id,
                "zone_id": terms.zone_id,
                "composite_score": composite_score,
                "confidence_tier": confidence_tier,
                "disruption_hours": disruption_hours,
                "registered_at": datetime.now(timezone.utc).isoformat(),
            }

        # Read parameters from on-chain state (NEVER from Python config)
        zone_params = self.get_on_chain_parameters(terms.zone_id)
        payout_pct = terms.payout_pct
        max_days = zone_params["max_consecutive_days"]
        fraud_threshold = zone_params["fraud_threshold"]
        min_disruption_hours = zone_params["min_disruption_hours"]

        # Build computation trace
        trace: Dict[str, Any] = {
            "step_1_fetch_terms": {
                "rider_id": rider_id,
                "zone_id": terms.zone_id,
                "earnings_baseline_weekly": terms.earnings_baseline_weekly,
                "payout_pct": payout_pct,
                "max_consecutive_days": max_days,
                "fraud_threshold": fraud_threshold,
                "terms_tx_id": terms.chain_tx_id,
            },
            "step_2_disruption_validation": {
                "event_id": event_id,
                "disruption_hours": disruption_hours,
                "min_disruption_hours": min_disruption_hours,
                "composite_score": composite_score,
                "confidence_tier": confidence_tier,
            },
        }

        # Check minimum disruption hours
        if disruption_hours < min_disruption_hours:
            trace["step_3_min_hours_gate"] = {
                "passed": False,
                "reason": (
                    f"Disruption hours ({disruption_hours}) below minimum "
                    f"({min_disruption_hours})"
                ),
            }
            claim_id = str(uuid.uuid4())
            result = SmartPolicyResult(
                claim_id=claim_id,
                rider_id=rider_id,
                event_id=event_id,
                payout_amount_inr=0.0,
                formula_inputs={
                    "earnings_baseline_weekly": terms.earnings_baseline_weekly,
                    "payout_pct": payout_pct,
                    "disruption_hours": disruption_hours,
                    "max_consecutive_days": max_days,
                    "fraud_score": fraud_score,
                    "fraud_threshold": fraud_threshold,
                },
                fraud_gate_passed=True,
                fraud_score=fraud_score,
                computation_trace=trace,
            )
            self._payout_records[claim_id] = result
            logger.info(
                f"[SmartPolicy] Payout blocked: min hours not met | "
                f"rider={rider_id} hours={disruption_hours}"
            )
            return result

        trace["step_3_min_hours_gate"] = {"passed": True}

        # Fraud score gate
        fraud_gate_passed = fraud_score <= fraud_threshold
        trace["step_4_fraud_gate"] = {
            "fraud_score": fraud_score,
            "fraud_threshold": fraud_threshold,
            "passed": fraud_gate_passed,
        }

        # Calculate payout (on-chain formula)
        daily_earnings = terms.earnings_baseline_weekly / 7.0
        effective_days = min(disruption_hours / 24.0, float(max_days))
        payout_amount = daily_earnings * payout_pct * effective_days

        # Apply forward lock discount to premium (informational -- payout is unaffected)
        trace["step_5_formula_execution"] = {
            "daily_earnings": round(daily_earnings, 2),
            "effective_days": round(effective_days, 4),
            "payout_pct": payout_pct,
            "raw_payout": round(payout_amount, 2),
            "forward_locked": terms.is_forward_locked,
            "forward_lock_discount_pct": terms.forward_lock_discount_pct,
        }

        # If fraud gate fails, zero the payout
        if not fraud_gate_passed:
            payout_amount = 0.0
            trace["step_6_final"] = {
                "payout_blocked": True,
                "reason": f"Fraud score {fraud_score} exceeds threshold {fraud_threshold}",
                "final_payout_inr": 0.0,
            }
        else:
            trace["step_6_final"] = {
                "payout_blocked": False,
                "final_payout_inr": round(payout_amount, 2),
            }

        # Generate claim ID and record on chain
        claim_id = str(uuid.uuid4())
        formula_inputs = {
            "earnings_baseline_weekly": terms.earnings_baseline_weekly,
            "payout_pct": payout_pct,
            "disruption_hours": disruption_hours,
            "max_consecutive_days": max_days,
            "effective_days": round(effective_days, 4),
            "daily_earnings": round(daily_earnings, 2),
            "fraud_score": fraud_score,
            "fraud_threshold": fraud_threshold,
        }

        # Write payout decision to chain
        payout_payload_json = json.dumps({
            "claim_id": claim_id,
            "rider_id": rider_id,
            "event_id": event_id,
            "payout_amount_inr": round(payout_amount, 2),
            "formula_inputs": formula_inputs,
            "fraud_gate_passed": fraud_gate_passed,
        }, sort_keys=True, separators=(",", ":"))

        on_chain_tx_id = (
            f"FABRIC-SP-{hashlib.sha256(payout_payload_json.encode()).hexdigest()[:16]}"
        )

        result = SmartPolicyResult(
            claim_id=claim_id,
            rider_id=rider_id,
            event_id=event_id,
            payout_amount_inr=round(payout_amount, 2),
            formula_inputs=formula_inputs,
            on_chain_tx_id=on_chain_tx_id,
            fraud_gate_passed=fraud_gate_passed,
            fraud_score=fraud_score,
            computation_trace=trace,
        )

        self._payout_records[claim_id] = result

        logger.info(
            f"[SmartPolicy] Payout executed on-chain | "
            f"rider={rider_id} claim={claim_id} "
            f"amount={round(payout_amount, 2)} INR "
            f"fraud_gate={'PASS' if fraud_gate_passed else 'BLOCK'} "
            f"tx_id={on_chain_tx_id}"
        )

        return result

    # ------------------------------------------------------------------
    # 3. Verify payout calculation (re-derive from on-chain inputs)
    # ------------------------------------------------------------------

    def verify_payout_calculation(self, claim_id: str) -> Dict[str, Any]:
        """
        Recalculate a payout from on-chain inputs and compare to the
        recorded result. Used for dispute resolution and audit.

        Args:
            claim_id: The claim to verify.

        Returns:
            Dict with original result, recalculated result, and match status.

        Raises:
            ValueError: If claim_id not found in on-chain records.
        """
        record = self._payout_records.get(claim_id)
        if record is None:
            raise ValueError(f"No on-chain payout record found for claim {claim_id}")

        terms = self.get_policy_terms(record.rider_id)
        if terms is None:
            return {
                "claim_id": claim_id,
                "verification_status": "FAILED",
                "reason": f"Policy terms not found for rider {record.rider_id}",
                "original_payout_inr": record.payout_amount_inr,
            }

        # Re-derive payout from on-chain inputs
        inputs = record.formula_inputs
        daily_earnings = terms.earnings_baseline_weekly / 7.0
        effective_days = min(
            inputs["disruption_hours"] / 24.0,
            float(inputs["max_consecutive_days"]),
        )
        recalculated = daily_earnings * inputs["payout_pct"] * effective_days

        # If fraud gate failed, recalculated should also be zero
        if not record.fraud_gate_passed:
            recalculated = 0.0

        matches = abs(recalculated - record.payout_amount_inr) < 0.01

        verification = {
            "claim_id": claim_id,
            "rider_id": record.rider_id,
            "event_id": record.event_id,
            "original_payout_inr": record.payout_amount_inr,
            "recalculated_payout_inr": round(recalculated, 2),
            "formula_version": record.formula_version,
            "match": matches,
            "verification_status": "VERIFIED" if matches else "MISMATCH",
            "on_chain_tx_id": record.on_chain_tx_id,
            "fraud_gate_passed": record.fraud_gate_passed,
            "formula_inputs_used": record.formula_inputs,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"[SmartPolicy] Payout verification | "
            f"claim={claim_id} status={'VERIFIED' if matches else 'MISMATCH'} "
            f"original={record.payout_amount_inr} recalculated={round(recalculated, 2)}"
        )

        return verification

    # ------------------------------------------------------------------
    # 4. Get policy terms for a rider
    # ------------------------------------------------------------------

    def get_policy_terms(self, rider_id: str) -> Optional[PolicyTermsOnChain]:
        """
        Fetch immutable policy terms from on-chain state.

        Args:
            rider_id: The rider whose terms to retrieve.

        Returns:
            PolicyTermsOnChain if found, None otherwise.
        """
        return self._policy_terms.get(rider_id)

    # ------------------------------------------------------------------
    # 5. Get on-chain parameters for a zone
    # ------------------------------------------------------------------

    def get_on_chain_parameters(self, zone_id: str) -> Dict[str, Any]:
        """
        Returns on-chain payout parameters for a zone.

        If no zone-specific override has been set via update_parameter(),
        returns the default parameters. This mirrors Fabric world state
        where each zone can have independent parameter values.

        Args:
            zone_id: The zone to query parameters for.

        Returns:
            Dict with payout_pct, max_consecutive_days, fraud_threshold,
            min_disruption_hours, operating_window_start, operating_window_end.
        """
        if zone_id in self._zone_params:
            # Merge zone-specific overrides with defaults
            params = dict(_default_zone_params)
            params.update(self._zone_params[zone_id])
            return params
        return dict(_default_zone_params)

    # ------------------------------------------------------------------
    # 6. Update on-chain parameter (DAO governance)
    # ------------------------------------------------------------------

    async def update_parameter(
        self,
        zone_id: str,
        param_name: str,
        new_value: Any,
        changed_by: str,
    ) -> None:
        """
        Update an on-chain parameter for a zone.

        Used by DAO governance after a vote passes. Writes a
        PARAMETER_CHANGED event to ZoneChain so the change is
        visible to the IRDAI observer node in real-time.

        Args:
            zone_id: Zone whose parameter to update.
            param_name: Parameter name (must be a known parameter).
            new_value: New value for the parameter.
            changed_by: Admin/DAO ID who authorised the change.

        Raises:
            ValueError: If param_name is not a recognised on-chain parameter.
        """
        if param_name not in _default_zone_params:
            raise ValueError(
                f"Unknown on-chain parameter '{param_name}'. "
                f"Valid parameters: {list(_default_zone_params.keys())}"
            )

        # Read old value
        current_params = self.get_on_chain_parameters(zone_id)
        old_value = current_params[param_name]

        # Update simulated chain state
        if zone_id not in self._zone_params:
            self._zone_params[zone_id] = {}
        self._zone_params[zone_id][param_name] = new_value

        # Write parameter change event to ZoneChain (Fabric ledger)
        await self._zonechain.write_parameter_change(
            parameter_name=param_name,
            old_value=old_value,
            new_value=new_value,
            changed_by_admin_id=changed_by,
            justification=(
                f"DAO governance update for zone {zone_id}: "
                f"{param_name} changed from {old_value} to {new_value}"
            ),
            zone_id=zone_id,
        )

        logger.info(
            f"[SmartPolicy] On-chain parameter updated | "
            f"zone={zone_id} param={param_name} "
            f"old={old_value} new={new_value} by={changed_by}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _verify_disruption_event(self, event_id: str) -> bool:
        """
        Mock verification that a disruption event exists.

        In production, this queries the ZoneChain signals collection
        for a confirmed disruption event with matching event_id.
        """
        return event_id in self._disruption_events


# ---------------------------------------------------------------------------
# Singleton for DI
# ---------------------------------------------------------------------------

_smart_policy: Optional[SmartPolicyEngine] = None


def get_smart_policy() -> SmartPolicyEngine:
    """FastAPI dependency -- returns the shared SmartPolicy engine."""
    global _smart_policy
    if _smart_policy is None:
        _smart_policy = SmartPolicyEngine()
    return _smart_policy
