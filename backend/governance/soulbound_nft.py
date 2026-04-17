"""
SoulboundPolicy NFT — Innovation 07
Non-transferable NFT minted weekly to a rider's ZeroKnow identity hash.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CROSS-SESSION DEPENDENCY CONTRACT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
This module depends on a ZeroKnow (ZK) identity service being provided
by another parallel session. The assumed interface is:

  GET /api/v1/identity/{rider_id}/zk-hash
  Response: {
    "zk_hash": "0x<64-char-hex>",   # sha3-256 of (rider_id + secret_salt)
    "verified": bool,
    "zk_proof_cid": str | null       # IPFS CID of the ZK proof
  }

FALLBACK (hackathon safe):
  If the ZK identity service is unavailable (ConnectionError / 404),
  this module falls back to: sha256(rider_id + ZONEGUARD_NFT_SALT)
  This produces a deterministic pseudonymous hash that can be replaced
  by the real ZK hash once the identity session is integrated.

FLAG FOR CROSS-SESSION ALIGNMENT:
  The ZK session must confirm the /api/v1/identity/{rider_id}/zk-hash
  endpoint structure. If different, update _resolve_zk_hash() below.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SOULBOUND ENFORCEMENT:
  - No transfer() or approve() function exists.
  - token_id is keyed to rider_zk_hash in DB.
  - On ZoneChain: SoulboundChaincode.MintNFT() stores by zk_hash with
    NO TransferNFT function implemented.

DeFi COMPOSABILITY SURFACE:
  - Coverage Continuity Score (CCS): 52 consecutive NFTs = Elite (Aave eligible)
  - Income verification: payout_received history exported as JSON
  - NBFC microloan integration: CCS report URI for Goldfinch/Credix underwriting
"""

from __future__ import annotations

