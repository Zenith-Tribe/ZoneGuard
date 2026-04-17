# MERGED BY SESSION 7 — Patches from sessions: 3

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.rider import Rider
from models.zone import Zone
from models.claim import Claim
from models.payout import Payout
from schemas.rider import RiderRegister, RiderResponse, RiderKYC, EShramVerifyRequest
from schemas.claim import ClaimResponse
from schemas.payout import PayoutResponse
from ml.zone_risk_scorer import calculate_zone_premium

# ── Session 3: ZK KYC imports (optional — graceful fallback to legacy OTP) ────
try:
    from identity.models import ZKVerifyRequest, ZKVerifyResponse, SnarkProof, PublicSignals
    from identity.zk_kyc import verify_rider_zk_proof, generate_flex_rider_proof
    from identity.did_passport import assemble_did_passport, generate_share_url, generate_qr_payload
    from identity.models import Platform
    HAS_ZK_IDENTITY = True
except ImportError:
    HAS_ZK_IDENTITY = False
# ── End Session 3 imports ─────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1/riders", tags=["riders"])


@router.get("")
async def list_riders(
    zone_id: str = Query(None),
    kyc_verified: bool = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all riders with optional zone/KYC filter and pagination."""
    query = select(Rider)
    if zone_id:
        query = query.where(Rider.zone_id == zone_id)
    if kyc_verified is not None:
        query = query.where(Rider.kyc_verified == kyc_verified)
    query = query.order_by(Rider.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    riders = result.scalars().all()

    return {
        "items": [RiderResponse.model_validate(r) for r in riders],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/register")
async def register_rider(payload: RiderRegister, db: AsyncSession = Depends(get_db)):
    """Register a new rider and return premium quote."""

    zone = await db.get(Zone, payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    existing = await db.get(Rider, payload.rider_id)
    if existing:
        raise HTTPException(status_code=409, detail="Rider already registered")

    rider = Rider(
        id=payload.rider_id,
        name=payload.name,
        phone=payload.phone,
        zone_id=payload.zone_id,
        weekly_earnings_baseline=payload.weekly_earnings,
        upi_id=payload.upi_id,
        eshram_id=payload.eshram_id,
    )
    db.add(rider)

    zone.active_riders = (zone.active_riders or 0) + 1

    await db.commit()
    await db.refresh(rider)

    premium_quote = calculate_zone_premium(
        {
            "historical_disruptions": zone.historical_disruptions,
            "risk_tier": zone.risk_tier,
            "active_riders": zone.active_riders,
        },
        rider_tenure_weeks=0,
    )

    return {
        "rider": RiderResponse.model_validate(rider),
        "premium_quote": premium_quote,
    }


@router.get("/{rider_id}")
async def get_rider(rider_id: str, db: AsyncSession = Depends(get_db)):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    return RiderResponse.model_validate(rider)


@router.put("/{rider_id}")
async def update_rider(rider_id: str, updates: dict, db: AsyncSession = Depends(get_db)):
    """Update rider details (name, phone, zone_id, weekly_earnings_baseline, upi_id)."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    allowed = {"name", "phone", "zone_id", "weekly_earnings_baseline", "upi_id"}
    for key, value in updates.items():
        if key in allowed:
            setattr(rider, key, value)

    await db.commit()
    await db.refresh(rider)
    return RiderResponse.model_validate(rider)


@router.post("/{rider_id}/verify-eshram")
async def verify_eshram(
    rider_id: str,
    payload: EShramVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    from integrations.eshram_sim import verify_eshram_worker, check_income_proxy

    verification = await verify_eshram_worker(
        eshram_id=payload.eshram_id,
        rider_name=rider.name,
        phone=rider.phone or "",
    )

    if verification["verified"]:
        rider.eshram_id = payload.eshram_id
        rider.eshram_verified = True
        rider.kyc_verified = True

        if rider.weekly_earnings_baseline > 0:
            income_check = await check_income_proxy(
                eshram_id=payload.eshram_id,
                declared_weekly_earnings=rider.weekly_earnings_baseline,
            )
            verification["income_proxy"] = income_check

        await db.commit()

    return verification


# ── Session 3: ZeroKnow KYC + CrossRider DID Passport endpoints ──────────────

@router.post("/{rider_id}/verify-zk")
async def verify_zk_kyc(
    rider_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    ZeroKnow KYC — Verify a ZK proof for rider identity.
    Innovation 04: ZeroKnow KYC (Session 3)

    Additive to existing OTP flow — backward compatible.
    zk_verified = True unlocks: DID Passport, loyalty discounts, DPDP compliance.

    Request body: { "proof": {...}, "public_signals": {...} }
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(
            status_code=503,
            detail="ZK identity module not available. Install: pip install cryptography"
        )

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    try:
        proof_data = payload.get("proof", {})
        signals_data = payload.get("public_signals", {})
        proof = SnarkProof(**proof_data)
        public_signals = PublicSignals(**signals_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid ZK proof format: {e}")

    result = await verify_rider_zk_proof(
        proof=proof,
        public_signals=public_signals,
        db_session=db,
    )

    if result.verified:
        from sqlalchemy import text
        from datetime import datetime, timezone
        await db.execute(
            text("""
                UPDATE riders SET
                    nullifier_hash    = :nullifier,
                    zk_proof_hash     = :proof_hash,
                    zk_verified       = TRUE,
                    zk_verified_at    = :verified_at,
                    eshram_zk_valid   = :eshram_valid,
                    disclosure_level  = 1
                WHERE id = :rider_id
            """),
            {
                "nullifier": public_signals.nullifier,
                "proof_hash": result.proof_id,
                "verified_at": datetime.now(timezone.utc),
                "eshram_valid": public_signals.eshram_valid,
                "rider_id": rider_id,
            }
        )
        await db.commit()

    return {
        "verified": result.verified,
        "proof_id": result.proof_id,
        "nullifier": result.nullifier,
        "zk_verified_at": result.zk_verified_at.isoformat(),
        "message": result.message,
        "legacy_kyc_preserved": True,
        "note": "ZK verification is additive. Existing OTP KYC remains valid.",
    }


@router.post("/{rider_id}/generate-zk-proof")
async def generate_zk_proof_for_rider(
    rider_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    TEE-side ZK proof generation for WhatsApp-native flow.
    Innovation 04: ZeroKnow KYC (Session 3)

    Rider sends raw credentials over TLS; server generates proof in TEE.
    Returns { proof, public_signals, nullifier_secret }.
    The nullifier_secret is returned to the rider and NEVER stored by ZoneGuard.

    In production: deploy inside AWS Nitro Enclave.
    Request body: { "eshram_id": "..." }
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(status_code=503, detail="ZK identity module not available")

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    eshram_id = payload.get("eshram_id")

    try:
        proof, public_signals, nullifier_secret = await generate_flex_rider_proof(
            rider_id=rider_id,
            eshram_id=eshram_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "proof": proof.model_dump(),
        "public_signals": public_signals.model_dump(),
        "nullifier_secret": nullifier_secret,
        "instructions": {
            "step1": "Store nullifier_secret securely. ZoneGuard will NEVER store it.",
            "step2": "Call POST /{rider_id}/verify-zk with proof + public_signals.",
            "step3": "After verification, your DID Passport is created automatically.",
        },
        "tee_mode": "simulated",  # Change to "nitro" in production
    }


@router.get("/{rider_id}/did-passport")
async def get_rider_did_passport(
    rider_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a rider's CrossRider DID Passport.
    Innovation 09: CrossRider DID Passport (Session 3)

    Returns the rider's full DID Document + Verifiable Credentials.
    Requires zk_verified = True.
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(status_code=503, detail="ZK identity module not available")

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    if not getattr(rider, "zk_verified", False):
        raise HTTPException(
            status_code=403,
            detail="DID Passport requires ZK verification. "
                   "Complete POST /{rider_id}/generate-zk-proof then POST /{rider_id}/verify-zk first."
        )

    nullifier = getattr(rider, "nullifier_hash", None)
    if not nullifier:
        raise HTTPException(status_code=500, detail="Nullifier not found despite zk_verified=True")

    passport = assemble_did_passport(
        nullifier=nullifier,
        zone_id=rider.zone_id or "unknown",
        tenure_weeks=getattr(rider, "tenure_weeks", 0) or 0,
        platforms=[Platform.AMAZON_FLEX],
        eshram_valid=bool(getattr(rider, "eshram_zk_valid", 0)),
        zk_proof_id=getattr(rider, "zk_proof_hash", "") or "",
    )

    share_url = generate_share_url(nullifier)
    qr_payload = generate_qr_payload(passport)

    return {
        "passport": passport.model_dump(),
        "share_url": share_url,
        "qr_payload": qr_payload,
        "privacy_note": "This passport contains zero PII. Safe to share with NBFCs and platforms.",
    }

# ── End Session 3 endpoints ───────────────────────────────────────────────────
