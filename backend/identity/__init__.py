"""
backend/identity/__init__.py
──────────────────────────────────────────────────────────────────────────────
ZoneGuard Identity System
Innovation 04: ZeroKnow KYC (zk-SNARKs)
Innovation 09: CrossRider DID Passport (W3C DID + Verifiable Credentials)

Public API:
    from identity import identity_router
    app.include_router(identity_router)
"""

from fastapi import APIRouter, Depends, HTTPException, Path as FPath
from sqlalchemy.ext.asyncio import AsyncSession
from db.database import get_db

from identity.models import (
    ZKVerifyRequest,
    ZKVerifyResponse,
    CredentialIssuanceRequest,
    DIDPassportResponse,
    Platform,
    VCType,
)
from identity.zk_kyc import (
    verify_rider_zk_proof,
    generate_flex_rider_proof,
    generate_earnings_proof,
    compute_proof_hash,
)
from identity.did_passport import (
    assemble_did_passport,
    generate_share_url,
    generate_qr_payload,
)
from identity.did_resolver import (
    resolve_did,
    resolve_passport_by_nullifier,
    verify_verifiable_credential,
)

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

identity_router = APIRouter(prefix="/api/v1/identity", tags=["identity"])


# ─────────────────────────────────────────────────────────────────────────────
# ZK PROOF ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@identity_router.post("/generate-proof")
async def generate_proof_endpoint(
    rider_id: str,
    eshram_id: str = None,
):
    """
    TEE-side proof generation endpoint.
    Rider submits raw credentials over TLS; server generates ZK proof.
    Returns (public_signals, nullifier_secret) — ZoneGuard never stores the secret.

    DPDP NOTE: This endpoint should be deployed in a TEE (AWS Nitro Enclave)
    in production. Raw rider_id is never logged.
    """
    try:
        proof, public_signals, nullifier_secret = await generate_flex_rider_proof(
            rider_id=rider_id,
            eshram_id=eshram_id,
        )
        return {
            "proof": proof.model_dump(),
            "public_signals": public_signals.model_dump(),
            "nullifier_secret": nullifier_secret,  # Return to rider, never store
            "warning": "Store nullifier_secret securely. ZoneGuard does not retain it.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@identity_router.post("/verify-proof", response_model=ZKVerifyResponse)
async def verify_proof_endpoint(
    payload: ZKVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Verify a ZK proof and record the nullifier.
    This is the core ZK KYC verification endpoint.
    Called by POST /riders/verify-zk (which delegates here).
    """
    return await verify_rider_zk_proof(
        proof=payload.proof,
        public_signals=payload.public_signals,
        db_session=db,
    )


@identity_router.post("/generate-earnings-proof")
async def generate_earnings_proof_endpoint(
    nullifier: str,
    bracket_lower: int = 10000,
    bracket_upper: int = 19999,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate earnings bracket proof from ZoneGuard payout history.
    No external API dependency — uses internal payouts table.

    The rider never needs to reveal exact earnings:
    only the bracket (low/mid/high) is disclosed.
    """
    from sqlalchemy import text

    # Fetch last 12 weeks of payouts for this rider's nullifier
    result = await db.execute(
        text("""
            SELECT SUM(p.amount) as weekly_total
            FROM payouts p
            JOIN riders r ON r.id = p.rider_id
            WHERE r.nullifier_hash = :nullifier
              AND p.created_at >= NOW() - INTERVAL '84 days'
            GROUP BY DATE_TRUNC('week', p.created_at)
            ORDER BY DATE_TRUNC('week', p.created_at) DESC
            LIMIT 12
        """),
        {"nullifier": nullifier}
    )
    rows = result.fetchall()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No payout history found for this nullifier. "
                   "Earnings proof requires at least 1 week of payouts."
        )

    weekly_earnings = [float(row.weekly_total) for row in rows]

    proof, signals = await generate_earnings_proof(
        weekly_earnings=weekly_earnings,
        bracket_lower=bracket_lower,
        bracket_upper=bracket_upper,
    )

    return {
        "proof": proof.model_dump(),
        "signals": signals.model_dump(),
        "bracket": signals.bracket.value,
        "weeks_proven": signals.weeks_proven,
        "bracket_satisfied": signals.bracket_satisfied,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DID PASSPORT ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@identity_router.get("/passport/{nullifier_prefix}", response_model=DIDPassportResponse)
async def get_passport(
    nullifier_prefix: str = FPath(..., min_length=8, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a rider's CrossRider DID Passport.
    Uses nullifier prefix (not raw ID) for privacy-preserving lookup.

    Returns the full passport with all VCs the rider has earned.
    For selective disclosure, use the share_url or qr_payload.
    """
    from sqlalchemy import text

    # Full lookup by prefix
    row_result = await db.execute(
        text("""
            SELECT r.nullifier_hash, r.did_document, r.zk_verified_at,
                   r.tenure_weeks, r.zone_id, r.zk_proof_hash
            FROM riders r
            WHERE r.nullifier_hash LIKE :prefix
            LIMIT 1
        """),
        {"prefix": f"{nullifier_prefix}%"}
    )
    row = row_result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Rider not found by nullifier prefix")

    # Fetch payout-based earnings proof if tenure >= 4 weeks
    earnings_signals = None
    if (row.tenure_weeks or 0) >= 4:
        try:
            proof, earnings_signals = await generate_earnings_proof(
                weekly_earnings=[0.0] * 12,  # Will be replaced by real query in production
            )
        except Exception:
            pass  # Earnings proof is optional

    passport = assemble_did_passport(
        nullifier=row.nullifier_hash,
        zone_id=row.zone_id or "unknown",
        tenure_weeks=row.tenure_weeks or 0,
        platforms=[Platform.AMAZON_FLEX],
        earnings_signals=earnings_signals,
        zk_proof_id=row.zk_proof_hash or "",
    )

    share_url = generate_share_url(row.nullifier_hash)
    qr_payload = generate_qr_payload(passport)

    return DIDPassportResponse(
        passport=passport,
        share_url=share_url,
        qr_payload=qr_payload,
    )


@identity_router.get("/resolve/{did:path}")
async def resolve_did_endpoint(did: str):
    """
    W3C DID Resolution endpoint.
    Resolves a DID to its DID Document.

    Used by: NBFC systems, Swiggy onboarding, government portals.
    Returns standard W3C DID Resolution response format.
    """
    result = await resolve_did(did)
    return result.to_dict()


@identity_router.post("/verify-credential")
async def verify_credential_endpoint(vc_json: dict):
    """
    Verify a Verifiable Credential's cryptographic proof.
    Anyone (NBFC, government, platform) can call this to verify a VC
    presented by a rider. No ZoneGuard account required for verification.
    """
    from identity.models import VerifiableCredential
    try:
        vc = VerifiableCredential(**vc_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid VC format: {e}")

    result = await verify_verifiable_credential(vc)
    return result


@identity_router.get("/credential-status")
async def credential_status():
    """
    Credential Status List endpoint.
    Allows verifiers to check if a credential has been revoked.
    Linked from DID Document service endpoints.
    """
    return {
        "id": "https://zoneguard.in/api/v1/identity/credential-status",
        "type": "StatusList2021",
        "statusPurpose": "revocation",
        "encodedList": "",  # In production: bitstring of revoked credential indices
        "issuer": "did:key:z6MkZoneGuardIssuer2026",
        "issued": datetime.now(timezone.utc).isoformat(),
    }
