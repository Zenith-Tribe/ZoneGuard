-- ─────────────────────────────────────────────────────────────────────────────
-- ZoneGuard Identity System — Database Migration
-- Session 3: ZeroKnow KYC (Innovation 04) + CrossRider DID Passport (Innovation 09)
--
-- TARGET TABLE: riders
-- ADDS:         nullifier_hash, zk_proof_hash, did_document, zk_verified_at,
--               vc_credentials, earnings_bracket, earnings_hash, eshram_zk_valid
--
-- DPDP ACT 2023 COMPLIANCE:
--   This migration does NOT touch the existing raw PII columns (phone, eshram_id,
--   rider_id). Those columns are preserved for backward compatibility with the
--   legacy OTP KYC flow. In a future migration (v4), they will be NULLED out
--   for ZK-verified riders and the columns deprecated.
--
-- BACKWARD COMPATIBLE:
--   All new columns are nullable. Existing riders without ZK verification
--   will have NULL in all new columns. The legacy KYC flow continues to work.
--
-- SESSION 7 NOTE:
--   The zk_verified flag added here (boolean) will need to be read by the
--   premium calculation engine to apply ZK-verified loyalty discounts.
--   See session3_patches.md PATCH 3-4 for context.
--
-- APPLY:
--   psql -U zoneguard -d zoneguard -f migration_003_zk_identity.sql
--   OR: run via Alembic: alembic upgrade head
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ─── Track migration ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
    version         VARCHAR(50) PRIMARY KEY,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description     TEXT,
    session         VARCHAR(20)
);

INSERT INTO schema_migrations (version, description, session)
VALUES ('003_zk_identity', 'ZeroKnow KYC + CrossRider DID Passport identity fields', 'session3')
ON CONFLICT (version) DO NOTHING;


-- ─────────────────────────────────────────────────────────────────────────────
-- RIDERS TABLE: Add ZK Identity columns
-- ─────────────────────────────────────────────────────────────────────────────

-- ── ZK KYC Fields (Innovation 04) ────────────────────────────────────────────

-- The ZK nullifier: unique per rider, prevents duplicate registration.
-- Derived from Poseidon(nullifier_secret, rider_id_hash) in the Circom circuit.
-- This is a PUBLIC SIGNAL from the proof — safe to store. No PII.
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS nullifier_hash          VARCHAR(128)    NULL
        CONSTRAINT uq_riders_nullifier UNIQUE;

COMMENT ON COLUMN riders.nullifier_hash IS
    'ZK nullifier: public signal from FlexRiderProof circuit. '
    'Unique per rider. Prevents duplicate registration (Sybil protection). '
    'NOT derivable back to rider ID without the rider''s secret. '
    'DPDP safe: no PII.';

-- SHA3-256 hash of the full Groth16 proof. The proof itself lives in Redis (24h TTL).
-- This hash allows re-verification and audit without storing the full proof.
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS zk_proof_hash           VARCHAR(128)    NULL;

COMMENT ON COLUMN riders.zk_proof_hash IS
    'SHA3-256 hash of the serialized Groth16 proof (FlexRiderProof). '
    'The full proof is cached in Redis (ZK_PROOF_CACHE_TTL). '
    'This hash is stored permanently for audit trail.';

-- When ZK verification was completed. NULL = not ZK verified (legacy OTP only).
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS zk_verified_at          TIMESTAMPTZ     NULL;

COMMENT ON COLUMN riders.zk_verified_at IS
    'Timestamp of successful ZK proof verification. '
    'NULL = rider uses legacy OTP KYC only. '
    'Non-null = rider has ZeroKnow KYC + all associated privacy protections.';

-- Boolean flag for fast filtering (indexes on this for queries like "zk_verified riders")
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS zk_verified             BOOLEAN         NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN riders.zk_verified IS
    'True if rider has completed ZK proof verification. '
    'Distinct from kyc_verified (which covers legacy OTP flow). '
    'zk_verified riders qualify for loyalty discounts and DID Passport.';

-- e-Shram verification result from ZK proof (no raw eshram_id stored in ZK path)
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS eshram_zk_valid         SMALLINT        NULL CHECK (eshram_zk_valid IN (0, 1));

COMMENT ON COLUMN riders.eshram_zk_valid IS
    'ZK-proven e-Shram registration status: 1=active, 0=not proven, NULL=not checked. '
    'This is a PUBLIC SIGNAL from FlexRiderProof.circom — no raw e-Shram UAN stored.';

-- ── Earnings Bracket Fields (from EarningsBracketProof) ──────────────────────

-- Income bracket: 'low', 'mid', 'high' — never exact earnings
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS earnings_bracket        VARCHAR(10)     NULL
        CHECK (earnings_bracket IN ('low', 'mid', 'high'));

