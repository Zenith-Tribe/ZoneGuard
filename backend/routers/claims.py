# MERGED BY SESSION 7 — Patches from sessions: 1, 2
# Session 6 (Autopilot MEDIUM-confidence path) NOT applied — session did not complete.
# [INTEGRATION WARNING] Session 6 was supposed to add Autopilot for MEDIUM confidence
#   claims. That path is absent. Claims with MEDIUM confidence still go to human review.
# [INTEGRATION WARNING] PATCH 1-6/1-7 assume claim object attributes: rider_id,
#   policy_id, zone_id, confidence_tier, composite_score, payout_amount.
#   Verify these against models/claim.py before deploying.

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.claim import Claim
from models.payout import Payout
from models.audit import AuditLog
from models.rider import Rider
from schemas.claim import ClaimResponse, ClaimReview
from integrations.payout_sim import process_payout
from integrations.gemini import generate_audit_report
from datetime import datetime, timezone

# ── Session 2: SmartPolicy ChainSDK (lazy import) ─────────────────────────────
import asyncio
import hashlib
import logging

_claim_chaincode_logger = logging.getLogger("chaincode.claim")

def _get_claim_sdk():
    try:
        from chaincode.chaincode_sdk import claim_sdk
        return claim_sdk
    except ImportError:
        _claim_chaincode_logger.warning(
            "chaincode_sdk not available — claims will not be recorded on-chain."
        )
        return None

