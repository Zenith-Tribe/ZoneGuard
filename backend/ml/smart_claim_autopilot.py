"""
ml/smart_claim_autopilot.py
============================
Innovation 12: SmartClaim Autopilot — LLM -> On-Chain Execution

Autonomous claim adjudication for MEDIUM-confidence claims with
5 guard rails ensuring the LLM cannot override safety boundaries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import statistics
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel

from config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Prompt Template
# ---------------------------------------------------------------------------

AUTOPILOT_PROMPT = """You are ZoneGuard's autonomous claim adjudicator.

Given verified data from blockchain oracles and ML models, decide on this MEDIUM-confidence parametric claim.

CLAIM CONTEXT:
{context_json}

INSTRUCTIONS:
- APPROVE if signals are consistent with genuine disruption
- REJECT if fraud indicators are elevated or exclusions apply
- ESCALATE if data is ambiguous or contradictory

Respond in JSON ONLY:
{{"decision": "APPROVE|REJECT|ESCALATE", "confidence_pct": <0-100>, "reasoning": "<detailed reasoning>", "recommended_payout": <amount_inr>}}
"""

# ---------------------------------------------------------------------------
# Guard Rail Identifiers
# ---------------------------------------------------------------------------

GUARD_RAILS = [
    "FORMULA_ENFORCEMENT",      # 1. LLM can't override SmartPolicy payout amount
    "CONFIDENCE_THRESHOLD",     # 2. Auto-ESCALATE if LLM confidence < 80%
    "ZONETWIN_CONSISTENCY",     # 3. Auto-ESCALATE if ZoneTwin conflicts with LLM
    "REASONING_MINIMUM",        # 4. Reasoning must be >50 words
    "DRIFT_MONITORING",         # 5. Check if recent decisions show statistical drift
]

# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------


class AutopilotDecision(BaseModel):
    claim_id: str
    action: Literal["APPROVE", "REJECT", "ESCALATE"]
    reasoning: str
    confidence_pct: int
    recommended_payout_inr: float
    formula_payout_inr: float  # Always the formula-calculated amount
    guardrails_passed: list[str]
    guardrails_failed: list[str]
    llm_model_used: str
    ipfs_hash: Optional[str] = None
    processing_time_ms: float = 0.0
    was_overridden: bool = False  # True if guard rails changed LLM decision


# ---------------------------------------------------------------------------
# In-memory Stores
# ---------------------------------------------------------------------------

_decision_log: list[dict] = []   # Rolling log for drift monitoring
_ipfs_store: dict[str, str] = {}  # Simulated IPFS: hash -> content
_override_log: list[dict] = []   # Human override records

# ---------------------------------------------------------------------------
# SmartClaimAutopilot
# ---------------------------------------------------------------------------


class SmartClaimAutopilot:
    """LLM-driven autonomous claim adjudicator with 5 guard rails."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def adjudicate_claim(
        self,
        claim_data: dict,
        fusion_result: dict,
        fraud_score: float,
        zone_twin: dict,
        exclusion_check: dict,
    ) -> AutopilotDecision:
        """Main entry point. Assembles context, calls LLM, validates with
        guard rails, and returns a decision.

        If any guard rail fails the decision is ESCALATE regardless of LLM
        output.
        """
        start = time.time()
        claim_id = claim_data.get("id", claim_data.get("claim_id", "UNKNOWN"))

        try:
            # 1. Assemble structured context
            context = self._assemble_context(
                claim_data, fusion_result, fraud_score, zone_twin, exclusion_check,
            )

            # 2. Calculate formula payout (55% of 7-day daily average)
            daily_avg = claim_data.get("weekly_earnings_baseline", 2000) / 7
            formula_payout = round(daily_avg * 0.55, 2)

            # 3. Ask LLM for reasoning
            llm_decision = await self._reason_with_llm(context)

            # 4. Validate against guard rails
            validated = self._validate_decision(llm_decision, context, claim_data)

            # 5. Determine final action
            guardrails_failed = validated["guardrails_failed"]
            guardrails_passed = validated["guardrails_passed"]

            if guardrails_failed:
                final_action = "ESCALATE"
                was_overridden = llm_decision.get("decision", "ESCALATE") != "ESCALATE"
            else:
                final_action = llm_decision.get("decision", "ESCALATE")
                was_overridden = False

            # 6. Build decision object
            decision = AutopilotDecision(
                claim_id=claim_id,
                action=final_action,
                reasoning=llm_decision.get("reasoning", "No reasoning provided."),
                confidence_pct=llm_decision.get("confidence_pct", 0),
                recommended_payout_inr=formula_payout,  # Always formula amount
                formula_payout_inr=formula_payout,
                guardrails_passed=guardrails_passed,
                guardrails_failed=guardrails_failed,
                llm_model_used=llm_decision.get("model_used", "unknown"),
                was_overridden=was_overridden,
            )

            # 7. Log to simulated IPFS
            ipfs_hash = await self._log_to_ipfs(decision.model_dump(), context)
            decision.ipfs_hash = ipfs_hash

            # 8. Record processing time
            decision.processing_time_ms = round((time.time() - start) * 1000, 2)

            # 9. Append to rolling decision log for drift monitoring
            _decision_log.append({
                "claim_id": claim_id,
                "action": decision.action,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "was_overridden": decision.was_overridden,
            })

            logger.info(
                f"[SmartClaim] Claim {claim_id} adjudicated -> {decision.action} "
                f"(confidence={decision.confidence_pct}%, "
                f"guardrails_failed={guardrails_failed}, "
                f"time={decision.processing_time_ms}ms)"
            )

            return decision

        except Exception as exc:
            elapsed = round((time.time() - start) * 1000, 2)
            logger.error(f"[SmartClaim] Error adjudicating claim {claim_id}: {exc}")

            # Never raise — return ESCALATE on any error
            daily_avg = claim_data.get("weekly_earnings_baseline", 2000) / 7
            formula_payout = round(daily_avg * 0.55, 2)

            return AutopilotDecision(
                claim_id=claim_id,
                action="ESCALATE",
                reasoning=f"Autopilot error: {exc}. Escalating to human reviewer.",
                confidence_pct=0,
                recommended_payout_inr=formula_payout,
                formula_payout_inr=formula_payout,
                guardrails_passed=[],
                guardrails_failed=["ERROR_FALLBACK"],
                llm_model_used="none",
                processing_time_ms=elapsed,
                was_overridden=False,
            )

    # ------------------------------------------------------------------
    # Context Assembly
    # ------------------------------------------------------------------

    def _assemble_context(
        self,
        claim_data: dict,
        fusion_result: dict,
        fraud_score: float,
        zone_twin: dict,
        exclusion_check: dict,
    ) -> dict:
        """Combine all inputs into a structured context for the LLM prompt."""
        daily_avg = claim_data.get("weekly_earnings_baseline", 2000) / 7
        formula_payout = round(daily_avg * 0.55, 2)

        return {
            "claim": {
                "id": claim_data.get("id", claim_data.get("claim_id", "UNKNOWN")),
                "rider_id": claim_data.get("rider_id"),
                "zone_id": claim_data.get("zone_id"),
                "policy_id": claim_data.get("policy_id"),
                "weekly_earnings_baseline": claim_data.get("weekly_earnings_baseline", 2000),
                "daily_average_inr": round(daily_avg, 2),
                "formula_payout_inr": formula_payout,
            },
            "fusion": {
                "confidence": fusion_result.get("confidence"),
                "signals_fired": fusion_result.get("signals_fired"),
                "signal_details": fusion_result.get("signal_details", {}),
            },
            "fraud": {
                "score": fraud_score,
                "risk_level": (
                    "hold" if fraud_score > 0.85
                    else "review" if fraud_score > 0.65
                    else "low"
                ),
            },
            "zone_twin": {
                "p10": zone_twin.get("expected_inactivity", {}).get("p10", 0),
                "p50": zone_twin.get("expected_inactivity", {}).get("p50", 0),
                "p90": zone_twin.get("expected_inactivity", {}).get("p90", 0),
            },
            "exclusion_check": {
                "passed": exclusion_check.get("passed", True),
                "triggered": exclusion_check.get("triggered_exclusions", []),
            },
        }

    # ------------------------------------------------------------------
    # LLM Reasoning
    # ------------------------------------------------------------------

    async def _reason_with_llm(self, context: dict) -> dict:
        """Call Gemini for reasoning. Falls back to template if unavailable.

        Returns dict with keys: decision, confidence_pct, reasoning,
        recommended_payout, model_used.
        """
        settings = get_settings()
        context_json = json.dumps(context, indent=2, default=str)

        prompt = AUTOPILOT_PROMPT.format(context_json=context_json)

        if settings.gemini_api_key:
            try:
                import google.generativeai as genai

                genai.configure(api_key=settings.gemini_api_key)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content(prompt)
                raw_text = response.text.strip()

                parsed = self._parse_llm_json(raw_text)
                parsed["model_used"] = "gemini-1.5-flash"
                logger.info("[SmartClaim] Gemini response received and parsed")
                return parsed

            except Exception as e:
                logger.warning(
                    f"[SmartClaim] Gemini API call failed: {e} — using fallback template"
                )
                return self._fallback_decision(context)
        else:
            logger.warning(
                "[SmartClaim] Gemini API key not set — using fallback template"
            )
            return self._fallback_decision(context)

    def _parse_llm_json(self, raw_text: str) -> dict:
        """Parse JSON from LLM response, handling markdown code fences and
        malformed output gracefully."""
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("[SmartClaim] Malformed LLM JSON — escalating")
            return {
                "decision": "ESCALATE",
                "confidence_pct": 0,
                "reasoning": f"LLM returned malformed JSON: {raw_text[:200]}",
                "recommended_payout": 0,
            }

        # Normalize decision value
        decision = str(parsed.get("decision", "ESCALATE")).upper().strip()
        if decision not in ("APPROVE", "REJECT", "ESCALATE"):
            decision = "ESCALATE"

        return {
            "decision": decision,
            "confidence_pct": int(parsed.get("confidence_pct", 0)),
            "reasoning": str(parsed.get("reasoning", "No reasoning provided.")),
            "recommended_payout": float(parsed.get("recommended_payout", 0)),
        }

    def _fallback_decision(self, context: dict) -> dict:
        """Template-based decision when Gemini is unavailable.

        Uses simple heuristics derived from context signals:
        - If exclusions triggered -> REJECT
        - If fraud score high -> ESCALATE
        - If signals consistent -> APPROVE
        - Otherwise -> ESCALATE
        """
        fraud_score = context.get("fraud", {}).get("score", 0)
        exclusion_passed = context.get("exclusion_check", {}).get("passed", True)
        signals_fired = context.get("fusion", {}).get("signals_fired", 0)
        p50_inactivity = context.get("zone_twin", {}).get("p50", 0)
        formula_payout = context.get("claim", {}).get("formula_payout_inr", 0)

        if not exclusion_passed:
            decision = "REJECT"
            confidence = 90
            reasoning = (
                "Claim rejected due to triggered coverage exclusions. "
                f"Exclusions: {context.get('exclusion_check', {}).get('triggered', [])}. "
                f"The QuadSignal fusion detected {signals_fired}/4 signals converging, "
                "however the exclusion engine flagged this claim before adjudication. "
                "ZoneTwin counterfactual analysis shows the expected inactivity "
                f"at p50 is {p50_inactivity}%. Formula-calculated payout would have been "
                f"INR {formula_payout}. No payout authorized due to exclusion trigger."
            )
        elif fraud_score > 0.65:
            decision = "ESCALATE"
            confidence = 60
            reasoning = (
                f"Fraud score of {fraud_score:.2f} exceeds the review threshold of 0.65. "
                f"While {signals_fired}/4 signals converged suggesting genuine disruption, "
                "the elevated fraud indicators require human review before authorization. "
                f"ZoneTwin p50 inactivity estimate is {p50_inactivity}%. "
                f"Formula payout of INR {formula_payout} is held pending manual review. "
                "Escalating to claims adjuster for detailed investigation of anomaly signals."
            )
        elif signals_fired >= 3 and p50_inactivity >= 30:
            decision = "APPROVE"
            confidence = 85
            reasoning = (
                f"Signal convergence is strong with {signals_fired}/4 signals breaching "
                "thresholds within the 2-hour rolling window. ZoneTwin counterfactual "
                f"analysis confirms expected rider inactivity at p50 = {p50_inactivity}%, "
                "which is consistent with genuine zone-level disruption. "
                f"Fraud score is {fraud_score:.2f} (low risk). No exclusions triggered. "
                f"Formula-calculated payout of INR {formula_payout} authorized at 55% "
                "of 7-day daily average earnings baseline."
            )
        else:
            decision = "ESCALATE"
            confidence = 50
            reasoning = (
                f"Ambiguous signal pattern: {signals_fired}/4 signals fired but ZoneTwin "
                f"p50 inactivity is only {p50_inactivity}%, suggesting the disruption "
                "impact may be less severe than signal convergence indicates. "
                f"Fraud score is {fraud_score:.2f}. No exclusions triggered. "
                f"Formula payout of INR {formula_payout} requires human review. "
                "Escalating for manual assessment of disruption severity and rider impact."
            )

        return {
            "decision": decision,
            "confidence_pct": confidence,
            "reasoning": reasoning,
            "recommended_payout": formula_payout,
            "model_used": "fallback_template",
        }

    # ------------------------------------------------------------------
    # Guard Rail Validation
    # ------------------------------------------------------------------

    def _validate_decision(
        self,
        llm_decision: dict,
        context: dict,
        claim_data: dict,
    ) -> dict:
        """Apply 5 guard rails to the LLM decision.

        Returns dict with ``guardrails_passed`` and ``guardrails_failed`` lists.
        If *any* guard rail fails, the caller must force ESCALATE.
        """
        passed: list[str] = []
        failed: list[str] = []

        # ------- 1. FORMULA_ENFORCEMENT -------
        # LLM can't override the SmartPolicy payout amount.
        daily_avg = claim_data.get("weekly_earnings_baseline", 2000) / 7
        formula_payout = round(daily_avg * 0.55, 2)
        llm_payout = llm_decision.get("recommended_payout", 0)

        if abs(llm_payout - formula_payout) > 0.01:
            logger.info(
                f"[SmartClaim] FORMULA_ENFORCEMENT: LLM recommended "
                f"INR {llm_payout}, formula says INR {formula_payout}. "
                "Using formula amount."
            )
            # We always use formula amount (enforced in adjudicate_claim).
            # This is a soft override — log but don't force ESCALATE.
            passed.append("FORMULA_ENFORCEMENT")
        else:
            passed.append("FORMULA_ENFORCEMENT")

        # ------- 2. CONFIDENCE_THRESHOLD -------
        confidence = llm_decision.get("confidence_pct", 0)
        if confidence < 80:
            failed.append("CONFIDENCE_THRESHOLD")
            logger.info(
                f"[SmartClaim] CONFIDENCE_THRESHOLD failed: "
                f"LLM confidence {confidence}% < 80% threshold"
            )
        else:
            passed.append("CONFIDENCE_THRESHOLD")

        # ------- 3. ZONETWIN_CONSISTENCY -------
        p50 = context.get("zone_twin", {}).get("p50", 0)
        llm_action = llm_decision.get("decision", "ESCALATE")

        if p50 < 30 and llm_action == "APPROVE":
            failed.append("ZONETWIN_CONSISTENCY")
            logger.info(
                f"[SmartClaim] ZONETWIN_CONSISTENCY failed: "
                f"ZoneTwin p50={p50}% < 30% but LLM says APPROVE"
            )
        else:
            passed.append("ZONETWIN_CONSISTENCY")

        # ------- 4. REASONING_MINIMUM -------
        reasoning = llm_decision.get("reasoning", "")
        word_count = len(reasoning.split())

        if word_count < 50:
            failed.append("REASONING_MINIMUM")
            logger.info(
                f"[SmartClaim] REASONING_MINIMUM failed: "
                f"reasoning has {word_count} words (min 50)"
            )
        else:
            passed.append("REASONING_MINIMUM")

        # ------- 5. DRIFT_MONITORING -------
        drift = self.monitor_drift()

        if drift["drift_detected"]:
            failed.append("DRIFT_MONITORING")
            logger.info(
                f"[SmartClaim] DRIFT_MONITORING failed: {drift['alert_message']}"
            )
        else:
            passed.append("DRIFT_MONITORING")

        return {
            "guardrails_passed": passed,
            "guardrails_failed": failed,
        }

    # ------------------------------------------------------------------
    # IPFS Logging (Simulated)
    # ------------------------------------------------------------------

    async def _log_to_ipfs(self, decision: dict, context: dict) -> str:
        """Simulated IPFS storage: hash the full decision + context JSON.

        Returns a simulated IPFS hash and stores the content in-memory for
        retrieval.
        """
        payload = {
            "decision": decision,
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        content = json.dumps(payload, indent=2, default=str)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:44]
        ipfs_hash = f"ipfs://Qm{content_hash}"

        _ipfs_store[ipfs_hash] = content

        logger.info(f"[SmartClaim] Decision logged to IPFS: {ipfs_hash}")
        return ipfs_hash

    # ------------------------------------------------------------------
    # Drift Monitoring
    # ------------------------------------------------------------------

    def monitor_drift(self) -> dict:
        """Track rolling 7-day approval/rejection/escalation counts.

        Alert if any rate deviates >2 standard deviations from 30-day average.

        Returns:
            dict with drift_detected, approval_rate, rejection_rate,
            escalation_rate, and alert_message.
        """
        now = datetime.now(timezone.utc)

        # Partition the decision log into 30-day and 7-day windows
        decisions_30d: list[dict] = []
        decisions_7d: list[dict] = []

        for entry in _decision_log:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
            except (KeyError, ValueError):
                continue
            delta = (now - ts).total_seconds() / 86400  # days
            if delta <= 30:
                decisions_30d.append(entry)
            if delta <= 7:
                decisions_7d.append(entry)

        # Not enough data to detect drift
        if len(decisions_30d) < 10:
            total_7d = len(decisions_7d) or 1
            approvals_7d = sum(1 for d in decisions_7d if d["action"] == "APPROVE")
            rejections_7d = sum(1 for d in decisions_7d if d["action"] == "REJECT")
            escalations_7d = sum(1 for d in decisions_7d if d["action"] == "ESCALATE")

            return {
                "drift_detected": False,
                "approval_rate": round(approvals_7d / total_7d, 4),
                "rejection_rate": round(rejections_7d / total_7d, 4),
                "escalation_rate": round(escalations_7d / total_7d, 4),
                "alert_message": None,
            }

        # Compute daily rates for the 30-day window (bucket by day)
        daily_buckets: dict[str, dict[str, int]] = {}
        for entry in decisions_30d:
            day_key = entry["timestamp"][:10]  # YYYY-MM-DD
            if day_key not in daily_buckets:
                daily_buckets[day_key] = {"APPROVE": 0, "REJECT": 0, "ESCALATE": 0, "total": 0}
            action = entry.get("action", "ESCALATE")
            daily_buckets[day_key][action] = daily_buckets[day_key].get(action, 0) + 1
            daily_buckets[day_key]["total"] += 1

        # Daily rates
        daily_approval_rates: list[float] = []
        daily_rejection_rates: list[float] = []
        daily_escalation_rates: list[float] = []

        for bucket in daily_buckets.values():
            total = bucket["total"] or 1
            daily_approval_rates.append(bucket["APPROVE"] / total)
            daily_rejection_rates.append(bucket["REJECT"] / total)
            daily_escalation_rates.append(bucket["ESCALATE"] / total)

        # 7-day rates
        total_7d = len(decisions_7d) or 1
        approvals_7d = sum(1 for d in decisions_7d if d["action"] == "APPROVE")
        rejections_7d = sum(1 for d in decisions_7d if d["action"] == "REJECT")
        escalations_7d = sum(1 for d in decisions_7d if d["action"] == "ESCALATE")

        rate_7d_approve = approvals_7d / total_7d
        rate_7d_reject = rejections_7d / total_7d
        rate_7d_escalate = escalations_7d / total_7d

        # Check for 2-sigma deviation
        alerts: list[str] = []

        for label, rates_30d, rate_7d in [
            ("approval", daily_approval_rates, rate_7d_approve),
            ("rejection", daily_rejection_rates, rate_7d_reject),
            ("escalation", daily_escalation_rates, rate_7d_escalate),
        ]:
            if len(rates_30d) < 2:
                continue
            mean_30d = statistics.mean(rates_30d)
            stdev_30d = statistics.stdev(rates_30d)
            if stdev_30d > 0 and abs(rate_7d - mean_30d) > 2 * stdev_30d:
                alerts.append(
                    f"{label} rate {rate_7d:.2%} deviates >2 sigma from "
                    f"30-day mean {mean_30d:.2%} (stdev={stdev_30d:.2%})"
                )

        drift_detected = len(alerts) > 0

        return {
            "drift_detected": drift_detected,
            "approval_rate": round(rate_7d_approve, 4),
            "rejection_rate": round(rate_7d_reject, 4),
            "escalation_rate": round(rate_7d_escalate, 4),
            "alert_message": "; ".join(alerts) if alerts else None,
        }

    # ------------------------------------------------------------------
    # Human Override
    # ------------------------------------------------------------------

    async def human_override(
        self,
        claim_id: str,
        reviewer_id: str,
        new_decision: str,
        justification: str,
    ) -> dict:
        """Record a human override decision.

        Would write a counter-signature to ZoneChain (simulated).

        Args:
            claim_id: The claim being overridden.
            reviewer_id: ID of the human reviewer.
            new_decision: The new decision (APPROVE / REJECT / ESCALATE).
            justification: Free-text justification for the override.

        Returns:
            dict with override details and simulated chain hash.
        """
        override_record = {
            "claim_id": claim_id,
            "reviewer_id": reviewer_id,
            "new_decision": new_decision.upper(),
            "justification": justification,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Simulated ZoneChain counter-signature
        sig_content = json.dumps(override_record, default=str)
        chain_hash = hashlib.sha256(sig_content.encode()).hexdigest()[:40]
        override_record["chain_hash"] = f"0x{chain_hash}"

        _override_log.append(override_record)

        logger.info(
            f"[SmartClaim] Human override for claim {claim_id} by {reviewer_id}: "
            f"{new_decision} — chain_hash={override_record['chain_hash']}"
        )

        return override_record


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_autopilot: Optional[SmartClaimAutopilot] = None


def get_smart_claim_autopilot() -> SmartClaimAutopilot:
    """Return the singleton SmartClaimAutopilot instance."""
    global _autopilot
    if _autopilot is None:
        _autopilot = SmartClaimAutopilot()
    return _autopilot