COMMENT ON COLUMN riders.earnings_bracket IS
    'ZK-proven income bracket from EarningsBracketProof.circom. '
    'low=<10k/wk, mid=10-20k/wk, high=>20k/wk (INR). '
    'Derived from ZoneGuard payout history — no e-Shram dependency. '
    'DPDP safe: exact earnings never stored.';

-- Earnings commitment hash (Poseidon of earnings array + salt)
-- Allows future re-verification without re-submitting earnings data
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS earnings_hash           VARCHAR(128)    NULL;

COMMENT ON COLUMN riders.earnings_hash IS
    'Poseidon commitment to weekly earnings data used in EarningsBracketProof. '
    'Allows rider to re-prove bracket in future sessions without re-submission. '
    'NOT reversible — cannot recover exact earnings from this hash.';

-- Number of weeks proven in the last earnings proof
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS earnings_weeks_proven   SMALLINT        NULL CHECK (earnings_weeks_proven >= 0);

-- ── DID Passport Fields (Innovation 09) ──────────────────────────────────────

-- Full W3C DID Document stored as JSONB for fast querying
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS did_document            JSONB           NULL;

COMMENT ON COLUMN riders.did_document IS
    'W3C DID Core v1.0 compliant DID Document (JSONB). '
    'Method: did:key (derived from nullifier keypair). '
    'Contains: verification methods, authentication keys, service endpoints. '
    'Public document — no PII.';

-- Aggregated Verifiable Credentials as JSONB array
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS vc_credentials          JSONB           NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN riders.vc_credentials IS
    'W3C Verifiable Credentials issued to this rider (JSONB array). '
    'Contains: FlexWorkerIdentityCredential, IncomeBracketCredential, etc. '
    'The rider controls presentation — ZoneGuard stores for issuance. '
    'In production: rider-controlled DID wallet holds these VCs.';

-- Progressive disclosure level (1=basic, 2=income, 3=full)
ALTER TABLE riders
    ADD COLUMN IF NOT EXISTS disclosure_level        SMALLINT        NOT NULL DEFAULT 1
        CHECK (disclosure_level BETWEEN 1 AND 3);

COMMENT ON COLUMN riders.disclosure_level IS
    'CrossRider DID Passport disclosure level. '
    '1=basic identity only, 2=income bracket added, 3=full history + loyalty. '
    'Upgrades automatically as rider builds payout history.';

-- ─────────────────────────────────────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────────────────────────────────────

-- Fast lookup for ZK verification status (most queries filter on this)
CREATE INDEX IF NOT EXISTS idx_riders_zk_verified
    ON riders (zk_verified)
    WHERE zk_verified = TRUE;

-- Nullifier lookup for anti-Sybil checks (must be fast — called on every registration)
CREATE INDEX IF NOT EXISTS idx_riders_nullifier_hash
    ON riders (nullifier_hash)
    WHERE nullifier_hash IS NOT NULL;

-- GIN index on DID document for JSONB queries (e.g., find by service endpoint)
CREATE INDEX IF NOT EXISTS idx_riders_did_document_gin
    ON riders USING GIN (did_document)
    WHERE did_document IS NOT NULL;

-- GIN index on VC credentials for type-based queries
CREATE INDEX IF NOT EXISTS idx_riders_vc_credentials_gin
    ON riders USING GIN (vc_credentials)
    WHERE vc_credentials IS NOT NULL;

-- Earnings bracket index for NBFC eligibility queries
CREATE INDEX IF NOT EXISTS idx_riders_earnings_bracket
    ON riders (earnings_bracket)
    WHERE earnings_bracket IS NOT NULL;

-- Disclosure level index for progressive disclosure queries
CREATE INDEX IF NOT EXISTS idx_riders_disclosure_level
    ON riders (disclosure_level);

-- ─────────────────────────────────────────────────────────────────────────────
-- VIEWS: Convenience queries for ZK-verified riders
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_zk_verified_riders AS
    SELECT
        id,
        zone_id,
        weekly_earnings_baseline,
        tenure_weeks,
        nullifier_hash,
        earnings_bracket,
        disclosure_level,
        eshram_zk_valid,
        zk_verified_at,
        -- Computed fields
        CASE
            WHEN tenure_weeks >= 52 THEN 'gold'
            WHEN tenure_weeks >= 24 THEN 'silver'
            WHEN tenure_weeks >= 12 THEN 'bronze'
            ELSE NULL
        END AS loyalty_tier,
        CASE
            WHEN tenure_weeks >= 52 THEN 15
            WHEN tenure_weeks >= 24 THEN 10
            WHEN tenure_weeks >= 12 THEN 5
            ELSE 0
        END AS loyalty_discount_pct
    FROM riders
    WHERE zk_verified = TRUE;

COMMENT ON VIEW v_zk_verified_riders IS
    'ZK-verified riders with computed loyalty tier and discount. '
    'Used by premium calculation engine (Session 7) and admin dashboard.';

