"""
fedshield_client.py — FedShield v3 Encrypted Federated Learning Client.

Extends the original FederatedClient with:
  1. Paillier PHE encryption of gradient deltas before transmission.
  2. Online fraud feedback loop — approved/rejected claim outcomes update
     local anomaly thresholds, creating a closed claims→model feedback loop.
  3. Synthetic fraud scenario ingestion from ZoneTwin GAN v3 for training
     data augmentation.

Activation:
  Set env var FEDSHIELD_V3_ENABLED=true to activate this client in the
  existing federated/client.py scaffold (see patch in session4_patches.md).

Privacy guarantee:
  Raw claim data NEVER leaves the city node.
  Gradient deltas are encrypted before any network transmission.
  The private key NEVER leaves the city node.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from ml.federated.client import FederatedClient
from ml.federated.model import FederatedAnomalyModel
from ml.fedshield_v3.homomorphic import (
    PaillierContext,
    encrypt_weights,
    decrypt_weights,
    finalise_aggregated_weights,
)
from ml.fedshield_v3.gnn_fraud import FraudRingDetector, ClaimEvent

logger = logging.getLogger(__name__)


class FedShieldClient(FederatedClient):
    """
    FedShield v3 city node — encrypts gradient deltas with Paillier PHE.

    Inherits all FederatedClient methods and adds:
      • get_encrypted_weights()     — returns PHE-encrypted weights
      • apply_encrypted_global()    — decrypts + applies server aggregate
      • register_claim_event()      — feeds GNN ring detector
      • claim_outcome_feedback()    — online threshold adaptation
      • ingest_synthetic_samples()  — GAN-augmented training data
    """

    def __init__(
        self,
        city_id: str,
        zone_ids: list[str],
        key_bits: int = 1024,
    ) -> None:
        super().__init__(city_id, zone_ids)
        self._paillier = PaillierContext(city_id=city_id, n_bits=key_bits)
        self._ring_detector = FraudRingDetector()
        self._outcome_history: list[dict] = []  # (claim_id, approved, fraud_score)
        # Adaptive threshold offsets learned from outcome feedback
        self._threshold_offset: float = 0.0
        logger.info("FedShieldClient[%s]: PHE enabled (%d-bit key).", city_id, key_bits)

    # ------------------------------------------------------------------
    # PHE-encrypted weight exchange
    # ------------------------------------------------------------------

    def get_encrypted_weights(self) -> dict:
        """
        Return Paillier-encrypted model weights.

        The server receives EncryptedNumber values — it can aggregate
        homomorphically but cannot decrypt individual city updates.
        """
        raw_weights = self.model.get_weights()
        encrypted = encrypt_weights(raw_weights, self._paillier.public_key)
        logger.debug(
            "FedShieldClient[%s]: weights encrypted with Paillier PHE.", self.city_id
        )
        return encrypted

    def get_public_key(self) -> Any:
        """Return public key for the server (safe to share)."""
        return self._paillier.get_public_key()

    def apply_encrypted_global(self, aggregated_enc: dict) -> None:
        """
        Receive the server's homomorphically aggregated ciphertext,
        decrypt it locally, and apply to the local model.

        This is the ONLY point where decryption happens — on the city node,
        using the private key that never left this node.
        """
        decrypted = finalise_aggregated_weights(
            aggregated_enc, self._paillier.private_key
        )
        self.model.set_weights(decrypted)
        logger.info(
            "FedShieldClient[%s]: applied decrypted global aggregate.", self.city_id
        )

    # ------------------------------------------------------------------
    # Gradient delta encryption (for differential FL round)
    # ------------------------------------------------------------------

    def get_gradient_delta(self, global_weights: dict) -> dict:
        """
        Compute and encrypt the gradient delta relative to global model.

        delta = local_weights - global_weights (per parameter per feature)
        Returns encrypted delta dict.
        """
        local_w = self.model.get_weights()
        delta: dict = {}
        for pk in local_w:
            delta[pk] = {}
            for fn in local_w[pk]:
                delta[pk][fn] = local_w[pk][fn] - global_weights.get(pk, {}).get(fn, 0.0)
        return encrypt_weights(delta, self._paillier.public_key)

    # ------------------------------------------------------------------
    # GNN fraud ring detection
    # ------------------------------------------------------------------

    def register_claim_event(self, event: ClaimEvent) -> dict:
        """
        Register a new claim event with the GNN ring detector.

        Returns the current ring detection summary for the event's zone.
        """
        self._ring_detector.register_claim(event)
        return self._ring_detector.get_zone_summary(event.zone_id)

    def get_ring_coefficient(self, zone_id: str) -> float:
        """Return temporal clustering coefficient for a zone (0-1)."""
        return self._ring_detector.get_clustering_coefficient(zone_id)

    # ------------------------------------------------------------------
    # Online learning from claim outcomes
    # ------------------------------------------------------------------

    def claim_outcome_feedback(
        self,
        claim_id: str,
        fraud_score: float,
        approved: bool,
    ) -> None:
        """
        Update local anomaly thresholds based on claim adjudication outcome.

        Logic:
          • High score + approved → false positive → relax threshold slightly
          • Low score + rejected  → false negative → tighten threshold slightly
          • Magnitude: 0.5% per feedback event, bounded at ±10%

        This creates a closed loop:
          QuadSignal → FraudShield → Claims Adjudication → FedShieldClient
        """
        LEARNING_RATE = 0.005
        MAX_OFFSET = 0.10

        high_score_approved = fraud_score > 0.65 and approved
        low_score_rejected = fraud_score < 0.40 and not approved

        if high_score_approved:
            # False positive — relax (increase threshold, reduce sensitivity)
            self._threshold_offset = min(
                self._threshold_offset + LEARNING_RATE, MAX_OFFSET
            )
        elif low_score_rejected:
            # False negative — tighten (decrease threshold, increase sensitivity)
            self._threshold_offset = max(
                self._threshold_offset - LEARNING_RATE, -MAX_OFFSET
            )

        self._outcome_history.append({
            "claim_id": claim_id,
            "fraud_score": fraud_score,
            "approved": approved,
            "threshold_offset": round(self._threshold_offset, 4),
        })

        logger.debug(
            "FedShieldClient[%s]: outcome feedback — approved=%s score=%.3f "
            "offset now=%.4f",
            self.city_id, approved, fraud_score, self._threshold_offset,
        )

    def get_adjusted_thresholds(self) -> dict:
        """
        Return fraud score thresholds adjusted by outcome learning.

        Upstream callers (fraud_shield.py, claims endpoint) use these
        instead of the hardcoded 0.65/0.85 values.
        """
        return {
            "review_threshold": round(0.65 + self._threshold_offset, 4),
            "hold_threshold": round(0.85 + self._threshold_offset, 4),
            "city_id": self.city_id,
            "offset": self._threshold_offset,
        }

    # ------------------------------------------------------------------
    # GAN-augmented training data ingestion
    # ------------------------------------------------------------------

    def ingest_synthetic_samples(self, synthetic_samples: list[dict]) -> int:
        """
        Augment local training data with synthetic fraud scenarios from
        ZoneTwin GAN v3.

        Synthetic samples follow the same 8-feature dict format as
        FederatedAnomalyModel.fit() expects.

        Returns: count of samples ingested.
        """
        if not synthetic_samples:
            return 0
        self.model.fit(synthetic_samples)
        self.training_samples += len(synthetic_samples)
        logger.info(
            "FedShieldClient[%s]: ingested %d synthetic samples from GAN.",
            self.city_id, len(synthetic_samples),
        )
        return len(synthetic_samples)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_v3_status(self) -> dict:
        """Return FedShield v3 diagnostics for this city node."""
        return {
            "city_id": self.city_id,
            "zone_ids": self.zone_ids,
            "phe_enabled": True,
            "key_bits": self._paillier.n_bits,
            "training_samples": self.training_samples,
            "threshold_offset": round(self._threshold_offset, 4),
            "adjusted_thresholds": self.get_adjusted_thresholds(),
            "outcome_history_count": len(self._outcome_history),
            "gnn_backend": "torch" if self._ring_detector._use_torch else "numpy",
        }
