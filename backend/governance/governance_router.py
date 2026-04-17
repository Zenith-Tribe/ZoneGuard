"""
Governance FastAPI Router — Innovations 06 + 07
Prefix: /api/v1/governance

Endpoints:
  ZONE Tokens:
    GET  /tokens/{rider_id}                  — balance + governance weight
    GET  /tokens/{rider_id}/history          — transaction history
    POST /tokens/{rider_id}/earn             — earn tokens (admin/system)
    GET  /tokens/{rider_id}/health-score     — governance health score

  Proposals:
    GET  /proposals                          — list proposals
    POST /proposals                          — create proposal
    GET  /proposals/{proposal_id}            — get proposal
    POST /proposals/{proposal_id}/vote       — cast vote
    POST /proposals/finalise                 — admin: finalise expired proposals

  SoulboundNFTs:
    GET  /nfts/{rider_id}                    — list rider's NFTs
    POST /nfts/{rider_id}/mint               — mint weekly NFT (system)
    GET  /nfts/{rider_id}/continuity-score   — Coverage Continuity Score

  Governance Health:
    GET  /parameters                         — current governable parameter values
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from db.database import get_db
from models.rider import Rider

from governance import dao_gov, zone_token, soulbound_nft
from governance.models import (
    ProposalCreate,
    VoteRequest,
    TokenEarnRequest,
    ZoneTokenEvent,
    PARAMETER_SAFE_BANDS,
    ZONE_TOKEN_DELTAS,
)

router = APIRouter(prefix="/api/v1/governance", tags=["governance"])


# ─────────────────────────────────────────────
# ZONE Token endpoints
# ─────────────────────────────────────────────

@router.get("/tokens/{rider_id}")
async def get_token_balance(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Get a rider's current ZONE token balance and governance weight."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    balance = await zone_token.get_balance(rider_id, db)
    return balance


@router.get("/tokens/{rider_id}/history")
async def get_token_history(
    rider_id: str,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get token transaction history for a rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    history = await zone_token.get_transaction_history(rider_id, db, limit=limit)
    return {"rider_id": rider_id, "transactions": history}


@router.post("/tokens/{rider_id}/earn")
async def earn_zone_tokens(
    rider_id: str,
    payload: TokenEarnRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Award ZONE tokens for a governance event.
    Called by: scheduler (weekly_coverage, claim_free_4weeks),
               claims pipeline (appeal outcomes),
               S4 signal poller (s4_checkin).
    """
    if payload.rider_id != rider_id:
        raise HTTPException(status_code=400, detail="rider_id mismatch")

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    try:
        tx = await zone_token.earn_tokens(
            rider_id=rider_id,
            event_type=payload.event_type,
            db=db,
            reference_id=payload.reference_id,
            manual_delta=payload.manual_delta,
            notes=payload.notes,
        )
        await db.commit()
        return {"transaction": tx, "message": f"Awarded {tx.delta:+d} ZONE tokens"}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/tokens/{rider_id}/health-score")
