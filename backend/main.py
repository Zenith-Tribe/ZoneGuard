# MERGED BY SESSION 7 — Patches from sessions: 1, 2, 3, 4, 5
# Session 6 did not complete — Session 6 patches NOT applied.
# Merge date: 2026-04-17
# [INTEGRATION WARNING] Session 6 (WhatsApp / Autopilot / Pulse) patches missing.
#   - Autopilot MEDIUM-confidence claim path not present in claims.py
#   - Pulse nowcasting tab NOT added to RiderDashboard (Session 5 tab applied only)
#   - generate_synthetic_scenarios() is available in zone_twin.py (Session 4) but
#     Session 6's consumer (Pulse nowcasting) has not been wired in yet.

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from config import get_settings
from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo

# ── Session 1: ZoneChain (Hyperledger Fabric) + TemporalSig (Polygon L2) ──────
from blockchain import router as blockchain_router
from blockchain.fabric_client import init_fabric_client, shutdown_fabric_client
from blockchain.temporalsig import init_temporalsig_client, shutdown_temporalsig_client

# ── Session 2: ChainOracle Health Router ──────────────────────────────────────
from oracle.oracle_health import oracle_health_router

# ── Session 3: ZeroKnow KYC + CrossRider DID Passport ────────────────────────
try:
    from identity import identity_router
    HAS_IDENTITY = True
except ImportError as e:
    import logging as _log3
    _log3.getLogger(__name__).warning(f"Identity module not loaded: {e}")
    identity_router = None
    HAS_IDENTITY = False

# ── Session 5: DAO PremiumGov + ZoneReinsurance ───────────────────────────────
from governance.governance_router import router as governance_router
from defi.amm_router import router as reinsurance_router

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

    # Initialize database — wrapped in try/except so app starts even if DB init fails
    try:
        from db.database import engine, Base
        from sqlalchemy import text
        import models  # noqa: F401
        import governance.db_models  # noqa: F401
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for stmt in [
                "ALTER TABLE riders ADD COLUMN IF NOT EXISTS eshram_id VARCHAR DEFAULT NULL",
                "ALTER TABLE riders ADD COLUMN IF NOT EXISTS eshram_verified BOOLEAN DEFAULT FALSE",
                "ALTER TABLE payouts ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0",
            ]:
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    pass
        logger.info("Database schema initialized")

        # Seed if empty
        from db.database import async_session
        from sqlalchemy import select, func
        async with async_session() as session:
            result = await session.execute(select(func.count()).select_from(models.Zone))
            count = result.scalar() or 0
            if count == 0:
                logger.info("Empty database — running seed in background")
                import subprocess, sys
                subprocess.Popen([sys.executable, "db/seed.py"], env={**__import__("os").environ})
            else:
                logger.info(f"Database seeded ({count} zones)")
    except Exception as e:
        logger.error(f"Database init failed (app continues): {e}")

    start_scheduler()

    # Session 1: Initialize blockchain clients (ZoneChain + TemporalSig)
    await init_fabric_client()
    await init_temporalsig_client()
    logger.info("ZoneChain (Fabric) and TemporalSig (Polygon) clients initialized")

    logger.info("ZoneGuard API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down ZoneGuard API...")
    stop_scheduler()

    # Session 1: Shutdown blockchain clients
    await shutdown_fabric_client()
    await shutdown_temporalsig_client()

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

# CORS — allow Railway and GitHub Pages origins
# Filter out glob patterns; CORSMiddleware needs exact origins or ["*"]
cors_origins = [
    o.strip() for o in settings.cors_origins.split(",")
    if o.strip() and "*" not in o.strip()
]
# If no explicit origins configured or env says allow all, use wildcard
use_wildcard = not cors_origins or settings.allowed_hosts == "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if use_wildcard else cors_origins,
    allow_credentials=not use_wildcard,  # credentials + wildcard origin is invalid per spec
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Session 4: AdaptPremium Admin Endpoints (Innovation 13) ───────────────────
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
# ── End Session 4 AdaptPremium router definition ──────────────────────────────


# Include all routers — original set
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

# ── Session 1: ZoneChain/TemporalSig router ───────────────────────────────────
app.include_router(blockchain_router.router)

# ── Session 2: Oracle health router ──────────────────────────────────────────
app.include_router(oracle_health_router)

# ── Session 3: Identity router (ZK KYC + DID Passport) ───────────────────────
if HAS_IDENTITY and identity_router:
    app.include_router(identity_router)
    logger.info("Identity router registered: /api/v1/identity")
else:
    logger.warning("Identity router not available — run: pip install cryptography")

# ── Session 4: AdaptPremium admin router ──────────────────────────────────────
app.include_router(_adapt_router)

# ── Session 5: Governance + Reinsurance routers ───────────────────────────────
app.include_router(governance_router)   # DAO PremiumGov + SoulboundNFT
app.include_router(reinsurance_router)  # ZoneReinsurance Pool


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
            # ── Session 3: Identity endpoints ──────────────────────────────
            "identity": "/api/v1/identity",
            "did_resolve": "/api/v1/identity/resolve/{did}",
            "zk_verify": "/api/v1/identity/verify-proof",
            "did_passport": "/api/v1/identity/passport/{nullifier_prefix}",
            # ── Session 5: Governance + Reinsurance ────────────────────────
            "governance":    "/api/v1/governance",
            "reinsurance":   "/api/v1/reinsurance",
            # ── Session 1: Blockchain ───────────────────────────────────────
            "blockchain": "/api/v1/blockchain",
            # ── Session 2: Oracle ───────────────────────────────────────────
            "oracle_health": "/api/v1/oracle/health",
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

    # Weather API key (primary oracle node)
    checks["openweathermap"] = {
        "status": "ok" if settings.openweathermap_api_key else "missing",
        "has_key": bool(settings.openweathermap_api_key),
    }

    # ── Session 2: Oracle network key health checks ────────────────────────
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
    # ── End Session 2 oracle checks ───────────────────────────────────────

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
