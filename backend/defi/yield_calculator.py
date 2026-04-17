"""
Yield Calculator — Premium flow distribution to reinsurance LP tranche holders.
Called weekly by services/scheduler.py after premium collection.

Distribution logic:
  1. Collect total weekly premium inflow
  2. Subtract total payouts for the week (net pool income)
  3. Distribute net income to active LP positions proportional to:
     - Their pool share within their tranche
     - Their tranche's yield rate (Senior gets least, Junior gets most)
  4. Record the YieldDistributionRecord for audit trail
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, text

from governance.db_models import (
    ReinsurancePositionDB,
    ReinsuranceYieldDistributionDB,
)
from governance.models import Tranche, TRANCHE_CONFIG, YieldDistributionRecord

logger = logging.getLogger(__name__)

# Fraction of net pool income distributed to LPs each week (rest stays in reserve)
LP_DISTRIBUTION_FRACTION = 0.85  # 85% to LPs, 15% retained as surplus buffer


async def run_weekly_yield_distribution(
    db: AsyncSession,
    period_start: datetime,
    period_end: datetime,
) -> YieldDistributionRecord:
    """
    Execute weekly yield distribution to all active LP positions.
    Called by scheduler every 7 days after policy renewal cycle.

    Returns a YieldDistributionRecord for audit and compliance.
    """
    # Fetch premium inflow and payout outflow for the period
    total_premium_inflow = await _sum_premiums(db, period_start, period_end)
    total_payout_outflow = await _sum_payouts(db, period_start, period_end)

    net_pool_income = max(0.0, total_premium_inflow - total_payout_outflow)
    distributable = net_pool_income * LP_DISTRIBUTION_FRACTION

    # Fetch all active LP positions
    result = await db.execute(
        select(ReinsurancePositionDB).where(ReinsurancePositionDB.is_active == True)
    )
    positions = result.scalars().all()

    # Group positions by tranche to compute pool totals
    tranche_totals: Dict[str, float] = {t.value: 0.0 for t in Tranche}
    for p in positions:
        tranche_totals[p.tranche] = tranche_totals.get(p.tranche, 0.0) + p.amount_staked

    total_staked = sum(tranche_totals.values())
    if total_staked == 0 or distributable == 0:
        logger.info("No yield to distribute (pool empty or net income = 0)")
        return _record_empty_distribution(period_start, period_end, total_premium_inflow, total_payout_outflow)

    # Allocate distribution budget to tranches proportionally by pool share
    # (Senior gets 70% of pool allocation, Mezzanine 20%, Junior 10%)
    tranche_allocation: Dict[str, float] = {}
    for tranche in Tranche:
        config = TRANCHE_CONFIG[tranche]
        tranche_allocation[tranche.value] = distributable * config["pool_share"]

    # Distribute to each LP position within its tranche
    senior_distributed = 0.0
    mezzanine_distributed = 0.0
    junior_distributed = 0.0

    for position in positions:
        tranche_total = tranche_totals.get(position.tranche, 1.0)
        if tranche_total == 0:
            continue
        position_share = position.amount_staked / tranche_total
        allocation = tranche_allocation.get(position.tranche, 0.0) * position_share
        weekly_yield = round(allocation, 2)

        # In production: credit the LP's external wallet/account
        # For demo: log it
        logger.debug(
            "Yield distribution | provider=%s tranche=%s amount=%.2f",
            position.provider_id, position.tranche, weekly_yield,
        )

        if position.tranche == Tranche.SENIOR.value:
            senior_distributed += weekly_yield
        elif position.tranche == Tranche.MEZZANINE.value:
            mezzanine_distributed += weekly_yield
        else:
            junior_distributed += weekly_yield

    # Record distribution
    now = datetime.now(timezone.utc)
    dist_record = ReinsuranceYieldDistributionDB(
        period_start=period_start,
        period_end=period_end,
        total_premium_inflow=round(total_premium_inflow, 2),
        total_payout_outflow=round(total_payout_outflow, 2),
        net_pool_income=round(net_pool_income, 2),
        senior_yield_distributed=round(senior_distributed, 2),
        mezzanine_yield_distributed=round(mezzanine_distributed, 2),
        junior_yield_distributed=round(junior_distributed, 2),
        distributed_at=now,
    )
    db.add(dist_record)
    await db.flush()
    await db.commit()
    await db.refresh(dist_record)

    logger.info(
        "Yield distribution complete | total=%.2f senior=%.2f mezz=%.2f junior=%.2f",
        senior_distributed + mezzanine_distributed + junior_distributed,
        senior_distributed, mezzanine_distributed, junior_distributed,
    )

    return YieldDistributionRecord(
        distribution_id=dist_record.distribution_id,
        period_start=period_start,
        period_end=period_end,
        total_premium_inflow=dist_record.total_premium_inflow,
        total_payout_outflow=dist_record.total_payout_outflow,
        net_pool_income=dist_record.net_pool_income,
        senior_yield_distributed=dist_record.senior_yield_distributed,
        mezzanine_yield_distributed=dist_record.mezzanine_yield_distributed,
        junior_yield_distributed=dist_record.junior_yield_distributed,
        distributed_at=dist_record.distributed_at,
    )


async def get_distribution_history(
    db: AsyncSession,
    limit: int = 12,
) -> List[YieldDistributionRecord]:
    """Fetch recent yield distribution history for LP reporting."""
    result = await db.execute(
        select(ReinsuranceYieldDistributionDB)
        .order_by(ReinsuranceYieldDistributionDB.distributed_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        YieldDistributionRecord(
            distribution_id=r.distribution_id,
            period_start=r.period_start,
            period_end=r.period_end,
            total_premium_inflow=r.total_premium_inflow,
            total_payout_outflow=r.total_payout_outflow,
            net_pool_income=r.net_pool_income,
            senior_yield_distributed=r.senior_yield_distributed,
            mezzanine_yield_distributed=r.mezzanine_yield_distributed,
            junior_yield_distributed=r.junior_yield_distributed,
            distributed_at=r.distributed_at,
        )
        for r in rows
    ]


# ─────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────

async def _sum_premiums(db: AsyncSession, start: datetime, end: datetime) -> float:
    try:
        result = await db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM premium_payments WHERE created_at BETWEEN :s AND :e"),
            {"s": start, "e": end},
        )
        return float(result.scalar() or 0)
    except Exception as ex:
        logger.warning("Could not fetch premiums: %s", ex)
        return 0.0


async def _sum_payouts(db: AsyncSession, start: datetime, end: datetime) -> float:
    try:
        result = await db.execute(
            text("SELECT COALESCE(SUM(amount), 0) FROM payouts WHERE created_at BETWEEN :s AND :e"),
            {"s": start, "e": end},
        )
        return float(result.scalar() or 0)
    except Exception as ex:
        logger.warning("Could not fetch payouts: %s", ex)
        return 0.0


def _record_empty_distribution(
    period_start: datetime,
    period_end: datetime,
    premiums: float,
    payouts: float,
) -> YieldDistributionRecord:
    now = datetime.now(timezone.utc)
    return YieldDistributionRecord(
        distribution_id=f"RDIST-{uuid.uuid4().hex[:8].upper()}",
        period_start=period_start,
        period_end=period_end,
        total_premium_inflow=round(premiums, 2),
        total_payout_outflow=round(payouts, 2),
        net_pool_income=0.0,
        senior_yield_distributed=0.0,
        mezzanine_yield_distributed=0.0,
        junior_yield_distributed=0.0,
        distributed_at=now,
    )
