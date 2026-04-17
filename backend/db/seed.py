"""
Database seeder — Creates tables and seeds initial data.

Seeds:
- 10 Bengaluru zones with coordinates, risk scores, premium tiers
- 10 policy exclusion types
- 5 sample riders with active policies
"""

import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import engine, async_session, Base
from models import (
    Zone, Rider, Policy, PolicyExclusionType, PolicyAppliedExclusion,
    Claim, SignalReading, DisruptionEvent, Payout, FraudFlag,
    AuditLog, PremiumCalculation, SimulationEvent,
)
from services.exclusion_engine import EXCLUSION_TYPES
from ml.zone_twin import ZONE_BASELINES
from datetime import datetime, timedelta, timezone
import uuid


ZONES = [
    # risk_score must be in correct tier range: low<30, medium 30-54, high 55-74, flood-prone 75+
    # weekly_premium and max_weekly_payout must match zone_risk_scorer.py PREMIUM_TIERS
    {"id": "hsr", "name": "HSR Layout", "pin_code": "560102", "lat": 12.9116, "lng": 77.6389, "risk_tier": "medium", "risk_score": 45, "weekly_premium": 89, "max_weekly_payout": 4290, "active_riders": 142, "historical_disruptions": 3},
    {"id": "koramangala", "name": "Koramangala", "pin_code": "560034", "lat": 12.9352, "lng": 77.6245, "risk_tier": "medium", "risk_score": 48, "weekly_premium": 89, "max_weekly_payout": 4290, "active_riders": 198, "historical_disruptions": 3},
    {"id": "whitefield", "name": "Whitefield", "pin_code": "560066", "lat": 12.9698, "lng": 77.7500, "risk_tier": "low", "risk_score": 22, "weekly_premium": 39, "max_weekly_payout": 1430, "active_riders": 215, "historical_disruptions": 1},
    {"id": "indiranagar", "name": "Indiranagar", "pin_code": "560038", "lat": 12.9784, "lng": 77.6408, "risk_tier": "medium", "risk_score": 50, "weekly_premium": 89, "max_weekly_payout": 4290, "active_riders": 167, "historical_disruptions": 3},
    {"id": "electronic-city", "name": "Electronic City", "pin_code": "560100", "lat": 12.8399, "lng": 77.6770, "risk_tier": "low", "risk_score": 24, "weekly_premium": 39, "max_weekly_payout": 1430, "active_riders": 289, "historical_disruptions": 1},
    {"id": "bellandur", "name": "Bellandur", "pin_code": "560103", "lat": 12.9256, "lng": 77.6780, "risk_tier": "flood-prone", "risk_score": 87, "weekly_premium": 225, "max_weekly_payout": 11440, "active_riders": 94, "historical_disruptions": 8},
    {"id": "btm-layout", "name": "BTM Layout", "pin_code": "560076", "lat": 12.9166, "lng": 77.6101, "risk_tier": "high", "risk_score": 68, "weekly_premium": 139, "max_weekly_payout": 7150, "active_riders": 131, "historical_disruptions": 5},
    {"id": "jp-nagar", "name": "JP Nagar", "pin_code": "560078", "lat": 12.9063, "lng": 77.5857, "risk_tier": "high", "risk_score": 65, "weekly_premium": 139, "max_weekly_payout": 7150, "active_riders": 112, "historical_disruptions": 5},
    {"id": "yelahanka", "name": "Yelahanka", "pin_code": "560064", "lat": 13.1007, "lng": 77.5963, "risk_tier": "low", "risk_score": 19, "weekly_premium": 39, "max_weekly_payout": 1430, "active_riders": 178, "historical_disruptions": 1},
    {"id": "hebbal", "name": "Hebbal", "pin_code": "560024", "lat": 13.0358, "lng": 77.5970, "risk_tier": "high", "risk_score": 71, "weekly_premium": 139, "max_weekly_payout": 7150, "active_riders": 103, "historical_disruptions": 5},
]

