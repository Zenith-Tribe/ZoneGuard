"""Tests for ZoneReinsurance Reserve Pool — Innovation 08: staking, waterfall, lock period."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from defi.reinsurance_pool import (
    stake_into_pool,
    withdraw_position,
    absorb_payout_loss,
)
from governance.models import (
    Tranche,
    StakeRequest,
    PoolState,
    TRANCHE_CONFIG,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_pool_state(**overrides) -> PoolState:
    """Return a PoolState with sensible defaults."""
    defaults = dict(
        total_pool_inr=1_000_000.0,
        senior_pool_inr=700_000.0,
        mezzanine_pool_inr=200_000.0,
        junior_pool_inr=100_000.0,
        total_premiums_collected_week=50_000.0,
        total_payouts_week=10_000.0,
        loss_ratio_ltm=20.0,
        pool_utilization_pct=1.0,
        active_positions=10,
        last_yield_distribution=None,
    )
    defaults.update(overrides)
    return PoolState(**defaults)


def _mock_position_db(**overrides):
    """Return a mock ReinsurancePositionDB."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        position_id="RPOS-TEST000001",
        provider_id="PROV-001",
        provider_type="institutional",
        tranche=Tranche.SENIOR.value,
        amount_staked=100_000.0,
        pool_share_pct=12.5,
        expected_annual_yield_pct=10.0,
        is_active=True,
        lock_period_days=90,
        staked_at=now - timedelta(days=30),
        unlock_at=now + timedelta(days=60),
        withdrawn_at=None,
    )
    defaults.update(overrides)
    mock = MagicMock(**defaults)
    return mock


def _make_async_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestReinsurancePool:

    @patch("defi.reinsurance_pool.get_pool_state", new_callable=AsyncMock)
    async def test_stake_into_pool(self, mock_pool_state):
        """
        Staking capital into the Senior tranche should create a position
        with the correct pool share percentage.
        """
        mock_pool_state.return_value = _make_pool_state(senior_pool_inr=700_000.0)
        db = _make_async_db()

        # Mock the position object returned after flush/refresh
        mock_position = MagicMock()
        mock_position.position_id = "RPOS-NEW0001"
        mock_position.provider_id = "PROV-001"
        mock_position.tranche = Tranche.SENIOR.value
        mock_position.amount_staked = 100_000.0
        # pool share = 100_000 / (700_000 + 100_000) * 100 = 12.5
        mock_position.pool_share_pct = 12.5
        config = TRANCHE_CONFIG[Tranche.SENIOR]
        expected_yield = round((config["yield_min_pct"] + config["yield_max_pct"]) / 2.0, 2)
        mock_position.expected_annual_yield_pct = expected_yield
        mock_position.lock_period_days = 90
        now = datetime.now(timezone.utc)
        mock_position.staked_at = now
        mock_position.unlock_at = now + timedelta(days=90)

        # Patch the ReinsurancePositionDB constructor to return our mock
        with patch("defi.reinsurance_pool.ReinsurancePositionDB", return_value=mock_position):
            payload = StakeRequest(
                provider_id="PROV-001",
                tranche=Tranche.SENIOR,
                amount_inr=100_000.0,
                provider_type="institutional",
            )
            response = await stake_into_pool(payload, db)

        assert response.position_id == "RPOS-NEW0001"
        assert response.tranche == Tranche.SENIOR
        assert response.amount_staked == 100_000.0
        # Pool share: 100_000 / 800_000 = 12.5%
        assert response.pool_share_pct == 12.5
        assert response.lock_period_days == 90
        assert response.expected_annual_yield_pct == expected_yield

    @patch("defi.reinsurance_pool.get_pool_state", new_callable=AsyncMock)
    async def test_loss_waterfall_junior_first(self, mock_pool_state):
        """
        Loss waterfall: Junior absorbs first, then Mezzanine, then Senior.
        A loss of 80,000 on a pool with Junior=100,000 should be fully
        absorbed by Junior, leaving Mezzanine and Senior untouched.
        """
        mock_pool_state.return_value = _make_pool_state(
            junior_pool_inr=100_000.0,
            mezzanine_pool_inr=200_000.0,
            senior_pool_inr=700_000.0,
        )
        db = _make_async_db()

        result = await absorb_payout_loss(80_000.0, db)

        assert result["payout_amount"] == 80_000.0
        assert result["absorption"][Tranche.JUNIOR.value] == 80_000.0
        assert result["absorption"][Tranche.MEZZANINE.value] == 0.0
        assert result["absorption"][Tranche.SENIOR.value] == 0.0
        assert result["unfunded_amount"] == 0.0
        assert result["pool_sufficient"] is True

    @patch("defi.reinsurance_pool.get_pool_state", new_callable=AsyncMock)
    async def test_loss_waterfall_spills_to_mezzanine(self, mock_pool_state):
        """
        When loss exceeds Junior pool, remainder spills to Mezzanine.
        Loss=150,000 with Junior=100,000 -> Junior absorbs 100k, Mezz absorbs 50k.
        """
        mock_pool_state.return_value = _make_pool_state(
            junior_pool_inr=100_000.0,
            mezzanine_pool_inr=200_000.0,
            senior_pool_inr=700_000.0,
        )
        db = _make_async_db()

        result = await absorb_payout_loss(150_000.0, db)

        assert result["absorption"][Tranche.JUNIOR.value] == 100_000.0
        assert result["absorption"][Tranche.MEZZANINE.value] == 50_000.0
        assert result["absorption"][Tranche.SENIOR.value] == 0.0
        assert result["unfunded_amount"] == 0.0
        assert result["pool_sufficient"] is True

    async def test_withdraw_before_lock_period(self):
        """
        Attempting withdrawal before the 90-day lock period should raise ValueError.
        """
        db = _make_async_db()

        # Position staked 30 days ago, unlocks in 60 days
        now = datetime.now(timezone.utc)
        position = _mock_position_db(
            staked_at=now - timedelta(days=30),
            unlock_at=now + timedelta(days=60),
            is_active=True,
            provider_id="PROV-001",
        )
        db.get = AsyncMock(return_value=position)

        with pytest.raises(ValueError, match="Lock period not expired"):
            await withdraw_position(
                position_id="RPOS-TEST000001",
                provider_id="PROV-001",
                db=db,
            )

    async def test_withdraw_after_lock_period(self):
        """
        Withdrawal after the lock period should succeed and mark position inactive.
        """
        db = _make_async_db()

        now = datetime.now(timezone.utc)
        position = _mock_position_db(
            staked_at=now - timedelta(days=100),
            unlock_at=now - timedelta(days=10),  # Already unlocked
            is_active=True,
            provider_id="PROV-001",
            amount_staked=100_000.0,
            expected_annual_yield_pct=10.0,
        )
        db.get = AsyncMock(return_value=position)

        result = await withdraw_position(
            position_id="RPOS-TEST000001",
            provider_id="PROV-001",
            db=db,
        )

        assert result["position_id"] == "RPOS-TEST000001"
        assert result["amount_staked"] == 100_000.0
        assert result["yield_earned"] > 0
        assert result["total_return"] > result["amount_staked"]
        assert position.is_active is False
