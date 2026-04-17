"""Tests for FedShield v3 GNN-based fraud ring detection.

Uses the FraudRingDetector which falls back to a NumPy heuristic when
PyTorch Geometric is not installed — tests are designed to work with
either backend.
"""

from datetime import datetime, timedelta

import pytest

from ml.fedshield_v3.gnn_fraud import ClaimEvent, FraudRingDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    rider_id: str,
    zone_id: str,
    claim_hour: int,
    s1_value: float,
    timestamp: datetime,
    **overrides,
) -> ClaimEvent:
    """Create a ClaimEvent with sensible defaults for non-critical fields."""
    defaults = {
        "rider_id": rider_id,
        "zone_id": zone_id,
        "claim_hour": claim_hour,
        "tenure_weeks": 20,
        "zone_inactivity_pct": 50.0,
        "claim_velocity_7d": 1,
        "zone_claim_rate_deviation": 1.0,
        "distance_from_centroid_km": 2.0,
        "s1_value": s1_value,
        "days_since_policy_start": 60,
        "timestamp": timestamp,
    }
    defaults.update(overrides)
    return ClaimEvent(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFraudRingDetection:

    def test_fraud_ring_detection(self):
        """Dense cluster of claim events in the same zone, same time window,
        and similar s1 values should yield a clustering coefficient > 0.5
        (ring alert)."""
        detector = FraudRingDetector()
        now = datetime.utcnow()
        zone = "bellandur"

        # 5 riders file claims within a tight 30-minute window,
        # all in the same zone with nearly identical s1 values and claim hour.
        for i in range(5):
            event = _make_event(
                rider_id=f"R-{100 + i}",
                zone_id=zone,
                claim_hour=14,
                s1_value=72.0 + i * 0.5,  # within S1_TOL of 10
                timestamp=now - timedelta(minutes=i * 5),  # within 2-hour TAU
            )
            detector.register_claim(event)

        cc = detector.get_clustering_coefficient(zone)
        summary = detector.get_zone_summary(zone)

        assert cc > 0.5, (
            f"Expected clustering coefficient > 0.5 for a dense fraud ring, got {cc}"
        )
        assert summary["ring_alert"] is True
        assert summary["claims_in_window"] == 5

    def test_isolated_claims_no_ring(self):
        """Unrelated claims spread across different time windows and varying
        s1 values should NOT trigger a ring alert (cc <= 0.5)."""
        detector = FraudRingDetector()
        now = datetime.utcnow()
        zone = "whitefield"

        # 4 riders file claims far apart in time within the 2-hour total
        # window, with widely varying s1 values and claim hours so they
        # do not form edges in the adjacency graph.
        events = [
            _make_event("R-200", zone, claim_hour=6, s1_value=20.0,
                        timestamp=now - timedelta(minutes=0)),
            _make_event("R-201", zone, claim_hour=14, s1_value=80.0,
                        timestamp=now - timedelta(minutes=30)),
            _make_event("R-202", zone, claim_hour=21, s1_value=45.0,
                        timestamp=now - timedelta(minutes=60)),
            _make_event("R-203", zone, claim_hour=3, s1_value=10.0,
                        timestamp=now - timedelta(minutes=90)),
        ]

        for e in events:
            detector.register_claim(e)

        cc = detector.get_clustering_coefficient(zone)
        summary = detector.get_zone_summary(zone)

        assert cc <= 0.5, (
            f"Expected clustering coefficient <= 0.5 for isolated claims, got {cc}"
        )
        assert summary["ring_alert"] is False
