"""Tests for TemporalSig Archive — Polygon L2 signal anchoring (Innovation 10)."""

import pytest
import uuid
from datetime import datetime, timezone

from blockchain.models import ConfidenceTier, SignalBatchPayload, SignalReading
from blockchain.temporalsig import TemporalSigClient


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_signal_batch(batch_id: str | None = None, zone_id: str = "BLR-CENTRAL") -> SignalBatchPayload:
    """Construct a valid SignalBatchPayload with 4 signal readings."""
    return SignalBatchPayload(
        batch_id=batch_id or str(uuid.uuid4()),
        zone_id=zone_id,
        polled_at=datetime.now(timezone.utc),
        signals=[
            SignalReading(
                signal_type="ENVIRONMENTAL",
                raw_value=75.0,
                normalized_score=0.85,
                source_api="openweathermap",
                zone_id=zone_id,
            ),
            SignalReading(
                signal_type="MOBILITY",
                raw_value=22.0,
                normalized_score=0.78,
                source_api="osrm",
                zone_id=zone_id,
            ),
            SignalReading(
                signal_type="ECONOMIC",
                raw_value=28.0,
                normalized_score=0.72,
                source_api="amazon_flex_proxy",
                zone_id=zone_id,
            ),
            SignalReading(
                signal_type="CROWD",
                raw_value=55.0,
                normalized_score=0.65,
                source_api="whatsapp_checkins",
                zone_id=zone_id,
            ),
        ],
        composite_score=0.75,
        confidence_tier=ConfidenceTier.HIGH,
        scheduler_run_id="test-scheduler-run-001",
    )


@pytest.fixture
def client():
    """Fresh TemporalSigClient — will be in stub mode without web3 / private key."""
    return TemporalSigClient()


# ─── Test 1: anchor_signal_batch in stub mode ────────────────────────────────

class TestAnchorSignalBatchStubMode:

    @pytest.mark.asyncio
    async def test_anchor_signal_batch_stub_mode(self, client):
        """
        Create TemporalSigClient (stub mode without web3), call anchor_signal_batch,
        verify TemporalSigAnchor returned with status='confirmed' and polygon_tx_hash set.
        """
        batch = _make_signal_batch()
        anchor = await client.anchor_signal_batch(batch)

        assert anchor.status == "confirmed"
        assert anchor.polygon_tx_hash is not None
        assert anchor.polygon_tx_hash.startswith("0xstub")
        assert anchor.batch_id == batch.batch_id
        assert anchor.zone_id == batch.zone_id
        assert anchor.keccak256_hash == batch.keccak256_hash
        assert anchor.polygon_block_number is not None
        assert anchor.polygon_block_timestamp is not None
        assert anchor.confirmed_at is not None
        assert anchor.gas_used is not None
        assert anchor.estimated_cost_usd is not None


# ─── Test 2: verify_anchor hash match ────────────────────────────────────────

class TestVerifyAnchorHashMatch:

    @pytest.mark.asyncio
    async def test_verify_anchor_hash_match(self, client):
        """
        Anchor a batch, then verify the same batch hash matches.
        In stub mode, verify_anchor returns a stub verification message
        but the local hash should be correctly populated.
        """
        batch = _make_signal_batch()
        anchor = await client.anchor_signal_batch(batch)

        result = await client.verify_anchor(batch, polygon_tx_hash=anchor.polygon_tx_hash)

        assert result["batch_id"] == batch.batch_id
        assert result["local_hash"] == batch.keccak256_hash
        assert result["stub_mode"] is True
        # In stub mode the on-chain verification cannot happen,
        # but the local hash is properly computed
        assert result["local_hash"].startswith("0x")


# ─── Test 3: get_anchor_for_event cache hit ──────────────────────────────────

class TestGetAnchorForEventCacheHit:

    @pytest.mark.asyncio
    async def test_get_anchor_for_event_cache_hit(self, client):
        """
        Anchor a batch, then call get_anchor_for_event with the same batch_id.
        Verify the cached anchor is returned.
        """
        batch = _make_signal_batch()
        original_anchor = await client.anchor_signal_batch(batch)

        cached_anchor = await client.get_anchor_for_event(batch_id=batch.batch_id)

        assert cached_anchor is not None
        assert cached_anchor.anchor_id == original_anchor.anchor_id
        assert cached_anchor.batch_id == batch.batch_id
        assert cached_anchor.keccak256_hash == batch.keccak256_hash
        assert cached_anchor.status == "confirmed"
        assert cached_anchor.polygon_tx_hash == original_anchor.polygon_tx_hash


# ─── Test 4: get_anchor_for_event cache miss ─────────────────────────────────

class TestGetAnchorForEventCacheMiss:

    @pytest.mark.asyncio
    async def test_get_anchor_for_event_cache_miss(self, client):
        """
        Call get_anchor_for_event with an unknown batch_id.
        Verify None is returned.
        """
        result = await client.get_anchor_for_event(batch_id="nonexistent-batch-id-12345")

        assert result is None
