"""
DAO PremiumGov — Innovation 06
Proposal lifecycle: create → vote → (actuarial check) → execute/reject/block
Execution writes to GovernanceChaincode on ZoneChain (Hyperledger Fabric).

QUORUM RULES:
  - Standard proposals: 10% of active riders must vote (quorum), simple majority (>50% weight)
  - Supermajority proposals (exclusion add/remove): 75% of weight_for / (weight_for + weight_against)

ACTUARIAL GUARDRAIL ENGINE:
  Before execution of any passed vote, the guardrail engine:
    1. Validates proposed_value is within PARAMETER_SAFE_BANDS
    2. Checks current loss ratio for payout_percentage changes
    3. Blocks execution (status=BLOCKED) with reason if violated
  This cannot be overridden by any vote — it is a hard safety constraint.

CHAINCODE INTEGRATION:
  On execution, a stub call is made to GovernanceChaincode.ExecuteParameterChange().
  In production this calls the Hyperledger Fabric SDK.
  For hackathon demo, execution is recorded in PostgreSQL with a simulated tx hash.
"""

from __future__ import annotations

import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from governance.db_models import (
    GovernanceProposalDB,
    GovernanceVoteDB,
    ZoneTokenBalanceDB,
)
from governance.models import (
    GovernableParameter,
    PARAMETER_SAFE_BANDS,
    ProposalCreate,
    ProposalResponse,
    ProposalStatus,
    VoteRequest,
    VoteResponse,
)
from governance.zone_token import (
    earn_tokens,
    calculate_governance_weight,
    get_or_create_balance,
)
from governance.models import ZoneTokenEvent


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
QUORUM_PCT = 0.10          # 10% of active riders must participate
SIMPLE_MAJORITY = 0.50     # >50% weight for standard proposals
SUPERMAJORITY = 0.75       # 75% for exclusion proposals
MIN_TOKEN_BALANCE_TO_PROPOSE = 50  # Rider must hold ≥50 ZONE to propose


# ─────────────────────────────────────────────
# Proposal lifecycle
# ─────────────────────────────────────────────

