## session1_patches.md
# Session 1 Patches
## ZoneChain (Innovation 01) + TemporalSig (Innovation 10)
## DO NOT apply these manually — coordinate with the session integration lead.

---

## PATCH 1-1
### Target File: `backend/main.py`
### Location: After the line `from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo`
### Action: INSERT
### Code:
```python
from blockchain import router as blockchain_router
from blockchain.fabric_client import init_fabric_client, shutdown_fabric_client
from blockchain.temporalsig import init_temporalsig_client, shutdown_temporalsig_client
```
### Reason: Import blockchain router and lifecycle managers.
### Conflicts With: Session 7 — if Session 7 adds imports in the same block, insert after theirs to avoid merge conflict. Both import blocks are independent.

---

## PATCH 1-2
### Target File: `backend/main.py`
### Location: Inside the `lifespan` async context manager, AFTER `start_scheduler()` and BEFORE `yield`
### Action: INSERT
```python
        # Initialize blockchain clients (Innovation 01 + 10)
        await init_fabric_client()
        await init_temporalsig_client()
        logger.info("ZoneChain (Fabric) and TemporalSig (Polygon) clients initialized")
```
### Reason: Establishes Fabric gRPC connection and Polygon web3 connection at app startup. Both are async and non-blocking — they enter stub mode gracefully if external services are unavailable.
### Conflicts With: Session 7 — if Session 7 also adds lifespan startup hooks, insert after theirs. Order does not matter between sessions for independent services.

---

## PATCH 1-3
### Target File: `backend/main.py`
### Location: Inside the `lifespan` async context manager, AFTER `stop_scheduler()` and BEFORE the final logger line
### Action: INSERT
```python
        # Shutdown blockchain clients
        await shutdown_fabric_client()
        await shutdown_temporalsig_client()
```
### Reason: Graceful shutdown — closes gRPC channel to Fabric peer and clears Polygon web3 connection.
### Conflicts With: None expected. Shutdown order is independent.

---

## PATCH 1-4
### Target File: `backend/main.py`
### Location: After the last `app.include_router(demo.router)` line
### Action: INSERT
```python
app.include_router(blockchain_router.router)
```
### Reason: Registers the blockchain API endpoints at /api/v1/blockchain.
### Update root() endpoint: Add `"blockchain": "/api/v1/blockchain"` to the `endpoints` dict in the root() response so the API index reflects the new router.
### Conflicts With: Session 7 — if Session 7 adds routers in the same block, just add after theirs. These are independent include_router calls.

---

## PATCH 1-5
### Target File: `backend/routers/claims.py`
### Location: At the top of the file, after existing imports
### Action: INSERT
```python
# ZoneChain integration (Innovation 01)
from blockchain.zonechain import ZoneChainClient, get_zonechain_client, ChainEventType, ConfidenceTier
from blockchain.temporalsig import get_temporalsig_client
```
### Reason: Claims router needs access to ZoneChainClient to write claim lifecycle events to Fabric.
### Conflicts With: Any session that also patches claims.py imports. Insert after their imports, before the router definition.

---

## PATCH 1-6
### Target File: `backend/routers/claims.py`
### Location: In the claim creation endpoint (POST /), after `await db.commit()` and `await db.refresh(claim)` — the last lines of the creation handler before `return`
### Action: INSERT
```python
    # ZoneChain: Record claim creation event (fire-and-forget, non-blocking)
    import asyncio
    zonechain = get_zonechain_client()
    asyncio.create_task(
        zonechain.write_claim_event(
            claim_id=str(claim.id),
            rider_id=str(claim.rider_id),
            policy_id=str(claim.policy_id),
            zone_id=str(claim.zone_id),
            event_type=ChainEventType.CLAIM_CREATED,
            confidence_tier=ConfidenceTier(claim.confidence_tier.upper()),
            composite_score=float(claim.composite_score or 0.0),
        )
    )
```
### Reason: Every new claim is recorded on ZoneChain at the moment of creation. `asyncio.create_task` ensures the API response is not delayed by the Fabric write (which may take 1-3 seconds).
### Conflicts With: Session 3 (if exists) — if another session wraps claim creation in a transaction, ensure ZoneChain write is OUTSIDE the DB transaction block (it should be, as it comes after commit()).
### IMPORTANT: The exact variable name for the new claim object may differ in your codebase (e.g., `claim`, `new_claim`, `db_claim`). Adjust accordingly after reading the actual endpoint.

---

## PATCH 1-7
### Target File: `backend/routers/claims.py`
### Location: In the claim approval endpoint (the endpoint that sets claim status to "approved" and triggers payout), after `await db.commit()`
### Action: INSERT
```python
    # ZoneChain: Record approval + payout trigger
    import asyncio
    zonechain = get_zonechain_client()
    asyncio.create_task(
        zonechain.write_claim_event(
            claim_id=claim_id,
            rider_id=str(claim.rider_id),
            policy_id=str(claim.policy_id),
            zone_id=str(claim.zone_id),
            event_type=ChainEventType.CLAIM_APPROVED,
            confidence_tier=ConfidenceTier(claim.confidence_tier.upper()),
            composite_score=float(claim.composite_score or 0.0),
            payout_amount_inr=float(claim.payout_amount or 0.0),
        )
    )
```
### Reason: Approval events are the most legally significant — they record the exact approved payout amount on an immutable ledger co-signed by the insurer peer.
### Conflicts With: Same as PATCH 1-6 — must be outside DB transaction, after commit.

---

## PATCH 1-8
### Target File: `docker-compose.yml`
### Location: Under the `backend:` service `environment:` block, after the last env var (`GEMINI_API_KEY`)
### Action: INSERT
```yaml
            # Innovation 01: ZoneChain (Hyperledger Fabric)
            - FABRIC_GATEWAY_URL=${FABRIC_GATEWAY_URL:-localhost:7051}
            - FABRIC_CHANNEL=${FABRIC_CHANNEL:-zoneguard-channel}
            - FABRIC_CHAINCODE=${FABRIC_CHAINCODE:-zoneguard-cc}
            - FABRIC_MSP_ID=${FABRIC_MSP_ID:-ZoneGuardMSP}
            - FABRIC_CERT_PEM=${FABRIC_CERT_PEM:-}
            - FABRIC_PRIVATE_KEY_PEM=${FABRIC_PRIVATE_KEY_PEM:-}
            - FABRIC_TLS_CERT_PEM=${FABRIC_TLS_CERT_PEM:-}
            - FABRIC_PEER_HOSTNAME=${FABRIC_PEER_HOSTNAME:-peer0.org1.example.com}
            # Innovation 10: TemporalSig (Polygon L2)
            - POLYGON_RPC_URL=${POLYGON_RPC_URL:-https://rpc-amoy.polygon.technology}
            - POLYGON_PRIVATE_KEY=${POLYGON_PRIVATE_KEY:-}
            - POLYGON_NETWORK=${POLYGON_NETWORK:-amoy}
            - TEMPORALSIG_CONTRACT_ADDRESS=${TEMPORALSIG_CONTRACT_ADDRESS:-}
```
### Reason: All blockchain config is via environment variables — secrets never hardcoded. Empty defaults mean both blockchain systems enter stub mode gracefully in dev.
### Conflicts With: Any session adding env vars to the backend service. Safe to append — env blocks are additive in Docker Compose.

---

## PATCH 1-9
### Target File: `docker-compose.yml`
### Location: Under `services:`, after the `redis:` service block (before `volumes:`)
### Action: INSERT
```yaml
    # ---- ZoneChain: Hyperledger Fabric (optional, for local dev) ----
    # Uncomment to run a local Fabric network. In staging/production,
    # point FABRIC_GATEWAY_URL to your deployed Fabric peer.
    #
    # fabric-peer:
    #   image: hyperledger/fabric-peer:2.5
    #   environment:
    #     - CORE_PEER_ID=peer0.org1.zoneguard.local
    #     - CORE_PEER_ADDRESS=peer0.org1.zoneguard.local:7051
    #     - CORE_PEER_LOCALMSPID=ZoneGuardMSP
    #   ports:
    #     - "7051:7051"
    #   volumes:
    #     - ./fabric-config:/etc/hyperledger/fabric
    #
    # ---- TemporalSig: Polygon (no local service needed) ----
    # TemporalSig connects to Polygon Amoy testnet via RPC URL.
    # Get a free RPC endpoint from: https://alchemy.com or https://infura.io
    # Set POLYGON_RPC_URL and POLYGON_PRIVATE_KEY in your .env file.
```
### Reason: Documents the Fabric service for local dev, kept commented to avoid breaking existing `docker compose up` for teams without Fabric installed.
### Conflicts With: None — this is comments + commented-out YAML.

---

## SUMMARY: New Environment Variables Required

Add these to your `.env` file (copy from `.env.example` if it exists):

```env
# ── ZoneChain (Hyperledger Fabric) ─────────────────────────────────────────
# Leave empty to run in STUB mode (blockchain writes are logged only)
FABRIC_GATEWAY_URL=localhost:7051
FABRIC_CHANNEL=zoneguard-channel
FABRIC_CHAINCODE=zoneguard-cc
FABRIC_MSP_ID=ZoneGuardMSP
FABRIC_CERT_PEM=
FABRIC_PRIVATE_KEY_PEM=
FABRIC_TLS_CERT_PEM=
FABRIC_PEER_HOSTNAME=peer0.org1.example.com

# ── TemporalSig (Polygon Amoy Testnet) ──────────────────────────────────────
# Leave POLYGON_PRIVATE_KEY empty to run in STUB mode
# Get Amoy MATIC from: https://faucet.polygon.technology/
POLYGON_RPC_URL=https://rpc-amoy.polygon.technology
POLYGON_PRIVATE_KEY=
POLYGON_NETWORK=amoy
TEMPORALSIG_CONTRACT_ADDRESS=
# After deploying TemporalSigAnchor.sol, set:
# TEMPORALSIG_CONTRACT_ADDRESS=0xYourDeployedContractAddress
```

## New Python Dependencies to Add

Add to `requirements.txt` (or `pyproject.toml`):

```
# Innovation 01: ZoneChain (Hyperledger Fabric)
grpcio>=1.60.0
grpcio-tools>=1.60.0
# fabric-protos-py>=0.3.0   # Uncomment when Fabric network is live

# Innovation 10: TemporalSig (Polygon L2)
web3>=6.15.0
pysha3>=1.0.2               # True keccak256 (not sha3_256)
```

## New Files Created (Session 1 owns these entirely)

```
backend/blockchain/__init__.py
backend/blockchain/models.py
backend/blockchain/fabric_client.py
backend/blockchain/zonechain.py
backend/blockchain/temporalsig.py
backend/blockchain/router.py
frontend/src/components/ZoneChainExplorer/index.tsx
contracts/TemporalSigAnchor.sol
```

## Warnings and Enhancements

### [WARNING] keccak256 hash fallback
`models.py` SignalBatchPayload.keccak256_hash uses `pysha3` for true keccak256.
If `pysha3` is not installed it falls back to `sha256` with a `0xsha256:` prefix marker.
The smart contract uses `bytes32` — the sha256 fallback produces a different hash
and WILL NOT VERIFY on-chain. Install `pysha3` before deploying to production.

### [WARNING] Fabric stub mode in production
`fabric_client.py` enters stub mode if `grpcio` is not installed OR if Fabric is
unreachable. Stub mode logs all writes but does NOT commit to the ledger.
Monitor `/api/v1/blockchain/status` — `fabric_connected: false` means you're in stub mode.

### [WARNING] POLYGON_PRIVATE_KEY security
Never commit `POLYGON_PRIVATE_KEY` to git. Use Docker secrets or a secrets manager
(AWS Secrets Manager / HashiCorp Vault) in production. The wallet only needs ~1 MATIC
for months of anchoring at $0.0001/anchor × 96 anchors/day × 30 days = ~$0.29/month.

### [WARNING] Claims router patch — variable name assumption
PATCH 1-6 and 1-7 assume the claim object is named `claim` and has attributes
`rider_id`, `policy_id`, `zone_id`, `confidence_tier`, `composite_score`, `payout_amount`.
Verify these against the actual claims.py before applying. The existing codebase
was read in stub (the file was truncated in session1_context.md).

### [ENHANCEMENT] Dead-letter queue for failed Fabric writes
`zonechain.py` logs failed writes with `PAYLOAD_FOR_REPLAY=` prefix. In production,
push failed payloads to a Redis Stream (`XADD zoneguard:blockchain:dlq`) so a
background worker can retry them without losing data.

### [ENHANCEMENT] PostgreSQL mirror for TemporalSig anchors
Add a `temporal_sig_anchors` table to PostgreSQL that mirrors every Polygon anchor.
This enables fast `get_anchor_for_event()` queries without RPC calls.
Suggested schema:
```sql
CREATE TABLE temporal_sig_anchors (
    anchor_id       UUID PRIMARY KEY,
    batch_id        UUID NOT NULL,
    zone_id         VARCHAR(50) NOT NULL,
    keccak256_hash  VARCHAR(66) NOT NULL UNIQUE,
    polygon_tx_hash VARCHAR(66),
    polygon_block   INTEGER,
    block_timestamp TIMESTAMPTZ,
    polygon_network VARCHAR(20) DEFAULT 'amoy',
    gas_used        INTEGER,
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    confirmed_at    TIMESTAMPTZ,
    error_message   TEXT
);
CREATE INDEX idx_tsig_zone_id ON temporal_sig_anchors(zone_id);
CREATE INDEX idx_tsig_batch_id ON temporal_sig_anchors(batch_id);
CREATE INDEX idx_tsig_block_ts ON temporal_sig_anchors(block_timestamp DESC);
```

### [ENHANCEMENT] TemporalSig scheduler integration
Hook `temporalsig.anchor_signal_batch(batch)` into the existing APScheduler job
in `services/scheduler.py` — specifically at the END of each 15-minute signal
fusion cycle, after composite score calculation and BEFORE claim evaluation.
This ensures every signal reading has an immutable timestamp before any claim
decision is made from it.

### [ENHANCEMENT] ZoneChainExplorer compact mode
The `ZoneChainExplorer` component supports `compact={true}` for embedding as a
dashboard card. Use it in the RiderDashboard claim cards:
```tsx
<ZoneChainExplorer claimId={claim.id} compact />
```
Full-page mode (default) is used for the dedicated dispute resolution view.
## session2_patches.md
# Session 2 Patches — SmartPolicy Contracts + ChainOracle Network

All patches to conflict-protected shared files are documented here.
Session 2 does NOT directly edit these files.
Session 7 (integration) should apply these patches in order.

---

## PATCH 2-1
### Target File: `backend/main.py`
### Location: After line containing → `from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo`
### Action: INSERT
### Code:
```python
from oracle.oracle_health import oracle_health_router
```
### Reason: Register the oracle health monitoring router so /api/v1/oracle/health is available.
### Conflicts With: Session 7 — check that no other session also imports from oracle.oracle_health. If so, merge the import lines.

---

## PATCH 2-2
### Target File: `backend/main.py`
### Location: After line containing → `app.include_router(demo.router)`
### Action: INSERT
### Code:
```python
app.include_router(oracle_health_router)
```
### Reason: Mount the oracle health dashboard router onto the FastAPI app.
### Conflicts With: Session 7 — ensure ordering of include_router calls is consistent.

---

## PATCH 2-3
### Target File: `backend/main.py`
### Location: After line containing → `checks["openweathermap"] = {`
### Action: REPLACE (replace the entire openweathermap check block, 4 lines)

Replace:
```python
    # Weather API key
    checks["openweathermap"] = {
        "status": "ok" if settings.openweathermap_api_key else "missing",
        "has_key": bool(settings.openweathermap_api_key),
    }
```

