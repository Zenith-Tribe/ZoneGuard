# MERGED BY SESSION 7 — Patches from sessions: 4
# Session 4 adds: FedShield v3 transparent override when FEDSHIELD_V3_ENABLED=true

"""
FraudShield v2 — Federated Client.

Each client represents a city-level fraud detection node that trains
on local claim data and shares only model parameters (never raw data)
with the central aggregation server.
"""

from ml.federated.model import FederatedAnomalyModel

# ── Session 4: FedShield v3 — activated by env var FEDSHIELD_V3_ENABLED=true ─
import os as _os

_FEDSHIELD_V3 = _os.getenv("FEDSHIELD_V3_ENABLED", "false").lower() == "true"

if _FEDSHIELD_V3:
    try:
        from ml.fedshield_v3.fedshield_client import FedShieldClient as FederatedClient  # noqa: F811
        import logging as _logging
        _logging.getLogger(__name__).info(
            "federated/client.py: FedShield v3 active — "
            "using PHE-encrypted FedShieldClient."
        )
    except ImportError as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "FEDSHIELD_V3_ENABLED=true but FedShieldClient import failed (%s). "
            "Falling back to FederatedClient v2.", _e
        )
# ── End Session 4 FedShield v3 override ───────────────────────────────────────


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
