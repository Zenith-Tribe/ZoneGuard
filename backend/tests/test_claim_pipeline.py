"""End-to-end integration tests for the claim pipeline."""

import pytest
from unittest.mock import AsyncMock, patch
from services.claim_pipeline import process_disruption_event


def _weather(rainfall=80, aqi=350, temp=38, ndma=False):
    return {"rainfall_mm_hr": rainfall, "aqi": aqi, "temperature_c": temp, "ndma_alert": ndma}


def _mobility(index=10, baseline=100):
    return {"mobility_index": index, "baseline": baseline}


def _orders(volume=20, baseline=100):
    return {"order_volume": volume, "baseline": baseline}


def _checkins(inactive=8, total=10):
    return {"inactive_riders": inactive, "total_riders": total, "inactivity_pct": (inactive / total) * 100}


def _rider(**overrides):
    defaults = {
        "id": "RIDER-001",
        "policy_id": "POL-001",
        "weekly_earnings_baseline": 18200,
        "tenure_weeks": 20,
        "recent_claims_7d": 0,
        "distance_km": 1.5,
        "days_since_policy_start": 30,
        "upi_id": "rider001@upi",
        "policy": {},
    }
    defaults.update(overrides)
    return defaults


ZONE_ID = "bellandur"
ZONE_DATA = {"name": "Bellandur", "id": "bellandur"}

MOCK_PAYOUT = {
    "upi_ref": "ZG-2026-TEST1234",
    "amount": 1430,
    "rider_id": "RIDER-001",
    "upi_id": "rider001@upi",
    "status": "settled",
    "gateway": "simulated_razorpay",
    "processed_at": "2026-04-16T12:00:00+00:00",
    "gateway_response": {"transaction_id": "ZG-2026-TEST1234", "status_code": 200, "message": "Payment successful"},
}

MOCK_AUDIT = {"report": "Test audit report", "model_used": "gemini-1.5-flash"}


