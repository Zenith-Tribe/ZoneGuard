"""Tests for SoulboundPolicy NFT — Innovation 07: minting, idempotency, CCS."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, date

from governance.soulbound_nft import (
    mint_weekly_nft,
    compute_coverage_continuity_score,
    _compute_consecutive_streak,
    CCS_THRESHOLDS,
    CREDIT_DELEGATION_MIN_CONSECUTIVE,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _mock_nft_db_row(**overrides):
    """Return a mock SoulboundNFTDB row."""
    defaults = dict(
        token_id="SNFT-TEST00000001",
        rider_zk_hash="0xabcdef1234567890",
        policy_id="POL-001",
        week_number=15,
        year=2026,
        coverage_tier="standard",
        zone_id="bellandur",
        premium_paid=150.0,
        max_payout=1430.0,
        was_disrupted=False,
        payout_received=0.0,
        ipfs_metadata_cid="QmTEST123",
        chain_tx_hash="FABRIC-SNFT-TEST123",
        minted_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    mock = MagicMock(**defaults)
    return mock


def _make_async_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


def _make_consecutive_nfts(count: int, start_year: int = 2026, start_week: int = 16):
    """
    Build a list of mock NFTs representing consecutive weeks,
    sorted by (year DESC, week DESC) as the code expects.
    """
    nfts = []
    for i in range(count):
        week = start_week - i
        year = start_year
        # Handle year boundary rollover
        while week <= 0:
            week += 52
            year -= 1
        nft = MagicMock()
        nft.year = year
        nft.week_number = week
        nft.premium_paid = 150.0
        nft.payout_received = 0.0
        nft.was_disrupted = False
        nfts.append(nft)
    return nfts


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSoulboundNFT:

    @patch("governance.soulbound_nft._resolve_zk_hash", new_callable=AsyncMock)
    async def test_mint_idempotent(self, mock_resolve_zk):
        """
        Minting an NFT for the same rider+policy+week twice should return
        the existing NFT rather than creating a duplicate.
        """
        mock_resolve_zk.return_value = ("0xfallbackhash123456", False)

        existing_nft = _mock_nft_db_row()
        db = _make_async_db()

        # First call to db.execute (idempotency check) returns existing NFT
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing_nft
        db.execute.return_value = result_mock

        response = await mint_weekly_nft(
            rider_id="RIDER-001",
            policy_id="POL-001",
            zone_id="bellandur",
            coverage_tier="standard",
            premium_paid=150.0,
            max_payout=1430.0,
            was_disrupted=False,
            payout_received=0.0,
            db=db,
            week_number=15,
            year=2026,
        )

        # Should return the existing NFT's token_id, not create a new one
        assert response.token_id == existing_nft.token_id
        # db.add should NOT have been called (no new record)
        db.add.assert_not_called()

    def test_coverage_continuity_score_consecutive(self):
        """
        _compute_consecutive_streak correctly counts consecutive weekly NFTs.
        """
        # 5 consecutive weeks starting from week 16 going backward
        nfts = _make_consecutive_nfts(5, start_year=2026, start_week=16)
        streak = _compute_consecutive_streak(nfts)
        assert streak == 5

    def test_coverage_continuity_score_with_gap(self):
        """
        A gap in the weekly NFTs should break the streak.
        """
        nfts = _make_consecutive_nfts(3, start_year=2026, start_week=16)
        # Add a 4th NFT with a gap (week 12 instead of 13)
        gap_nft = MagicMock()
        gap_nft.year = 2026
        gap_nft.week_number = 11  # Gap: 13 -> 11 (skips week 12)
        gap_nft.premium_paid = 150.0
        gap_nft.payout_received = 0.0
        nfts.append(gap_nft)

        streak = _compute_consecutive_streak(nfts)
        assert streak == 3  # Only the first 3 consecutive weeks count

    def test_ccs_elite_threshold(self):
        """52 consecutive weeks should produce the 'Elite' label."""
        nfts = _make_consecutive_nfts(52, start_year=2026, start_week=52)
        streak = _compute_consecutive_streak(nfts)
        assert streak == 52

        # Verify against the threshold constant
        assert streak >= CCS_THRESHOLDS["Elite"]
        assert streak >= CREDIT_DELEGATION_MIN_CONSECUTIVE

    @patch("governance.soulbound_nft._resolve_zk_hash", new_callable=AsyncMock)
    async def test_compute_ccs_with_nfts(self, mock_resolve_zk):
        """
        compute_coverage_continuity_score with a set of consecutive NFTs
        should return a valid CCS with the correct label.
        """
        mock_resolve_zk.return_value = ("0xfallbackhash123456", False)

        # 52 consecutive NFTs -> Elite
        nfts = _make_consecutive_nfts(52, start_year=2026, start_week=52)

        db = _make_async_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = nfts
        db.execute.return_value = result_mock

        ccs = await compute_coverage_continuity_score("RIDER-001", db)

        assert ccs.consecutive_weeks == 52
        assert ccs.score_label == "Elite"
        assert ccs.eligible_for_credit_delegation is True
        assert ccs.eligible_for_microloan is True
        assert ccs.total_nfts == 52
