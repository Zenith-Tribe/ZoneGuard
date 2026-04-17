from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.database import get_db
from models.zone import Zone
from models.rider import Rider
from models.policy import Policy
from models.claim import Claim
from schemas.zone import ZoneResponse
from schemas.rider import RiderResponse
from schemas.claim import ClaimResponse
from services.signal_poller import poll_zone_signals
from ml.signal_fusion import evaluate_s1, evaluate_s2, evaluate_s3, evaluate_s4, fuse_signals, get_h3_index
from ml.zone_twin import counterfactual_inactivity, get_predictive_hedge_opportunity
from datetime import datetime, timezone

router = APIRouter(prefix="/api/v1/zones", tags=["zones"])

# In-memory cache of latest signal readings per zone (for real-time polling)
_signal_cache: dict[str, dict] = {}


@router.get("")
async def list_zones(db: AsyncSession = Depends(get_db)) -> list[ZoneResponse]:
    """List all zones enriched with Phase 3 H3 metadata."""
    result = await db.execute(select(Zone))
    zones = result.scalars().all()
    # Pydantic will handle the validation, but we can enrich the objects if needed
    return [ZoneResponse.model_validate(z) for z in zones]


@router.get("/{zone_id}")
async def get_zone(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Get zone details with hyper-local H3 index."""
    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    
    response = ZoneResponse.model_validate(zone).model_dump()
    # Add H3 Hex ID for hyper-local precision
    response["h3_id"] = get_h3_index(zone.lat, zone.lng, res=8)
    return response


@router.get("/{zone_id}/signals/current")
async def get_current_signals(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Get current signal readings for a zone (cached or live)."""
    if zone_id in _signal_cache:
        return _signal_cache[zone_id]

    zone = await db.get(Zone, zone_id)
    if not zone:
        return {"error": "Zone not found"}

    signals = await poll_zone_signals({
        "id": zone.id, "lat": zone.lat, "lng": zone.lng,
        "active_riders": zone.active_riders,
    })

    # Evaluate fusion
    weather = signals["weather"]
    mobility = signals["mobility"]
    orders = signals["orders"]
    checkins = signals["checkins"]

    s1 = evaluate_s1(weather["rainfall_mm_hr"], weather["aqi"], weather["temperature_c"])
    s2 = evaluate_s2(mobility["mobility_index"])
    s3 = evaluate_s3(orders["order_volume"])
    s4 = evaluate_s4(checkins["inactive_riders"], checkins["total_riders"])
    
    # Phase 3: Include rider location for H3 verification
    rider_loc = {"lat": zone.lat, "lng": zone.lng}
    fusion = fuse_signals(s1, s2, s3, s4, rider_location=rider_loc)

    result = {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "h3_index": fusion.get("h3_index"),
        "s1_environmental": {
            "status": "firing" if s1["breached"] else "inactive",
            "value": f"Rainfall: {weather['rainfall_mm_hr']:.0f}mm/hr",
            "threshold": ">65mm/hr",
            "raw": s1,
        },
        "s2_mobility": {
            "status": "firing" if s2["breached"] else "inactive",
            "value": f"Mobility: {s2['value']:.0f}% of baseline",
            "threshold": "<25% of baseline",
            "raw": s2,
        },
        "s3_economic": {
            "status": "firing" if s3["breached"] else "inactive",
            "value": f"Orders: {s3['value']:.0f}% of baseline",
            "threshold": "<30% of baseline",
            "raw": s3,
        },
        "s4_crowd": {
            "status": "firing" if s4["breached"] else "inactive",
            "value": f"Check-ins: {s4['value']:.0f}% inactivity",
            "threshold": ">=40% inactivity",
            "raw": s4,
        },
        "confidence": fusion["confidence"],
        "signals_fired": fusion["signals_fired"],
        "is_disrupted": fusion["signals_fired"] >= 2,
        "fusion": fusion,
        "weather": weather,
        "phase_version": 3.0
    }

    _signal_cache[zone_id] = result
    return result


@router.get("/{zone_id}/risk-score")
async def get_risk_score(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Zone risk score with ZoneTwin counterfactual."""
    zone = await db.get(Zone, zone_id)
    if not zone:
        return {"error": "Zone not found"}

    # Get current weather for counterfactual
    signals = _signal_cache.get(zone_id)
    rainfall = 20  # default
    aqi = 100
    if signals:
        rainfall = signals.get("weather", {}).get("rainfall_mm_hr", 20)
        aqi = signals.get("weather", {}).get("aqi", 100)

    twin = counterfactual_inactivity(zone_id, rainfall, aqi)

    return {
        "zone_id": zone_id,
        "risk_score": zone.risk_score,
        "risk_tier": zone.risk_tier,
        "zone_twin": twin,
    }


# --- PHASE 3 GOLDEN FEATURE ENDPOINTS ---

@router.get("/{zone_id}/predictive-hedge")
async def get_zone_hedge(zone_id: str):
    """
    Phase 3: Sunday-night Predictive Hedge API.
    Returns forecasted disruption probability for the week.
    """
    prediction = get_predictive_hedge_opportunity(zone_id)
    return {
        "status": "success",
        "data": prediction
    }


@router.get("/analytics/h3-heatmap")
async def get_h3_heatmap(db: AsyncSession = Depends(get_db)):
    """
    Phase 3: Returns Resolution 8 Hexagonal grid data for Admin Heatmap.
    This fulfills the requirement for hyper-local granularity visualization.
    """
    result = await db.execute(select(Zone))
    zones = result.scalars().all()
    
    cells = []
    for z in zones:
        cells.append({
            "h3_id": get_h3_index(z.lat, z.lng, res=8),
            "risk_level": z.risk_tier,
            "risk_score": z.risk_score,
            "is_active": z.risk_score > 60
        })
        
    return {
        "resolution": 8,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cells": cells
    }


@router.get("/{zone_id}/riders")
async def get_zone_riders(zone_id: str, db: AsyncSession = Depends(get_db)):
    """List all riders in a zone."""
    zone = await db.get(Zone, zone_id)
    if not zone:
        return {"error": "Zone not found"}

    result = await db.execute(
        select(Rider).where(Rider.zone_id == zone_id).order_by(Rider.created_at.desc())
    )
    riders = result.scalars().all()
    return [RiderResponse.model_validate(r) for r in riders]


@router.get("/{zone_id}/policies")
async def get_zone_policies(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Active policies in a zone."""
    result = await db.execute(
        select(Policy).where(Policy.zone_id == zone_id).where(Policy.status == "active")
    )
    policies = result.scalars().all()
    return [
        {
            "id": p.id,
            "rider_id": p.rider_id,
            "zone_id": p.zone_id,
            "status": p.status,
            "weekly_premium": p.weekly_premium,
            "max_payout": p.max_payout,
            "coverage_start": p.coverage_start.isoformat() if p.coverage_start else None,
            "coverage_end": p.coverage_end.isoformat() if p.coverage_end else None,
        }
        for p in policies
    ]


@router.get("/{zone_id}/claims")
async def get_zone_claims(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Claims history for a zone."""
    result = await db.execute(
        select(Claim).where(Claim.zone_id == zone_id).order_by(Claim.created_at.desc())
    )
    claims = result.scalars().all()
    return [ClaimResponse.model_validate(c) for c in claims]


def update_signal_cache(zone_id: str, data: dict):
    """Update the signal cache (used by simulator and poller)."""
    _signal_cache[zone_id] = data


def clear_signal_cache(zone_id: str):
    """Clear cached signals for a zone."""
    _signal_cache.pop(zone_id, None)
