"""
backend/identity/models.py
──────────────────────────────────────────────────────────────────────────────
ZoneGuard Identity System — Pydantic Models
Innovation 04: ZeroKnow KYC
Innovation 09: CrossRider DID Passport

All models are serializable to/from JSON for storage in PostgreSQL JSONB
columns and transmission over the ZoneGuard API.

DPDP Act 2023 note: No model in this file stores raw PII. Rider-identifying
fields always use hashes, nullifiers, or commitments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator
import uuid


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class EarningsBracket(str, Enum):
    """Income brackets for ZK earnings range proofs."""
    LOW  = "low"    # < ₹10,000/week
    MID  = "mid"    # ₹10,000–₹19,999/week
    HIGH = "high"   # ₹20,000+/week

    @classmethod
    def from_index(cls, idx: int) -> "EarningsBracket":
        return [cls.LOW, cls.MID, cls.HIGH][idx]

    def to_inr_range(self) -> tuple[int, int | None]:
        """Return (lower_bound, upper_bound) in INR. None = unbounded."""
        return {
            cls.LOW:  (0, 9999),
            cls.MID:  (10000, 19999),
            cls.HIGH: (20000, None),
        }[self]


class ProofCircuit(str, Enum):
    """Which Circom circuit was used to generate a proof."""
    FLEX_RIDER   = "FlexRiderProof"
    EARNINGS     = "EarningsBracketProof"


class ProofStatus(str, Enum):
    """Lifecycle states of a ZK proof."""
    PENDING   = "pending"    # Witness being generated (server-side TEE)
    GENERATED = "generated"  # Proof created, not yet verified
    VERIFIED  = "verified"   # Proof passed snarkjs verifyProof()
    FAILED    = "failed"     # Proof generation or verification failed
    EXPIRED   = "expired"    # Proof TTL exceeded (24h default)


class Platform(str, Enum):
    """Gig platforms for CrossRider DID portability."""
    AMAZON_FLEX = "amazon_flex"
    SWIGGY      = "swiggy"
    ZOMATO      = "zomato"
    DUNZO       = "dunzo"
    BLINKIT     = "blinkit"

    def to_circuit_id(self) -> int:
        return {
            Platform.AMAZON_FLEX: 1,
            Platform.SWIGGY:      2,
            Platform.ZOMATO:      3,
            Platform.DUNZO:       4,
            Platform.BLINKIT:     5,
        }[self]


class VCType(str, Enum):
    """Verifiable Credential claim types issued by ZoneGuard."""
    FLEX_WORKER_IDENTITY = "FlexWorkerIdentityCredential"
    ESHRAM_REGISTRATION  = "EShramRegistrationCredential"
    INCOME_BRACKET       = "IncomeBracketCredential"
    PLATFORM_TENURE      = "PlatformTenureCredential"
    PAYOUT_HISTORY       = "PayoutHistoryCredential"
    LOYALTY_DISCOUNT     = "LoyaltyDiscountCredential"


# ─────────────────────────────────────────────────────────────────────────────
# ZK PROOF MODELS
# ─────────────────────────────────────────────────────────────────────────────

class SnarkProof(BaseModel):
    """
    Raw Groth16 proof output from snarkjs.
    This is the actual cryptographic proof — 3 elliptic curve points.
    Stored only temporarily (24h cache); DB stores only the hash.
    """
    pi_a: list[str] = Field(..., description="G1 point [x, y, z]")
    pi_b: list[list[str]] = Field(..., description="G2 point [[x1,x2],[y1,y2],[z1,z2]]")
    pi_c: list[str] = Field(..., description="G1 point [x, y, z]")
    protocol: str = Field(default="groth16")
    curve: str = Field(default="bn128")


class PublicSignals(BaseModel):
    """
    Public signals output from a ZK proof — the only data ZoneGuard stores.
    All fields are cryptographic hashes/commitments, zero PII.
    """
    nullifier: str = Field(
        ...,
        description="Unique per-rider commitment. Prevents duplicate registration."
    )
    rider_id_hash: str = Field(
        ...,
        description="Poseidon hash of (rider_id_digits, salt). Identity commitment."
    )
    eshram_valid: int = Field(
        ...,
        ge=0, le=1,
        description="1 = active e-Shram registration proven, 0 = unproven"
    )


class EarningsPublicSignals(BaseModel):
    """Public signals from EarningsBracketProof circuit."""
    bracket_index: int = Field(..., ge=0, le=2)
    earnings_hash: str = Field(..., description="Commitment to earnings data")
    weeks_proven: int = Field(..., ge=1, le=52)
    platform_tag: int = Field(..., ge=1, le=5)
    lower_bound_satisfied: int = Field(..., ge=0, le=1)
    upper_bound_satisfied: int = Field(..., ge=0, le=1)

    @property
    def bracket(self) -> EarningsBracket:
        return EarningsBracket.from_index(self.bracket_index)

    @property
    def bracket_satisfied(self) -> bool:
        return bool(self.lower_bound_satisfied and self.upper_bound_satisfied)


class ZKProofRecord(BaseModel):
    """
    Complete ZK proof record stored (hashed) in ZoneGuard database.
    The proof itself is cached in Redis; only hashes enter PostgreSQL.
    """
    proof_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    circuit: ProofCircuit
    status: ProofStatus = ProofStatus.PENDING

    # Public signals (safe to store — no PII)
    nullifier: str
    proof_hash: str = Field(
        ...,
        description="SHA3-256 of the serialized SnarkProof. Allows re-verification."
    )

    # Metadata
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verified_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None  # 24h TTL
    verification_key_id: str = Field(
        default="zoneguard-vk-v1",
        description="Which verification key was used (for key rotation)"
    )

    # TEE attestation (for production — attestation that proof was generated
    # in a trusted execution environment, not on attacker-controlled hardware)
    tee_attestation: Optional[str] = Field(
        default=None,
        description="AWS Nitro or Intel TDX attestation quote (base64)"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class ZKVerifyRequest(BaseModel):
    """Request body for POST /riders/verify-zk endpoint."""
    # The proof (from client or TEE)
    proof: SnarkProof
    public_signals: PublicSignals

    # Anti-replay: include registration timestamp in commitment
    registration_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Optional: earnings proof to attach in same request
    earnings_proof: Optional[SnarkProof] = None
    earnings_signals: Optional[EarningsPublicSignals] = None

    @field_validator("public_signals")
    @classmethod
    def nullifier_not_empty(cls, v: PublicSignals) -> PublicSignals:
        if not v.nullifier or len(v.nullifier) < 32:
            raise ValueError("Nullifier must be a valid 32+ character hex string")
        return v


class ZKVerifyResponse(BaseModel):
    """Response from ZK verification endpoint."""
    verified: bool
    proof_id: str
    nullifier: str  # Safe to return — it's a public signal, not PII
    zk_verified_at: datetime
    earnings_bracket: Optional[EarningsBracket] = None
    message: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# W3C DID MODELS (Innovation 09 — CrossRider DID Passport)
# ─────────────────────────────────────────────────────────────────────────────

class DIDVerificationMethod(BaseModel):
    """
    W3C DID Core v1.0 — Verification Method.
    https://www.w3.org/TR/did-core/#verification-methods
    """
    id: str                  # e.g. "did:key:z6Mk...#key-1"
    type: str                # "Ed25519VerificationKey2020"
    controller: str          # DID that controls this key
    public_key_multibase: str  # Multibase-encoded public key


class DIDService(BaseModel):
    """
    W3C DID Core v1.0 — Service Endpoint.
    Used for NBFC loan applications, ZoneGuard profile, etc.
    """
    id: str
    type: str
    service_endpoint: str | dict[str, str]


class DIDDocument(BaseModel):
    """
    W3C DID Core v1.0 compliant DID Document.
    https://www.w3.org/TR/did-core/#did-documents

    Method: did:key (cryptographic, no blockchain needed for hackathon)
    Migration path: did:ethr (Polygon Mumbai) for production

    The DID is derived from the rider's ZK nullifier, ensuring:
    - No PII in the DID itself
    - Deterministic: same nullifier always produces same DID
    - Portable across platforms
    """
    context: list[str] = Field(
        default=[
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
        ],
        alias="@context"
    )
    id: str = Field(..., description="The DID: did:key:z6Mk...")
    controller: str = Field(..., description="Same as id for self-sovereign identity")
    verification_method: list[DIDVerificationMethod]
    authentication: list[str] = Field(
        ..., description="References to verification methods for auth"
    )
    assertion_method: list[str] = Field(
        ..., description="References to verification methods for signing VCs"
    )
    service: list[DIDService] = Field(default=[])

    # ZoneGuard extensions (outside W3C spec — use custom namespace)
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class VCCredentialSubject(BaseModel):
    """
    The subject of a Verifiable Credential — what is being claimed.
    All claims use ZK-proven data; no raw PII.
    """
    id: str = Field(..., description="The rider's DID")

    # FlexWorkerIdentityCredential claims
    platform: Optional[str] = None          # "amazon_flex"
    zone: Optional[str] = None              # "hsr" (zone ID, not personal address)
    kyc_method: Optional[str] = None        # "zk_snark_groth16"
    nullifier: Optional[str] = None         # ZK nullifier (public signal)

    # IncomeBracketCredential claims
    income_bracket: Optional[str] = None    # "mid" (never exact figure)
    weeks_proven: Optional[int] = None      # Rolling window size
    bracket_verified_by: Optional[str] = None  # "zoneguard_payout_history"

    # PlatformTenureCredential claims
    tenure_weeks: Optional[int] = None
    multi_platform: Optional[bool] = None
    platforms: Optional[list[str]] = None

    # LoyaltyDiscountCredential claims
    discount_tier: Optional[str] = None    # "gold", "silver", "bronze"
    discount_percent: Optional[int] = None


class VerifiableCredential(BaseModel):
    """
    W3C Verifiable Credentials Data Model v1.1.
    https://www.w3.org/TR/vc-data-model/

    Issued by ZoneGuard as the credential issuer.
    Signed with ZoneGuard's Ed25519 private key.
    Rider controls presentation — they choose what to share.
    """
    context: list[str] = Field(
        default=[
            "https://www.w3.org/2018/credentials/v1",
            "https://zoneguard.in/credentials/v1",  # ZoneGuard custom vocab
        ],
        alias="@context"
    )
    id: str = Field(default_factory=lambda: f"urn:uuid:{uuid.uuid4()}")
    type: list[str] = Field(
        ...,
        description="['VerifiableCredential', '<SpecificType>']"
    )
    issuer: str = Field(
        default="did:key:z6MkZoneGuard2026",  # ZoneGuard's DID
        description="ZoneGuard's DID as credential issuer"
    )
    issuance_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expiration_date: Optional[datetime] = None

    credential_subject: VCCredentialSubject

    # Proof (Ed25519Signature2020)
    proof: Optional[dict[str, Any]] = Field(
        default=None,
        description="Ed25519Signature2020 proof block. Added after signing."
    )

    # ZoneGuard metadata (not part of W3C spec)
    zk_proof_id: Optional[str] = Field(
        default=None,
        description="Reference to the ZK proof that backs this credential"
    )
    progressive_disclosure_level: int = Field(
        default=1,
        ge=1, le=3,
        description="1=basic identity, 2=income bracket, 3=full history + loyalty"
    )

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


class DIDPassport(BaseModel):
    """
    The complete CrossRider DID Passport — a rider's portable professional identity.
    Aggregates all VCs into a single shareable bundle.

    Use cases:
    - NBFC microloan application: share IncomeBracketCredential
    - Platform switch (Flex → Swiggy): share PlatformTenureCredential
    - Government scheme: share EShramRegistrationCredential
    - ZoneGuard loyalty discount: share LoyaltyDiscountCredential
    """
    did_document: DIDDocument
    credentials: list[VerifiableCredential] = Field(default=[])

    # Passport metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_tenure_weeks: int = Field(default=0)
    platforms_active: list[Platform] = Field(default=[])

    # Progressive disclosure state
    disclosure_level: int = Field(
        default=1,
        description="Current disclosure level. Upgrades as rider builds history."
    )

    def get_credentials_by_type(self, vc_type: VCType) -> list[VerifiableCredential]:
        """Filter credentials by type for selective disclosure."""
        return [
            vc for vc in self.credentials
            if vc_type.value in vc.type
        ]

    def is_eligible_for_microloan(self) -> bool:
        """Check if rider has proven income bracket ≥ mid for NBFC eligibility."""
        income_vcs = self.get_credentials_by_type(VCType.INCOME_BRACKET)
        if not income_vcs:
            return False
        for vc in income_vcs:
            if vc.credential_subject.income_bracket in ["mid", "high"]:
                return True
        return False

    def is_eligible_for_loyalty_discount(self) -> bool:
        """12+ weeks multi-platform tenure → loyalty discount."""
        return self.total_tenure_weeks >= 12 and len(self.platforms_active) >= 1

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class DIDPassportResponse(BaseModel):
    """API response wrapping the DID Passport."""
    passport: DIDPassport
    share_url: str = Field(
        ...,
        description="One-time URL for selective disclosure sharing (48h TTL)"
    )
    qr_payload: str = Field(
        ...,
        description="Base64-encoded QR payload for offline verification"
    )


class CredentialIssuanceRequest(BaseModel):
    """Request to issue a new Verifiable Credential."""
    rider_nullifier: str     # Identifies rider without PII
    vc_type: VCType
    disclosure_level: int = Field(default=1, ge=1, le=3)
    platform: Platform = Platform.AMAZON_FLEX

    # For income bracket VCs — pass the earnings proof signals
    earnings_signals: Optional[EarningsPublicSignals] = None
    tenure_weeks: Optional[int] = None