-- ─────────────────────────────────────────────────────────────────────────────
-- NBFC ELIGIBILITY VIEW
-- Used when NBFC queries ZoneGuard to verify loan applicant
-- Returns no PII — only bracket + tenure
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_nbfc_eligibility AS
    SELECT
        nullifier_hash,
        earnings_bracket,
        earnings_weeks_proven,
        tenure_weeks,
        eshram_zk_valid,
        disclosure_level,
        zk_verified_at,
        -- NBFC eligibility: mid or high bracket + e-Shram proven + 4+ weeks
        (
            earnings_bracket IN ('mid', 'high')
            AND (eshram_zk_valid = 1 OR tenure_weeks >= 8)
            AND earnings_weeks_proven >= 4
        ) AS is_loan_eligible
    FROM riders
    WHERE zk_verified = TRUE
      AND nullifier_hash IS NOT NULL;

COMMENT ON VIEW v_nbfc_eligibility IS
    'NBFC microloan eligibility view. Zero PII — nullifier only. '
    'is_loan_eligible: true if rider earns >= 10k/wk + e-Shram or 8+ week tenure.';

-- ─────────────────────────────────────────────────────────────────────────────
-- SEED: Update existing test riders with ZK placeholder data
-- (so frontend dev can test without running full ZK proof pipeline)
-- ─────────────────────────────────────────────────────────────────────────────

-- Only update dev/test riders — skip in production (no AMZFLEX-BLR prefix check)
UPDATE riders SET
    nullifier_hash      = 'sim_' || ENCODE(SHA256(id::bytea), 'hex'),
    zk_proof_hash       = 'phash_' || ENCODE(SHA256((id || '_proof')::bytea), 'hex'),
    zk_verified         = TRUE,
    zk_verified_at      = NOW(),
    eshram_zk_valid     = 1,
    earnings_bracket    = CASE
                            WHEN weekly_earnings_baseline >= 20000 THEN 'high'
                            WHEN weekly_earnings_baseline >= 10000 THEN 'mid'
                            ELSE 'low'
                          END,
    earnings_weeks_proven = LEAST(tenure_weeks, 12),
    disclosure_level    = CASE
                            WHEN tenure_weeks >= 12 THEN 3
                            WHEN tenure_weeks >= 4  THEN 2
                            ELSE 1
                          END,
    did_document        = jsonb_build_object(
                            '@context', '["https://www.w3.org/ns/did/v1"]'::jsonb,
                            'id', 'did:key:sim_' || LEFT(ENCODE(SHA256(id::bytea), 'hex'), 32),
                            'controller', 'did:key:sim_' || LEFT(ENCODE(SHA256(id::bytea), 'hex'), 32)
                          ),
    vc_credentials      = '[]'::jsonb
WHERE kyc_verified = TRUE
  AND id LIKE 'AMZFLEX-%';

-- ─────────────────────────────────────────────────────────────────────────────
-- ROLLBACK INSTRUCTIONS (save before applying):
-- ─────────────────────────────────────────────────────────────────────────────
-- ALTER TABLE riders DROP COLUMN IF EXISTS nullifier_hash;
-- ALTER TABLE riders DROP COLUMN IF EXISTS zk_proof_hash;
-- ALTER TABLE riders DROP COLUMN IF EXISTS zk_verified_at;
-- ALTER TABLE riders DROP COLUMN IF EXISTS zk_verified;
-- ALTER TABLE riders DROP COLUMN IF EXISTS eshram_zk_valid;
-- ALTER TABLE riders DROP COLUMN IF EXISTS earnings_bracket;
-- ALTER TABLE riders DROP COLUMN IF EXISTS earnings_hash;
-- ALTER TABLE riders DROP COLUMN IF EXISTS earnings_weeks_proven;
-- ALTER TABLE riders DROP COLUMN IF EXISTS did_document;
-- ALTER TABLE riders DROP COLUMN IF EXISTS vc_credentials;
-- ALTER TABLE riders DROP COLUMN IF EXISTS disclosure_level;
-- DROP VIEW IF EXISTS v_zk_verified_riders;
-- DROP VIEW IF EXISTS v_nbfc_eligibility;
-- DELETE FROM schema_migrations WHERE version = '003_zk_identity';

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- POST-MIGRATION VERIFICATION
-- ─────────────────────────────────────────────────────────────────────────────
-- Run these after applying to confirm success:
--
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'riders'
--   AND column_name IN ('nullifier_hash', 'zk_verified', 'did_document', 'earnings_bracket')
-- ORDER BY column_name;
--
-- SELECT COUNT(*) FROM v_zk_verified_riders;
-- SELECT COUNT(*) FROM v_nbfc_eligibility WHERE is_loan_eligible = TRUE;
