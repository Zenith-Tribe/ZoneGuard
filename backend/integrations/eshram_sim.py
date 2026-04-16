"""
Simulated e-Shram Portal API integration.

Budget 2025 mandated gig platform aggregators to register their workers on e-Shram.
Provides:
- KYC verification — no separate document upload for registered workers
- Identity deduplication — prevents duplicate registration fraud
- Income proxy validation — e-Shram work history cross-referenced with declared baseline earnings
"""

import logging
import asyncio
import hashlib
import numpy as np
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def verify_eshram_worker(
    eshram_id: str,
    rider_name: str,
    phone: str,
) -> dict:
    """Verify a worker against the e-Shram portal (simulated)."""

    # Simulate API delay (1 second)
    await asyncio.sleep(1)

    # Validate UAN format: must be exactly 12-digit numeric
    if not (eshram_id.isdigit() and len(eshram_id) == 12):
        logger.warning(f"e-Shram KYC rejected: invalid UAN format '{eshram_id}'")
        return {
            "status": "invalid",
            "eshram_id": eshram_id,
            "message": "Invalid e-Shram UAN format (must be 12-digit numeric)",
            "verified": False,
            "source": "simulated_eshram_portal",
        }

    # Deterministic success/failure based on hash of eshram_id (90% success rate)
    digest = hashlib.sha256(eshram_id.encode()).hexdigest()
    success = int(digest, 16) % 10 < 9  # 9 out of 10 → success

    if success:
        logger.info(f"e-Shram KYC verified: UAN {eshram_id} for {rider_name}")
        return {
            "status": "verified",
            "eshram_id": eshram_id,
            "verified": True,
            "worker_name": rider_name,
            "phone_match": True,
            "registration_date": "2025-06-15",
            "worker_category": "gig_delivery",
            "occupation_code": "9621",  # Messengers, package deliverers
            "income_band": "₹10,000–₹25,000/month",
            "state": "Karnataka",
            "deduplication_check": {
                "is_unique": True,
                "existing_accounts": 0,
                "check_method": "eshram_uan_crossref",
            },
            "source": "simulated_eshram_portal",
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    # 10% mismatch
    logger.warning(f"e-Shram KYC mismatch: UAN {eshram_id} — name/phone mismatch")
    return {
        "status": "mismatch",
        "eshram_id": eshram_id,
        "verified": False,
        "message": "Name/phone mismatch with e-Shram records",
        "source": "simulated_eshram_portal",
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


async def check_income_proxy(
    eshram_id: str,
    declared_weekly_earnings: float,
) -> dict:
    """Cross-reference declared earnings with e-Shram income records (simulated)."""

    # Simulate API delay (0.5 seconds)
    await asyncio.sleep(0.5)

    declared_monthly = declared_weekly_earnings * 4.33

    # Generate simulated e-Shram reported monthly income within ±30% of declared
    seed = int(hashlib.sha256(eshram_id.encode()).hexdigest(), 16) % (2**31)
    rng = np.random.default_rng(seed)
    deviation_factor = rng.uniform(-0.30, 0.30)
    simulated_monthly = round(declared_monthly * (1 + deviation_factor), 2)

    deviation_pct = round(abs(deviation_factor) * 100, 1)
    income_validated = deviation_pct < 50  # within 50% is acceptable

    if deviation_pct < 30:
        risk_flag = "none"
    elif deviation_pct < 50:
        risk_flag = "review"
    else:
        risk_flag = "high"

    logger.info(
        f"e-Shram income proxy for UAN {eshram_id}: "
        f"declared ₹{declared_monthly:.0f}/mo vs reported ₹{simulated_monthly:.0f}/mo "
        f"(deviation {deviation_pct}%, flag={risk_flag})"
    )

    return {
        "eshram_id": eshram_id,
        "declared_weekly": declared_weekly_earnings,
        "declared_monthly": round(declared_monthly, 2),
        "eshram_reported_monthly": simulated_monthly,
        "deviation_pct": deviation_pct,
        "income_validated": income_validated,
        "risk_flag": risk_flag,
        "source": "simulated_eshram_income_proxy",
    }