RIDERS = [
    {"id": "AMZFLEX-BLR-04821", "name": "Ravi Kumar", "phone": "+919876543210", "zone_id": "hsr", "weekly_earnings_baseline": 18200, "tenure_weeks": 28, "kyc_verified": True, "upi_id": "ravi.kumar@upi"},
    {"id": "AMZFLEX-BLR-03156", "name": "Priya Sharma", "phone": "+919876543211", "zone_id": "koramangala", "weekly_earnings_baseline": 15400, "tenure_weeks": 42, "kyc_verified": True, "upi_id": "priya.s@upi"},
    {"id": "AMZFLEX-BLR-07392", "name": "Ahmed Khan", "phone": "+919876543212", "zone_id": "bellandur", "weekly_earnings_baseline": 16800, "tenure_weeks": 15, "kyc_verified": True, "upi_id": "ahmed.k@upi"},
    {"id": "AMZFLEX-BLR-01984", "name": "Lakshmi Devi", "phone": "+919876543213", "zone_id": "btm-layout", "weekly_earnings_baseline": 14000, "tenure_weeks": 52, "kyc_verified": True, "upi_id": "lakshmi.d@upi"},
    {"id": "AMZFLEX-BLR-05678", "name": "Suresh Reddy", "phone": "+919876543214", "zone_id": "whitefield", "weekly_earnings_baseline": 19600, "tenure_weeks": 8, "kyc_verified": False, "upi_id": None},
]


async def seed():
    print("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migrate existing DBs: add columns that may be missing from earlier schema
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE riders ADD COLUMN IF NOT EXISTS eshram_id VARCHAR DEFAULT NULL"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE riders ADD COLUMN IF NOT EXISTS eshram_verified BOOLEAN DEFAULT FALSE"
            )
        )
        await conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE notifications ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE 'UTC'"
            )
        )
    print("Tables created.")

    async with async_session() as session:
        # Check if already seeded
        from sqlalchemy import select, func
        result = await session.execute(select(func.count(Zone.id)))
        zone_count = result.scalar()
        if zone_count > 0:
            print(f"Database already seeded ({zone_count} zones found). Skipping.")
            return

        # Seed zones — flush immediately so FK constraints work
        print("Seeding zones...")
        for z in ZONES:
            zone = Zone(**z)
            # Populate zone_baselines from ZoneTwin historical data
            if z["id"] in ZONE_BASELINES:
                zone.zone_baselines = ZONE_BASELINES[z["id"]]
            session.add(zone)
        await session.flush()

        # Seed exclusion types — flush so policy FK constraints work
        print("Seeding exclusion types...")
        for excl in EXCLUSION_TYPES:
            session.add(PolicyExclusionType(**excl))
        await session.flush()

        # Seed riders — zones must exist in DB first
        print("Seeding riders...")
        for r in RIDERS:
            session.add(Rider(**r))
        await session.flush()

        # Seed policies for verified riders
        print("Seeding policies...")
        now = datetime.now(timezone.utc)
        for r in RIDERS:
            if not r["kyc_verified"]:
                continue

            zone = next(z for z in ZONES if z["id"] == r["zone_id"])
            policy = Policy(
                rider_id=r["id"],
                zone_id=r["zone_id"],
                weekly_premium=zone["weekly_premium"],
                max_payout=zone["max_weekly_payout"],
                coverage_start=now - timedelta(days=2),
                coverage_end=now + timedelta(days=5),
            )
            session.add(policy)
            await session.flush()

            # Attach all exclusions to each policy
            for excl in EXCLUSION_TYPES:
                applied = PolicyAppliedExclusion(
                    id=uuid.uuid4().hex[:12],
                    policy_id=policy.id,
                    exclusion_type_id=excl["id"],
                )
                session.add(applied)

        await session.commit()
        print("Seed complete! Created:")
        print(f"  - {len(ZONES)} zones")
        print(f"  - {len(EXCLUSION_TYPES)} exclusion types")
        print(f"  - {len(RIDERS)} riders")
        print(f"  - {sum(1 for r in RIDERS if r['kyc_verified'])} policies with exclusions")


if __name__ == "__main__":
    asyncio.run(seed())
