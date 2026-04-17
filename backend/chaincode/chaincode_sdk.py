"""
chaincode_sdk.py — Python wrapper for ZoneGuard Hyperledger Fabric chaincode invocations.

Wraps the ZoneChain fabric_client.py (provided by another session) to give the
FastAPI routers a clean, typed interface for all three chaincodes:
  - PolicyChaincode: create_policy, renew_policy, amend_policy, cancel_policy
  - ClaimChaincode:  trigger_claim, record_fraud_score, approve_claim, reject_claim, challenge_claim
  - GovernanceChaincode: propose_change, vote, finalise, get_parameter

All calls are async. Fabric errors are translated to structured ChaincodError exceptions
so the FastAPI routers can return appropriate HTTP status codes.

Usage:
    from backend.chaincode.chaincode_sdk import PolicySDK, ClaimSDK, GovernanceSDK

    sdk = PolicySDK()
    result = await sdk.create_policy(policy_id="P123", rider_id="R1", ...)
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── Chaincode names (must match Fabric peer channel config) ─────────────────

POLICY_CHAINCODE     = "policy_chaincode"
CLAIM_CHAINCODE      = "claim_chaincode"
GOVERNANCE_CHAINCODE = "governance_chaincode"
CHANNEL_NAME         = "zoneguard-channel"


# ─── Exceptions ───────────────────────────────────────────────────────────────

class ChaincodeError(Exception):
    """Raised when a chaincode invocation returns an error or fails connectivity."""
    def __init__(self, chaincode: str, function: str, detail: str, raw: Any = None):
        self.chaincode = chaincode
        self.function = function
        self.detail = detail
        self.raw = raw
        super().__init__(f"[{chaincode}.{function}] {detail}")


class ChaincodeUnavailableError(ChaincodeError):
    """Raised when the Fabric peer is unreachable or the SDK client fails to initialise."""
    pass


# ─── Fabric Client Adapter ────────────────────────────────────────────────────

class FabricClientAdapter:
    """
    Thin adapter around the ZoneChain fabric_client.py provided by the blockchain session.
    Falls back to a local mock mode if fabric_client is not yet available (dev/test).
    """

    def __init__(self):
        self._client = None
        self._mock_mode = False
        self._mock_ledger: dict[str, dict] = {}  # in-process ledger for testing

    async def _get_client(self):
        """Lazy-initialise the fabric SDK client."""
        if self._client is not None:
            return self._client
        try:
            # Import the ZoneChain fabric client (provided by blockchain session)
            from backend.blockchain.fabric_client import FabricClient  # type: ignore
            self._client = FabricClient(channel=CHANNEL_NAME)
            await self._client.connect()
            logger.info("FabricClientAdapter: connected to ZoneChain Fabric network")
        except ImportError:
            logger.warning(
                "FabricClientAdapter: fabric_client.py not available — running in MOCK MODE. "
                "All chaincode calls will use an in-process ledger. DO NOT use in production."
            )
            self._mock_mode = True
        except Exception as exc:
            raise ChaincodeUnavailableError(
                chaincode="fabric",
                function="connect",
                detail=f"Failed to connect to Fabric peer: {exc}",
            ) from exc
        return self._client

    async def invoke(self, chaincode: str, function: str, args: list[str]) -> dict:
        """Submit a transaction (read-write) to the Fabric peer."""
        if self._mock_mode:
            return await self._mock_invoke(chaincode, function, args)
        client = await self._get_client()
        try:
            response = await client.chaincode_invoke(
                chaincode_name=chaincode,
                function=function,
                args=args,
            )
            return self._parse_response(chaincode, function, response)
        except ChaincodeError:
            raise
        except Exception as exc:
            raise ChaincodeError(chaincode, function, str(exc)) from exc

    async def query(self, chaincode: str, function: str, args: list[str]) -> dict:
        """Submit a read-only query to the Fabric peer."""
        if self._mock_mode:
            return await self._mock_query(chaincode, function, args)
        client = await self._get_client()
        try:
            response = await client.chaincode_query(
                chaincode_name=chaincode,
                function=function,
                args=args,
            )
            return self._parse_response(chaincode, function, response)
        except ChaincodeError:
            raise
        except Exception as exc:
            raise ChaincodeError(chaincode, function, str(exc)) from exc

    def _parse_response(self, chaincode: str, function: str, response: Any) -> dict:
        """Parse Fabric SDK response into a Python dict."""
        if response is None:
            raise ChaincodeError(chaincode, function, "Empty response from chaincode")
        # fabric-sdk-py returns bytes payload
        if isinstance(response, bytes):
            try:
                return json.loads(response.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ChaincodeError(chaincode, function, f"Invalid JSON response: {exc}", raw=response)
        if isinstance(response, dict):
            return response
        raise ChaincodeError(chaincode, function, f"Unexpected response type: {type(response)}", raw=response)

    # ── Mock mode (used when fabric_client.py is unavailable) ────────────────

    async def _mock_invoke(self, chaincode: str, function: str, args: list[str]) -> dict:
        """
        Minimal in-process mock of chaincode invocation.
        Stores state in self._mock_ledger for round-trip testing only.
        Does NOT implement full business logic — use only in unit tests.
        """
        logger.debug(f"MOCK INVOKE {chaincode}.{function}({args})")
        key = f"{chaincode}::{function}::{':'.join(args[:1])}"
        result = {
            "mock": True,
            "chaincode": chaincode,
            "function": function,
            "args": args,
            "tx_id": hashlib.sha256(key.encode()).hexdigest()[:16],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if args:
            try:
                payload = json.loads(args[0])
                result.update(payload)
            except (json.JSONDecodeError, IndexError):
                pass
        self._mock_ledger[key] = result
        return result

    async def _mock_query(self, chaincode: str, function: str, args: list[str]) -> dict:
        logger.debug(f"MOCK QUERY {chaincode}.{function}({args})")
        return {"mock": True, "chaincode": chaincode, "function": function, "result": None}


# Shared singleton adapter
_adapter = FabricClientAdapter()


# ─── PolicySDK ────────────────────────────────────────────────────────────────

class PolicySDK:
    """High-level Python interface to PolicyChaincode."""

    async def create_policy(
        self,
        policy_id: str,
        rider_id: str,
        zone_id: str,
        weekly_premium: float,
        max_payout: float,
        coverage_start: str,
        coverage_end: str,
        is_forward_locked: bool = False,
        forward_lock_weeks: int = 0,
    ) -> dict:
        """Record a new policy on-chain. Enforces Forward Premium Lock discount immutably."""
        payload = json.dumps({
            "policy_id": policy_id,
            "rider_id": rider_id,
            "zone_id": zone_id,
            "weekly_premium": weekly_premium,
            "max_payout": max_payout,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "is_forward_locked": is_forward_locked,
            "forward_lock_weeks": forward_lock_weeks,
        })
        result = await _adapter.invoke(POLICY_CHAINCODE, "CreatePolicy", [payload])
        logger.info(f"PolicySDK.create_policy: policy {policy_id} recorded on-chain")
        return result

    async def renew_policy(self, policy_id: str, new_coverage_start: str, new_coverage_end: str) -> dict:
        result = await _adapter.invoke(
            POLICY_CHAINCODE, "RenewPolicy",
            [policy_id, new_coverage_start, new_coverage_end]
        )
        logger.info(f"PolicySDK.renew_policy: policy {policy_id} renewed on-chain")
        return result

    async def amend_policy(self, policy_id: str, amendments: dict, amended_by: str) -> dict:
        result = await _adapter.invoke(
            POLICY_CHAINCODE, "AmendPolicy",
            [policy_id, json.dumps(amendments), amended_by]
        )
        logger.info(f"PolicySDK.amend_policy: policy {policy_id} amended by {amended_by}")
        return result

    async def cancel_policy(self, policy_id: str, cancelled_by: str) -> dict:
        result = await _adapter.invoke(POLICY_CHAINCODE, "CancelPolicy", [policy_id, cancelled_by])
        logger.info(f"PolicySDK.cancel_policy: policy {policy_id} cancelled on-chain")
        return result

    async def query_policy(self, policy_id: str) -> dict:
        return await _adapter.query(POLICY_CHAINCODE, "QueryPolicy", [policy_id])


# ─── ClaimSDK ─────────────────────────────────────────────────────────────────

class ClaimSDK:
    """High-level Python interface to ClaimChaincode."""

    async def trigger_claim(
        self,
        claim_id: str,
        policy_id: str,
        rider_id: str,
        zone_id: str,
        confidence_level: str,
        signals_fired: int,
        signal_details: dict,
        oracle_consensus_ref: str,
        seven_day_rolling_earnings: float,
        eligible_days: int,
        policy_max_payout: float,
    ) -> dict:
        """
        Record a claim on-chain. The payout formula (55% × daily_avg × eligible_days)
        is computed INSIDE the chaincode — the result returned here is authoritative.
        """
        payload = json.dumps({
            "claim_id": claim_id,
            "policy_id": policy_id,
            "rider_id": rider_id,
            "zone_id": zone_id,
            "confidence_level": confidence_level,
            "signals_fired": signals_fired,
            "signal_details": signal_details,
            "oracle_consensus_ref": oracle_consensus_ref,
            "seven_day_rolling_earnings": seven_day_rolling_earnings,
            "eligible_days": eligible_days,
            "policy_max_payout": policy_max_payout,
        })
        result = await _adapter.invoke(CLAIM_CHAINCODE, "TriggerClaim", [payload])
        logger.info(
            f"ClaimSDK.trigger_claim: claim {claim_id} recorded on-chain. "
            f"recommended_payout={result.get('recommended_payout', '?')}"
        )
        return result

    async def record_fraud_score(self, claim_id: str, fraud_score: float, recorded_by: str) -> dict:
        """
        Write FraudShield score to chain BEFORE any payout decision.
        If score > 0.75, chaincode auto-rejects the claim immutably.
        """
        result = await _adapter.invoke(
            CLAIM_CHAINCODE, "RecordFraudScore",
            [claim_id, str(fraud_score), recorded_by]
        )
        auto_rejected = result.get("fraud_auto_rejected", False)
        if auto_rejected:
            logger.warning(f"ClaimSDK.record_fraud_score: claim {claim_id} AUTO-REJECTED by FraudShield (score={fraud_score})")
        else:
            logger.info(f"ClaimSDK.record_fraud_score: claim {claim_id} score={fraud_score} recorded")
        return result

    async def approve_claim(self, claim_id: str, reviewed_by: str, upi_ref: str) -> dict:
        """
        Approve a claim. upi_ref is hashed before writing to chain (PII protection).
        The raw UPI reference stays off-chain; only its SHA-256 fingerprint is recorded.
        """
        upi_ref_hash = hashlib.sha256(upi_ref.encode("utf-8")).hexdigest()
        result = await _adapter.invoke(
            CLAIM_CHAINCODE, "ApproveClaim",
            [claim_id, reviewed_by, upi_ref_hash]
        )
        logger.info(f"ClaimSDK.approve_claim: claim {claim_id} approved. UPI hash={upi_ref_hash[:8]}...")
        return result

    async def reject_claim(self, claim_id: str, reviewed_by: str, reason: str) -> dict:
        result = await _adapter.invoke(
            CLAIM_CHAINCODE, "RejectClaim",
            [claim_id, reviewed_by, reason]
        )
        logger.info(f"ClaimSDK.reject_claim: claim {claim_id} rejected by {reviewed_by}")
        return result

    async def challenge_claim(self, claim_id: str, rider_id: str, reason: str) -> dict:
        result = await _adapter.invoke(
            CLAIM_CHAINCODE, "ChallengeClaim",
            [claim_id, rider_id, reason]
        )
        logger.info(f"ClaimSDK.challenge_claim: claim {claim_id} challenged by rider {rider_id}")
        return result

    async def query_claim(self, claim_id: str) -> dict:
        return await _adapter.query(CLAIM_CHAINCODE, "QueryClaim", [claim_id])


# ─── GovernanceSDK ────────────────────────────────────────────────────────────

class GovernanceSDK:
    """High-level Python interface to GovernanceChaincode."""

    async def get_parameter(self, param_name: str) -> str:
        """Read a governed parameter value from the chain."""
        result = await _adapter.query(GOVERNANCE_CHAINCODE, "GetParameter", [param_name])
        return str(result.get("value", result))

    async def get_all_parameters(self) -> dict:
        """Read all governed parameters from the chain."""
        return await _adapter.query(GOVERNANCE_CHAINCODE, "GetAllParameters", [])

    async def propose_change(
        self,
        proposal_id: str,
        param_name: str,
        proposed_value: str,
        rationale: str,
        proposed_by: str,
    ) -> dict:
        result = await _adapter.invoke(
            GOVERNANCE_CHAINCODE, "ProposeParameterChange",
            [proposal_id, param_name, proposed_value, rationale, proposed_by]
        )
        logger.info(f"GovernanceSDK.propose_change: proposal {proposal_id} created for param {param_name}")
        return result

    async def vote(self, proposal_id: str, voter_org: str, vote: str) -> dict:
        if vote not in ("YES", "NO"):
            raise ValueError(f"Vote must be 'YES' or 'NO', got '{vote}'")
        result = await _adapter.invoke(
            GOVERNANCE_CHAINCODE, "VoteOnProposal",
            [proposal_id, voter_org, vote]
        )
        logger.info(f"GovernanceSDK.vote: {voter_org} voted {vote} on proposal {proposal_id}")
        return result

    async def finalise(self, proposal_id: str, finalised_by: str) -> dict:
        result = await _adapter.invoke(
            GOVERNANCE_CHAINCODE, "FinaliseProposal",
            [proposal_id, finalised_by]
        )
        logger.info(
            f"GovernanceSDK.finalise: proposal {proposal_id} finalised. "
            f"status={result.get('status', '?')}"
        )
        return result

    async def query_proposal(self, proposal_id: str) -> dict:
        return await _adapter.query(GOVERNANCE_CHAINCODE, "QueryProposal", [proposal_id])


# ─── Convenience singletons (import these in routers) ────────────────────────

policy_sdk     = PolicySDK()
claim_sdk      = ClaimSDK()
governance_sdk = GovernanceSDK()
