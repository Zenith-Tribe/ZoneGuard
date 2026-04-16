from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func
from db.database import get_db
from models.zone import Zone
from models.rider import Rider
from models.premium_payment import PremiumPayment
from models.payout import Payout
from schemas.premium import PremiumPaymentCreate, PremiumPaymentResponse, PremiumStatsResponse
from ml.zone_risk_scorer import calculate_zone_premium, calculate_risk_score
from datetime import datetime, timezone
import uuid

router = APIRouter(prefix="/api/v1/premium", tags=["premium"])


@router.get("/calculate")
async def calculate_premium(
    zone_id: str = Query(...),
    rider_id: str = Query(None),
    forward_lock: bool = Query(False, description="Show Forward Premium Lock discount"),
    db: AsyncSession = Depends(get_db),
):
    """Dynamic premium calculation with full factor breakdown."""

    zone = await db.get(Zone, zone_id)
    if not zone:
        return {"error": "Zone not found"}

    tenure_weeks = 0
    if rider_id:
        rider = await db.get(Rider, rider_id)
        if rider:
            tenure_weeks = rider.tenure_weeks

    result = calculate_risk_score(
        disruption_freq=zone.historical_disruptions,
        imd_forecast_severity=40,  # default moderate
        rider_tenure_weeks=tenure_weeks,
        zone_classification=zone.risk_tier,
        recent_claims_7d=2,  # default
        total_zone_riders=zone.active_riders or 100,
    )

    response = {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "rider_id": rider_id,
        **result,
    }

    if forward_lock:
        regular = result.get("premium", 0)
        locked = round(regular * 0.92)
        response["forward_lock_discount"] = {
            "regular_premium": regular,
            "locked_premium": locked,
            "savings_per_week": regular - locked,
            "total_4_week_savings": (regular - locked) * 4,
            "discount_pct": 8,
        }

    return response


@router.get("/history", response_model=list[PremiumPaymentResponse])
async def get_payment_history(
    rider_id: str = Query(..., description="Rider ID to get payment history for"),
    limit: int = Query(50, ge=1, le=100, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    db: AsyncSession = Depends(get_db),
):
    """Get premium payment history for a rider."""
    # Verify rider exists
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    query = (
        select(PremiumPayment)
        .where(PremiumPayment.rider_id == rider_id)
        .order_by(PremiumPayment.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    payments = result.scalars().all()

    return [PremiumPaymentResponse.model_validate(p) for p in payments]


@router.post("/record-payment", response_model=PremiumPaymentResponse, status_code=201)
async def record_payment(
    payload: PremiumPaymentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record a new premium payment."""
    # Verify rider exists
    rider = await db.get(Rider, payload.rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Verify policy exists
    from models.policy import Policy
    policy = await db.get(Policy, payload.policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Verify policy belongs to rider
    if policy.rider_id != payload.rider_id:
        raise HTTPException(status_code=400, detail="Policy does not belong to this rider")

    # Generate transaction reference if not provided
    transaction_ref = payload.transaction_ref or f"ZG-PREM-{uuid.uuid4().hex[:8].upper()}"

    payment = PremiumPayment(
        id=str(uuid.uuid4()),
        rider_id=payload.rider_id,
        policy_id=payload.policy_id,
        amount=payload.amount,
        week_start=payload.week_start,
        week_end=payload.week_end,
        status=payload.status,
        payment_method=payload.payment_method,
        transaction_ref=transaction_ref,
        created_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    return PremiumPaymentResponse.model_validate(payment)


@router.get("/stats", response_model=PremiumStatsResponse)
async def get_premium_stats(
    rider_id: str = Query(..., description="Rider ID to get stats for"),
    db: AsyncSession = Depends(get_db),
):
    """Get cumulative premium statistics for a rider."""
    # Verify rider exists
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Sum all premium payments (only paid status)
    premium_query = select(
        sql_func.coalesce(sql_func.sum(PremiumPayment.amount), 0).label("total_paid"),
        sql_func.count(PremiumPayment.id).label("payment_count"),
    ).where(
        PremiumPayment.rider_id == rider_id,
        PremiumPayment.status == "paid",
    )
    premium_result = await db.execute(premium_query)
    premium_stats = premium_result.one()
    total_paid = float(premium_stats.total_paid)
    payment_count = premium_stats.payment_count

    # Sum all payouts received (only settled status)
    payout_query = select(
        sql_func.coalesce(sql_func.sum(Payout.amount), 0).label("total_payouts")
    ).where(
        Payout.rider_id == rider_id,
        Payout.status == "settled",
    )
    payout_result = await db.execute(payout_query)
    total_payouts = float(payout_result.scalar_one())

    # Calculate net benefit (payouts - premiums)
    net_benefit = total_payouts - total_paid

    # Count distinct coverage weeks
    weeks_query = select(
        sql_func.count(sql_func.distinct(PremiumPayment.week_start))
    ).where(
        PremiumPayment.rider_id == rider_id,
        PremiumPayment.status == "paid",
    )
    weeks_result = await db.execute(weeks_query)
    coverage_weeks = weeks_result.scalar_one() or 0

    return PremiumStatsResponse(
        rider_id=rider_id,
        total_paid=total_paid,
        total_payouts=total_payouts,
        net_benefit=net_benefit,
        coverage_weeks=coverage_weeks,
        payment_count=payment_count,
    )
