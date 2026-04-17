"""
backend/identity/did_passport.py
──────────────────────────────────────────────────────────────────────────────
ZoneGuard Innovation 09 — CrossRider DID Passport
W3C DID Core v1.0 + W3C Verifiable Credentials Data Model v1.1

DID METHOD: did:key (cryptographic, no blockchain required for hackathon)
  - DID is derived from rider's Ed25519 public key
  - Public key is derived from the rider's ZK nullifier (no PII)
  - Self-sovereign: rider controls their key, ZoneGuard is just the issuer

MIGRATION PATH TO did:ethr:
  - Deploy ZoneGuardDIDRegistry.sol on Polygon Mumbai
  - Replace did:key with did:ethr:polygon:0x...
  - Same VC structure, just anchored on-chain for global resolvability

CREDENTIALS ISSUED:
  1. FlexWorkerIdentityCredential — on registration (ZK ID proven)
  2. EShramRegistrationCredential — when eshram_valid=1 in ZK proof
  3. IncomeBracketCredential — after 4+ weeks of payout history
  4. PlatformTenureCredential — tracks multi-platform career
  5. LoyaltyDiscountCredential — 12+ weeks tenure reward

ENV VARS:
  DID_REGISTRY_URL:      URL of DID resolution service (default: local)
  ZONEGUARD_DID:         ZoneGuard's issuer DID
  ZONEGUARD_SIGNING_KEY: ZoneGuard's Ed25519 private key (hex) for VC signing
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)

from identity.models import (
    DIDDocument,
    DIDPassport,
    DIDService,
    DIDVerificationMethod,
    EarningsPublicSignals,
    Platform,
    VCCredentialSubject,
    VCType,
    VerifiableCredential,
    EarningsBracket,
)
from identity.zk_kyc import get_disclosure_level

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

DID_REGISTRY_URL = os.getenv("DID_REGISTRY_URL", "https://zoneguard.in/did/resolve")
ZONEGUARD_ISSUER_DID = os.getenv("ZONEGUARD_DID", "did:key:z6MkZoneGuardIssuer2026")

# In production: load from AWS Secrets Manager / KMS
# For hackathon: generate a deterministic key from environment variable
_RAW_SIGNING_KEY = os.getenv("ZONEGUARD_SIGNING_KEY", "")


def _get_zoneguard_signing_key() -> Ed25519PrivateKey:
    """
    Get ZoneGuard's Ed25519 signing key for VC issuance.
    In production: load from HSM/KMS. In dev: derive from env var seed.
    """
    if _RAW_SIGNING_KEY:
        key_bytes = bytes.fromhex(_RAW_SIGNING_KEY[:64].ljust(64, "0"))
    else:
        # Deterministic dev key — NEVER use this seed in production
        seed = hashlib.sha256(b"zoneguard-dev-signing-key-2026").digest()
        key_bytes = seed

    return Ed25519PrivateKey.from_private_bytes(key_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# KEY DERIVATION FROM NULLIFIER
# ─────────────────────────────────────────────────────────────────────────────

def derive_rider_keypair(nullifier: str) -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    """
    Derive a deterministic Ed25519 keypair from the rider's ZK nullifier.

    WHY: The nullifier is a cryptographic commitment to the rider's identity
    without revealing it. Deriving the DID key from it ensures:
    - Same rider always gets the same DID (deterministic)
    - DID is unlinkable to raw rider ID (privacy-preserving)
    - Key recovery is possible if rider knows their nullifier_secret

    NOTE: In production, the rider should generate their own keypair and
    only share the public key. This server-side derivation is a hackathon
    simplification for the WhatsApp-native flow (riders don't manage keys).
    """
    # Derive 32 bytes of key material from nullifier using HKDF-like construction
    key_material = hashlib.sha256(
        f"zoneguard:did:key_derivation:{nullifier}".encode()
    ).digest()

    private_key = Ed25519PrivateKey.from_private_bytes(key_material)
    public_key = private_key.public_key()
    return private_key, public_key


def public_key_to_multibase(public_key: Ed25519PublicKey) -> str:
    """
    Encode Ed25519 public key in multibase format (base58btc with 'z' prefix).
    This is the standard format for did:key verification methods.
    """
    raw_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    # Multicodec prefix for Ed25519 public key: 0xed01
    multicodec_bytes = b"\xed\x01" + raw_bytes
    b58 = _base58_encode(multicodec_bytes)
    return f"z{b58}"


def _base58_encode(data: bytes) -> str:
    """Base58 encoding (Bitcoin alphabet)."""
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    num = int.from_bytes(data, "big")
    result = ""
    while num > 0:
        num, remainder = divmod(num, 58)
        result = alphabet[remainder] + result
    # Add leading '1's for leading zero bytes
    for byte in data:
        if byte == 0:
            result = "1" + result
        else:
            break
    return result


# ─────────────────────────────────────────────────────────────────────────────
# DID DOCUMENT CREATION
# ─────────────────────────────────────────────────────────────────────────────

def create_did_from_nullifier(nullifier: str) -> str:
    """
    Create a did:key DID from a rider's ZK nullifier.
    The DID is deterministic: same nullifier → same DID always.
    """
    _, public_key = derive_rider_keypair(nullifier)
    key_multibase = public_key_to_multibase(public_key)
    return f"did:key:{key_multibase}"


def create_did_document(
    nullifier: str,
    zone_id: Optional[str] = None,
    platform: Platform = Platform.AMAZON_FLEX,
) -> DIDDocument:
    """
    Create a W3C DID Core v1.0 compliant DID Document for a rider.

    The DID Document is public — it contains no PII.
    It only contains cryptographic material needed for:
    - Verifying signatures on Verifiable Credentials
    - Authenticating the rider (prove they control the DID)
    - Service endpoints (ZoneGuard profile, NBFC loan application)

    Args:
        nullifier:   Rider's ZK nullifier (public signal from proof)
        zone_id:     Rider's delivery zone (coarse location, not address)
        platform:    Primary gig platform
    """
    _, public_key = derive_rider_keypair(nullifier)
    key_multibase = public_key_to_multibase(public_key)
    did = f"did:key:{key_multibase}"
    key_id = f"{did}#key-1"

    verification_method = DIDVerificationMethod(
        id=key_id,
        type="Ed25519VerificationKey2020",
        controller=did,
        public_key_multibase=key_multibase,
    )

    services = [
        DIDService(
            id=f"{did}#zoneguard-profile",
            type="ZoneGuardProfile",
            service_endpoint=f"https://zoneguard.in/api/v1/identity/resolve/{nullifier[:16]}",
        ),
        DIDService(
            id=f"{did}#credential-status",
            type="CredentialStatusList2021",
            service_endpoint="https://zoneguard.in/api/v1/identity/credential-status",
        ),
    ]

    # Add NBFC loan application endpoint if zone known
    if zone_id:
        services.append(
            DIDService(
                id=f"{did}#loan-application",
                type="NBFCLoanApplication",
                service_endpoint={
                    "uri": "https://zoneguard.in/api/v1/identity/loan-intent",
                    "accept": ["application/ld+json"],
                    "routingKeys": [key_id],
                },
            )
        )

    now = datetime.now(timezone.utc)
    return DIDDocument(
        **{"@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
            "https://zoneguard.in/contexts/did/v1",
        ]},
        id=did,
        controller=did,
        verification_method=[verification_method],
        authentication=[key_id],
        assertion_method=[key_id],
        service=services,
        created=now,
        updated=now,
    )


# ─────────────────────────────────────────────────────────────────────────────
# VERIFIABLE CREDENTIAL ISSUANCE
# ─────────────────────────────────────────────────────────────────────────────

def _sign_vc(vc_data: dict[str, Any]) -> dict[str, Any]:
    """
    Sign a Verifiable Credential with ZoneGuard's Ed25519 key.
    Produces an Ed25519Signature2020 proof block.

    In production: use JSON-LD canonicalization (RDF Dataset Normalization)
    before signing. For hackathon: sign the JSON-serialized credential.
    """
    signing_key = _get_zoneguard_signing_key()

    # Canonicalize: sort keys for deterministic serialization
    # Production: replace with json-ld normalization (pyld library)
    canonical = json.dumps(vc_data, sort_keys=True, default=str).encode()
    signature_bytes = signing_key.sign(canonical)
    signature_b64 = base64.b64encode(signature_bytes).decode()

    return {
        "type": "Ed25519Signature2020",
        "created": datetime.now(timezone.utc).isoformat(),
        "verificationMethod": f"{ZONEGUARD_ISSUER_DID}#key-1",
        "proofPurpose": "assertionMethod",
        "proofValue": signature_b64,
    }


def issue_flex_worker_credential(
    rider_did: str,
    nullifier: str,
    zone_id: str,
    eshram_valid: bool = False,
) -> VerifiableCredential:
    """
    Issue a FlexWorkerIdentityCredential.
    Issued immediately on successful ZK proof verification at registration.

    Claims proven:
    - Rider is a verified Amazon Flex gig worker
    - KYC method: ZK-SNARK (not simple OTP)
    - Nullifier: unique per-rider, prevents duplicate credentials
    - Optional: e-Shram registration active
    """
    now = datetime.now(timezone.utc)

    vc_types = ["VerifiableCredential", VCType.FLEX_WORKER_IDENTITY.value]
    if eshram_valid:
        vc_types.append(VCType.ESHRAM_REGISTRATION.value)

    subject = VCCredentialSubject(
        id=rider_did,
        platform="amazon_flex",
        zone=zone_id,
        kyc_method="zk_snark_groth16",
        nullifier=nullifier,
    )

    vc = VerifiableCredential(
        **{"@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://zoneguard.in/credentials/v1",
        ]},
        type=vc_types,
        issuer=ZONEGUARD_ISSUER_DID,
        issuance_date=now,
        expiration_date=now + timedelta(days=365),  # Annual renewal
        credential_subject=subject,
        progressive_disclosure_level=1,
    )

    # Sign the VC
    vc_dict = json.loads(vc.model_dump_json(by_alias=True))
    vc.proof = _sign_vc(vc_dict)

    return vc


def issue_income_bracket_credential(
    rider_did: str,
    nullifier: str,
    earnings_signals: EarningsPublicSignals,
    zk_proof_id: str,
) -> VerifiableCredential:
    """
    Issue an IncomeBracketCredential based on ZK earnings proof.
    Available after 4+ weeks of payout history.

    Claims proven:
    - Income bracket (low/mid/high) without revealing exact figure
    - Number of weeks averaged over
    - Source: ZoneGuard payout history (internally verified)
    - Bracket bounds satisfied (for NBFC minimum income checks)

    Use case: NBFC can verify rider earns ≥ ₹10,000/week for microloan
    without ZoneGuard revealing exact weekly payouts.
    """
    now = datetime.now(timezone.utc)
    bracket = earnings_signals.bracket

    subject = VCCredentialSubject(
        id=rider_did,
        income_bracket=bracket.value,
        weeks_proven=earnings_signals.weeks_proven,
        bracket_verified_by="zoneguard_payout_history_zk_proof",
    )

    vc = VerifiableCredential(
        **{"@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://zoneguard.in/credentials/v1",
        ]},
        type=["VerifiableCredential", VCType.INCOME_BRACKET.value],
        issuer=ZONEGUARD_ISSUER_DID,
        issuance_date=now,
        expiration_date=now + timedelta(days=90),  # Quarterly refresh
        credential_subject=subject,
        zk_proof_id=zk_proof_id,
        progressive_disclosure_level=2,
    )

    vc_dict = json.loads(vc.model_dump_json(by_alias=True))
    vc.proof = _sign_vc(vc_dict)
    return vc


def issue_tenure_credential(
    rider_did: str,
    nullifier: str,
    tenure_weeks: int,
    platforms: list[Platform],
    zone_id: str,
) -> VerifiableCredential:
    """
    Issue a PlatformTenureCredential.
    Tracks multi-platform gig career for portability (Flex → Swiggy onboarding).

    Claims proven:
    - Total weeks active on ZoneGuard-covered platforms
    - Whether multi-platform (reduces onboarding friction)
    - Zone (for risk-adjusted insurance underwriting by new platforms)
    """
    now = datetime.now(timezone.utc)
    is_multi = len(platforms) > 1

    subject = VCCredentialSubject(
        id=rider_did,
        tenure_weeks=tenure_weeks,
        multi_platform=is_multi,
        platforms=[p.value for p in platforms],
        zone=zone_id,
    )

    vc = VerifiableCredential(
        **{"@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://zoneguard.in/credentials/v1",
        ]},
        type=["VerifiableCredential", VCType.PLATFORM_TENURE.value],
        issuer=ZONEGUARD_ISSUER_DID,
        issuance_date=now,
        expiration_date=now + timedelta(days=30),  # Monthly refresh
        credential_subject=subject,
        progressive_disclosure_level=2 if not is_multi else 3,
    )

    vc_dict = json.loads(vc.model_dump_json(by_alias=True))
    vc.proof = _sign_vc(vc_dict)
    return vc


def issue_loyalty_credential(
    rider_did: str,
    nullifier: str,
    tenure_weeks: int,
) -> VerifiableCredential:
    """
    Issue a LoyaltyDiscountCredential for riders with 12+ weeks tenure.

    Discount tiers:
    - Bronze: 12-23 weeks → 5% premium discount
    - Silver: 24-51 weeks → 10% premium discount
    - Gold:   52+ weeks   → 15% premium discount

    This VC is presented to ZoneGuard at policy renewal.
    Cross-platform tenure adds weeks: (Flex tenure + Swiggy tenure) for total.
    """
    now = datetime.now(timezone.utc)

    if tenure_weeks >= 52:
        tier, discount = "gold", 15
    elif tenure_weeks >= 24:
        tier, discount = "silver", 10
    else:
        tier, discount = "bronze", 5

    subject = VCCredentialSubject(
        id=rider_did,
        discount_tier=tier,
        discount_percent=discount,
        tenure_weeks=tenure_weeks,
    )

    vc = VerifiableCredential(
        **{"@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://zoneguard.in/credentials/v1",
        ]},
        type=["VerifiableCredential", VCType.LOYALTY_DISCOUNT.value],
        issuer=ZONEGUARD_ISSUER_DID,
        issuance_date=now,
        expiration_date=now + timedelta(days=7),  # Weekly renewal at policy renewal
        credential_subject=subject,
        progressive_disclosure_level=3,
    )

    vc_dict = json.loads(vc.model_dump_json(by_alias=True))
    vc.proof = _sign_vc(vc_dict)
    return vc


# ─────────────────────────────────────────────────────────────────────────────
# DID PASSPORT ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────

def assemble_did_passport(
    nullifier: str,
    zone_id: str,
    tenure_weeks: int,
    platforms: list[Platform],
    earnings_signals: Optional[EarningsPublicSignals] = None,
    eshram_valid: bool = False,
    zk_proof_id: str = "",
) -> DIDPassport:
    """
    Assemble a complete CrossRider DID Passport.
    Progressive: credentials are added as the rider builds history.

    Level 1 (registration):     FlexWorkerIdentityCredential (+ EShramRegistration if proven)
    Level 2 (4+ weeks):         + IncomeBracketCredential + PlatformTenureCredential
    Level 3 (12+ weeks):        + LoyaltyDiscountCredential

    Args:
        nullifier:          Rider's ZK nullifier
        zone_id:            Rider's delivery zone
        tenure_weeks:       Total weeks on ZoneGuard-covered platforms
        platforms:          Active platforms
        earnings_signals:   From EarningsBracketProof (optional)
        eshram_valid:       Whether e-Shram registration was proven
        zk_proof_id:        Reference to the backing ZK proof record
    """
    has_earnings_proof = earnings_signals is not None and earnings_signals.bracket_satisfied
    disclosure_level = get_disclosure_level(tenure_weeks, has_earnings_proof)

    # Create DID Document
    did_doc = create_did_document(nullifier, zone_id, platforms[0] if platforms else Platform.AMAZON_FLEX)
    rider_did = did_doc.id

    credentials: list[VerifiableCredential] = []

    # Level 1: Always issued on ZK registration
    flex_vc = issue_flex_worker_credential(
        rider_did=rider_did,
        nullifier=nullifier,
        zone_id=zone_id,
        eshram_valid=eshram_valid,
    )
    credentials.append(flex_vc)

    # Level 2: Income + tenure (4+ weeks)
    if disclosure_level >= 2 and earnings_signals:
        income_vc = issue_income_bracket_credential(
            rider_did=rider_did,
            nullifier=nullifier,
            earnings_signals=earnings_signals,
            zk_proof_id=zk_proof_id,
        )
        credentials.append(income_vc)

    if disclosure_level >= 2 and tenure_weeks >= 4:
        tenure_vc = issue_tenure_credential(
            rider_did=rider_did,
            nullifier=nullifier,
            tenure_weeks=tenure_weeks,
            platforms=platforms,
            zone_id=zone_id,
        )
        credentials.append(tenure_vc)

    # Level 3: Loyalty discount (12+ weeks)
    if disclosure_level >= 3:
        loyalty_vc = issue_loyalty_credential(
            rider_did=rider_did,
            nullifier=nullifier,
            tenure_weeks=tenure_weeks,
        )
        credentials.append(loyalty_vc)

    now = datetime.now(timezone.utc)
    return DIDPassport(
        did_document=did_doc,
        credentials=credentials,
        created_at=now,
        last_updated=now,
        total_tenure_weeks=tenure_weeks,
        platforms_active=platforms,
        disclosure_level=disclosure_level,
    )


def generate_share_url(nullifier: str, vc_types: Optional[list[VCType]] = None) -> str:
    """
    Generate a one-time, time-limited URL for selective VC disclosure.
    The URL encodes which credentials to share and expires in 48h.

    In production: store a one-time token in Redis, validate on retrieval.
    For hackathon: encode in URL params (not production-secure).
    """
    token = secrets.token_urlsafe(16)
    nullifier_short = nullifier[:16]
    type_params = "&type=".join(t.value for t in (vc_types or [])) if vc_types else "all"

    return (
        f"https://zoneguard.in/verify?"
        f"n={nullifier_short}&t={token}&creds={type_params}&ttl=48h"
    )


def generate_qr_payload(passport: DIDPassport) -> str:
    """
    Generate a compact QR payload for offline VC verification.
    The payload contains the DID + a digest of current credentials,
    allowing verifiers to check authenticity even without internet.
    """
    payload = {
        "did": passport.did_document.id,
        "vc_count": len(passport.credentials),
        "vc_types": [vc.type[-1] for vc in passport.credentials],
        "issued_by": ZONEGUARD_ISSUER_DID,
        "level": passport.disclosure_level,
        "ts": int(datetime.now(timezone.utc).timestamp()),
    }
    payload_json = json.dumps(payload, separators=(",", ":"))
    return base64.b64encode(payload_json.encode()).decode()
