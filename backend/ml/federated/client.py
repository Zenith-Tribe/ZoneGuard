"""
FraudShield v2 — Federated Client.

Each client represents a city-level fraud detection node that trains
on local claim data and shares only model parameters (never raw data)
with the central aggregation server.
"""

from ml.federated.model import FederatedAnomalyModel


class FederatedClient:
    """City-level federated learning client for FraudShield v2."""

    def __init__(self, city_id: str, zone_ids: list[str]) -> None:
        self.city_id = city_id
        self.zone_ids = zone_ids
        self.model = FederatedAnomalyModel()
        self.training_samples: int = 0

    def train_local_model(self, claim_data: list[dict]) -> dict:
        """Train on local city data. Returns model weights (NOT raw data).

        This is the core privacy guarantee of federated learning: raw
        claim-level data never leaves the city node.  Only aggregated
        statistics (means, stds, weights) are shared.
        """
        self.model.fit(claim_data)
        self.training_samples = len(claim_data)
        return self.model.get_weights()

    def get_model_weights(self) -> dict:
        """Return current local model parameters."""
        return self.model.get_weights()

    def update_model(self, global_weights: dict) -> None:
        """Apply global model parameters received from the server."""
        self.model.set_weights(global_weights)

    def predict(self, claim_features: dict) -> dict:
        """Score a claim using the local (or globally-updated) model."""
        return self.model.predict(claim_features)
