"""Tests for FedShield v3 Paillier PHE — encrypt/decrypt roundtrip, homomorphic
addition, and probabilistic encryption properties.

Works with both the real `python-paillier` library and the plaintext stub
fallback that ships in homomorphic.py when phe is not installed.
"""

import pytest

from ml.fedshield_v3.homomorphic import (
    PaillierContext,
    SCALE_FACTOR,
    encrypt_weights,
    decrypt_weights,
    _PHE_AVAILABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_weights() -> dict:
    """Return a minimal weight dict matching FederatedAnomalyModel format."""
    return {
        "weights": {"feat_a": 0.75, "feat_b": -1.25},
        "means": {"feat_a": 10.5, "feat_b": 3.0},
        "stds": {"feat_a": 2.1, "feat_b": 0.8},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPaillierPHE:

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypt a weight dict, decrypt it, and verify the original values
        are recovered within floating-point tolerance."""
        ctx = PaillierContext(city_id="bengaluru-test")
        weights = _sample_weights()

        encrypted = encrypt_weights(weights, ctx.public_key)
        decrypted = decrypt_weights(encrypted, ctx.private_key)

        for param_key in weights:
            for feat_name in weights[param_key]:
                original = weights[param_key][feat_name]
                recovered = decrypted[param_key][feat_name]
                assert abs(recovered - original) < 1e-4, (
                    f"{param_key}.{feat_name}: expected {original}, got {recovered}"
                )

    def test_homomorphic_addition(self):
        """Encrypt(a) + Encrypt(b), decrypt result, verify equals a + b.

        Paillier supports additive homomorphism on ciphertext — this test
        verifies the property using two individual values encrypted with the
        same public key.
        """
        ctx = PaillierContext(city_id="hyderabad-test")

        a_val = 42.5
        b_val = 17.25
        expected_sum = a_val + b_val

        # Quantise and encrypt
        a_encoded = round(a_val * SCALE_FACTOR)
        b_encoded = round(b_val * SCALE_FACTOR)

        enc_a = ctx.public_key.encrypt(a_encoded)
        enc_b = ctx.public_key.encrypt(b_encoded)

        # Homomorphic addition on ciphertext
        enc_sum = enc_a + enc_b

        # Decrypt and de-quantise
        decrypted_sum = ctx.private_key.decrypt(enc_sum) / SCALE_FACTOR

        assert abs(decrypted_sum - expected_sum) < 1e-4, (
            f"Expected {expected_sum}, got {decrypted_sum}"
        )

    def test_encrypted_values_different(self):
        """Encrypt the same value twice and verify the ciphertexts differ.

        Paillier is a probabilistic encryption scheme — encrypting the same
        plaintext twice must produce different ciphertexts (semantic security).

        For the plaintext stub fallback, the ciphertexts are deterministic
        wrapper objects so we skip the inequality check in that case.
        """
        ctx = PaillierContext(city_id="mumbai-test")

        value = round(99.99 * SCALE_FACTOR)

        enc1 = ctx.public_key.encrypt(value)
        enc2 = ctx.public_key.encrypt(value)

        if _PHE_AVAILABLE:
            # Real Paillier: ciphertexts must differ
            assert enc1.ciphertext() != enc2.ciphertext(), (
                "Paillier ciphertexts for the same plaintext should differ "
                "(probabilistic encryption)."
            )
        else:
            # Plaintext stub: both decrypt to the same value (functional check)
            assert ctx.private_key.decrypt(enc1) == ctx.private_key.decrypt(enc2)
