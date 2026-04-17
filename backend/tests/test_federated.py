"""Tests for FraudShield v2 Federated Learning simulation — pure functions, no DB."""

from ml.federated.model import FederatedAnomalyModel
from ml.federated.client import FederatedClient
from ml.federated.server import FederatedServer, generate_synthetic_training_data


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _normal_features(**overrides) -> dict:
    """Return a realistic, non-anomalous feature dict."""
    defaults = {
        "claim_hour": 14,
        "tenure_weeks": 30,
        "zone_inactivity_pct": 45.0,
        "claim_velocity_7d": 1,
        "zone_claim_rate_deviation": 1.0,
        "distance_from_centroid_km": 2.0,
        "s1_value": 70.0,
        "days_since_policy_start": 30,
    }
    defaults.update(overrides)
    return defaults


def _anomalous_features(**overrides) -> dict:
    """Return a clearly fraudulent feature dict."""
    defaults = {
        "claim_hour": 2,
        "tenure_weeks": 0,
        "zone_inactivity_pct": 5.0,
        "claim_velocity_7d": 7,
        "zone_claim_rate_deviation": 4.5,
        "distance_from_centroid_km": 12.0,
        "s1_value": 10.0,
        "days_since_policy_start": 0,
    }
    defaults.update(overrides)
    return defaults


def _make_training_data(n_normal: int = 80, n_anomalous: int = 20) -> list[dict]:
    """Build a mixed training set from helpers."""
    data = [_normal_features() for _ in range(n_normal)]
    data += [_anomalous_features() for _ in range(n_anomalous)]
    return data


# ──────────────────────────────────────────────────────────────────────
# Model tests
# ──────────────────────────────────────────────────────────────────────

class TestFederatedAnomalyModel:
    def test_model_fit_updates_parameters(self):
        """Fitting a model should change means and stds from defaults."""
        model = FederatedAnomalyModel()
        original_means = model.means.copy()
        original_stds = model.stds.copy()

        data = _make_training_data()
        model.fit(data)

        assert model.is_fitted
        # At least some means/stds should have changed.
        means_changed = any(
            model.means[f] != original_means[f]
            for f in FederatedAnomalyModel.FEATURE_NAMES
        )
        stds_changed = any(
            model.stds[f] != original_stds[f]
            for f in FederatedAnomalyModel.FEATURE_NAMES
        )
        assert means_changed, "means should update after fit"
        assert stds_changed, "stds should update after fit"

    def test_model_predict_returns_valid_score(self):
        """Prediction should return score in [0,1] and a valid risk_level."""
        model = FederatedAnomalyModel()
        model.fit(_make_training_data())

        result = model.predict(_normal_features())

        assert 0.0 <= result["score"] <= 1.0
        assert result["risk_level"] in ("low", "review", "hold")
        assert isinstance(result["anomaly_signals"], list)
        assert "features" in result

    def test_model_predict_high_anomaly(self):
        """Clearly anomalous features should yield a high score."""
        model = FederatedAnomalyModel()
        model.fit(_make_training_data())

        result = model.predict(_anomalous_features())

        assert result["score"] > 0.6, f"Expected high anomaly score, got {result['score']}"
        assert len(result["anomaly_signals"]) > 0

    def test_model_predict_normal(self):
        """Normal features should yield a low score."""
        model = FederatedAnomalyModel()
        model.fit(_make_training_data())

        result = model.predict(_normal_features())

        assert result["score"] < 0.5, f"Expected low score for normal features, got {result['score']}"

    def test_fallback_unfitted_model(self):
        """An unfitted model should still return valid predictions (graceful degradation)."""
        model = FederatedAnomalyModel()
        assert not model.is_fitted

        result = model.predict(_normal_features())

        assert 0.0 <= result["score"] <= 1.0
        assert result["risk_level"] in ("low", "review", "hold")
        assert isinstance(result["anomaly_signals"], list)
        assert "features" in result


# ──────────────────────────────────────────────────────────────────────
# Client tests
# ──────────────────────────────────────────────────────────────────────

