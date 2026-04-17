"""
Pydantic models for ZoneGuard Governance, ZONE Token, SoulboundNFT, and Reinsurance Pool.
Session 5 — Innovations 06, 07, 08.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal, Dict, Any
from datetime import datetime
from enum import Enum


# ─────────────────────────────────────────────
# ZONE TOKEN MODELS
# ─────────────────────────────────────────────

class ZoneTokenEvent(str, Enum):
    WEEKLY_COVERAGE       = "weekly_coverage"       # +10
    CLAIM_FREE_4WEEKS     = "claim_free_4weeks"      # +25
    S4_CHECKIN            = "s4_checkin"             # +5
    REFERRAL_ACTIVE       = "referral_active"        # +50
    APPEAL_SUCCESSFUL     = "appeal_successful"      # +100
    APPEAL_FALSE          = "appeal_false"           # -50
    GOVERNANCE_VOTE       = "governance_vote"        # +3 (participation reward)
    ADMIN_ADJUSTMENT      = "admin_adjustment"       # manual


ZONE_TOKEN_DELTAS: Dict[ZoneTokenEvent, int] = {
    ZoneTokenEvent.WEEKLY_COVERAGE:    +10,
    ZoneTokenEvent.CLAIM_FREE_4WEEKS:  +25,
    ZoneTokenEvent.S4_CHECKIN:         +5,
    ZoneTokenEvent.REFERRAL_ACTIVE:    +50,
    ZoneTokenEvent.APPEAL_SUCCESSFUL:  +100,
    ZoneTokenEvent.APPEAL_FALSE:       -50,
    ZoneTokenEvent.GOVERNANCE_VOTE:    +3,
    ZoneTokenEvent.ADMIN_ADJUSTMENT:   0,  # delta supplied manually
}


class ZoneTokenBalance(BaseModel):
    rider_id: str
    balance: int = Field(ge=0, description="Current non-negative ZONE token balance")
    lifetime_earned: int = 0
    lifetime_burned: int = 0
    governance_weight: float = Field(description="Quadratic-scaled voting power")
    updated_at: datetime


class ZoneTokenTransaction(BaseModel):
    id: str
    rider_id: str
    event_type: ZoneTokenEvent
    delta: int
    balance_after: int
    reference_id: Optional[str] = None  # policy_id, claim_id, etc.
    notes: Optional[str] = None
    created_at: datetime


class TokenEarnRequest(BaseModel):
    rider_id: str
    event_type: ZoneTokenEvent
    reference_id: Optional[str] = None
    manual_delta: Optional[int] = None  # only for ADMIN_ADJUSTMENT
    notes: Optional[str] = None


# ─────────────────────────────────────────────
# GOVERNANCE PROPOSAL MODELS
# ─────────────────────────────────────────────

class GovernableParameter(str, Enum):
    PAYOUT_PERCENTAGE     = "payout_percentage"      # 50-65%
    MAX_DISRUPTION_DAYS   = "max_disruption_days"    # 2-4 days
    FORWARD_LOCK_DISCOUNT = "forward_lock_discount"  # 6-12%
    EXCLUSION_ADD         = "exclusion_add"          # 75% supermajority
    EXCLUSION_REMOVE      = "exclusion_remove"       # 75% supermajority
    S4_THRESHOLD          = "s4_threshold"           # crowd signal threshold


# Actuarial safe bands — guardrail engine enforces these regardless of vote outcome
PARAMETER_SAFE_BANDS: Dict[GovernableParameter, Dict[str, Any]] = {
    GovernableParameter.PAYOUT_PERCENTAGE: {
        "min": 50.0, "max": 65.0,
        "supermajority_required": False,
        "loss_ratio_block": 85.0,  # block payout% increase if LTM loss ratio > 85%
    },
    GovernableParameter.MAX_DISRUPTION_DAYS: {
        "min": 2, "max": 4,
        "supermajority_required": False,
        "loss_ratio_block": None,
    },
    GovernableParameter.FORWARD_LOCK_DISCOUNT: {
        "min": 6.0, "max": 12.0,
        "supermajority_required": False,
        "loss_ratio_block": None,
    },
    GovernableParameter.EXCLUSION_ADD: {
        "min": None, "max": None,
        "supermajority_required": True,   # 75% threshold
        "loss_ratio_block": None,
    },
    GovernableParameter.EXCLUSION_REMOVE: {
        "min": None, "max": None,
        "supermajority_required": True,   # 75% threshold
        "loss_ratio_block": None,
    },
    GovernableParameter.S4_THRESHOLD: {
        "min": 0.3, "max": 0.9,
        "supermajority_required": False,
        "loss_ratio_block": None,
    },
}


class ProposalStatus(str, Enum):
    ACTIVE   = "active"
    PASSED   = "passed"
    REJECTED = "rejected"
    EXPIRED  = "expired"
    EXECUTED = "executed"
    BLOCKED  = "blocked"   # actuarial guardrail blocked execution


class ProposalCreate(BaseModel):
    proposer_rider_id: str
    parameter: GovernableParameter
    proposed_value: float = Field(description="Numeric value; for exclusions, encode as exclusion_type_id hash")
    proposed_exclusion_id: Optional[str] = None  # for EXCLUSION_ADD/REMOVE
    rationale: str = Field(min_length=20, max_length=500)
    voting_period_hours: int = Field(default=168, ge=24, le=336)  # 1-14 days, default 7

    @model_validator(mode="after")
    def validate_exclusion_fields(self) -> "ProposalCreate":
        if self.parameter in (GovernableParameter.EXCLUSION_ADD, GovernableParameter.EXCLUSION_REMOVE):
            if not self.proposed_exclusion_id:
                raise ValueError("proposed_exclusion_id required for exclusion proposals")
        return self


class ProposalResponse(BaseModel):
    id: str
    proposer_rider_id: str
    parameter: GovernableParameter
    proposed_value: float
    proposed_exclusion_id: Optional[str] = None
    rationale: str
    status: ProposalStatus
    votes_for: int = 0
    votes_against: int = 0
    weight_for: float = 0.0
    weight_against: float = 0.0
    quorum_reached: bool = False
    supermajority_reached: bool = False
    voting_ends_at: datetime
    executed_at: Optional[datetime] = None
    execution_tx_hash: Optional[str] = None
    guardrail_block_reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VoteRequest(BaseModel):
    rider_id: str
    support: bool  # True = for, False = against


class VoteResponse(BaseModel):
    proposal_id: str
    rider_id: str
    support: bool
    governance_weight: float
    voted_at: datetime
    token_reward: int = 3  # GOVERNANCE_VOTE reward


# ─────────────────────────────────────────────
# SOULBOUND NFT MODELS
# ─────────────────────────────────────────────

class NFTMetadata(BaseModel):
    """IPFS-compatible metadata schema for SoulboundPolicy NFT."""
    name: str                          # "ZoneGuard Coverage — Week 42, 2025"
    description: str
    image: str                         # IPFS CID or placeholder URI
    attributes: list[Dict[str, Any]]   # OpenSea-style trait array
    external_url: str = "https://zoneguard.in"
    background_color: str = "FFFBF3"


class SoulboundNFTResponse(BaseModel):
    token_id: str
    rider_zk_hash: str
    policy_id: str
    week_number: int
    year: int
    coverage_tier: str
    zone_id: str
    premium_paid: float
    max_payout: float
    was_disrupted: bool
    payout_received: float
    minted_at: datetime
    ipfs_metadata_cid: Optional[str] = None
    chain_tx_hash: Optional[str] = None  # Hyperledger Fabric tx ID

    model_config = {"from_attributes": True}


class CoverageContinuityScore(BaseModel):
    rider_id: str
    rider_zk_hash: str
    total_nfts: int
    consecutive_weeks: int
    score: float = Field(ge=0.0, le=100.0, description="0-100 financial discipline score")
    score_label: Literal["Unrated", "Building", "Established", "Trusted", "Elite"]
    eligible_for_microloan: bool
    eligible_for_credit_delegation: bool  # Aave Credit Delegation threshold = 52 consecutive
    total_payout_received: float
    avg_premium_paid: float
    computed_at: datetime

    # NBFC integration surface
    nbfc_report_uri: Optional[str] = None


# ─────────────────────────────────────────────
# REINSURANCE POOL MODELS
# ─────────────────────────────────────────────

class Tranche(str, Enum):
    SENIOR     = "senior"      # 70% of pool, 9-11% yield, last-in-loss
    MEZZANINE  = "mezzanine"   # 20%, 14-18%, pro-rata loss
    JUNIOR     = "junior"      # 10%, 25-30%, first-loss


TRANCHE_CONFIG: Dict[Tranche, Dict[str, Any]] = {
    Tranche.SENIOR: {
        "pool_share": 0.70,
        "yield_min_pct": 9.0,
        "yield_max_pct": 11.0,
        "loss_priority": 3,      # last to absorb losses
        "description": "Senior secured — last-in-loss, institutional grade",
    },
    Tranche.MEZZANINE: {
        "pool_share": 0.20,
        "yield_min_pct": 14.0,
        "yield_max_pct": 18.0,
        "loss_priority": 2,
        "description": "Mezzanine — pro-rata loss sharing",
    },
    Tranche.JUNIOR: {
        "pool_share": 0.10,
        "yield_min_pct": 25.0,
        "yield_max_pct": 30.0,
        "loss_priority": 1,      # first to absorb losses
        "description": "Junior equity — first-loss, highest yield",
    },
}


class StakeRequest(BaseModel):
    provider_id: str
    tranche: Tranche
    amount_inr: float = Field(gt=0, description="Stake amount in INR")
    provider_type: Literal["institutional", "individual", "nbfc"] = "institutional"


class StakeResponse(BaseModel):
    position_id: str
    provider_id: str
    tranche: Tranche
    amount_staked: float
    pool_share_pct: float
    expected_annual_yield_pct: float
    staked_at: datetime
    lock_period_days: int = 90  # minimum 90-day lock per IRDAI sandbox framework


class PoolState(BaseModel):
    total_pool_inr: float
    senior_pool_inr: float
    mezzanine_pool_inr: float
    junior_pool_inr: float
    total_premiums_collected_week: float
    total_payouts_week: float
    loss_ratio_ltm: float
    pool_utilization_pct: float
    active_positions: int
    last_yield_distribution: Optional[datetime]
    irdai_sandbox_ref: str = "IRDAI/SB/2024/ZG-001"  # placeholder sandbox ref


class YieldDistributionRecord(BaseModel):
    distribution_id: str
    period_start: datetime
    period_end: datetime
    total_premium_inflow: float
    total_payout_outflow: float
    net_pool_income: float
    senior_yield_distributed: float
    mezzanine_yield_distributed: float
    junior_yield_distributed: float
    distributed_at: datetime


# ─────────────────────────────────────────────
# GOVERNANCE HEALTH SCORE
# ─────────────────────────────────────────────

class GovernanceHealthScore(BaseModel):
    rider_id: str
    score: float = Field(ge=0.0, le=100.0)
    token_balance_component: float   # 40% weight
    participation_component: float   # 30% weight
    claims_free_component: float     # 30% weight
    label: Literal["Inactive", "Emerging", "Active", "Champion"]
    premium_discount_eligible: bool  # score > 75 unlocks discount
    computed_at: datetime
