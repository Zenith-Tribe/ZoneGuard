"""
ZoneReinsurance Pool FastAPI Router — Innovation 08
Prefix: /api/v1/reinsurance

Endpoints:
  GET  /pool/state                        — aggregate pool state
  GET  /pool/tranches                     — tranche configuration
  POST /pool/stake                        — stake capital into a tranche
  GET  /pool/positions/{provider_id}      — get provider's positions
  POST /pool/positions/{position_id}/withdraw — withdraw after lock period
  GET  /pool/yield-history                — recent yield distributions
  POST /pool/distribute-yield             — admin: run yield distribution
  POST /pool/absorb-loss                  — system: absorb payout loss

NOTE: This router exposes the simplified SPV model.
The full AMM extension is documented in reinsurance_pool.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone, timedelta

from db.database import get_db
from defi import reinsurance_pool, yield_calculator
from governance.models import StakeRequest, TRANCHE_CONFIG, Tranche

router = APIRouter(prefix="/api/v1/reinsurance", tags=["reinsurance"])


@router.get("/pool/state")
async def get_pool_state(db: AsyncSession = Depends(get_db)):
    """
    Get the current aggregate state of the ZoneReinsurance pool.
    Includes total capital, per-tranche breakdown, and loss ratio.
    """
    state = await reinsurance_pool.get_pool_state(db)
    return state


@router.get("/pool/tranches")
async def get_tranche_info():
    """
    Get the configuration for all three reinsurance tranches.
    Includes yield ranges, pool shares, and loss priority.
    """
    return {
        "tranches": [
            {
                "tranche": tranche.value,
                **config,
                "irdai_framework": "IRDAI/SB/2024/ZG-001",
                "model_type": "simplified_spv",  # not full AMM
            }
            for tranche, config in TRANCHE_CONFIG.items()
        ],
        "model_note": (
            "Simplified reserve pool model (IRDAI sandbox compliant). "
            "Full AMM with dynamic pricing curves is documented as an extension "
            "pending IRDAI full-sandbox approval."
        ),
    }


@router.post("/pool/stake")
async def stake_capital(
    payload: StakeRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Stake capital into the reinsurance pool.
    Minimum 90-day lock per IRDAI sandbox framework.
    Tranche allocation: Senior (70%) / Mezzanine (20%) / Junior (10%).
    """
    try:
        position = await reinsurance_pool.stake_into_pool(payload, db)
        return {
            "position": position,
            "message": (
                f"Successfully staked ₹{payload.amount_inr:,.0f} into "
                f"{payload.tranche.value.capitalize()} tranche. "
                f"Expected yield: {position.expected_annual_yield_pct:.1f}% p.a. "
                f"Lock period: {position.lock_period_days} days."
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/pool/positions/{provider_id}")
async def get_positions(provider_id: str, db: AsyncSession = Depends(get_db)):
    """Get all active staking positions for a capital provider."""
    positions = await reinsurance_pool.get_provider_positions(provider_id, db)
    total_staked = sum(p.amount_staked for p in positions)
    return {
        "provider_id": provider_id,
        "positions": positions,
        "total_staked": total_staked,
        "active_count": len(positions),
    }


@router.post("/pool/positions/{position_id}/withdraw")
async def withdraw_position(
    position_id: str,
    provider_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Withdraw a staked position after the 90-day lock period.
    Early withdrawal not permitted under IRDAI sandbox framework.
    """
    try:
        result = await reinsurance_pool.withdraw_position(position_id, provider_id, db)
        return {
            "result": result,
            "message": (
                f"Withdrawal successful. "
                f"Yield earned: ₹{result['yield_earned']:,.2f} over {result['days_staked']} days."
            ),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/pool/yield-history")
async def get_yield_history(
    limit: int = Query(default=12, le=52),
    db: AsyncSession = Depends(get_db),
):
    """Get recent weekly yield distribution history for LP reporting."""
    history = await yield_calculator.get_distribution_history(db, limit=limit)
    return {"distributions": history, "count": len(history)}


@router.post("/pool/distribute-yield")
async def distribute_yield(
    db: AsyncSession = Depends(get_db),
):
    """
    Admin endpoint: run the weekly yield distribution.
    Normally called by services/scheduler.py every 7 days.
    """
    now = datetime.now(timezone.utc)
    period_end = now
    period_start = now - timedelta(days=7)

    try:
        record = await yield_calculator.run_weekly_yield_distribution(
            db=db,
            period_start=period_start,
            period_end=period_end,
        )
        return {
            "distribution": record,
            "message": (
                f"Yield distributed. "
                f"Net income: ₹{record.net_pool_income:,.2f} | "
                f"Senior: ₹{record.senior_yield_distributed:,.2f} | "
                f"Mezzanine: ₹{record.mezzanine_yield_distributed:,.2f} | "
                f"Junior: ₹{record.junior_yield_distributed:,.2f}"
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pool/absorb-loss")
async def absorb_loss(
    payout_amount: float = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    """
    System endpoint: apply a payout loss event to the pool waterfall.
    Called by claims pipeline after a payout is issued.
    Junior tranche absorbs first, then Mezzanine, then Senior.
    """
    try:
        result = await reinsurance_pool.absorb_payout_loss(payout_amount, db)
        return {
            "absorption": result,
            "message": (
                "Loss absorbed via waterfall. "
                + (
                    "Pool fully covered this payout."
                    if result["pool_sufficient"]
                    else f"WARNING: Unfunded amount ₹{result['unfunded_amount']:,.2f}"
                )
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
