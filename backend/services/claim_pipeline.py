"""
End-to-end claim pipeline: signal → disruption → exclusion check → fraud check → payout.

This is the core orchestrator that ties together SignalFusion, ExclusionEngine,
FraudShield, ZoneTwin, Gemini audit, PayoutSim, and blockchain recording.

Blockchain integration (Innovation 01, 02, 10, 12):
  - TemporalSig: anchor signal batch after fusion (immutable timestamp proof)
  - ZoneChain: record claim lifecycle events (creation, approval, rejection)
  - SmartPolicy: on-chain payout formula for HIGH confidence claims
  - SmartClaim Autopilot: LLM adjudication for MEDIUM confidence claims
"""

import asyncio
import logging
from datetime import datetime, timezone
from ml.signal_fusion import fuse_signals, evaluate_s1, evaluate_s2, evaluate_s3, evaluate_s4
from ml.fraud_shield import calculate_fraud_score
from ml.zone_twin import counterfactual_inactivity
from services.exclusion_engine import evaluate_claim_exclusions
from integrations.gemini import generate_audit_report
from integrations.payout_sim import process_payout
import uuid

logger = logging.getLogger(__name__)


def _fire_and_forget(coro):
    """Schedule a coroutine as fire-and-forget — never blocks the pipeline."""
    try:
        asyncio.create_task(coro)
    except Exception as e:
        logger.warning(f"[ClaimPipeline] fire-and-forget scheduling failed: {e}")


