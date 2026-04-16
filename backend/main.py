from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from config import get_settings
from routers import riders, zones, policies, claims, signals, payouts, admin, simulator, premium, notifications, chat, auth, demo

from features.feature_14.pulse_router import router as pulse_router
from features.feature_12.autopilot_router import router as f12_router
from features.feature_04.zk_router import router as zk_router

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
app.include_router(pulse_router)
app.include_router(f12_router, prefix="/api/v1", tags=["SmartClaim Autopilot"])
app.include_router(zk_router)


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
