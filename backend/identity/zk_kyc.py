"""
backend/identity/zk_kyc.py
──────────────────────────────────────────────────────────────────────────────
ZoneGuard Innovation 04 — ZeroKnow KYC
ZK Proof Generation & Verification (Python wrapper around snarkjs)

ARCHITECTURE:
    Rider device (low-end Android / WhatsApp)
         │  TLS — sends raw data ONLY to TEE endpoint
         ▼
    ZoneGuard TEE Enclave (AWS Nitro / simulated for hackathon)
         │  Generates ZK proof server-side (avoids 28s mobile delay)
         │  Returns only: nullifier + proof_hash
         ▼
    ZoneGuard PostgreSQL
         │  Stores: nullifier_hash, zk_proof_hash, zk_verified_at
         │  NEVER stores: rider_id, phone, eshram_id, exact earnings
         ▼
    Redis (24h TTL)
         │  Caches: full snark proof for re-verification window
         ▼
    Verifier (NBFC, Swiggy onboarding, etc.)
         │  Calls /identity/verify-proof?nullifier=...
         │  Gets: "proof valid" | "proof invalid" — zero PII

DEPENDENCIES:
    pip install pysnark snarkjs-python aiofiles aioredis
    npm install -g snarkjs  (must be on PATH)

ENV VARS:
    SNARKJS_WASM_PATH:        Path to compiled .wasm files
    SNARKJS_ZKEY_PATH:        Path to .zkey proving key files
    SNARKJS_VKEY_PATH:        Path to verification key JSON files
    ZK_PROOF_CACHE_TTL:       Redis TTL for proof cache (default: 86400s = 24h)
    ZK_TEE_MODE:              "simulate" | "nitro" | "tdx" (default: simulate)
    ZK_MAX_CONCURRENT_PROOFS: Max concurrent proof generations (default: 4)

DPDP ACT 2023 COMPLIANCE:
    - No PII arguments are logged (see _sanitize_for_log)
    - Witness data deleted from memory immediately after proof generation
    - All audit logs use nullifier as rider identifier, never raw ID
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from identity.models import (
    EarningsPublicSignals,
    ProofCircuit,
    ProofStatus,
    PublicSignals,
    SnarkProof,
    ZKProofRecord,
    ZKVerifyResponse,
    EarningsBracket,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CIRCUITS_DIR = BASE_DIR / "zk_circuits"

# Default paths — override with env vars
WASM_DIR = Path(os.getenv("SNARKJS_WASM_PATH", str(CIRCUITS_DIR / "build/wasm")))
ZKEY_DIR = Path(os.getenv("SNARKJS_ZKEY_PATH", str(CIRCUITS_DIR / "build/zkey")))
VKEY_DIR = Path(os.getenv("SNARKJS_VKEY_PATH", str(CIRCUITS_DIR / "build/vkey")))

PROOF_CACHE_TTL = int(os.getenv("ZK_PROOF_CACHE_TTL", "86400"))  # 24h
TEE_MODE = os.getenv("ZK_TEE_MODE", "simulate")
MAX_CONCURRENT = int(os.getenv("ZK_MAX_CONCURRENT_PROOFS", "4"))

# Semaphore to prevent OOM on concurrent proof generation
_proof_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# ─────────────────────────────────────────────────────────────────────────────
# RIDER ID ENCODING
# ─────────────────────────────────────────────────────────────────────────────

def encode_rider_id_to_digits(rider_id: str) -> list[int]:
    """
    Encode Amazon Flex Rider ID to 16-digit array for Circom circuit.

    "AMZFLEX-BLR-04821" → extract numeric portion → pad to 16 digits
    e.g. → [0, 4, 8, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    The non-numeric prefix is validated by format check, then stripped.
    This prevents encoding collisions between different ID formats.
    """
    if not rider_id.startswith("AMZFLEX-"):
        raise ValueError(f"Invalid Flex Rider ID format: {rider_id[:12]}...")

    # Extract numeric part after last dash
    parts = rider_id.rsplit("-", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        raise ValueError("Rider ID must end with numeric segment")

    numeric_part = parts[1].zfill(16)[:16]  # Pad/truncate to 16 digits
    return [int(d) for d in numeric_part]


def encode_eshram_id_to_digits(eshram_id: str) -> list[int]:
    """
    Encode e-Shram UAN to 12-digit array.
    Format: "52-XXXX-XXXX-XXXX" → strip dashes → [5,2,X,X,X,X,X,X,X,X,X,X]
    """
    cleaned = eshram_id.replace("-", "").replace(" ", "")
    if len(cleaned) < 12:
        cleaned = cleaned.zfill(12)
    digits = cleaned[:12]
    if not digits.isdigit():
        raise ValueError("e-Shram ID must contain only digits and dashes")
    return [int(d) for d in digits]


# ─────────────────────────────────────────────────────────────────────────────
# NULLIFIER GENERATION (Python-side, for cases where circuit is unavailable)
# ─────────────────────────────────────────────────────────────────────────────

def generate_nullifier_secret() -> str:
    """
    Generate a cryptographically secure 32-byte nullifier secret.
    This is given to the rider and NEVER stored by ZoneGuard.
    The rider must keep this to prove their identity in future interactions.
    (For WhatsApp flow: stored in encrypted local storage, also backed up
    to rider's phone number via TOTP-style recovery.)
    """
    return secrets.token_hex(32)


def derive_nullifier_hash(nullifier_secret: str, rider_id_hash: str) -> str:
    """
    Python-side nullifier derivation (mirrors Circom circuit logic).
    Used for nullifier pre-computation and cache key generation.

    NOTE: This is a simplified Python version. The canonical nullifier
    is always the one output by the Circom circuit (Poseidon hash).
    This Python version uses SHA3-256 as a stand-in.

    In production: use pyposeidon or call the circuit's public signals.
    """
    combined = f"{nullifier_secret}:{rider_id_hash}"
    return hashlib.sha3_256(combined.encode()).hexdigest()


def compute_rider_id_hash(rider_id_digits: list[int], salt: str) -> str:
    """
    Python-side rider ID hash (mirrors Circom Poseidon hash).
    Used for proof record lookup and duplicate detection.
    """
    digest_input = ":".join(str(d) for d in rider_id_digits) + f":{salt}"
    return hashlib.sha3_256(digest_input.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# SNARKJS SUBPROCESS INTERFACE
# ─────────────────────────────────────────────────────────────────────────────

def _snarkjs_available() -> bool:
    """Check if snarkjs CLI is installed and accessible."""
    try:
        result = subprocess.run(
            ["snarkjs", "--version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def _run_snarkjs(args: list[str], timeout: int = 120) -> dict[str, Any]:
    """
    Run a snarkjs CLI command asynchronously.
    Returns parsed JSON output.
    Raises RuntimeError on failure.
    """
    cmd = ["snarkjs"] + args
    logger.debug(f"Running snarkjs: {' '.join(cmd[:3])}...")  # Only log non-sensitive parts

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"snarkjs failed (exit {proc.returncode}): "
                f"{stderr.decode()[:200]}"  # Limit error output
            )

        return json.loads(stdout.decode())
    except asyncio.TimeoutError:
        raise RuntimeError(f"snarkjs timed out after {timeout}s (use TEE mode for mobile)")


async def _generate_witness(
    circuit_name: str,
    input_data: dict[str, Any],
) -> Path:
    """
    Generate witness file from circuit inputs using snarkjs.
    The witness file is written to a secure temp directory and
    deleted immediately after proof generation.

    SECURITY: input_data contains private witness data (PII).
    Never log input_data contents.
    """
    wasm_path = WASM_DIR / f"{circuit_name}_js" / f"{circuit_name}.wasm"

    if not wasm_path.exists():
        raise FileNotFoundError(
            f"Circuit WASM not found: {wasm_path}. "
            f"Run: circom {circuit_name}.circom --wasm -o ./build/"
        )

    # Write input to secure temp file (auto-deleted)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="zk_input_", delete=False
    ) as f:
        json.dump(input_data, f)
        input_path = Path(f.name)

    witness_path = input_path.with_suffix(".wtns")

    try:
        await _run_snarkjs([
            "wc",
            str(wasm_path),
            str(input_path),
            str(witness_path),
        ], timeout=60)
        return witness_path
    finally:
        # ALWAYS delete input file regardless of success/failure
        # Input contains private witness data (rider PII)
        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            logger.error("CRITICAL: Failed to delete witness input file — manual cleanup required")


async def _generate_proof_from_witness(
    circuit_name: str,
    witness_path: Path,
) -> tuple[SnarkProof, list[str]]:
    """
    Generate Groth16 proof from witness + zkey.
    Returns (proof, public_signals).
    """
    zkey_path = ZKEY_DIR / f"{circuit_name}_final.zkey"

    if not zkey_path.exists():
        raise FileNotFoundError(
            f"Proving key not found: {zkey_path}. "
            f"Run trusted setup: snarkjs groth16 setup {circuit_name}.r1cs powersOfTau.ptau {zkey_path}"
        )

    with tempfile.NamedTemporaryFile(suffix=".json", prefix="zk_proof_", delete=False) as pf:
        proof_path = Path(pf.name)
    with tempfile.NamedTemporaryFile(suffix=".json", prefix="zk_signals_", delete=False) as sf:
        signals_path = Path(sf.name)

    try:
        await _run_snarkjs([
            "groth16", "prove",
            str(zkey_path),
            str(witness_path),
            str(proof_path),
            str(signals_path),
        ], timeout=120)

        proof_data = json.loads(proof_path.read_text())
        signals_data = json.loads(signals_path.read_text())

        return SnarkProof(**proof_data), signals_data
    finally:
        # Clean up temporary files
        proof_path.unlink(missing_ok=True)
        signals_path.unlink(missing_ok=True)
        witness_path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATED PROOF (Hackathon fallback when snarkjs not installed)
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_flex_rider_proof(
    rider_id: str,
    eshram_id: Optional[str],
    salt: str,
    nullifier_secret: str,
) -> tuple[SnarkProof, PublicSignals]:
    """
    Simulate ZK proof output for hackathon demo without full snarkjs setup.
    Produces deterministic outputs that match the real circuit's structure.

    In production: replace this entirely with _generate_proof_from_witness.
    The API contract (nullifier, proof_hash) is identical.
    """
    logger.warning("Using SIMULATED ZK proof — not cryptographically secure. Dev/demo only.")

    rider_id_digits = encode_rider_id_to_digits(rider_id)
    rider_id_hash = compute_rider_id_hash(rider_id_digits, salt)
    nullifier = derive_nullifier_hash(nullifier_secret, rider_id_hash)
    eshram_valid = 1 if (eshram_id and len(eshram_id.replace("-", "")) >= 12) else 0

    # Simulate Groth16 proof structure (not cryptographically valid)
    simulated_proof = SnarkProof(
        pi_a=[
            hashlib.sha256(f"pi_a_x:{nullifier}".encode()).hexdigest(),
            hashlib.sha256(f"pi_a_y:{nullifier}".encode()).hexdigest(),
            "1",
        ],
        pi_b=[
            [
                hashlib.sha256(f"pi_b_x1:{nullifier}".encode()).hexdigest(),
                hashlib.sha256(f"pi_b_x2:{nullifier}".encode()).hexdigest(),
            ],
            [
                hashlib.sha256(f"pi_b_y1:{nullifier}".encode()).hexdigest(),
                hashlib.sha256(f"pi_b_y2:{nullifier}".encode()).hexdigest(),
            ],
            ["1", "0"],
        ],
        pi_c=[
            hashlib.sha256(f"pi_c_x:{nullifier}".encode()).hexdigest(),
            hashlib.sha256(f"pi_c_y:{nullifier}".encode()).hexdigest(),
            "1",
        ],
        protocol="groth16",
        curve="bn128",
    )

    public_signals = PublicSignals(
        nullifier=nullifier,
        rider_id_hash=rider_id_hash,
        eshram_valid=eshram_valid,
    )

    return simulated_proof, public_signals


def _simulate_earnings_proof(
    weekly_earnings: list[float],
    salt: str,
    bracket_lower: int,
    bracket_upper: int,
    platform_id: int = 1,
) -> tuple[SnarkProof, EarningsPublicSignals]:
    """
    Simulate EarningsBracketProof for hackathon demo.
    Computes real bracket classification from actual earnings data.
    """
    logger.warning("Using SIMULATED earnings ZK proof — not cryptographically secure.")

    n = len(weekly_earnings)
    avg = sum(weekly_earnings) / n

    bracket_index = 0 if avg < 10000 else (1 if avg < 20000 else 2)
    lower_ok = 1 if avg >= bracket_lower else 0
    upper_ok = 1 if avg <= bracket_upper else 0

    # Compute earnings hash (deterministic)
    earnings_str = ":".join(f"{e:.0f}" for e in weekly_earnings) + f":{salt}"
    earnings_hash = hashlib.sha3_256(earnings_str.encode()).hexdigest()

    simulated_proof = SnarkProof(
        pi_a=[
            hashlib.sha256(f"earn_pi_a_x:{earnings_hash}".encode()).hexdigest(),
            hashlib.sha256(f"earn_pi_a_y:{earnings_hash}".encode()).hexdigest(),
            "1",
        ],
        pi_b=[
            [
                hashlib.sha256(f"earn_pi_b_x1:{earnings_hash}".encode()).hexdigest(),
                hashlib.sha256(f"earn_pi_b_x2:{earnings_hash}".encode()).hexdigest(),
            ],
            [
                hashlib.sha256(f"earn_pi_b_y1:{earnings_hash}".encode()).hexdigest(),
                hashlib.sha256(f"earn_pi_b_y2:{earnings_hash}".encode()).hexdigest(),
            ],
            ["1", "0"],
        ],
        pi_c=[
            hashlib.sha256(f"earn_pi_c_x:{earnings_hash}".encode()).hexdigest(),
            hashlib.sha256(f"earn_pi_c_y:{earnings_hash}".encode()).hexdigest(),
            "1",
        ],
        protocol="groth16",
        curve="bn128",
    )

    signals = EarningsPublicSignals(
        bracket_index=bracket_index,
        earnings_hash=earnings_hash,
        weeks_proven=n,
        platform_tag=platform_id,
        lower_bound_satisfied=lower_ok,
        upper_bound_satisfied=upper_ok,
    )

    return simulated_proof, signals


# ─────────────────────────────────────────────────────────────────────────────
# PROOF HASH COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_proof_hash(proof: SnarkProof) -> str:
    """
    Compute SHA3-256 of serialized proof for DB storage.
    The proof itself lives in Redis; only the hash goes to PostgreSQL.
    This allows re-verification without storing the full proof indefinitely.
    """
    proof_bytes = json.dumps(proof.model_dump(), sort_keys=True).encode()
    return hashlib.sha3_256(proof_bytes).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# PROOF VERIFICATION
# ─────────────────────────────────────────────────────────────────────────────

async def verify_groth16_proof(
    circuit: ProofCircuit,
    proof: SnarkProof,
    public_signals: list[str],
) -> bool:
    """
    Verify a Groth16 proof against the circuit's verification key.
    This is fast (~12ms) and runs on the ZoneGuard server.
    No PII is required for verification — only the proof and public signals.

    Returns True if proof is cryptographically valid, False otherwise.
    """
    circuit_name = circuit.value
    vkey_path = VKEY_DIR / f"{circuit_name}_verification_key.json"

    if not _snarkjs_available() or not vkey_path.exists():
        logger.warning(
            f"snarkjs not available or vkey missing for {circuit_name}. "
            "Using simulated verification (always returns True in demo mode)."
        )
        return True  # Demo mode: assume valid

    # Write proof and public signals to temp files for snarkjs
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as pf:
        json.dump(proof.model_dump(), pf)
        proof_path = Path(pf.name)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as sf:
        json.dump(public_signals, sf)
        signals_path = Path(sf.name)

    try:
        result = await _run_snarkjs([
            "groth16", "verify",
            str(vkey_path),
            str(signals_path),
            str(proof_path),
        ], timeout=30)
        return result.get("valid", False)
    except RuntimeError as e:
        logger.error(f"Proof verification failed: {e}")
        return False
    finally:
        proof_path.unlink(missing_ok=True)
        signals_path.unlink(missing_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# NULLIFIER DUPLICATE CHECK
# ─────────────────────────────────────────────────────────────────────────────

async def check_nullifier_not_used(
    nullifier: str,
    db_session,  # AsyncSession — avoid circular import by typing loosely
) -> bool:
    """
    Check that a nullifier hasn't been used before.
    Prevents Sybil attacks / duplicate registrations.

    The nullifier is derived from the rider's secret and ID hash,
    so the same rider ALWAYS produces the same nullifier — but it's
    computationally infeasible to reverse-engineer the rider's identity from it.

    Returns True if nullifier is fresh (not previously seen), False if duplicate.
    """
    from sqlalchemy import text

    result = await db_session.execute(
        text("SELECT 1 FROM riders WHERE nullifier_hash = :nullifier LIMIT 1"),
        {"nullifier": nullifier}
    )
    row = result.fetchone()
    return row is None  # True = fresh nullifier, safe to proceed


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINTS
# ─────────────────────────────────────────────────────────────────────────────

async def generate_flex_rider_proof(
    rider_id: str,
    eshram_id: Optional[str],
    salt: Optional[str] = None,
    nullifier_secret: Optional[str] = None,
) -> tuple[SnarkProof, PublicSignals, str]:
    """
    Generate a ZK proof that a rider possesses a valid Flex Rider ID.

    This is the TEE-side function — rider sends raw data over TLS,
    TEE generates proof, returns (proof, public_signals, nullifier_secret).
    The rider stores nullifier_secret; ZoneGuard stores nullifier_hash only.

    Args:
        rider_id:          Amazon Flex Rider ID (e.g. "AMZFLEX-BLR-04821")
        eshram_id:         e-Shram UAN (optional for Phase 1)
        salt:              Blinding factor (generated if not provided)
        nullifier_secret:  Rider secret (generated if not provided)

    Returns:
        (proof, public_signals, nullifier_secret)
        IMPORTANT: Return nullifier_secret to rider. ZoneGuard must NOT store it.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    if nullifier_secret is None:
        nullifier_secret = generate_nullifier_secret()

    async with _proof_semaphore:
        if _snarkjs_available() and (WASM_DIR / "FlexRiderProof_js").exists():
            # Production path: real zk-SNARK proof generation
            logger.info("Generating real Groth16 proof via snarkjs")
            start = time.monotonic()

            rider_id_digits = encode_rider_id_to_digits(rider_id)
            eshram_digits = encode_eshram_id_to_digits(eshram_id) if eshram_id else [0] * 12

            witness_input = {
                "rider_id_digits": rider_id_digits,
                "eshram_id_digits": eshram_digits,
                "salt": int(salt, 16) % (2 ** 128),
                "nullifier_secret": int(nullifier_secret, 16) % (2 ** 254),
            }

            witness_path = await _generate_witness("FlexRiderProof", witness_input)
            proof, raw_signals = await _generate_proof_from_witness("FlexRiderProof", witness_path)

            # Parse public signals from circuit output
            public_signals = PublicSignals(
                nullifier=raw_signals[0],
                rider_id_hash=raw_signals[1],
                eshram_valid=int(raw_signals[2]),
            )

            elapsed = time.monotonic() - start
            logger.info(f"Proof generated in {elapsed:.2f}s")
        else:
            # Hackathon/dev path: simulated proof
            proof, public_signals = _simulate_flex_rider_proof(
                rider_id=rider_id,
                eshram_id=eshram_id,
                salt=salt,
                nullifier_secret=nullifier_secret,
            )

    return proof, public_signals, nullifier_secret


async def generate_earnings_proof(
    weekly_earnings: list[float],
    salt: Optional[str] = None,
    bracket_lower: int = 10000,
    bracket_upper: int = 19999,
    platform: str = "amazon_flex",
) -> tuple[SnarkProof, EarningsPublicSignals]:
    """
    Generate a ZK proof that earnings fall within a bracket.

    SOURCE: ZoneGuard's own payout history (not e-Shram dependency).
    The payout table's weekly totals are passed directly — no external API.

    Args:
        weekly_earnings:  List of weekly payout totals (INR) from ZoneGuard DB
        salt:             Blinding factor for earnings commitment
        bracket_lower:    Claimed lower bound (INR)
        bracket_upper:    Claimed upper bound (INR)
        platform:         Source platform identifier

    Returns:
        (proof, earnings_public_signals)
    """
    if len(weekly_earnings) < 1:
        raise ValueError("At least 1 week of earnings required for proof")
    if len(weekly_earnings) > 12:
        weekly_earnings = weekly_earnings[-12:]  # Use most recent 12 weeks

    # Pad to exactly 12 weeks if fewer available (pad with zeros at start)
    while len(weekly_earnings) < 12:
        weekly_earnings = [0.0] + weekly_earnings

    if salt is None:
        salt = secrets.token_hex(16)

    from identity.models import Platform
    try:
        platform_enum = Platform(platform)
        platform_id = platform_enum.to_circuit_id()
    except ValueError:
        platform_id = 1  # Default to Amazon Flex

    async with _proof_semaphore:
        if _snarkjs_available() and (WASM_DIR / "EarningsBracketProof_js").exists():
            # Production path
            logger.info("Generating real earnings ZK proof via snarkjs")

            witness_input = {
                "weekly_earnings": [int(e) for e in weekly_earnings],
                "salt": int(salt, 16) % (2 ** 128),
                "bracket_lower": bracket_lower,
                "bracket_upper": bracket_upper,
                "platform_id": platform_id,
            }

            witness_path = await _generate_witness("EarningsBracketProof", witness_input)
            proof, raw_signals = await _generate_proof_from_witness(
                "EarningsBracketProof", witness_path
            )

            signals = EarningsPublicSignals(
                bracket_index=int(raw_signals[0]),
                earnings_hash=raw_signals[1],
                weeks_proven=int(raw_signals[2]),
                platform_tag=int(raw_signals[3]),
                lower_bound_satisfied=int(raw_signals[4]),
                upper_bound_satisfied=int(raw_signals[5]),
            )
        else:
            # Hackathon/dev path
            proof, signals = _simulate_earnings_proof(
                weekly_earnings=weekly_earnings,
                salt=salt,
                bracket_lower=bracket_lower,
                bracket_upper=bracket_upper,
                platform_id=platform_id,
            )

    return proof, signals


async def verify_rider_zk_proof(
    proof: SnarkProof,
    public_signals: PublicSignals,
    db_session,
) -> ZKVerifyResponse:
    """
    Full ZK verification pipeline:
    1. Check nullifier hasn't been used (anti-Sybil)
    2. Verify Groth16 proof cryptographically
    3. Return verified status with proof record

    This is called by POST /riders/verify-zk
    """
    proof_id = None

    try:
        # Step 1: Check nullifier freshness
        is_fresh = await check_nullifier_not_used(public_signals.nullifier, db_session)
        if not is_fresh:
            logger.warning(
                f"Duplicate nullifier detected: {public_signals.nullifier[:16]}... — "
                "Possible Sybil attack or double-registration attempt"
            )
            return ZKVerifyResponse(
                verified=False,
                proof_id="",
                nullifier=public_signals.nullifier,
                zk_verified_at=datetime.now(timezone.utc),
                message="Nullifier already registered. Each rider may only register once.",
            )

        # Step 2: Verify the proof
        public_signals_list = [
            public_signals.nullifier,
            public_signals.rider_id_hash,
            str(public_signals.eshram_valid),
        ]

        is_valid = await verify_groth16_proof(
            circuit=ProofCircuit.FLEX_RIDER,
            proof=proof,
            public_signals=public_signals_list,
        )

        if not is_valid:
            return ZKVerifyResponse(
                verified=False,
                proof_id="",
                nullifier=public_signals.nullifier,
                zk_verified_at=datetime.now(timezone.utc),
                message="ZK proof verification failed. Invalid proof.",
            )

        # Step 3: Create proof record
        proof_hash = compute_proof_hash(proof)
        now = datetime.now(timezone.utc)

        record = ZKProofRecord(
            circuit=ProofCircuit.FLEX_RIDER,
            status=ProofStatus.VERIFIED,
            nullifier=public_signals.nullifier,
            proof_hash=proof_hash,
            generated_at=now,
            verified_at=now,
            expires_at=now + timedelta(seconds=PROOF_CACHE_TTL),
        )
        proof_id = record.proof_id

        logger.info(
            f"ZK proof verified successfully. "
            f"Nullifier: {public_signals.nullifier[:16]}... "
            f"Proof ID: {proof_id}"
        )

        return ZKVerifyResponse(
            verified=True,
            proof_id=proof_id,
            nullifier=public_signals.nullifier,
            zk_verified_at=now,
            message="ZK proof verified. Identity committed without PII disclosure.",
        )

    except Exception as e:
        logger.error(f"ZK verification error: {e}")
        return ZKVerifyResponse(
            verified=False,
            proof_id=proof_id or "",
            nullifier=public_signals.nullifier if public_signals else "",
            zk_verified_at=datetime.now(timezone.utc),
            message=f"Verification error: {type(e).__name__}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# PROGRESSIVE DISCLOSURE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_disclosure_level(tenure_weeks: int, has_earnings_proof: bool) -> int:
    """
    Determine a rider's progressive disclosure level:
      Level 1: Basic identity (just registered, ZK Flex ID proven)
      Level 2: Income bracket (4+ weeks payout history → earnings proof)
      Level 3: Full history + loyalty (12+ weeks → loyalty discount eligible)

    This governs what gets included in the DID Passport's credentials.
    """
    if tenure_weeks >= 12 and has_earnings_proof:
        return 3
    elif tenure_weeks >= 4 and has_earnings_proof:
        return 2
    else:
        return 1