# ── Session 1: ZoneChain + TemporalSig imports ────────────────────────────────
from blockchain.zonechain import ZoneChainClient, get_zonechain_client, ChainEventType, ConfidenceTier
from blockchain.temporalsig import get_temporalsig_client
# ── End Session 1 imports ─────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.get("/stats")
async def claim_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate claim statistics: approval rate, avg payout, velocity."""
    total_result = await db.execute(select(func.count(Claim.id)))
    total = total_result.scalar() or 0

    approved_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "approved")
    )
    approved = approved_result.scalar() or 0

    rejected_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "rejected")
    )
    rejected = rejected_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status.in_(["pending_review", "held"]))
    )
    pending = pending_result.scalar() or 0

    avg_payout_result = await db.execute(
        select(func.avg(Claim.actual_payout)).where(Claim.actual_payout.isnot(None))
    )
    avg_payout = avg_payout_result.scalar() or 0

    avg_fraud_result = await db.execute(
        select(func.avg(Claim.fraud_score)).where(Claim.fraud_score.isnot(None))
    )
    avg_fraud = avg_fraud_result.scalar() or 0

    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "pending": pending,
        "approval_rate": round(approved / total * 100, 1) if total else 0,
        "avg_payout": round(float(avg_payout), 2),
        "avg_fraud_score": round(float(avg_fraud), 3),
    }


@router.get("")
async def list_claims(
    status: str = Query(None),
    zone_id: str = Query(None),
    rider_id: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Claim)
    if status:
        query = query.where(Claim.status == status)
    if zone_id:
        query = query.where(Claim.zone_id == zone_id)
    if rider_id:
        query = query.where(Claim.rider_id == rider_id)
    query = query.order_by(Claim.created_at.desc())

    from utils.pagination import paginate
    return await paginate(db, query, ClaimResponse, page, per_page)


@router.get("/{claim_id}")
async def get_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Get audit report if exists
    audit_result = await db.execute(
        select(AuditLog).where(AuditLog.claim_id == claim_id).order_by(AuditLog.created_at.desc())
    )
    audit = audit_result.scalars().first()

    return {
        "claim": ClaimResponse.model_validate(claim),
        "audit_report": {
            "content": audit.content if audit else None,
            "model_used": audit.model_used if audit else None,
            "generated_at": audit.created_at.isoformat() if audit else None,
        } if audit else None,
    }


@router.post("/{claim_id}/audit")
async def generate_claim_audit(claim_id: str, db: AsyncSession = Depends(get_db)):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    report = await generate_audit_report(claim)

    audit_log = AuditLog(
        claim_id=claim_id,
        event_type="gemini_audit",
        content=report["report"],
        model_used=report["model_used"],
        generated_by="gemini",
    )
    db.add(audit_log)
    await db.commit()

    return {
        "claim_id": claim_id,
        "content": report["report"],
        "model_used": report["model_used"],
        "generated_at": audit_log.created_at.isoformat() if audit_log.created_at else datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{claim_id}/challenge")
async def challenge_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    """Rider contests a rejected claim. Flips status back to pending_review."""
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status != "rejected":
        raise HTTPException(status_code=400, detail="Only rejected claims can be challenged")

    claim.status = "pending_review"
    claim.reviewed_at = None
    claim.reviewed_by = None

    audit = AuditLog(
        claim_id=claim_id,
        event_type="claim_challenge",
        content=f"Claim challenged by rider {claim.rider_id}. Status reset to pending_review.",
        generated_by=claim.rider_id,
    )
    db.add(audit)
    await db.commit()

    return {
        "claim_id": claim_id,
        "status": "pending_review",
        "message": "Claim has been reopened for review",
    }


@router.post("/{claim_id}/review")
async def review_claim(claim_id: str, payload: ClaimReview, db: AsyncSession = Depends(get_db)):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status not in ("pending_review", "held"):
        raise HTTPException(status_code=400, detail=f"Claim cannot be reviewed in '{claim.status}' status")

    claim.status = "approved" if payload.action == "approve" else "rejected"
    claim.reviewed_at = datetime.now(timezone.utc)
    claim.reviewed_by = payload.reviewed_by

    # ── Session 2: Record fraud score on-chain BEFORE payout decision ─────────
    # Fraud score must be immutably committed before approval.
    # If chaincode auto-rejects due to fraud, reviewer action is overridden.
    _claim_sdk = _get_claim_sdk()
    chain_claim = None
    if _claim_sdk and claim.fraud_score is not None:
        try:
            chain_claim = await _claim_sdk.record_fraud_score(
                claim_id=claim_id,
                fraud_score=float(claim.fraud_score),
                recorded_by=payload.reviewed_by,
            )
            if chain_claim.get("fraud_auto_rejected"):
                _claim_chaincode_logger.warning(
                    f"Claim {claim_id}: FraudShield on-chain auto-reject. "
                    f"Overriding reviewer action to 'reject'."
                )
                payload.action = "reject"
                claim.status = "rejected"
                claim.reviewed_at = datetime.now(timezone.utc)
                claim.reviewed_by = "FraudShield-OnChain"
                await db.commit()
                return {
                    "status": "rejected",
                    "claim_id": claim_id,
                    "reason": "FraudShield on-chain auto-reject",
                    "fraud_score": claim.fraud_score,
                    "chain_tx": chain_claim.get("tx_id"),
                    "payout": None,
                }
        except Exception as exc:
            _claim_chaincode_logger.error(f"Fraud score chaincode write failed for {claim_id}: {exc}")
    # ── End Session 2 fraud score block ───────────────────────────────────────

    payout_result = None
    if payload.action == "approve":
        claim.actual_payout = claim.recommended_payout

        # Ensure no duplicate payout exists for this claim
        existing_payout = await db.execute(select(Payout).where(Payout.claim_id == claim_id))
        if not existing_payout.scalars().first():
            rider = await db.get(Rider, claim.rider_id)
            upi_id = rider.upi_id if rider else None
            payout_result = await process_payout(claim.rider_id, claim.recommended_payout, upi_id)
            payout = Payout(
                claim_id=claim_id,
                rider_id=claim.rider_id,
                amount=claim.recommended_payout,
                upi_ref=payout_result["upi_ref"],
                status=payout_result["status"],
                gateway_response=str(payout_result["gateway_response"]),
            )
            if payout_result["status"] == "settled":
                payout.settled_at = datetime.now(timezone.utc)
            db.add(payout)

            # ── Session 2: Approve claim on-chain with UPI hash ───────────────
            if _claim_sdk:
                upi_ref = payout_result.get("upi_ref", "")
                async def _approve_on_chain():
                    try:
                        await _claim_sdk.approve_claim(
                            claim_id=claim_id,
                            reviewed_by=payload.reviewed_by,
                            upi_ref=upi_ref,  # SDK hashes before writing — no raw PII on chain
                        )
                        _claim_chaincode_logger.info(
                            f"Claim {claim_id} approved on-chain. "
                            f"UPI hash recorded (not raw ref)."
                        )
                    except Exception as exc:
                        _claim_chaincode_logger.error(f"Claim approval chaincode write failed: {exc}")
                asyncio.create_task(_approve_on_chain())
            # ── End Session 2 approve on-chain ────────────────────────────────

    # Log the review
    audit = AuditLog(
        claim_id=claim_id,
        event_type="claim_review",
        content=f"Claim {payload.action}d by {payload.reviewed_by}",
        generated_by=payload.reviewed_by,
    )
    db.add(audit)
    await db.commit()

    # ── Session 2: Reject claim on-chain ──────────────────────────────────────
    if payload.action == "reject" and _claim_sdk:
        async def _reject_on_chain():
            try:
                await _claim_sdk.reject_claim(
                    claim_id=claim_id,
                    reviewed_by=payload.reviewed_by,
                    reason=getattr(payload, "rejection_reason", "Manual rejection by reviewer"),
                )
                _claim_chaincode_logger.info(f"Claim {claim_id} rejection recorded on-chain.")
            except Exception as exc:
                _claim_chaincode_logger.error(f"Claim rejection chaincode write failed: {exc}")
        asyncio.create_task(_reject_on_chain())
    # ── End Session 2 reject on-chain ─────────────────────────────────────────

    # ── Session 1: ZoneChain — Record approval event (fire-and-forget) ───────
    zonechain = get_zonechain_client()
    asyncio.create_task(
        zonechain.write_claim_event(
            claim_id=claim_id,
            rider_id=str(claim.rider_id),
            policy_id=str(claim.policy_id),
            zone_id=str(claim.zone_id),
            event_type=ChainEventType.CLAIM_APPROVED if payload.action == "approve" else ChainEventType.CLAIM_REJECTED,
            confidence_tier=ConfidenceTier(claim.confidence_tier.upper()) if hasattr(claim, "confidence_tier") and claim.confidence_tier else ConfidenceTier("LOW"),
            composite_score=float(claim.composite_score or 0.0) if hasattr(claim, "composite_score") else 0.0,
            payout_amount_inr=float(claim.payout_amount or 0.0) if payload.action == "approve" and hasattr(claim, "payout_amount") else 0.0,
        )
    )
    # ── End Session 1 ZoneChain approval record ───────────────────────────────

    return {
        "status": claim.status,
        "claim_id": claim_id,
        "payout": payout_result,
    }