import hashlib
import json
import uuid
import os
import logging
from datetime import datetime, timezone, date
from typing import Optional, List, Tuple

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from governance.db_models import SoulboundNFTDB
from governance.models import (
    SoulboundNFTResponse,
    CoverageContinuityScore,
    NFTMetadata,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
ZONEGUARD_NFT_SALT = os.getenv("ZONEGUARD_NFT_SALT", "zg-nft-salt-dev-2025")
ZK_IDENTITY_BASE_URL = os.getenv("ZK_IDENTITY_BASE_URL", "http://localhost:8001")
ZK_IDENTITY_TIMEOUT = 3.0  # seconds — fast fallback for demo

# CCS thresholds for DeFi composability
CCS_THRESHOLDS = {
    "Unrated":     0,     # < 4 NFTs
    "Building":    4,     # 4-12 weeks
    "Established": 13,    # 13-25 weeks
    "Trusted":     26,    # 26-51 weeks
    "Elite":       52,    # 52+ consecutive weeks (Aave Credit Delegation eligible)
}
MICROLOAN_MIN_CONSECUTIVE = 13   # 13 weeks = Goldfinch/Credix eligible
CREDIT_DELEGATION_MIN_CONSECUTIVE = 52  # 1 year = Aave eligible

# IPFS simulation (replace with real Pinata/web3.storage in production)
IPFS_GATEWAY = "https://ipfs.io/ipfs/"


# ─────────────────────────────────────────────
# ZK Identity resolution
# ─────────────────────────────────────────────

async def _resolve_zk_hash(rider_id: str) -> Tuple[str, bool]:
    """
    Resolve the ZK identity hash for a rider.

    Returns (zk_hash, is_real_zk) where is_real_zk=False means fallback was used.

    ── CONTRACT with ZK Identity Session ─────────────────────────────────────
    Calls GET {ZK_IDENTITY_BASE_URL}/api/v1/identity/{rider_id}/zk-hash
    Expected response: {"zk_hash": "0x...", "verified": bool}
    ─────────────────────────────────────────────────────────────────────────
    """
    try:
        async with httpx.AsyncClient(timeout=ZK_IDENTITY_TIMEOUT) as client:
            resp = await client.get(
                f"{ZK_IDENTITY_BASE_URL}/api/v1/identity/{rider_id}/zk-hash"
            )
            if resp.status_code == 200:
                data = resp.json()
                zk_hash = data.get("zk_hash")
                if zk_hash and len(zk_hash) >= 10:
                    logger.info("ZK identity resolved for rider %s", rider_id)
                    return zk_hash, True
    except Exception as e:
        logger.warning(
            "ZK identity service unavailable for rider %s (%s). "
            "Using deterministic fallback hash.", rider_id, type(e).__name__
        )

    # Fallback: deterministic pseudonymous hash
    fallback_input = f"{rider_id}:{ZONEGUARD_NFT_SALT}"
    fallback_hash = "0x" + hashlib.sha256(fallback_input.encode()).hexdigest()
    return fallback_hash, False


# ─────────────────────────────────────────────
# NFT minting
# ─────────────────────────────────────────────

async def mint_weekly_nft(
    rider_id: str,
    policy_id: str,
    zone_id: str,
    coverage_tier: str,
    premium_paid: float,
    max_payout: float,
    was_disrupted: bool,
    payout_received: float,
    db: AsyncSession,
    week_number: Optional[int] = None,
    year: Optional[int] = None,
) -> SoulboundNFTResponse:
    """
    Mint a SoulboundPolicy NFT for a completed coverage week.
    Idempotent: returns existing NFT if already minted for this policy+week.

    Called by:
      - services/scheduler.py on weekly policy renewal
      - policies router POST /{policy_id}/renew (post-renewal hook)
    """
    now = datetime.now(timezone.utc)
    iso_cal = now.isocalendar()
    wk = week_number or iso_cal[1]
    yr = year or iso_cal[0]

    # Idempotency check
    existing = await db.execute(
        select(SoulboundNFTDB).where(
            and_(
                SoulboundNFTDB.policy_id == policy_id,
                SoulboundNFTDB.week_number == wk,
                SoulboundNFTDB.year == yr,
            )
        )
    )
    existing_nft = existing.scalar_one_or_none()
    if existing_nft:
        return _nft_to_response(existing_nft)

    # Resolve ZK identity
    zk_hash, is_real_zk = await _resolve_zk_hash(rider_id)
    if not is_real_zk:
        logger.warning(
            "NFT minted with fallback ZK hash for rider %s. "
            "Flag for ZK identity session integration.", rider_id
        )

    # Build IPFS metadata
    metadata = _build_nft_metadata(
        rider_zk_hash=zk_hash,
        policy_id=policy_id,
        week_number=wk,
        year=yr,
        zone_id=zone_id,
        coverage_tier=coverage_tier,
        premium_paid=premium_paid,
        max_payout=max_payout,
        was_disrupted=was_disrupted,
        payout_received=payout_received,
    )

    # Simulate IPFS pin (replace with Pinata SDK in production)
    ipfs_cid = _simulate_ipfs_pin(metadata)

    # Simulate Hyperledger Fabric mint tx
    chain_tx = _simulate_fabric_mint(zk_hash, policy_id, wk, yr)

    nft = SoulboundNFTDB(
        rider_zk_hash=zk_hash,
        policy_id=policy_id,
        week_number=wk,
        year=yr,
        coverage_tier=coverage_tier,
        zone_id=zone_id,
        premium_paid=premium_paid,
        max_payout=max_payout,
        was_disrupted=was_disrupted,
        payout_received=payout_received,
        ipfs_metadata_cid=ipfs_cid,
        chain_tx_hash=chain_tx,
        minted_at=now,
    )
    db.add(nft)
    await db.flush()
    await db.commit()
    await db.refresh(nft)

    logger.info(
        "SoulboundNFT minted | token=%s rider_hash=%s week=%s/%s tx=%s",
        nft.token_id, zk_hash[:12], wk, yr, chain_tx
    )

    return _nft_to_response(nft)


# ─────────────────────────────────────────────
# Coverage Continuity Score
# ─────────────────────────────────────────────

async def compute_coverage_continuity_score(
    rider_id: str,
    db: AsyncSession,
) -> CoverageContinuityScore:
    """
    Compute the Coverage Continuity Score (CCS) from a rider's NFT history.

    CCS is based on:
      - total NFTs minted (breadth)
      - consecutive weeks without a gap (continuity — primary driver)
      - total payout received (income disruption record)

    DeFi composability:
      - eligible_for_microloan: ≥13 consecutive weeks (Goldfinch/Credix)
      - eligible_for_credit_delegation: ≥52 consecutive weeks (Aave)
    """
    now = datetime.now(timezone.utc)
    zk_hash, _ = await _resolve_zk_hash(rider_id)

    # Fetch all NFTs for this rider sorted by year+week
    result = await db.execute(
        select(SoulboundNFTDB)
        .where(SoulboundNFTDB.rider_zk_hash == zk_hash)
        .order_by(SoulboundNFTDB.year.desc(), SoulboundNFTDB.week_number.desc())
    )
    nfts = result.scalars().all()

    total_nfts = len(nfts)
    consecutive_weeks = _compute_consecutive_streak(nfts)

    # Aggregate stats
    total_payout = sum(n.payout_received for n in nfts)
    avg_premium = (sum(n.premium_paid for n in nfts) / total_nfts) if total_nfts > 0 else 0.0

    # Score: 50% from consecutive weeks (max 52), 50% from total coverage breadth (max 104)
    consecutive_score = min(consecutive_weeks / 52.0, 1.0) * 50.0
    breadth_score = min(total_nfts / 104.0, 1.0) * 50.0
    score = round(consecutive_score + breadth_score, 1)

    # Determine label
    label = "Unrated"
    for lbl, threshold in sorted(CCS_THRESHOLDS.items(), key=lambda x: -x[1]):
        if consecutive_weeks >= threshold:
            label = lbl  # type: ignore[assignment]
            break

    eligible_microloan = consecutive_weeks >= MICROLOAN_MIN_CONSECUTIVE
    eligible_credit_delegation = consecutive_weeks >= CREDIT_DELEGATION_MIN_CONSECUTIVE

    # NBFC report URI (in production: generate signed PDF + IPFS pin)
    nbfc_uri = f"https://zoneguard.in/nbfc-report/{zk_hash[:16]}" if eligible_microloan else None

    return CoverageContinuityScore(
        rider_id=rider_id,
        rider_zk_hash=zk_hash,
        total_nfts=total_nfts,
        consecutive_weeks=consecutive_weeks,
        score=score,
        score_label=label,  # type: ignore[arg-type]
        eligible_for_microloan=eligible_microloan,
        eligible_for_credit_delegation=eligible_credit_delegation,
        total_payout_received=round(total_payout, 2),
        avg_premium_paid=round(avg_premium, 2),
        computed_at=now,
        nbfc_report_uri=nbfc_uri,
    )


async def get_rider_nfts(
    rider_id: str,
    db: AsyncSession,
    limit: int = 60,
) -> List[SoulboundNFTResponse]:
    """Fetch all NFTs for a rider by ZK hash."""
    zk_hash, _ = await _resolve_zk_hash(rider_id)
    result = await db.execute(
        select(SoulboundNFTDB)
        .where(SoulboundNFTDB.rider_zk_hash == zk_hash)
        .order_by(SoulboundNFTDB.year.desc(), SoulboundNFTDB.week_number.desc())
        .limit(limit)
    )
    return [_nft_to_response(n) for n in result.scalars().all()]


# ─────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────

def _compute_consecutive_streak(nfts: list) -> int:
    """
    Given NFTs sorted by (year DESC, week DESC), compute the current
    consecutive weekly streak starting from the most recent NFT.
    """
    if not nfts:
        return 0

    streak = 1
    for i in range(1, len(nfts)):
        prev = nfts[i - 1]
        curr = nfts[i]

        # Convert year/week to ISO date for comparison
        prev_date = date.fromisocalendar(prev.year, prev.week_number, 1)
        curr_date = date.fromisocalendar(curr.year, curr.week_number, 1)

        # Consecutive means exactly 7 days apart
        if (prev_date - curr_date).days == 7:
            streak += 1
        else:
            break  # gap found — streak ends

    return streak


def _build_nft_metadata(
    rider_zk_hash: str,
    policy_id: str,
    week_number: int,
    year: int,
    zone_id: str,
    coverage_tier: str,
    premium_paid: float,
    max_payout: float,
    was_disrupted: bool,
    payout_received: float,
) -> NFTMetadata:
    return NFTMetadata(
        name=f"ZoneGuard Coverage — Week {week_number}, {year}",
        description=(
            f"Soulbound proof of active ZoneGuard income protection coverage. "
            f"Zone: {zone_id} | Tier: {coverage_tier} | "
            f"{'Disruption recorded — payout issued.' if was_disrupted else 'Claim-free week.'}"
        ),
        image=f"ipfs://QmZoneGuardPlaceholder/{zone_id}/{year}W{week_number}",
        attributes=[
            {"trait_type": "Coverage Week",     "value": f"W{week_number} {year}"},
            {"trait_type": "Zone",              "value": zone_id},
            {"trait_type": "Coverage Tier",     "value": coverage_tier},
            {"trait_type": "Premium Paid (INR)","value": premium_paid},
            {"trait_type": "Max Payout (INR)",  "value": max_payout},
            {"trait_type": "Disrupted",         "value": "Yes" if was_disrupted else "No"},
            {"trait_type": "Payout (INR)",      "value": payout_received},
            {"trait_type": "Policy ID",         "value": policy_id},
            {"trait_type": "Rider ZK Hash",     "value": rider_zk_hash[:16] + "..."},
            {"trait_type": "Platform",          "value": "ZoneGuard v2.0"},
        ],
    )


def _simulate_ipfs_pin(metadata: NFTMetadata) -> str:
    """Simulate IPFS CID generation (deterministic for demo)."""
    payload = json.dumps(metadata.model_dump(), sort_keys=True).encode()
    digest = hashlib.sha256(payload).hexdigest()
    return f"Qm{digest[:44]}"  # Simulate IPFS CIDv0 prefix format


def _simulate_fabric_mint(
    zk_hash: str,
    policy_id: str,
    week: int,
    year: int,
) -> str:
    """Simulate Hyperledger Fabric SoulboundChaincode.MintNFT() tx hash."""
    payload = f"SNFT:{zk_hash}:{policy_id}:{year}W{week}"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return "FABRIC-SNFT-" + digest[:12].upper()


def _nft_to_response(n: SoulboundNFTDB) -> SoulboundNFTResponse:
    return SoulboundNFTResponse(
        token_id=n.token_id,
        rider_zk_hash=n.rider_zk_hash,
        policy_id=n.policy_id,
        week_number=n.week_number,
        year=n.year,
        coverage_tier=n.coverage_tier,
        zone_id=n.zone_id,
        premium_paid=n.premium_paid,
        max_payout=n.max_payout,
        was_disrupted=n.was_disrupted,
        payout_received=n.payout_received,
        minted_at=n.minted_at,
        ipfs_metadata_cid=n.ipfs_metadata_cid,
        chain_tx_hash=n.chain_tx_hash,
    )