@pytest.mark.asyncio
class TestClaimPipeline:
    """Full pipeline tests with mocked external dependencies."""

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_high_confidence_auto_payout(self, mock_audit, mock_payout):
        """4/4 signals → HIGH → auto-approved + auto-payout."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        assert result["disruption_created"] is True
        assert result["fusion"]["confidence"] == "HIGH"
        assert result["fusion"]["signals_fired"] == 4
        assert len(result["claims"]) == 1

        claim = result["claims"][0]
        assert claim["status"] == "approved"
        assert claim["confidence"] == "HIGH"
        assert "payout" in claim
        mock_payout.assert_called_once()
        mock_audit.assert_not_called()  # No audit for HIGH

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_medium_confidence_pending_with_audit(self, mock_audit, mock_payout):
        """3/4 signals → MEDIUM → SmartClaim Autopilot adjudicates (or falls
        back to audit report if autopilot unavailable)."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=2, total=10),  # S4 NOT breached
            riders_with_policies=[_rider()],
        )

        assert result["fusion"]["confidence"] == "MEDIUM"
        assert result["fusion"]["signals_fired"] == 3

        claim = result["claims"][0]
        # SmartClaim Autopilot may approve clean claims, or fall back to audit
        assert claim["status"] in ("approved", "pending_review")
        assert "autopilot_decision" in claim or "audit_report" in claim

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_low_confidence_pending_review(self, mock_audit, mock_payout):
        """2/4 signals → LOW → pending_review, no audit."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=50),  # S2 NOT breached (50% of baseline)
            order_data=_orders(volume=50),       # S3 NOT breached
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        assert result["fusion"]["confidence"] == "LOW"
        assert result["fusion"]["signals_fired"] == 2

        claim = result["claims"][0]
        assert claim["status"] == "pending_review"
        mock_payout.assert_not_called()
        mock_audit.assert_not_called()

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_noise_no_disruption(self, mock_audit, mock_payout):
        """0-1 signals → NOISE → no disruption event created."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=10, aqi=50, temp=30),
            mobility_data=_mobility(index=90),
            order_data=_orders(volume=90),
            checkin_data=_checkins(inactive=1, total=10),
            riders_with_policies=[_rider()],
        )

        assert result["disruption_created"] is False
        assert result["fusion"]["confidence"] == "NOISE"
        assert len(result["claims"]) == 0
        mock_payout.assert_not_called()
        mock_audit.assert_not_called()

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_exclusion_rejects_claim(self, mock_audit, mock_payout):
        """Claim rejected when max disruption days exceeded."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider(consecutive_disruption_days=4)],
        )

        claim = result["claims"][0]
        assert claim["status"] == "rejected"
        assert claim["exclusion_check"]["passed"] is False
        triggered_ids = [e["id"] for e in claim["exclusion_check"]["exclusions_triggered"]]
        assert "MAX_DAYS_EXCEEDED" in triggered_ids
        mock_payout.assert_not_called()

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_fraud_flags_propagated(self, mock_audit, mock_payout):
        """Suspicious rider params produce elevated fraud score with anomaly signals."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider(
                claim_velocity_7d=4,
                tenure_weeks=1,
                days_since_policy_start=0,
            )],
        )

        claim = result["claims"][0]
        assert claim["fraud_score"] > 0
        assert len(claim["fraud_details"]["anomaly_signals"]) > 0
        assert "features" in claim["fraud_details"]

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_payout_amount_calculation(self, mock_audit, mock_payout):
        """Payout = 55% of (weekly_earnings / 7)."""
        weekly = 18200  # daily avg = 2600, 55% = 1430
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider(weekly_earnings_baseline=weekly)],
        )

        claim = result["claims"][0]
        expected = round((weekly / 7) * 0.55)
        assert claim["recommended_payout"] == expected

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_multiple_riders_processed(self, mock_audit, mock_payout):
        """Multiple riders each get their own claim."""
        riders = [
            _rider(id="RIDER-001", weekly_earnings_baseline=14000),
            _rider(id="RIDER-002", weekly_earnings_baseline=21000),
            _rider(id="RIDER-003", weekly_earnings_baseline=7000),
        ]
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=riders,
        )

        assert result["claims_count"] == 3
        assert len(result["claims"]) == 3
        rider_ids = {c["rider_id"] for c in result["claims"]}
        assert rider_ids == {"RIDER-001", "RIDER-002", "RIDER-003"}
        # Each claim has unique ID
        claim_ids = [c["id"] for c in result["claims"]]
        assert len(set(claim_ids)) == 3

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_zone_twin_included(self, mock_audit, mock_payout):
        """Pipeline result includes zone_twin counterfactual data."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        assert "zone_twin" in result
        zt = result["zone_twin"]
        assert "expected_inactivity" in zt
        ei = zt["expected_inactivity"]
        assert "p10" in ei
        assert "p50" in ei
        assert "p90" in ei
        assert ei["p10"] <= ei["p50"] <= ei["p90"]

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_ndma_override_triggers_high(self, mock_audit, mock_payout):
        """NDMA alert → S1 forced breach. With other signals → HIGH."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=10, aqi=50, temp=30, ndma=True),  # Normal weather but NDMA
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        assert result["fusion"]["signals_fired"] == 4
        assert result["fusion"]["confidence"] == "HIGH"

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_event_id_format(self, mock_audit, mock_payout):
        """Disruption event ID follows DE-XXXXXXXX format."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        assert result["event_id"].startswith("DE-")
        assert len(result["event_id"]) == 11  # DE- + 8 hex chars

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_empty_riders_list(self, mock_audit, mock_payout):
        """No riders → disruption created but zero claims."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[],
        )

        assert result["disruption_created"] is True
        assert result["claims_count"] == 0
        assert len(result["claims"]) == 0

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_claim_contains_required_fields(self, mock_audit, mock_payout):
        """Each claim has all required fields."""
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[_rider()],
        )

        claim = result["claims"][0]
        required_fields = [
            "id", "rider_id", "policy_id", "zone_id",
            "disruption_event_id", "status", "confidence",
            "recommended_payout", "exclusion_check",
            "fraud_score", "fraud_details", "zone_twin",
        ]
        for field in required_fields:
            assert field in claim, f"Missing field: {field}"

    @patch("services.claim_pipeline.process_payout", new_callable=AsyncMock, return_value=MOCK_PAYOUT)
    @patch("services.claim_pipeline.generate_audit_report", new_callable=AsyncMock, return_value=MOCK_AUDIT)
    async def test_default_weekly_earnings(self, mock_audit, mock_payout):
        """Default weekly earnings = 2000 when not provided."""
        rider = _rider()
        del rider["weekly_earnings_baseline"]
        result = await process_disruption_event(
            zone_id=ZONE_ID,
            zone_data=ZONE_DATA,
            weather_data=_weather(rainfall=80, aqi=350),
            mobility_data=_mobility(index=10),
            order_data=_orders(volume=20),
            checkin_data=_checkins(inactive=8, total=10),
            riders_with_policies=[rider],
        )

        claim = result["claims"][0]
        expected = round((2000 / 7) * 0.55)
        assert claim["recommended_payout"] == expected
