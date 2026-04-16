"""Tests for temporal clustering — Poisson deviation and collusion ring detection."""

import random
from datetime import datetime, timedelta

from ml.temporal_clustering import analyze_temporal_clustering, detect_collusion_rings


class TestAnalyzeTemporalClustering:
    def test_poisson_distributed_not_suspicious(self):
        """Evenly spread timestamps (one every 5-10 min with jitter) should look normal."""
        base = datetime(2026, 4, 15, 8, 0, 0)
        random.seed(42)
        timestamps = [
            base + timedelta(minutes=i * 7 + random.uniform(-2, 2))
            for i in range(24)
        ]
        result = analyze_temporal_clustering(timestamps, zone_id="zone-1")
        assert result["is_suspicious"] is False
        assert result["clustering_coefficient"] < 0.3
        assert result["recommendation"] == "normal"

    def test_tightly_clustered_suspicious(self):
        """10 claims within 2 minutes should be flagged."""
        base = datetime(2026, 4, 15, 14, 0, 0)
        timestamps = [base + timedelta(seconds=i * 10) for i in range(10)]
        result = analyze_temporal_clustering(timestamps, zone_id="zone-2")
        assert result["is_suspicious"] is True
        assert result["clustering_coefficient"] > 0.5
        assert result["recommendation"] == "investigate"

    def test_mixed_pattern_detects_spike(self):
        """20 spread-out + 8 in the same 5-min window should detect a spike cluster."""
        base = datetime(2026, 4, 15, 8, 0, 0)
        random.seed(99)
        spread = [base + timedelta(minutes=i * 10 + random.uniform(0, 3)) for i in range(20)]
        spike_start = base + timedelta(hours=4)
        spike = [spike_start + timedelta(seconds=i * 20) for i in range(8)]
        timestamps = spread + spike

        result = analyze_temporal_clustering(timestamps, zone_id="zone-3")
        assert len(result["detected_clusters"]) >= 1
        # The spike cluster should contain at least 8 claims
        max_cluster = max(result["detected_clusters"], key=lambda c: c["claim_count"])
        assert max_cluster["claim_count"] >= 8

    def test_empty_input_safe_defaults(self):
        """Empty list should return safe defaults."""
        result = analyze_temporal_clustering([], zone_id="zone-empty")
        assert result["is_suspicious"] is False
        assert result["clustering_coefficient"] == 0.0
        assert result["total_claims"] == 0
        assert result["detected_clusters"] == []
        assert result["recommendation"] == "normal"

    def test_single_claim_safe(self):
        """Single timestamp should not be suspicious and have no clusters."""
        ts = [datetime(2026, 4, 15, 12, 0, 0)]
        result = analyze_temporal_clustering(ts, zone_id="zone-single")
        assert result["is_suspicious"] is False
        assert result["total_claims"] == 1
        assert result["detected_clusters"] == []
        assert result["clustering_coefficient"] == 0.0

    def test_all_same_timestamp(self):
        """10 identical timestamps should be suspicious with high clustering."""
        ts = [datetime(2026, 4, 15, 12, 0, 0)] * 10
        result = analyze_temporal_clustering(ts, zone_id="zone-same")
        assert result["is_suspicious"] is True
        assert result["clustering_coefficient"] > 0.5
        assert result["recommendation"] == "investigate"

    def test_recommendation_levels(self):
        """Verify that different patterns produce normal, monitor, and investigate."""
        base = datetime(2026, 4, 15, 8, 0, 0)

        # Normal: well spread
        random.seed(7)
        normal_ts = [base + timedelta(minutes=i * 8 + random.uniform(-1, 1)) for i in range(20)]
        r_normal = analyze_temporal_clustering(normal_ts, zone_id="zone-n")
        assert r_normal["recommendation"] == "normal"

        # Investigate: extreme cluster
        cluster_ts = [base + timedelta(seconds=i * 5) for i in range(15)]
        r_invest = analyze_temporal_clustering(cluster_ts, zone_id="zone-i")
        assert r_invest["recommendation"] == "investigate"

    def test_poisson_analysis_fields(self):
        """Returned dict should contain all expected poisson_analysis keys."""
        ts = [datetime(2026, 4, 15, 10, 0, 0), datetime(2026, 4, 15, 10, 30, 0)]
        result = analyze_temporal_clustering(ts, zone_id="zone-fields")
        pa = result["poisson_analysis"]
        assert "expected_rate" in pa
        assert "observed_max_rate" in pa
        assert "chi_squared_stat" in pa
        assert "p_value" in pa
        assert 0.0 <= pa["p_value"] <= 1.0


