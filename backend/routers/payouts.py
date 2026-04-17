from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.payout import Payout
from models.claim import Claim
from models.rider import Rider
from schemas.payout import PayoutResponse
from integrations.payout_sim import process_payout
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/payouts", tags=["payouts"])

MAX_RETRIES = 3


@router.get("")
async def list_payouts(
    rider_id: str = Query(None),
    status: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Payout)
    if rider_id:
        query = query.where(Payout.rider_id == rider_id)
    if status:
        query = query.where(Payout.status == status)
    query = query.order_by(Payout.created_at.desc())

    from utils.pagination import paginate
    return await paginate(db, query, PayoutResponse, page, per_page)


@router.get("/stats")
async def payout_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate payout statistics."""
    total_result = await db.execute(select(func.count(Payout.id)))
    total = total_result.scalar() or 0

    settled_result = await db.execute(
        select(func.count(Payout.id)).where(Payout.status == "settled")
    )
    settled = settled_result.scalar() or 0

    failed_result = await db.execute(
        select(func.count(Payout.id)).where(Payout.status == "failed")
    )
    failed = failed_result.scalar() or 0

    avg_amount_result = await db.execute(
        select(func.avg(Payout.amount)).where(Payout.status == "settled")
    )
    avg_amount = float(avg_amount_result.scalar() or 0)

    total_amount_result = await db.execute(
        select(func.sum(Payout.amount)).where(Payout.status == "settled")
    )
    total_amount = float(total_amount_result.scalar() or 0)

    success_rate = round((settled / max(total, 1)) * 100, 1)

    return {
        "total": total,
        "settled": settled,
        "failed": failed,
        "processing": total - settled - failed,
        "avg_amount": round(avg_amount, 2),
        "total_amount": total_amount,
        "success_rate": success_rate,
    }


@router.get("/{payout_id}")
async def get_payout(payout_id: str, db: AsyncSession = Depends(get_db)):
    """Individual payout detail with claim/rider metadata."""
    payout = await db.get(Payout, payout_id)
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")

    claim = await db.get(Claim, payout.claim_id)
    rider = await db.get(Rider, payout.rider_id)

    return {
        "payout": PayoutResponse.model_validate(payout),
        "claim": {
            "id": claim.id if claim else None,
            "status": claim.status if claim else None,
            "confidence": claim.confidence if claim else None,
            "zone_id": claim.zone_id if claim else None,
        },
        "rider": {
            "id": rider.id if rider else None,
            "name": rider.name if rider else None,
            "upi_id": rider.upi_id if rider else None,
        },
    }


@router.post("/{payout_id}/retry")
async def retry_payout(payout_id: str, db: AsyncSession = Depends(get_db)):
    """Retry a failed payout (max 3 retries, idempotency check)."""
    payout = await db.get(Payout, payout_id)
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")

    if payout.status == "settled":
        raise HTTPException(status_code=400, detail="Payout already settled")

    if payout.retry_count >= MAX_RETRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Max retries ({MAX_RETRIES}) exceeded for this payout",
        )

    rider = await db.get(Rider, payout.rider_id)
    upi_id = rider.upi_id if rider else None

    result = await process_payout(payout.rider_id, payout.amount, upi_id)

    payout.retry_count += 1
    payout.status = result["status"]
    payout.upi_ref = result["upi_ref"]
    payout.gateway_response = str(result["gateway_response"])

    if result["status"] == "settled":
        payout.settled_at = datetime.now(timezone.utc)

        # Wire to ZoneReinsurance AMM — absorb payout as loss
        try:
            from defi.reinsurance_pool import absorb_payout_loss
            import asyncio
            asyncio.create_task(
                absorb_payout_loss(float(payout.amount), db)
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Reinsurance loss absorption skipped: {e}")

    await db.commit()

    return {
        "payout_id": payout_id,
        "status": payout.status,
        "retry_count": payout.retry_count,
        "upi_ref": payout.upi_ref,
    }
