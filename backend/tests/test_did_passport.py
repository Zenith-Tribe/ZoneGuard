"""Tests for CrossRider DID Passport — DID documents, Verifiable Credentials, DID resolution."""

import pytest
import pytest_asyncio

from identity.did_passport import (
    create_did_document,
    create_did_from_nullifier,
    issue_flex_worker_credential,
    issue_income_bracket_credential,
    issue_tenure_credential,
    issue_loyalty_credential,
)
from identity.did_resolver import resolve_did
from identity.models import (
    EarningsPublicSignals,
    Platform,
    VCType,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

# A deterministic nullifier (hex string >=32 chars) for repeatable tests
TEST_NULLIFIER = "ab" * 32  # 64 hex chars
TEST_ZONE_ID = "hsr"


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

class TestDIDDocument:
    def test_create_did_document(self):
        """DID Document must follow W3C structure: @context, id, verificationMethod, service."""
        doc = create_did_document(TEST_NULLIFIER, zone_id=TEST_ZONE_ID)

        # W3C DID Core v1.0 required fields
        context = doc.model_dump(by_alias=True)["@context"]
        assert "https://www.w3.org/ns/did/v1" in context

        assert doc.id.startswith("did:key:z")
        assert doc.controller == doc.id

        # verificationMethod
        assert len(doc.verification_method) >= 1
        vm = doc.verification_method[0]
        assert vm.type == "Ed25519VerificationKey2020"
        assert vm.controller == doc.id
        assert vm.public_key_multibase.startswith("z")

        # authentication and assertionMethod reference the key
        assert len(doc.authentication) >= 1
        assert len(doc.assertion_method) >= 1

        # service endpoints
        assert len(doc.service) >= 2  # ZoneGuardProfile + CredentialStatusList + optional loan


class TestVerifiableCredential:
    def test_issue_verifiable_credential(self):
        """Issued FlexWorkerIdentity VC must have issuer, credentialSubject, and proof."""
        rider_did = create_did_from_nullifier(TEST_NULLIFIER)

        vc = issue_flex_worker_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            zone_id=TEST_ZONE_ID,
            eshram_valid=True,
        )

        # W3C VC required fields
        assert vc.issuer is not None and len(vc.issuer) > 0
        assert vc.credential_subject is not None
        assert vc.credential_subject.id == rider_did
        assert vc.credential_subject.platform == "amazon_flex"
        assert vc.credential_subject.nullifier == TEST_NULLIFIER

        # Proof block must be present after signing
        assert vc.proof is not None
        assert vc.proof["type"] == "Ed25519Signature2020"
        assert "proofValue" in vc.proof
        assert "verificationMethod" in vc.proof

        # VC types must include both base and specific type
        assert "VerifiableCredential" in vc.type
        assert VCType.FLEX_WORKER_IDENTITY.value in vc.type
        # eshram_valid=True should add the EShram type
        assert VCType.ESHRAM_REGISTRATION.value in vc.type


class TestDIDResolution:
    @pytest.mark.asyncio
    async def test_resolve_did(self):
        """Creating a DID then resolving it should return the same document structure."""
        doc = create_did_document(TEST_NULLIFIER, zone_id=TEST_ZONE_ID)
        did = doc.id

        resolution = await resolve_did(did)

        assert resolution.did_document is not None
        assert resolution.did_document.id == did
        assert resolution.did_resolution_metadata.get("contentType") == "application/did+ld+json"

        # Verification method should match
        assert len(resolution.did_document.verification_method) >= 1
        resolved_vm = resolution.did_document.verification_method[0]
        original_vm = doc.verification_method[0]
        assert resolved_vm.public_key_multibase == original_vm.public_key_multibase


class TestAllCredentialTypes:
    def test_5_credential_types(self):
        """All 5 credential types must be issuable: FlexWorkerIdentity, EShramRegistration,
        IncomeBracket, PlatformTenure, LoyaltyDiscount."""
        rider_did = create_did_from_nullifier(TEST_NULLIFIER)

        # 1. FlexWorkerIdentityCredential
        flex_vc = issue_flex_worker_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            zone_id=TEST_ZONE_ID,
            eshram_valid=False,
        )
        assert VCType.FLEX_WORKER_IDENTITY.value in flex_vc.type
        assert flex_vc.proof is not None

        # 2. EShramRegistrationCredential (included when eshram_valid=True)
        eshram_vc = issue_flex_worker_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            zone_id=TEST_ZONE_ID,
            eshram_valid=True,
        )
        assert VCType.ESHRAM_REGISTRATION.value in eshram_vc.type
        assert eshram_vc.proof is not None

        # 3. IncomeBracketCredential
        earnings_signals = EarningsPublicSignals(
            bracket_index=1,  # mid bracket
            earnings_hash="a1b2c3d4" * 8,
            weeks_proven=8,
            platform_tag=1,
            lower_bound_satisfied=1,
            upper_bound_satisfied=1,
        )
        income_vc = issue_income_bracket_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            earnings_signals=earnings_signals,
            zk_proof_id="proof-123",
        )
        assert VCType.INCOME_BRACKET.value in income_vc.type
        assert income_vc.credential_subject.income_bracket == "mid"
        assert income_vc.proof is not None

        # 4. PlatformTenureCredential
        tenure_vc = issue_tenure_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            tenure_weeks=20,
            platforms=[Platform.AMAZON_FLEX, Platform.SWIGGY],
            zone_id=TEST_ZONE_ID,
        )
        assert VCType.PLATFORM_TENURE.value in tenure_vc.type
        assert tenure_vc.credential_subject.multi_platform is True
        assert tenure_vc.proof is not None

        # 5. LoyaltyDiscountCredential
        loyalty_vc = issue_loyalty_credential(
            rider_did=rider_did,
            nullifier=TEST_NULLIFIER,
            tenure_weeks=52,
        )
        assert VCType.LOYALTY_DISCOUNT.value in loyalty_vc.type
        assert loyalty_vc.credential_subject.discount_tier == "gold"
        assert loyalty_vc.credential_subject.discount_percent == 15
        assert loyalty_vc.proof is not None
