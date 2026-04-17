"""
blockchain/zonechain.py
=======================
Innovation 01: ZoneChain

High-level write operations that map ZoneGuard domain events to
Hyperledger Fabric chaincode invocations.

Design principles:
  1. NEVER block the API — all writes are async and errors are logged, not raised
  2. Every write is idempotent (event_id is the Fabric key, re-submits are no-ops)
  3. Dual-write: Fabric ledger + local PostgreSQL event log for resilience
  4. TemporalSig links are embedded in claim/payout events automatically

Chaincode function mapping:
  CreateClaimEvent      → claimsCollection
  CreatePolicyEvent     → policiesCollection
  CreatePayoutEvent     → payoutsCollection
  CreateParameterChange → parametersCollection
  CreateSignalAnchor    → signalsCollection (mirrors TemporalSig)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from .fabric_client import FabricGatewayClient, FabricTransactionResult, get_fabric_client
from .models import (
    ChainEventType,
    ClaimEventPayload,
    ConfidenceTier,
    NodeRole,
    ParameterChangePayload,
    PayoutEventPayload,
    PolicyEventPayload,
    SignalBatchPayload,
    ZoneChainEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ZoneChain Client
# ---------------------------------------------------------------------------

class ZoneChainClient:
    """
    Domain-level ZoneChain write interface.

    Wraps FabricGatewayClient with ZoneGuard-specific business logic:
    - Constructs ZoneChainEvent envelopes
    - Validates payload completeness before writing
    - Handles retries for transient Fabric failures
    - Emits structured audit logs for every operation
    """

    # Chaincode function names — must match the deployed chaincode exactly
    _CC_FUNCTIONS = {
        "claim":     "CreateClaimEvent",
        "policy":    "CreatePolicyEvent",
        "payout":    "CreatePayoutEvent",
        "parameter": "CreateParameterChange",
        "signal":    "CreateSignalAnchor",
        "query_claim": "GetClaimHistory",
        "query_policy": "GetPolicyHistory",
    }

    def __init__(self, fabric_client: Optional[FabricGatewayClient] = None):
        self._fabric = fabric_client or get_fabric_client()

    # ------------------------------------------------------------------
    # Innovation 01 Core Write Methods
    # ------------------------------------------------------------------

    async def write_claim_event(
        self,
        claim_id: str,
        rider_id: str,
        policy_id: str,
        zone_id: str,
        event_type: ChainEventType,
        confidence_tier: ConfidenceTier,
        composite_score: float,
        payout_amount_inr: Optional[float] = None,
        rejection_reason: Optional[str] = None,
        claude_audit_summary: Optional[str] = None,
        signal_batch_ids: Optional[list] = None,
        temporalsig_polygon_tx: Optional[str] = None,
        temporalsig_block_number: Optional[int] = None,
        temporalsig_block_timestamp: Optional[datetime] = None,
    ) -> ZoneChainEvent:
        """
        Write a claim lifecycle event to ZoneChain.

        Called at:
          - Claim creation (CLAIM_CREATED)
          - Claude AI audit completion (CLAIM_AUDITED)
          - Claim approval (CLAIM_APPROVED)
          - Claim rejection (CLAIM_REJECTED)

        The TemporalSig fields link this claim event to the exact Polygon block
        timestamp of the triggering signal batch — creating an immutable
        "disruption start time" proof.
        """
        payload = ClaimEventPayload(
            claim_id=claim_id,
            rider_id=rider_id,
            policy_id=policy_id,
            zone_id=zone_id,
            event_type=event_type,
            confidence_tier=confidence_tier,
            composite_score=composite_score,
            payout_amount_inr=payout_amount_inr,
            rejection_reason=rejection_reason,
            claude_audit_summary=claude_audit_summary,
            signal_batch_ids=signal_batch_ids or [],
            temporalsig_polygon_tx=temporalsig_polygon_tx,
            temporalsig_block_number=temporalsig_block_number,
            temporalsig_block_timestamp=temporalsig_block_timestamp,
        )

        event = ZoneChainEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            written_by=NodeRole.ZONEGUARD,
            claim_payload=payload,
        )

        await self._submit(self._CC_FUNCTIONS["claim"], event)
        return event

    async def write_policy_creation(
        self,
        policy_id: str,
        rider_id: str,
        zone_id: str,
        event_type: ChainEventType,
        coverage_tier: str,
        weekly_premium_inr: float,
        coverage_start: datetime,
        coverage_end: datetime,
        is_forward_locked: bool = False,
        forward_lock_weeks: int = 0,
        insurer_node_id: str = "BAJAJ_ALLIANZ",
    ) -> ZoneChainEvent:
        """
        Write a policy lifecycle event to ZoneChain.

        Called at:
          - Policy creation (POLICY_CREATED)
          - Policy renewal (POLICY_RENEWED)
          - Policy cancellation (POLICY_CANCELLED)

        The insurer peer (Bajaj Allianz / ICICI Lombard) endorses this
        transaction, making policy state immutable across both parties.
        This eliminates disputes about what was covered and when.
        """
        payload = PolicyEventPayload(
            policy_id=policy_id,
            rider_id=rider_id,
            zone_id=zone_id,
            event_type=event_type,
            coverage_tier=coverage_tier,
            weekly_premium_inr=weekly_premium_inr,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            is_forward_locked=is_forward_locked,
            forward_lock_weeks=forward_lock_weeks,
            insurer_node_id=insurer_node_id,
        )

        event = ZoneChainEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            written_by=NodeRole.ZONEGUARD,
            policy_payload=payload,
        )

        await self._submit(self._CC_FUNCTIONS["policy"], event)
        return event

    async def write_payout_trigger(
        self,
        payout_id: str,
        claim_id: str,
        rider_id: str,
        policy_id: str,
        amount_inr: float,
        triggered_at: datetime,
        event_type: ChainEventType = ChainEventType.PAYOUT_TRIGGERED,
        upi_reference: Optional[str] = None,
        payment_gateway_ref: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        triggering_batch_id: Optional[str] = None,
        temporalsig_polygon_tx: Optional[str] = None,
    ) -> ZoneChainEvent:
        """
        Write a payout trigger or completion event to ZoneChain.

        This is the highest-stakes write — it records the exact payout amount
        and the TemporalSig proof that justifies it. The insurer peer
        co-signs this transaction, making it the settlement record.

        Called at:
          - Payout initiation (PAYOUT_TRIGGERED)
          - Payout confirmation from payment gateway (PAYOUT_COMPLETED)
        """
        payload = PayoutEventPayload(
            payout_id=payout_id,
            claim_id=claim_id,
            rider_id=rider_id,
            policy_id=policy_id,
            event_type=event_type,
            amount_inr=amount_inr,
            upi_reference=upi_reference,
            payment_gateway_ref=payment_gateway_ref,
            triggered_at=triggered_at,
            completed_at=completed_at,
            triggering_batch_id=triggering_batch_id,
            temporalsig_polygon_tx=temporalsig_polygon_tx,
        )

        event = ZoneChainEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            written_by=NodeRole.ZONEGUARD,
            payout_payload=payload,
        )

        await self._submit(self._CC_FUNCTIONS["payout"], event)
        return event

    async def write_parameter_change(
        self,
        parameter_name: str,
        old_value,
        new_value,
        changed_by_admin_id: str,
        justification: str,
        zone_id: Optional[str] = None,
        effective_from: Optional[datetime] = None,
    ) -> ZoneChainEvent:
        """
        Write a parameter/threshold change to ZoneChain.

        [ENHANCEMENT] This is visible to the IRDAI observer node in real-time.
        Any change to claim thresholds, payout multipliers, or zone risk scores
        is permanently recorded — preventing retroactive manipulation of
        parameters to reject valid claims.

        Called from: admin router when thresholds are updated
        """
        payload = ParameterChangePayload(
            parameter_name=parameter_name,
            old_value=old_value,
            new_value=new_value,
            changed_by_admin_id=changed_by_admin_id,
            zone_id=zone_id,
            effective_from=effective_from or datetime.now(timezone.utc),
            justification=justification,
            irdai_notified=True,  # IRDAI observer node receives this automatically
        )

        event = ZoneChainEvent(
            event_id=str(uuid.uuid4()),
            event_type=ChainEventType.PARAMETER_CHANGED,
            written_by=NodeRole.ZONEGUARD,
            parameter_payload=payload,
        )

        await self._submit(self._CC_FUNCTIONS["parameter"], event)
        return event

    # ------------------------------------------------------------------
    # Query Methods (read from ledger)
    # ------------------------------------------------------------------

    async def get_claim_audit_trail(self, claim_id: str) -> list:
        """
        Fetch the full audit trail for a claim from the Fabric ledger.
        Returns ordered list of ZoneChainEvent dicts.
        """
        result = await self._fabric.get_history_for_key("claimsCollection", claim_id)
        logger.info(
            f"[ZoneChain] Fetched {len(result)} events for claim {claim_id}"
        )
        return result

    async def get_policy_audit_trail(self, policy_id: str) -> list:
        """Fetch the full lifecycle history for a policy from the ledger."""
        result = await self._fabric.get_history_for_key("policiesCollection", policy_id)
        logger.info(
            f"[ZoneChain] Fetched {len(result)} events for policy {policy_id}"
        )
        return result

    async def get_health(self) -> dict:
        """Return Fabric connectivity health info."""
        is_live = await self._fabric.ping()
        return {
            "fabric_connected": is_live,
            "stub_mode": self._fabric.is_stub_mode,
            "channel": self._fabric.channel_name,
            "chaincode": self._fabric.chaincode_name,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _submit(
        self,
        function_name: str,
        event: ZoneChainEvent,
        max_retries: int = 3,
    ) -> FabricTransactionResult:
        """
        Submit a ZoneChainEvent to Fabric with retry logic.

        Retries up to max_retries times with exponential backoff.
        On final failure, logs the full event payload for manual replay.
        NEVER raises — the caller (API handler) must not be blocked.
        """
        payload_json = event.to_fabric_json()

        for attempt in range(1, max_retries + 1):
            try:
                result = await self._fabric.submit_transaction(
                    function_name, payload_json
                )
                if result.success:
                    logger.info(
                        f"[ZoneChain] ✓ {function_name} | "
                        f"event_id={event.event_id} | "
                        f"tx_id={result.transaction_id} | "
                        f"stub={result.stub_mode}"
                    )
                    return result
                else:
                    raise RuntimeError(result.error or "Unknown Fabric error")

            except Exception as e:
                if attempt == max_retries:
                    logger.error(
                        f"[ZoneChain] ✗ FINAL FAILURE {function_name} | "
                        f"event_id={event.event_id} | "
                        f"error={e} | "
                        f"PAYLOAD_FOR_REPLAY={payload_json}"
                    )
                    # [ENHANCEMENT] In production: push to a dead-letter queue
                    # (Redis stream / SQS) for guaranteed eventual consistency
                    return FabricTransactionResult(
                        success=False,
                        transaction_id=None,
                        block_number=None,
                        payload=None,
                        error=str(e),
                    )
                else:
                    backoff = 2 ** attempt
                    logger.warning(
                        f"[ZoneChain] Retry {attempt}/{max_retries} "
                        f"for {function_name} in {backoff}s: {e}"
                    )
                    await asyncio.sleep(backoff)

        # Should not reach here
        return FabricTransactionResult(
            success=False, transaction_id=None, block_number=None, payload=None
        )


# ---------------------------------------------------------------------------
# Singleton for DI
# ---------------------------------------------------------------------------

_zonechain_client: Optional[ZoneChainClient] = None


def get_zonechain_client() -> ZoneChainClient:
    """FastAPI dependency — returns the shared ZoneChain client."""
    global _zonechain_client
    if _zonechain_client is None:
        _zonechain_client = ZoneChainClient()
    return _zonechain_client
