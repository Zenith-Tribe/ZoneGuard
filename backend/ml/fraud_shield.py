"""
FraudShield Phase 3 — Behavioral & Multimodal Anomaly Detection.

Features used for scoring:
- claim_hour: hour of claim creation (0-23)
- tenure_weeks: rider's tenure
- zone_inactivity_pct: % riders inactive in zone
- claim_velocity_7d: claims by this rider in last 7 days
- zone_claim_rate_deviation: zone's claim rate vs mean
- distance_from_centroid: how far rider is from zone center
- s1_value: environmental signal value
- days_since_policy_start: freshness of policy
- vibration_entropy: mechanical engine signature vs GPS simulator (Phase 3)
- acoustic_confidence: Gemini audio verification of rainfall (Phase 3)

Thresholds:
- score > 0.65 → "review" flag
- score > 0.85 → "hold" (auto-hold payout)
"""

import numpy as np
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def calculate_fraud_score(
    claim_hour: int,
    tenure_weeks: int,
    zone_inactivity_pct: float,
    claim_velocity_7d: int,
    zone_claim_rate_deviation: float,
    distance_from_centroid_km: float,
    s1_value: float,
    days_since_policy_start: int,
    temporal_clustering_coefficient: float = 0.0,
    vibration_entropy: float = 0.8,    # Phase 3: Individual Telemetry
    acoustic_confidence: float = 0.0,  # Phase 3: Gemini Multimodal Verification
) -> dict:
    """
    Rule-based fraud scoring with Phase 3 Behavioral and Multimodal logic.
    Ensures score is bounded between 0.0 and 1.0.
    """
    anomaly_signals = []
    score = 0.0

    # Phase 3: Individual Behavioral Analysis (Accelerometer/Vibration)
    # Low vibration entropy while GPS is moving suggests a GPS simulator.
    if vibration_entropy < 0.3:
        score += 0.35
        anomaly_signals.append("Anomaly: Low Vibration Entropy (Possible GPS Simulator)")
    
    # Phase 3: Acoustic Verification (Signal 4 Override)
    # AI-confirmed rainfall reduces the overall fraud suspicion score.
    if acoustic_confidence > 0.8:
        score -= 0.2 
        anomaly_signals.append("Acoustic Proof: Gemini verified rainfall audio")

    # Suspicious claim timing (late night / early morning)
    if claim_hour < 6 or claim_hour > 22:
        score += 0.15
        anomaly_signals.append(f"unusual claim hour ({claim_hour}:00)")

    # Very new policy (less than 2 days old)
    if days_since_policy_start < 2:
        score += 0.20
        anomaly_signals.append(f"policy only {days_since_policy_start} days old")

    # High claim velocity
    if claim_velocity_7d > 3:
        score += 0.25
        anomaly_signals.append(f"{claim_velocity_7d} claims in 7 days")
    elif claim_velocity_7d > 2:
        score += 0.10

    # Zone claim rate deviation (zone claiming much more than average)
    if zone_claim_rate_deviation > 2.0:
        score += 0.15
        anomaly_signals.append(f"zone claim rate {zone_claim_rate_deviation:.1f}x above mean")

    # Low inactivity but claiming (other riders are active, this rider claims)
    if zone_inactivity_pct < 20:
        score += 0.15
        anomaly_signals.append(f"only {zone_inactivity_pct:.0f}% zone inactive but claiming")

    # Far from zone centroid
    if distance_from_centroid_km > 5:
        score += 0.10
        anomaly_signals.append(f"{distance_from_centroid_km:.1f}km from zone center")

    # Low environmental signal but claiming
    if s1_value < 30:
        score += 0.10
        anomaly_signals.append(f"S1 environmental value only {s1_value:.0f}")

    # Very new rider
    if tenure_weeks < 2:
        score += 0.10
        anomaly_signals.append(f"rider tenure only {tenure_weeks} weeks")

    # Temporal clustering — possible coordinated claims
    if temporal_clustering_coefficient > 0.5:
        score += 0.20
        anomaly_signals.append(
            f"temporal clustering coefficient {temporal_clustering_coefficient:.2f} — possible coordinated claims"
        )

    # FIX: Ensure score is never negative and never exceeds 1.0
    score = max(0.0, min(1.0, score))

    if score > 0.85:
        risk_level = "hold"
    elif score > 0.65:
        risk_level = "review"
    else:
        risk_level = "low"

    return {
        "score": round(score, 3),
        "risk_level": risk_level,
        "anomaly_signals": anomaly_signals,
        "model_version": "v3_behavioral_heuristic",
        "features": {
            "claim_hour": claim_hour,
            "tenure_weeks": tenure_weeks,
            "zone_inactivity_pct": zone_inactivity_pct,
            "claim_velocity_7d": claim_velocity_7d,
            "zone_claim_rate_deviation": zone_claim_rate_deviation,
            "distance_from_centroid_km": distance_from_centroid_km,
            "s1_value": s1_value,
            "days_since_policy_start": days_since_policy_start,
            "vibration_entropy": vibration_entropy,    # Added for Phase 3
            "acoustic_confidence": acoustic_confidence # Added for Phase 3
        },
    }


