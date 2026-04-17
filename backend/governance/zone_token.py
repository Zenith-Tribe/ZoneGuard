"""
ZONE Token Manager — Innovation 06: DAO PremiumGov
Non-transferable governance token for ZoneGuard riders.

NON-TRANSFERABILITY ENFORCEMENT:
  - No transfer() function exists in this module.
  - All mutations are keyed to rider_id; no cross-rider delta functions exist.
  - On ZoneChain (Hyperledger Fabric), GovernanceChaincode mirrors these rules:
      * ctx.GetClientIdentity().GetID() must match token owner on every mutation.
      * No TransferToken chaincode function is implemented.
      * This is enforced at chaincode level, not just application level.

GAMING MITIGATIONS:
  - Referral cap: max 3 referral bonuses per rider per 365-day rolling window.
  - S4 check-in: max 1 per 7-day window (enforced by last_s4_checkin timestamp).
  - Appeal bonus: 14-day cooldown after any appeal resolves.
  - Balance floor: 0 (can never go negative).

GOVERNANCE WEIGHT:
  - Quadratic voting: weight = sqrt(balance) to prevent whale dominance.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from governance.db_models import (
    ZoneTokenBalanceDB,
    ZoneTokenTransactionDB,
)
from governance.models import (
    ZoneTokenEvent,
    ZoneTokenBalance,
    ZoneTokenTransaction,
    ZONE_TOKEN_DELTAS,
    GovernanceHealthScore,
)


# ─────────────────────────────────────────────
# Rate-limit constants
# ─────────────────────────────────────────────
REFERRAL_ANNUAL_CAP = 3
S4_CHECKIN_COOLDOWN_DAYS = 7
APPEAL_COOLDOWN_DAYS = 14
GOVERNANCE_VOTE_COOLDOWN_HOURS = 0  # no cooldown — vote once per proposal (enforced in dao_gov.py)


# ─────────────────────────────────────────────
# Core token operations
# ─────────────────────────────────────────────

async def get_or_create_balance(rider_id: str, db: AsyncSession) -> ZoneTokenBalanceDB:
    """Fetch or initialise a rider's ZONE token balance record."""
    record = await db.get(ZoneTokenBalanceDB, rider_id)
    if not record:
        record = ZoneTokenBalanceDB(
            rider_id=rider_id,
            balance=0,
            lifetime_earned=0,
            lifetime_burned=0,
            last_s4_checkin=None,
            last_appeal_resolved=None,
            referral_count_this_year=0,
            referral_year=datetime.now(timezone.utc).year,
        )
        db.add(record)
        await db.flush()
    return record


async def earn_tokens(
    rider_id: str,
    event_type: ZoneTokenEvent,
    db: AsyncSession,
    reference_id: Optional[str] = None,
    manual_delta: Optional[int] = None,
    notes: Optional[str] = None,
) -> ZoneTokenTransaction:
    """
    Credit (or debit) ZONE tokens for a rider, enforcing all rate limits.
    Returns the resulting transaction record.
    Raises ValueError for rate-limit violations.

    NOTE: This function intentionally has no `to_rider_id` parameter — 
    tokens cannot be transferred between riders.
    """
    record = await get_or_create_balance(rider_id, db)
    now = datetime.now(timezone.utc)

    # Determine delta
    if event_type == ZoneTokenEvent.ADMIN_ADJUSTMENT:
        if manual_delta is None:
            raise ValueError("manual_delta required for ADMIN_ADJUSTMENT")
        delta = manual_delta
    else:
        delta = ZONE_TOKEN_DELTAS[event_type]

    # ── Rate-limit checks ──────────────────────────────────────────────────────

    if event_type == ZoneTokenEvent.REFERRAL_ACTIVE:
        # Reset annual counter if year has changed
        if record.referral_year != now.year:
            record.referral_count_this_year = 0
            record.referral_year = now.year
        if record.referral_count_this_year >= REFERRAL_ANNUAL_CAP:
            raise ValueError(
                f"Referral bonus cap reached ({REFERRAL_ANNUAL_CAP}/year). "
                "No further referral ZONE tokens until next calendar year."
            )
        record.referral_count_this_year += 1

    elif event_type == ZoneTokenEvent.S4_CHECKIN:
        if record.last_s4_checkin:
            days_since = (now - record.last_s4_checkin).days
            if days_since < S4_CHECKIN_COOLDOWN_DAYS:
                raise ValueError(
                    f"S4 check-in cooldown active. Next eligible in "
                    f"{S4_CHECKIN_COOLDOWN_DAYS - days_since} day(s)."
                )
        record.last_s4_checkin = now

    elif event_type in (ZoneTokenEvent.APPEAL_SUCCESSFUL, ZoneTokenEvent.APPEAL_FALSE):
        if record.last_appeal_resolved:
            days_since = (now - record.last_appeal_resolved).days
            if days_since < APPEAL_COOLDOWN_DAYS:
                raise ValueError(
                    f"Appeal cooldown active ({APPEAL_COOLDOWN_DAYS}-day window). "
                    f"Next eligible in {APPEAL_COOLDOWN_DAYS - days_since} day(s)."
                )
        record.last_appeal_resolved = now

    # ── Apply delta with floor at 0 ────────────────────────────────────────────
    new_balance = max(0, record.balance + delta)
    actual_delta = new_balance - record.balance  # may differ from delta if floored

    if actual_delta >= 0:
        record.lifetime_earned += actual_delta
    else:
        record.lifetime_burned += abs(actual_delta)

    record.balance = new_balance
    record.updated_at = now

    # ── Persist transaction log ────────────────────────────────────────────────
    tx = ZoneTokenTransactionDB(
        id=f"ZTX-{uuid.uuid4().hex[:10].upper()}",
        rider_id=rider_id,
        event_type=event_type.value,
        delta=actual_delta,
        balance_after=new_balance,
        reference_id=reference_id,
        notes=notes,
        created_at=now,
    )
    db.add(tx)
    await db.flush()

    return ZoneTokenTransaction(
        id=tx.id,
        rider_id=rider_id,
        event_type=event_type,
        delta=actual_delta,
        balance_after=new_balance,
        reference_id=reference_id,
        notes=notes,
        created_at=now,
    )


