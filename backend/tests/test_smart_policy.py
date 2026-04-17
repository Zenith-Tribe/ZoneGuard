"""Tests for SmartPolicy on-chain payout formula (Innovation 02)."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from blockchain.smart_policy import SmartPolicyEngine
from blockchain.models import PolicyTermsOnChain, SmartPolicyResult


class TestSmartPolicyEngine:
    """SmartPolicyEngine tests — all use simulated (in-memory) Fabric state."""

    @patch("blockchain.smart_policy.get_zonechain_client")
    def _make_engine(self, mock_get_zonechain):
        """Helper: create a SmartPolicyEngine with a mocked ZoneChain client."""
        mock_zonechain = MagicMock()
        mock_zonechain.write_parameter_change = AsyncMock()
        mock_get_zonechain.return_value = mock_zonechain
        return SmartPolicyEngine()

    def _create_terms(self, engine, **overrides):
        """Helper: register default policy terms and return them."""
        defaults = dict(
            rider_id="RIDER-001",
            zone_id="bellandur",
            premium_inr=149.0,
            earnings_baseline_weekly=18200.0,
            coverage_tier="MEDIUM",
            is_forward_locked=False,
            forward_lock_weeks=0,
        )
        defaults.update(overrides)
        return engine.create_policy_terms(**defaults)

    def test_execute_payout_high_confidence(self):
        """HIGH confidence payout: amount = (weekly/7) * 0.55 * min(hours/24, 3)."""
        engine = self._make_engine()
        self._create_terms(engine)

        result = engine.execute_payout(
            rider_id="RIDER-001",
            event_id="EVT-001",
            disruption_hours=24.0,
            composite_score=0.95,
            confidence_tier="HIGH",
            fraud_score=0.1,
        )

        assert isinstance(result, SmartPolicyResult)
        assert result.fraud_gate_passed is True

        # Expected: daily = 18200/7 = 2600, effective_days = min(24/24, 3) = 1.0
        # payout = 2600 * 0.55 * 1.0 = 1430.0
        expected = round((18200.0 / 7.0) * 0.55 * min(24.0 / 24.0, 3.0), 2)
        assert result.payout_amount_inr == expected

    def test_execute_payout_respects_max_days(self):
        """disruption_hours=120 (5 days) is capped at max_consecutive_days=3."""
        engine = self._make_engine()
        self._create_terms(engine)

        result = engine.execute_payout(
            rider_id="RIDER-001",
            event_id="EVT-002",
            disruption_hours=120.0,  # 5 days
            composite_score=0.90,
            confidence_tier="HIGH",
            fraud_score=0.0,
        )

        # effective_days = min(120/24, 3) = min(5.0, 3) = 3.0
        # payout = (18200/7) * 0.55 * 3.0 = 2600 * 0.55 * 3 = 4290.0
        expected = round((18200.0 / 7.0) * 0.55 * 3.0, 2)
        assert result.payout_amount_inr == expected
        assert result.formula_inputs["effective_days"] == 3.0

    def test_execute_payout_forward_lock_discount(self):
        """Forward-locked policy terms record 8% discount."""
        engine = self._make_engine()
        terms = self._create_terms(
            engine,
            is_forward_locked=True,
            forward_lock_weeks=4,
        )

        # Verify the terms have the discount recorded
        assert terms.is_forward_locked is True
        assert terms.forward_lock_discount_pct == 0.08

        # Execute payout — the discount is informational on terms, payout formula is same
        result = engine.execute_payout(
            rider_id="RIDER-001",
            event_id="EVT-003",
            disruption_hours=24.0,
            composite_score=0.90,
            confidence_tier="HIGH",
            fraud_score=0.0,
        )

        # Payout amount uses same formula regardless of forward lock
        expected = round((18200.0 / 7.0) * 0.55 * 1.0, 2)
        assert result.payout_amount_inr == expected
        # But the computation trace records the forward lock info
        assert result.computation_trace["step_5_formula_execution"]["forward_locked"] is True
        assert result.computation_trace["step_5_formula_execution"]["forward_lock_discount_pct"] == 0.08

    def test_execute_payout_fraud_gate_blocks(self):
        """Fraud score above threshold blocks payout — fraud_gate_passed=False, payout=0."""
        engine = self._make_engine()
        self._create_terms(engine)

        result = engine.execute_payout(
            rider_id="RIDER-001",
            event_id="EVT-004",
            disruption_hours=24.0,
            composite_score=0.90,
            confidence_tier="HIGH",
            fraud_score=0.95,  # Above default threshold of 0.85
        )

        assert result.fraud_gate_passed is False
        assert result.fraud_score == 0.95
        assert result.payout_amount_inr == 0.0

    def test_get_on_chain_parameters_default(self):
        """Unknown zone returns default parameters."""
        engine = self._make_engine()

        params = engine.get_on_chain_parameters("unknown-zone-xyz")

        assert params["payout_pct"] == 0.55
        assert params["max_consecutive_days"] == 3
        assert params["fraud_threshold"] == 0.85
        assert params["min_disruption_hours"] == 4
        assert params["operating_window_start"] == 6
        assert params["operating_window_end"] == 22

    @pytest.mark.asyncio
    async def test_update_parameter(self):
        """update_parameter() changes on-chain params for a zone."""
        engine = self._make_engine()

        # Before update — default value
        params_before = engine.get_on_chain_parameters("bellandur")
        assert params_before["payout_pct"] == 0.55

        # Update the parameter
        await engine.update_parameter(
            zone_id="bellandur",
            param_name="payout_pct",
            new_value=0.60,
            changed_by="ADMIN-001",
        )

        # After update — new value returned
        params_after = engine.get_on_chain_parameters("bellandur")
        assert params_after["payout_pct"] == 0.60

        # Other defaults remain unchanged
        assert params_after["max_consecutive_days"] == 3

    def test_create_policy_terms(self):
        """create_policy_terms() returns PolicyTermsOnChain with chain_tx_id populated."""
        engine = self._make_engine()

        terms = engine.create_policy_terms(
            rider_id="RIDER-010",
            zone_id="whitefield",
            premium_inr=199.0,
            earnings_baseline_weekly=21000.0,
            coverage_tier="HIGH",
            is_forward_locked=False,
        )

        assert isinstance(terms, PolicyTermsOnChain)
        assert terms.rider_id == "RIDER-010"
        assert terms.zone_id == "whitefield"
        assert terms.premium_inr == 199.0
        assert terms.earnings_baseline_weekly == 21000.0
        assert terms.risk_tier == "HIGH"
        assert terms.chain_tx_id is not None
        assert terms.chain_tx_id.startswith("FABRIC-SP-")
        assert terms.exclusions_hash is not None
        assert len(terms.exclusions_hash) == 64  # SHA-256 hex digest