With:
```python
    # Weather API key (primary oracle node)
    checks["openweathermap"] = {
        "status": "ok" if settings.openweathermap_api_key else "missing",
        "has_key": bool(settings.openweathermap_api_key),
    }

    # Oracle network keys
    import os
    checks["oracle_imd"] = {
        "status": "ok" if os.getenv("IMD_API_KEY") else "missing",
        "has_key": bool(os.getenv("IMD_API_KEY")),
    }
    checks["oracle_accuweather"] = {
        "status": "ok" if os.getenv("ACCUWEATHER_API_KEY") else "missing",
        "has_key": bool(os.getenv("ACCUWEATHER_API_KEY")),
    }
    checks["oracle_google_mobility"] = {
        "status": "ok" if os.getenv("GOOGLE_MOBILITY_API_KEY") else "missing",
        "has_key": bool(os.getenv("GOOGLE_MOBILITY_API_KEY")),
    }
```
### Reason: Expose all oracle API key health checks in /health/detailed so ops teams can see which oracle nodes are configured.
### Conflicts With: Session 7 — if other sessions add their own health checks, merge the check dicts rather than replacing.

---

## PATCH 2-4
### Target File: `backend/routers/policies.py`
### Location: After line containing → `import uuid`
### Action: INSERT
### Code:
```python
import asyncio
import logging

_policy_chaincode_logger = logging.getLogger("chaincode.policy")

# Lazy import to avoid circular dependency at startup.
# fabric_client.py is provided by the blockchain session and may not exist yet.
def _get_policy_sdk():
    try:
        from chaincode.chaincode_sdk import policy_sdk
        return policy_sdk
    except ImportError:
        _policy_chaincode_logger.warning(
            "chaincode_sdk not available — policy will not be recorded on-chain. "
            "This is expected in dev/test before ZoneChain is running."
        )
        return None
```
### Reason: Import the PolicySDK lazily so the router starts even if the blockchain SDK is not yet installed.
### Conflicts With: Session 7 — if another session also imports from chaincode_sdk in policies.py, consolidate into one import block.

---

## PATCH 2-5
### Target File: `backend/routers/policies.py`
### Location: After line containing → `await db.commit()`  (in `create_policy`, the FIRST db.commit)
### Action: INSERT
### Code:
```python
    # ── SmartPolicy: Record policy on-chain (Innovation 02) ──────────────────
    # Fire-and-forget: chaincode write does not block the API response.
    # If the blockchain is unavailable, the policy is still created in PostgreSQL
    # and will be reconciled by the background sync job.
    _policy_sdk = _get_policy_sdk()
    if _policy_sdk:
        async def _write_policy_on_chain():
            try:
                await _policy_sdk.create_policy(
                    policy_id=policy.id,
                    rider_id=str(policy.rider_id),
                    zone_id=str(policy.zone_id),
                    weekly_premium=float(policy.weekly_premium),
                    max_payout=float(policy.max_payout),
                    coverage_start=policy.coverage_start.isoformat(),
                    coverage_end=policy.coverage_end.isoformat(),
                    is_forward_locked=bool(policy.is_forward_locked),
                    forward_lock_weeks=int(policy.forward_lock_weeks or 0),
                )
                _policy_chaincode_logger.info(f"Policy {policy.id} recorded on-chain")
            except Exception as exc:
                _policy_chaincode_logger.error(
                    f"Policy {policy.id} chaincode write failed (will reconcile): {exc}"
                )
        asyncio.create_task(_write_policy_on_chain())
    # ─────────────────────────────────────────────────────────────────────────
```
### Reason: Write every new policy to PolicyChaincode on creation. Uses create_task so the API response is not delayed by Fabric network latency.
### Conflicts With:
- Session 7: if another session's patch also hooks into create_policy after db.commit(), ensure both create_task calls are preserved — they are independent.
- Session 5 (premium): if premium calculation changes weekly_premium before this point, our chaincode write picks up the correct final value because it reads from policy.weekly_premium after flush.

---

## PATCH 2-6
### Target File: `backend/routers/policies.py`
### Location: After line containing → `await db.commit()` (in `renew_policy`)
### Action: INSERT
### Code:
```python
    # ── SmartPolicy: Record renewal on-chain ─────────────────────────────────
    _policy_sdk = _get_policy_sdk()
    if _policy_sdk:
        async def _renew_on_chain():
            try:
                await _policy_sdk.renew_policy(
                    policy_id=policy_id,
                    new_coverage_start=new_policy.coverage_start.isoformat(),
                    new_coverage_end=new_policy.coverage_end.isoformat(),
                )
                _policy_chaincode_logger.info(f"Policy {policy_id} renewal recorded on-chain → {new_policy.id}")
            except Exception as exc:
                _policy_chaincode_logger.error(f"Policy renewal chaincode write failed: {exc}")
        asyncio.create_task(_renew_on_chain())
    # ─────────────────────────────────────────────────────────────────────────
```
### Reason: Keep the on-chain forward-lock countdown in sync with off-chain renewal.
### Conflicts With: Session 7 — same pattern as PATCH 2-5, independent create_task.

---

## PATCH 2-7
### Target File: `backend/routers/claims.py`
### Location: After line containing → `from datetime import datetime, timezone`
### Action: INSERT
### Code:
```python
import asyncio
import hashlib
import logging

_claim_chaincode_logger = logging.getLogger("chaincode.claim")

def _get_claim_sdk():
    try:
        from chaincode.chaincode_sdk import claim_sdk
        return claim_sdk
    except ImportError:
        _claim_chaincode_logger.warning(
            "chaincode_sdk not available — claims will not be recorded on-chain."
        )
        return None
```
### Reason: Lazy import of ClaimSDK, same pattern as policies.
### Conflicts With: Session 7 — consolidate with any other chaincode imports in claims.py.

---

## PATCH 2-8
### Target File: `backend/routers/claims.py`
### Location: After line containing → `payout_result = None` (inside `review_claim`, before `if payload.action == "approve":`)
### Action: INSERT
### Code:
```python
    # ── SmartPolicy: Record fraud score on-chain before any payout decision ──
    # The fraud score must be committed to chain BEFORE approval so it is
    # cryptographically immutable. This is a synchronous wait — we need the
    # fraud_auto_reject result before deciding whether to proceed with approval.
    _claim_sdk = _get_claim_sdk()
    chain_claim = None
    if _claim_sdk and claim.fraud_score is not None:
        try:
            chain_claim = await _claim_sdk.record_fraud_score(
                claim_id=claim_id,
                fraud_score=float(claim.fraud_score),
                recorded_by=payload.reviewed_by,
            )
            # If chaincode auto-rejected due to fraud, override the payload action
            if chain_claim.get("fraud_auto_rejected"):
                _claim_chaincode_logger.warning(
                    f"Claim {claim_id}: FraudShield on-chain auto-reject. "
                    f"Overriding reviewer action to 'reject'."
                )
                payload.action = "reject"
                claim.status = "rejected"
                claim.reviewed_at = datetime.now(timezone.utc)
                claim.reviewed_by = "FraudShield-OnChain"
                await db.commit()
                return {
                    "status": "rejected",
                    "claim_id": claim_id,
                    "reason": "FraudShield on-chain auto-reject",
                    "fraud_score": claim.fraud_score,
                    "chain_tx": chain_claim.get("tx_id"),
                    "payout": None,
                }
        except Exception as exc:
            _claim_chaincode_logger.error(f"Fraud score chaincode write failed for {claim_id}: {exc}")
            # Do not block approval — log and continue. Reconciliation job will retry.
    # ─────────────────────────────────────────────────────────────────────────
```
### Reason: Ensures fraud score is written to chain before payout — makes fraud decisions immutable and auditable. Also implements the on-chain auto-reject override.
### Conflicts With:
- Session 6 (FraudShield): Session 6 writes claim.fraud_score to the DB. Our patch reads it. Ensure Session 6's fraud score write happens BEFORE review_claim is called (it should, as fraud scoring happens during trigger, not review).
- Session 7: This patch must come BEFORE the approval block. Check patch ordering.

---

## PATCH 2-9
### Target File: `backend/routers/claims.py`
### Location: After line containing → `payout_result["status"] == "settled"` block (i.e., after `db.add(payout)`) inside the approve block
### Action: INSERT
### Code:
```python
            # ── SmartPolicy: Approve claim on-chain with UPI hash ────────────
            if _claim_sdk:
                upi_ref = payout_result.get("upi_ref", "")
                async def _approve_on_chain():
                    try:
                        await _claim_sdk.approve_claim(
                            claim_id=claim_id,
                            reviewed_by=payload.reviewed_by,
                            upi_ref=upi_ref,  # SDK hashes this before writing
                        )
                        _claim_chaincode_logger.info(
                            f"Claim {claim_id} approved on-chain. "
                            f"UPI hash recorded (not raw ref)."
                        )
                    except Exception as exc:
                        _claim_chaincode_logger.error(f"Claim approval chaincode write failed: {exc}")
                asyncio.create_task(_approve_on_chain())
            # ────────────────────────────────────────────────────────────────
```
### Reason: Records the approved claim and UPI reference hash on-chain. The raw UPI string is hashed by ClaimSDK.approve_claim — only the SHA-256 fingerprint goes to the ledger (PII protection).
### Conflicts With: Session 7 — ensure this create_task is inside the `if payload.action == "approve":` block. The indentation must match the existing payout block.

---

## PATCH 2-10
### Target File: `backend/routers/claims.py`
### Location: After line containing → `audit = AuditLog(` block inside `review_claim` (the rejection path)
### Action: INSERT (after the `else` block where claim.status = "rejected")
### Code:
```python
    # ── SmartPolicy: Reject claim on-chain ───────────────────────────────────
    if payload.action == "reject" and _claim_sdk:
        async def _reject_on_chain():
            try:
                await _claim_sdk.reject_claim(
                    claim_id=claim_id,
                    reviewed_by=payload.reviewed_by,
                    reason=getattr(payload, "rejection_reason", "Manual rejection by reviewer"),
                )
                _claim_chaincode_logger.info(f"Claim {claim_id} rejection recorded on-chain.")
            except Exception as exc:
                _claim_chaincode_logger.error(f"Claim rejection chaincode write failed: {exc}")
        asyncio.create_task(_reject_on_chain())
    # ─────────────────────────────────────────────────────────────────────────
```
### Reason: Immutably records rejections on-chain so riders can verify their claim was rejected (not silently dropped).
### Conflicts With: Session 7 — same fire-and-forget pattern.

---

## PATCH 2-11
### Target File: `backend/integrations/weather.py`
### Location: After line containing → `logger = logging.getLogger(__name__)`
### Action: INSERT
### Code:
```python
import os
_ORACLE_MODE = os.getenv("ORACLE_MODE", "false").lower() == "true"
```
### Reason: Feature flag to switch between legacy single-OWM mode and oracle consensus mode without requiring code changes.
### Conflicts With: Session 7 — if another session also adds an ORACLE_MODE flag, consolidate into config.py settings.

---

## PATCH 2-12
### Target File: `backend/integrations/weather.py`
### Location: After line containing → `async def get_current_weather(lat: float, lng: float) -> dict:`
### Action: INSERT (at the very top of the function body, before the `settings = get_settings()` line)
### Code:
```python
    # ── ChainOracle mode: use multi-source consensus instead of single OWM ──
    if _ORACLE_MODE:
        try:
            from oracle.aggregator import get_aggregator
            from oracle.models import ConsensusStatus
            aggregator = get_aggregator()
            consensus = await aggregator.get_s1_consensus(lat=lat, lng=lng)
            if consensus.status == ConsensusStatus.ACCEPTED and consensus.aggregated_value:
                return {
                    **consensus.aggregated_value,
                    "source": "oracle_consensus",
                    "consensus_ref": consensus.consensus_ref,
                    "agreeing_nodes": consensus.agreeing_sources,
                }
            else:
                logger.warning(
                    f"get_current_weather: S1 oracle consensus not reached "
                    f"({consensus.nodes_agreed}/{consensus.nodes_polled} nodes agreed, "
                    f"need {consensus.threshold_required}). "
                    f"Falling back to single-source OWM."
                )
                # Fall through to single-source OWM below
        except Exception as exc:
            logger.error(f"get_current_weather: Oracle aggregator error: {exc}. Falling back to OWM.")
            # Fall through to single-source OWM below
    # ─────────────────────────────────────────────────────────────────────────
```
### Reason:
- When ORACLE_MODE=true, uses 3/4 consensus before returning weather data.
- If consensus fails (insufficient nodes, all failed), gracefully falls back to single OWM source.
- This is the [ENHANCEMENT] INSUFFICIENT_CONSENSUS fallback pattern: never crash the signal pipeline.
- The `source` field in the returned dict indicates whether consensus or fallback was used, so signal_fusion and audit logs can record provenance.
### Conflicts With:
- Session 4 (QuadSignal / Scheduler): if the scheduler calls `get_current_weather` directly, the oracle mode will transparently upgrade it. No scheduler changes needed.
- Session 7: ensure ORACLE_MODE env var is documented and defaulted to "false" in the deployment config so existing behaviour is preserved unless explicitly enabled.

---

## ENV VARS ADDED BY SESSION 2

New environment variables required (add to .env and deployment secrets):

```bash
# ChainOracle Network (Innovation 03)
ORACLE_MODE=false                    # Set to "true" to enable multi-source consensus
IMD_API_KEY=                         # India Meteorological Department API key
ACCUWEATHER_API_KEY=                 # AccuWeather API key
GOOGLE_MOBILITY_API_KEY=             # Google Maps Platform API key
AMAZON_FLEX_PROXY_URL=               # Internal Amazon Flex signal proxy URL
DUNZO_API_KEY=                       # Dunzo Partner API key
ZOMATO_API_KEY=                      # Zomato API key
ECOMMERCE_DENSITY_URL=               # Internal e-commerce density aggregation service
IOT_SENSOR_ENDPOINT=                 # Bengaluru IoT environmental sensor API endpoint
BBMP_SENSOR_ENDPOINT=                # BBMP traffic sensor API endpoint
ORACLE_HMAC_SECRET=change-me-in-prod # HMAC secret for oracle reading signatures

# ChainOracle Consensus Thresholds (can be overridden by GovernanceChaincode DAO vote)
ORACLE_S1_CONSENSUS_THRESHOLD=3      # of 4 nodes
ORACLE_S2_CONSENSUS_THRESHOLD=2      # of 3 nodes
ORACLE_S3_CONSENSUS_THRESHOLD=2      # of 3 nodes

# SmartPolicy Chaincode (Innovation 02)
# (Fabric peer connection config is handled by blockchain session's fabric_client.py)
CHAINCODE_MOCK_MODE=true             # Set to "false" when ZoneChain Fabric is running
```

---

## [WARNING] FLAGS

**[WARNING] W1 — mobility.py was empty**
`backend/integrations/mobility.py` was blank in session2_context.md. Session 2 has written
`backend/oracle/sources/mobility_sources.py` as the canonical mobility data layer.
Session 7 must verify that `signal_fusion.py`'s S2 path (which presumably called something
in mobility.py) is updated to call the oracle aggregator instead.

**[WARNING] W2 — Forward Lock countdown is off-chain only**
Currently `renew_policy` decrements `forward_lock_weeks` in Python (off-chain).
PATCH 2-6 records this to PolicyChaincode, but the decrement logic remains in Python.
Risk: if someone calls `renew_policy` without going through the FastAPI route (direct DB write),
the on-chain counter will diverge. Session 7 should add a DB trigger or reconciliation job.

