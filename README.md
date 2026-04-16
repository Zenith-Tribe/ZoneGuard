# ZoneGuard
### AI-Powered Parametric Income Protection for Amazon Flex Last-Mile Riders

**Guidewire DEVTrails 2026 — Phase 3 Complete · Demo-Ready Platform**

> *"A flash flood doesn't wait for a claims adjuster. Neither should a delivery rider's rent."*

![Phase](https://img.shields.io/badge/Phase-3%20Complete-brightgreen)
![Build](https://img.shields.io/badge/Build-Passing-brightgreen)
![Backend](https://img.shields.io/badge/Backend-FastAPI%20Python-blue)
![Frontend](https://img.shields.io/badge/Frontend-React%2019%20TypeScript-61dafb)
![ML](https://img.shields.io/badge/ML-QuadSignal%20Fusion-purple)
![LLM](https://img.shields.io/badge/LLM-Gemini%201.5%20Flash-orange)
![Persona](https://img.shields.io/badge/Persona-Amazon%20Flex%20E--Commerce-green)
![Premium](https://img.shields.io/badge/Weekly%20Premium-₹39–₹225-purple)
![Payout](https://img.shields.io/badge/Payout%20Window-Under%202%20Hours-orange)
![Hackathon](https://img.shields.io/badge/Guidewire-DEVTrails%202026-red)

**Live Demo:** https://zenith-tribe.github.io/ZoneGuard/ · **Repo:** https://github.com/Zenith-Tribe/ZoneGuard

---

## Phase 3 — Demo-Ready Platform

### Quick Start (Full Stack in 3 Commands)

```bash
git clone https://github.com/Zenith-Tribe/ZoneGuard && cd ZoneGuard
cp backend/.env.example backend/.env   # optionally add GEMINI_API_KEY, OPENWEATHERMAP_API_KEY
docker compose up --build              # starts frontend :5173, backend :8000, PostgreSQL, Redis
# In a second terminal (one-time seed):
docker compose exec backend python db/seed.py
```
Open **http://localhost:5173** → ZoneGuard is live.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  →  React 19 + TypeScript + Tailwind + Recharts   │
│              nginx (Docker :5173) — SPA + /api/ proxy       │
└─────────────────┬───────────────────────────────────────────┘
                  │ HTTP /api/v1/
┌─────────────────▼───────────────────────────────────────────┐
│  FastAPI Backend (:8000) — 13 routers, 11 ORM models       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ML Pipeline                                         │   │
│  │  ZoneRisk Scorer → QuadSignal Fusion → FraudShield  │   │
│  │  ZoneTwin Counterfactual · Gemini LLM Audit Reports │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Integrations                                        │   │
│  │  OpenWeatherMap (live) · OSRM mock · UPI mock       │   │
│  │  WhatsApp sim · Gemini 1.5 Flash                    │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────┬─────────────────┬───────────────────────────────┘
             │                 │
      PostgreSQL 16       Redis 7
      (11 tables)     (signal cache)
```

### 8-Step Demo Flow (Judge Walkthrough)

| Step | Action | What You See |
|------|---------|-------------|
| 1 | Open http://localhost:5173 | Landing page — ZoneGuard pitch |
| 2 | "Get Covered" → Onboarding | 3-step: Rider ID → Zone → Earnings |
| 3 | Confirm policy | Rider Dashboard — ₹89/week active coverage (HSR Medium Risk) |
| 4 | Admin Dashboard → Disruption Simulator | Select HSR Layout → "Flash Flood" |
| 5 | Trigger simulation | QuadSignal panel: S1+S2+S3+S4 all fire → HIGH confidence |
| 6 | Claims Queue | Auto-created claim — Exclusion check PASSED — FraudShield 12% risk |
| 7 | Approve payout | UPI ref ZG-2026-XXXXXXXX generated — ₹1,430 disbursed (55% of ₹2,600 daily baseline) |
| 8 | KPIs update | Total payouts ↑, Loss ratio ↑, Active claims ↓ |

### Phase 2 Deliverables Checklist

- [x] **Working registration** — 90-second onboarding, Rider ID + Zone + Earnings
- [x] **Policy management** — create / view / renew / cancel with exclusions list
- [x] **Dynamic weekly premium calculator** — ZoneRisk Scorer (5-factor weighted ML)
- [x] **Claims management** — auto-trigger + manual review queue + Gemini AI audit
- [x] **4 automated disruption triggers** — flash_flood, severe_aqi, transport_strike, heat_wave
- [x] **Payout simulation** — UPI mock (ZG-2026-XXXXXXXX), 55% of 7-day earnings baseline
- [x] **Analytics dashboard** — KPIs, QuadSignal live feed, loss ratio, claims charts
- [x] **10 standard exclusions** — War, Pandemic, Terrorism, Rider Misconduct, Vehicle Defect, Pre-existing Zone, Scheduled Maintenance, Grace Period Lapse, Fraud Detected, Max Days Exceeded
- [x] **Intelligent fraud detection** — FraudShield heuristic scorer (duplicate/velocity/timing checks)
- [x] **LLM audit reports** — Gemini 1.5 Flash with graceful template fallback
- [x] **Docker Compose full stack** — 4 services (frontend nginx, backend, PostgreSQL 16, Redis 7)
- [x] **GitHub Actions CI** — lint + build (frontend) + app load verify (backend)

### Phase 3 Deliverables (Demo-Ready)

- [x] **13 API routers** — admin, claims, signals, riders, zones, payouts, simulator, policies, premium, notifications, chat, auth, demo
- [x] **Admin analytics endpoints** — claims-by-zone, payouts-over-time, loss-ratio-trend, signal-history
- [x] **Payout retry system** — max 3 retries with idempotency check, stats endpoint
- [x] **Claims expansion** — stats aggregation, Gemini audit report fetch/generate, rider challenge mechanism
- [x] **Signals expansion** — at-risk zones, signal history, baselines comparison, NDMA override
- [x] **Riders/Zones expansion** — list/update riders, zone riders/policies/claims subresources
- [x] **Gemini-powered chatbot** — API-first with local keyword fallback
- [x] **Real-time notifications** — triggered by simulator and policy creation events
- [x] **JWT authentication** — optional (`AUTH_ENABLED=false` default), demo creds: `rider/rider123`, `admin/admin123`
- [x] **Error boundary** — graceful crash recovery, no white screen during demo
- [x] **404 page** — proper not-found page with navigation back
- [x] **Demo tour** — `?demo=true` activates 6-step guided overlay on admin dashboard
- [x] **Demo reset** — `POST /api/v1/demo/reset` clears transient data for fresh judge runs
- [x] **Pagination** — all list endpoints support `page` + `per_page` params
- [x] **API rate limiting** — slowapi 100 req/min (optional dependency)
- [x] **Zone baselines** — seeded from ZoneTwin historical data
- [x] **Structured logging** — all integrations log warnings on fallback
- [x] **85 backend tests** — pytest: signal fusion, fraud detection, exclusion engine, zone risk, zone twin, claim pipeline, pagination
- [x] **24 frontend tests** — vitest: chat responses, API service layer

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/riders/register` | Register new rider |
| GET | `/api/v1/riders` | List riders (paginated, zone/KYC filter) |
| POST | `/api/v1/policies` | Create policy |
| GET | `/api/v1/premium/calculate?zone_id=hsr` | Dynamic premium breakdown |
| POST | `/api/v1/simulator/trigger` | Fire disruption scenario |
| GET | `/api/v1/signals/active-events` | Live signal feed |
| GET | `/api/v1/signals/at-risk` | Zones with 2+ breached signals |
| POST | `/api/v1/signals/ndma-override/{zone_id}` | NDMA flood alert override |
| GET | `/api/v1/claims?status=pending_review` | Claims queue (paginated) |
| GET | `/api/v1/claims/stats` | Approval rate, avg payout, fraud score |
| POST | `/api/v1/claims/{id}/review` | Approve / reject claim |
| POST | `/api/v1/claims/{id}/challenge` | Rider contest rejected claim |
| GET | `/api/v1/payouts?rider_id=X` | Payout history (paginated) |
| GET | `/api/v1/payouts/stats` | Payout aggregates + success rate |
| POST | `/api/v1/payouts/{id}/retry` | Retry failed payout (max 3) |
| GET | `/api/v1/admin/kpis` | Dashboard KPIs |
| GET | `/api/v1/admin/claims` | Admin claims queue (paginated, filtered) |
| GET | `/api/v1/admin/analytics/claims-by-zone` | Claims aggregated by zone |
| GET | `/api/v1/admin/analytics/loss-ratio-trend` | 7-day rolling loss ratio |
| POST | `/api/v1/auth/login` | JWT login (demo creds) |
| POST | `/api/v1/chat` | Gemini-powered chatbot |
| POST | `/api/v1/demo/reset` | Reset transient data for demo |
| GET | `/health` | Health check |
| GET | `/health/detailed` | DB + API key status |

Full Swagger docs: http://localhost:8000/docs

### Business Rules (Critical Constraints from DEVTrails PDF)

- **Income loss ONLY** — strictly excludes health, life, accidents, vehicle repair (10 hard exclusions enforced)
- **Weekly pricing** — ₹39–₹225/week based on zone risk tier (Low / Medium / High / Flood-Prone)
- **Payout = 55%** of 7-day rolling earnings baseline (25% retained for moral hazard)
- **4-signal convergence required** — S1 Environmental + S2 Mobility + S3 Economic + S4 Crowd
- **Confidence gating** — HIGH (4 signals) = auto-payout; MEDIUM (3) = recheck; LOW (2) = review
- **Max 3 consecutive disruption days** per week covered

### Deployment

See [DEPLOY.md](DEPLOY.md) for:
- Option A: Local dev (DB/Redis in Docker, backend native — recommended for demo)
- Option B: Railway (backend) + GitHub Pages (frontend) — production setup
- Option C: Full Docker Compose

---

## Table of Contents

0. [Phase 3 — Demo-Ready Platform](#phase-3--demo-ready-platform) ← **Start Here**
1. [The Problem We Are Solving](#1-the-problem-we-are-solving)
2. [ZoneGuard Platform Overview](#2-zoneguard-platform-overview)
3. [Persona: Why Amazon Flex](#3-persona-why-amazon-flex-e-commerce)
4. [Persona Scenario: Ravi's Week](#4-persona-scenario-ravis-week)
5. [WhatsApp-Native Onboarding](#5-whatsapp-native-onboarding)
6. [Weekly Premium Model](#6-weekly-premium-model)
7. [QuadSignal Fusion Engine](#7-quadsignal-fusion-engine-the-core-innovation)
8. [Parametric Triggers](#8-parametric-triggers-defined)
9. [AI/ML Architecture](#9-aiml-architecture)
10. [**Adversarial Defense & Anti-Spoofing Strategy**](#10-adversarial-defense--anti-spoofing-strategy) ← *Market Crash Response*
11. [FraudShield Architecture](#11-fraudshield-architecture)
12. [Basis Risk Mitigation](#12-basis-risk-mitigation-protocol)
13. [Platform & Technology Choices](#13-platform--technology-choices)
14. [Tech Stack](#14-tech-stack)
15. [Regulatory Framework](#15-regulatory-framework--compliance-path)
16. [Business Case](#16-business-case)
17. [Development Roadmap](#17-development-roadmap-6-weeks)
18. [Repository Structure](#18-repository-structure)
19. [Novelty Matrix](#19-novelty-matrix)
20. [Phase 1 Deliverable Expectations — Coverage Map](#20-phase-1-deliverable-expectations--coverage-map)

---

## 1. The Problem We Are Solving

India's gig economy is projected to reach **2.35 crore platform workers by 2030** (NITI Aayog, 2022). The e-commerce last-mile segment alone — Amazon Flex, Flipkart Quick — employs approximately **800,000–1,000,000 riders**. These workers earn ₹600–₹800/day under normal conditions. When a zone-level disruption hits — a flash flood, a severe AQI event, a civil curfew — their income drops to **zero, instantly**. Not gradually. Not partially. Zero.

**Why existing products fail them completely:**

| Dimension | Motor Insurance | PMJJBY/PMSBY | ZoneGuard |
|-----------|----------------|--------------|-----------|
| Income loss coverage | No | No | **Yes — primary purpose** |
| Claims trigger | Incident report + survey | Death/disability only | **Automated parametric signal** |
| Payout timeline | 7–30 days | Weeks | **< 2 hours** |
| Weekly pricing | No | Annual only | **Yes** |
| Gig worker accessible | No (salaried proof required) | Partial | **Native — WhatsApp onboarding** |
| Documentation burden | High | Medium | **Zero** |
| Covers external disruptions | No | No | **Yes — the only product that does** |

Budget 2025's AB-PMJAY covers **health**. It covers nothing for lost wages from a flood. **ZoneGuard fills that gap — and nothing else does.**

**The scale of the gap:** External disruptions cause income drops of **20–30% per month** for gig workers, with zero safety net in place. For riders carrying EMIs, even a two-day disruption cascades into a debt trap.

---

## 2. ZoneGuard Platform Overview

ZoneGuard is a **B2B2C AI-powered parametric income protection platform** built exclusively for Amazon Flex last-mile delivery partners in India.

**What ZoneGuard is NOT:**
- Not an insurance company (ZoneGuard is the technology layer; an IRDAI-licensed insurer underwrites the risk)
- Not health, life, accident, or vehicle repair coverage — those are strictly excluded per platform design and IRDAI parametric scope
- Not a claims-filing app — riders never file a claim

**What ZoneGuard IS:**
- A **zero-touch income certainty engine**: when a verified zone disruption occurs, the payout reaches the rider's UPI account within 2 hours, with no action required from the rider
- A **real-time multi-signal fusion platform**: four independent data layers must converge before a payout fires — making single-signal gaming structurally impossible
- A **weekly-priced, WhatsApp-native** financial product — designed for how gig workers actually live and manage money

**The B2B2C Model:**

```
Amazon Flex Platform (distribution partner)
              ↓
         ZoneGuard
    (AI risk engine + trigger monitoring +
     payout orchestration + fraud detection)
              ↓
  IRDAI-Licensed Insurer Partner
  (Bajaj Allianz / ICICI Lombard — identified)
              ↓
        Rider's UPI Account
```

ZoneGuard provides the intelligence layer. The insurer provides the regulated underwriting wrapper. Amazon Flex provides near-zero CAC distribution. Every party does what they're best at.

---

## 3. Persona: Why Amazon Flex (E-Commerce)

We chose **E-Commerce (Amazon Flex)** over Food (Zomato/Swiggy) or Grocery/Q-Commerce (Zepto/Blinkit) for three precise, actuarially motivated reasons:

**1. Higher per-disruption income loss magnitude**
A Swiggy rider completes 8–12 short trips per day. An Amazon Flex rider completes 3–6 longer-distance deliveries with a higher per-order earning. One disrupted day hits a Flex rider proportionally harder — making income protection more valuable and justifying a premium.

**2. Zone-assignment creates a verifiable, structured income proxy**
Flex riders are assigned delivery zones by the platform *before their shift begins*. Their income is structurally tied to zone accessibility — not random order flow. If the zone is inaccessible, income is zero. This linkage is **provable, localized, and structurally fraud-resistant** in a way food delivery cannot be.

**3. Controllable fraud surface via route predictability**
Because Flex riders follow assigned routes in specific zones, GPS anomaly detection is far more tractable than for food riders who move freely. Our fraud model exploits this directly — a Flex rider whose GPS shows movement while claiming inactivity is trivially detectable against the zone's expected route grid.

---

## 4. Persona Scenario: Ravi's Week

**Ravi Kumar, 34. Bengaluru, HSR Layout zone. Amazon Flex rider, 3 years' tenure. Average weekly earnings: ₹13,000. Monthly EMI on two-wheeler loan: ₹3,800.**

### Without ZoneGuard

| Day | Event | Ravi's Earnings |
|-----|-------|----------------|
| Monday | Normal operations | ₹2,600 |
| Tuesday | Normal operations | ₹2,800 |
| Wednesday | Flash flood — HSR Layout zone shutdown | ₹0 |
| Thursday | Waterlogging continues — zone inaccessible | ₹0 |
| Friday | Zone clears, back to work | ₹2,400 |
| **Weekly Total** | | **₹7,800 (expected: ₹13,000)** |

> Ravi lost ₹5,200 this week. His EMI is ₹3,800. **He defaults.** This becomes a debt trap.

### With ZoneGuard (₹89/week, HSR Layout Medium Risk tier)

| Day | Event | Ravi's Earnings | ZoneGuard Payout |
|-----|-------|----------------|-----------------|
| Monday | Normal | ₹2,600 | — |
| Tuesday | Normal | ₹2,800 | — |
| Wednesday | Flash flood — **all 4 signals fire** | ₹0 | **₹1,430** (55% of daily baseline) |
| Thursday | Flood sustained — signals active | ₹0 | **₹1,430** |
| Friday | Zone clears | ₹2,400 | — |
| **Weekly Total** | | **₹7,800 + ₹2,860 payout** | **₹10,660** |

> Ravi lost ₹2,340 instead of ₹5,200. **He pays his EMI. He stays on the road.**
> Net cost of ZoneGuard this week: ₹89. Net benefit: ₹2,860 

**The payout was automatic. Ravi received a WhatsApp notification. He filed nothing.**

---

## 5. WhatsApp-Native Onboarding

India has 530M+ WhatsApp users. Amazon Flex riders are already on WhatsApp — most have informal zone group chats. ZoneGuard meets them where they already are.

**Why WhatsApp, not an app:** SEWA's parametric insurance program and GoDigit's 2025 migrant worker heat insurance both demonstrated WhatsApp as the optimal delivery channel for informal worker financial products. Riders who receive payouts and manage coverage via WhatsApp convert at dramatically higher rates than those required to install a new app.

### The 90-Second Onboarding Flow

```
Step 1 ── Rider receives WhatsApp invite link from a zone buddy
          or Amazon Flex partner communication.

Step 2 ── Rider sends "JOIN" to ZoneGuard's WhatsApp Business number.

Step 3 ── Conversational bot (3 messages, no forms):
          Bot: "What's your Amazon Flex Rider ID?"
          Bot: "Which zone do you primarily operate in?" [zone menu]
          Bot: "What's your average weekly earning?
                (We'll calculate your exact premium)"

Step 4 ── Bot presents weekly premium quote:
          "Your zone: HSR Layout (Medium Risk)
           Your weekly premium: ₹89
           Your max weekly payout: ₹4,290
           Coverage starts: Immediately on confirmation."
          Rider replies: YES

Step 5 ── First week's premium deducted from next Flex payout
          (simulated in Phase 1).
          Policy active immediately. Welcome message sent.
```

**Total time: < 90 seconds. Zero app download. Zero form filling. Zero document upload.**

### Signal 4: Ongoing Crowd-Truth Engine

Post-onboarding, the WhatsApp channel becomes ZoneGuard's crowd-sourced verification layer:

When Signals 1–3 approach their trigger thresholds, ZoneGuard broadcasts to all riders in the affected zone:

> *"Zone disruption detected in HSR Layout. Are you unable to work right now? Reply YES / NO."*

- **≥ 40% YES responses from ≥ 15 active zone riders within a 2-hour window** = Signal 4 fires
- This simultaneously corroborates the disruption AND captures ground-truth data that API layers can miss (local road blockades, zone closures not yet in weather data)
- All responses feed back into the ZoneTwin model for continuous improvement

---

## 6. Weekly Premium Model

Gig workers don't plan monthly. ZoneGuard is priced, billed, and settled **weekly** — aligned exactly with the Amazon Flex payout cycle.

### ZoneRisk Scorer: Dynamic Weekly Pricing Engine

Every **Monday morning**, ZoneGuard's XGBoost model recalculates each zone's premium for the upcoming week based on five weighted factors:

| Factor | Weight | Description |
|--------|--------|-------------|
| Historical disruption frequency | 35% | Last 24 months of weather + traffic events in the zone (IMD open data) |
| IMD seasonal forecast | 25% | Upcoming week's predicted monsoon intensity / heat risk |
| Rider tenure band | 15% | New riders (< 4 weeks) carry a 15% discovery premium |
| Zone-type classification | 15% | Warehouse-adjacent vs. residential last-mile vs. flood-prone |
| Prior week's claim history | 10% | Zone-level loss ratio adjustment |

**This is not a lookup table.** If IMD predicts a heavy monsoon week in a specific district, premiums in that zone's pin codes adjust *before the week begins*. This is live actuarial pricing that responds to real-world forecast data.

### Premium Tiers (Actuarially Derived)

| Zone Risk Class | Example Zones | Disruption Days/Year | Weekly Premium | Max Annual Payout | Annual Revenue |Annual Profit (per Rider)
|----------------|---------------|----------------------|----------------|------------------|--------------|--------------|
| Low Risk | Whitefield (BLR), Wakad (Pune) | ~1 | **₹39** | ₹1,430 | ₹2,028|+₹598
| Medium Risk | HSR Layout, Andheri West | ~3 | **₹89** | ₹4,290 | ₹4,628|+₹338
| High Risk | Dharavi, Kukatpally | ~5 | **₹139** | ₹7,150 | ₹7,228|+₹78
| Flood-Prone | Riverbank zones, low-lying areas | ~8 | **₹225** | ₹11,440 | ₹11,700|+₹260



### Coverage Rules

| Rule | Value | Rationale |
|------|-------|-----------|
| Payout rate | **55% of 7-day average daily earnings** | 45% retained — moral hazard prevention |
| Max disruption days covered/week | **3 consecutive days** | Beyond = declared disaster; separate mechanisms apply |
| Minimum disruption duration | **4 continuous hours (6am–10pm)** | Filters brief non-income-impacting disruptions |
| Waiting period — environmental | **None** | No time to game; signals are objective |
| Waiting period — social (curfews, strikes) | **24 hours** | Prevents pre-arranged disruption gaming |
| Earnings baseline cap | **7-day rolling average** | Rider cannot earn more from payout than from working |

### Forward Premium Lock

Riders can commit to **4 consecutive weekly premiums upfront** and receive an **8% discount per week**. This improves ZoneGuard's premium pool predictability before high-risk seasons and rewards long-term engagement — reducing adverse selection.

---

## 7. QuadSignal Fusion Engine: The Core Innovation

> Every team in this hackathon will use a weather API. ZoneGuard doesn't just use a weather API.

Most parametric insurance approaches trigger on a single measurable variable. The fatal flaw: **a single-signal system is gameable, noisy, and prone to basis risk.** ZoneGuard triggers income protection only when **four independent signals converge simultaneously** on the same delivery zone within a rolling 2-hour window.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    QUADSIGNAL FUSION ENGINE                         │
│                   (15-minute polling cycle)                         │
├─────────────────┬───────────────────────────────────────────────────┤
│  SIGNAL 1       │  Environmental Layer                              │
│  (always live)  │  Source: OpenWeatherMap (pin-code granular)       │
│                 │  Trigger: Rainfall > 65mm/hr for ≥ 4 hrs          │
│                 │         OR AQI > 300 for ≥ 4 continuous hrs       │
│                 │         OR Temperature > 43°C + IMD heat advisory │
│                 │         OR NDMA flood alert for district           │
├─────────────────┼───────────────────────────────────────────────────┤
│  SIGNAL 2       │  Mobility Layer                                   │
│  (always live)  │  Source: OSRM (self-hosted, zero API cost)        │
│                 │  Trigger: Zone mobility index drops > 75% from    │
│                 │           7-day rolling baseline                  │
│                 │           (actual road traversability, not traffic)│
├─────────────────┼───────────────────────────────────────────────────┤
│  SIGNAL 3       │  Economic Layer                                   │
│  (Phase 1:      │  Source: Amazon Flex Order Volume Proxy           │
│   simulated)    │  Trigger: Zone order volume drops > 70% from      │
│                 │           hourly rolling baseline                  │
│                 │  Phase 2: Real platform API or crowd-sourced data  │
├─────────────────┼───────────────────────────────────────────────────┤
│  SIGNAL 4       │  Crowd-Sourced Truth Layer   ← Novel              │
│  (always live)  │  Source: WhatsApp Rider Check-In System           │
│                 │  Trigger: ≥ 40% of zone riders (min 15) confirm   │
│                 │           inactivity within same 2-hour window    │
└─────────────────┴───────────────────────────────────────────────────┘
```

### Confidence Score → Payout Decision

```
All 4 signals fire   → HIGH confidence   → Automatic payout within 2 hours
3 of 4 signals fire  → MEDIUM confidence → 1-hour recheck cycle, then auto-payout
2 of 4 signals fire  → LOW confidence    → Logged, flagged for human review
1 signal fires       → NOISE             → No action (data retained for model training)
```

### The Convergence Requirement Is Our Fraud Wall

A fraudster cannot simultaneously fake a meteorological flood event, a road traversability collapse, a 70% order volume drop, **AND** get 40+ independent riders to corroborate it — all in the same pin code, at the same time. The coordination cost for a fraud ring exceeds the payout value many times over. **This is structural fraud resistance, not just algorithmic detection.**

---

## 8. Parametric Triggers (Defined)

| Trigger ID | Type | Signals Required | Condition | Confidence Level |
|-----------|------|-----------------|-----------|-----------------|
| **ENV-01** | Environmental | S1 + S2 + (S3 or S4) | Rainfall > 65mm/hr for ≥ 4 hrs + mobility drop > 75% | HIGH |
| **ENV-02** | Environmental | S1 + S2 | AQI > 300 (Severe) for ≥ 4 hrs + traffic collapse confirmed | HIGH |
| **ENV-03** | Environmental | S1 + S4 | Temperature > 43°C + IMD heat advisory + rider check-ins | MEDIUM → HIGH |
| **ENV-04** | Environmental | S1 (auto) | NDMA flood alert issued for specific district | HIGH (auto) |
| **SOC-01** | Social | S2 + S3 + S4 | Curfew declared (govt API/news NLP) + mobility < 20% of baseline + rider check-ins | HIGH |
| **SOC-02** | Social | S2 + S3 + S4 | Verified transport strike + zone volume < 25% baseline for ≥ 4 hrs | HIGH |

**ENV-04 Special Rule:** NDMA-declared flood alerts constitute a government-verified, independently sourced trigger. When NDMA issues a district-level flood alert, ZoneGuard treats this as a pre-validated Signal 1 substitute — no further environmental sensor corroboration required. This approach is consistent with SEWA's parametric program and GoDigit's 2025 migrant worker scheme handling of declared disaster events.

---

## 9. AI/ML Architecture

### Module 1: ZoneRisk Scorer

**Purpose:** Dynamic weekly premium calculation per zone
**Model:** XGBoost (Gradient Boosted Decision Tree)
**Recalculation:** Every Monday, before the week's policies activate
**Output:** Zone risk score 0–100 → maps to premium tier

**Training features include:**
- Zone-level rainfall frequency (last 24 months, IMD open data)
- AQI exceedance events by pin code (CPCB open data)
- Traffic mobility collapse events (OSRM historical)
- Strike/curfew event logs (news API NLP tagging + manual labels)
- Seasonal decomposition (monsoon, winter fog, summer heat waves)
- Urbanisation density score (OpenStreetMap)
- Proximity to flood-risk infrastructure (NDMA flood zone maps)

### Module 2: QuadSignal Fusion Engine

**Purpose:** Real-time payout trigger decision
**Architecture:** Rule-based ensemble with real-time anomaly detection overlay

**Four processing layers:**

```
Layer 1 — Signal Ingestion (every 15 minutes)
  OpenWeatherMap → zone weather state
  OSRM routing   → mobility index per pin code
  Order volume   → proxy signal (simulated Phase 1)
  WhatsApp agg.  → crowd-truth signal

Layer 2 — Baseline Modeling
  Rolling 7-day hourly baseline per zone (order volume + mobility)
  Seasonal adjustment for known low-volume windows (holidays, Sunday PM)
  Exponential moving average for drift detection

Layer 3 — Convergence Detection
  All signals evaluated within rolling 2-hour window
  Confidence score: HIGH / MEDIUM / LOW / NOISE
  HIGH  → automatic payout initiation
  MEDIUM → 1-hour recheck before trigger
  LOW   → logged, flagged for manual review
  NOISE → data retained for model training

Layer 4 — LLM-Powered Claim Audit (MEDIUM confidence only)
  Claude API (claude-sonnet) synthesizes all signal data into
  a plain-language audit report for the human reviewer.
  Report includes: signal deltas vs baseline, historical comparisons,
  WhatsApp check-in verbatim distribution, recommended decision
  with confidence reasoning.
  Review time reduced from ~20 minutes to ~2 minutes per case.
```

**Output per event:** Binary trigger (YES/NO) + confidence score + calculated payout amount + audit trail hash

### Module 3: ZoneTwin — Digital Zone Simulation

**Concept:** Each delivery zone has a corresponding **ZoneTwin** — a lightweight ML model trained on 24 months of zone-specific historical data.

**Three capabilities:**

1. **Pre-season risk recalibration:** Before each monsoon season, ZoneTwin runs forward simulations using IMD seasonal forecasts to predict expected disruption days and recalibrate premium tiers proactively

2. **Counterfactual fraud checks:** Asks the question — *"If this exact level of rainfall had occurred on a normal working day in this zone historically, how many riders would have gone dark?"* — if the claim pattern deviates significantly from the counterfactual, it is flagged

3. **New zone bootstrapping:** When expanding to a new city/pin code with sparse data, ZoneTwin bootstraps initial risk estimates using transfer learning from similar zones — enabling faster geographic expansion

**Implementation:** Python (scikit-learn + statsmodels), < 200ms inference, no GPU required. Zone model files are 2–5 MB — stored as versioned PostgreSQL JSONB blobs.

### Module 4: FraudShield

See full architecture in [Section 11](#11-fraudshield-architecture).

---

## 10. Adversarial Defense & Anti-Spoofing Strategy

> **Market Crash Response — Mandatory Phase 1 Addition**
>
> *Context: A sophisticated syndicate of 500 delivery workers in a tier-1 city successfully exploited a competing beta parametric platform. Using Telegram coordination and GPS-spoofing applications, they faked their locations inside red-alert weather zones while resting safely at home — triggering mass false payouts that drained the platform's liquidity pool.*
>
> *Simple GPS verification is officially obsolete. Here is how ZoneGuard's architecture defeats this attack.*

---

### 10.1 The Differentiation: Genuine Worker vs. GPS Spoofer

**The fundamental insight:** A GPS spoofer can fake *location*. They cannot simultaneously fake **all of the following**:

| Signal Layer | What a Real Stranded Rider Shows | What a GPS Spoofer Shows |
|---|---|---|
| **GPS coordinates** | In the disrupted zone | Faked as in the disrupted zone |
| **GPS signal quality** | Degraded — heavy rain causes multipath interference, signal drops | Artificially clean — spoofed GPS is typically too perfect |
| **Device accelerometer** | Stationary or minimal movement for hours | Potentially stationary, but no correlation to zone conditions |
| **Cell tower triangulation** | Tower IDs match the claimed zone's cell grid; signal strength reflects weather degradation | Tower IDs from actual home location — **mismatch with GPS coordinates** |
| **Amazon Flex app activity** | App open, waiting for zone to clear — last order scan timestamp matches zone activity | App state shows no pre-shift zone assignment in the disrupted zone **OR** app shows normal background activity from a different location |
| **Battery drain pattern** | Elevated drain from GPS + data in poor signal area | Normal drain pattern from a stable home Wi-Fi environment |
| **Zone mobility collapse** | 40+ other riders in same zone also went dark (Poisson-distributed, simultaneous, independent) | Spoofed rider is one of a small suspicious cluster **OR** in an isolated fake claim |

**ZoneGuard's AI differentiation pipeline for individual claims:**

```
Step 1 — Cross-layer consistency check
  GPS coordinates ↔ Cell tower triangulation ↔ Flex app zone assignment
  If any two layers disagree → flag for FraudShield review

Step 2 — Signal quality anomaly detection
  GPS fix quality score analyzed (spoofed signals show abnormally
  low positional variance — real outdoor GPS in heavy rain fluctuates)
  Satellite count + HDOP value range checked against weather conditions

Step 3 — Zone-level population check
  Query: How many zone riders went dark in this 2-hour window?
  If < 15 riders dark during a claimed HIGH-impact event → suspect
  If 40+ riders dark, Poisson-distributed pattern → genuine

Step 4 — Behavioral baseline deviation
  Compare rider's claim-time app activity against their own 90-day
  behavioral fingerprint (order acceptance rate, movement patterns,
  session activity). Deviations from personal baseline increase suspicion score.
```

**The key asymmetry:** A GPS spoofer can control their own location signal. They cannot control the 39+ other honest riders in the zone — whose independent, non-coordinated behavior is the ground truth that validates the event.

---

### 10.2 The Data: Detecting a Coordinated Fraud Ring

The 500-person Telegram-coordinated syndicate is a fundamentally different attack from individual GPS spoofing. Here is how ZoneGuard's data architecture detects it.

**Data points analyzed beyond GPS coordinates:**

**Temporal Pattern Analysis (the core detection layer):**

Genuine disruptions produce a **Poisson-distributed** claim pattern — riders go dark organically, at slightly different times, based on when they individually encounter impassable roads or zone entry blocks. A coordinated 500-person Telegram group, receiving a "go now" message simultaneously, produces a **sharp temporal spike** — dozens of claims initiating within a narrow 5–15 minute window.

```
Genuine disruption claim pattern:
  08:02 — Rider A goes dark
  08:11 — Rider B goes dark
  08:19 — Rider C goes dark  ← Poisson distributed, random arrival times
  08:34 — Rider D goes dark
  08:41 — Rider E goes dark

Coordinated fraud syndicate pattern (Telegram "go now" at 08:15):
  08:16 — Rider A goes dark
  08:16 — Rider B goes dark  ← Suspicious spike: 40+ claims within
  08:17 — Rider C goes dark     a 90-second window
  08:17 — Rider D goes dark
  08:17 — Rider E goes dark
```

ZoneGuard's FraudShield computes the **clustering coefficient of claim timestamp graphs** per zone. A genuine disruption's graph is sparse and randomly distributed. A coordinated attack's graph is a dense, highly clustered sub-graph — detectable via graph anomaly algorithms even before any GPS data is examined.

**Additional data points for ring detection:**

| Data Point | What It Reveals | How ZoneGuard Captures It |
|---|---|---|
| **Claim timestamp clustering** | Coordination signal — organic vs. synchronized | Clustering coefficient on 5-minute-bucket timestamp graph |
| **Device registration network graph** | Accounts registered from the same device fingerprint set, same time window, same IP range | Device fingerprint + IP hash at onboarding |
| **WhatsApp response pattern** | Coordinated groups send YES in a synchronized burst vs. organic trickle | Response timestamp distribution analysis on S4 check-in data |
| **Mutual zone registration** | 40+ riders all newly registered in the same zone in the days before a claimed disruption | Zone registration recency check — new registrations before claim events are flagged |
| **Social graph connectivity** | Fraud rings have high internal connectivity (everyone knows everyone); genuine worker cohorts have normal social graphs | Amazon Flex Rider ID network graph from zone assignment data |
| **Cell tower geography distribution** | If 40+ "zone riders" are all pinging the same 2 cell towers instead of the expected 8–12 towers across a zone | Tower ID diversity score per zone claim batch |
| **ZoneTwin counterfactual** | Did the scale of rider inactivity match what history predicts for this weather event? | ZoneTwin "expected dark rider count" vs. actual claim count |

**The ZoneTwin counterfactual is particularly powerful against large coordinated attacks:**

If ZoneTwin predicts that a 65mm/hr rainfall event in HSR Layout historically results in 18–25 riders going dark across the zone — and 500 claims come in — the statistical deviation is so extreme (20x the expected value) that it triggers an **automatic liquidity protection mode**: all payouts are held for coordinated review, the Telegram/social signal is back-traced, and the insurer partner is notified.

---

### 10.3 The UX Balance: Protecting Honest Workers from False Positives

**The problem with aggressive fraud detection:** In bad weather, a genuine rider may have a network drop (can't send the WhatsApp YES response), their GPS may behave erratically (rain causes real signal degradation), and their cell tower triangulation may show unexpected results (network handoffs are common during storms). Penalizing these riders destroys trust and defeats the product's core purpose.

**ZoneGuard's tiered "flagged claim" workflow:**

```
TIER 1 — PRESUMED GENUINE (default for all flagged claims)
  When: Claim flagged but zone-level signals are HIGH confidence
  Action: Payout PROCEEDS immediately, flag noted in audit log
  Rationale: If the zone-wide event is verified by 3+ independent signals,
             individual inconsistencies are presumed to be technical artifacts
             of the disruption itself (network drops, GPS degradation in rain)

TIER 2 — SOFT HOLD (individual anomalies without zone confirmation)
  When: GPS/cell mismatch detected + zone-level signals are MEDIUM confidence
  Action: Payout held for 2 hours; rider receives WhatsApp message:
          "We're verifying your coverage for [zone] — you'll hear back by [time].
           If you have a network issue, you can reply CONFIRM to let us know
           you're in [zone]."
  Rationale: Gives honest riders a frictionless resolution path.
             A scammer will not reply CONFIRM — they're at home.
             An honest worker in bad weather will reply immediately.

TIER 3 — COORDINATED INVESTIGATION (ring detection active)
  When: Clustering coefficient anomaly + 3+ of the ring-detection signals fire
  Action: All claims in the suspected batch held; individual riders
          NOT notified of investigation. Senior FraudShield review triggered.
          Innocent riders in the batch automatically cleared and paid
          within 4 hours of investigation completion.
  Rationale: Ring investigation must not tip off the syndicate.
             Innocent workers are not penalized — they are delayed briefly
             and paid in full once the batch is cleared.
```

**The Honest Worker Protection Guarantee:**

A legitimate rider who experiences a genuine disruption but has a network drop will:
1. Be protected by the zone-level signal (if 3+ zone signals fired, their payout proceeds regardless)
2. Have a 2-hour frictionless appeal window via a single WhatsApp reply
3. Never be permanently denied based on a single anomalous data point — the system requires multiple fraud signals to converge before a claim is rejected

**The philosophy:** We bias toward paying genuine workers, not toward catching fraudsters. The structural architecture (QuadSignal convergence, ZoneTwin counterfactuals, cluster detection) means fraudsters are caught at the population level — not at the individual level where the risk of false positives is highest.

---

## 11. FraudShield Architecture

### Identified Fraud Vectors

| Fraud Vector | Detection Method | Confidence |
|---|---|---|
| **GPS spoofing** (claiming to be in disrupted zone while working elsewhere) | Cross-layer consistency check: GPS vs. cell tower triangulation vs. Flex app zone assignment. If 40+ zone riders went dark simultaneously: event is real. If 1–2 riders report inactivity while all other signals show no zone collapse: flagged. | High |
| **Collusion rings** (coordinated fake claims via Telegram/WhatsApp groups) | Temporal clustering analysis on claim timestamps. Genuine disruptions = Poisson-distributed arrival pattern. Coordinated attacks = tight temporal spike. Clustering coefficient on 5-minute-bucket timestamp graph. | High |
| **Duplicate registration** (same rider, multiple accounts) | Amazon Flex Rider ID + device fingerprinting + phone OTP binding. One account per device-phone pair, enforced at onboarding. e-Shram ID cross-reference in Phase 2. | Very High |
| **Weather API gaming** (deliberately not working at threshold conditions) | QuadSignal convergence required. Gaming S1 threshold alone does not trigger payout — mobility, economic, and crowd signals must also collapse simultaneously. | Very High |
| **Fabricated disruptions in low-data zones** | Confidence score weighting — low-data zones require higher signal strength. ZoneTwin counterfactual comparison flags statistically anomalous claim scales vs. historical disruption patterns. | Medium |

### FraudShield v1 (Phase 2): Centralized Baseline

Isolation Forest (scikit-learn) trained on claim patterns, GPS cross-reference vectors, and temporal clustering signals. Centralized — operates on ZoneGuard's servers.

### FraudShield v2 (Phase 3): Federated Privacy-Preserving Architecture

Inspired by 2025 research in privacy-preserving fraud detection, FraudShield v2 uses **federated learning** to detect fraud patterns across all cities without centralizing raw rider data:

```
Each city's rider cohort trains a local anomaly detection model
on their own device-side / city-server data.
                      ↓
Model gradients (NOT raw GPS or activity data) are shared
with ZoneGuard's central aggregation server.
                      ↓
Central server aggregates gradients using FedAvg
into an improved global FraudShield model.
                      ↓
Updated global model pushed back to city servers.
Raw rider GPS and activity data NEVER leaves the city.
```

**Why this matters:** Satisfies India's **DPDP Act 2023** data minimization principle. Rider privacy is preserved while the model continuously improves as more riders enroll across more cities.

**Implementation:** Flower framework (open-source FL) + scikit-learn Isolation Forest as the base model.

---

## 12. Basis Risk Mitigation Protocol

**Basis risk** — the gap between the parametric trigger firing and the rider's actual income loss — is the primary academic critique of parametric insurance. ZoneGuard addresses it directly and explicitly.

| Basis Risk Source | ZoneGuard's Mitigation |
|---|---|
| Weather API reports rain in pin code, but rider was in adjacent dry area | Signal 4 crowd check-in required. If rider's GPS showed movement in dry area, FraudShield cross-reference flags and excludes their claim |
| Trigger fires but rider chose not to work for personal reasons | Payout capped at 55% of baseline — rider cannot profit from disruption. 45% moral hazard retention is structural |
| API measurement point not granular enough for specific micro-zone | Pin-code level data used, never city-level. OSRM mobility index computed per-zone |
| Rider earns more on disrupted days via surge pricing | Covered income capped at 7-day average earnings baseline — not theoretical maximum earnings |
| Seasonal income variation makes baseline inaccurate | ZoneTwin applies seasonal decomposition. Monsoon weeks use monsoon-adjusted baselines, not flat annual averages |

---

## 13. Platform & Technology Choices

### Platform Justification: Web-First with PWA Path

**Insurer/Admin interface (Web — desktop primary):** Zone risk dashboards, claim review queues, loss ratio monitoring, and premium model management are workflow-heavy tasks. Desktop is the correct primary interface for this persona.

**Rider interface (Progressive Web App — Phase 2):** Riders already use Amazon Flex on their phones. A PWA delivers: offline capability, installable home-screen icon, no app store friction, no Play Store review delays. Phase 1 delivers a responsive web interface; Phase 2 PWA-ifies it with Workbox.

**WhatsApp-first for onboarding and payouts:** Based on demonstrated success in SEWA's parametric program and GoDigit's 2025 migrant worker initiative — WhatsApp is the highest-conversion onboarding channel for informal workers. Not an app. Not a URL. A conversation.

---

## 14. Tech Stack

### Frontend

| Component | Technology | Reason |
|-----------|-----------|--------|
| UI Framework | React.js (TypeScript) | Component-driven, strong typing for financial data |
| Styling | Tailwind CSS | Rapid development, no design debt |
| Data Visualization | Recharts | Zone risk dashboards, earnings protection timelines |
| PWA Layer | Workbox (Phase 2) | Offline capability, installable |

### Backend

| Component | Technology | Reason |
|-----------|-----------|--------|
| API Server | Python FastAPI | Unified REST + ML inference, async support for 15-min signal polling |
| Database | PostgreSQL | Rider profiles, zone data, claim records, policy ledger |
| Cache | Redis | Real-time signal state, 15-min refresh cycle, WhatsApp session state |
| Message Queue | Celery + Redis | Async signal processing, payout job queue |

### AI/ML

| Module | Technology | Reason |
|--------|-----------|--------|
| ZoneRisk Scorer | XGBoost + scikit-learn | Gradient boosting for structured zone risk data |
| ZoneTwin | statsmodels + scikit-learn | Time-series decomposition + lightweight simulation |
| FraudShield v1 | Isolation Forest (scikit-learn) | Unsupervised anomaly detection on claim patterns |
| FraudShield v2 | Flower FL + Isolation Forest | Federated privacy-preserving fraud model (Phase 3) |
| LLM Claim Audit | Claude API (claude-sonnet) | Natural language synthesis for medium-confidence reviews |
| Data Processing | Pandas + NumPy | Baseline modeling, rolling averages, signal processing |

### External APIs & Data Sources

| Source | Data | Signal Usage |
|--------|------|--------------|
| OpenWeatherMap (free tier) | Rainfall, AQI, temperature | Signal 1 — Environmental |
| OSRM (self-hosted, open source) | Road traversability, route time | Signal 2 — Mobility, zero API cost |
| IMD Open Data | Historical rainfall + seasonal forecasts | ZoneRisk Scorer training + seasonal adjustment |
| CPCB API | AQI by city/zone | ENV-02 trigger |
| NDMA Flood Alert API | District-level flood declarations | ENV-04 auto-trigger |
| Twilio WhatsApp Business API | Onboarding + crowd check-ins | Signal 4 + rider communication |
| Razorpay Test Mode | Simulated UPI payout disbursement | Phase 1 mock payments |
| e-Shram Portal API | Worker KYC and identity | Phase 2 deduplication, KYC |

### Infrastructure

| Component | Technology |
|-----------|-----------|
| Containerization | Docker + docker-compose |
| CI/CD | GitHub Actions |
| Hosting (Phase 1) | Render / Railway (free tier) |
| Zone model storage | PostgreSQL JSONB (versioned model blobs) |

---

## 15. Regulatory Framework & Compliance Path

### IRDAI "Use & File" Regulatory Sandbox (2024 onwards)

IRDAI's updated framework allows insurers to **launch parametric products and file the details afterward** — dramatically reducing time-to-market. A licensed insurer partner can launch ZoneGuard's product without waiting months for prior approval. ZoneGuard (the technology platform) is not itself the licensed insurer.

### e-Shram Portal Integration (Phase 2)

Budget 2025 mandated gig platform aggregators to register their workers on e-Shram. ZoneGuard's Phase 2 integration provides:
- **KYC verification** — no separate document upload for registered workers
- **Identity deduplication** — prevents duplicate registration fraud
- **Income proxy validation** — e-Shram work history cross-referenced with declared baseline earnings

### DPDP Act 2023 Compliance

ZoneGuard's federated FraudShield architecture was designed from the ground up to satisfy India's Data Protection and Privacy Act 2023 data minimization principle. Raw rider GPS and activity data never leaves the city cluster — only model gradients are centralized.

### Embedded Insurance Model (B2B2C)

ZoneGuard is a **technology platform**, not a licensed insurer. In production:
- Insurance risk is underwritten by an IRDAI-licensed general insurer partner
- **Identified candidates:** Bajaj Allianz (ClimateSafe for gig workers, 2025) and ICICI Lombard (backs SEWA's parametric microinsurance at scale — 225,000 workers covered, 2023–present)
- ZoneGuard provides: AI risk engine, trigger monitoring, payout orchestration, fraud detection
- Distribution via Amazon Flex platform API partnership

---

## 16. Business Case

### Market Opportunity

| Metric | Value | Source |
|--------|-------|--------|
| India gig workforce by 2030 | 2.35 crore workers | NITI Aayog, 2022 |
| E-commerce last-mile riders today | ~800,000–1,000,000 | Industry estimate |
| Parametric insurance market growth rate | 11.3% annually through 2028 | Market data |
| Existing income-loss products for this segment | **Zero** | Gap confirmed |
| Budget 2025 AB-PMJAY coverage scope | Health only | Govt. document |

### Unit Economics (Year 1 — 3% Penetration Target)

| Metric | Value |
|--------|-------|
| Target riders (3% penetration) | ~27,000 |
| Average weekly premium (blended) | ₹123 |
| Annual premium per rider | ₹6,396 |
| Annual gross premium (27K riders) | **₹17.3 Crore (~$2.06M)** |
| Expected loss ratio | 55–65% |
| Customer Acquisition Cost | Near-zero (B2B2C platform partnership) |
| Operational cost per claim | Near-zero (zero-touch automation) |

### Why The Loss Ratio Works

At maximum payout exposure (all disruption days triggered, all claims paid), the blended loss ratio across ZoneGuard's four risk tiers reaches ~95%. However, ZoneGuard's QuadSignal convergence requirement reduces qualifying event days by ~38% compared to a single-weather-API trigger (internal simulation basis: HSR Layout, monsoon season, 2022–2024 IMD data). This compression brings the realized loss ratio to ~59%, well within the 55–65% target band. Fewer events qualify, but every event that does is unambiguous, independently verified, and fast — which means the payouts that fire are real, and rider trust is maintained.

### Distribution Path

The hardest part of any insurance business is distribution. ZoneGuard's B2B2C model makes this near-zero cost: Amazon Flex already communicates regularly with riders via app notifications and email. ZoneGuard's integration point is the Flex partner communication channel — not individual rider acquisition. This is the key Phase 2 dependency.

---

## 17. Development Roadmap: 6 Weeks

### Phase 1 [March 4–20]: Ideation & Foundation ← CURRENT (Submitting Today)

- [x] Persona definition and scenario mapping (Amazon Flex, e-commerce)
- [x] Weekly premium model design (zone-risk-adjusted, Monday recalculation)
- [x] QuadSignal trigger specification (Environmental + Mobility + Economic + Crowd)
- [x] Fraud vector analysis and FraudShield architecture design
- [x] **Adversarial Defense & Anti-Spoofing Strategy** (Market Crash Response — Section 10)
- [x] ZoneTwin concept design and data requirements
- [x] Regulatory path research (IRDAI sandbox, e-Shram, embedded B2B2C model)
- [x] Basis risk mitigation protocol documented
- [x] Tech stack finalization and architecture design
- [x] Zone database seed plan (10 Bengaluru pin codes with IMD historical data)
- [x] WhatsApp onboarding flow design

### Phase 2 [March 21 – April 4]: Automation & Protection ← **COMPLETE**

- [x] WhatsApp onboarding bot — simulated (`whatsapp_sim.py`); web onboarding fully functional
- [x] Rider KYC flow — Amazon Flex Rider ID + phone binding + `kyc_verified` flag
- [x] Insurance Policy Management — create / view / renew / cancel with full exclusion list
- [x] Dynamic premium calculation API — ZoneRisk Scorer, ₹39/₹89/₹139/₹225 tiers, live zone data
- [x] QuadSignal Fusion Engine live — S1 (OpenWeatherMap live), S2-S4 simulated; 4 auto-scenarios
- [x] Claims Management UI — auto-trigger pipeline + manual review queue + Gemini AI audit
- [x] LLM Claim Audit integration — Gemini 1.5 Flash for MEDIUM confidence claims
- [x] Razorpay test mode UPI payout simulation — `payout_sim.py` (ZG-2026-XXXXXXXX refs)
- [x] FraudShield v1 — 8-feature heuristic scorer (velocity, timing, distance, tenure)
- [x] ZoneTwin v1 — per-zone logistic-curve counterfactual simulation (10 Bengaluru zones)

### Phase 3 [April 5–17]: Scale & Optimise ← **Final Submission Package**

- [x] FraudShield v1 heuristic — velocity, timing, GPS distance, tenure scoring
- [ ] FraudShield v2 — Federated Learning upgrade (Flower framework) — Phase 3
- [ ] Temporal clustering analysis for collusion ring detection — Phase 3
- [x] **Rider Analytics Dashboard** — earnings protected, payout history, active coverage card, zone risk level, disruption event feed
- [x] **Insurer Admin Analytics Dashboard** — KPI strip, ClaimsChart, PayoutChart, LossRatioWidget, QuadSignal live feed, FraudShield queue
- [x] Disruption simulation engine — 4 scenarios (flash_flood, severe_aqi, transport_strike, heat_wave)
- [ ] Forward Premium Lock feature (4-week commitment, 8% discount) — Phase 3
- [ ] e-Shram KYC integration — Phase 3
- [ ] **Final pitch deck (PDF)** ← Must create for submission
- [ ] **5-minute demo video** ← Must record for submission

---

## 18. Repository Structure

```
zoneguard/
├── README.md                           ← Phase 1 submission (this document)
├── SUBMISSION.md                       ← Final Phase 1 deliverable
├── backend/
│   ├── main.py                         # FastAPI entry point
│   ├── ml/
│   │   ├── zone_risk_scorer.py         # XGBoost premium model (Monday recalc)
│   │   ├── zone_twin.py                # Digital zone simulation + counterfactuals
│   │   ├── fraud_shield.py             # Isolation Forest + temporal clustering
│   │   ├── signal_fusion.py            # QuadSignal convergence engine
│   │   └── federated/                  # Flower FL framework (Phase 3)
│   │       ├── client.py
│   │       └── server.py
│   ├── routers/
│   │   ├── riders.py                   # Onboarding, KYC, profile management
│   │   ├── policies.py                 # Policy lifecycle (create, pause, cancel)
│   │   ├── claims.py                   # Trigger, audit, payout orchestration
│   │   └── zones.py                    # Zone data, risk scores, ZoneTwin queries
│   ├── integrations/
│   │   ├── whatsapp.py                 # Twilio WhatsApp Business API
│   │   ├── weather.py                  # OpenWeatherMap + NDMA alerts
│   │   ├── mobility.py                 # OSRM routing engine (self-hosted)
│   │   └── payments.py                 # Razorpay sandbox UPI simulation
│   └── db/                             # PostgreSQL schema + Alembic migrations
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── RiderDashboard/         # Earnings protected, payout history
│       │   ├── InsurerAdmin/           # Loss ratios, zone heatmaps, alerts
│       │   └── Onboarding/             # Web onboarding (non-WhatsApp path)
│       ├── components/
│       │   ├── ZoneMap/                # Interactive zone risk visualization
│       │   ├── CoverageWidget/         # Active weekly coverage card
│       │   └── PayoutHistory/          # Payout timeline
│       └── services/                   # API clients, signal polling
├── data/
│   ├── zones/                          # 10 Bengaluru pin code definitions
│   ├── historical/                     # IMD + CPCB + OSRM seed data
│   └── simulation/                     # Disruption simulation scripts for demo
├── ml_notebooks/
│   ├── zone_risk_analysis.ipynb        # Premium tier derivation + actuarial basis
│   ├── fraud_vector_analysis.ipynb     # Fraud pattern simulation + detection
│   └── zone_twin_prototype.ipynb       # Zone simulation prototype
└── docker-compose.yml
```

---

## 19. Novelty Matrix

| Dimension | Typical Solution | ZoneGuard's Approach |
|-----------|-----------------|---------------------|
| **Trigger design** | Single weather API threshold | Four independent signals must converge (environmental + mobility + economic + crowd-sourced) |
| **GPS fraud defense** | GPS coordinate check | Multi-layer: GPS quality + cell tower triangulation + Flex app state + accelerometer + ZoneTwin counterfactual |
| **Coordinated ring detection** | Not addressed | Temporal clustering coefficient analysis — genuine disruptions produce Poisson patterns; coordinated attacks produce detectable spikes |
| **Fraud model** | Isolation Forest on centralized data | Federated Learning across rider cohorts — fraud patterns learned without raw data centralization (DPDP Act compliant) |
| **Premium calculation** | Flat weekly fee or fixed risk tiers | Zone-specific XGBoost recalculated every Monday using live IMD forecast |
| **Basis risk** | Not addressed | Explicitly mitigated via crowd-truth layer, GPS cross-reference, ZoneTwin counterfactuals, moral hazard retention |
| **Onboarding** | App download or web form | WhatsApp-native, < 90 seconds, zero download |
| **Claim process** | Rider files a claim | Zero-touch: all signals converge → UPI payout within 2 hours |
| **Medium-confidence review** | Human reviews raw data | Claude API generates plain-language audit report; review time < 2 minutes |
| **Zone intelligence** | Static risk data | ZoneTwin per-zone digital simulation: forward seasonal runs, counterfactual checks, transfer learning for new zones |
| **Regulatory design** | Not considered | IRDAI Use & File sandbox + e-Shram integration + DPDP Act compliant federated architecture + B2B2C embedded model |
| **Data sources** | OpenWeatherMap only | OpenWeatherMap + OSRM (self-hosted) + IMD + CPCB + NDMA + Twilio WhatsApp + e-Shram (Phase 2) |
| **Anti-spoofing UX** | Penalize flagged workers | Tiered response — genuine workers protected by zone-level signal; two-hour frictionless appeal; rings detected at population level |

---

## 20. Phase 1 Deliverable Expectations — Coverage Map

The table below maps each official DEVTrails 2026 deliverable expectation to the specific section in this document where it is addressed. Provided for evaluator reference.

| Deliverable Expectation | ZoneGuard Coverage | Section Reference |
|------------------------|-------------------|-------------------|
| **Optimized onboarding for your delivery persona** | WhatsApp-native 90-second conversational flow — 3 messages, no forms, no app download. Flex Rider ID-based identity, instant policy activation. | [Section 5](#5-whatsapp-native-onboarding) |
| **Risk profiling using AI/ML** | ZoneRisk Scorer (XGBoost, Monday recalculation), ZoneTwin digital simulation (per-zone counterfactuals + seasonal forecasting), FraudShield Isolation Forest (anomaly detection on claim patterns). | [Section 9](#9-aiml-architecture) |
| **Policy creation with appropriate pricing structured on a Weekly basis** | Zone-specific weekly premiums ₹39–₹225 derived from XGBoost risk scoring. Monday recalculation. Forward Premium Lock (4-week, 8% discount). Payout = 55% of 7-day rolling average earnings. | [Section 6](#6-weekly-premium-model) |
| **Claim triggering through relevant parametric events (loss of income triggers only)** | QuadSignal convergence across 6 defined triggers (ENV-01 through SOC-02). All triggers are income-loss-only. Health, life, accidents, and vehicle repairs are structurally excluded. | [Sections 7–8](#7-quadsignal-fusion-engine-the-core-innovation) |
| **Payout processing via appropriate channels** | Razorpay test-mode UPI simulation. Auto-payout within 2 hours on HIGH confidence. Payout capped at 55% of 7-day earnings baseline. Zero rider action required. | [Sections 6, 14](#6-weekly-premium-model) |
| **Analytics dashboard showing relevant metrics** | Rider Analytics Dashboard (earnings protected, payout history, zone risk, coverage card) + Insurer Admin Analytics Dashboard (zone risk heatmaps, loss ratios, QuadSignal log, disruption alerts, FraudShield queue). | [Section 17 — Phase 3](#17-development-roadmap-6-weeks) |

---

## Regulatory Note

For the purposes of this hackathon, ZoneGuard operates in a sandboxed simulation environment. The post-hackathon production path requires securing a white-label underwriting partnership with an IRDAI-licensed general insurer before real premium collection begins.

ZoneGuard's IRDAI "Use & File" regulatory design means product launch can begin within weeks of securing a partner, not months.

---

*Built for Guidewire DEVTrails 2026 · University Hackathon · Phase 2 Complete Submission*
*Phase 1 Submitted: March 20, 2026 · Phase 2 Submitted: April 4, 2026*

---

> **Coverage strictly limited to:** Lost working hours caused by external, uncontrollable disruptions — extreme weather, severe pollution, curfews, transport strikes.
>
> **Strictly excluded:** Health, life, accidents, vehicle repairs — per IRDAI parametric scope and challenge constraints.
