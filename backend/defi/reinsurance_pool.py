"""
ZoneReinsurance Reserve Pool — Innovation 08 (Simplified SPV Model)
Innovation 08: ZoneReinsurance AMM

DESIGN DECISION: Simplified Reserve Pool (not full AMM)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IRDAI 2024 Sandbox framework requires prior written approval for:
  - Dynamic pricing curves (AMM bonding curves)
  - Automated market making with variable exchange rates

BUILT FOR HACKATHON: Simplified yield-earning reserve pool:
  - Fixed tranche ratios (Senior 70% / Mezzanine 20% / Junior 10%)
  - Fixed yield bands per tranche (configurable, not dynamic)
  - Loss waterfall: Junior absorbs first, then Mezzanine, then Senior
  - IRDAI-defensible as "catastrophe reserve fund with LP participation"

EXTENSION PATH (post-IRDAI approval):
  - Replace _calculate_expected_yield() with bonding curve:
      yield = f(utilization_ratio, tranche_risk, time_to_unlock)
  - Add liquidity depth parameter (k) for constant-product AMM
  - Implement dynamic rebalancing between tranches based on loss history
  - ZoneReinsurance SPV: IRDAI/SB/2024/ZG-001 reference number
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TRANCHE STRUCTURE:
  Senior    (70%): 9-11% yield, last-in-loss
  Mezzanine (20%): 14-18% yield, pro-rata loss
  Junior    (10%): 25-30% yield, first-loss

LOSS WATERFALL EXAMPLE:
  Total pool = Rs. 10,00,000. Payout event = Rs. 80,000 (8% loss):
    Junior (Rs. 1,00,000) absorbs Rs. 80,000 → Junior NAV = Rs. 20,000
    Mezzanine and Senior are unaffected.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from governance.db_models import (
    ReinsurancePositionDB,
    ReinsuranceYieldDistributionDB,
)
from governance.models import (
    Tranche,
    TRANCHE_CONFIG,
    StakeRequest,
    StakeResponse,
    PoolState,
    YieldDistributionRecord,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Pool operations
# ─────────────────────────────────────────────

async def stake_into_pool(
    payload: StakeRequest,
    db: AsyncSession,
) -> StakeResponse:
    """
    Stake capital into a reinsurance tranche.
    90-day minimum lock per IRDAI sandbox framework.
    """
    config = TRANCHE_CONFIG[payload.tranche]
    expected_yield = _calculate_expected_yield(payload.tranche, payload.amount_inr)
    now = datetime.now(timezone.utc)

    # Calculate pool share percentage
    pool_state = await get_pool_state(db)
    tranche_pool = getattr(pool_state, f"{payload.tranche.value}_pool_inr")
    new_tranche_total = tranche_pool + payload.amount_inr
    pool_share_pct = round((payload.amount_inr / max(new_tranche_total, 1)) * 100, 4)

    position = ReinsurancePositionDB(
        provider_id=payload.provider_id,
        provider_type=payload.provider_type,
        tranche=payload.tranche.value,
        amount_staked=payload.amount_inr,
        pool_share_pct=pool_share_pct,
        expected_annual_yield_pct=expected_yield,
        lock_period_days=90,
        staked_at=now,
        unlock_at=now + timedelta(days=90),
    )
    db.add(position)
    await db.flush()
    await db.commit()
    await db.refresh(position)

    logger.info(
        "Reinsurance stake | provider=%s tranche=%s amount=%.0f yield=%.1f%%",
        payload.provider_id, payload.tranche.value, payload.amount_inr, expected_yield,
    )

    return StakeResponse(
        position_id=position.position_id,
        provider_id=payload.provider_id,
        tranche=payload.tranche,
        amount_staked=payload.amount_inr,
        pool_share_pct=pool_share_pct,
        expected_annual_yield_pct=expected_yield,
        staked_at=now,
        lock_period_days=90,
    )


async def get_pool_state(db: AsyncSession) -> PoolState:
    """Return the current aggregate state of the reinsurance pool."""
    # Aggregate active positions by tranche
    result = await db.execute(
        select(
            ReinsurancePositionDB.tranche,
            func.sum(ReinsurancePositionDB.amount_staked).label("total"),
            func.count(ReinsurancePositionDB.position_id).label("count"),
        )
        .where(ReinsurancePositionDB.is_active == True)
        .group_by(ReinsurancePositionDB.tranche)
    )
    rows = result.all()

    tranche_totals: Dict[str, float] = {t.value: 0.0 for t in Tranche}
    active_positions = 0
    for row in rows:
        tranche_totals[row.tranche] = float(row.total or 0)
        active_positions += int(row.count or 0)

    senior_pool = tranche_totals[Tranche.SENIOR.value]
    mezzanine_pool = tranche_totals[Tranche.MEZZANINE.value]
    junior_pool = tranche_totals[Tranche.JUNIOR.value]
    total_pool = senior_pool + mezzanine_pool + junior_pool

    # Fetch last yield distribution
    last_dist_result = await db.execute(
        select(ReinsuranceYieldDistributionDB.distributed_at)
        .order_by(ReinsuranceYieldDistributionDB.distributed_at.desc())
        .limit(1)
    )
    last_yield_dist = last_dist_result.scalar()

    # Fetch weekly premium and payout totals (last 7 days)
    from sqlalchemy import text
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        prem_result = await db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM premium_payments WHERE created_at >= :cutoff"),
            {"cutoff": week_ago},
        )
        total_premiums_week = float(prem_result.scalar() or 0)

        pay_result = await db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payouts WHERE created_at >= :cutoff"),
            {"cutoff": week_ago},
        )
        total_payouts_week = float(pay_result.scalar() or 0)
    except Exception:
        total_premiums_week = 0.0
        total_payouts_week = 0.0

    loss_ratio = (
        round((total_payouts_week / total_premiums_week) * 100, 1)
        if total_premiums_week > 0 else 0.0
    )
    pool_utilization = (
        round((total_payouts_week / max(total_pool, 1)) * 100, 1)
        if total_pool > 0 else 0.0
    )

    return PoolState(
        total_pool_inr=round(total_pool, 2),
        senior_pool_inr=round(senior_pool, 2),
        mezzanine_pool_inr=round(mezzanine_pool, 2),
        junior_pool_inr=round(junior_pool, 2),
        total_premiums_collected_week=round(total_premiums_week, 2),
        total_payouts_week=round(total_payouts_week, 2),
        loss_ratio_ltm=loss_ratio,
        pool_utilization_pct=pool_utilization,
        active_positions=active_positions,
        last_yield_distribution=last_yield_dist,
    )


async def get_provider_positions(
    provider_id: str,
    db: AsyncSession,
) -> List[StakeResponse]:
    """Get all active positions for a capital provider."""
    result = await db.execute(
        select(ReinsurancePositionDB).where(
            and_(
                ReinsurancePositionDB.provider_id == provider_id,
                ReinsurancePositionDB.is_active == True,
            )
        )
    )
    positions = result.scalars().all()
    return [
        StakeResponse(
            position_id=p.position_id,
            provider_id=p.provider_id,
            tranche=Tranche(p.tranche),
            amount_staked=p.amount_staked,
            pool_share_pct=p.pool_share_pct,
            expected_annual_yield_pct=p.expected_annual_yield_pct,
            staked_at=p.staked_at,
            lock_period_days=p.lock_period_days,
        )
        for p in positions
    ]


async def withdraw_position(
    position_id: str,
    provider_id: str,
    db: AsyncSession,
) -> Dict:
    """
    Withdraw a staked position after lock period expires.
    Returns final yield earned.
    """
    position = await db.get(ReinsurancePositionDB, position_id)
    if not position:
        raise ValueError("Position not found")
    if position.provider_id != provider_id:
        raise ValueError("Position does not belong to this provider")
    if not position.is_active:
        raise ValueError("Position already withdrawn")

    now = datetime.now(timezone.utc)
    if position.unlock_at and now < position.unlock_at:
        days_remaining = (position.unlock_at - now).days
        raise ValueError(
            f"Lock period not expired. {days_remaining} days remaining. "
            "Early withdrawal not permitted under IRDAI sandbox framework."
        )

    # Calculate actual yield earned
    days_staked = max((now - position.staked_at).days, 1)
    annual_yield = position.expected_annual_yield_pct / 100.0
    yield_earned = round(position.amount_staked * annual_yield * (days_staked / 365), 2)
    total_return = position.amount_staked + yield_earned

    position.is_active = False
    position.withdrawn_at = now
    await db.commit()

    return {
        "position_id": position_id,
        "amount_staked": position.amount_staked,
        "days_staked": days_staked,
        "yield_earned": yield_earned,
        "total_return": total_return,
        "annual_yield_pct": position.expected_annual_yield_pct,
        "withdrawn_at": now.isoformat(),
    }


# ─────────────────────────────────────────────
# Yield calculation (simplified — not full AMM)
# ─────────────────────────────────────────────

def _calculate_expected_yield(tranche: Tranche, amount: float) -> float:
    """
    Simplified fixed-band yield assignment.
    Uses midpoint of the tranche's yield band.

    EXTENSION PATH (full AMM):
      Replace with bonding curve:
        yield = yield_min + (yield_max - yield_min) * utilization_ratio^alpha
      Where alpha controls the curve steepness and utilization_ratio
      is derived from (total_payouts_LTM / total_pool).
    """
    config = TRANCHE_CONFIG[tranche]
    midpoint = (config["yield_min_pct"] + config["yield_max_pct"]) / 2.0
    return round(midpoint, 2)


# ─────────────────────────────────────────────
# Payout loss absorption (waterfall)
# ─────────────────────────────────────────────

async def absorb_payout_loss(
    payout_amount: float,
    db: AsyncSession,
) -> Dict:
    """
    Apply a payout event to the pool using the loss waterfall.
    Junior absorbs first, then Mezzanine, then Senior.
    Called by the claims pipeline after a payout is issued.

    Returns a breakdown of which tranche absorbed how much.
    """
    pool = await get_pool_state(db)
    remaining = payout_amount
    absorption: Dict[str, float] = {}

    # Loss waterfall order: Junior → Mezzanine → Senior
    for tranche, pool_amt in [
        (Tranche.JUNIOR, pool.junior_pool_inr),
        (Tranche.MEZZANINE, pool.mezzanine_pool_inr),
        (Tranche.SENIOR, pool.senior_pool_inr),
    ]:
        if remaining <= 0:
            absorption[tranche.value] = 0.0
            continue
        absorbed = min(remaining, pool_amt)
        absorption[tranche.value] = absorbed
        remaining -= absorbed

    unfunded = max(0.0, remaining)

    logger.info(
        "Reinsurance loss absorption | payout=%.0f junior=%.0f mezz=%.0f senior=%.0f unfunded=%.0f",
        payout_amount,
        absorption.get(Tranche.JUNIOR.value, 0),
        absorption.get(Tranche.MEZZANINE.value, 0),
        absorption.get(Tranche.SENIOR.value, 0),
        unfunded,
    )

    return {
        "payout_amount": payout_amount,
        "absorption": absorption,
        "unfunded_amount": unfunded,
        "pool_sufficient": unfunded == 0.0,
    }
