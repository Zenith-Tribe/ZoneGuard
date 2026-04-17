-- ============================================================
-- ZoneGuard Session 5 — Database Migration
-- Innovations 06 (DAO PremiumGov), 07 (SoulboundNFT), 08 (ZoneReinsurance)
-- Run AFTER all existing migrations (policies, riders, payouts tables must exist)
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- ZONE TOKEN TABLES
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS zone_token_balances (
    rider_id                    VARCHAR PRIMARY KEY REFERENCES riders(id) ON DELETE CASCADE,
    balance                     INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    lifetime_earned             INTEGER NOT NULL DEFAULT 0,
    lifetime_burned             INTEGER NOT NULL DEFAULT 0,
    -- Rate-limit tracking
    last_s4_checkin             TIMESTAMPTZ NULL,
    last_appeal_resolved        TIMESTAMPTZ NULL,
    referral_count_this_year    INTEGER NOT NULL DEFAULT 0,
    referral_year               INTEGER NOT NULL DEFAULT 2025,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE zone_token_balances IS 
    'Non-transferable ZONE governance token balances. No transfer() function. '
    'Governance weight = sqrt(balance) for quadratic voting.';

CREATE TABLE IF NOT EXISTS zone_token_transactions (
    id              VARCHAR PRIMARY KEY,                        -- ZTX-XXXXXXXXXX
    rider_id        VARCHAR NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    event_type      VARCHAR NOT NULL,
    delta           INTEGER NOT NULL,
    balance_after   INTEGER NOT NULL CHECK (balance_after >= 0),
    reference_id    VARCHAR NULL,                               -- policy_id, claim_id, etc.
    notes           TEXT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_zone_token_tx_rider ON zone_token_transactions(rider_id);
CREATE INDEX IF NOT EXISTS idx_zone_token_tx_created ON zone_token_transactions(created_at DESC);


-- ─────────────────────────────────────────────────────────────
-- GOVERNANCE PROPOSAL & VOTE TABLES
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS governance_proposals (
    id                      VARCHAR PRIMARY KEY DEFAULT ('PROP-' || upper(substr(md5(random()::text), 1, 8))),
    proposer_rider_id       VARCHAR NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    parameter               VARCHAR NOT NULL,       -- GovernableParameter enum value
    proposed_value          FLOAT NOT NULL,
    proposed_exclusion_id   VARCHAR NULL,           -- for EXCLUSION_ADD/REMOVE
    rationale               TEXT NOT NULL,
    status                  VARCHAR NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','passed','rejected','expired','executed','blocked')),
    votes_for               INTEGER NOT NULL DEFAULT 0,
    votes_against           INTEGER NOT NULL DEFAULT 0,
    weight_for              FLOAT NOT NULL DEFAULT 0.0,
    weight_against          FLOAT NOT NULL DEFAULT 0.0,
    quorum_reached          BOOLEAN NOT NULL DEFAULT FALSE,
    supermajority_reached   BOOLEAN NOT NULL DEFAULT FALSE,
    voting_ends_at          TIMESTAMPTZ NOT NULL,
    executed_at             TIMESTAMPTZ NULL,
    execution_tx_hash       VARCHAR NULL,
    guardrail_block_reason  TEXT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gov_proposals_status ON governance_proposals(status);
CREATE INDEX IF NOT EXISTS idx_gov_proposals_proposer ON governance_proposals(proposer_rider_id);
CREATE INDEX IF NOT EXISTS idx_gov_proposals_ends ON governance_proposals(voting_ends_at);

CREATE TABLE IF NOT EXISTS governance_votes (
    id                  VARCHAR PRIMARY KEY DEFAULT ('VOTE-' || upper(substr(md5(random()::text), 1, 8))),
    proposal_id         VARCHAR NOT NULL REFERENCES governance_proposals(id) ON DELETE CASCADE,
    rider_id            VARCHAR NOT NULL REFERENCES riders(id) ON DELETE CASCADE,
    support             BOOLEAN NOT NULL,
    governance_weight   FLOAT NOT NULL,
    voted_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_vote_per_rider_proposal UNIQUE (proposal_id, rider_id)
);

CREATE INDEX IF NOT EXISTS idx_gov_votes_proposal ON governance_votes(proposal_id);
CREATE INDEX IF NOT EXISTS idx_gov_votes_rider ON governance_votes(rider_id);


-- ─────────────────────────────────────────────────────────────
-- SOULBOUND NFT TABLE
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS soulbound_nfts (
    token_id            VARCHAR PRIMARY KEY DEFAULT ('SNFT-' || upper(substr(md5(random()::text), 1, 12))),
    rider_zk_hash       VARCHAR NOT NULL,           -- ZeroKnow identity hash (or fallback sha256)
    policy_id           VARCHAR NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    week_number         INTEGER NOT NULL CHECK (week_number BETWEEN 1 AND 53),
    year                INTEGER NOT NULL,
    coverage_tier       VARCHAR NOT NULL DEFAULT 'standard',
    zone_id             VARCHAR NOT NULL,
    premium_paid        FLOAT NOT NULL,
    max_payout          FLOAT NOT NULL,
    was_disrupted       BOOLEAN NOT NULL DEFAULT FALSE,
    payout_received     FLOAT NOT NULL DEFAULT 0.0,
    ipfs_metadata_cid   VARCHAR NULL,               -- IPFS CIDv0 of NFT metadata JSON
    chain_tx_hash       VARCHAR NULL,               -- Hyperledger Fabric MintNFT tx hash
    minted_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_nft_policy_week UNIQUE (policy_id, week_number, year)
);

CREATE INDEX IF NOT EXISTS idx_snft_zk_hash ON soulbound_nfts(rider_zk_hash);
CREATE INDEX IF NOT EXISTS idx_snft_policy ON soulbound_nfts(policy_id);
CREATE INDEX IF NOT EXISTS idx_snft_year_week ON soulbound_nfts(year DESC, week_number DESC);

COMMENT ON TABLE soulbound_nfts IS
    'Non-transferable SoulboundPolicy NFTs. One per rider per coverage week. '
    'Keyed to ZeroKnow identity hash for privacy. '
    'Accumulates into Coverage Continuity Score for DeFi composability.';


-- ─────────────────────────────────────────────────────────────
-- REINSURANCE POOL TABLES
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reinsurance_positions (
    position_id                 VARCHAR PRIMARY KEY DEFAULT ('RPOS-' || upper(substr(md5(random()::text), 1, 10))),
    provider_id                 VARCHAR NOT NULL,
    provider_type               VARCHAR NOT NULL DEFAULT 'institutional'
                                CHECK (provider_type IN ('institutional','individual','nbfc')),
    tranche                     VARCHAR NOT NULL CHECK (tranche IN ('senior','mezzanine','junior')),
    amount_staked               FLOAT NOT NULL CHECK (amount_staked > 0),
    pool_share_pct              FLOAT NOT NULL DEFAULT 0.0,
    expected_annual_yield_pct   FLOAT NOT NULL,
    is_active                   BOOLEAN NOT NULL DEFAULT TRUE,
    lock_period_days            INTEGER NOT NULL DEFAULT 90,
    staked_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    unlock_at                   TIMESTAMPTZ NULL,
    withdrawn_at                TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_rpos_provider ON reinsurance_positions(provider_id);
CREATE INDEX IF NOT EXISTS idx_rpos_tranche ON reinsurance_positions(tranche);
CREATE INDEX IF NOT EXISTS idx_rpos_active ON reinsurance_positions(is_active);

COMMENT ON TABLE reinsurance_positions IS
    'Reinsurance capital LP positions. Simplified SPV model (not full AMM). '
    'IRDAI Sandbox ref: IRDAI/SB/2024/ZG-001. '
    'Loss waterfall: junior → mezzanine → senior.';

CREATE TABLE IF NOT EXISTS reinsurance_yield_distributions (
    distribution_id                 VARCHAR PRIMARY KEY DEFAULT ('RDIST-' || upper(substr(md5(random()::text), 1, 8))),
    period_start                    TIMESTAMPTZ NOT NULL,
    period_end                      TIMESTAMPTZ NOT NULL,
    total_premium_inflow            FLOAT NOT NULL,
    total_payout_outflow            FLOAT NOT NULL,
    net_pool_income                 FLOAT NOT NULL,
    senior_yield_distributed        FLOAT NOT NULL DEFAULT 0.0,
    mezzanine_yield_distributed     FLOAT NOT NULL DEFAULT 0.0,
    junior_yield_distributed        FLOAT NOT NULL DEFAULT 0.0,
    distributed_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rdist_period ON reinsurance_yield_distributions(period_end DESC);

-- ─────────────────────────────────────────────────────────────
-- ROLLBACK (keep for safety)
-- ─────────────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS reinsurance_yield_distributions CASCADE;
-- DROP TABLE IF EXISTS reinsurance_positions CASCADE;
-- DROP TABLE IF EXISTS soulbound_nfts CASCADE;
-- DROP TABLE IF EXISTS governance_votes CASCADE;
-- DROP TABLE IF EXISTS governance_proposals CASCADE;
-- DROP TABLE IF EXISTS zone_token_transactions CASCADE;
-- DROP TABLE IF EXISTS zone_token_balances CASCADE;
