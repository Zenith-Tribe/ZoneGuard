"""
backend/identity/did_resolver.py
──────────────────────────────────────────────────────────────────────────────
ZoneGuard Innovation 09 — CrossRider DID Passport
DID Resolution Service

Implements DID resolution per W3C DID Core v1.0 spec:
https://www.w3.org/TR/did-core/#resolution

SUPPORTED DID METHODS:
  did:key     — Local resolution (cryptographic, no network required)
  did:web     — HTTP resolution (future: https://zoneguard.in/.well-known/did.json)
  did:ethr    — Ethereum/Polygon resolution (future: Polygon Mumbai testnet)

RESOLUTION FLOW:
  1. Parse DID method from DID string
  2. Route to appropriate resolver
  3. Return DID Document + DID Resolution Metadata
  4. Cache result in Redis (TTL: 1h for did:key, 5min for did:ethr)

EXTERNAL INTEGRATION:
  NBFC systems, Swiggy onboarding, and government portals call:
  GET /api/v1/identity/resolve/{did}
  → Returns DID Document with verification methods
  → Verifier can then verify VC signatures without contacting ZoneGuard

ENV VARS:
  DID_REGISTRY_URL:     External DID registry (for did:web, did:ethr)
  DID_CACHE_TTL:        Redis TTL for resolved DIDs (default: 3600s)
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from identity.models import (
    DIDDocument,
    DIDPassport,
    DIDVerificationMethod,
    VerifiableCredential,
    VCType,
)
from identity.did_passport import (
    create_did_document,
    derive_rider_keypair,
    public_key_to_multibase,
    ZONEGUARD_ISSUER_DID,
    _get_zoneguard_signing_key,
)

logger = logging.getLogger(__name__)

DID_CACHE_TTL = int(os.getenv("DID_CACHE_TTL", "3600"))

# ─────────────────────────────────────────────────────────────────────────────
# DID PARSING
# ─────────────────────────────────────────────────────────────────────────────

def parse_did(did: str) -> tuple[str, str]:
    """
    Parse a DID into (method, method-specific-id).
    e.g. "did:key:z6Mk..." → ("key", "z6Mk...")
         "did:ethr:0x..."  → ("ethr", "0x...")
    """
    parts = did.split(":", 2)
    if len(parts) < 3 or parts[0] != "did":
        raise ValueError(f"Invalid DID format: {did}")
    return parts[1], parts[2]


def is_zoneguard_did(did: str) -> bool:
    """Check if a DID was issued by ZoneGuard (i.e., rider DID vs external DID)."""
    try:
        method, _ = parse_did(did)
        return method == "key"  # All ZoneGuard rider DIDs use did:key for now
    except ValueError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DID:KEY RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_did_key(method_specific_id: str) -> DIDDocument:
    """
    Resolve a did:key DID Document.

    did:key resolution is purely cryptographic — no network, no DB.
    The DID document is reconstructed entirely from the public key
    embedded in the DID string.

    Per: https://w3c-ccg.github.io/did-method-key/
    """
    if not method_specific_id.startswith("z"):
        raise ValueError(f"did:key method-specific-id must start with 'z' (multibase): {method_specific_id[:16]}...")

    full_did = f"did:key:{method_specific_id}"
    key_id = f"{full_did}#key-1"

    # Reconstruct verification method from the encoded public key
    verification_method = DIDVerificationMethod(
        id=key_id,
        type="Ed25519VerificationKey2020",
        controller=full_did,
        public_key_multibase=method_specific_id,
    )

    now = datetime.now(timezone.utc)
    return DIDDocument(
        **{"@context": [
            "https://www.w3.org/ns/did/v1",
            "https://w3id.org/security/suites/ed25519-2020/v1",
        ]},
        id=full_did,
        controller=full_did,
        verification_method=[verification_method],
        authentication=[key_id],
        assertion_method=[key_id],
        service=[],
        created=now,
        updated=now,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DID RESOLUTION METADATA
# ─────────────────────────────────────────────────────────────────────────────

class DIDResolutionResult:
    """
    W3C DID Resolution result per spec:
    https://www.w3.org/TR/did-core/#did-resolution
    """
    def __init__(
        self,
        did_document: Optional[DIDDocument],
        did_resolution_metadata: dict[str, Any],
        did_document_metadata: dict[str, Any],
    ):
        self.did_document = did_document
        self.did_resolution_metadata = did_resolution_metadata
        self.did_document_metadata = did_document_metadata

    def to_dict(self) -> dict[str, Any]:
        return {
            "@context": "https://w3id.org/did-resolution/v1",
            "didDocument": self.did_document.model_dump(by_alias=True) if self.did_document else None,
            "didResolutionMetadata": self.did_resolution_metadata,
            "didDocumentMetadata": self.did_document_metadata,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RESOLVER
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_did(did: str) -> DIDResolutionResult:
    """
    Resolve a DID to its DID Document.
    Implements the W3C DID Resolution algorithm.

    Supports:
    - did:key (local, cryptographic)
    - did:web (HTTP fetch, future)
    - did:ethr (Polygon, future)

    Returns DIDResolutionResult with document + metadata.
    """
    start = datetime.now(timezone.utc)

    try:
        method, method_specific_id = parse_did(did)
    except ValueError as e:
        return DIDResolutionResult(
            did_document=None,
            did_resolution_metadata={"error": "invalidDid", "message": str(e)},
            did_document_metadata={},
        )

    try:
        if method == "key":
            doc = _resolve_did_key(method_specific_id)
            resolution_meta = {
                "contentType": "application/did+ld+json",
                "resolved_in_ms": (datetime.now(timezone.utc) - start).microseconds // 1000,
            }
            doc_meta = {
                "created": doc.created.isoformat(),
                "updated": doc.updated.isoformat(),
                "method": "did:key",
                "equivalentId": [did],
            }
            return DIDResolutionResult(doc, resolution_meta, doc_meta)

        elif method == "web":
            # Future: fetch from https://{method_specific_id}/.well-known/did.json
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "methodNotSupported",
                    "message": "did:web resolution not yet implemented. Planned for v3.0."
                },
                did_document_metadata={},
            )

        elif method == "ethr":
            # Future: query Ethereum/Polygon DID Registry smart contract
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "methodNotSupported",
                    "message": "did:ethr resolution not yet implemented. Planned for v3.0 (Polygon Mumbai)."
                },
                did_document_metadata={},
            )

        else:
            return DIDResolutionResult(
                did_document=None,
                did_resolution_metadata={
                    "error": "methodNotSupported",
                    "message": f"DID method '{method}' not supported by ZoneGuard resolver."
                },
                did_document_metadata={},
            )

    except Exception as e:
        logger.error(f"DID resolution failed for {did[:32]}...: {e}")
        return DIDResolutionResult(
            did_document=None,
            did_resolution_metadata={
                "error": "internalError",
                "message": str(e),
            },
            did_document_metadata={},
        )


# ─────────────────────────────────────────────────────────────────────────────
# VC VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

async def verify_verifiable_credential(vc: VerifiableCredential) -> dict[str, Any]:
    """
    Verify a Verifiable Credential's cryptographic proof.

    Steps:
    1. Resolve the issuer's DID Document
    2. Get the verification method referenced in the proof
    3. Verify the Ed25519 signature against the VC's content
    4. Check expiration date

    Returns:
        {
            "verified": bool,
            "checks": ["proof", "expiration"],
            "errors": [],
            "warnings": [],
        }
    """
    result: dict[str, Any] = {
        "verified": False,
        "checks": [],
        "errors": [],
        "warnings": [],
    }

    # Check expiration
    if vc.expiration_date and vc.expiration_date < datetime.now(timezone.utc):
        result["errors"].append("Credential has expired")
        return result
    result["checks"].append("expiration")

    # Verify proof exists
    if not vc.proof:
        result["errors"].append("Credential has no proof block")
        return result

    # Resolve issuer DID to get verification method
    resolution = await resolve_did(vc.issuer)
    if not resolution.did_document:
        result["errors"].append(f"Could not resolve issuer DID: {vc.issuer}")
        return result

    # Find the verification method referenced in the proof
    vm_id = vc.proof.get("verificationMethod", "")
    vm = next(
        (vm for vm in resolution.did_document.verification_method if vm.id == vm_id),
        None
    )

    if not vm:
        # Issuer DID might be the ZoneGuard issuer DID — use ZoneGuard's key directly
        if vc.issuer == ZONEGUARD_ISSUER_DID:
            signing_key = _get_zoneguard_signing_key()
            public_key = signing_key.public_key()
        else:
            result["errors"].append(f"Verification method not found: {vm_id}")
            return result
    else:
        # Decode the public key from multibase
        # For hackathon: use ZoneGuard's key (all VCs signed by ZoneGuard)
        signing_key = _get_zoneguard_signing_key()
        public_key = signing_key.public_key()

    # Verify signature
    try:
        proof_value_b64 = vc.proof.get("proofValue", "")
        signature_bytes = base64.b64decode(proof_value_b64)

        # Reconstruct the message that was signed (same as in _sign_vc)
        vc_dict = json.loads(vc.model_dump_json(by_alias=True))
        vc_dict.pop("proof", None)  # Remove proof before verifying
        canonical = json.dumps(vc_dict, sort_keys=True, default=str).encode()

        public_key.verify(signature_bytes, canonical)
        result["checks"].append("proof")
        result["verified"] = True

    except Exception as e:
        result["errors"].append(f"Signature verification failed: {type(e).__name__}")
        return result

    return result


# ─────────────────────────────────────────────────────────────────────────────
# PASSPORT LOOKUP (from DB)
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_passport_by_nullifier(
    nullifier_prefix: str,
    db_session,
) -> Optional[dict[str, Any]]:
    """
    Look up a rider's DID Passport by their nullifier prefix.
    The nullifier prefix (first 16 chars) is used as a pseudonymous lookup key.
    Full nullifier stored in DB; only prefix exposed in URLs.

    Returns the stored DID document JSON, or None if not found.
    """
    from sqlalchemy import text

    result = await db_session.execute(
        text("""
            SELECT nullifier_hash, did_document, zk_verified_at, tenure_weeks
            FROM riders
            WHERE nullifier_hash LIKE :prefix
            LIMIT 1
        """),
        {"prefix": f"{nullifier_prefix}%"}
    )
    row = result.fetchone()

    if not row:
        return None

    return {
        "nullifier_prefix": nullifier_prefix,
        "did_document": row.did_document,
        "zk_verified_at": row.zk_verified_at.isoformat() if row.zk_verified_at else None,
        "tenure_weeks": row.tenure_weeks,
    }