async def process_disruption_event(
    zone_id: str,
    zone_data: dict,
    weather_data: dict,
    mobility_data: dict,
    order_data: dict,
    checkin_data: dict,
    riders_with_policies: list[dict],
) -> dict:
    """
    Full pipeline: evaluate signals → create disruption → process claims.
    """

    # Step 1: Evaluate all 4 signals
    s1 = evaluate_s1(
        rainfall_mm=weather_data["rainfall_mm_hr"],
        aqi=weather_data["aqi"],
        temp_c=weather_data["temperature_c"],
        ndma_alert=weather_data.get("ndma_alert", False),
    )
    s2 = evaluate_s2(
        mobility_index=mobility_data["mobility_index"],
        baseline=mobility_data.get("baseline", 100),
    )
    s3 = evaluate_s3(
        order_volume=order_data["order_volume"],
        baseline=order_data.get("baseline", 100),
    )
    s4 = evaluate_s4(
        inactive_riders=checkin_data["inactive_riders"],
        total_riders=checkin_data["total_riders"],
    )

    # Step 2: Fuse signals
    fusion = fuse_signals(s1, s2, s3, s4)

    # Step 2b: Anchor signal batch to TemporalSig (Innovation 10)
    try:
        from blockchain.temporalsig import get_temporalsig_client
        from blockchain.models import SignalBatchPayload, SignalReading, ConfidenceTier
        batch_id = str(uuid.uuid4())
        batch = SignalBatchPayload(
            batch_id=batch_id,
            zone_id=zone_id,
            polled_at=datetime.now(timezone.utc),
            signals=[
                SignalReading(signal_type="ENVIRONMENTAL", raw_value=weather_data.get("rainfall_mm_hr", 0), normalized_score=min(1.0, s1.get("value", 0)), source_api="openweathermap", zone_id=zone_id),
                SignalReading(signal_type="MOBILITY", raw_value=mobility_data.get("mobility_index", 100), normalized_score=min(1.0, s2.get("value", 0)), source_api="osrm", zone_id=zone_id),
                SignalReading(signal_type="ECONOMIC", raw_value=order_data.get("order_volume", 100), normalized_score=min(1.0, s3.get("value", 0)), source_api="amazon_flex", zone_id=zone_id),
                SignalReading(signal_type="CROWD", raw_value=checkin_data.get("inactivity_pct", 0), normalized_score=min(1.0, s4.get("value", 0)), source_api="whatsapp", zone_id=zone_id),
            ],
            composite_score=fusion.get("composite_score", 0.0),
            confidence_tier=ConfidenceTier(fusion["confidence"]),
            scheduler_run_id=f"pipeline-{zone_id}",
        )
        ts_client = get_temporalsig_client()
        _fire_and_forget(ts_client.anchor_signal_batch(batch))
        logger.info(f"[ClaimPipeline] TemporalSig anchor queued for batch {batch_id}")
    except Exception as e:
        batch_id = None
        logger.warning(f"[ClaimPipeline] TemporalSig anchoring skipped: {e}")

    # No disruption event if NOISE
    if fusion["confidence"] == "NOISE":
        return {"disruption_created": False, "fusion": fusion, "claims": []}

    # Step 3: Create disruption event record
    event_id = f"DE-{uuid.uuid4().hex[:8].upper()}"

    # Step 4: ZoneTwin counterfactual
    zone_twin = counterfactual_inactivity(
        zone_id=zone_id,
        rainfall_mm=weather_data["rainfall_mm_hr"],
        aqi=weather_data["aqi"],
    )

    # Step 5: Process claims for each eligible rider
    claims = []
    for rider in riders_with_policies:
        # Calculate payout (55% of 7-day daily average)
        daily_avg = rider.get("weekly_earnings_baseline", 2000) / 7
        payout_amount = round(daily_avg * 0.55)

        # SmartPolicy on-chain payout (Innovation 02) — use formula from chain
        try:
            from blockchain.smart_policy import get_smart_policy
            sp = get_smart_policy()
            sp_result = sp.execute_payout(
                rider_id=rider["id"],
                event_id=event_id,
                disruption_hours=rider.get("disruption_hours", 8),
                composite_score=fusion.get("composite_score", 0.5),
                confidence_tier=fusion["confidence"],
            )
            payout_amount = round(sp_result.payout_amount_inr)
            logger.info(f"[ClaimPipeline] SmartPolicy payout: {payout_amount} INR for {rider['id']}")
        except Exception as e:
            logger.warning(f"[ClaimPipeline] SmartPolicy unavailable, using local formula: {e}")

        # Fraud check
        fraud = calculate_fraud_score(
            claim_hour=datetime.now(timezone.utc).hour,
            tenure_weeks=rider.get("tenure_weeks", 10),
            zone_inactivity_pct=checkin_data.get("inactivity_pct", 40),
            claim_velocity_7d=rider.get("recent_claims_7d", 0),
            zone_claim_rate_deviation=1.0,
            distance_from_centroid_km=rider.get("distance_km", 1.5),
            s1_value=weather_data["rainfall_mm_hr"],
            days_since_policy_start=rider.get("days_since_policy_start", 5),
        )

        # Exclusion check
        exclusion_check = evaluate_claim_exclusions(
            claim_data={"rider_id": rider["id"], "zone_id": zone_id},
            policy_data=rider.get("policy", {}),
            fraud_score=fraud["score"],
            consecutive_disruption_days=rider.get("consecutive_disruption_days", 0),
        )

        claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"

        # Determine claim status
        if not exclusion_check["passed"]:
            status = "rejected"
        elif fraud["risk_level"] == "hold":
            status = "held"
        elif fusion["confidence"] == "HIGH":
            status = "approved"
        elif fusion["confidence"] == "MEDIUM":
            status = "pending_review"
        else:
            status = "pending_review"

        claim = {
            "id": claim_id,
            "rider_id": rider["id"],
            "policy_id": rider.get("policy_id", ""),
            "zone_id": zone_id,
            "disruption_event_id": event_id,
            "status": status,
            "confidence": fusion["confidence"],
            "recommended_payout": payout_amount,
            "exclusion_check": exclusion_check,
            "fraud_score": fraud["score"],
            "fraud_details": fraud,
            "zone_twin": zone_twin,
        }

        # Record claim creation on ZoneChain (Innovation 01)
        try:
            from blockchain.zonechain import get_zonechain_client
            from blockchain.models import ChainEventType, ConfidenceTier as CT
            zc = get_zonechain_client()
            _fire_and_forget(zc.write_claim_event(
                claim_id=claim_id,
                rider_id=rider["id"],
                policy_id=rider.get("policy_id", ""),
                zone_id=zone_id,
                event_type=ChainEventType.CLAIM_CREATED,
                confidence_tier=CT(fusion["confidence"]),
                composite_score=fusion.get("composite_score", 0.0),
                payout_amount_inr=payout_amount if status == "approved" else None,
                rejection_reason=str(exclusion_check.get("triggered", [])) if status == "rejected" else None,
            ))
        except Exception as e:
            logger.warning(f"[ClaimPipeline] ZoneChain claim write skipped: {e}")

        # SmartClaim Autopilot for MEDIUM confidence claims (Innovation 12)
        if fusion["confidence"] == "MEDIUM":
            try:
                from ml.smart_claim_autopilot import get_smart_claim_autopilot
                autopilot = get_smart_claim_autopilot()
                autopilot_decision = await autopilot.adjudicate_claim(
                    claim_data=claim,
                    fusion_result=fusion,
                    fraud_score=fraud["score"],
                    zone_twin=zone_twin,
                    exclusion_check=exclusion_check,
                )
                claim["autopilot_decision"] = autopilot_decision.model_dump() if hasattr(autopilot_decision, "model_dump") else autopilot_decision
                # Override status based on autopilot
                if hasattr(autopilot_decision, "action"):
                    if autopilot_decision.action == "APPROVE":
                        claim["status"] = "approved"
                    elif autopilot_decision.action == "REJECT":
                        claim["status"] = "rejected"
                logger.info(f"[ClaimPipeline] SmartClaim Autopilot: {autopilot_decision.action} for {claim_id}")
            except Exception as e:
                logger.warning(f"[ClaimPipeline] SmartClaim Autopilot failed, using Gemini audit: {e}")
                # Fallback to standard Gemini audit report
                audit = await generate_audit_report({
                    "claim_id": claim_id,
                    "zone_name": zone_data.get("name", zone_id),
                    "zone_id": zone_id,
                    "confidence": fusion["confidence"],
                    "signals_fired": fusion["signals_fired"],
                    "signal_details": fusion["signal_details"],
                    "s1": s1, "s2": s2, "s3": s3, "s4": s4,
                    "zone_twin": zone_twin,
                    "exclusion_check": exclusion_check,
                    "fraud_score": fraud["score"],
                })
                claim["audit_report"] = audit

        # Auto-payout for HIGH confidence approved claims
        if status == "approved" and fusion["confidence"] == "HIGH":
            payout = await process_payout(
                rider_id=rider["id"],
                amount=payout_amount,
                upi_id=rider.get("upi_id"),
            )
            claim["payout"] = payout

            # Record payout on ZoneChain (Innovation 01)
            try:
                from blockchain.zonechain import get_zonechain_client
                from blockchain.models import ChainEventType as CET
                zc = get_zonechain_client()
                _fire_and_forget(zc.write_payout_trigger(
                    payout_id=payout.get("payout_id", str(uuid.uuid4())),
                    claim_id=claim_id,
                    rider_id=rider["id"],
                    policy_id=rider.get("policy_id", ""),
                    amount_inr=payout_amount,
                    triggered_at=datetime.now(timezone.utc),
                    upi_reference=payout.get("upi_ref"),
                ))
            except Exception as e:
                logger.warning(f"[ClaimPipeline] ZoneChain payout write skipped: {e}")

        claims.append(claim)

    return {
        "disruption_created": True,
        "event_id": event_id,
        "fusion": fusion,
        "zone_twin": zone_twin,
        "claims_count": len(claims),
        "claims": claims,
    }
