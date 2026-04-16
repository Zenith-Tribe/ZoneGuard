from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.rider import Rider
from models.zone import Zone
from models.claim import Claim
from models.payout import Payout
from schemas.rider import RiderRegister, RiderResponse, RiderKYC, EShramVerifyRequest
from schemas.claim import ClaimResponse
from schemas.payout import PayoutResponse
from ml.zone_risk_scorer import calculate_zone_premium

router = APIRouter(prefix="/api/v1/riders", tags=["riders"])


@router.get("")
async def list_riders(
    zone_id: str = Query(None),
    kyc_verified: bool = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all riders with optional zone/KYC filter and pagination."""
    query = select(Rider)
    if zone_id:
        query = query.where(Rider.zone_id == zone_id)
    if kyc_verified is not None:
        query = query.where(Rider.kyc_verified == kyc_verified)
    query = query.order_by(Rider.created_at.desc())

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    riders = result.scalars().all()

    return {
        "items": [RiderResponse.model_validate(r) for r in riders],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/register")
async def register_rider(payload: RiderRegister, db: AsyncSession = Depends(get_db)):
    """Register a new rider and return premium quote."""

    # Check zone exists
    zone = await db.get(Zone, payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    # Check rider doesn't already exist
    existing = await db.get(Rider, payload.rider_id)
    if existing:
        raise HTTPException(status_code=409, detail="Rider already registered")

    # Create rider
    rider = Rider(
        id=payload.rider_id,
        name=payload.name,
        phone=payload.phone,
        zone_id=payload.zone_id,
        weekly_earnings_baseline=payload.weekly_earnings,
        upi_id=payload.upi_id,
        eshram_id=payload.eshram_id,
    )
    db.add(rider)

    # Update zone active rider count
    zone.active_riders = (zone.active_riders or 0) + 1

    await db.commit()
    await db.refresh(rider)

    # Calculate premium quote
    premium_quote = calculate_zone_premium(
        {
            "historical_disruptions": zone.historical_disruptions,
            "risk_tier": zone.risk_tier,
            "active_riders": zone.active_riders,
        },
        rider_tenure_weeks=0,
    )

    return {
        "rider": RiderResponse.model_validate(rider),
        "premium_quote": premium_quote,
    }


@router.get("/{rider_id}")
async def get_rider(rider_id: str, db: AsyncSession = Depends(get_db)):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    return RiderResponse.model_validate(rider)


@router.put("/{rider_id}")
async def update_rider(rider_id: str, updates: dict, db: AsyncSession = Depends(get_db)):
    """Update rider details (name, phone, zone_id, weekly_earnings_baseline, upi_id)."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    allowed = {"name", "phone", "zone_id", "weekly_earnings_baseline", "upi_id"}
    for key, value in updates.items():
        if key in allowed:
            setattr(rider, key, value)

    await db.commit()
    await db.refresh(rider)
    return RiderResponse.model_validate(rider)


@router.get("/{rider_id}/claims")
async def get_rider_claims(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Get all claims for a specific rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    result = await db.execute(
        select(Claim).where(Claim.rider_id == rider_id).order_by(Claim.created_at.desc())
    )
    claims = result.scalars().all()
    return [ClaimResponse.model_validate(c) for c in claims]


@router.get("/{rider_id}/payouts")
async def get_rider_payouts(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Get all payouts for a specific rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    result = await db.execute(
        select(Payout).where(Payout.rider_id == rider_id).order_by(Payout.created_at.desc())
    )
    payouts = result.scalars().all()
    return [PayoutResponse.model_validate(p) for p in payouts]


@router.post("/{rider_id}/kyc")
async def update_kyc(rider_id: str, payload: RiderKYC, db: AsyncSession = Depends(get_db)):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    rider.upi_id = payload.upi_id
    rider.phone = payload.phone
    rider.kyc_verified = True
    await db.commit()

    return {"status": "kyc_verified", "rider_id": rider_id}


@router.post("/{rider_id}/verify-eshram")
async def verify_eshram(
    rider_id: str, payload: EShramVerifyRequest, db: AsyncSession = Depends(get_db),
):
    """Verify rider via e-Shram portal (simulated)."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    from integrations.eshram_sim import verify_eshram_worker, check_income_proxy

    verification = await verify_eshram_worker(
        eshram_id=payload.eshram_id,
        rider_name=rider.name,
        phone=rider.phone or "",
    )

    if verification["verified"]:
        rider.eshram_id = payload.eshram_id
        rider.eshram_verified = True
        rider.kyc_verified = True

        # Cross-reference income if rider has earnings baseline
        if rider.weekly_earnings_baseline > 0:
            income_check = await check_income_proxy(
                eshram_id=payload.eshram_id,
                declared_weekly_earnings=rider.weekly_earnings_baseline,
            )
            verification["income_proxy"] = income_check

        await db.commit()

    return verification