async def get_governance_health_score(
    rider_id: str,
    claim_free_weeks: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Compute the rider's Governance Health Score.
    Pass claim_free_weeks from the claims pipeline for accurate scoring.
    """
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    score = await zone_token.compute_governance_health_score(
        rider_id=rider_id,
        db=db,
        claim_free_weeks=claim_free_weeks,
    )
    return score


# ─────────────────────────────────────────────
# Proposal endpoints
# ─────────────────────────────────────────────

@router.get("/proposals")
async def list_proposals(
    status: str = Query(default=None),
    limit: int = Query(default=20, le=50),
    db: AsyncSession = Depends(get_db),
):
    """List governance proposals, optionally filtered by status."""
    proposals = await dao_gov.list_proposals(db, status=status, limit=limit)
    return {"proposals": proposals, "count": len(proposals)}


@router.post("/proposals")
async def create_proposal(
    payload: ProposalCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new governance proposal.
    Requires ≥50 ZONE tokens. proposed_value must be within actuarial safe band.
    """
    # Fetch active rider count for quorum calculation
    count_result = await db.execute(select(func.count()).select_from(Rider))
    active_rider_count = count_result.scalar() or 100

    rider = await db.get(Rider, payload.proposer_rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Proposer rider not found")

    try:
        proposal = await dao_gov.create_proposal(
            payload=payload,
            db=db,
            active_rider_count=active_rider_count,
        )
        return {"proposal": proposal, "message": "Proposal created. Voting is now open."}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific proposal with full vote tallies."""
    try:
        proposal = await dao_gov.get_proposal(proposal_id, db)
        return proposal
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/proposals/{proposal_id}/vote")
async def cast_vote(
    proposal_id: str,
    payload: VoteRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Cast a vote on an active proposal.
    Voting power = sqrt(ZONE balance). Rewards +3 ZONE.
    """
    count_result = await db.execute(select(func.count()).select_from(Rider))
    active_rider_count = count_result.scalar() or 100

    rider = await db.get(Rider, payload.rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Voter rider not found")

    try:
        vote = await dao_gov.cast_vote(
            proposal_id=proposal_id,
            payload=payload,
            db=db,
            active_rider_count=active_rider_count,
        )
        return {
            "vote": vote,
            "message": f"Vote cast. You earned +{vote.token_reward} ZONE tokens.",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/proposals/finalise")
async def finalise_proposals(db: AsyncSession = Depends(get_db)):
    """
    Admin endpoint: finalise all proposals whose voting period has ended.
    Also called by the background scheduler.
    """
    processed = await dao_gov.finalise_proposals(db)
    return {
        "finalised_count": len(processed),
        "proposal_ids": processed,
        "message": "Proposals finalised. Passed proposals executed via GovernanceChaincode.",
    }


# ─────────────────────────────────────────────
# SoulboundNFT endpoints
# ─────────────────────────────────────────────

@router.get("/nfts/{rider_id}")
async def list_rider_nfts(
    rider_id: str,
    limit: int = Query(default=60, le=120),
    db: AsyncSession = Depends(get_db),
):
    """List all SoulboundPolicy NFTs for a rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    nfts = await soulbound_nft.get_rider_nfts(rider_id, db, limit=limit)
    return {"rider_id": rider_id, "nfts": nfts, "total": len(nfts)}


@router.post("/nfts/{rider_id}/mint")
async def mint_nft(
    rider_id: str,
    policy_id: str = Query(...),
    zone_id: str = Query(...),
    coverage_tier: str = Query(default="standard"),
    premium_paid: float = Query(...),
    max_payout: float = Query(...),
    was_disrupted: bool = Query(default=False),
    payout_received: float = Query(default=0.0),
    db: AsyncSession = Depends(get_db),
):
    """
    Mint a SoulboundPolicy NFT for a completed coverage week.
    Called by the scheduler/policy renewal pipeline. Idempotent.
    """
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    nft = await soulbound_nft.mint_weekly_nft(
        rider_id=rider_id,
        policy_id=policy_id,
        zone_id=zone_id,
        coverage_tier=coverage_tier,
        premium_paid=premium_paid,
        max_payout=max_payout,
        was_disrupted=was_disrupted,
        payout_received=payout_received,
        db=db,
    )
    return {"nft": nft, "message": "SoulboundPolicy NFT minted to ZK identity hash."}


@router.get("/nfts/{rider_id}/continuity-score")
async def get_continuity_score(rider_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get the Coverage Continuity Score (CCS) and DeFi composability status.
    52 consecutive NFTs = Aave Credit Delegation eligible.
    """
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    score = await soulbound_nft.compute_coverage_continuity_score(rider_id, db)
    return score


# ─────────────────────────────────────────────
# Parameter reference endpoint
# ─────────────────────────────────────────────

@router.get("/parameters")
async def get_governable_parameters():
    """Return all governable parameters with their current safe bands."""
    return {
        "parameters": [
            {
                "parameter": param.value,
                "safe_band_min": band.get("min"),
                "safe_band_max": band.get("max"),
                "supermajority_required": band.get("supermajority_required", False),
                "loss_ratio_block_threshold": band.get("loss_ratio_block"),
            }
            for param, band in PARAMETER_SAFE_BANDS.items()
        ],
        "zone_token_events": [
            {"event": e.value, "delta": ZONE_TOKEN_DELTAS[e]}
            for e in ZoneTokenEvent
        ],
    }
