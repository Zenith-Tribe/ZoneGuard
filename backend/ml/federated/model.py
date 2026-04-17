"""
FraudShield v2 — Federated Anomaly Model.

Lightweight anomaly scorer with tunable weights, designed for federated
training across city-level nodes. Uses z-score weighted combination
across the same 8 features as FraudShield v1.

Thresholds (same as v1):
- score > 0.65 -> "review"
- score > 0.85 -> "hold"
"""

import numpy as np


class FederatedAnomalyModel:
    """Anomaly detection model with tunable weights for federated training."""

    FEATURE_NAMES = [
        "claim_hour",
        "tenure_weeks",
        "zone_inactivity_pct",
        "claim_velocity_7d",
        "zone_claim_rate_deviation",
        "distance_from_centroid_km",
        "s1_value",
        "days_since_policy_start",
    ]

    # Default population statistics used when the model has not been fitted.
    # These act as reasonable priors so an unfitted model still returns
    # sensible (if less precise) scores — graceful degradation.
    _DEFAULT_MEANS = {
        "claim_hour": 12.0,
        "tenure_weeks": 20.0,
        "zone_inactivity_pct": 35.0,
        "claim_velocity_7d": 1.0,
        "zone_claim_rate_deviation": 1.0,
        "distance_from_centroid_km": 2.5,
        "s1_value": 55.0,
        "days_since_policy_start": 30.0,
    }

    _DEFAULT_STDS = {
        "claim_hour": 6.0,
        "tenure_weeks": 12.0,
        "zone_inactivity_pct": 20.0,
        "claim_velocity_7d": 1.0,
        "zone_claim_rate_deviation": 0.8,
        "distance_from_centroid_km": 2.0,
        "s1_value": 25.0,
        "days_since_policy_start": 20.0,
    }

    def __init__(self) -> None:
        self.weights: dict[str, float] = {f: 1.0 for f in self.FEATURE_NAMES}
        self.means: dict[str, float] = dict(self._DEFAULT_MEANS)
        self.stds: dict[str, float] = dict(self._DEFAULT_STDS)
        self.is_fitted: bool = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(self, data: list[dict]) -> None:
        """Learn population statistics from training data.

        For each feature, computes mean and std from the data.  Weights
        are then adjusted based on feature variance — higher-variance
        features receive higher weight because they carry more
        discriminative signal for anomaly detection.
        """
        if not data:
            return

        for feat in self.FEATURE_NAMES:
            values = np.array([d[feat] for d in data], dtype=np.float64)
            self.means[feat] = float(np.mean(values))
            std = float(np.std(values))
            # Guard against zero std (constant feature).
            self.stds[feat] = std if std > 1e-8 else 1e-8

        # Weight by coefficient of variation (normalized variance).
        # Higher CV means the feature varies more relative to its mean,
        # making it more useful for spotting outliers.
        cvs: dict[str, float] = {}
        for feat in self.FEATURE_NAMES:
            # FIX: Prevent Exploding Weights by using a logical floor of 1.0 
            # instead of 1e-8 for the mean absolute value.
            mean_abs = max(abs(self.means[feat]), 1.0)
            cvs[feat] = self.stds[feat] / mean_abs

        max_cv = max(cvs.values()) if cvs else 1.0
        # FIX: Ensure max_cv also has a safe floor to prevent division by near-zero
        max_cv = max(max_cv, 1.0)

        for feat in self.FEATURE_NAMES:
            # Normalize to [0.5, 2.0] range so no feature is zeroed out.
            self.weights[feat] = 0.5 + 1.5 * (cvs[feat] / max_cv)

        self.is_fitted = True

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: dict) -> dict:
        """Compute anomaly score using z-score weighted combination.

        Returns the same structure as FraudShield v1's
        ``calculate_fraud_score``:
          - score: float in [0, 1]
          - risk_level: "low" | "review" | "hold"
          - anomaly_signals: list[str]
          - features: dict  (echo of input)
        """
        z_scores: dict[str, float] = {}
        anomaly_signals: list[str] = []

        for feat in self.FEATURE_NAMES:
            value = float(features.get(feat, 0.0))
            mean = self.means[feat]
            std = self.stds[feat] if self.stds[feat] > 1e-8 else 1e-8
            z = (value - mean) / std
            z_scores[feat] = z

            # Flag features with |z| > 1.5 as anomalous.
            if abs(z) > 1.5:
                direction = "high" if z > 0 else "low"
                anomaly_signals.append(
                    f"{feat} is {direction} (z={z:+.2f})"
                )

        # Weighted combination of absolute z-scores.
        total_weight = sum(self.weights[f] for f in self.FEATURE_NAMES)
        raw_score = sum(
            abs(z_scores[f]) * self.weights[f] for f in self.FEATURE_NAMES
        ) / total_weight

        # Sigmoid-like normalization to [0, 1].
        # A raw score of ~3 maps to ~0.95; raw 1 maps to ~0.46.
        score = float(1.0 / (1.0 + np.exp(-1.2 * (raw_score - 1.5))))
        score = round(min(1.0, max(0.0, score)), 3)

        if score > 0.85:
            risk_level = "hold"
        elif score > 0.65:
            risk_level = "review"
        else:
            risk_level = "low"

        return {
            "score": score,
            "risk_level": risk_level,
            "anomaly_signals": anomaly_signals,
            "features": {f: features.get(f, 0.0) for f in self.FEATURE_NAMES},
        }

    # ------------------------------------------------------------------
    # Parameter exchange (federation interface)
    # ------------------------------------------------------------------

    def get_weights(self) -> dict:
        """Return current model parameters for federation."""
        return {
            "weights": self.weights.copy(),
            "means": self.means.copy(),
            "stds": self.stds.copy(),
        }

    def set_weights(self, params: dict) -> None:
        """Apply global parameters from federation server."""
        self.weights = params["weights"].copy()
        self.means = params["means"].copy()
        self.stds = params["stds"].copy()
        self.is_fitted = True
