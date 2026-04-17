"""
SQLAlchemy ORM models for all Session 5 database tables.

Tables created:
  - zone_token_balances
  - zone_token_transactions
  - governance_proposals
  - governance_votes
  - soulbound_nfts
  - reinsurance_positions
  - reinsurance_yield_distributions

These extend the existing Base from db.database — no changes to Base itself.
"""

from __future__ import annotations

import uuid
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime,
    ForeignKey, Text, UniqueConstraint,
)
from sqlalchemy.sql import func
from db.database import Base


# ─────────────────────────────────────────────
# ZONE TOKEN TABLES
# ─────────────────────────────────────────────

class ZoneTokenBalanceDB(Base):
    __tablename__ = "zone_token_balances"

    rider_id                = Column(String, ForeignKey("riders.id"), primary_key=True)
    balance                 = Column(Integer, nullable=False, default=0)
    lifetime_earned         = Column(Integer, nullable=False, default=0)
    lifetime_burned         = Column(Integer, nullable=False, default=0)
    # Rate-limit tracking columns
    last_s4_checkin         = Column(DateTime(timezone=True), nullable=True)
    last_appeal_resolved    = Column(DateTime(timezone=True), nullable=True)
    referral_count_this_year= Column(Integer, nullable=False, default=0)
    referral_year           = Column(Integer, nullable=False, default=2025)
    updated_at              = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ZoneTokenTransactionDB(Base):
    __tablename__ = "zone_token_transactions"

    id              = Column(String, primary_key=True)   # ZTX-XXXXXXXXXX
    rider_id        = Column(String, ForeignKey("riders.id"), nullable=False, index=True)
    event_type      = Column(String, nullable=False)
    delta           = Column(Integer, nullable=False)
    balance_after   = Column(Integer, nullable=False)
    reference_id    = Column(String, nullable=True)      # policy_id, claim_id, etc.
    notes           = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# GOVERNANCE PROPOSAL & VOTE TABLES
# ─────────────────────────────────────────────

class GovernanceProposalDB(Base):
    __tablename__ = "governance_proposals"

    id                      = Column(String, primary_key=True, default=lambda: f"PROP-{uuid.uuid4().hex[:8].upper()}")
    proposer_rider_id       = Column(String, ForeignKey("riders.id"), nullable=False, index=True)
    parameter               = Column(String, nullable=False)        # GovernableParameter enum value
    proposed_value          = Column(Float, nullable=False)
    proposed_exclusion_id   = Column(String, nullable=True)
    rationale               = Column(Text, nullable=False)
    status                  = Column(String, nullable=False, default="active")
    votes_for               = Column(Integer, nullable=False, default=0)
    votes_against           = Column(Integer, nullable=False, default=0)
    weight_for              = Column(Float, nullable=False, default=0.0)
    weight_against          = Column(Float, nullable=False, default=0.0)
    quorum_reached          = Column(Boolean, nullable=False, default=False)
    supermajority_reached   = Column(Boolean, nullable=False, default=False)
    voting_ends_at          = Column(DateTime(timezone=True), nullable=False)
    executed_at             = Column(DateTime(timezone=True), nullable=True)
    execution_tx_hash       = Column(String, nullable=True)
    guardrail_block_reason  = Column(Text, nullable=True)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())


class GovernanceVoteDB(Base):
    __tablename__ = "governance_votes"
    __table_args__ = (
        UniqueConstraint("proposal_id", "rider_id", name="uq_vote_per_rider_proposal"),
    )

    id              = Column(String, primary_key=True, default=lambda: f"VOTE-{uuid.uuid4().hex[:8].upper()}")
    proposal_id     = Column(String, ForeignKey("governance_proposals.id"), nullable=False, index=True)
    rider_id        = Column(String, ForeignKey("riders.id"), nullable=False, index=True)
    support         = Column(Boolean, nullable=False)
    governance_weight = Column(Float, nullable=False)
    voted_at        = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# SOULBOUND NFT TABLE
# ─────────────────────────────────────────────

class SoulboundNFTDB(Base):
    __tablename__ = "soulbound_nfts"
    __table_args__ = (
        # One NFT per policy per week
        UniqueConstraint("policy_id", "week_number", "year", name="uq_nft_policy_week"),
    )

    token_id            = Column(String, primary_key=True, default=lambda: f"SNFT-{uuid.uuid4().hex[:12].upper()}")
    rider_zk_hash       = Column(String, nullable=False, index=True)  # ZeroKnow identity hash
    policy_id           = Column(String, ForeignKey("policies.id"), nullable=False, index=True)
    week_number         = Column(Integer, nullable=False)
    year                = Column(Integer, nullable=False)
    coverage_tier       = Column(String, nullable=False)
    zone_id             = Column(String, nullable=False)
    premium_paid        = Column(Float, nullable=False)
    max_payout          = Column(Float, nullable=False)
    was_disrupted       = Column(Boolean, nullable=False, default=False)
    payout_received     = Column(Float, nullable=False, default=0.0)
    ipfs_metadata_cid   = Column(String, nullable=True)
    chain_tx_hash       = Column(String, nullable=True)  # Hyperledger Fabric tx
    minted_at           = Column(DateTime(timezone=True), server_default=func.now())


# ─────────────────────────────────────────────
# REINSURANCE POOL TABLES
# ─────────────────────────────────────────────

class ReinsurancePositionDB(Base):
    __tablename__ = "reinsurance_positions"

    position_id             = Column(String, primary_key=True, default=lambda: f"RPOS-{uuid.uuid4().hex[:10].upper()}")
    provider_id             = Column(String, nullable=False, index=True)
    provider_type           = Column(String, nullable=False, default="institutional")
    tranche                 = Column(String, nullable=False)          # senior/mezzanine/junior
    amount_staked           = Column(Float, nullable=False)
    pool_share_pct          = Column(Float, nullable=False, default=0.0)
    expected_annual_yield_pct = Column(Float, nullable=False)
    is_active               = Column(Boolean, nullable=False, default=True)
    lock_period_days        = Column(Integer, nullable=False, default=90)
    staked_at               = Column(DateTime(timezone=True), server_default=func.now())
    unlock_at               = Column(DateTime(timezone=True), nullable=True)
    withdrawn_at            = Column(DateTime(timezone=True), nullable=True)


class ReinsuranceYieldDistributionDB(Base):
    __tablename__ = "reinsurance_yield_distributions"

    distribution_id             = Column(String, primary_key=True, default=lambda: f"RDIST-{uuid.uuid4().hex[:8].upper()}")
    period_start                = Column(DateTime(timezone=True), nullable=False)
    period_end                  = Column(DateTime(timezone=True), nullable=False)
    total_premium_inflow        = Column(Float, nullable=False)
    total_payout_outflow        = Column(Float, nullable=False)
    net_pool_income             = Column(Float, nullable=False)
    senior_yield_distributed    = Column(Float, nullable=False, default=0.0)
    mezzanine_yield_distributed = Column(Float, nullable=False, default=0.0)
    junior_yield_distributed    = Column(Float, nullable=False, default=0.0)
    distributed_at              = Column(DateTime(timezone=True), server_default=func.now())
