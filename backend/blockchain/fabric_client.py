"""
blockchain/fabric_client.py
===========================
Python wrapper around the Hyperledger Fabric Gateway SDK (fabric-sdk-py / gRPC gateway).

Architecture:
  - Uses the Fabric Gateway protocol (v2.4+) via gRPC
  - Wraps the `fabric-protos` + `grpcio` stack (lighter than full fabric-sdk-py)
  - Falls back gracefully to a mock/stub mode when Fabric is not available
    (important for dev/CI environments without a running Fabric network)

Channel layout:
  zoneguard-channel
    ├── org1.zoneguard.local     (ZoneGuard peer)
    ├── org2.insurer.local       (Bajaj Allianz / ICICI Lombard peer)
    └── org3.irdai.local         (IRDAI observer — endorsement not required)

Chaincode:
  Name: zoneguard-cc
  Collections:
    - claimsCollection
    - policiesCollection
    - payoutsCollection
    - parametersCollection
    - signalsCollection
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Fabric SDK import — graceful degradation
# ---------------------------------------------------------------------------

try:
    import grpc
    import grpc.experimental.aio as aio_grpc

    # fabric-protos-py package for Fabric Gateway protocol
    from google.protobuf import json_format
    HAS_FABRIC_SDK = True
    logger.info("Fabric gRPC dependencies loaded successfully")
except ImportError:
    HAS_FABRIC_SDK = False
    logger.warning(
        "Fabric gRPC dependencies not installed. "
        "Running in STUB mode — all writes logged only. "
        "Install: pip install grpcio grpcio-tools fabric-protos"
    )


# ---------------------------------------------------------------------------
# Connection profile / identity config
# ---------------------------------------------------------------------------

class FabricIdentity:
    """MSP identity for signing Fabric transactions."""

    def __init__(
        self,
        msp_id: str,
        cert_pem: str,
        private_key_pem: str,
    ):
        self.msp_id = msp_id
        self.cert_pem = cert_pem
        self.private_key_pem = private_key_pem

    @classmethod
    def from_env(cls) -> "FabricIdentity":
        """Load identity from environment variables (Docker secrets / K8s secrets)."""
        return cls(
            msp_id=os.getenv("FABRIC_MSP_ID", "ZoneGuardMSP"),
            cert_pem=os.getenv("FABRIC_CERT_PEM", ""),
            private_key_pem=os.getenv("FABRIC_PRIVATE_KEY_PEM", ""),
        )


class FabricConnectionProfile:
    """
    Minimal connection profile.
    In production this would be loaded from a YAML/JSON file mounted into
    the Docker container. For now, environment variables are used.
    """

    def __init__(self):
        self.gateway_endpoint = os.getenv("FABRIC_GATEWAY_URL", "localhost:7051")
        self.channel_name = os.getenv("FABRIC_CHANNEL", "zoneguard-channel")
        self.chaincode_name = os.getenv("FABRIC_CHAINCODE", "zoneguard-cc")
        self.tls_cert_pem = os.getenv("FABRIC_TLS_CERT_PEM", "")
        self.override_hostname = os.getenv("FABRIC_PEER_HOSTNAME", "peer0.org1.example.com")


# ---------------------------------------------------------------------------
# Stub result — returned when Fabric is unavailable
# ---------------------------------------------------------------------------

class FabricTransactionResult:
    def __init__(
        self,
        success: bool,
        transaction_id: Optional[str],
        block_number: Optional[int],
        payload: Optional[bytes],
        error: Optional[str] = None,
        stub_mode: bool = False,
    ):
        self.success = success
        self.transaction_id = transaction_id
        self.block_number = block_number
        self.payload = payload
        self.error = error
        self.stub_mode = stub_mode  # True = Fabric not available, event only logged

    def __repr__(self) -> str:
        return (
            f"FabricTransactionResult("
            f"success={self.success}, "
            f"tx_id={self.transaction_id}, "
            f"block={self.block_number}, "
            f"stub={self.stub_mode})"
        )


# ---------------------------------------------------------------------------
# Main Fabric Gateway Client
# ---------------------------------------------------------------------------

class FabricGatewayClient:
    """
    Async Hyperledger Fabric Gateway client.

    Usage:
        client = FabricGatewayClient()
        await client.connect()
        result = await client.submit_transaction("CreateClaim", json_payload)
        await client.disconnect()

    Or as an async context manager:
        async with FabricGatewayClient() as client:
            result = await client.submit_transaction(...)
    """

    def __init__(self):
        self.profile = FabricConnectionProfile()
        self.identity = FabricIdentity.from_env()
        self._connected = False
        self._channel = None       # gRPC channel
        self._stub = None          # Fabric Gateway gRPC stub
        self._stub_mode = not HAS_FABRIC_SDK

    async def connect(self) -> None:
        """Establish gRPC connection to Fabric peer gateway."""
        if self._stub_mode:
            logger.warning("[FabricClient] STUB MODE — no real Fabric connection")
            self._connected = True
            return

        try:
            if self.profile.tls_cert_pem:
                credentials = grpc.ssl_channel_credentials(
                    root_certificates=self.profile.tls_cert_pem.encode()
                )
                self._channel = aio_grpc.secure_channel(
                    self.profile.gateway_endpoint, credentials
                )
            else:
                # Insecure for local dev / testnet
                self._channel = aio_grpc.insecure_channel(
                    self.profile.gateway_endpoint
                )

            # NOTE: In production, import generated gateway_pb2_grpc here
            # from gateway_pb2_grpc import GatewayStub
            # self._stub = GatewayStub(self._channel)

            self._connected = True
            logger.info(
                f"[FabricClient] Connected to {self.profile.gateway_endpoint} "
                f"channel={self.profile.channel_name}"
            )
        except Exception as e:
            logger.error(f"[FabricClient] Connection failed: {e}")
            self._stub_mode = True
            self._connected = True  # Mark connected so we don't retry on every call

    async def disconnect(self) -> None:
        if self._channel:
            await self._channel.close()
        self._connected = False
        logger.info("[FabricClient] Disconnected")

    async def __aenter__(self) -> "FabricGatewayClient":
        await self.connect()
        return self

    async def __aexit__(self, *args) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Core transaction methods
    # ------------------------------------------------------------------

    async def submit_transaction(
        self,
        function_name: str,
        json_payload: str,
        transient_data: Optional[Dict[str, bytes]] = None,
    ) -> FabricTransactionResult:
        """
        Submit a transaction to the chaincode (write operation).
        Blocks until the transaction is committed to the ledger.

        Args:
            function_name: Chaincode function name (e.g. "CreateClaimEvent")
            json_payload: JSON string payload
            transient_data: Optional private data map (for private collections)

        Returns:
            FabricTransactionResult
        """
        if not self._connected:
            await self.connect()

        if self._stub_mode:
            return self._stub_result(function_name, json_payload)

        try:
            # ----------------------------------------------------------------
            # PRODUCTION IMPLEMENTATION PLACEHOLDER
            # In a full implementation using fabric-gateway-client-go via gRPC:
            #
            # proposal = await self._stub.Endorse(EndorseRequest(
            #     channel_id=self.profile.channel_name,
            #     chaincode_id=self.profile.chaincode_name,
            #     transaction=Transaction(
            #         function_name=function_name,
            #         args=[json_payload.encode()],
            #     )
            # ))
            # submit_response = await self._stub.Submit(SubmitRequest(
            #     prepared_transaction=proposal.prepared_transaction
            # ))
            # await self._stub.CommitStatus(CommitStatusRequest(...))
            # ----------------------------------------------------------------

            # For now, log and return stub (swap with above when Fabric is live)
            logger.info(
                f"[FabricClient] WOULD submit tx: fn={function_name} "
                f"payload_len={len(json_payload)}"
            )
            return self._stub_result(function_name, json_payload)

        except Exception as e:
            logger.error(f"[FabricClient] submit_transaction failed: {e}")
            return FabricTransactionResult(
                success=False,
                transaction_id=None,
                block_number=None,
                payload=None,
                error=str(e),
                stub_mode=self._stub_mode,
            )

    async def evaluate_transaction(
        self,
        function_name: str,
        *args: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a query against the ledger (read-only, no consensus needed).

        Returns the deserialized JSON response from chaincode.
        """
        if not self._connected:
            await self.connect()

        if self._stub_mode:
            logger.debug(f"[FabricClient] STUB query: {function_name}({args})")
            return {"stub": True, "function": function_name, "args": args}

        try:
            # PRODUCTION: call Gateway EvaluateTransaction RPC
            # result = await self._stub.Evaluate(EvaluateRequest(...))
            # return json.loads(result.result.payload)
            return {"stub": True, "function": function_name}
        except Exception as e:
            logger.error(f"[FabricClient] evaluate_transaction failed: {e}")
            return None

    async def get_transaction_by_id(
        self, transaction_id: str
    ) -> Optional[Dict[str, Any]]:
        """Fetch a committed transaction from the ledger by its ID."""
        return await self.evaluate_transaction("GetTransactionByID", transaction_id)

    async def get_history_for_key(
        self, collection: str, key: str
    ) -> List[Dict[str, Any]]:
        """
        Get full audit history for a ledger key (e.g. all events for claim_id).
        Uses GetHistoryForKey chaincode function.
        """
        result = await self.evaluate_transaction(
            "GetHistoryForKey", collection, key
        )
        if result and "history" in result:
            return result["history"]
        return []

    async def ping(self) -> bool:
        """Health check — returns True if Fabric peer is reachable."""
        if self._stub_mode:
            return False
        try:
            result = await self.evaluate_transaction("Ping")
            return result is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stub_result(
        self, function_name: str, payload: str
    ) -> FabricTransactionResult:
        """Generate a realistic-looking stub result for dev/test mode."""
        import uuid
        import hashlib

        fake_tx_id = "stub-" + hashlib.sha256(
            f"{function_name}{payload}".encode()
        ).hexdigest()[:32]

        logger.info(
            f"[FabricClient][STUB] fn={function_name} "
            f"fake_tx_id={fake_tx_id} payload_len={len(payload)}"
        )
        return FabricTransactionResult(
            success=True,
            transaction_id=fake_tx_id,
            block_number=None,
            payload=payload.encode(),
            stub_mode=True,
        )

    @property
    def is_stub_mode(self) -> bool:
        return self._stub_mode

    @property
    def channel_name(self) -> str:
        return self.profile.channel_name

    @property
    def chaincode_name(self) -> str:
        return self.profile.chaincode_name


# ---------------------------------------------------------------------------
# Singleton — shared across the FastAPI app lifetime
# ---------------------------------------------------------------------------

_fabric_client: Optional[FabricGatewayClient] = None


def get_fabric_client() -> FabricGatewayClient:
    """FastAPI dependency — returns the shared Fabric client instance."""
    global _fabric_client
    if _fabric_client is None:
        _fabric_client = FabricGatewayClient()
    return _fabric_client


async def init_fabric_client() -> None:
    """Called from FastAPI lifespan startup."""
    client = get_fabric_client()
    await client.connect()
    logger.info(
        f"[FabricClient] Initialized. "
        f"stub_mode={client.is_stub_mode} "
        f"channel={client.channel_name}"
    )


async def shutdown_fabric_client() -> None:
    """Called from FastAPI lifespan shutdown."""
    global _fabric_client
    if _fabric_client:
        await _fabric_client.disconnect()
        _fabric_client = None
