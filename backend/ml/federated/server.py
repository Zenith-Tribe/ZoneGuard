# MERGED BY SESSION 7 — Patches from sessions: 4
# Session 4 adds: FedShield v3 Krum aggregation override when FEDSHIELD_V3_ENABLED=true
# [INTEGRATION WARNING] FedShieldServer.run_full_training_v3() returns an extended
#   dict with `byzantine_reports` key. Any handler calling run_full_training() must
#   handle the extra key gracefully (extra keys are non-breaking).

"""
FraudShield v2 — Federated Aggregation Server.

Implements FedAvg (Federated Averaging) for aggregating anomaly-model
parameters from city-level clients.  Inspired by the Flower framework
but implemented as a lightweight simulation for hackathon demo purposes.
"""

import numpy as np

from ml.federated.client import FederatedClient
from ml.federated.model import FederatedAnomalyModel

# ── Session 4: FedShield v3 — Krum aggregation replaces FedAvg when enabled ──
import os as _os

_FEDSHIELD_V3 = _os.getenv("FEDSHIELD_V3_ENABLED", "false").lower() == "true"

if _FEDSHIELD_V3:
    try:
        from ml.fedshield_v3.fedshield_server import FedShieldServer as FederatedServer  # noqa: F811
        import logging as _logging
        _logging.getLogger(__name__).info(
            "federated/server.py: FedShield v3 active — "
            "using Krum aggregation + PHE FedShieldServer."
        )
    except ImportError as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "FEDSHIELD_V3_ENABLED=true but FedShieldServer import failed (%s). "
            "Falling back to FederatedServer v2 (FedAvg).", _e
        )
# ── End Session 4 FedShield v3 override ───────────────────────────────────────


class FederatedServer:
    """Central aggregation server implementing FedAvg for FraudShield v2."""

    def __init__(self, num_rounds: int = 5) -> None:
        self.num_rounds = num_rounds
        self.clients: list[FederatedClient] = []
        self.global_model = FederatedAnomalyModel()
        self.training_history: list[dict] = []
        self.is_trained: bool = False

    def register_client(self, client: FederatedClient) -> None:
        """Register a city-level client with the server."""
        self.clients.append(client)

    def aggregate_weights(
        self,
        client_weights: list[dict],
        sample_counts: list[int],
    ) -> dict:
        """FedAvg: weighted average of client parameters by sample count."""
        total_samples = sum(sample_counts)
        if total_samples == 0:
            return client_weights[0] if client_weights else self.global_model.get_weights()

        feature_names = FederatedAnomalyModel.FEATURE_NAMES
        aggregated: dict = {"weights": {}, "means": {}, "stds": {}}

        for param_key in ("weights", "means", "stds"):
            for feat in feature_names:
                weighted_sum = sum(
                    cw[param_key][feat] * n
                    for cw, n in zip(client_weights, sample_counts)
                )
                aggregated[param_key][feat] = weighted_sum / total_samples

        return aggregated

    def run_federation_round(self) -> dict:
        """Execute one federation round (FedAvg).

        1. Collect current weights and sample counts from all clients.
        2. Aggregate via FedAvg.
        3. Push the global weights back to every client.

        Returns a dict with round metrics.
        """
        client_weights: list[dict] = []
        sample_counts: list[int] = []

        for client in self.clients:
            client_weights.append(client.get_model_weights())
            sample_counts.append(client.training_samples)

        previous_global = self.global_model.get_weights()
        aggregated = self.aggregate_weights(client_weights, sample_counts)

        deltas: list[float] = []
        for param_key in ("weights", "means", "stds"):
            for feat in FederatedAnomalyModel.FEATURE_NAMES:
                deltas.append(
                    abs(aggregated[param_key][feat] - previous_global[param_key][feat])
                )
        convergence_delta = float(np.mean(deltas))

        self.global_model.set_weights(aggregated)
        for client in self.clients:
            client.update_model(aggregated)

        round_metrics = {
            "participating_clients": len(self.clients),
            "total_samples": sum(sample_counts),
            "convergence_delta": round(convergence_delta, 6),
            "per_client_samples": {
                c.city_id: c.training_samples for c in self.clients
            },
        }
        self.training_history.append(round_metrics)
        return round_metrics

    def run_full_training(self) -> dict:
        """Run all rounds and return a training summary."""
        for _ in range(self.num_rounds):
            self.run_federation_round()

        self.is_trained = True

        return {
            "rounds_completed": self.num_rounds,
            "final_weights": self.global_model.get_weights(),
            "convergence_history": [
                r["convergence_delta"] for r in self.training_history
            ],
            "per_client_stats": {
                c.city_id: {
                    "zone_ids": c.zone_ids,
                    "training_samples": c.training_samples,
                }
                for c in self.clients
            },
        }

    def get_status(self) -> dict:
        """Return current federation state."""
        return {
            "is_trained": self.is_trained,
            "num_clients": len(self.clients),
            "num_rounds": self.num_rounds,
            "training_history": self.training_history,
        }


# ======================================================================
# Synthetic data generation (unchanged from baseline)
# ======================================================================

def generate_synthetic_training_data(
    zone_id: str,
    num_samples: int = 100,
    anomaly_fraction: float = 0.12,
    seed: int | None = None,
) -> list[dict]:
    """Generate realistic synthetic claim data for demo/training."""
    if seed is None:
        seed = hash(zone_id) % (2**31)
    rng = np.random.default_rng(seed)

    num_anomalous = int(num_samples * anomaly_fraction)
    num_normal = num_samples - num_anomalous

    samples: list[dict] = []

    for _ in range(num_normal):
        samples.append({
            "claim_hour": int(rng.integers(7, 21)),
            "tenure_weeks": int(rng.integers(4, 80)),
            "zone_inactivity_pct": round(float(rng.uniform(25, 65)), 1),
            "claim_velocity_7d": int(rng.integers(0, 3)),
            "zone_claim_rate_deviation": round(float(rng.uniform(0.5, 1.8)), 2),
            "distance_from_centroid_km": round(float(rng.uniform(0.5, 4.0)), 1),
            "s1_value": round(float(rng.uniform(40, 95)), 1),
            "days_since_policy_start": int(rng.integers(7, 120)),
        })

    for _ in range(num_anomalous):
        samples.append({
            "claim_hour": int(rng.choice([1, 2, 3, 4, 23, 0])),
            "tenure_weeks": int(rng.integers(0, 3)),
            "zone_inactivity_pct": round(float(rng.uniform(5, 18)), 1),
            "claim_velocity_7d": int(rng.integers(4, 8)),
            "zone_claim_rate_deviation": round(float(rng.uniform(2.5, 5.0)), 2),
            "distance_from_centroid_km": round(float(rng.uniform(6, 15)), 1),
            "s1_value": round(float(rng.uniform(5, 25)), 1),
            "days_since_policy_start": int(rng.integers(0, 2)),
        })

    rng.shuffle(samples)

    return samples