**[WARNING] W3 — Fraud score recorded after claim creation, not at trigger time**
`claim.fraud_score` is written to DB at some point before `review_claim` is called.
Our PATCH 2-8 reads it during review. If `fraud_score` is NULL at review time
(e.g., FraudShield hasn't run yet), the chaincode write is skipped with a log warning.
Session 6 (FraudShield) must ensure fraud_score is always populated before review.

**[WARNING] W4 — Oracle HMAC secret in env**
`ORACLE_HMAC_SECRET` must be rotated regularly and never committed to source control.
In production, use AWS Secrets Manager / GCP Secret Manager.

**[WARNING] W5 — GovernanceChaincode threshold updates not yet wired to aggregator**
When a DAO vote passes via `GovernanceChaincode.FinaliseProposal`, the updated threshold
(e.g., oracle_s1_consensus_threshold) is written to the Fabric ledger but NOT automatically
pushed to the running Python aggregator instance. Session 7 must implement a Fabric event
listener (using the Python SDK's event hub) that calls `aggregator.update_threshold()` when
a `ProposalFinalised` chaincode event is received.

---

## [ENHANCEMENT] FLAGS

**[ENHANCEMENT] E1 — Oracle health dashboard**
`GET /api/v1/oracle/health` — per-node latency, success rate, circuit breaker status.
`POST /api/v1/oracle/health/{source_id}/reset` — manual circuit breaker reset for ops.

**[ENHANCEMENT] E2 — INSUFFICIENT_CONSENSUS fallback**
When oracle consensus is not reached, `get_current_weather` falls back to single-OWM
rather than returning an error. The `source` field in the response indicates
`"oracle_consensus"` vs `"openweathermap"` vs `"simulated"` for full audit provenance.

**[ENHANCEMENT] E3 — Circuit breaker per oracle source**
After 3 consecutive failures, a source is marked DEGRADED and excluded from the quorum
denominator. After 10, it's marked OFFLINE. Recovery is automatic on first success.
Manual reset available via the health endpoint.

**[ENHANCEMENT] E4 — UPI reference hashing**
`ClaimChaincode.ApproveClaim` stores only the SHA-256 hash of the UPI transaction ref.
The raw UPI ID never touches the blockchain ledger (PII compliance, RBI guidelines).
Off-chain verification: SHA-256(raw_upi_ref) == on-chain upi_ref_hash.

**[ENHANCEMENT] E5 — Governance DAO parameter TTL**
Proposals expire after 72 hours if not finalised. The `FinaliseProposal` call marks
expired proposals as "expired" rather than silently failing.

**[ENHANCEMENT] E6 — Mock mode for development**
All chaincode SDK calls fall back to an in-process mock ledger when `fabric_client.py`
is not available. Zero configuration needed for local development.
Set `CHAINCODE_MOCK_MODE=true` explicitly to make this intent clear in logs.
## session3_patches.md
# session3_patches.md
# ZoneGuard Session 3 — Conflict-Protected File Patches
# ZeroKnow KYC (Innovation 04) + CrossRider DID Passport (Innovation 09)
#
# DO NOT apply these patches until Session 7 (integration/merge session) reviews them.
# Every patch is backward compatible — no existing endpoints removed.
# ─────────────────────────────────────────────────────────────────────────────

---

## PATCH 3-1
### Target File: `backend/main.py`
### Location: After line containing → `from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo`
### Action: INSERT
### Code:
```python
# Session 3: ZeroKnow KYC + CrossRider DID Passport
try:
    from identity import identity_router
    HAS_IDENTITY = True
except ImportError as e:
    import logging
    logging.getLogger(__name__).warning(f"Identity module not loaded: {e}")
    identity_router = None
    HAS_IDENTITY = False
```
### Reason: Import the identity router with graceful fallback if the identity module's dependencies (cryptography, etc.) aren't installed yet. Prevents breaking the main app during staged deployment.
### Conflicts With: Session 7 — if Session 7 adds its own top-level try/import block, merge by combining both into a single try block or separate try/except statements.

---

## PATCH 3-2
### Target File: `backend/main.py`
### Location: After line containing → `app.include_router(demo.router)`
### Action: INSERT
### Code:
```python
# Session 3: Identity System (ZK KYC + DID Passport)
if HAS_IDENTITY and identity_router:
    app.include_router(identity_router)
    logger.info("Identity router registered: /api/v1/identity")
else:
    logger.warning("Identity router not available — run: pip install cryptography")
```
### Reason: Register the identity router only if the module loaded successfully. The conditional prevents deployment failures if cryptography library isn't installed.
### Conflicts With: Session 7 — coordinate ordering of router registration. Identity router should come after auth router (auth.router) since identity endpoints may require authentication in production.

---

## PATCH 3-3
### Target File: `backend/main.py`
### Location: After line containing → `"auth": "/api/v1/auth",`
### Action: INSERT
### Code:
```python
            "identity": "/api/v1/identity",
            "did_resolve": "/api/v1/identity/resolve/{did}",
            "zk_verify": "/api/v1/identity/verify-proof",
            "did_passport": "/api/v1/identity/passport/{nullifier_prefix}",
```
### Reason: Add identity endpoints to the root endpoint discovery response so API consumers (NBFC integrations, Swiggy onboarding) can autodiscover the ZK/DID endpoints.
### Conflicts With: Session 7 — if Session 7 modifies the root endpoint dict structure, apply this inside their modified dict.

---

## PATCH 3-4
### Target File: `backend/routers/riders.py`
### Location: After line containing → `from ml.zone_risk_scorer import calculate_zone_premium`
### Action: INSERT
### Code:
```python
# Session 3: ZK KYC imports (optional — graceful fallback to legacy OTP)
try:
    from identity.models import ZKVerifyRequest, ZKVerifyResponse, SnarkProof, PublicSignals
    from identity.zk_kyc import verify_rider_zk_proof, generate_flex_rider_proof
    from identity.did_passport import assemble_did_passport, generate_share_url, generate_qr_payload
    from identity.models import Platform
    HAS_ZK_IDENTITY = True
except ImportError:
    HAS_ZK_IDENTITY = False
```
### Reason: Import ZK identity functions with graceful fallback. If the identity module isn't installed, the legacy OTP flow continues to work. HAS_ZK_IDENTITY flag gates the new endpoints.
### Conflicts With: Session 5 (if they add ML imports to riders.py) — merge by placing after their imports, before the router definition.

---

## PATCH 3-5
### Target File: `backend/routers/riders.py`
### Location: After the closing of `async def verify_eshram(...)` function (after `return verification`)
### Action: INSERT
### Code:
```python

@router.post("/{rider_id}/verify-zk")
async def verify_zk_kyc(
    rider_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    ZeroKnow KYC — Verify a ZK proof for rider identity.
    Innovation 04: ZeroKnow KYC (Session 3)

    This endpoint runs ALONGSIDE the existing OTP flow — backward compatible.
    The rider's OTP KYC is NOT replaced; ZK verification is an upgrade.

    Flow:
    1. Rider completes existing OTP KYC (kyc_verified = True)
    2. Rider optionally calls this endpoint with their ZK proof
    3. zk_verified = True unlocks: DID Passport, loyalty discounts, DPDP compliance

    Request body: { "proof": {...}, "public_signals": {...} }
    Returns: ZKVerifyResponse with nullifier and verified status
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(
            status_code=503,
            detail="ZK identity module not available. Install: pip install cryptography"
        )

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Parse the ZK proof from request body
    try:
        proof_data = payload.get("proof", {})
        signals_data = payload.get("public_signals", {})

        proof = SnarkProof(**proof_data)
        public_signals = PublicSignals(**signals_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid ZK proof format: {e}")

    # Run ZK verification
    result = await verify_rider_zk_proof(
        proof=proof,
        public_signals=public_signals,
        db_session=db,
    )

    if result.verified:
        # Update rider record with ZK proof results (no PII stored)
        from sqlalchemy import text
        from datetime import datetime, timezone
        await db.execute(
            text("""
                UPDATE riders SET
                    nullifier_hash    = :nullifier,
                    zk_proof_hash     = :proof_hash,
                    zk_verified       = TRUE,
                    zk_verified_at    = :verified_at,
                    eshram_zk_valid   = :eshram_valid,
                    earnings_bracket  = COALESCE(earnings_bracket, NULL),
                    disclosure_level  = 1
                WHERE id = :rider_id
            """),
            {
                "nullifier": public_signals.nullifier,
                "proof_hash": result.proof_id,
                "verified_at": datetime.now(timezone.utc),
                "eshram_valid": public_signals.eshram_valid,
                "rider_id": rider_id,
            }
        )
        await db.commit()

    return {
        "verified": result.verified,
        "proof_id": result.proof_id,
        "nullifier": result.nullifier,
        "zk_verified_at": result.zk_verified_at.isoformat(),
        "message": result.message,
        "legacy_kyc_preserved": True,
        "note": "ZK verification is additive. Existing OTP KYC remains valid.",
    }


@router.post("/{rider_id}/generate-zk-proof")
async def generate_zk_proof_for_rider(
    rider_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    TEE-side ZK proof generation for WhatsApp-native flow.
    Innovation 04: ZeroKnow KYC (Session 3)

    Rider sends raw credentials over TLS; server generates proof in TEE.
    Returns: { proof, public_signals, nullifier_secret }
    The nullifier_secret is returned to the rider and NEVER stored by ZoneGuard.

    This avoids 28s proof generation delay on low-end Android (MediaTek Helio G35).
    In production: deploy this endpoint inside AWS Nitro Enclave.

    Request body: { "eshram_id": "..." }
    (rider_id comes from path, not body — avoids double-logging)
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(status_code=503, detail="ZK identity module not available")

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    eshram_id = payload.get("eshram_id")

    try:
        proof, public_signals, nullifier_secret = await generate_flex_rider_proof(
            rider_id=rider_id,
            eshram_id=eshram_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "proof": proof.model_dump(),
        "public_signals": public_signals.model_dump(),
        "nullifier_secret": nullifier_secret,
        "instructions": {
            "step1": "Store nullifier_secret securely. ZoneGuard will NEVER store it.",
            "step2": "Call POST /{rider_id}/verify-zk with proof + public_signals.",
            "step3": "After verification, your DID Passport is created automatically.",
        },
        "tee_mode": "simulated",  # Change to "nitro" in production
    }


@router.get("/{rider_id}/did-passport")
async def get_rider_did_passport(
    rider_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a rider's CrossRider DID Passport.
    Innovation 09: CrossRider DID Passport (Session 3)

    Returns the rider's full DID Document + Verifiable Credentials.
    Requires zk_verified = True (rider must complete ZK KYC first).

    The passport is assembled on-demand from the rider's ZK proof history
    and payout records. No raw PII is included.
    """
    if not HAS_ZK_IDENTITY:
        raise HTTPException(status_code=503, detail="ZK identity module not available")

    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    if not getattr(rider, "zk_verified", False):
        raise HTTPException(
            status_code=403,
            detail="DID Passport requires ZK verification. "
                   "Complete POST /{rider_id}/generate-zk-proof then POST /{rider_id}/verify-zk first."
        )

    nullifier = getattr(rider, "nullifier_hash", None)
    if not nullifier:
        raise HTTPException(status_code=500, detail="Nullifier not found despite zk_verified=True")

    passport = assemble_did_passport(
        nullifier=nullifier,
        zone_id=rider.zone_id or "unknown",
        tenure_weeks=getattr(rider, "tenure_weeks", 0) or 0,
        platforms=[Platform.AMAZON_FLEX],
        eshram_valid=bool(getattr(rider, "eshram_zk_valid", 0)),
        zk_proof_id=getattr(rider, "zk_proof_hash", "") or "",
    )

    share_url = generate_share_url(nullifier)
    qr_payload = generate_qr_payload(passport)

    return {
        "passport": passport.model_dump(),
        "share_url": share_url,
        "qr_payload": qr_payload,
        "privacy_note": "This passport contains zero PII. Safe to share with NBFCs and platforms.",
    }
```
### Reason: Add three new endpoints to riders.py: (1) verify-zk for ZK proof verification, (2) generate-zk-proof for TEE-side proof generation, (3) did-passport for passport retrieval. All are additive — no existing endpoints modified.
### Conflicts With:
  - Session 5 (ML/premium): If they add to riders.py, ensure HAS_ZK_IDENTITY import block comes before their new code.
  - Session 7 (integration): Coordinate that zk_verified field is read by premium calculator for loyalty discounts.
  - Session 6 (WhatsApp): The generate-zk-proof endpoint is the TEE gateway called from the WhatsApp flow. Session 6 should call POST /{rider_id}/generate-zk-proof then POST /{rider_id}/verify-zk in their WhatsApp message handler.

---

## PATCH 3-6
### Target File: `backend/config.py`
### Location: After line containing → `cors_origins: str = "http://localhost:5173,...`
### Action: INSERT
### Code:
```python
    # Session 3: ZK Identity System
    snarkjs_wasm_path: str = "backend/identity/zk_circuits/build/wasm"
    snarkjs_zkey_path: str = "backend/identity/zk_circuits/build/zkey"
    snarkjs_vkey_path: str = "backend/identity/zk_circuits/build/vkey"
    zk_proof_cache_ttl: int = 86400          # 24 hours
    zk_tee_mode: str = "simulate"             # simulate | nitro | tdx
    zk_max_concurrent_proofs: int = 4

    # Session 3: DID Passport
    did_registry_url: str = "https://zoneguard.in/did/resolve"
    zoneguard_did: str = "did:key:z6MkZoneGuardIssuer2026"
    zoneguard_signing_key: str = ""           # Ed25519 private key hex (load from secrets in prod)
    did_cache_ttl: int = 3600                 # 1 hour
```
### Reason: Add ZK and DID configuration to the central Settings class so all env vars are documented and typed. The pydantic-settings model will automatically read from .env file.
### Conflicts With: Any session that also modifies config.py. Add these fields at the end of the Settings class body — they won't conflict with other fields.

---

## PATCH 3-7 (SEED UPDATE)
### Target File: `backend/db/seed.py`
### Location: After line containing → `{"id": "AMZFLEX-BLR-05678", ... "upi_id": None},`
### Action: INSERT (into the RIDERS list, these are additional fields for existing seeded riders)
### Code:
```python
# Session 3: ZK identity seed fields
# These are added to the Rider model constructor calls below in the seed loop:
# session.add(Rider(**r)) → needs nullifier_hash, zk_verified etc.
# The migration SQL handles backfilling existing records.
# For new seeds post-migration, add to the Rider() constructor:
#
#   nullifier_hash = "sim_" + hashlib.sha256(r["id"].encode()).hexdigest(),
#   zk_verified = r.get("kyc_verified", False),
#   zk_verified_at = datetime.now(timezone.utc) if r.get("kyc_verified") else None,
#   disclosure_level = 2 if r.get("tenure_weeks", 0) >= 4 else 1,
#
# NOTE: Do NOT add this in Session 3 directly — coordinate with Session 7
# who owns the final seed.py merge. This comment documents the intent.
```
### Reason: Document what needs changing in seed.py for ZK fields without directly editing it (Session 7 owns the seed merge). This comment patch is informational.
### Conflicts With: Session 7 — they should apply the actual Rider() constructor changes when merging.

---

## ENV VARS REQUIRED (add to .env)

```bash
# ── Session 3: ZeroKnow KYC ───────────────────────────────────────────────────
# Paths to compiled Circom circuit artifacts (after running circom + snarkjs setup)
SNARKJS_WASM_PATH=backend/identity/zk_circuits/build/wasm
SNARKJS_ZKEY_PATH=backend/identity/zk_circuits/build/zkey
SNARKJS_VKEY_PATH=backend/identity/zk_circuits/build/vkey

# ZK proof generation mode:
#   simulate  = deterministic mock proofs (hackathon/dev)
#   nitro     = AWS Nitro Enclave TEE (production)
#   tdx       = Intel TDX TEE (production alternative)
ZK_TEE_MODE=simulate

# Redis TTL for cached ZK proofs (seconds). Default 24h.
ZK_PROOF_CACHE_TTL=86400

# Max concurrent proof generations (prevents OOM on proof-intensive workloads)
ZK_MAX_CONCURRENT_PROOFS=4

# ── Session 3: CrossRider DID Passport ───────────────────────────────────────
# ZoneGuard's DID (issuer identity for Verifiable Credentials)
# In production: replace with did:ethr:polygon:0x... after deploying registry contract
ZONEGUARD_DID=did:key:z6MkZoneGuardIssuer2026

# ZoneGuard's Ed25519 signing key (64 hex chars = 32 bytes)
# CRITICAL: Generate fresh key for production. Never commit to git.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
ZONEGUARD_SIGNING_KEY=

# DID resolution service URL (for did:web and did:ethr, future)
DID_REGISTRY_URL=https://zoneguard.in/did/resolve

# Redis TTL for resolved DID documents (seconds). Default 1h.
DID_CACHE_TTL=3600

# ── Circuit Setup (run once, not runtime env vars) ───────────────────────────
# After installing circom + snarkjs, run these to compile circuits:
#
#   cd backend/identity/zk_circuits
#   npm init -y && npm install circomlib
#
#   circom FlexRiderProof.circom --r1cs --wasm --sym -o ./build/
#   circom EarningsBracketProof.circom --r1cs --wasm --sym -o ./build/
#
#   # Download Powers of Tau (one-time, 28MB)
#   snarkjs powersoftau new bn128 14 pot14_0000.ptau -v
#   snarkjs powersoftau contribute pot14_0000.ptau pot14_0001.ptau --name="ZoneGuard" -v
#   snarkjs powersoftau prepare phase2 pot14_0001.ptau pot14_final.ptau -v
#
#   snarkjs groth16 setup build/FlexRiderProof.r1cs pot14_final.ptau build/zkey/FlexRiderProof_0000.zkey
#   snarkjs zkey contribute build/zkey/FlexRiderProof_0000.zkey build/zkey/FlexRiderProof_final.zkey -v
#   snarkjs zkey export verificationkey build/zkey/FlexRiderProof_final.zkey build/vkey/FlexRiderProof_verification_key.json
#
#   # Repeat for EarningsBracketProof
```

---

## PIP DEPENDENCIES (add to requirements.txt)

```
# Session 3: ZK Identity System
cryptography>=42.0.0        # Ed25519 keys for DID + VC signing
# snarkjs via npm (CLI tool, not pip)
# circom via npm (circuit compiler, not pip)
```

---

## NPM DEPENDENCIES (for circuit compilation, not runtime)

```json
{
  "devDependencies": {
    "circomlib": "^2.0.5",
    "snarkjs": "^0.7.4"
  }
}
```

---

## SESSION HANDOFF NOTES FOR SESSION 7 (Integration)

1. **Router registration order**: Identity router must come AFTER auth.router in main.py.
   In production, identity endpoints should require JWT auth (except /resolve and /verify-credential which are public).

2. **ZK verified flag for premium engine**: The `zk_verified` boolean on the riders table
   and the `v_zk_verified_riders` view (which includes `loyalty_discount_pct`) should be
   consumed by the premium calculation engine. Session 5 (if they handle premiums) needs
   to know about `discount_level` field.

3. **WhatsApp flow integration** (Session 6): The ZK proof generation flow is:
   ```
   WhatsApp → POST /riders/{id}/generate-zk-proof { eshram_id }
            → Returns { proof, public_signals, nullifier_secret }
            → Rider confirms (stores nullifier_secret in encrypted storage)
            → POST /riders/{id}/verify-zk { proof, public_signals }
            → zk_verified = True, DID Passport created
   ```
   Total UX time: ~5-10s (server-side proof) vs 28s on device.

4. **Seed file**: After migration 003 is applied, the seed.py UPDATE at the bottom
   backfills existing test riders with simulated ZK hashes. New riders seeded after
   migration need ZK fields in their Rider() constructor (see PATCH 3-7 comment).

5. **Frontend integration**: `<IdentityCard nullifierPrefix="..." />` requires the
   `/api/v1/identity/passport/{prefix}` endpoint to be live. Use the nullifier_hash
   first 16 chars as the prefix. The component handles loading/error states.
## session4_patches.md
# Session 4 — Conflict-Protected File Patches
# ZoneGuard ML Session 4: FedShield v3, ZoneTwin GAN v3, AdaptPremium
# Generated: Session 4 parallel build
# DO NOT apply these directly — coordinate with Session 7 for merge review.

---

## PATCH 4-1
### Target File: `backend/ml/zone_twin.py`
### Location: After line containing → `"zone_id": zone_id,`  (end of `counterfactual_inactivity` return dict, i.e. after the `_interpret` function definition, at module level)
### Action: INSERT
### Code:
```python
# ======================================================================
# ZoneTwin GAN v3 delegation interface (Session 4 — Innovation 11)
# ======================================================================

def generate_synthetic_scenarios(
    zone_id: str,
    n: int = 1000,
    zone_type: str = "medium",
    season: str = "monsoon",
    day_of_week: str = "mon",
    time_of_day: str = "morning",
    signal_history: list | None = None,
    model_dir: str | None = None,
) -> list[dict]:
    """
    Generate n synthetic (S1, S2, S3, S4, rider_dark_pct) scenario tuples
    using the ZoneTwin GAN v3 (cGAN with WGAN-GP).

    Delegates to ml.zone_twin_gan.ZoneTwinGAN. If a trained model exists at
    model_dir/{zone_id}_gan.pt it is loaded; otherwise a freshly instantiated
    (untrained) GAN generates via numpy statistical fallback.

    Applications:
      • Pre-season simulation before monsoon
      • New zone bootstrapping with zero history
      • FedShield v3 synthetic fraud scenario augmentation
      • Reinsurance pool stress-testing

    Args:
        zone_id:        Zone identifier (must be in ZONE_BASELINES).
        n:              Number of synthetic scenarios to generate.
        zone_type:      One of low / medium / high / flood-prone.
        season:         One of pre_monsoon / monsoon / post_monsoon / winter.
        day_of_week:    mon–sun.
        time_of_day:    morning / afternoon / evening / night.
        signal_history: Optional 48-step history [[S1,S2,S3,S4], ...].
        model_dir:      Directory containing trained GAN weights.
                        Defaults to env var GAN_MODEL_DIR.

    Returns:
        List of n dicts — each contains s1_rainfall, s2_mobility,
        s3_order_pct, s4_inactivity_pct, rider_dark_pct, synthetic=True.
    """
    import os
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)

    try:
        from ml.zone_twin_gan import ZoneTwinGAN, bootstrap_synthetic_history

        # Resolve zone_type from ZONE_BASELINES if not explicitly provided
        baseline = ZONE_BASELINES.get(zone_id)
        if baseline and zone_type == "medium":
            # Infer zone_type from flood_correlation
            fc = baseline.get("flood_correlation", 0.5)
            if fc > 0.90:
                zone_type = "flood-prone"
            elif fc > 0.70:
                zone_type = "high"
            elif fc > 0.40:
                zone_type = "medium"
            else:
                zone_type = "low"

        gan = ZoneTwinGAN(zone_id=zone_id, zone_type=zone_type)

        # Load pre-trained weights if available
        _model_dir = model_dir or os.getenv("GAN_MODEL_DIR", "/models/zone_twin_gan")
        model_path = Path(_model_dir) / f"{zone_id}_gan.pt"
        if model_path.exists():
            gan.load(str(model_path))
        else:
            # Bootstrap training from synthetic history (hackathon path)
            logger.info(
                "generate_synthetic_scenarios[%s]: no pre-trained GAN found at %s. "
                "Bootstrapping from synthetic history.",
                zone_id, model_path,
            )
            records = bootstrap_synthetic_history(zone_id, n_days=730)
            # Add zone_type to records for conditioning
            for r in records:
                r["zone_type"] = zone_type
            gan.fit(records, epochs=200, log_every=50)

        scenarios = gan.generate(
            n=n,
            zone_type=zone_type,
            season=season,
            day_of_week=day_of_week,
            time_of_day=time_of_day,
            signal_history=signal_history,
        )
        return scenarios

    except ImportError as e:
        logger.warning(
            "generate_synthetic_scenarios: zone_twin_gan module not available (%s). "
            "Falling back to logistic-curve counterfactual sampling.", e
        )
        # Fallback: sample from existing logistic curve model with noise
        baseline = ZONE_BASELINES.get(zone_id, ZONE_BASELINES["hsr"])
        import random as _random
        results = []
        for _ in range(n):
            rainfall = max(0, _random.gauss(baseline["avg_rainfall_mm"] * 1.5, 20))
            result = counterfactual_inactivity(zone_id, rainfall)
            p50 = result["expected_inactivity"]["p50"]
            results.append({
                "s1_rainfall": round(rainfall, 2),
                "s2_mobility": round(max(0, baseline["avg_mobility"] - p50 * 0.5), 2),
                "s3_order_pct": round(max(0, 100 - p50 * 0.8), 2),
                "s4_inactivity_pct": round(p50, 2),
                "rider_dark_pct": round(min(95, p50 * 1.1), 2),
                "zone_type": zone_type,
                "season": season,
                "day_of_week": day_of_week,
                "time_of_day": time_of_day,
                "synthetic": True,
                "generator": "logistic_fallback",
            })
        return results


def nowcast_72h(
    zone_id: str,
    signal_history: list[list[float]],
    zone_type: str = "medium",
    season: str = "monsoon",
    n_paths: int = 200,
    model_dir: str | None = None,
) -> dict:
    """
    Generate a 72-hour probabilistic signal forecast (p10/p50/p90) using
    iterative ZoneTwin GAN v3 Monte Carlo rollouts.

    Each 15-minute step generates a new (S1–S4) tuple conditioned on the
    rolling 12-hour history window. Generates n_paths independent paths
    then computes percentile bands.

    Args:
        zone_id:        Zone identifier.
        signal_history: Recent 48-step (12h) history [[S1,S2,S3,S4], ...].
        zone_type:      Zone classification (auto-inferred if not provided).
        season:         Current season.
        n_paths:        Monte Carlo paths (default 200).
        model_dir:      GAN weights directory.

    Returns:
        Dict with 288 forecast steps × p10/p50/p90 per signal.
        Compatible with existing QuadSignal threshold evaluators in
        signal_fusion.py — each step's p50 values can be passed directly
        to evaluate_s1/s2/s3/s4().
    """
    import os
    import logging
    from pathlib import Path

    logger = logging.getLogger(__name__)

    try:
        from ml.zone_twin_gan import ZoneTwinGAN, bootstrap_synthetic_history

        baseline = ZONE_BASELINES.get(zone_id)
        if baseline and zone_type == "medium":
            fc = baseline.get("flood_correlation", 0.5)
            zone_type = (
                "flood-prone" if fc > 0.90 else
                "high" if fc > 0.70 else
                "medium" if fc > 0.40 else
                "low"
            )

        gan = ZoneTwinGAN(zone_id=zone_id, zone_type=zone_type)

        _model_dir = model_dir or os.getenv("GAN_MODEL_DIR", "/models/zone_twin_gan")
        model_path = Path(_model_dir) / f"{zone_id}_gan.pt"
        if model_path.exists():
            gan.load(str(model_path))
        else:
            logger.info("nowcast_72h[%s]: bootstrapping GAN from synthetic history.", zone_id)
            records = bootstrap_synthetic_history(zone_id, n_days=730)
            for r in records:
                r["zone_type"] = zone_type
            gan.fit(records, epochs=200, log_every=100)

        return gan.nowcast_72h(
            signal_history=signal_history,
            zone_type=zone_type,
            season=season,
            n_paths=n_paths,
        )

    except ImportError as e:
        logger.warning(
            "nowcast_72h: zone_twin_gan not available (%s). "
            "Returning single-point counterfactual estimate.", e
        )
        # Fallback: 72h flat forecast from current counterfactual estimate
        current_rain = signal_history[-1][0] if signal_history else 30.0
        current_result = counterfactual_inactivity(zone_id, current_rain)
        p10 = current_result["expected_inactivity"]["p10"]
        p50 = current_result["expected_inactivity"]["p50"]
        p90 = current_result["expected_inactivity"]["p90"]
        STEPS = 288
        return {
            "zone_id": zone_id,
            "horizon_hours": 72,
            "steps": STEPS,
            "step_interval_minutes": 15,
            "n_monte_carlo_paths": 1,
            "percentiles": {
                "p10": [[current_rain * 0.7, 80, 75, p10]] * STEPS,
                "p50": [[current_rain, 85 - p50, 80 - p50 * 0.8, p50]] * STEPS,
                "p90": [[current_rain * 1.3, 90 - p90, 85 - p90 * 0.8, p90]] * STEPS,
            },
            "signal_labels": ["S1_rainfall", "S2_mobility", "S3_order_pct", "S4_inactivity_pct"],
            "synthetic": True,
            "generator": "counterfactual_fallback",
        }
```
### Reason: Adds `generate_synthetic_scenarios()` and `nowcast_72h()` module-level functions that delegate to the new ZoneTwin GAN v3 module (zone_twin_gan/). zone_twin.py has no class — these must be module-level functions, not methods. Full fallback to existing logistic-curve logic if GAN module is unavailable.
### Conflicts With: Session 7 (API layer) — if Session 7 exposes `zone_twin` endpoints, they should call these new functions. Session 5/6 (if any) touching zone_twin.py must merge carefully around the `_interpret()` function definition boundary.

---

## PATCH 4-2
### Target File: `backend/ml/zone_risk_scorer.py`
### Location: After line containing → `return calculate_risk_score(`  (end of `calculate_zone_premium` function)
### Action: INSERT
### Code:
```python
def get_rl_recommendation(
    zone_data: dict,
    rider_tenure_weeks: int = 0,
    loss_ratios_4w: list | None = None,
    churn_rate: float = 0.05,
    enrolled_riders: int = 100,
    imd_seasonal: float = 0.5,
    pool_funded_ratio: float = 1.2,
) -> dict:
    """
    Run the AdaptPremium PPO agent alongside the existing rule-based scorer
    in shadow mode and log the comparison.

    This method is the primary integration point between the existing Monday
    recalculation flow and the new RL-based pricing system (Innovation 13).

    When ADAPT_PREMIUM_SHADOW_MODE=true (default):
      - Existing rule-based premium is returned unchanged.
      - RL recommendation is appended under `rl_shadow_recommendation`.
      - Comparison is logged to AdaptPremium decision log.

    When ADAPT_PREMIUM_SHADOW_MODE=false:
      - RL premium replaces rule-based premium.
      - IRDAI constraints are enforced before returning.

    Args:
        zone_data:            Dict passed to calculate_zone_premium().
        rider_tenure_weeks:   Rider's tenure (for personalisation).
        loss_ratios_4w:       4-week rolling loss ratio history.
        churn_rate:           Current weekly churn rate.
        enrolled_riders:      Enrolled rider count.
        imd_seasonal:         IMD 90-day forecast severity (0-1).
        pool_funded_ratio:    Pool balance / expected annual claims.

    Returns:
        Result dict from calculate_zone_premium() with optional
        `rl_shadow_recommendation` field appended.
    """
    import os
    import logging

    logger = logging.getLogger(__name__)

    # Always compute the existing rule-based result first (zero regression risk)
    rule_based_result = calculate_zone_premium(zone_data, rider_tenure_weeks)

    # Attempt RL recommendation in shadow mode
    try:
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent

        zone_id = zone_data.get("zone_id", "unknown")
        zone_type = zone_data.get("risk_tier", "medium")
        current_premium = float(rule_based_result["premium"])

        # Load cached agent (one per zone, module-level cache)
        agent = _get_or_create_rl_agent(zone_id, zone_type, current_premium)

        recommendation = agent.get_recommendation(
            zone_data=zone_data,
            rider_tenure_weeks=rider_tenure_weeks,
            loss_ratios_4w=loss_ratios_4w,
            churn_rate=churn_rate,
            enrolled_riders=enrolled_riders,
            imd_seasonal=imd_seasonal,
            pool_funded_ratio=pool_funded_ratio,
        )

        shadow_mode = os.getenv("ADAPT_PREMIUM_SHADOW_MODE", "true").lower() == "true"

        if shadow_mode:
            # Append RL recommendation without changing rule-based result
            rule_based_result["rl_shadow_recommendation"] = recommendation.get(
                "rl_shadow_recommendation", {}
            )
            logger.info(
                "get_rl_recommendation[%s]: shadow comparison — "
                "rule=₹%.0f rl=₹%.0f delta=%s%%",
                zone_id,
                rule_based_result["premium"],
                recommendation.get("rl_shadow_recommendation", {}).get("recommended_premium", current_premium),
                recommendation.get("rl_shadow_recommendation", {}).get("delta_pct", 0),
            )
            return rule_based_result
        else:
            # Live mode — return RL result directly
            return recommendation

    except ImportError:
        logger.warning(
            "get_rl_recommendation: AdaptPremium not available "
            "(stable-baselines3 not installed). Returning rule-based result."
        )
        return rule_based_result
    except Exception as e:
        logger.error(
            "get_rl_recommendation: unexpected error (%s). "
            "Returning rule-based result.", e
        )
        return rule_based_result


# Module-level RL agent cache — one per zone, initialised lazily
_rl_agent_cache: dict = {}


def _get_or_create_rl_agent(
    zone_id: str,
    zone_type: str,
    initial_premium: float,
) -> object:
    """Retrieve or create a cached AdaptPremiumAgent for a zone."""
    import os

    if zone_id not in _rl_agent_cache:
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent
        agent = AdaptPremiumAgent(
            zone_id=zone_id,
            zone_type=zone_type,
            initial_premium=initial_premium,
        )
        # Try loading pre-trained model
        model_path = os.getenv("PPO_MODEL_PATH", "/models/adapt_ppo")
        agent.load(f"{model_path}/{zone_id}_ppo")
        _rl_agent_cache[zone_id] = agent

    return _rl_agent_cache[zone_id]
```
### Reason: Adds `get_rl_recommendation()` to zone_risk_scorer.py as a drop-in shadow mode wrapper. Existing `calculate_zone_premium()` is completely unchanged — zero regression risk. The RL agent is loaded lazily and cached per zone to avoid repeated disk I/O on every Monday recalculation.
### Conflicts With: Session 7 (API) — the Monday recalculation endpoint should call `get_rl_recommendation()` instead of `calculate_zone_premium()` when AdaptPremium is enabled. Coordinate on the endpoint handler signature.

---

## PATCH 4-3
### Target File: `backend/ml/federated/client.py`
### Location: After line containing → `from ml.federated.model import FederatedAnomalyModel`
### Action: INSERT
### Code:
```python
import os as _os

# FedShield v3 — activated by env var FEDSHIELD_V3_ENABLED=true
_FEDSHIELD_V3 = _os.getenv("FEDSHIELD_V3_ENABLED", "false").lower() == "true"

if _FEDSHIELD_V3:
    try:
        from ml.fedshield_v3.fedshield_client import FedShieldClient as FederatedClient  # noqa: F811
        import logging as _logging
        _logging.getLogger(__name__).info(
            "federated/client.py: FedShield v3 active — "
            "using PHE-encrypted FedShieldClient."
        )
    except ImportError as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "FEDSHIELD_V3_ENABLED=true but FedShieldClient import failed (%s). "
            "Falling back to FederatedClient v2.", _e
        )
```
### Reason: When FEDSHIELD_V3_ENABLED=true, transparently replaces FederatedClient with FedShieldClient in the existing import namespace. All callers that do `from ml.federated.client import FederatedClient` automatically receive the encrypted v3 client. Falls back gracefully if the new module is missing.
### Conflicts With: Session 7 — if client.py is used directly in API handlers, this patch is transparent. If Session 7 added a custom import alias for FederatedClient, coordinate to avoid the alias masking this override.

---

## PATCH 4-4
### Target File: `backend/ml/federated/server.py`
### Location: After line containing → `from ml.federated.model import FederatedAnomalyModel`
### Action: INSERT
### Code:
```python
import os as _os

# FedShield v3 — Krum aggregation replaces FedAvg when enabled
_FEDSHIELD_V3 = _os.getenv("FEDSHIELD_V3_ENABLED", "false").lower() == "true"

if _FEDSHIELD_V3:
    try:
        from ml.fedshield_v3.fedshield_server import FedShieldServer as FederatedServer  # noqa: F811
        import logging as _logging
        _logging.getLogger(__name__).info(
            "federated/server.py: FedShield v3 active — "
            "using Krum aggregation + PHE FedShieldServer."
        )
    except ImportError as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "FEDSHIELD_V3_ENABLED=true but FedShieldServer import failed (%s). "
            "Falling back to FederatedServer v2 (FedAvg).", _e
        )
```
### Reason: Same transparent-override pattern as PATCH 4-3. When FEDSHIELD_V3_ENABLED=true, callers of `from ml.federated.server import FederatedServer` automatically get the Krum-based encrypted server. FedAvg fallback preserved.
### Conflicts With: Session 7 — `POST /admin/fraudshield/train` endpoint calls `FederatedServer.run_full_training()`. FedShieldServer.run_full_training_v3() has the same return structure but adds `byzantine_reports`. Session 7 must handle the extended return dict gracefully (extra keys are non-breaking).

---

## PATCH 4-5
### Target File: `backend/main.py`
### Location: After line containing → `app = FastAPI(` (or the first router registration line, e.g. `app.include_router(`)
### Action: INSERT
### Code:
```python
# ======================================================================
# AdaptPremium Admin Endpoints (Session 4 — Innovation 13)
# ======================================================================
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

_adapt_router = APIRouter(prefix="/admin/adapt-premium", tags=["AdaptPremium"])


class AdaptPremiumTrainRequest(BaseModel):
    zone: str = "all"
    total_timesteps: int = 200_000
    attach_gan: bool = False


class AdaptPremiumRecommendRequest(BaseModel):
    zone_id: str
    zone_data: dict
    rider_tenure_weeks: int = 0
    loss_ratios_4w: Optional[list[float]] = None
    churn_rate: float = 0.05
    enrolled_riders: int = 100
    imd_seasonal: float = 0.5
    pool_funded_ratio: float = 1.2


@_adapt_router.post("/train")
async def adapt_premium_train(
    request: AdaptPremiumTrainRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger AdaptPremium PPO training in the background.
    Training runs asynchronously — check /admin/adapt-premium/status for progress.
    """
    try:
        from ml.adapt_premium.ppo_trainer import AdaptPremiumTrainer

        def _run_training():
            trainer = AdaptPremiumTrainer()
            if request.zone == "all":
                trainer.train_all_zones(
                    total_timesteps=request.total_timesteps,
                    attach_gan=request.attach_gan,
                )
            else:
                trainer.train_zone(
                    request.zone,
                    request.total_timesteps,
                    request.attach_gan,
                )

        background_tasks.add_task(_run_training)
        return {
            "status": "training_started",
            "zone": request.zone,
            "total_timesteps": request.total_timesteps,
            "shadow_mode": True,
            "note": "Training runs in background. Set ADAPT_PREMIUM_SHADOW_MODE=false to activate live pricing.",
        }
    except ImportError as e:
        raise HTTPException(
            status_code=503,
            detail=f"AdaptPremium not available: {e}. Install stable-baselines3.",
        )


@_adapt_router.post("/recommend")
async def adapt_premium_recommend(request: AdaptPremiumRecommendRequest):
    """
    Get RL premium recommendation for a zone (shadow mode by default).
    Returns both rule-based and RL-recommended premiums for comparison.
    """
    try:
        from ml.zone_risk_scorer import get_rl_recommendation
        result = get_rl_recommendation(
            zone_data={"zone_id": request.zone_id, **request.zone_data},
            rider_tenure_weeks=request.rider_tenure_weeks,
            loss_ratios_4w=request.loss_ratios_4w,
            churn_rate=request.churn_rate,
            enrolled_riders=request.enrolled_riders,
            imd_seasonal=request.imd_seasonal,
            pool_funded_ratio=request.pool_funded_ratio,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_adapt_router.get("/shadow-log/{zone_id}")
async def adapt_premium_shadow_log(zone_id: str, n: int = 10):
    """Return recent shadow mode comparison log for a zone."""
    try:
        from ml.zone_risk_scorer import _rl_agent_cache
        agent = _rl_agent_cache.get(zone_id)
        if agent is None:
            return {"zone_id": zone_id, "log": [], "note": "No decisions logged yet for this zone."}
        return {
            "zone_id": zone_id,
            "shadow_mode": True,
            "log": agent.get_shadow_comparison(n_recent=n),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@_adapt_router.get("/status")
async def adapt_premium_status():
    """Return current AdaptPremium configuration and loaded agents."""
    import os
    from ml.zone_risk_scorer import _rl_agent_cache
    return {
        "shadow_mode": os.getenv("ADAPT_PREMIUM_SHADOW_MODE", "true"),
        "ppo_model_path": os.getenv("PPO_MODEL_PATH", "/models/adapt_ppo"),
        "gan_enabled": os.getenv("GAN_ENABLED", "false"),
        "loaded_agents": list(_rl_agent_cache.keys()),
        "n_loaded_zones": len(_rl_agent_cache),
    }


# Register router — add this line immediately after the router definition block above:
app.include_router(_adapt_router)
```
### Reason: Registers four AdaptPremium admin endpoints:
#   POST /admin/adapt-premium/train          — trigger background PPO training
#   POST /admin/adapt-premium/recommend      — get zone RL recommendation
#   GET  /admin/adapt-premium/shadow-log/{z} — inspect shadow comparison log
#   GET  /admin/adapt-premium/status         — configuration status
# All endpoints are non-breaking additions. Existing endpoints are unchanged.
### Conflicts With: Session 7 — if Session 7 is building the main API, coordinate the `app.include_router(_adapt_router)` placement so it lands after all existing routers. The `/admin/adapt-premium/train` endpoint uses BackgroundTasks — ensure the FastAPI app is configured with at least 1 background worker thread.

---

## New Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FEDSHIELD_V3_ENABLED` | `false` | Activate PHE + Krum FL path |
| `PPO_MODEL_PATH` | `/models/adapt_ppo` | PPO model save/load directory |
| `ADAPT_PREMIUM_SHADOW_MODE` | `true` | Log RL decisions without applying |
| `GAN_ENABLED` | `false` | Use ZoneTwinGAN rollouts in PPO env |
| `GAN_MODEL_DIR` | `/models/zone_twin_gan` | ZoneTwinGAN weights directory |

---

## New requirements.txt Additions

```
# FedShield v3
python-paillier>=1.5.0
torch>=2.0.0
torch-geometric>=2.3.0

# AdaptPremium
stable-baselines3>=2.0.0
gymnasium>=0.29.0

# ZoneTwin GAN v3 (uses torch above)
# no additional deps beyond torch

# Federated Learning (existing Flower scaffold is custom — no flwr needed)
# flower>=1.5.0  ← NOT needed — custom FL simulation, not actual Flower
```

---

## Session Coordination Notes for Session 7

1. **`/admin/fraudshield/train` endpoint** — `FedShieldServer.run_full_training_v3()` returns an extended dict with `byzantine_reports` key. Handle gracefully (extra keys don't break existing response consumers).

2. **Monday recalculation cron** — Replace `calculate_zone_premium()` call with `get_rl_recommendation()` in the Monday cron handler. Pass `ADAPT_PREMIUM_SHADOW_MODE=true` for initial deployment.

3. **Zone Twin endpoints** — Any endpoint currently calling `counterfactual_inactivity()` can optionally also call `generate_synthetic_scenarios()` and `nowcast_72h()` for richer responses.

4. **GAN model seeding** — For hackathon demo, set `GAN_ENABLED=false` initially. The GAN bootstrap runs in ~30s per zone on CPU. Call `POST /admin/adapt-premium/train` with `attach_gan=false` first.

5. **PHE key management** — `PaillierContext` generates keys in-memory at startup. For production, persist keys to encrypted volume. In hackathon demo, in-memory is fine (keys regenerate on restart).
## session5_patches.md
# Session 5 Patches
## Innovations 06 (DAO PremiumGov) + 07 (SoulboundNFT) + 08 (ZoneReinsurance)

These patches modify conflict-protected shared files.
All changes are ADDITIVE — nothing is removed or restructured.

---

## PATCH 5-1
### Target File: `backend/main.py`
### Location: After line containing → `from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo`
### Action: INSERT
### Code:
```python
from governance.governance_router import router as governance_router
from defi.amm_router import router as reinsurance_router
```
### Reason: Register the two new Session 5 routers so their endpoints are mounted on the FastAPI app.
### Conflicts With:
- Session 6 may also add imports to this line. Merge by appending to the import tuple.
- Session 7: If they add routers, concatenate all router imports together — do not replace.

---

## PATCH 5-2
### Target File: `backend/main.py`
### Location: After line containing → `app.include_router(demo.router)`
### Action: INSERT
### Code:
```python
app.include_router(governance_router)  # Session 5: DAO PremiumGov + SoulboundNFT
app.include_router(reinsurance_router) # Session 5: ZoneReinsurance Pool
```
### Reason: Mount the governance (/api/v1/governance) and reinsurance (/api/v1/reinsurance) routers.
### Conflicts With:
- Any session adding `app.include_router(...)` calls — concatenate, do not replace existing calls.
- Order does not matter for FastAPI router registration.

---

## PATCH 5-3
### Target File: `backend/main.py`
### Location: After line containing → `"auth": "/api/v1/auth",`
### Action: INSERT
### Code:
```python
            "governance":    "/api/v1/governance",
            "reinsurance":   "/api/v1/reinsurance",
```
### Reason: Expose new endpoint groups in the root API index response for discoverability.
### Conflicts With:
- Other sessions adding entries to the `endpoints` dict — safe to concatenate.
- Ensure trailing comma on the line above (`"auth": "/api/v1/auth",`) is present.

---

## PATCH 5-4
### Target File: `frontend/src/pages/RiderDashboard.tsx`
### Location: After line containing → `import type { PolicyData, ZoneSignalData, RawApiZone, RawApiPayout } from '../types'`
### Action: INSERT
### Code:
```tsx
import GovernancePanel from '../components/GovernancePanel'
```
### Reason: Import the GovernancePanel component for use in the new Governance tab.
### Conflicts With:
- Session 6 also modifies RiderDashboard. If Session 6 adds imports above the `import type` line,
  this patch is still safe — it appends after the type imports line.
- Session 7: Coordinate import ordering. All session imports should be grouped after existing imports.

---

## PATCH 5-5
### Target File: `frontend/src/pages/RiderDashboard.tsx`
### Location: After line containing → `const { fetchNotifications } = useNotifications()`
### Action: INSERT
### Code:
```tsx
  const [dashTab, setDashTab] = useState<'overview' | 'governance'>('overview')
```
### Reason: Add tab state for switching between Overview and Governance panes.
### Conflicts With:
- Session 6: If they also add a state variable here, merge both useState calls.
  Convention: each session's state variable name must be unique (Session 5 uses `dashTab`).

---

## PATCH 5-6
### Target File: `frontend/src/pages/RiderDashboard.tsx`
### Location: After line containing → `<main className="max-w-2xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4">`
### Action: INSERT
### Code:
```tsx
        {/* ── Session 5: Tab bar (Overview / Governance) ────────────────── */}
        <div className="flex gap-1 bg-stone-100 rounded-xl p-1">
          {(['overview', 'governance'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setDashTab(tab)}
              className={`flex-1 py-2 rounded-lg text-xs font-semibold capitalize transition-all ${
                dashTab === tab
                  ? 'bg-white text-amber-700 shadow-sm'
                  : 'text-stone-500 hover:text-stone-700'
              }`}
            >
              {tab === 'governance' ? '⬡ Governance' : 'Overview'}
            </button>
          ))}
        </div>
        {/* ── Session 5: Governance tab content ─────────────────────────── */}
        {dashTab === 'governance' && (
          <GovernancePanel riderId={rider.riderId} apiAvailable={!loading} />
        )}
        {/* ── Existing overview content below (wrapped in conditional) ───── */}
        {dashTab === 'overview' && (<>
```
### Reason:
Adds the tab switcher and renders <GovernancePanel /> when "Governance" tab is active.
Wraps existing content in `{dashTab === 'overview' && (<>` — the closing `</>)}` goes in PATCH 5-7.
### Conflicts With:
- Session 6: They may also add a tab. Coordinate tab labels and the tab array.
  Merge: add Session 6's tab to the tabs array; add another conditional block for their content.
- Do NOT move or restructure the existing `<main>` content — only wrap it.

---

## PATCH 5-7
### Target File: `frontend/src/pages/RiderDashboard.tsx`
### Location: After line containing → `</main>`  (the closing tag of the main element, line ~785)
### Action: REPLACE the `</main>` with:
### Code:
```tsx
        </>)}
        {/* ── End Session 5 overview conditional ────────────────────────── */}
      </main>
```
### Reason:
Closes the `{dashTab === 'overview' && (<>` fragment opened in PATCH 5-6.
This is the only structural change to existing content — it wraps (does not remove) existing JSX.
### Conflicts With:
- Session 6/7: If they also wrap content, coordinate the nesting order.
  Rule: outermost wrapper = earliest session number.
- If the overview content already ends with a different closing pattern due to another session's patch,
  adjust the fragment closing `</>)}` placement accordingly.

---

## PATCH 5-8 (Optional — backend/db/seed.py or equivalent)
### Target File: `backend/db/seed.py`
### Location: After line containing → (end of file / last seeding block)
### Action: INSERT
### Code:
```python
# Session 5: Seed sample reinsurance positions for demo
async def seed_reinsurance_demo(db):
    from governance.db_models import ReinsurancePositionDB
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    demo_positions = [
        ReinsurancePositionDB(
            position_id="RPOS-DEMO-SENIOR",
            provider_id="INST-HDFC-ERGO",
            provider_type="institutional",
            tranche="senior",
            amount_staked=2_000_000.0,
            pool_share_pct=47.6,
            expected_annual_yield_pct=10.0,
            lock_period_days=90,
            staked_at=now - timedelta(days=30),
            unlock_at=now + timedelta(days=60),
        ),
        ReinsurancePositionDB(
            position_id="RPOS-DEMO-JUNIOR",
            provider_id="NBFC-JAIPUR-MICRO",
            provider_type="nbfc",
            tranche="junior",
            amount_staked=300_000.0,
            pool_share_pct=71.4,
            expected_annual_yield_pct=27.5,
            lock_period_days=90,
            staked_at=now - timedelta(days=15),
            unlock_at=now + timedelta(days=75),
        ),
    ]
    for pos in demo_positions:
        existing = await db.get(ReinsurancePositionDB, pos.position_id)
        if not existing:
            db.add(pos)
    await db.commit()
```
### Reason: Provides realistic demo data for the reinsurance pool during hackathon judging.
### Conflicts With: Low risk — function name is unique. Call it from the main seed() function.

---

## INTEGRATION NOTES FOR OTHER SESSIONS

### For Session 6 (if modifying RiderDashboard):
- `dashTab` state variable is owned by Session 5. Do not redefine it.
- Add your tab to the tabs array in PATCH 5-6 and add your conditional block.
- Do not remove the `{dashTab === 'overview' && (<>` wrapper.

### For Session 7 (ZoneChain / Hyperledger Fabric):
- `GovernanceChaincode.ExecuteParameterChange(parameter, value, proposal_id)` is called by
  `governance/dao_gov.py::_execute_on_chain()`. Currently simulated with a sha256 tx hash.
  Replace the stub with the real Fabric SDK call when chaincode is deployed.
- `SoulboundChaincode.MintNFT(zk_hash, policy_id, week, year)` is called by
  `governance/soulbound_nft.py::_simulate_fabric_mint()`. Same — replace stub with SDK call.
- Non-transferability must be enforced at chaincode level too:
  * No TransferToken() function in GovernanceChaincode
  * ctx.GetClientIdentity().GetID() must match token owner on every mutation
  * No TransferNFT() function in SoulboundChaincode

### For ZK Identity Session:
- This session calls `GET {ZK_IDENTITY_BASE_URL}/api/v1/identity/{rider_id}/zk-hash`
- Set env var `ZK_IDENTITY_BASE_URL` to point to your service
- Set env var `ZONEGUARD_NFT_SALT` for the fallback hash salt
- If your endpoint structure differs, update `_resolve_zk_hash()` in soulbound_nft.py

### Environment variables added by Session 5:
```
ZK_IDENTITY_BASE_URL=http://localhost:8001   # ZK identity service URL
ZONEGUARD_NFT_SALT=zg-nft-salt-dev-2025      # fallback hash salt (change in prod)
```
Add these to `backend/.env.example`.
## session6_patches.md
---CURRENT FILES---
## backend/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from config import get_settings
from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo

try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
    HAS_SLOWAPI = True
except ImportError:
    limiter = None
    HAS_SLOWAPI = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup/shutdown events.
    
    Starts the background signal polling scheduler on startup
    and gracefully shuts it down on application exit.
    """
    from services.scheduler import start_scheduler, stop_scheduler
    
    # Startup
    logger.info("Starting ZoneGuard API...")
    start_scheduler()
    logger.info("ZoneGuard API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down ZoneGuard API...")
    stop_scheduler()
    logger.info("ZoneGuard API shutdown complete")


app = FastAPI(
    title="ZoneGuard API",
    description="AI-powered parametric income protection for Amazon Flex riders",
    version="2.0.0",
    lifespan=lifespan,
)

# Rate limiting
if HAS_SLOWAPI:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all routers
app.include_router(riders.router)
app.include_router(zones.router)
app.include_router(policies.router)
app.include_router(claims.router)
app.include_router(signals.router)
app.include_router(payouts.router)
app.include_router(admin.router)
app.include_router(simulator.router)
app.include_router(premium.router)
app.include_router(notifications.router)
app.include_router(chat.router)
app.include_router(auth.router)
app.include_router(demo.router)


@app.get("/")
async def root():
    return {
        "name": "ZoneGuard API",
        "version": "2.0.0",
        "description": "Parametric income protection for Amazon Flex riders — Bengaluru",
        "docs": "/docs",
        "endpoints": {
            "riders": "/api/v1/riders",
            "zones": "/api/v1/zones",
            "policies": "/api/v1/policies",
            "claims": "/api/v1/claims",
            "signals": "/api/v1/signals",
            "payouts": "/api/v1/payouts",
            "admin": "/api/v1/admin",
            "simulator": "/api/v1/simulator",
            "premium": "/api/v1/premium",
            "notifications": "/api/v1/notifications",
            "chat": "/api/v1/chat",
            "auth": "/api/v1/auth",
        },
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "env": settings.app_env}


@app.get("/health/detailed")
async def health_detailed():
    """Detailed health check: DB connectivity, API key availability."""
    checks = {}

    # DB check
    try:
        from db.database import async_session
        from sqlalchemy import text
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}

    # Weather API key
    checks["openweathermap"] = {
        "status": "ok" if settings.openweathermap_api_key else "missing",
        "has_key": bool(settings.openweathermap_api_key),
    }

    # Gemini API key
    checks["gemini"] = {
        "status": "ok" if settings.gemini_api_key else "missing",
        "has_key": bool(settings.gemini_api_key),
    }

    all_ok = all(
        c.get("status") == "ok" for c in checks.values()
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "env": settings.app_env,
        "checks": checks,
    }


# Mangum handler for AWS Lambda (if deployed there)
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    pass
## backend/routers/claims.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.claim import Claim
from models.payout import Payout
from models.audit import AuditLog
from models.rider import Rider
from schemas.claim import ClaimResponse, ClaimReview
from integrations.payout_sim import process_payout
from integrations.gemini import generate_audit_report
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/claims", tags=["claims"])


@router.get("/stats")
async def claim_stats(db: AsyncSession = Depends(get_db)):
    """Aggregate claim statistics: approval rate, avg payout, velocity."""
    total_result = await db.execute(select(func.count(Claim.id)))
    total = total_result.scalar() or 0

    approved_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "approved")
    )
    approved = approved_result.scalar() or 0

    rejected_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "rejected")
    )
    rejected = rejected_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status.in_(["pending_review", "held"]))
    )
    pending = pending_result.scalar() or 0

    avg_payout_result = await db.execute(
        select(func.avg(Claim.actual_payout)).where(Claim.actual_payout.isnot(None))
    )
    avg_payout = avg_payout_result.scalar() or 0

    avg_fraud_result = await db.execute(
        select(func.avg(Claim.fraud_score)).where(Claim.fraud_score.isnot(None))
    )
    avg_fraud = avg_fraud_result.scalar() or 0

    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "pending": pending,
        "approval_rate": round(approved / total * 100, 1) if total else 0,
        "avg_payout": round(float(avg_payout), 2),
        "avg_fraud_score": round(float(avg_fraud), 3),
    }


@router.get("")
async def list_claims(
    status: str = Query(None),
    zone_id: str = Query(None),
    rider_id: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Claim)
    if status:
        query = query.where(Claim.status == status)
    if zone_id:
        query = query.where(Claim.zone_id == zone_id)
    if rider_id:
        query = query.where(Claim.rider_id == rider_id)
    query = query.order_by(Claim.created_at.desc())

    from utils.pagination import paginate
    return await paginate(db, query, ClaimResponse, page, per_page)


@router.get("/{claim_id}")
async def get_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Get audit report if exists
    audit_result = await db.execute(
        select(AuditLog).where(AuditLog.claim_id == claim_id).order_by(AuditLog.created_at.desc())
    )
    audit = audit_result.scalars().first()

    return {
        "claim": ClaimResponse.model_validate(claim),
        "audit_report": {
            "content": audit.content if audit else None,
            "model_used": audit.model_used if audit else None,
            "generated_at": audit.created_at.isoformat() if audit else None,
        } if audit else None,
    }


@router.get("/{claim_id}/audit-report")
async def get_claim_audit_report(claim_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch or generate a Gemini audit report for a claim."""
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Check if audit report already exists
    existing = await db.execute(
        select(AuditLog)
        .where(AuditLog.claim_id == claim_id)
        .where(AuditLog.event_type == "gemini_audit")
        .order_by(AuditLog.created_at.desc())
    )
    audit = existing.scalars().first()

    if audit:
        return {
            "claim_id": claim_id,
            "content": audit.content,
            "model_used": audit.model_used,
            "generated_at": audit.created_at.isoformat(),
        }

    # Generate new audit report
    report = await generate_audit_report({
        "claim_id": claim_id,
        "zone_id": claim.zone_id,
        "confidence": claim.confidence,
        "signals_fired": claim.exclusion_check.get("signals_fired", 3) if claim.exclusion_check else 3,
        "exclusion_check": claim.exclusion_check,
        "fraud_score": claim.fraud_score,
        "signal_details": claim.exclusion_check.get("signal_details", {}) if claim.exclusion_check else {},
    })

    # Store the audit report
    audit_log = AuditLog(
        claim_id=claim_id,
        event_type="gemini_audit",
        content=report["report"],
        model_used=report["model_used"],
        generated_by="gemini",
    )
    db.add(audit_log)
    await db.commit()

    return {
        "claim_id": claim_id,
        "content": report["report"],
        "model_used": report["model_used"],
        "generated_at": audit_log.created_at.isoformat() if audit_log.created_at else datetime.now(timezone.utc).isoformat(),
    }


@router.post("/{claim_id}/challenge")
async def challenge_claim(claim_id: str, db: AsyncSession = Depends(get_db)):
    """Rider contests a rejected claim. Flips status back to pending_review."""
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status != "rejected":
        raise HTTPException(status_code=400, detail="Only rejected claims can be challenged")

    claim.status = "pending_review"
    claim.reviewed_at = None
    claim.reviewed_by = None

    audit = AuditLog(
        claim_id=claim_id,
        event_type="claim_challenge",
        content=f"Claim challenged by rider {claim.rider_id}. Status reset to pending_review.",
        generated_by=claim.rider_id,
    )
    db.add(audit)
    await db.commit()

    return {
        "claim_id": claim_id,
        "status": "pending_review",
        "message": "Claim has been reopened for review",
    }


@router.post("/{claim_id}/review")
async def review_claim(claim_id: str, payload: ClaimReview, db: AsyncSession = Depends(get_db)):
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.status not in ("pending_review", "held"):
        raise HTTPException(status_code=400, detail=f"Claim cannot be reviewed in '{claim.status}' status")

    claim.status = "approved" if payload.action == "approve" else "rejected"
    claim.reviewed_at = datetime.now(timezone.utc)
    claim.reviewed_by = payload.reviewed_by

    payout_result = None
    if payload.action == "approve":
        claim.actual_payout = claim.recommended_payout

        # Ensure no duplicate payout exists for this claim
        existing_payout = await db.execute(select(Payout).where(Payout.claim_id == claim_id))
        if not existing_payout.scalars().first():
            rider = await db.get(Rider, claim.rider_id)
            upi_id = rider.upi_id if rider else None
            payout_result = await process_payout(claim.rider_id, claim.recommended_payout, upi_id)
            payout = Payout(
                claim_id=claim_id,
                rider_id=claim.rider_id,
                amount=claim.recommended_payout,
                upi_ref=payout_result["upi_ref"],
                status=payout_result["status"],
                gateway_response=str(payout_result["gateway_response"]),
            )
            if payout_result["status"] == "settled":
                payout.settled_at = datetime.now(timezone.utc)
            db.add(payout)

    # Log the review
    audit = AuditLog(
        claim_id=claim_id,
        event_type="claim_review",
        content=f"Claim {payload.action}d by {payload.reviewed_by}",
        generated_by=payload.reviewed_by,
    )
    db.add(audit)
    await db.commit()

    return {
        "status": claim.status,
        "claim_id": claim_id,
        "payout": payout_result,
    }
## backend/routers/policies.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from models.policy import Policy, PolicyAppliedExclusion, PolicyExclusionType
from models.premium_payment import PremiumPayment
from models.zone import Zone
from models.rider import Rider
from schemas.policy import PolicyCreate, PolicyResponse, ExclusionResponse
from services.exclusion_engine import get_all_exclusion_types
from ml.zone_risk_scorer import calculate_zone_premium
from models.notification import create_notification, NotificationType
from datetime import datetime, timedelta, timezone
import uuid

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


@router.post("")
async def create_policy(payload: PolicyCreate, db: AsyncSession = Depends(get_db)):
    """Create a weekly policy with all exclusions attached."""

    zone = await db.get(Zone, payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    rider = await db.get(Rider, payload.rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    # Calculate premium
    premium_info = calculate_zone_premium(
        {"historical_disruptions": zone.historical_disruptions, "risk_tier": zone.risk_tier, "active_riders": zone.active_riders},
        rider_tenure_weeks=rider.tenure_weeks,
    )

    weekly_premium = premium_info["premium"]
    # Forward Premium Lock: 8% discount for 4-week commitment
    if payload.is_forward_locked and payload.forward_lock_weeks >= 4:
        weekly_premium = round(weekly_premium * 0.92)

    now = datetime.now(timezone.utc)
    policy = Policy(
        rider_id=payload.rider_id,
        zone_id=payload.zone_id,
        weekly_premium=weekly_premium,
        max_payout=premium_info["max_payout"],
        coverage_start=now,
        coverage_end=now + timedelta(weeks=1),
        is_forward_locked=payload.is_forward_locked,
        forward_lock_weeks=payload.forward_lock_weeks,
    )
    db.add(policy)
    await db.flush()

    # Attach all 10 standard exclusions
    exclusion_types = get_all_exclusion_types()
    for excl in exclusion_types:
        # Ensure exclusion type exists in DB
        existing = await db.get(PolicyExclusionType, excl["id"])
        if not existing:
            db.add(PolicyExclusionType(**excl))

        applied = PolicyAppliedExclusion(
            id=uuid.uuid4().hex[:12],
            policy_id=policy.id,
            exclusion_type_id=excl["id"],
        )
        db.add(applied)

    # Create premium payment record for the policy
    premium_payment = PremiumPayment(
        id=str(uuid.uuid4()),
        rider_id=policy.rider_id,
        policy_id=policy.id,
        amount=policy.weekly_premium,
        week_start=policy.coverage_start.date(),
        week_end=policy.coverage_end.date(),
        status="paid",
        payment_method="UPI",
        transaction_ref=f"ZG-PREM-{uuid.uuid4().hex[:8].upper()}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(premium_payment)

    # Notify rider
    await create_notification(
        db=db, rider_id=payload.rider_id, type=NotificationType.POLICY_ACTIVATED,
        title="Policy Activated",
        message=f"Your ZoneGuard policy for {zone.name} is active. Premium: ₹{weekly_premium}/week. Max payout: ₹{premium_info['max_payout']:,}.",
        metadata={"policy_id": policy.id, "zone_id": payload.zone_id},
    )

    await db.commit()
    await db.refresh(policy)

    return {
        "policy": {
            "id": policy.id,
            "rider_id": policy.rider_id,
            "zone_id": policy.zone_id,
            "status": policy.status,
            "weekly_premium": policy.weekly_premium,
            "max_payout": policy.max_payout,
            "coverage_start": policy.coverage_start.isoformat(),
            "coverage_end": policy.coverage_end.isoformat(),
            "is_forward_locked": policy.is_forward_locked,
            "forward_lock_weeks": policy.forward_lock_weeks,
        },
        "exclusions": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in exclusion_types],
        "premium_breakdown": premium_info,
    }


@router.get("")
async def list_policies(rider_id: str = Query(None), db: AsyncSession = Depends(get_db)):
    query = select(Policy)
    if rider_id:
        query = query.where(Policy.rider_id == rider_id)
    query = query.order_by(Policy.created_at.desc())
    result = await db.execute(query)
    policies = result.scalars().all()
    return [PolicyResponse.model_validate(p) for p in policies]


@router.get("/{policy_id}")
async def get_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    # Get applied exclusions
    result = await db.execute(
        select(PolicyExclusionType)
        .join(PolicyAppliedExclusion)
        .where(PolicyAppliedExclusion.policy_id == policy_id)
    )
    exclusions = result.scalars().all()

    return {
        "policy": PolicyResponse.model_validate(policy),
        "exclusions": [ExclusionResponse.model_validate(e) for e in exclusions],
    }


@router.get("/{policy_id}/exclusions")
async def get_policy_exclusions(policy_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PolicyExclusionType)
        .join(PolicyAppliedExclusion)
        .where(PolicyAppliedExclusion.policy_id == policy_id)
    )
    exclusions = result.scalars().all()
    return [ExclusionResponse.model_validate(e) for e in exclusions]


@router.post("/{policy_id}/renew")
async def renew_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    old_policy = await db.get(Policy, policy_id)
    if not old_policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    old_policy.status = "expired"

    now = datetime.now(timezone.utc)
    new_policy = Policy(
        rider_id=old_policy.rider_id,
        zone_id=old_policy.zone_id,
        weekly_premium=old_policy.weekly_premium,
        max_payout=old_policy.max_payout,
        coverage_start=now,
        coverage_end=now + timedelta(weeks=1),
        is_forward_locked=old_policy.is_forward_locked,
        forward_lock_weeks=max(0, old_policy.forward_lock_weeks - 1),
    )
    db.add(new_policy)
    await db.flush()

    # Create premium payment record for the renewed policy
    premium_payment = PremiumPayment(
        id=str(uuid.uuid4()),
        rider_id=new_policy.rider_id,
        policy_id=new_policy.id,
        amount=new_policy.weekly_premium,
        week_start=new_policy.coverage_start.date(),
        week_end=new_policy.coverage_end.date(),
        status="paid",
        payment_method="UPI",
        transaction_ref=f"ZG-PREM-{uuid.uuid4().hex[:8].upper()}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(premium_payment)

    await db.commit()

    return {"old_policy_id": policy_id, "new_policy": PolicyResponse.model_validate(new_policy)}


@router.post("/{policy_id}/forward-lock")
async def activate_forward_lock(policy_id: str, db: AsyncSession = Depends(get_db)):
    """Activate Forward Premium Lock: 4-week commitment with 8% discount."""
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    if policy.status != "active":
        raise HTTPException(status_code=400, detail="Only active policies can be forward-locked")
    if policy.is_forward_locked:
        raise HTTPException(status_code=400, detail="Policy already forward-locked")

    original_premium = policy.weekly_premium
    discounted_premium = round(original_premium * 0.92)
    savings_per_week = original_premium - discounted_premium

    policy.is_forward_locked = True
    policy.forward_lock_weeks = 4
    policy.weekly_premium = discounted_premium

    await db.commit()
    await db.refresh(policy)

    return {
        "policy_id": policy.id,
        "is_forward_locked": True,
        "weeks_remaining": policy.forward_lock_weeks,
        "original_premium": original_premium,
        "weekly_premium": discounted_premium,
        "discount_pct": 8,
        "savings_per_week": savings_per_week,
        "total_savings": savings_per_week * 4,
    }


@router.post("/{policy_id}/cancel")
async def cancel_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    policy = await db.get(Policy, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    policy.status = "cancelled"
    await db.commit()
    return {"status": "cancelled", "policy_id": policy_id}
## backend/routers/riders.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from db.database import get_db
from models.rider import Rider
from models.zone import Zone
from models.claim import Claim
from models.payout import Payout
from schemas.rider import RiderRegister, RiderResponse, RiderKYC, EShramVerifyRequest
from schemas.claim import ClaimResponse
from schemas.payout import PayoutResponse
from ml.zone_risk_scorer import calculate_zone_premium

router = APIRouter(prefix="/api/v1/riders", tags=["riders"])


@router.get("")
async def list_riders(
    zone_id: str = Query(None),
    kyc_verified: bool = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all riders with optional zone/KYC filter and pagination."""
    query = select(Rider)
    if zone_id:
        query = query.where(Rider.zone_id == zone_id)
    if kyc_verified is not None:
        query = query.where(Rider.kyc_verified == kyc_verified)
    query = query.order_by(Rider.created_at.desc())

    # Count total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    riders = result.scalars().all()

    return {
        "items": [RiderResponse.model_validate(r) for r in riders],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.post("/register")
async def register_rider(payload: RiderRegister, db: AsyncSession = Depends(get_db)):
    """Register a new rider and return premium quote."""

    # Check zone exists
    zone = await db.get(Zone, payload.zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    # Check rider doesn't already exist
    existing = await db.get(Rider, payload.rider_id)
    if existing:
        raise HTTPException(status_code=409, detail="Rider already registered")

    # Create rider
    rider = Rider(
        id=payload.rider_id,
        name=payload.name,
        phone=payload.phone,
        zone_id=payload.zone_id,
        weekly_earnings_baseline=payload.weekly_earnings,
        upi_id=payload.upi_id,
        eshram_id=payload.eshram_id,
    )
    db.add(rider)

    # Update zone active rider count
    zone.active_riders = (zone.active_riders or 0) + 1

    await db.commit()
    await db.refresh(rider)

    # Calculate premium quote
    premium_quote = calculate_zone_premium(
        {
            "historical_disruptions": zone.historical_disruptions,
            "risk_tier": zone.risk_tier,
            "active_riders": zone.active_riders,
        },
        rider_tenure_weeks=0,
    )

    return {
        "rider": RiderResponse.model_validate(rider),
        "premium_quote": premium_quote,
    }


@router.get("/{rider_id}")
async def get_rider(rider_id: str, db: AsyncSession = Depends(get_db)):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")
    return RiderResponse.model_validate(rider)


@router.put("/{rider_id}")
async def update_rider(rider_id: str, updates: dict, db: AsyncSession = Depends(get_db)):
    """Update rider details (name, phone, zone_id, weekly_earnings_baseline, upi_id)."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    allowed = {"name", "phone", "zone_id", "weekly_earnings_baseline", "upi_id"}
    for key, value in updates.items():
        if key in allowed:
            setattr(rider, key, value)

    await db.commit()
    await db.refresh(rider)
    return RiderResponse.model_validate(rider)


@router.get("/{rider_id}/claims")
async def get_rider_claims(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Get all claims for a specific rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    result = await db.execute(
        select(Claim).where(Claim.rider_id == rider_id).order_by(Claim.created_at.desc())
    )
    claims = result.scalars().all()
    return [ClaimResponse.model_validate(c) for c in claims]


@router.get("/{rider_id}/payouts")
async def get_rider_payouts(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Get all payouts for a specific rider."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    result = await db.execute(
        select(Payout).where(Payout.rider_id == rider_id).order_by(Payout.created_at.desc())
    )
    payouts = result.scalars().all()
    return [PayoutResponse.model_validate(p) for p in payouts]


@router.post("/{rider_id}/kyc")
async def update_kyc(rider_id: str, payload: RiderKYC, db: AsyncSession = Depends(get_db)):
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    rider.upi_id = payload.upi_id
    rider.phone = payload.phone
    rider.kyc_verified = True
    await db.commit()

    return {"status": "kyc_verified", "rider_id": rider_id}


@router.post("/{rider_id}/verify-eshram")
async def verify_eshram(
    rider_id: str, payload: EShramVerifyRequest, db: AsyncSession = Depends(get_db),
):
    """Verify rider via e-Shram portal (simulated)."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    from integrations.eshram_sim import verify_eshram_worker, check_income_proxy

    verification = await verify_eshram_worker(
        eshram_id=payload.eshram_id,
        rider_name=rider.name,
        phone=rider.phone or "",
    )

    if verification["verified"]:
        rider.eshram_id = payload.eshram_id
        rider.eshram_verified = True
        rider.kyc_verified = True

        # Cross-reference income if rider has earnings baseline
        if rider.weekly_earnings_baseline > 0:
            income_check = await check_income_proxy(
                eshram_id=payload.eshram_id,
                declared_weekly_earnings=rider.weekly_earnings_baseline,
            )
            verification["income_proxy"] = income_check

        await db.commit()

    return verification
## backend/ml/zone_twin.py
"""
ZoneTwin — Per-zone lightweight counterfactual simulation.

Uses historical baselines to answer:
"At this rainfall level, how many riders historically went dark?"

Returns (p10, p50, p90) expected inactivity percentiles for grounding
fraud checks and claim validation.
"""

import random
import math


# Historical baselines per zone (simulated from IMD + rider data)
ZONE_BASELINES = {
    "hsr": {
        "avg_rainfall_mm": 28, "avg_mobility": 88, "avg_inactivity_pct": 8,
        "disruption_rainfall_threshold": 55, "flood_correlation": 0.82,
    },
    "koramangala": {
        "avg_rainfall_mm": 25, "avg_mobility": 91, "avg_inactivity_pct": 6,
        "disruption_rainfall_threshold": 58, "flood_correlation": 0.75,
    },
    "whitefield": {
        "avg_rainfall_mm": 18, "avg_mobility": 93, "avg_inactivity_pct": 4,
        "disruption_rainfall_threshold": 70, "flood_correlation": 0.45,
    },
    "indiranagar": {
        "avg_rainfall_mm": 22, "avg_mobility": 90, "avg_inactivity_pct": 7,
        "disruption_rainfall_threshold": 60, "flood_correlation": 0.68,
    },
    "electronic-city": {
        "avg_rainfall_mm": 20, "avg_mobility": 92, "avg_inactivity_pct": 5,
        "disruption_rainfall_threshold": 65, "flood_correlation": 0.52,
    },
    "bellandur": {
        "avg_rainfall_mm": 35, "avg_mobility": 78, "avg_inactivity_pct": 15,
        "disruption_rainfall_threshold": 45, "flood_correlation": 0.94,
    },
    "btm-layout": {
        "avg_rainfall_mm": 30, "avg_mobility": 84, "avg_inactivity_pct": 10,
        "disruption_rainfall_threshold": 50, "flood_correlation": 0.80,
    },
    "jp-nagar": {
        "avg_rainfall_mm": 27, "avg_mobility": 86, "avg_inactivity_pct": 9,
        "disruption_rainfall_threshold": 52, "flood_correlation": 0.77,
    },
    "yelahanka": {
        "avg_rainfall_mm": 15, "avg_mobility": 95, "avg_inactivity_pct": 3,
        "disruption_rainfall_threshold": 72, "flood_correlation": 0.35,
    },
    "hebbal": {
        "avg_rainfall_mm": 26, "avg_mobility": 85, "avg_inactivity_pct": 11,
        "disruption_rainfall_threshold": 54, "flood_correlation": 0.78,
    },
}


def counterfactual_inactivity(zone_id: str, rainfall_mm: float, aqi: float = 100) -> dict:
    """
    Given current conditions, estimate expected rider inactivity
    based on historical zone behavior.

    Returns p10/p50/p90 percentiles for expected inactivity %.
    """
    baseline = ZONE_BASELINES.get(zone_id, ZONE_BASELINES["hsr"])

    # How severe is current rainfall relative to zone's disruption threshold?
    rainfall_ratio = rainfall_mm / max(baseline["disruption_rainfall_threshold"], 1)

    # Logistic curve: maps rainfall_ratio to expected inactivity multiplier
    # At ratio=1 (threshold), expect ~40-50% inactivity
    # At ratio=2 (2x threshold), expect ~70-80% inactivity
    base_inactivity = baseline["avg_inactivity_pct"]
    multiplier = 1 + (baseline["flood_correlation"] * 10 * (1 / (1 + math.exp(-3 * (rainfall_ratio - 0.8)))))

    # AQI contribution
    if aqi > 300:
        multiplier += 0.5
    elif aqi > 200:
        multiplier += 0.2

    expected_median = min(90, base_inactivity * multiplier)

    # Simulate percentile spread based on zone's historical variance
    variance = max(5, expected_median * 0.25)
    p10 = max(0, round(expected_median - 1.28 * variance, 1))
    p50 = round(expected_median, 1)
    p90 = min(100, round(expected_median + 1.28 * variance, 1))

    return {
        "zone_id": zone_id,
        "conditions": {"rainfall_mm": rainfall_mm, "aqi": aqi},
        "expected_inactivity": {"p10": p10, "p50": p50, "p90": p90},
        "historical_baseline": {
            "avg_inactivity_pct": baseline["avg_inactivity_pct"],
            "disruption_threshold_mm": baseline["disruption_rainfall_threshold"],
            "flood_correlation": baseline["flood_correlation"],
        },
        "interpretation": _interpret(p50, rainfall_mm, baseline),
    }


def _interpret(expected_pct: float, rainfall: float, baseline: dict) -> str:
    if expected_pct > 50:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, historically {expected_pct:.0f}% of riders "
            f"went dark in this zone. This is consistent with a major disruption event."
        )
    elif expected_pct > 25:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, historically {expected_pct:.0f}% of riders "
            f"reported inactivity. Moderate disruption expected."
        )
    else:
        return (
            f"At {rainfall:.0f}mm/hr rainfall, only {expected_pct:.0f}% rider inactivity "
            f"expected historically. Current conditions are within normal range."
        )
## backend/ml/zone_risk_scorer.py
"""
ZoneRisk Scorer — Weighted rule-based risk model.

5 factors with transparent weights:
- disruption_freq (35%): historical disruption frequency for the zone
- imd_forecast (25%): IMD seasonal forecast severity
- rider_tenure (15%): rider's tenure in weeks (lower = higher risk)
- zone_class (15%): zone classification risk level
- claim_history (10%): recent claim volume for the zone

Output: risk score 0-100 → premium tier (₹39/₹89/₹139/₹225)
"""

PREMIUM_TIERS = {
    (0, 30): {"premium": 39, "tier": "low", "max_payout": 1430},
    (30, 55): {"premium": 89, "tier": "medium", "max_payout": 4290},
    (55, 75): {"premium": 139, "tier": "high", "max_payout": 7150},
    (75, 101): {"premium": 225, "tier": "flood-prone", "max_payout": 11440},
}

# Zone classification base scores
ZONE_CLASS_SCORES = {
    "low": 20,
    "medium": 50,
    "high": 70,
    "flood-prone": 90,
}


def calculate_risk_score(
    disruption_freq: int,        # historical disruptions per year
    imd_forecast_severity: float, # 0-100 severity from IMD
    rider_tenure_weeks: int,
    zone_classification: str,
    recent_claims_7d: int,
    total_zone_riders: int,
) -> dict:
    """Calculate zone risk score with full factor breakdown."""

    # Factor 1: Disruption frequency (35%)
    # Scale: 0 disruptions = 0, 10+ = 100
    disrupt_score = min(100, (disruption_freq / 10) * 100)

    # Factor 2: IMD forecast (25%)
    imd_score = min(100, imd_forecast_severity)

    # Factor 3: Rider tenure (15%)
    # New riders = higher risk, capped at 52 weeks
    tenure_score = max(0, 100 - (min(rider_tenure_weeks, 52) / 52 * 100))

    # Factor 4: Zone classification (15%)
    zone_score = ZONE_CLASS_SCORES.get(zone_classification, 50)

    # Factor 5: Claim history (10%)
    # Claims as % of riders, scaled
    claim_rate = (recent_claims_7d / max(total_zone_riders, 1)) * 100
    claim_score = min(100, claim_rate * 10)  # 10% claim rate = 100

    # Weighted total
    weights = {
        "disruption_freq": 0.35,
        "imd_forecast": 0.25,
        "rider_tenure": 0.15,
        "zone_class": 0.15,
        "claim_history": 0.10,
    }

    scores = {
        "disruption_freq": disrupt_score,
        "imd_forecast": imd_score,
        "rider_tenure": tenure_score,
        "zone_class": zone_score,
        "claim_history": claim_score,
    }

    total_score = sum(scores[k] * weights[k] for k in weights)
    total_score = round(min(100, max(0, total_score)))

    # Determine premium tier
    tier_info = {"premium": 49, "tier": "medium", "max_payout": 2200}
    for (low, high), info in PREMIUM_TIERS.items():
        if low <= total_score < high:
            tier_info = info
            break

    factor_breakdown = {}
    for k in weights:
        contribution = round(scores[k] * weights[k], 1)
        factor_breakdown[k] = {
            "weight": weights[k],
            "raw_score": round(scores[k], 1),
            "contribution": contribution,
            "contribution_inr": round(contribution * tier_info["premium"] / 100, 1),
        }

    return {
        "risk_score": total_score,
        "premium": tier_info["premium"],
        "tier": tier_info["tier"],
        "max_payout": tier_info["max_payout"],
        "factor_breakdown": factor_breakdown,
    }


def calculate_zone_premium(zone_data: dict, rider_tenure_weeks: int = 0) -> dict:
    """Convenience function for zone-based premium calculation."""
    return calculate_risk_score(
        disruption_freq=zone_data.get("historical_disruptions", 3),
        imd_forecast_severity=zone_data.get("imd_severity", 40),
        rider_tenure_weeks=rider_tenure_weeks,
        zone_classification=zone_data.get("risk_tier", "medium"),
        recent_claims_7d=zone_data.get("recent_claims", 2),
        total_zone_riders=zone_data.get("active_riders", 100),
    )
## backend/ml/signal_fusion.py
"""
QuadSignal Fusion Engine — 4 independent signals must converge within a 2-hour rolling window.

Signal types and thresholds:
- S1 Environmental: rainfall >65mm/hr, AQI >300, temp >43°C, or NDMA flood alert
- S2 Mobility: zone mobility index drops >75% from 7-day rolling baseline
- S3 Economic: order volume drops >70% from hourly baseline
- S4 Crowd: ≥40% of zone riders self-report inactivity via WhatsApp check-ins

Confidence levels:
- 4 signals = HIGH → auto-payout
- 3 signals = MEDIUM → 1hr recheck
- 2 signals = LOW → human review
- 1 signal = NOISE → no action
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

# Thresholds
THRESHOLDS = {
    "S1": {
        "rainfall_mm_hr": 65,
        "aqi": 300,
        "temp_celsius": 43,
    },
    "S2": {
        "mobility_drop_pct": 75,  # mobility < 25% of baseline
    },
    "S3": {
        "order_drop_pct": 70,  # orders < 30% of baseline
    },
    "S4": {
        "inactivity_pct": 40,  # ≥40% riders inactive
    },
}

CONFIDENCE_MAP = {4: "HIGH", 3: "MEDIUM", 2: "LOW", 1: "NOISE", 0: "NOISE"}
ROLLING_WINDOW_HOURS = 2


def evaluate_s1(rainfall_mm: float, aqi: float, temp_c: float, ndma_alert: bool = False) -> dict:
    """Evaluate S1 Environmental signal."""
    if ndma_alert:
        return {"breached": True, "value": "NDMA flood alert active", "reason": "ndma_override"}

    breached = (
        rainfall_mm > THRESHOLDS["S1"]["rainfall_mm_hr"]
        or aqi > THRESHOLDS["S1"]["aqi"]
        or temp_c > THRESHOLDS["S1"]["temp_celsius"]
    )

    reasons = []
    if rainfall_mm > THRESHOLDS["S1"]["rainfall_mm_hr"]:
        reasons.append(f"rainfall {rainfall_mm:.0f}mm/hr > {THRESHOLDS['S1']['rainfall_mm_hr']}mm/hr")
    if aqi > THRESHOLDS["S1"]["aqi"]:
        reasons.append(f"AQI {aqi:.0f} > {THRESHOLDS['S1']['aqi']}")
    if temp_c > THRESHOLDS["S1"]["temp_celsius"]:
        reasons.append(f"temp {temp_c:.1f}°C > {THRESHOLDS['S1']['temp_celsius']}°C")

    return {
        "breached": breached,
        "value": rainfall_mm,
        "threshold": THRESHOLDS["S1"]["rainfall_mm_hr"],
        "details": {"rainfall_mm": rainfall_mm, "aqi": aqi, "temp_c": temp_c, "ndma_alert": ndma_alert},
        "reason": "; ".join(reasons) if reasons else "within normal range",
    }


def evaluate_s2(mobility_index: float, baseline: float = 100) -> dict:
    """Evaluate S2 Mobility signal."""
    pct_of_baseline = (mobility_index / max(baseline, 1)) * 100
    breached = pct_of_baseline < (100 - THRESHOLDS["S2"]["mobility_drop_pct"])

    return {
        "breached": breached,
        "value": round(pct_of_baseline, 1),
        "threshold": 100 - THRESHOLDS["S2"]["mobility_drop_pct"],
        "details": {"mobility_index": mobility_index, "baseline": baseline, "pct_of_baseline": round(pct_of_baseline, 1)},
        "reason": f"mobility at {pct_of_baseline:.0f}% of baseline" + (" — BREACHED" if breached else ""),
    }


def evaluate_s3(order_volume: float, baseline: float = 100) -> dict:
    """Evaluate S3 Economic signal."""
    pct_of_baseline = (order_volume / max(baseline, 1)) * 100
    breached = pct_of_baseline < (100 - THRESHOLDS["S3"]["order_drop_pct"])

    return {
        "breached": breached,
        "value": round(pct_of_baseline, 1),
        "threshold": 100 - THRESHOLDS["S3"]["order_drop_pct"],
        "details": {"order_volume": order_volume, "baseline": baseline, "pct_of_baseline": round(pct_of_baseline, 1)},
        "reason": f"orders at {pct_of_baseline:.0f}% of baseline" + (" — BREACHED" if breached else ""),
    }


def evaluate_s4(inactive_riders: int, total_riders: int) -> dict:
    """Evaluate S4 Crowd signal."""
    pct_inactive = (inactive_riders / max(total_riders, 1)) * 100
    breached = pct_inactive >= THRESHOLDS["S4"]["inactivity_pct"]

    return {
        "breached": breached,
        "value": round(pct_inactive, 1),
        "threshold": THRESHOLDS["S4"]["inactivity_pct"],
        "details": {"inactive_riders": inactive_riders, "total_riders": total_riders, "pct_inactive": round(pct_inactive, 1)},
        "reason": f"{pct_inactive:.0f}% riders inactive ({inactive_riders}/{total_riders})" + (" — BREACHED" if breached else ""),
    }


def fuse_signals(s1: dict, s2: dict, s3: dict, s4: dict) -> dict:
    """Fuse all 4 signals into a disruption assessment."""
    signals = {"S1": s1, "S2": s2, "S3": s3, "S4": s4}
    fired = sum(1 for s in signals.values() if s["breached"])
    confidence = CONFIDENCE_MAP.get(fired, "NOISE")

    return {
        "signals_fired": fired,
        "confidence": confidence,
        "signal_details": signals,
        "should_auto_payout": confidence == "HIGH",
        "should_recheck": confidence == "MEDIUM",
        "needs_review": confidence == "LOW",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
## backend/ml/federated/client.py
"""
FraudShield v2 — Federated Client.

Each client represents a city-level fraud detection node that trains
on local claim data and shares only model parameters (never raw data)
with the central aggregation server.
"""

from ml.federated.model import FederatedAnomalyModel


class FederatedClient:
    """City-level federated learning client for FraudShield v2."""

    def __init__(self, city_id: str, zone_ids: list[str]) -> None:
        self.city_id = city_id
        self.zone_ids = zone_ids
        self.model = FederatedAnomalyModel()
        self.training_samples: int = 0

    def train_local_model(self, claim_data: list[dict]) -> dict:
        """Train on local city data. Returns model weights (NOT raw data).

        This is the core privacy guarantee of federated learning: raw
        claim-level data never leaves the city node.  Only aggregated
        statistics (means, stds, weights) are shared.
        """
        self.model.fit(claim_data)
        self.training_samples = len(claim_data)
        return self.model.get_weights()

    def get_model_weights(self) -> dict:
        """Return current local model parameters."""
        return self.model.get_weights()

    def update_model(self, global_weights: dict) -> None:
        """Apply global model parameters received from the server."""
        self.model.set_weights(global_weights)

    def predict(self, claim_features: dict) -> dict:
        """Score a claim using the local (or globally-updated) model."""
        return self.model.predict(claim_features)
## backend/ml/federated/server.py
"""
FraudShield v2 — Federated Aggregation Server.

Implements FedAvg (Federated Averaging) for aggregating anomaly-model
parameters from city-level clients.  Inspired by the Flower framework
but implemented as a lightweight simulation for hackathon demo purposes.
"""

import numpy as np

from ml.federated.client import FederatedClient
from ml.federated.model import FederatedAnomalyModel


class FederatedServer:
    """Central aggregation server implementing FedAvg for FraudShield v2."""

    def __init__(self, num_rounds: int = 5) -> None:
        self.num_rounds = num_rounds
        self.clients: list[FederatedClient] = []
        self.global_model = FederatedAnomalyModel()
        self.training_history: list[dict] = []
        self.is_trained: bool = False

    # ------------------------------------------------------------------
    # Client management
    # ------------------------------------------------------------------

    def register_client(self, client: FederatedClient) -> None:
        """Register a city-level client with the server."""
        self.clients.append(client)

    # ------------------------------------------------------------------
    # FedAvg aggregation
    # ------------------------------------------------------------------

    def aggregate_weights(
        self,
        client_weights: list[dict],
        sample_counts: list[int],
    ) -> dict:
        """FedAvg: weighted average of client parameters by sample count.

        For each parameter group (weights, means, stds) and each feature,
        the global value is::

            global[param][feature] = sum(
                client_i[param][feature] * n_i
            ) / sum(n_i)

        where ``n_i`` is the number of training samples on client i.
        """
        total_samples = sum(sample_counts)
        if total_samples == 0:
            # Nothing to aggregate — return the first client's weights
            # or current global weights as a safe fallback.
            return client_weights[0] if client_weights else self.global_model.get_weights()

        feature_names = FederatedAnomalyModel.FEATURE_NAMES
        aggregated: dict = {"weights": {}, "means": {}, "stds": {}}

        for param_key in ("weights", "means", "stds"):
            for feat in feature_names:
                weighted_sum = sum(
                    cw[param_key][feat] * n
                    for cw, n in zip(client_weights, sample_counts)
                )
                aggregated[param_key][feat] = weighted_sum / total_samples

        return aggregated

    # ------------------------------------------------------------------
    # Training rounds
    # ------------------------------------------------------------------

    def run_federation_round(self) -> dict:
        """Execute one federation round.

        1. Collect current weights and sample counts from all clients.
        2. Aggregate via FedAvg.
        3. Push the global weights back to every client.

        Returns a dict with round metrics.
        """
        # 1. Collect
        client_weights: list[dict] = []
        sample_counts: list[int] = []

        for client in self.clients:
            client_weights.append(client.get_model_weights())
            sample_counts.append(client.training_samples)

        # 2. Aggregate
        previous_global = self.global_model.get_weights()
        aggregated = self.aggregate_weights(client_weights, sample_counts)

        # Compute convergence metric: mean absolute weight delta.
        deltas: list[float] = []
        for param_key in ("weights", "means", "stds"):
            for feat in FederatedAnomalyModel.FEATURE_NAMES:
                deltas.append(
                    abs(aggregated[param_key][feat] - previous_global[param_key][feat])
                )
        convergence_delta = float(np.mean(deltas))

        # 3. Push global weights to all clients (and the server model).
        self.global_model.set_weights(aggregated)
        for client in self.clients:
            client.update_model(aggregated)

        round_metrics = {
            "participating_clients": len(self.clients),
            "total_samples": sum(sample_counts),
            "convergence_delta": round(convergence_delta, 6),
            "per_client_samples": {
                c.city_id: c.training_samples for c in self.clients
            },
        }
        self.training_history.append(round_metrics)
        return round_metrics

    def run_full_training(self) -> dict:
        """Run all rounds and return a training summary.

        Returns:
            dict with rounds_completed, final_weights,
            convergence_history, and per_client_stats.
        """
        for _ in range(self.num_rounds):
            self.run_federation_round()

        self.is_trained = True

        return {
            "rounds_completed": self.num_rounds,
            "final_weights": self.global_model.get_weights(),
            "convergence_history": [
                r["convergence_delta"] for r in self.training_history
            ],
            "per_client_stats": {
                c.city_id: {
                    "zone_ids": c.zone_ids,
                    "training_samples": c.training_samples,
                }
                for c in self.clients
            },
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        """Return current federation state."""
        return {
            "is_trained": self.is_trained,
            "num_clients": len(self.clients),
            "num_rounds": self.num_rounds,
            "training_history": self.training_history,
        }


# ======================================================================
# Synthetic data generation
# ======================================================================

def generate_synthetic_training_data(
    zone_id: str,
    num_samples: int = 100,
    anomaly_fraction: float = 0.12,
    seed: int | None = None,
) -> list[dict]:
    """Generate realistic synthetic claim data for demo/training.

    Produces ``num_samples`` dicts each containing the 8 FraudShield
    features.  Approximately ``anomaly_fraction`` of the samples are
    injected as clearly anomalous to make fraud detection meaningful.

    Args:
        zone_id: Used to seed deterministic randomness per zone.
        num_samples: Total number of samples to generate.
        anomaly_fraction: Fraction of anomalous samples (default 12%).
        seed: Optional RNG seed (overrides zone-based seed).

    Returns:
        List of feature dicts ready for ``FederatedAnomalyModel.fit``.
    """
    # Zone-deterministic seed so repeated calls produce the same data.
    if seed is None:
        seed = hash(zone_id) % (2**31)
    rng = np.random.default_rng(seed)

    num_anomalous = int(num_samples * anomaly_fraction)
    num_normal = num_samples - num_anomalous

    samples: list[dict] = []

    # --- Normal samples ---
    for _ in range(num_normal):
        samples.append({
            "claim_hour": int(rng.integers(7, 21)),          # 7am-9pm
            "tenure_weeks": int(rng.integers(4, 80)),        # established riders
            "zone_inactivity_pct": round(float(rng.uniform(25, 65)), 1),
            "claim_velocity_7d": int(rng.integers(0, 3)),    # 0-2 claims
            "zone_claim_rate_deviation": round(float(rng.uniform(0.5, 1.8)), 2),
            "distance_from_centroid_km": round(float(rng.uniform(0.5, 4.0)), 1),
            "s1_value": round(float(rng.uniform(40, 95)), 1),
            "days_since_policy_start": int(rng.integers(7, 120)),
        })

    # --- Anomalous samples ---
    for _ in range(num_anomalous):
        samples.append({
            "claim_hour": int(rng.choice([1, 2, 3, 4, 23, 0])),  # suspicious hours
            "tenure_weeks": int(rng.integers(0, 3)),              # brand-new riders
            "zone_inactivity_pct": round(float(rng.uniform(5, 18)), 1),  # low inactivity
            "claim_velocity_7d": int(rng.integers(4, 8)),         # high velocity
            "zone_claim_rate_deviation": round(float(rng.uniform(2.5, 5.0)), 2),
            "distance_from_centroid_km": round(float(rng.uniform(6, 15)), 1),
            "s1_value": round(float(rng.uniform(5, 25)), 1),     # low env signal
            "days_since_policy_start": int(rng.integers(0, 2)),   # brand-new policy
        })

    # Shuffle so anomalies are interspersed.
    rng.shuffle(samples)

    return samples
## docker-compose.yml
services:
  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_URL: http://localhost:8000
    ports:
      - "5173:80"
    depends_on:
      - backend
    restart: unless-stopped

  backend:
    build:
      context: ./backend
      network: host           # uses host network during build so pip can reach PyPI
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://zoneguard:zoneguard_dev@db:5432/zoneguard
      - REDIS_URL=redis://redis:6379/0
      - CORS_ORIGINS=http://localhost:5173,http://localhost:3000,https://pranaav2409.github.io
      - APP_ENV=development
      - DEBUG=true
      - OPENWEATHERMAP_API_KEY=${OPENWEATHERMAP_API_KEY:-}
      - GEMINI_API_KEY=${GEMINI_API_KEY:-}
    dns:
      - 8.8.8.8
      - 8.8.4.4
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: zoneguard
      POSTGRES_USER: zoneguard
      POSTGRES_PASSWORD: zoneguard_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U zoneguard"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
## frontend/src/pages/RiderDashboard/
