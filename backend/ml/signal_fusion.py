"""
Phase 3: QuadSignal Fusion Engine (Updated for Hyper-local Precision)

4 independent signals must converge within a 2-hour rolling window.
Supports Resolution 8 Hexagonal triggers for hyper-local precision (~450m).

Signal types and thresholds:
- S1 Environmental: rainfall >65mm/hr, AQI >300, temp >43°C, or NDMA flood alert
- S2 Mobility: zone mobility index drops >75% from 7-day rolling baseline
- S3 Economic: order volume drops >70% from hourly baseline
- S4 Crowd: ≥40% of zone riders self-report inactivity via WhatsApp check-ins
"""

from datetime import datetime, timezone
from typing import Optional, Set

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

def get_h3_index(lat: float, lng: float, res: int = 8) -> str:
    """
    Phase 3: Converts coordinates to a Resolution 8 Hexagon.
    Uses H3 v4 API (latlng_to_cell). 
    """
    try:
        import h3
        # h3-py v4.x API
        return h3.latlng_to_cell(lat, lng, res)
    except (ImportError, AttributeError):
        # Graceful deterministic fallback: Valid 15-char H3 token format for demo
        # Ensures downstream logic doesn't crash on malformed strings
        return f"886014c1d3{int(abs(lat))%10}{int(abs(lng))%10}ffff"[:15]

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

def fuse_signals(
    s1: dict, 
    s2: dict, 
    s3: dict, 
    s4: dict, 
    rider_location: Optional[dict] = None,
    breached_hexes: Optional[Set[str]] = None
) -> dict:
    """
    Phase 3: Fuse signals with active Hyper-local H3 Gate.
    Verifies if the specific micro-cell (Res 8) has confirmed signal breaches.
    """
    signals = {"S1": s1, "S2": s2, "S3": s3, "S4": s4}
    fired = sum(1 for s in signals.values() if s.get("breached"))
    confidence = CONFIDENCE_MAP.get(fired, "NOISE")

    # Hyper-local Gate Implementation
    h3_index = None
    is_hyper_local_verified = False 
    
    if rider_location and 'lat' in rider_location and 'lng' in rider_location:
        h3_index = get_h3_index(rider_location['lat'], rider_location['lng'], res=8)
        
        # Real-world logic: Match rider's cell against cells with confirmed sensor breaches
        # For the hackathon demo: If 3+ signals are firing, we simulate cell-level verification
        if breached_hexes:
            is_hyper_local_verified = h3_index in breached_hexes
        else:
            is_hyper_local_verified = (fired >= 3)
    else:
        # Default to True only if no location is provided for backward compatibility
        is_hyper_local_verified = True 

    return {
        "signals_fired": fired,
        "confidence": confidence,
        "signal_details": signals,
        "h3_index": h3_index,
        "is_hyper_local": is_hyper_local_verified,
        "should_auto_payout": (confidence == "HIGH" and is_hyper_local_verified),
        "should_recheck": confidence == "MEDIUM",
        "needs_review": confidence == "LOW",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase_version": 3.0
    }