class TestDetectCollusionRings:
    def test_collusion_ring_detection(self):
        """3 riders with co-occurring timestamps twice should be detected as a ring."""
        base = datetime(2026, 4, 15, 10, 0, 0)
        claims = [
            # Event 1: all three riders claim within 5 minutes
            {"rider_id": "R1", "timestamp": base, "zone_id": "Z1"},
            {"rider_id": "R2", "timestamp": base + timedelta(minutes=2), "zone_id": "Z1"},
            {"rider_id": "R3", "timestamp": base + timedelta(minutes=4), "zone_id": "Z1"},
            # Event 2: same three riders claim again within 5 minutes
            {"rider_id": "R1", "timestamp": base + timedelta(hours=3), "zone_id": "Z1"},
            {"rider_id": "R2", "timestamp": base + timedelta(hours=3, minutes=1), "zone_id": "Z1"},
            {"rider_id": "R3", "timestamp": base + timedelta(hours=3, minutes=3), "zone_id": "Z1"},
        ]
        result = detect_collusion_rings(claims, time_window_minutes=10, min_co_occurrences=2)
        assert result["rings_detected"] >= 1
        ring_rider_ids = result["suspected_rings"][0]["rider_ids"]
        assert "R1" in ring_rider_ids
        assert "R2" in ring_rider_ids
        assert "R3" in ring_rider_ids
        assert result["suspected_rings"][0]["co_occurrence_count"] >= 2

    def test_no_collusion_ring(self):
        """5 riders with completely independent timestamps should produce no rings."""
        claims = [
            {"rider_id": "A", "timestamp": datetime(2026, 4, 10, 8, 0), "zone_id": "Z1"},
            {"rider_id": "B", "timestamp": datetime(2026, 4, 11, 14, 0), "zone_id": "Z2"},
            {"rider_id": "C", "timestamp": datetime(2026, 4, 12, 9, 30), "zone_id": "Z3"},
            {"rider_id": "D", "timestamp": datetime(2026, 4, 13, 16, 0), "zone_id": "Z1"},
            {"rider_id": "E", "timestamp": datetime(2026, 4, 14, 11, 0), "zone_id": "Z2"},
        ]
        result = detect_collusion_rings(claims, time_window_minutes=10, min_co_occurrences=2)
        assert result["rings_detected"] == 0
        assert result["suspected_rings"] == []
        assert result["total_riders_analyzed"] == 5

    def test_empty_input(self):
        """Empty claims list should return safe defaults."""
        result = detect_collusion_rings([], time_window_minutes=10, min_co_occurrences=2)
        assert result["rings_detected"] == 0
        assert result["total_riders_analyzed"] == 0

    def test_single_co_occurrence_below_threshold(self):
        """Pairs co-occurring only once should not be flagged with min_co_occurrences=2."""
        base = datetime(2026, 4, 15, 10, 0, 0)
        claims = [
            {"rider_id": "R1", "timestamp": base, "zone_id": "Z1"},
            {"rider_id": "R2", "timestamp": base + timedelta(minutes=3), "zone_id": "Z1"},
            # Only one co-occurrence — no second event
        ]
        result = detect_collusion_rings(claims, time_window_minutes=10, min_co_occurrences=2)
        assert result["rings_detected"] == 0