async def create_proposal(
    payload: ProposalCreate,
    db: AsyncSession,
    active_rider_count: int = 100,  # fetched from DB in router
) -> ProposalResponse:
    """
    Create a new governance proposal.
    Validates:
      - Proposer holds ≥50 ZONE tokens
      - proposed_value within actuarial safe band
      - No other active proposal for the same parameter by the same rider
    """
    # Check proposer token balance
    balance_record = await get_or_create_balance(payload.proposer_rider_id, db)
    if balance_record.balance < MIN_TOKEN_BALANCE_TO_PROPOSE:
        raise ValueError(
            f"Insufficient ZONE tokens. Need {MIN_TOKEN_BALANCE_TO_PROPOSE}, "
            f"have {balance_record.balance}. Earn more by maintaining coverage."
        )

    # Validate proposed_value against safe band (pre-vote guardrail)
    param = payload.parameter
    band = PARAMETER_SAFE_BANDS.get(param)
    if band and band["min"] is not None and band["max"] is not None:
        if not (band["min"] <= payload.proposed_value <= band["max"]):
            raise ValueError(
                f"Proposed value {payload.proposed_value} for {param.value} is outside "
                f"actuarial safe band [{band['min']}, {band['max']}]. "
                "Proposal rejected by actuarial guardrail."
            )

    # Check for duplicate active proposal
    existing = await db.execute(
        select(GovernanceProposalDB).where(
            and_(
                GovernanceProposalDB.proposer_rider_id == payload.proposer_rider_id,
                GovernanceProposalDB.parameter == param.value,
                GovernanceProposalDB.status == ProposalStatus.ACTIVE.value,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("You already have an active proposal for this parameter.")

    now = datetime.now(timezone.utc)
    ends_at = now + timedelta(hours=payload.voting_period_hours)

    proposal = GovernanceProposalDB(
        proposer_rider_id=payload.proposer_rider_id,
        parameter=param.value,
        proposed_value=payload.proposed_value,
        proposed_exclusion_id=payload.proposed_exclusion_id,
        rationale=payload.rationale,
        status=ProposalStatus.ACTIVE.value,
        voting_ends_at=ends_at,
    )
    db.add(proposal)
    await db.flush()
    await db.commit()
    await db.refresh(proposal)

    return _proposal_to_response(proposal)


async def cast_vote(
    proposal_id: str,
    payload: VoteRequest,
    db: AsyncSession,
    active_rider_count: int = 100,
) -> VoteResponse:
    """
    Cast a vote on an active proposal.
    - Each rider can vote once per proposal (DB unique constraint).
    - Voting power = sqrt(ZONE token balance) (quadratic voting).
    - Awards +3 ZONE governance vote reward.
    - Checks if proposal should be auto-finalised after this vote.
    """
    proposal = await db.get(GovernanceProposalDB, proposal_id)
    if not proposal:
        raise ValueError("Proposal not found")
    if proposal.status != ProposalStatus.ACTIVE.value:
        raise ValueError(f"Proposal is not active (status: {proposal.status})")

    now = datetime.now(timezone.utc)
    if now > proposal.voting_ends_at:
        proposal.status = ProposalStatus.EXPIRED.value
        await db.commit()
        raise ValueError("Voting period has ended")

    # Check for duplicate vote (also enforced by DB unique constraint)
    existing_vote = await db.execute(
        select(GovernanceVoteDB).where(
            and_(
                GovernanceVoteDB.proposal_id == proposal_id,
                GovernanceVoteDB.rider_id == payload.rider_id,
            )
        )
    )
    if existing_vote.scalar_one_or_none():
        raise ValueError("You have already voted on this proposal")

    # Get voter's governance weight
    balance_record = await get_or_create_balance(payload.rider_id, db)
    weight = calculate_governance_weight(balance_record.balance)

    # Record vote
    vote = GovernanceVoteDB(
        proposal_id=proposal_id,
        rider_id=payload.rider_id,
        support=payload.support,
        governance_weight=weight,
        voted_at=now,
    )
    db.add(vote)

    # Update proposal tallies
    if payload.support:
        proposal.votes_for += 1
        proposal.weight_for += weight
    else:
        proposal.votes_against += 1
        proposal.weight_against += weight

    # Check quorum
    total_votes = proposal.votes_for + proposal.votes_against
    total_weight = proposal.weight_for + proposal.weight_against
    quorum_threshold = max(1, int(active_rider_count * QUORUM_PCT))
    proposal.quorum_reached = total_votes >= quorum_threshold

    # Check majority thresholds
    param = GovernableParameter(proposal.parameter)
    band = PARAMETER_SAFE_BANDS.get(param, {})
    needs_supermajority = band.get("supermajority_required", False)

    if total_weight > 0:
        support_ratio = proposal.weight_for / total_weight
        if needs_supermajority:
            proposal.supermajority_reached = support_ratio >= SUPERMAJORITY
        else:
            proposal.supermajority_reached = support_ratio > SIMPLE_MAJORITY

    await db.flush()

    # Award participation tokens (fire-and-forget; don't raise on failure)
    try:
        await earn_tokens(
            rider_id=payload.rider_id,
            event_type=ZoneTokenEvent.GOVERNANCE_VOTE,
            db=db,
            reference_id=proposal_id,
            notes=f"Voted on proposal {proposal_id}",
        )
    except Exception:
        pass  # token award failure should not block vote

    await db.commit()

    return VoteResponse(
        proposal_id=proposal_id,
        rider_id=payload.rider_id,
        support=payload.support,
        governance_weight=weight,
        voted_at=now,
        token_reward=3,
    )


async def finalise_proposals(db: AsyncSession) -> List[str]:
    """
    Scheduled task: finalise all proposals whose voting period has ended.
    Returns list of proposal IDs processed.
    Called by services/scheduler.py.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(GovernanceProposalDB).where(
            and_(
                GovernanceProposalDB.status == ProposalStatus.ACTIVE.value,
                GovernanceProposalDB.voting_ends_at <= now,
            )
        )
    )
    proposals = result.scalars().all()
    processed = []

    for proposal in proposals:
        await _finalise_single_proposal(proposal, db)
        processed.append(proposal.id)

    await db.commit()
    return processed


async def _finalise_single_proposal(
    proposal: GovernanceProposalDB,
    db: AsyncSession,
) -> None:
    """Determine outcome and attempt execution for a single expired proposal."""
    param = GovernableParameter(proposal.parameter)
    band = PARAMETER_SAFE_BANDS.get(param, {})
    needs_supermajority = band.get("supermajority_required", False)

    passed = proposal.quorum_reached and (
        proposal.supermajority_reached if needs_supermajority
        else (proposal.weight_for > proposal.weight_against)
    )

    if not passed:
        proposal.status = ProposalStatus.REJECTED.value
        return

    # ── Actuarial Guardrail Check (post-vote, pre-execution) ─────────────────
    block_reason = await _actuarial_guardrail_check(proposal, db)
    if block_reason:
        proposal.status = ProposalStatus.BLOCKED.value
        proposal.guardrail_block_reason = block_reason
        return

    # ── Execute via GovernanceChaincode ───────────────────────────────────────
    tx_hash = await _execute_on_chain(proposal, db)
    proposal.status = ProposalStatus.EXECUTED.value
    proposal.executed_at = datetime.now(timezone.utc)
    proposal.execution_tx_hash = tx_hash
    proposal.status = ProposalStatus.EXECUTED.value


async def _actuarial_guardrail_check(
    proposal: GovernanceProposalDB,
    db: AsyncSession,
) -> Optional[str]:
    """
    Returns a block reason string if the proposal should be blocked,
    or None if it is safe to execute.

    Checks:
      1. proposed_value still within safe band (rechecked at execution time)
      2. For payout_percentage increases: block if LTM loss ratio > 85%
    """
    param = GovernableParameter(proposal.parameter)
    band = PARAMETER_SAFE_BANDS.get(param)

    if band is None:
        return None  # unknown parameter, allow (shouldn't happen)

    # Re-validate safe band at execution time
    if band["min"] is not None and band["max"] is not None:
        if not (band["min"] <= proposal.proposed_value <= band["max"]):
            return (
                f"Actuarial guardrail: proposed value {proposal.proposed_value} "
                f"now outside safe band [{band['min']}, {band['max']}] at execution time."
            )

    # Loss ratio check for payout percentage increases
    if param == GovernableParameter.PAYOUT_PERCENTAGE:
        loss_ratio_block = band.get("loss_ratio_block")
        if loss_ratio_block:
            current_loss_ratio = await _fetch_ltm_loss_ratio(db)
            if current_loss_ratio > loss_ratio_block:
                return (
                    f"Actuarial guardrail: Cannot increase payout percentage when "
                    f"LTM loss ratio is {current_loss_ratio:.1f}% "
                    f"(threshold: {loss_ratio_block}%). "
                    "Reinsurance pool reserves are insufficient for this change."
                )

    return None


async def _fetch_ltm_loss_ratio(db: AsyncSession) -> float:
    """
    Fetch last-twelve-months loss ratio from payout and premium tables.
    Returns 0.0 if data unavailable (fail-safe: don't block if data missing).
    """
    try:
        from sqlalchemy import text
        from datetime import timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        result = await db.execute(text("""
            SELECT
                COALESCE(SUM(p.amount), 0) AS total_payouts,
                COALESCE(SUM(pp.amount), 1) AS total_premiums
            FROM payouts p
            CROSS JOIN premium_payments pp
            WHERE p.created_at >= :cutoff AND pp.created_at >= :cutoff
        """), {"cutoff": cutoff})
        row = result.fetchone()
        if row and row.total_premiums > 0:
            return round((row.total_payouts / row.total_premiums) * 100, 1)
    except Exception:
        pass
    return 0.0


async def _execute_on_chain(
    proposal: GovernanceProposalDB,
    db: AsyncSession,
) -> str:
    """
    Execute a passed proposal by writing to GovernanceChaincode on ZoneChain.

    PRODUCTION: Call Hyperledger Fabric SDK:
        fabric_client.submit_transaction(
            "GovernanceChaincode",
            "ExecuteParameterChange",
            proposal.parameter,
            str(proposal.proposed_value),
            proposal.id,
        )

    HACKATHON DEMO: Simulate with deterministic tx hash.
    """
    # Simulated Fabric tx hash (deterministic for demo reproducibility)
    payload_str = f"{proposal.id}:{proposal.parameter}:{proposal.proposed_value}"
    tx_hash = "FABRIC-" + hashlib.sha256(payload_str.encode()).hexdigest()[:16].upper()

    # In production, also update the live parameter in the config/settings table
    # For demo: log the execution
    import logging
    logging.getLogger(__name__).info(
        "GovernanceChaincode.ExecuteParameterChange | "
        "proposal=%s param=%s value=%s tx=%s",
        proposal.id, proposal.parameter, proposal.proposed_value, tx_hash,
    )

    return tx_hash


# ─────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────

async def list_proposals(
    db: AsyncSession,
    status: Optional[str] = None,
    limit: int = 20,
) -> List[ProposalResponse]:
    query = select(GovernanceProposalDB).order_by(GovernanceProposalDB.created_at.desc())
    if status:
        query = query.where(GovernanceProposalDB.status == status)
    query = query.limit(limit)
    result = await db.execute(query)
    return [_proposal_to_response(p) for p in result.scalars().all()]


async def get_proposal(proposal_id: str, db: AsyncSession) -> ProposalResponse:
    proposal = await db.get(GovernanceProposalDB, proposal_id)
    if not proposal:
        raise ValueError("Proposal not found")
    return _proposal_to_response(proposal)


async def count_proposals_voted_by_rider(
    rider_id: str,
    db: AsyncSession,
    days: int = 90,
) -> Tuple[int, int]:
    """Returns (voted_count, total_proposals_in_period)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    voted_q = await db.execute(
        select(func.count()).select_from(GovernanceVoteDB).where(
            and_(
                GovernanceVoteDB.rider_id == rider_id,
                GovernanceVoteDB.voted_at >= cutoff,
            )
        )
    )
    voted = voted_q.scalar() or 0

    total_q = await db.execute(
        select(func.count()).select_from(GovernanceProposalDB).where(
            GovernanceProposalDB.created_at >= cutoff
        )
    )
    total = total_q.scalar() or 0

    return int(voted), int(total)


def _proposal_to_response(p: GovernanceProposalDB) -> ProposalResponse:
    return ProposalResponse(
        id=p.id,
        proposer_rider_id=p.proposer_rider_id,
        parameter=GovernableParameter(p.parameter),
        proposed_value=p.proposed_value,
        proposed_exclusion_id=p.proposed_exclusion_id,
        rationale=p.rationale,
        status=ProposalStatus(p.status),
        votes_for=p.votes_for,
        votes_against=p.votes_against,
        weight_for=p.weight_for,
        weight_against=p.weight_against,
        quorum_reached=p.quorum_reached,
        supermajority_reached=p.supermajority_reached,
        voting_ends_at=p.voting_ends_at,
        executed_at=p.executed_at,
        execution_tx_hash=p.execution_tx_hash,
        guardrail_block_reason=p.guardrail_block_reason,
        created_at=p.created_at,
    )