async def get_balance(rider_id: str, db: AsyncSession) -> ZoneTokenBalance:
    """Return the current balance and governance weight for a rider."""
    record = await get_or_create_balance(rider_id, db)
    await db.commit()
    return ZoneTokenBalance(
        rider_id=rider_id,
        balance=record.balance,
        lifetime_earned=record.lifetime_earned,
        lifetime_burned=record.lifetime_burned,
        governance_weight=calculate_governance_weight(record.balance),
        updated_at=record.updated_at or datetime.now(timezone.utc),
    )


async def get_transaction_history(
    rider_id: str,
    db: AsyncSession,
    limit: int = 50,
) -> List[ZoneTokenTransaction]:
    """Return the most recent token transactions for a rider."""
    result = await db.execute(
        select(ZoneTokenTransactionDB)
        .where(ZoneTokenTransactionDB.rider_id == rider_id)
        .order_by(ZoneTokenTransactionDB.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        ZoneTokenTransaction(
            id=r.id,
            rider_id=r.rider_id,
            event_type=ZoneTokenEvent(r.event_type),
            delta=r.delta,
            balance_after=r.balance_after,
            reference_id=r.reference_id,
            notes=r.notes,
            created_at=r.created_at,
        )
        for r in rows
    ]


# ─────────────────────────────────────────────
# Governance weight calculation
# ─────────────────────────────────────────────

def calculate_governance_weight(balance: int) -> float:
    """
    Quadratic voting weight: weight = sqrt(balance).
    Prevents whale dominance while rewarding long-tenure riders.

    Examples:
      100 tokens → 10.0 weight
      400 tokens → 20.0 weight
      1000 tokens → 31.6 weight
    """
    return round(math.sqrt(max(0, balance)), 4)


# ─────────────────────────────────────────────
# Governance Health Score
# ─────────────────────────────────────────────

async def compute_governance_health_score(
    rider_id: str,
    db: AsyncSession,
    claim_free_weeks: int = 0,
) -> GovernanceHealthScore:
    """
    Compute a rider's Governance Health Score (0-100).
    Components:
      - Token balance component (40%): normalised against 500 token benchmark
      - Participation component (30%): proposals voted / proposals active (last 90 days)
      - Claims-free component (30%): claim-free weeks / 52 (max 1 year)
    """
    from governance.dao_gov import count_proposals_voted_by_rider

    now = datetime.now(timezone.utc)
    record = await get_or_create_balance(rider_id, db)

    # Token component (40%) — benchmark: 500 tokens = full score
    token_norm = min(record.balance / 500.0, 1.0)
    token_component = token_norm * 40.0

    # Participation component (30%)
    voted, total_active = await count_proposals_voted_by_rider(rider_id, db, days=90)
    participation_norm = (voted / max(total_active, 1)) if total_active > 0 else 0.0
    participation_component = participation_norm * 30.0

    # Claims-free component (30%)
    claims_free_norm = min(claim_free_weeks / 52.0, 1.0)
    claims_free_component = claims_free_norm * 30.0

    score = round(token_component + participation_component + claims_free_component, 1)

    if score >= 85:
        label = "Champion"
    elif score >= 65:
        label = "Active"
    elif score >= 35:
        label = "Emerging"
    else:
        label = "Inactive"

    return GovernanceHealthScore(
        rider_id=rider_id,
        score=score,
        token_balance_component=round(token_component, 1),
        participation_component=round(participation_component, 1),
        claims_free_component=round(claims_free_component, 1),
        label=label,
        premium_discount_eligible=score >= 75.0,
        computed_at=now,
    )
