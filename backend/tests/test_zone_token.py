"""Tests for ZONE Token Manager — earn, cooldown, quadratic governance weight."""

import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from governance.zone_token import (
    earn_tokens,
    calculate_governance_weight,
    S4_CHECKIN_COOLDOWN_DAYS,
)
from governance.models import (
    ZoneTokenEvent,
    ZONE_TOKEN_DELTAS,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _mock_balance_record(balance: int = 0, last_s4_checkin=None):
    """Return a mock ZoneTokenBalanceDB record."""
    record = MagicMock()
    record.balance = balance
    record.lifetime_earned = balance
    record.lifetime_burned = 0
    record.last_s4_checkin = last_s4_checkin
    record.last_appeal_resolved = None
    record.referral_count_this_year = 0
    record.referral_year = 2026
    record.updated_at = datetime.now(timezone.utc)
    return record


def _make_async_db():
    """Create a mock AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    return db


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestZoneToken:

    @patch("governance.zone_token.get_or_create_balance", new_callable=AsyncMock)
    async def test_earn_tokens_weekly_coverage(self, mock_get_balance):
        """
        Earning WEEKLY_COVERAGE tokens should increase the rider's balance
        by the configured delta (+10).
        """
        initial_balance = 40
        record = _mock_balance_record(balance=initial_balance)
        mock_get_balance.return_value = record
        db = _make_async_db()

        tx = await earn_tokens(
            rider_id="RIDER-001",
            event_type=ZoneTokenEvent.WEEKLY_COVERAGE,
            db=db,
            reference_id="POL-001",
            notes="Weekly coverage completed",
        )

        expected_delta = ZONE_TOKEN_DELTAS[ZoneTokenEvent.WEEKLY_COVERAGE]
        assert expected_delta == 10

        # Balance should have been updated on the record
        assert record.balance == initial_balance + expected_delta

        # Transaction response should reflect the new balance
        assert tx.delta == expected_delta
        assert tx.balance_after == initial_balance + expected_delta
        assert tx.event_type == ZoneTokenEvent.WEEKLY_COVERAGE

    @patch("governance.zone_token.get_or_create_balance", new_callable=AsyncMock)
    async def test_s4_checkin_cooldown(self, mock_get_balance):
        """
        After an S4 check-in, a second attempt within 7 days should be rejected.
        """
        # First check-in was 3 days ago (within the 7-day cooldown)
        recent_checkin = datetime.now(timezone.utc) - timedelta(days=3)
        record = _mock_balance_record(balance=50, last_s4_checkin=recent_checkin)
        mock_get_balance.return_value = record
        db = _make_async_db()

        with pytest.raises(ValueError, match="S4 check-in cooldown active"):
            await earn_tokens(
                rider_id="RIDER-002",
                event_type=ZoneTokenEvent.S4_CHECKIN,
                db=db,
            )

    def test_governance_weight_quadratic(self):
        """
        Governance weight = sqrt(balance).
        100 tokens -> 10.0, 400 -> 20.0, 0 -> 0.0, 1 -> 1.0.
        """
        assert calculate_governance_weight(100) == round(math.sqrt(100), 4)
        assert calculate_governance_weight(100) == 10.0

        assert calculate_governance_weight(400) == round(math.sqrt(400), 4)
        assert calculate_governance_weight(400) == 20.0

        assert calculate_governance_weight(0) == 0.0
        assert calculate_governance_weight(1) == 1.0

        # Negative balance (shouldn't happen, but function guards with max(0, ...))
        assert calculate_governance_weight(-10) == 0.0

        # Large balance
        assert calculate_governance_weight(1000) == round(math.sqrt(1000), 4)