# Module-level registry for trained federated model weights.
_federated_global_weights: dict | None = None


def set_federated_weights(weights: dict) -> None:
    """Store trained global weights for v2 scoring."""
    global _federated_global_weights
    _federated_global_weights = weights


def calculate_fraud_score_v2(
    claim_hour: int,
    tenure_weeks: int,
    zone_inactivity_pct: float,
    claim_velocity_7d: int,
    zone_claim_rate_deviation: float,
    distance_from_centroid_km: float,
    s1_value: float,
    days_since_policy_start: int,
    temporal_clustering_coefficient: float = 0.0,
    vibration_entropy: float = 0.8,
    acoustic_confidence: float = 0.0,
) -> dict:
    """
    FraudShield v3 — Federated Learning anomaly detection.
    Passes all Phase 3 features to the federated model.
    """
    if _federated_global_weights is not None:
        try:
            from ml.federated.model import FederatedAnomalyModel

            model = FederatedAnomalyModel()
            model.set_weights(_federated_global_weights)
            result = model.predict({
                "claim_hour": claim_hour,
                "tenure_weeks": tenure_weeks,
                "zone_inactivity_pct": zone_inactivity_pct,
                "claim_velocity_7d": claim_velocity_7d,
                "zone_claim_rate_deviation": zone_claim_rate_deviation,
                "distance_from_centroid_km": distance_from_centroid_km,
                "s1_value": s1_value,
                "days_since_policy_start": days_since_policy_start,
                "vibration_entropy": vibration_entropy,
                "acoustic_confidence": acoustic_confidence
            })
            result["model_version"] = "v3_federated"
            result["federated_metadata"] = {"model_type": "FederatedAnomalyModel", "aggregation": "FedAvg"}
            return result
        except (ImportError, Exception) as e:
            logger.warning(f"FraudShield v3 federated prediction failed ({e}), falling back to heuristic")

    # Fallback to logic-based heuristic
    result = calculate_fraud_score(
        claim_hour=claim_hour,
        tenure_weeks=tenure_weeks,
        zone_inactivity_pct=zone_inactivity_pct,
        claim_velocity_7d=claim_velocity_7d,
        zone_claim_rate_deviation=zone_claim_rate_deviation,
        distance_from_centroid_km=distance_from_centroid_km,
        s1_value=s1_value,
        days_since_policy_start=days_since_policy_start,
        temporal_clustering_coefficient=temporal_clustering_coefficient,
        vibration_entropy=vibration_entropy,
        acoustic_confidence=acoustic_confidence
    )
    result["model_version"] = "v3_heuristic_fallback"
    return result
