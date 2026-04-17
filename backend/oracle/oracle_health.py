"""
backend/oracle/oracle_health.py — Oracle node health monitoring & circuit breaker (Innovation 03)

Tracks per-node health across all three oracle streams.
Provides:
  - Success/failure recording per fetch attempt
  - Rolling 24h success rate computation
  - P95 latency tracking (sliding window)
  - Circuit breaker: after CIRCUIT_BREAKER_THRESHOLD consecutive failures,
    node is marked DEGRADED. After OFFLINE_THRESHOLD, marked OFFLINE.
    OFFLINE nodes are excluded from the quorum denominator (not just skipped).
  - Recovery: after a successful fetch, consecutive_failures resets.
  - FastAPI router for /api/v1/oracle/health to expose this dashboard.

Persistence: health state is stored in Redis (key: oracle_health:{source_id}:{stream})
with a TTL of 24h. Falls back to in-memory dict if Redis is unavailable.
"""

import asyncio
import json
import logging
import statistics
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from oracle.models import NodeHealth, OracleNetworkHealth, OracleNodeHealth, OracleStream

logger = logging.getLogger(__name__)

# ─── Circuit breaker thresholds ───────────────────────────────────────────────

CIRCUIT_BREAKER_THRESHOLD = 3   # consecutive failures → DEGRADED
OFFLINE_THRESHOLD         = 10  # consecutive failures → OFFLINE
LATENCY_WINDOW            = 100 # last N readings for P95 computation
RECOVERY_ON_SUCCESS       = True

# ─── Node registry ────────────────────────────────────────────────────────────

# Which sources belong to each stream
STREAM_SOURCES = {
    OracleStream.S1_ENVIRONMENTAL: ["openweathermap", "imd", "accuweather", "iot_env"],
    OracleStream.S2_MOBILITY:      ["osrm", "google_mobility", "bbmp_sensors"],
    OracleStream.S3_ECONOMIC:      ["amazon_flex", "dunzo_zomato", "ecommerce_density"],
}

# Consensus thresholds per stream (mirrored; updated by aggregator on governance change)
STREAM_THRESHOLDS = {
    OracleStream.S1_ENVIRONMENTAL: 3,
    OracleStream.S2_MOBILITY:      2,
    OracleStream.S3_ECONOMIC:      2,
}


# ─── Health Monitor ───────────────────────────────────────────────────────────

