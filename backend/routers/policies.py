# MERGED BY SESSION 7 — Patches from sessions: 2
# No other sessions patched policies.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from models.policy import Policy, PolicyAppliedExclusion, PolicyExclusionType
from models.premium_payment import PremiumPayment
from models.zone import Zone
from models.rider import Rider
from schemas.policy import PolicyCreate, PolicyResponse, ExclusionResponse
from services.exclusion_engine import get_all_exclusion_types
from ml.zone_risk_scorer import calculate_zone_premium
from models.notification import create_notification, NotificationType
from datetime import datetime, timedelta, timezone
import uuid

# ── Session 2: SmartPolicy Chaincode (lazy import) ────────────────────────────
import asyncio
import logging

_policy_chaincode_logger = logging.getLogger("chaincode.policy")

def _get_policy_sdk():
    try:
        from chaincode.chaincode_sdk import policy_sdk
        return policy_sdk
    except ImportError:
        _policy_chaincode_logger.warning(
            "chaincode_sdk not available — policy will not be recorded on-chain. "
            "This is expected in dev/test before ZoneChain is running."
        )
        return None
# ── End Session 2 imports ─────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


@router.post("")
async def create_policy(payload: PolicyCreate, db: AsyncSession = Depends(get_db)):
    """Create a weekly policy with all exclusions attached."""

    zone = await db.get(Zone, payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    rider = await db.get(Rider, payload.rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Calculate premium
    premium_info = calculate_zone_premium(
        {"historical_disruptions": zone.historical_disruptions, "risk_tier": zone.risk_tier, "active_riders": zone.active_riders},
        rider_tenure_weeks=rider.tenure_weeks,
    )

    weekly_premium = premium_info["premium"]
    # Forward Premium Lock: 8% discount for 4-week commitment
    if payload.is_forward_locked and payload.forward_lock_weeks >= 4:
        weekly_premium = round(weekly_premium * 0.92)

    now = datetime.now(timezone.utc)
    policy = Policy(
        rider_id=payload.rider_id,
        zone_id=payload.zone_id,
        weekly_premium=weekly_premium,
        max_payout=premium_info["max_payout"],
        coverage_start=now,
        coverage_end=now + timedelta(weeks=1),
        is_forward_locked=payload.is_forward_locked,
        forward_lock_weeks=payload.forward_lock_weeks,
    )
    db.add(policy)
    await db.flush()

    # Attach all 10 standard exclusions
    exclusion_types = get_all_exclusion_types()
    for excl in exclusion_types:
        existing = await db.get(PolicyExclusionType, excl["id"])
        if not existing:
            db.add(PolicyExclusionType(**excl))

        applied = PolicyAppliedExclusion(
            id=uuid.uuid4().hex[:12],
            policy_id=policy.id,
            exclusion_type_id=excl["id"],
        )
        db.add(applied)

    # Create premium payment record
    premium_payment = PremiumPayment(
        id=str(uuid.uuid4()),
        rider_id=policy.rider_id,
        policy_id=policy.id,
        amount=policy.weekly_premium,
        week_start=policy.coverage_start.date(),
        week_end=policy.coverage_end.date(),
        status="paid",
        payment_method="UPI",
        transaction_ref=f"ZG-PREM-{uuid.uuid4().hex[:8].upper()}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(premium_payment)

    # Notify rider
    await create_notification(
        db=db, rider_id=payload.rider_id, type=NotificationType.POLICY_ACTIVATED,
        title="Policy Activated",
        message=f"Your ZoneGuard policy for {zone.name} is active. Premium: ₹{weekly_premium}/week. Max payout: ₹{premium_info['max_payout']:,}.",
        metadata={"policy_id": policy.id, "zone_id": payload.zone_id},
    )

    await db.commit()
    await db.refresh(policy)

    # ── Session 2: Record policy on-chain (fire-and-forget) ───────────────────
    _policy_sdk = _get_policy_sdk()
    if _policy_sdk:
        async def _write_policy_on_chain():
            try:
                await _policy_sdk.create_policy(
                    policy_id=policy.id,
                    rider_id=str(policy.rider_id),
                    zone_id=str(policy.zone_id),
                    weekly_premium=float(policy.weekly_premium),
                    max_payout=float(policy.max_payout),
                    coverage_start=policy.coverage_start.isoformat(),
                    coverage_end=policy.coverage_end.isoformat(),
                    is_forward_locked=bool(policy.is_forward_locked),
                    forward_lock_weeks=int(policy.forward_lock_weeks or 0),
                )
                _policy_chaincode_logger.info(f"Policy {policy.id} recorded on-chain")
            except Exception as exc:
                _policy_chaincode_logger.error(
                    f"Policy {policy.id} chaincode write failed (will reconcile): {exc}"
                )
        asyncio.create_task(_write_policy_on_chain())
    # ── End Session 2 create policy on-chain ──────────────────────────────────

    return {
        "policy": {
            "id": policy.id,
            "rider_id": policy.rider_id,
            "zone_id": policy.zone_id,
            "status": policy.status,
            "weekly_premium": policy.weekly_premium,
            "max_payout": policy.max_payout,
            "coverage_start": policy.coverage_start.isoformat(),
            "coverage_end": policy.coverage_end.isoformat(),
            "is_forward_locked": policy.is_forward_locked,
            "forward_lock_weeks": policy.forward_lock_weeks,
        },
        "exclusions": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in exclusion_types],
        "premium_breakdown": premium_info,
    }


@router.get("")
async def list_policies(rider_id: str = Query(None), db: AsyncSession = Depends(get_db)):
    query = select(Policy)
    if rider_id:
        query = query.where(Policy.rider_id == rider_id)
    query = query.order_by(Policy.created_at.desc())
    result = await db.execute(query)
    policies = result.scalars().all()
    return [PolicyResponse.model_validate(p) for p in policies]


@router.get("/{policy_id}")
async def get_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    result = await db.execute(
        select(PolicyExclusionType)
        .join(PolicyAppliedExclusion)
        .where(PolicyAppliedExclusion.policy_id == policy_id)
    )
    exclusions = result.scalars().all()

    return {
        "policy": PolicyResponse.model_validate(policy),
        "exclusions": [ExclusionResponse.model_validate(e) for e in exclusions],
    }


@router.get("/{policy_id}/exclusions")
async def get_policy_exclusions(policy_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PolicyExclusionType)
        .join(PolicyAppliedExclusion)
        .where(PolicyAppliedExclusion.policy_id == policy_id)
    )
    exclusions = result.scalars().all()
    return [ExclusionResponse.model_validate(e) for e in exclusions]


@router.post("/{policy_id}/renew")
async def renew_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    old_policy = await db.get(Policy, policy_id)
    if not old_policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    old_policy.status = "expired"

    now = datetime.now(timezone.utc)
    new_policy = Policy(
        rider_id=old_policy.rider_id,
        zone_id=old_policy.zone_id,
        weekly_premium=old_policy.weekly_premium,
        max_payout=old_policy.max_payout,
        coverage_start=now,
        coverage_end=now + timedelta(weeks=1),
        is_forward_locked=old_policy.is_forward_locked,
        forward_lock_weeks=max(0, old_policy.forward_lock_weeks - 1),
    )
    db.add(new_policy)
    await db.flush()

    premium_payment = PremiumPayment(
        id=str(uuid.uuid4()),
        rider_id=new_policy.rider_id,
        policy_id=new_policy.id,
        amount=new_policy.weekly_premium,
        week_start=new_policy.coverage_start.date(),
        week_end=new_policy.coverage_end.date(),
        status="paid",
        payment_method="UPI",
        transaction_ref=f"ZG-PREM-{uuid.uuid4().hex[:8].upper()}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(premium_payment)

    await db.commit()

    # ── Session 2: Record renewal on-chain ────────────────────────────────────
    _policy_sdk = _get_policy_sdk()
    if _policy_sdk:
        async def _renew_on_chain():
            try:
                await _policy_sdk.renew_policy(
                    policy_id=policy_id,
                    new_coverage_start=new_policy.coverage_start.isoformat(),
                    new_coverage_end=new_policy.coverage_end.isoformat(),
                )
                _policy_chaincode_logger.info(f"Policy {policy_id} renewal recorded on-chain → {new_policy.id}")
            except Exception as exc:
                _policy_chaincode_logger.error(f"Policy renewal chaincode write failed: {exc}")
        asyncio.create_task(_renew_on_chain())
    # ── End Session 2 renew on-chain ──────────────────────────────────────────

    return {"old_policy_id": policy_id, "new_policy": PolicyResponse.model_validate(new_policy)}


@router.post("/{policy_id}/forward-lock")
async def activate_forward_lock(policy_id: str, db: AsyncSession = Depends(get_db)):
    """Activate Forward Premium Lock: 4-week commitment with 8% discount."""
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.status != "active":
        raise HTTPException(status_code=400, detail="Only active policies can be forward-locked")
    if policy.is_forward_locked:
        raise HTTPException(status_code=400, detail="Policy already forward-locked")

    original_premium = policy.weekly_premium
    discounted_premium = round(original_premium * 0.92)
    savings_per_week = original_premium - discounted_premium

    policy.is_forward_locked = True
    policy.forward_lock_weeks = 4
    policy.weekly_premium = discounted_premium

    await db.commit()
    await db.refresh(policy)

    return {
        "policy_id": policy.id,
        "is_forward_locked": True,
        "weeks_remaining": policy.forward_lock_weeks,
        "original_premium": original_premium,
        "weekly_premium": discounted_premium,
        "discount_pct": 8,
        "savings_per_week": savings_per_week,
        "total_savings": savings_per_week * 4,
    }


@router.post("/{policy_id}/cancel")
async def cancel_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy.status = "cancelled"
    await db.commit()
    return {"status": "cancelled", "policy_id": policy_id}