class TestFederatedClient:
    def test_client_train_returns_weights(self):
        """Client training should return a dict with weights, means, stds."""
        client = FederatedClient("bangalore", ["hsr", "koramangala"])
        data = generate_synthetic_training_data("hsr", num_samples=50)
        weights = client.train_local_model(data)

        assert "weights" in weights
        assert "means" in weights
        assert "stds" in weights
        assert client.training_samples == 50
        assert client.model.is_fitted

    def test_client_update_model(self):
        """Client should accept global weights and use them for prediction."""
        client = FederatedClient("mumbai", ["andheri"])

        # Create custom global weights.
        global_weights = {
            "weights": {f: 1.5 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "means": {f: 10.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "stds": {f: 5.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
        }
        client.update_model(global_weights)

        assert client.model.is_fitted
        assert client.model.weights["claim_hour"] == 1.5
        assert client.model.means["claim_hour"] == 10.0

        # Prediction should work with the updated model.
        result = client.predict(_normal_features())
        assert 0.0 <= result["score"] <= 1.0


# ──────────────────────────────────────────────────────────────────────
# Server tests
# ──────────────────────────────────────────────────────────────────────

class TestFederatedServer:
    def test_server_fedavg_aggregation(self):
        """FedAvg with Sybil Resistance: caps each client at 20% of total samples."""
        server = FederatedServer(num_rounds=1)

        # Client A: 100 samples, all weights = 2.0, means = 10.0, stds = 3.0
        weights_a = {
            "weights": {f: 2.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "means": {f: 10.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "stds": {f: 3.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
        }
        # Client B: 300 samples, all weights = 4.0, means = 20.0, stds = 5.0
        weights_b = {
            "weights": {f: 4.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "means": {f: 20.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
            "stds": {f: 5.0 for f in FederatedAnomalyModel.FEATURE_NAMES},
        }

        aggregated = server.aggregate_weights(
            [weights_a, weights_b],
            sample_counts=[100, 300],
        )

        # Sybil cap = 20% of 400 = 80. Effective: [80, 80] (both capped).
        # Equal effective weight → simple average: (2.0 + 4.0) / 2 = 3.0
        for feat in FederatedAnomalyModel.FEATURE_NAMES:
            assert abs(aggregated["weights"][feat] - 3.0) < 1e-6
        # Means: (10 + 20) / 2 = 15.0
        for feat in FederatedAnomalyModel.FEATURE_NAMES:
            assert abs(aggregated["means"][feat] - 15.0) < 1e-6
        # Stds: Pooled variance (Law of Total Variance)
        # Var = [80*(9 + 25) + 80*(25 + 25)] / 160 = 6720/160 = 42.0
        import math
        expected_std = math.sqrt(42.0)
        for feat in FederatedAnomalyModel.FEATURE_NAMES:
            assert abs(aggregated["stds"][feat] - expected_std) < 1e-4

    def test_server_full_training_converges(self):
        """Run 5 rounds; verify weight deltas decrease (convergence)."""
        server = FederatedServer(num_rounds=5)

        # Create 3 city clients with different data distributions.
        cities = [
            ("bangalore", ["hsr", "koramangala"]),
            ("mumbai", ["andheri", "bandra"]),
            ("delhi", ["cp", "dwarka"]),
        ]
        for city_id, zones in cities:
            client = FederatedClient(city_id, zones)
            data = generate_synthetic_training_data(zones[0], num_samples=80)
            client.train_local_model(data)
            server.register_client(client)

        summary = server.run_full_training()

        assert summary["rounds_completed"] == 5
        assert server.is_trained

        convergence = summary["convergence_history"]
        assert len(convergence) == 5

        # After the first round all clients get identical global weights,
        # so subsequent rounds should have zero or near-zero deltas.
        # Check that later deltas are <= earlier deltas (non-increasing).
        # Allow small floating-point tolerance.
        for i in range(1, len(convergence)):
            assert convergence[i] <= convergence[i - 1] + 1e-9, (
                f"Convergence should be non-increasing: "
                f"round {i} delta {convergence[i]} > round {i-1} delta {convergence[i-1]}"
            )

    def test_server_round_returns_metrics(self):
        """Each round should return participation count and convergence metric."""
        server = FederatedServer(num_rounds=1)

        client_a = FederatedClient("bangalore", ["hsr"])
        client_a.train_local_model(
            generate_synthetic_training_data("hsr", num_samples=50)
        )
        client_b = FederatedClient("mumbai", ["andheri"])
        client_b.train_local_model(
            generate_synthetic_training_data("andheri", num_samples=60)
        )

        server.register_client(client_a)
        server.register_client(client_b)

        metrics = server.run_federation_round()

        assert metrics["participating_clients"] == 2
        assert metrics["total_samples"] == 110
        assert "convergence_delta" in metrics
        assert isinstance(metrics["convergence_delta"], float)
        assert "per_client_samples" in metrics
        assert metrics["per_client_samples"]["bangalore"] == 50
        assert metrics["per_client_samples"]["mumbai"] == 60


# ──────────────────────────────────────────────────────────────────────
# Synthetic data generation tests
# ──────────────────────────────────────────────────────────────────────

class TestGenerateSyntheticData:
    def test_generate_synthetic_data(self):
        """Generated data should have correct keys and reasonable value ranges."""
        data = generate_synthetic_training_data("hsr", num_samples=200, seed=42)

        assert len(data) == 200

        expected_keys = set(FederatedAnomalyModel.FEATURE_NAMES)
        for sample in data:
            assert set(sample.keys()) == expected_keys

            assert 0 <= sample["claim_hour"] <= 23
            assert sample["tenure_weeks"] >= 0
            assert 0 <= sample["zone_inactivity_pct"] <= 100
            assert sample["claim_velocity_7d"] >= 0
            assert sample["zone_claim_rate_deviation"] >= 0
            assert sample["distance_from_centroid_km"] >= 0
            assert sample["s1_value"] >= 0
            assert sample["days_since_policy_start"] >= 0
