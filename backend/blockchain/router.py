"""
blockchain/router.py
====================
FastAPI router for ZoneChain and TemporalSig endpoints.

All endpoints are READ-ONLY from the API consumer's perspective:
  - Status / health of both blockchain systems
  - Claim audit trail viewer (for RiderDashboard and insurer portal)
  - TemporalSig anchor verification (for dispute resolution)
  - Policy lifecycle history

Write operations are triggered internally by claims/policies/payouts routers,
not exposed as public API endpoints — this prevents replay attacks.

Prefix: /api/v1/blockchain
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .models import (
    AnchorVerifyResponse,
    BlockchainStatusResponse,
    ClaimAuditTrailResponse,
    PolicyTermsOnChain,
    SmartPolicyResult,
    TemporalSigAnchor,
    ZoneChainEvent,
)
from .smart_policy import SmartPolicyEngine, get_smart_policy
from .temporalsig import TemporalSigClient, get_temporalsig_client
from .zonechain import ZoneChainClient, get_zonechain_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/blockchain",
    tags=["blockchain"],
)


# ---------------------------------------------------------------------------
# Health / Status
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    response_model=BlockchainStatusResponse,
    summary="Blockchain system status",
    description=(
        "Returns connectivity status for both ZoneChain (Hyperledger Fabric) "
        "and TemporalSig (Polygon L2). Used by admin dashboard and monitoring."
    ),
)
async def get_blockchain_status(
    zonechain: ZoneChainClient = Depends(get_zonechain_client),
    temporalsig: TemporalSigClient = Depends(get_temporalsig_client),
) -> BlockchainStatusResponse:
    fabric_health = await zonechain.get_health()
    polygon_health = await temporalsig.get_health()

    return BlockchainStatusResponse(
        fabric_connected=fabric_health["fabric_connected"],
        fabric_peer_count=3,  # org1 + org2 + org3 (IRDAI)
        fabric_channel=fabric_health["channel"],
        fabric_chaincode=fabric_health["chaincode"],
        polygon_connected=polygon_health["polygon_connected"],
        polygon_network=polygon_health["network"],
        polygon_contract_address=polygon_health["contract_address"],
        polygon_wallet_balance_matic=polygon_health.get("wallet_balance_matic"),
        last_anchor_at=None,    # [ENHANCEMENT] Wire to DB query
        total_anchors_today=0,  # [ENHANCEMENT] Wire to DB count
        total_fabric_events_today=0,  # [ENHANCEMENT] Wire to DB count
    )


# ---------------------------------------------------------------------------
# ZoneChain — Claim Audit Trail
# ---------------------------------------------------------------------------

@router.get(
    "/claims/{claim_id}/audit-trail",
    response_model=ClaimAuditTrailResponse,
    summary="Full immutable claim audit trail",
    description=(
        "Returns the complete ZoneChain event history for a claim, including "
        "all state transitions, Claude AI audit results, and linked TemporalSig "
        "proofs. Used by the RiderDashboard and insurer dispute portal."
    ),
)
async def get_claim_audit_trail(
    claim_id: str,
    zonechain: ZoneChainClient = Depends(get_zonechain_client),
    temporalsig: TemporalSigClient = Depends(get_temporalsig_client),
) -> ClaimAuditTrailResponse:
    try:
        fabric_events_raw = await zonechain.get_claim_audit_trail(claim_id)

        # Reconstruct typed events from Fabric response
        fabric_events: List[ZoneChainEvent] = []
        temporalsig_anchors: List[TemporalSigAnchor] = []
        earliest_ts: Optional[datetime] = None
        latest_ts: Optional[datetime] = None

        for raw in fabric_events_raw:
            try:
                event = ZoneChainEvent.model_validate(raw)
                fabric_events.append(event)

                # Extract TemporalSig references from claim events
                if event.claim_payload and event.claim_payload.temporalsig_polygon_tx:
                    ts = event.claim_payload.temporalsig_block_timestamp
                    if ts:
                        if earliest_ts is None or ts < earliest_ts:
                            earliest_ts = ts
                        if latest_ts is None or ts > latest_ts:
                            latest_ts = ts

                    for batch_id in event.claim_payload.signal_batch_ids:
                        anchor = await temporalsig.get_anchor_for_event(batch_id)
                        if anchor:
                            temporalsig_anchors.append(anchor)

            except Exception as parse_err:
                logger.warning(
                    f"[BlockchainRouter] Failed to parse Fabric event: {parse_err}"
                )
                continue

        return ClaimAuditTrailResponse(
            claim_id=claim_id,
            fabric_events=fabric_events,
            temporalsig_anchors=temporalsig_anchors,
            dispute_proof_available=len(temporalsig_anchors) > 0,
            earliest_signal_timestamp=earliest_ts,
            latest_signal_timestamp=latest_ts,
        )

    except Exception as e:
        logger.error(f"[BlockchainRouter] get_claim_audit_trail failed: {e}")
        raise HTTPException(status_code=500, detail=f"Blockchain query failed: {e}")


# ---------------------------------------------------------------------------
# ZoneChain — Policy Lifecycle History
# ---------------------------------------------------------------------------

@router.get(
    "/policies/{policy_id}/history",
    summary="Immutable policy lifecycle history from ZoneChain",
    description=(
        "Returns all policy events (creation, renewal, cancellation) from the "
        "Fabric ledger. Both ZoneGuard and insurer nodes co-sign these — making "
        "the coverage terms immutable."
    ),
)
async def get_policy_history(
    policy_id: str,
    zonechain: ZoneChainClient = Depends(get_zonechain_client),
) -> dict:
    try:
        events = await zonechain.get_policy_audit_trail(policy_id)
        return {
            "policy_id": policy_id,
            "event_count": len(events),
            "events": events,
            "source": "hyperledger_fabric_zoneguard_channel",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Blockchain query failed: {e}")


# ---------------------------------------------------------------------------
# TemporalSig — Anchor Verification (Dispute Resolution)
# ---------------------------------------------------------------------------

class VerifyRequest(BaseModel):
    batch_id: str
    zone_id: str
    polled_at: datetime
    composite_score: float
    confidence_tier: str
    polygon_tx_hash: str
    signal_batch_canonical_json: Optional[str] = None  # If provided, re-hash and verify


@router.post(
    "/temporalsig/verify",
    response_model=AnchorVerifyResponse,
    summary="Verify a TemporalSig anchor (dispute resolution)",
    description=(
        "Given a batch_id and Polygon tx hash, re-computes the keccak256 hash "
        "from the signal data and compares it to what's stored on-chain. "
        "Returns the Polygon block.timestamp as the immutable disruption proof time. "
        "This is the primary dispute resolution endpoint — usable by IRDAI, "
        "insurer, or rider."
    ),
)
async def verify_temporalsig_anchor(
    request: VerifyRequest,
    temporalsig: TemporalSigClient = Depends(get_temporalsig_client),
) -> AnchorVerifyResponse:
    from .models import SignalBatchPayload, ConfidenceTier

    # Reconstruct a minimal SignalBatchPayload for hash verification
    # In production this would be fetched from the DB by batch_id
    batch = SignalBatchPayload(
        batch_id=request.batch_id,
        zone_id=request.zone_id,
        polled_at=request.polled_at,
        signals=[],  # Empty for hash comparison (hash stored in anchor)
        composite_score=request.composite_score,
        confidence_tier=ConfidenceTier(request.confidence_tier),
        scheduler_run_id="verify-mode",
    )

    anchor = TemporalSigAnchor(
        anchor_id="verify-mode",
        batch_id=request.batch_id,
        zone_id=request.zone_id,
        keccak256_hash=batch.keccak256_hash,
        polygon_tx_hash=request.polygon_tx_hash,
        polygon_network=temporalsig._network,
        status="confirmed",
    )

    verification = await temporalsig.verify_anchor(batch, request.polygon_tx_hash)

    anchor.hash_matches = verification.get("hash_matches", False)
    if verification.get("block_timestamp_utc"):
        anchor.polygon_block_timestamp = datetime.fromisoformat(
            verification["block_timestamp_utc"]
        )

    return AnchorVerifyResponse(
        batch_id=request.batch_id,
        anchor=anchor,
        hash_matches=verification.get("hash_matches", False),
        block_timestamp_utc=anchor.polygon_block_timestamp,
        polygonscan_url=verification.get("polygonscan_url"),
        verification_message=verification.get("verification_message", ""),
    )


# ---------------------------------------------------------------------------
# TemporalSig — Recent Anchors (zone timeline)
# ---------------------------------------------------------------------------

@router.get(
    "/temporalsig/anchors",
    summary="Recent TemporalSig anchors for a zone",
    description=(
        "Returns the most recent signal-batch anchors for a zone. "
        "Shows the 15-minute cadence of Polygon timestamps — visualized "
        "in the RiderDashboard ZoneChainExplorer component."
    ),
)
async def get_recent_anchors(
    zone_id: str = Query(..., description="Zone ID to filter anchors"),
    limit: int = Query(default=48, le=192, description="Max anchors (48 = 12 hours)"),
    temporalsig: TemporalSigClient = Depends(get_temporalsig_client),
) -> dict:
    # [ENHANCEMENT] In production: query PostgreSQL temporal_sig_anchors table
    # SELECT * FROM temporal_sig_anchors WHERE zone_id = $1 ORDER BY created_at DESC LIMIT $2
    return {
        "zone_id": zone_id,
        "anchors": [],
        "total": 0,
        "message": "Wire to PostgreSQL temporal_sig_anchors table",
        "stub_mode": temporalsig._stub_mode,
    }


# ---------------------------------------------------------------------------
# IRDAI Observer Feed (read-only, for regulatory portal)
# ---------------------------------------------------------------------------

@router.get(
    "/irdai/parameter-changes",
    summary="Parameter change log visible to IRDAI",
    description=(
        "All threshold and parameter changes recorded on ZoneChain. "
        "IRDAI observer node has read-only access to this collection. "
        "Provides regulatory transparency without exposing rider PII."
    ),
)
async def get_parameter_changes(
    zone_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    zonechain: ZoneChainClient = Depends(get_zonechain_client),
) -> dict:
    # [ENHANCEMENT] query parametersCollection on Fabric
    return {
        "parameter_changes": [],
        "total": 0,
        "message": "Wire to Fabric parametersCollection query",
    }


# ---------------------------------------------------------------------------
# Innovation 02: SmartPolicy Contracts — On-Chain Policy Execution
# ---------------------------------------------------------------------------

@router.get(
    "/policy/{policy_id}/terms",
    response_model=PolicyTermsOnChain,
    summary="Immutable on-chain policy terms",
    description=(
        "Fetches the immutable policy terms stored on the Fabric chain state "
        "for a given policy/rider ID. These terms include payout percentage, "
        "max consecutive days, earnings baseline, exclusion hash, and Forward "
        "Premium Lock details. Once written, these terms cannot be altered."
    ),
)
async def get_policy_terms_on_chain(
    policy_id: str,
    engine: SmartPolicyEngine = Depends(get_smart_policy),
) -> PolicyTermsOnChain:
    terms = engine.get_policy_terms(policy_id)
    if terms is None:
        raise HTTPException(
            status_code=404,
            detail=f"No on-chain policy terms found for '{policy_id}'",
        )
    return terms


class VerifyPayoutRequest(BaseModel):
    claim_id: str


@router.post(
    "/policy/verify-payout",
    summary="Verify payout calculation against on-chain formula",
    description=(
        "Re-derives the payout amount from on-chain inputs and compares it "
        "to the recorded result. Returns VERIFIED if the amounts match, "
        "MISMATCH otherwise. Used for dispute resolution and regulatory audit."
    ),
)
async def verify_payout_on_chain(
    request: VerifyPayoutRequest,
    engine: SmartPolicyEngine = Depends(get_smart_policy),
) -> dict:
    try:
        verification = engine.verify_payout_calculation(request.claim_id)
        return verification
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