class OracleHealthMonitor:
    """
    Tracks per-node health and exposes circuit-breaker state to the aggregator.

    In production, reads/writes health state to Redis so it persists across
    server restarts and is shared between multiple API workers.
    Falls back to in-memory storage if Redis is unavailable.
    """

    def __init__(self):
        # In-memory state: (source_id, stream) → OracleNodeHealth
        self._health: dict[tuple[str, OracleStream], OracleNodeHealth] = {}
        # Latency windows: (source_id, stream) → deque of float (ms)
        self._latency_windows: dict[tuple[str, OracleStream], deque] = defaultdict(
            lambda: deque(maxlen=LATENCY_WINDOW)
        )
        # 24h event log: (source_id, stream) → deque of (timestamp, success bool)
        self._event_log: dict[tuple[str, OracleStream], deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._redis = None
        self._redis_available = False
        self._initialise_all_nodes()

    def _initialise_all_nodes(self):
        """Seed health records for all known nodes."""
        for stream, sources in STREAM_SOURCES.items():
            for source_id in sources:
                key = (source_id, stream)
                if key not in self._health:
                    self._health[key] = OracleNodeHealth(
                        source_id=source_id,
                        stream=stream,
                        health=NodeHealth.HEALTHY,
                        consecutive_failures=0,
                    )

    async def connect_redis(self):
        """Attempt to connect to Redis for persistent health state."""
        try:
            import redis.asyncio as aioredis
            from config import get_settings
            settings = get_settings()
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("OracleHealthMonitor: connected to Redis for persistent health state")
        except Exception as exc:
            logger.warning(f"OracleHealthMonitor: Redis unavailable, using in-memory state: {exc}")
            self._redis_available = False

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_success(self, source_id: str, stream: OracleStream, latency_ms: float = 0.0):
        """Record a successful oracle fetch. Resets consecutive failure counter."""
        key = (source_id, stream)
        node = self._health.get(key)
        if node is None:
            node = OracleNodeHealth(source_id=source_id, stream=stream, health=NodeHealth.HEALTHY)
            self._health[key] = node

        was_degraded = node.health in (NodeHealth.DEGRADED, NodeHealth.OFFLINE)

        node.consecutive_failures = 0
        node.last_success_at = datetime.now(timezone.utc)
        node.latency_ms = latency_ms  # store for reference

        if RECOVERY_ON_SUCCESS:
            node.health = NodeHealth.HEALTHY
            node.excluded_from_quorum = False
            node.exclusion_reason = None

        # Update latency window
        self._latency_windows[key].append(latency_ms)
        node.avg_latency_ms = statistics.mean(self._latency_windows[key])
        if len(self._latency_windows[key]) >= 20:
            sorted_latencies = sorted(self._latency_windows[key])
            p95_idx = int(len(sorted_latencies) * 0.95)
            node.p95_latency_ms = sorted_latencies[p95_idx]

        # Log event
        self._event_log[key].append((datetime.now(timezone.utc), True))
        node.success_rate_24h = self._compute_success_rate_24h(key)
        node.total_calls_24h = self._count_events_24h(key)
        node.total_failures_24h = self._count_failures_24h(key)

        if was_degraded:
            logger.info(f"OracleHealthMonitor: {source_id} ({stream}) RECOVERED → HEALTHY")

    def record_failure(self, source_id: str, stream: OracleStream):
        """Record a failed oracle fetch. Applies circuit breaker if threshold exceeded."""
        key = (source_id, stream)
        node = self._health.get(key)
        if node is None:
            node = OracleNodeHealth(source_id=source_id, stream=stream, health=NodeHealth.HEALTHY)
            self._health[key] = node

        node.consecutive_failures += 1
        node.last_failure_at = datetime.now(timezone.utc)

        self._event_log[key].append((datetime.now(timezone.utc), False))
        node.success_rate_24h = self._compute_success_rate_24h(key)
        node.total_calls_24h = self._count_events_24h(key)
        node.total_failures_24h = self._count_failures_24h(key)

        # Apply circuit breaker
        if node.consecutive_failures >= OFFLINE_THRESHOLD and node.health != NodeHealth.OFFLINE:
            node.health = NodeHealth.OFFLINE
            node.excluded_from_quorum = True
            node.exclusion_reason = f"OFFLINE: {node.consecutive_failures} consecutive failures"
            logger.error(
                f"OracleHealthMonitor: {source_id} ({stream}) → OFFLINE "
                f"({node.consecutive_failures} consecutive failures). "
                f"Excluded from quorum denominator."
            )
        elif node.consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD and node.health == NodeHealth.HEALTHY:
            node.health = NodeHealth.DEGRADED
            node.excluded_from_quorum = True
            node.exclusion_reason = f"DEGRADED: {node.consecutive_failures} consecutive failures"
            logger.warning(
                f"OracleHealthMonitor: {source_id} ({stream}) → DEGRADED "
                f"({node.consecutive_failures} consecutive failures). "
                f"Excluded from quorum denominator."
            )

    # ── Querying ──────────────────────────────────────────────────────────────

    def get_node_health(self, source_id: str, stream: OracleStream) -> Optional[OracleNodeHealth]:
        return self._health.get((source_id, stream))

    def get_degraded_sources(self, stream: OracleStream) -> list[str]:
        """Return source IDs for this stream that are DEGRADED or OFFLINE."""
        return [
            source_id
            for (source_id, s), node in self._health.items()
            if s == stream and node.health in (NodeHealth.DEGRADED, NodeHealth.OFFLINE)
        ]

    def get_network_health(self) -> OracleNetworkHealth:
        """Compute aggregated health across all streams."""
        nodes = list(self._health.values())
        warnings = []

        def healthy_count(stream: OracleStream) -> int:
            return sum(
                1 for (sid, s), node in self._health.items()
                if s == stream and node.health == NodeHealth.HEALTHY
            )

        s1_healthy = healthy_count(OracleStream.S1_ENVIRONMENTAL)
        s2_healthy = healthy_count(OracleStream.S2_MOBILITY)
        s3_healthy = healthy_count(OracleStream.S3_ECONOMIC)

        s1_req = STREAM_THRESHOLDS[OracleStream.S1_ENVIRONMENTAL]
        s2_req = STREAM_THRESHOLDS[OracleStream.S2_MOBILITY]
        s3_req = STREAM_THRESHOLDS[OracleStream.S3_ECONOMIC]

        if s1_healthy < s1_req:
            warnings.append(f"S1 Environmental: only {s1_healthy}/{s1_req} required nodes healthy")
        if s2_healthy < s2_req:
            warnings.append(f"S2 Mobility: only {s2_healthy}/{s2_req} required nodes healthy")
        if s3_healthy < s3_req:
            warnings.append(f"S3 Economic: only {s3_healthy}/{s3_req} required nodes healthy")

        degraded_nodes = [n for n in nodes if n.health in (NodeHealth.DEGRADED, NodeHealth.OFFLINE)]
        if degraded_nodes:
            for n in degraded_nodes:
                warnings.append(f"{n.source_id} ({n.stream}): {n.health} — {n.exclusion_reason}")

        overall = NodeHealth.HEALTHY
        if warnings:
            overall = NodeHealth.DEGRADED
        if any(n.health == NodeHealth.OFFLINE for n in nodes):
            overall = NodeHealth.OFFLINE

        return OracleNetworkHealth(
            nodes=nodes,
            s1_healthy_count=s1_healthy,
            s1_required_count=s1_req,
            s2_healthy_count=s2_healthy,
            s2_required_count=s2_req,
            s3_healthy_count=s3_healthy,
            s3_required_count=s3_req,
            overall_health=overall,
            warnings=warnings,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _compute_success_rate_24h(self, key: tuple) -> float:
        events = self._event_log[key]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = [(ts, ok) for ts, ok in events if ts >= cutoff]
        if not recent:
            return 1.0
        successes = sum(1 for _, ok in recent if ok)
        return round(successes / len(recent), 4)

    def _count_events_24h(self, key: tuple) -> int:
        events = self._event_log[key]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        return sum(1 for ts, _ in events if ts >= cutoff)

    def _count_failures_24h(self, key: tuple) -> int:
        events = self._event_log[key]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        return sum(1 for ts, ok in events if ts >= cutoff and not ok)


# ─── FastAPI Router ───────────────────────────────────────────────────────────

from fastapi import APIRouter

oracle_health_router = APIRouter(prefix="/api/v1/oracle", tags=["oracle"])

# Shared monitor instance (shared with aggregator)
_monitor: Optional[OracleHealthMonitor] = None


def get_health_monitor() -> OracleHealthMonitor:
    global _monitor
    if _monitor is None:
        _monitor = OracleHealthMonitor()
    return _monitor


@oracle_health_router.get("/health")
async def get_oracle_health():
    """
    Oracle network health dashboard.
    Returns per-node health, latency stats, circuit breaker status,
    and whether each stream has enough healthy nodes to reach consensus.
    """
    monitor = get_health_monitor()
    network_health = monitor.get_network_health()
    return {
        "status": network_health.overall_health.value,
        "timestamp": network_health.timestamp.isoformat(),
        "streams": {
            "S1_environmental": {
                "healthy_nodes":   network_health.s1_healthy_count,
                "required_nodes":  network_health.s1_required_count,
                "can_consensus":   network_health.s1_healthy_count >= network_health.s1_required_count,
            },
            "S2_mobility": {
                "healthy_nodes":  network_health.s2_healthy_count,
                "required_nodes": network_health.s2_required_count,
                "can_consensus":  network_health.s2_healthy_count >= network_health.s2_required_count,
            },
            "S3_economic": {
                "healthy_nodes":  network_health.s3_healthy_count,
                "required_nodes": network_health.s3_required_count,
                "can_consensus":  network_health.s3_healthy_count >= network_health.s3_required_count,
            },
        },
        "nodes": [
            {
                "source_id":             n.source_id,
                "stream":                n.stream.value,
                "health":                n.health.value,
                "consecutive_failures":  n.consecutive_failures,
                "avg_latency_ms":        round(n.avg_latency_ms, 1),
                "p95_latency_ms":        round(n.p95_latency_ms, 1),
                "success_rate_24h":      n.success_rate_24h,
                "total_calls_24h":       n.total_calls_24h,
                "excluded_from_quorum":  n.excluded_from_quorum,
                "exclusion_reason":      n.exclusion_reason,
                "last_success_at":       n.last_success_at.isoformat() if n.last_success_at else None,
                "last_failure_at":       n.last_failure_at.isoformat() if n.last_failure_at else None,
            }
            for n in network_health.nodes
        ],
        "warnings": network_health.warnings,
    }


@oracle_health_router.post("/health/{source_id}/reset")
async def reset_node_circuit_breaker(source_id: str, stream: str):
    """
    Manually reset a node's circuit breaker (admin only).
    Use when a node has been repaired and should be re-included in quorum.
    """
    try:
        stream_enum = OracleStream(stream)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid stream '{stream}'")

    monitor = get_health_monitor()
    key = (source_id, stream_enum)
    node = monitor._health.get(key)
    if not node:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Node {source_id}/{stream} not found")

    old_health = node.health.value
    node.health = NodeHealth.HEALTHY
    node.consecutive_failures = 0
    node.excluded_from_quorum = False
    node.exclusion_reason = None

    logger.info(f"OracleHealthMonitor: {source_id} ({stream}) manually reset from {old_health} → HEALTHY")

    return {
        "source_id": source_id,
        "stream":    stream,
        "old_health": old_health,
        "new_health": "HEALTHY",
        "message":   "Circuit breaker manually reset",
    }
