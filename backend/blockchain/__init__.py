"""
ZoneGuard Blockchain Package
============================
Innovation 01: ZoneChain — Hyperledger Fabric v2.5 permissioned ledger
Innovation 02: SmartPolicy Contracts — On-chain payout formula execution
Innovation 10: TemporalSig — Polygon L2 signal-batch timestamp anchoring

All blockchain operations are fire-and-forget with local DB fallback.
The application NEVER blocks on blockchain writes.
"""

from .zonechain import ZoneChainClient
from .temporalsig import TemporalSigClient
from .smart_policy import SmartPolicyEngine
from .models import (
    ChainEventType,
    ZoneChainEvent,
    TemporalSigAnchor,
    SignalBatchPayload,
    ClaimEventPayload,
    PolicyEventPayload,
    PayoutEventPayload,
    ParameterChangePayload,
    PolicyTermsOnChain,
    SmartPolicyResult,
)

__all__ = [
    "ZoneChainClient",
    "TemporalSigClient",
    "SmartPolicyEngine",
    "ChainEventType",
    "ZoneChainEvent",
    "TemporalSigAnchor",
    "SignalBatchPayload",
    "ClaimEventPayload",
    "PolicyEventPayload",
    "PayoutEventPayload",
    "ParameterChangePayload",
    "PolicyTermsOnChain",
    "SmartPolicyResult",
]
