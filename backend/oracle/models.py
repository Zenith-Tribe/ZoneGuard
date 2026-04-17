"""
backend/oracle/models.py — Pydantic models for ChainOracle Network (Innovation 03)

Defines the data contracts for:
  - Individual oracle source readings (per node, cryptographically signed)
  - Consensus results (accepted or INSUFFICIENT_CONSENSUS)
  - Oracle health snapshots per node
  - The three oracle streams: S1 Environmental, S2 Mobility, S3 Economic

These models flow through the aggregator and into signal_fusion.py.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class OracleStream(str, Enum):
    S1_ENVIRONMENTAL = "S1_ENVIRONMENTAL"
    S2_MOBILITY      = "S2_MOBILITY"
    S3_ECONOMIC      = "S3_ECONOMIC"
    S4_CROWD         = "S4_CROWD"


class ConsensusStatus(str, Enum):
    ACCEPTED              = "ACCEPTED"
    INSUFFICIENT_CONSENSUS = "INSUFFICIENT_CONSENSUS"
    ALL_NODES_FAILED      = "ALL_NODES_FAILED"


class NodeHealth(str, Enum):
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"   # >3 consecutive failures
    OFFLINE  = "OFFLINE"    # no response in last polling cycle


# ─── Individual Oracle Reading ────────────────────────────────────────────────

class OracleReading(BaseModel):
    """
    A single data reading from one oracle source node.
    The signature field is a HMAC-SHA256 of the canonical JSON payload
    (source_id + stream + data + timestamp) using the node's shared secret.
    """
    source_id:   str   = Field(..., description="Unique identifier for the oracle source, e.g. 'openweathermap'")
    stream:      OracleStream
    data:        dict[str, Any] = Field(..., description="Raw data payload from the source")
    timestamp:   datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signature:   str   = Field(..., description="HMAC-SHA256 signature of canonical payload")
    latency_ms:  float = Field(default=0.0, description="Round-trip time to fetch this reading in ms")
    success:     bool  = Field(default=True)
    error_detail: Optional[str] = None

    def canonical_payload(self) -> str:
        """Reproducible string used for signature verification."""
        return json.dumps({
            "source_id": self.source_id,
            "stream":    self.stream.value,
            "data":      self.data,
            "timestamp": self.timestamp.isoformat(),
        }, sort_keys=True)

    def content_hash(self) -> str:
        """SHA-256 of the canonical payload — used as oracle_consensus_ref in chaincode."""
        return hashlib.sha256(self.canonical_payload().encode()).hexdigest()

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class FailedOracleReading(BaseModel):
    """Represents a node that failed to respond or returned invalid data."""
    source_id:    str
    stream:       OracleStream
    error_detail: str
    timestamp:    datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    success:      bool = False
    signature:    str  = "FAILED"
    latency_ms:   float = 0.0


# ─── S1 Environmental Normalised ─────────────────────────────────────────────

class S1NormalisedReading(BaseModel):
    """
    Normalised environmental data extracted from a raw OracleReading.
    Each source maps to this schema — the aggregator works on normalised values.
    """
    rainfall_mm_hr: float = Field(ge=0)
    temperature_c:  float
    aqi:            float = Field(ge=0, le=500)  # all sources mapped to 0–500 scale
    humidity:       float = Field(ge=0, le=100)
    wind_speed_mps: float = Field(ge=0)
    description:    str   = ""
    source_id:      str   = ""


# ─── S2 Mobility Normalised ───────────────────────────────────────────────────

class S2NormalisedReading(BaseModel):
    """
    Normalised mobility data. mobility_index is a 0–100 score where
    100 = full normal mobility, 0 = complete standstill.
    """
    mobility_index:   float = Field(ge=0, le=100)
    avg_speed_kmh:    Optional[float] = None
    congestion_level: Optional[float] = None  # 0–1 scale
    route_delay_pct:  Optional[float] = None  # % delay vs free-flow
    source_id:        str = ""


# ─── S3 Economic Normalised ──────────────────────────────────────────────────

class S3NormalisedReading(BaseModel):
    """
    Normalised economic activity data. order_volume is an index where
    100 = normal baseline, lower values = suppressed activity.
    """
    order_volume_index: float = Field(ge=0)  # relative to 7-day baseline
    active_riders_pct:  Optional[float] = None  # % of expected riders online
    delivery_density:   Optional[float] = None  # orders per km²
    source_id:          str = ""


# ─── S4 Crowd Normalised ─────────────────────────────────────────────────────

class S4NormalisedReading(BaseModel):
    """
    Normalised crowd signal data. inactivity_pct is the percentage of
    zone riders reporting/detected as inactive (0-100 scale).
    """
    inactivity_pct: float = Field(ge=0, le=100)
    total_riders:   int   = Field(ge=0)
    inactive_riders: int  = Field(ge=0)
    response_rate:  Optional[float] = None  # % of riders who responded
    source_id:      str = ""


# ─── Consensus Result ─────────────────────────────────────────────────────────

class ConsensusResult(BaseModel):
    """
    The output of OracleAggregator for a single stream.
    If status == ACCEPTED, the aggregated_value is the median/mean of agreeing nodes.
    If status == INSUFFICIENT_CONSENSUS, the caller should treat the signal as unknown.
    """
    stream:              OracleStream
    status:              ConsensusStatus
    # Populated on ACCEPTED
    aggregated_value:    Optional[dict[str, Any]] = None
    agreeing_sources:    list[str] = Field(default_factory=list)
    dissenting_sources:  list[str] = Field(default_factory=list)
    failed_sources:      list[str] = Field(default_factory=list)
    nodes_polled:        int   = 0
    nodes_agreed:        int   = 0
    threshold_required:  int   = 0
    # Cryptographic reference — SHA-256 of all agreeing readings concatenated
    consensus_ref:       Optional[str] = None
    timestamp:           datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Raw readings for audit
    readings:            list[OracleReading] = Field(default_factory=list)
    # Circuit-breaker info
    degraded_nodes:      list[str] = Field(default_factory=list)

    @property
    def is_accepted(self) -> bool:
        return self.status == ConsensusStatus.ACCEPTED

    def to_signal_fusion_input(self) -> Optional[dict]:
        """
        Converts an ACCEPTED consensus result to the dict format
        expected by signal_fusion.evaluate_s1 / evaluate_s2 / evaluate_s3.
        Returns None if consensus was not reached.
        """
        if not self.is_accepted or self.aggregated_value is None:
            return None
        return self.aggregated_value

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


# ─── Oracle Health Snapshot ───────────────────────────────────────────────────

class OracleNodeHealth(BaseModel):
    """Health record for a single oracle source node."""
    source_id:           str
    stream:              OracleStream
    health:              NodeHealth
    consecutive_failures: int   = 0
    last_success_at:     Optional[datetime] = None
    last_failure_at:     Optional[datetime] = None
    avg_latency_ms:      float  = 0.0
    p95_latency_ms:      float  = 0.0
    success_rate_24h:    float  = 1.0   # 0.0–1.0
    total_calls_24h:     int    = 0
    total_failures_24h:  int    = 0
    # If DEGRADED/OFFLINE, excluded from quorum denominator
    excluded_from_quorum: bool  = False
    exclusion_reason:    Optional[str] = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class OracleNetworkHealth(BaseModel):
    """Aggregated health snapshot across all oracle nodes."""
    timestamp:            datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nodes:                list[OracleNodeHealth] = Field(default_factory=list)
    s1_healthy_count:     int = 0
    s1_required_count:    int = 3   # must be ≥ threshold
    s2_healthy_count:     int = 0
    s2_required_count:    int = 2
    s3_healthy_count:     int = 0
    s3_required_count:    int = 2
    s4_healthy_count:     int = 0
    s4_required_count:    int = 2
    overall_health:       NodeHealth = NodeHealth.HEALTHY
    warnings:             list[str] = Field(default_factory=list)

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
