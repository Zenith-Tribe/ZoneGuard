"""
ZoneGuard Blockchain Package
============================
Innovation 01: ZoneChain — Hyperledger Fabric v2.5 permissioned ledger
Innovation 10: TemporalSig — Polygon L2 signal-batch timestamp anchoring

All blockchain operations are fire-and-forget with local DB fallback.
The application NEVER blocks on blockchain writes.
"""

from .zonechain import ZoneChainClient
from .temporalsig import TemporalSigClient
from .models import (
    ChainEventType,
    ZoneChainEvent,
    TemporalSigAnchor,
    SignalBatchPayload,
    ClaimEventPayload,
    PolicyEventPayload,
    PayoutEventPayload,
    ParameterChangePayload,
)

__all__ = [
    "ZoneChainClient",
    "TemporalSigClient",
    "ChainEventType",
    "ZoneChainEvent",
    "TemporalSigAnchor",
    "SignalBatchPayload",
    "ClaimEventPayload",
    "PolicyEventPayload",
    "PayoutEventPayload",
    "ParameterChangePayload",
]
