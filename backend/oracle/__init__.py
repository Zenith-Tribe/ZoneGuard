"""
backend/oracle/__init__.py — ChainOracle Network package (Innovation 03)

Exports the primary interfaces for use by the rest of the application:
  - OracleAggregator / get_aggregator: multi-source consensus engine
  - OracleHealthMonitor / get_health_monitor: circuit breaker & health tracker
  - oracle_health_router: FastAPI router for /api/v1/oracle/health
  - Models: ConsensusResult, OracleStream, ConsensusStatus
"""

from oracle.aggregator import OracleAggregator, get_aggregator
from oracle.oracle_health import OracleHealthMonitor, get_health_monitor, oracle_health_router
from oracle.models import (
    ConsensusResult,
    ConsensusStatus,
    OracleStream,
    OracleReading,
    OracleNetworkHealth,
    OracleNodeHealth,
)

__all__ = [
    "OracleAggregator",
    "get_aggregator",
    "OracleHealthMonitor",
    "get_health_monitor",
    "oracle_health_router",
    "ConsensusResult",
    "ConsensusStatus",
    "OracleStream",
    "OracleReading",
    "OracleNetworkHealth",
    "OracleNodeHealth",
]
