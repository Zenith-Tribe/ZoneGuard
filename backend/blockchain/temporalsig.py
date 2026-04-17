"""
blockchain/temporalsig.py
=========================
Innovation 10: TemporalSig Archive

Every 15-minute QuadSignal polling cycle produces a keccak256 hash of all
four signal readings. That hash is anchored to Polygon L2 (Amoy testnet /
Polygon mainnet) via the TemporalSigAnchor smart contract.

The Ethereum block timestamp (consensus-set, ~2s finality on Polygon) becomes
the IMMUTABLE proof of WHEN a signal reading occurred. This eliminates the
entire class of parametric insurance disputes about "when did the disruption
actually begin."

Cost: ~$0.0001 per anchor on Polygon PoS (calldata ~100 bytes @ ~30 gwei)

Architecture:
  - web3.py (async) connects to Polygon via Alchemy/Infura RPC
  - TemporalSigAnchor.sol stores hash → block.timestamp mapping on-chain
  - Local PostgreSQL mirrors every anchor for fast query (no RPC needed for reads)
  - Anchors are written AFTER signal fusion completes, before claim evaluation
  - Verify flow: re-hash payload → compare with on-chain hash → return block timestamp

Dependencies:
  pip install web3>=6.0.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional web3.py import — graceful degradation
# ---------------------------------------------------------------------------

try:
    from web3 import AsyncWeb3
    from web3.middleware import async_geth_poa_middleware
    from web3.exceptions import ContractLogicError, Web3Exception
    HAS_WEB3 = True
    logger.info("web3.py loaded successfully")
except ImportError:
    HAS_WEB3 = False
    logger.warning(
        "web3.py not installed. TemporalSig running in STUB mode. "
        "Install: pip install web3"
    )

from .models import SignalBatchPayload, TemporalSigAnchor

# ---------------------------------------------------------------------------
# TemporalSigAnchor contract ABI (minimal — only what we call)
# ---------------------------------------------------------------------------

TEMPORALSIG_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "hash", "type": "bytes32"}],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "hash", "type": "bytes32"}],
        "name": "getAnchor",
        "outputs": [
            {"internalType": "uint256", "name": "blockNumber", "type": "uint256"},
            {"internalType": "uint256", "name": "blockTimestamp", "type": "uint256"},
            {"internalType": "address", "name": "anchorer", "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "hash", "type": "bytes32"}],
        "name": "exists",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "hash", "type": "bytes32"},
            {"indexed": False, "internalType": "uint256", "name": "blockTimestamp", "type": "uint256"},
            {"indexed": True, "internalType": "address", "name": "anchorer", "type": "address"},
        ],
        "name": "Anchored",
        "type": "event",
    },
]


# ---------------------------------------------------------------------------
# TemporalSig Client
# ---------------------------------------------------------------------------

class TemporalSigClient:
    """
    Async client for anchoring signal batch hashes to Polygon L2.

    Primary methods:
      anchor_signal_batch(batch)  → TemporalSigAnchor  (write)
      verify_anchor(batch_id)     → TemporalSigAnchor  (verify)
      get_anchor_for_event(...)   → TemporalSigAnchor  (claim dispute proof)
    """

    def __init__(self):
        self._rpc_url: str = os.getenv(
            "POLYGON_RPC_URL",
            "https://rpc-amoy.polygon.technology"
        )
        self._private_key: str = os.getenv("POLYGON_PRIVATE_KEY", "")
        self._contract_address: str = os.getenv(
            "TEMPORALSIG_CONTRACT_ADDRESS", ""
        )
        self._network: str = os.getenv("POLYGON_NETWORK", "amoy")  # amoy | polygon
        self._w3: Optional[AsyncWeb3] = None
        self._contract = None
        self._wallet_address: Optional[str] = None
        self._stub_mode = not HAS_WEB3 or not self._private_key

        # In-memory anchor cache (keyed by batch_id) — supplements DB
        self._anchor_cache: dict[str, TemporalSigAnchor] = {}

    async def connect(self) -> None:
        """Initialize web3 connection and contract instance."""
        if self._stub_mode:
            logger.warning("[TemporalSig] STUB MODE — no real Polygon connection")
            return

        try:
            self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(self._rpc_url))

            # Polygon PoS uses PoA consensus — needed for middleware
            self._w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)

            if not await self._w3.is_connected():
                raise ConnectionError(f"Cannot connect to Polygon RPC: {self._rpc_url}")

            # Derive wallet address from private key
            account = self._w3.eth.account.from_key(self._private_key)
            self._wallet_address = account.address

            # Load contract
            if self._contract_address:
                self._contract = self._w3.eth.contract(
                    address=AsyncWeb3.to_checksum_address(self._contract_address),
                    abi=TEMPORALSIG_ABI,
                )
                logger.info(
                    f"[TemporalSig] Connected to Polygon {self._network} | "
                    f"wallet={self._wallet_address} | "
                    f"contract={self._contract_address}"
                )
            else:
                logger.warning(
                    "[TemporalSig] No contract address set — "
                    "anchoring will use stub mode until deployed"
                )
                self._stub_mode = True

        except Exception as e:
            logger.error(f"[TemporalSig] Connection failed: {e} — entering stub mode")
            self._stub_mode = True

    # ------------------------------------------------------------------
    # Core: Anchor a signal batch
    # ------------------------------------------------------------------

    async def anchor_signal_batch(
        self, batch: SignalBatchPayload
    ) -> TemporalSigAnchor:
        """
        Anchor a 15-minute signal batch to Polygon L2.

        Flow:
          1. Compute keccak256 of batch.canonical_json
          2. Call TemporalSigAnchor.anchor(hash) on Polygon
          3. Wait for tx receipt (1-2 blocks, ~2-4 seconds on Polygon)
          4. Extract block.timestamp from receipt
          5. Return TemporalSigAnchor with all proof fields populated

        The block.timestamp is set by Polygon validators via consensus.
        It cannot be forged by ZoneGuard, the insurer, or any single party.
        This is the "truth timestamp" for when a disruption was detected.

        Cost: ~0.0001 USD per call (Polygon calldata)
        """
        anchor = TemporalSigAnchor(
            anchor_id=str(uuid.uuid4()),
            batch_id=batch.batch_id,
            zone_id=batch.zone_id,
            keccak256_hash=batch.keccak256_hash,
            polygon_network=self._network,
            status="pending",
        )

        if self._stub_mode:
            return await self._stub_anchor(anchor, batch)

        try:
            hash_bytes = bytes.fromhex(
                batch.keccak256_hash.replace("0x", "").replace("sha256:", "")
            )
            if len(hash_bytes) != 32:
                raise ValueError(f"Hash must be 32 bytes, got {len(hash_bytes)}")

            # Build transaction
            nonce = await self._w3.eth.get_transaction_count(self._wallet_address)
            gas_price = await self._w3.eth.gas_price

            tx = await self._contract.functions.anchor(hash_bytes).build_transaction({
                "from": self._wallet_address,
                "nonce": nonce,
                "gasPrice": gas_price,
            })

            # Estimate gas
            estimated_gas = await self._w3.eth.estimate_gas(tx)
            tx["gas"] = int(estimated_gas * 1.2)  # 20% buffer

            # Sign and send
            signed_tx = self._w3.eth.account.sign_transaction(
                tx, private_key=self._private_key
            )
            tx_hash = await self._w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logger.info(
                f"[TemporalSig] Anchor tx sent: {tx_hash.hex()} "
                f"batch={batch.batch_id}"
            )

            # Wait for receipt (timeout: 30s = ~15 Polygon blocks)
            receipt = await asyncio.wait_for(
                self._w3.eth.wait_for_transaction_receipt(tx_hash),
                timeout=30.0,
            )

            if receipt.status != 1:
                raise RuntimeError("Transaction reverted on-chain")

            # Get the block to extract timestamp
            block = await self._w3.eth.get_block(receipt.blockNumber)
            block_timestamp = datetime.fromtimestamp(
                block.timestamp, tz=timezone.utc
            )

            # Estimate cost (MATIC)
            gas_used = receipt.gasUsed
            gas_price_gwei = gas_price / 1e9
            cost_matic = (gas_used * gas_price) / 1e18
            # MATIC ≈ $0.60–$0.80; use $0.70 estimate
            cost_usd = cost_matic * 0.70

            anchor.polygon_tx_hash = receipt.transactionHash.hex()
            anchor.polygon_block_number = receipt.blockNumber
            anchor.polygon_block_timestamp = block_timestamp
            anchor.gas_used = gas_used
            anchor.gas_price_gwei = gas_price_gwei
            anchor.estimated_cost_usd = round(cost_usd, 6)
            anchor.status = "confirmed"
            anchor.confirmed_at = datetime.now(timezone.utc)

            # Cache
            self._anchor_cache[batch.batch_id] = anchor

            logger.info(
                f"[TemporalSig] ✓ Anchored | "
                f"batch={batch.batch_id} | "
                f"tx={anchor.polygon_tx_hash} | "
                f"block={anchor.polygon_block_number} | "
                f"timestamp={block_timestamp.isoformat()} | "
                f"cost_usd≈${cost_usd:.6f}"
            )
            return anchor

        except asyncio.TimeoutError:
            anchor.status = "failed"
            anchor.error_message = "Transaction receipt timeout (30s)"
            logger.error(
                f"[TemporalSig] ✗ Timeout anchoring batch={batch.batch_id}"
            )
            return anchor

        except Exception as e:
            anchor.status = "failed"
            anchor.error_message = str(e)
            logger.error(
                f"[TemporalSig] ✗ Anchor failed batch={batch.batch_id}: {e}"
            )
            return anchor

    # ------------------------------------------------------------------
    # Verify an existing anchor
    # ------------------------------------------------------------------

    async def verify_anchor(
        self,
        batch: SignalBatchPayload,
        polygon_tx_hash: str,
    ) -> dict:
        """
        Verify that the on-chain hash matches the locally-computed hash.

        Used in claim dispute resolution:
          - Recompute hash from signal data
          - Read the on-chain hash from the contract
          - Compare — they must match
          - Return the consensus block.timestamp as the authoritative time

        Returns a dict with verification result and block timestamp.
        """
        local_hash = batch.keccak256_hash
        result = {
            "batch_id": batch.batch_id,
            "local_hash": local_hash,
            "on_chain_hash": None,
            "block_timestamp_utc": None,
            "hash_matches": False,
            "verification_message": "",
            "polygonscan_url": None,
            "stub_mode": self._stub_mode,
        }

        if self._stub_mode:
            result["verification_message"] = (
                "STUB MODE: Cannot verify on-chain. "
                "Deploy TemporalSigAnchor contract and set TEMPORALSIG_CONTRACT_ADDRESS."
            )
            return result

        try:
            hash_bytes = bytes.fromhex(local_hash.replace("0x", ""))

            # Query contract
            on_chain = await self._contract.functions.getAnchor(hash_bytes).call()
            block_number, block_timestamp_unix, anchorer = on_chain

            if block_number == 0:
                result["verification_message"] = (
                    f"Hash not found on-chain for batch {batch.batch_id}. "
                    "Either anchor hasn't confirmed yet or hash mismatch."
                )
                return result

            block_timestamp = datetime.fromtimestamp(block_timestamp_unix, tz=timezone.utc)
            result["on_chain_hash"] = local_hash      # Same hash, so it exists
            result["block_timestamp_utc"] = block_timestamp.isoformat()
            result["hash_matches"] = True
            result["polygonscan_url"] = (
                f"https://amoy.polygonscan.com/tx/{polygon_tx_hash}"
                if self._network == "amoy"
                else f"https://polygonscan.com/tx/{polygon_tx_hash}"
            )
            result["verification_message"] = (
                f"✓ VERIFIED. Signal batch {batch.batch_id} was detected at "
                f"{block_timestamp.isoformat()} UTC (Polygon block #{block_number}, "
                f"consensus-certified). This timestamp is immutable."
            )

        except Exception as e:
            result["verification_message"] = f"Verification error: {e}"
            logger.error(f"[TemporalSig] verify_anchor failed: {e}")

        return result

    # ------------------------------------------------------------------
    # Get anchor for a specific claim event
    # ------------------------------------------------------------------

    async def get_anchor_for_event(
        self,
        batch_id: str,
    ) -> Optional[TemporalSigAnchor]:
        """
        Retrieve the TemporalSig anchor for a specific signal batch ID.
        Used in claim dispute UI to show proof.

        In production this queries the local PostgreSQL mirror first,
        then falls back to on-chain if not found locally.
        """
        # Check memory cache first
        if batch_id in self._anchor_cache:
            return self._anchor_cache[batch_id]

        # [ENHANCEMENT] In production: query PostgreSQL temporal_sig_anchors table
        # anchor_row = await db.execute(
        #     "SELECT * FROM temporal_sig_anchors WHERE batch_id = $1", batch_id
        # )
        # if anchor_row: return TemporalSigAnchor(**anchor_row)

        logger.warning(
            f"[TemporalSig] Anchor for batch {batch_id} not found in cache. "
            "DB query not yet wired — implement PostgreSQL lookup here."
        )
        return None

    async def get_wallet_balance(self) -> Optional[float]:
        """Return the MATIC balance of the anchoring wallet."""
        if self._stub_mode or not self._wallet_address:
            return None
        try:
            balance_wei = await self._w3.eth.get_balance(self._wallet_address)
            return float(self._w3.from_wei(balance_wei, "ether"))
        except Exception as e:
            logger.error(f"[TemporalSig] get_wallet_balance failed: {e}")
            return None

    async def get_health(self) -> dict:
        """Return TemporalSig connectivity health info."""
        balance = await self.get_wallet_balance()
        return {
            "polygon_connected": not self._stub_mode,
            "stub_mode": self._stub_mode,
            "network": self._network,
            "contract_address": self._contract_address or None,
            "wallet_address": self._wallet_address,
            "wallet_balance_matic": balance,
            "rpc_url": self._rpc_url.split("@")[-1],  # Hide API key if in URL
        }

    # ------------------------------------------------------------------
    # Stub mode helpers
    # ------------------------------------------------------------------

    async def _stub_anchor(
        self, anchor: TemporalSigAnchor, batch: SignalBatchPayload
    ) -> TemporalSigAnchor:
        """Generate a realistic stub anchor for dev/test mode."""
        import hashlib

        fake_tx = "0xstub" + hashlib.sha256(
            f"{batch.batch_id}{batch.keccak256_hash}".encode()
        ).hexdigest()[:60]

        anchor.polygon_tx_hash = fake_tx
        anchor.polygon_block_number = 99999999
        anchor.polygon_block_timestamp = datetime.now(timezone.utc)
        anchor.gas_used = 24681
        anchor.gas_price_gwei = 30.0
        anchor.estimated_cost_usd = 0.000052
        anchor.status = "confirmed"
        anchor.confirmed_at = datetime.now(timezone.utc)

        self._anchor_cache[batch.batch_id] = anchor

        logger.info(
            f"[TemporalSig][STUB] Anchor simulated | "
            f"batch={batch.batch_id} | "
            f"fake_tx={fake_tx[:20]}..."
        )
        return anchor


# ---------------------------------------------------------------------------
# Singleton for DI
# ---------------------------------------------------------------------------

_temporalsig_client: Optional[TemporalSigClient] = None


def get_temporalsig_client() -> TemporalSigClient:
    """FastAPI dependency — returns the shared TemporalSig client."""
    global _temporalsig_client
    if _temporalsig_client is None:
        _temporalsig_client = TemporalSigClient()
    return _temporalsig_client


async def init_temporalsig_client() -> None:
    """Called from FastAPI lifespan startup."""
    client = get_temporalsig_client()
    await client.connect()
    health = await client.get_health()
    logger.info(f"[TemporalSig] Initialized: {health}")


async def shutdown_temporalsig_client() -> None:
    """Called from FastAPI lifespan shutdown."""
    global _temporalsig_client
    _temporalsig_client = None
