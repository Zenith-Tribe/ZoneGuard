"""Tests for ZoneChain ledger operations (Innovation 01)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from blockchain.zonechain import ZoneChainClient
from blockchain.fabric_client import FabricTransactionResult
from blockchain.models import ChainEventType, ConfidenceTier, ZoneChainEvent


def _stub_success_result():
    """Return a successful FabricTransactionResult for mocking."""
    return FabricTransactionResult(
        success=True,
        transaction_id="stub-abc123",
        block_number=42,
        payload=b"{}",
        stub_mode=True,
    )


def _stub_failure_result(error="Fabric peer unavailable"):
    """Return a failed FabricTransactionResult for mocking."""
    return FabricTransactionResult(
        success=False,
        transaction_id=None,
        block_number=None,
        payload=None,
        error=error,
    )


@pytest.mark.asyncio
class TestZoneChain:
    """ZoneChain write/query operations with mocked Fabric client."""

    async def test_write_claim_event_creates_envelope(self):
        """write_claim_event() returns a ZoneChainEvent with correct event_type and claim_payload."""
        mock_fabric = MagicMock()
        mock_fabric.submit_transaction = AsyncMock(return_value=_stub_success_result())

        client = ZoneChainClient(fabric_client=mock_fabric)

        event = await client.write_claim_event(
            claim_id="CLM-001",
            rider_id="RIDER-001",
            policy_id="POL-001",
            zone_id="bellandur",
            event_type=ChainEventType.CLAIM_CREATED,
            confidence_tier=ConfidenceTier.HIGH,
            composite_score=0.92,
            payout_amount_inr=1430.0,
        )

        assert isinstance(event, ZoneChainEvent)
        assert event.event_type == ChainEventType.CLAIM_CREATED
        assert event.claim_payload is not None
        assert event.claim_payload.claim_id == "CLM-001"
        assert event.claim_payload.rider_id == "RIDER-001"
        assert event.claim_payload.policy_id == "POL-001"
        assert event.claim_payload.zone_id == "bellandur"
        assert event.claim_payload.confidence_tier == ConfidenceTier.HIGH
        assert event.claim_payload.composite_score == 0.92
        assert event.claim_payload.payout_amount_inr == 1430.0
        mock_fabric.submit_transaction.assert_called_once()

    async def test_write_policy_creation(self):
        """write_policy_creation() returns event with policy_payload containing correct coverage_tier and premium."""
        mock_fabric = MagicMock()
        mock_fabric.submit_transaction = AsyncMock(return_value=_stub_success_result())

        client = ZoneChainClient(fabric_client=mock_fabric)
        now = datetime.now(timezone.utc)

        event = await client.write_policy_creation(
            policy_id="POL-042",
            rider_id="RIDER-007",
            zone_id="koramangala",
            event_type=ChainEventType.POLICY_CREATED,
            coverage_tier="MEDIUM",
            weekly_premium_inr=149.0,
            coverage_start=now,
            coverage_end=now,
            is_forward_locked=True,
            forward_lock_weeks=4,
        )

        assert isinstance(event, ZoneChainEvent)
        assert event.event_type == ChainEventType.POLICY_CREATED
        assert event.policy_payload is not None
        assert event.policy_payload.coverage_tier == "MEDIUM"
        assert event.policy_payload.weekly_premium_inr == 149.0
        assert event.policy_payload.is_forward_locked is True
        assert event.policy_payload.forward_lock_weeks == 4
        assert event.policy_payload.rider_id == "RIDER-007"
        mock_fabric.submit_transaction.assert_called_once()

    async def test_write_payout_trigger_with_upi(self):
        """write_payout_trigger() returns event with payout_payload containing correct amount and UPI ref."""
        mock_fabric = MagicMock()
        mock_fabric.submit_transaction = AsyncMock(return_value=_stub_success_result())

        client = ZoneChainClient(fabric_client=mock_fabric)
        now = datetime.now(timezone.utc)

        event = await client.write_payout_trigger(
            payout_id="PAY-001",
            claim_id="CLM-001",
            rider_id="RIDER-001",
            policy_id="POL-001",
            amount_inr=1430.0,
            triggered_at=now,
            upi_reference="ZG-2026-UPI789",
        )

        assert isinstance(event, ZoneChainEvent)
        assert event.event_type == ChainEventType.PAYOUT_TRIGGERED
        assert event.payout_payload is not None
        assert event.payout_payload.amount_inr == 1430.0
        assert event.payout_payload.upi_reference == "ZG-2026-UPI789"
        assert event.payout_payload.payout_id == "PAY-001"
        assert event.payout_payload.claim_id == "CLM-001"
        mock_fabric.submit_transaction.assert_called_once()

    @patch("blockchain.zonechain.asyncio.sleep", new_callable=AsyncMock)
    async def test_write_claim_event_retry_on_failure(self, mock_sleep):
        """submit_transaction fails first 2 times then succeeds — verify 3 attempts made."""
        mock_fabric = MagicMock()
        mock_fabric.submit_transaction = AsyncMock(
            side_effect=[
                _stub_failure_result("timeout"),
                _stub_failure_result("timeout"),
                _stub_success_result(),
            ]
        )

        client = ZoneChainClient(fabric_client=mock_fabric)

        event = await client.write_claim_event(
            claim_id="CLM-RETRY",
            rider_id="RIDER-001",
            policy_id="POL-001",
            zone_id="bellandur",
            event_type=ChainEventType.CLAIM_CREATED,
            confidence_tier=ConfidenceTier.HIGH,
            composite_score=0.90,
        )

        assert isinstance(event, ZoneChainEvent)
        assert mock_fabric.submit_transaction.call_count == 3

    @patch("blockchain.zonechain.asyncio.sleep", new_callable=AsyncMock)
    async def test_write_claim_event_final_failure(self, mock_sleep):
        """All 3 submit_transaction calls fail — returns FabricTransactionResult(success=False)."""
        mock_fabric = MagicMock()
        mock_fabric.submit_transaction = AsyncMock(
            side_effect=[
                _stub_failure_result("error1"),
                _stub_failure_result("error2"),
                _stub_failure_result("error3"),
            ]
        )

        client = ZoneChainClient(fabric_client=mock_fabric)

        # write_claim_event always returns a ZoneChainEvent (it never raises),
        # but internally _submit returns a failed FabricTransactionResult.
        # We verify the failure by checking that submit_transaction was called 3 times.
        event = await client.write_claim_event(
            claim_id="CLM-FAIL",
            rider_id="RIDER-001",
            policy_id="POL-001",
            zone_id="bellandur",
            event_type=ChainEventType.CLAIM_CREATED,
            confidence_tier=ConfidenceTier.LOW,
            composite_score=0.40,
        )

        assert isinstance(event, ZoneChainEvent)
        assert mock_fabric.submit_transaction.call_count == 3

    async def test_get_claim_audit_trail_empty(self):
        """get_claim_audit_trail returns empty list when no events exist."""
        mock_fabric = MagicMock()
        mock_fabric.get_history_for_key = AsyncMock(return_value=[])

        client = ZoneChainClient(fabric_client=mock_fabric)
        trail = await client.get_claim_audit_trail("CLM-NONEXIST")

        assert trail == []
        mock_fabric.get_history_for_key.assert_called_once_with(
            "claimsCollection", "CLM-NONEXIST"
        )
