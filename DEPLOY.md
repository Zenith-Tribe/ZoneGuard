# Deployment Guide

## Architecture (Phase 3)

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  →  React 19 + TypeScript + Tailwind + Recharts   │
│              nginx (Docker :5173) — SPA + /api/ proxy       │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP /api/v1/
┌─────────────────▼───────────────────────────────────────────┐
│  FastAPI Backend (:8000) — 14 routers, 70+ endpoints        │
│  ML: ZoneRisk, QuadSignal, FraudShield v1+v2, ZoneTwin     │
│  Federated Learning (simulated), Temporal Clustering        │
│  Integrations: Weather, Mobility, OSRM, Gemini, e-Shram    │
└────────┬──────────────────────────┬─────────────────────────┘
         │                          │
    PostgreSQL 16              Redis 7
    (:5432)                    (:6379)
```

**Services:** 4 containers (frontend, backend, PostgreSQL 16, Redis 7)
**Tests:** 123 backend (pytest) + 24 frontend (vitest)
**Demo creds:** rider/rider123, admin/admin123

---

## Option A: Local Dev (Behind Firewall) — Recommended for Demo

**Problem**: Docker containers can't reach PyPI behind institutional DNS.
**Solution**: Run infra (DB/Redis) in Docker, backend natively.

```bash
# One-time: fix Docker DNS (if you ever need full docker-compose)
./fix-docker-dns.sh

# For daily dev: run infra in Docker, backend natively
./dev-setup.sh
# In another terminal:
cd frontend && npm run dev
```

Access:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs

---

## Option B: Railway (Production Backend) + GitHub Pages (Frontend)

### Step 1: Deploy backend to Railway

1. Create account at [railway.app](https://railway.app)
2. New Project → Deploy from GitHub repo → select `ZoneGuard`
3. Set **Root Directory** to `backend`
4. Railway auto-detects the `Dockerfile`
5. Add environment variables in Railway dashboard:
   ```
   DATABASE_URL=<Railway PostgreSQL URL>  ← add PostgreSQL service first
   REDIS_URL=<Railway Redis URL>          ← add Redis service
   GEMINI_API_KEY=<your key>
   OPENWEATHERMAP_API_KEY=<your key>
   CORS_ORIGINS=https://pranaav2409.github.io,http://localhost:5173
   APP_ENV=production
   DEBUG=false
   AUTH_ENABLED=false
   ```
6. Add PostgreSQL service → copy the connection string → set as `DATABASE_URL`
7. Deploy → get your Railway URL (e.g. `https://zoneguard-backend-prod.up.railway.app`)
8. Run seed: Railway → backend service → Shell → `python db/seed.py`

### Step 2: Wire frontend to Railway backend

In GitHub repo settings → Secrets and variables → Actions:
```
VITE_API_URL = https://zoneguard-backend-prod.up.railway.app
```

Push to `main` → GitHub Actions builds frontend with the API URL → deploys to GitHub Pages.

### Step 3: Verify

```bash
# Check backend health
curl https://zoneguard-backend-prod.up.railway.app/health

# Check zones seeded
curl https://zoneguard-backend-prod.up.railway.app/api/v1/zones

# Trigger simulator
curl -X POST https://zoneguard-backend-prod.up.railway.app/api/v1/simulator/trigger \
  -H "Content-Type: application/json" \
  -d '{"zone_id": "hsr", "scenario": "flash_flood"}'

# Run federated learning training
curl -X POST https://zoneguard-backend-prod.up.railway.app/api/v1/admin/fraudshield/train

# Check temporal clustering for a zone
curl https://zoneguard-backend-prod.up.railway.app/api/v1/admin/fraud/temporal-analysis/hsr
```

---

## Option C: Full Docker Compose (after DNS fix)

```bash
# Fix Docker DNS first (one-time)
./fix-docker-dns.sh

# Then rebuild and run
cd ZoneGuard
docker compose up --build

# Seed in another terminal
docker compose exec backend python db/seed.py
```

---

## Environment Variables

### Backend (backend/.env)

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...localhost.../zoneguard` | Yes | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Yes | Redis connection string |
| `OPENWEATHERMAP_API_KEY` | — | No | Live weather for S1 signal (falls back to sim) |
| `GEMINI_API_KEY` | — | No | Gemini 1.5 Flash for audit reports + chat (falls back to templates) |
| `AUTH_ENABLED` | `false` | No | Enable JWT authentication |
| `JWT_SECRET` | `zoneguard-demo-secret` | No | JWT signing key (change for production) |
| `APP_ENV` | `development` | No | Environment identifier |
| `DEBUG` | `true` | No | SQLAlchemy echo + verbose logging |
| `CORS_ORIGINS` | `http://localhost:5173,...` | No | Comma-separated allowed CORS origins |

### Frontend (build-time)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API URL (baked into Vite build) |

---

## Database Schema

Tables created by `db/seed.py` via `Base.metadata.create_all`:
- `riders` (includes `eshram_id`, `eshram_verified` columns for Phase 3 e-Shram KYC)
- `policies` (includes `is_forward_locked`, `forward_lock_weeks` for Forward Premium Lock)
- `claims`, `payouts`, `zones`, `signals`, `disruption_events`
- `fraud_flags`, `audit_logs`, `premium_payments`, `premium_calculations`
- `simulation_events`, `policy_exclusion_types`, `policy_applied_exclusions`

> Re-running `seed.py` on existing DB is safe — `create_all` adds missing columns/tables without dropping existing data.

---

## Running Tests

```bash
# Backend — 123 tests (ML, pipeline, fraud, clustering, federated, e-Shram, forward lock)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest pytest-asyncio aiosqlite
.venv/bin/pytest tests/ -v

# Frontend — 24 tests (chat responses, API service layer)
cd frontend
npm test
```

---

## Demo Walkthrough

### For Judges

1. Open http://localhost:5173 → Landing page
2. Login as `rider/rider123` or `admin/admin123` (or skip auth)
3. **Rider flow:** Onboarding → select zone → enter earnings → toggle Forward Premium Lock → confirm
4. **Admin flow:** Navigate to `/admin?demo=true` for guided tour
5. Trigger disruption simulation → watch claims auto-process → see payout
6. Admin Dashboard: run FraudShield v2 training, check temporal clustering per zone
7. Reset between runs: `POST /api/v1/demo/reset`

### Key Phase 3 Demo Endpoints

| Endpoint | Method | Feature |
|----------|--------|---------|
| `/api/v1/policies/{id}/forward-lock` | POST | Activate Forward Premium Lock (8% discount) |
| `/api/v1/riders/{id}/verify-eshram` | POST | e-Shram KYC verification |
| `/api/v1/admin/fraudshield/train` | POST | Run federated learning training |
| `/api/v1/admin/fraudshield/status` | GET | Federated model status |
| `/api/v1/admin/fraud/temporal-analysis/{zone_id}` | GET | Collusion ring detection |

---

## Frontend-Only Mode (No Backend)

The frontend gracefully degrades to mock data when the backend is unreachable.
GitHub Pages site works standalone for frontend demo.

---

## Production Checklist

- [ ] Set `AUTH_ENABLED=true` with strong `JWT_SECRET`
- [ ] Set `DEBUG=false`
- [ ] Use proper database credentials
- [ ] Configure `CORS_ORIGINS` for production domain
- [ ] Run Alembic migrations instead of `create_all`
- [ ] Add monitoring (Sentry, OpenTelemetry)
- [ ] Enable HTTPS via reverse proxy
