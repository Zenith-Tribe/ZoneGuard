"""
homomorphic.py — Paillier Partially Homomorphic Encryption for FedShield v3.

Design:
  • Uses the `python-paillier` library (phe) for key generation and encryption.
  • Floats are quantised to integers before encryption:
        encoded = round(float_value * SCALE_FACTOR)
    and restored after decryption:
        float_value = decoded / SCALE_FACTOR
  • The central server NEVER calls decrypt during aggregation — it operates
    only on EncryptedNumber objects (ciphertext arithmetic).
  • Key pairs are generated per-city at startup; the PUBLIC key is shared
    with the server; the PRIVATE key stays exclusively on the city node.

Gradient delta format (matches FederatedAnomalyModel.get_weights()):
  {
    "weights": {"feat_name": float, ...},
    "means":   {"feat_name": float, ...},
    "stds":    {"feat_name": float, ...},
  }

Install:
  pip install python-paillier

References:
  Paillier, P. (1999). Public-Key Cryptosystems Based on Composite Degree
  Residuosity Classes. EUROCRYPT 1999.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Quantisation scale — 6 decimal places of precision
SCALE_FACTOR: int = 1_000_000

# Paillier key size — 2048 bits for production security
# Use 1024 for hackathon demo speed (key-gen ~0.3s vs ~3s)
KEY_BITS: int = 1024


# ---------------------------------------------------------------------------
# Graceful import — fall back to a plaintext stub if phe is not installed
# ---------------------------------------------------------------------------

try:
    import phe  # python-paillier
    _PHE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PHE_AVAILABLE = False
    logger.warning(
        "python-paillier not installed. FedShield v3 will use plaintext "
        "arithmetic (insecure — install phe for production)."
    )


# ---------------------------------------------------------------------------
# PaillierContext — holds a city's keypair
# ---------------------------------------------------------------------------

@dataclass
class PaillierContext:
    """
    Holds a Paillier keypair for one city node.

    Attributes:
        city_id:      Identifier for this city node.
        public_key:   Paillier public key (safe to share with server).
        private_key:  Paillier private key (NEVER leaves city node).
        n_bits:       RSA modulus bit length used during key generation.
    """

    city_id: str
    public_key: Any = field(default=None, repr=False)
    private_key: Any = field(default=None, repr=False)
    n_bits: int = KEY_BITS

    def __post_init__(self) -> None:
        if self.public_key is None:
            self._generate_keypair()

    def _generate_keypair(self) -> None:
        if _PHE_AVAILABLE:
            pub, priv = phe.generate_paillier_keypair(n_length=self.n_bits)
            self.public_key = pub
            self.private_key = priv
            logger.info(
                "PaillierContext[%s]: generated %d-bit keypair.", self.city_id, self.n_bits
            )
        else:
            # Stub keypair — plaintext passthrough
            self.public_key = _PlaintextPublicKey()
            self.private_key = _PlaintextPrivateKey()
            logger.warning(
                "PaillierContext[%s]: using PLAINTEXT stub (phe not installed).",
                self.city_id,
            )

    def get_public_key(self) -> Any:
        """Return public key for sharing with the aggregation server."""
        return self.public_key


# ---------------------------------------------------------------------------
# Plaintext stubs — used when phe is unavailable
# ---------------------------------------------------------------------------

class _PlaintextEncryptedNumber:
    """Stub that pretends to be an EncryptedNumber using plaintext."""
    def __init__(self, value: int) -> None:
        self._value = value

    def __add__(self, other: "_PlaintextEncryptedNumber") -> "_PlaintextEncryptedNumber":
        return _PlaintextEncryptedNumber(self._value + other._value)

    def __radd__(self, other: object) -> "_PlaintextEncryptedNumber":
        if isinstance(other, int) and other == 0:
            return self
        return self.__add__(other)  # type: ignore[arg-type]

    def __mul__(self, scalar: int) -> "_PlaintextEncryptedNumber":
        return _PlaintextEncryptedNumber(self._value * scalar)

    def decrypt_stub(self) -> int:
        return self._value


class _PlaintextPublicKey:
    def encrypt(self, value: int) -> _PlaintextEncryptedNumber:
        return _PlaintextEncryptedNumber(value)


class _PlaintextPrivateKey:
    def decrypt(self, enc: _PlaintextEncryptedNumber) -> int:  # type: ignore[override]
        return enc.decrypt_stub()


# ---------------------------------------------------------------------------
# Encode / Decode helpers
# ---------------------------------------------------------------------------

def _encode(value: float) -> int:
    """Quantise float → integer."""
    return round(value * SCALE_FACTOR)


def _decode(value: int) -> float:
    """Restore integer → float."""
    return value / SCALE_FACTOR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_weights(weights: dict, public_key: Any) -> dict:
    """
    Encrypt a FederatedAnomalyModel weights dict using a Paillier public key.

    Each float value is quantised then encrypted.  The returned dict has
    the same structure but EncryptedNumber values instead of floats.

    Args:
        weights:    Raw weight dict {"weights": {...}, "means": {...}, "stds": {...}}
        public_key: Paillier (or stub) public key belonging to this city node.

    Returns:
        Encrypted weight dict — safe to transmit to the aggregation server.
    """
    encrypted: dict = {}
    for param_key, feat_dict in weights.items():
        encrypted[param_key] = {}
        for feat_name, float_val in feat_dict.items():
            encoded = _encode(float_val)
            encrypted[param_key][feat_name] = public_key.encrypt(encoded)
    return encrypted


def decrypt_weights(enc_weights: dict, private_key: Any) -> dict:
    """
    Decrypt an encrypted weights dict back to floats.

    This function is called ONLY on the city node — never on the server.

    Args:
        enc_weights: Encrypted weight dict from encrypt_weights().
        private_key: Paillier private key (stays on city node).

    Returns:
        Plain float weight dict matching FederatedAnomalyModel.set_weights().
    """
    decrypted: dict = {}
    for param_key, feat_dict in enc_weights.items():
        decrypted[param_key] = {}
        for feat_name, enc_val in feat_dict.items():
            raw_int = private_key.decrypt(enc_val)
            decrypted[param_key][feat_name] = _decode(raw_int)
    return decrypted


def aggregate_encrypted(
    encrypted_weight_list: list[dict],
    sample_counts: list[int],
) -> dict:
    """
    Homomorphic FedAvg aggregation — operates entirely on ciphertext.

    Paillier supports additive homomorphism:
        E(a) + E(b) = E(a + b)
        E(a) * k   = E(a * k)

    So weighted sum on ciphertext = E(sum_i(w_i * n_i)) without
    ever decrypting intermediate values.

    The returned dict contains EncryptedNumber objects — the server
    returns this to city nodes who decrypt it with their private key.

    Args:
        encrypted_weight_list: List of encrypted weight dicts, one per city.
        sample_counts:         Number of training samples per city.

    Returns:
        Aggregated encrypted weight dict (ciphertext).
    """
    if not encrypted_weight_list:
        raise ValueError("aggregate_encrypted: received empty client list.")

    total_samples = sum(sample_counts)
    if total_samples == 0:
        logger.warning("aggregate_encrypted: total_samples=0, returning first client weights.")
        return encrypted_weight_list[0]

    # Use the structure of the first client to initialise accumulator
    param_keys = list(encrypted_weight_list[0].keys())
    feat_names = {pk: list(encrypted_weight_list[0][pk].keys()) for pk in param_keys}

    # Weighted sum on ciphertext — never touches plaintext
    aggregated: dict = {pk: {} for pk in param_keys}

    for param_key in param_keys:
        for feat_name in feat_names[param_key]:
            # Multiply each encrypted value by its sample count weight
            # then accumulate — all homomorphic
            weighted_enc_values = [
                enc_weights[param_key][feat_name] * n_i
                for enc_weights, n_i in zip(encrypted_weight_list, sample_counts)
            ]
            # Sum encrypted values (homomorphic addition)
            enc_sum = sum(weighted_enc_values)
            # Division by total_samples must happen AFTER decryption
            # (Paillier does not support ciphertext division).
            # We store (enc_sum, total_samples) as a tuple so the city
            # node can decode correctly: decrypt(enc_sum) / total_samples.
            aggregated[param_key][feat_name] = (enc_sum, total_samples)

    return aggregated


def finalise_aggregated_weights(
    aggregated: dict,
    private_key: Any,
) -> dict:
    """
    Decrypt and finalise aggregated weights on the city node.

    This is the CITY-SIDE counterpart to aggregate_encrypted().
    Each city decrypts the aggregated ciphertext and divides by
    total_samples to obtain the true FedAvg result.

    Args:
        aggregated:   Output of aggregate_encrypted() — contains
                      (EncryptedNumber, total_samples) tuples.
        private_key:  City's Paillier private key.

    Returns:
        Plain float weight dict ready for model.set_weights().
    """
    finalised: dict = {}
    for param_key, feat_dict in aggregated.items():
        finalised[param_key] = {}
        for feat_name, (enc_sum, total_samples) in feat_dict.items():
            raw_int_sum = private_key.decrypt(enc_sum)
            # Decode: raw_int_sum is already scaled by SCALE_FACTOR * n_i,
            # so divide by total_samples then by SCALE_FACTOR
            finalised[param_key][feat_name] = raw_int_sum / (total_samples * SCALE_FACTOR)
    return finalised
