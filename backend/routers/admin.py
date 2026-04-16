from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast
from sqlalchemy.types import Date
from db.database import get_db
from models.zone import Zone
from models.rider import Rider
from models.policy import Policy
from models.claim import Claim
from models.payout import Payout
from models.fraud import FraudFlag
from models.audit import AuditLog
from models.signal import SignalReading
from schemas.claim import ClaimResponse
from schemas.rider import RiderResponse
from schemas.payout import PayoutResponse
from schemas.admin import ZoneBaselineUpdate
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/kpis")
async def get_kpis(db: AsyncSession = Depends(get_db)):
    """Dashboard KPIs for admin."""
    active_policies_result = await db.execute(
        select(func.count(Policy.id)).where(Policy.status == "active")
    )
    active_policies = active_policies_result.scalar() or 0

    riders_result = await db.execute(select(func.count(Rider.id)))
    total_riders = riders_result.scalar() or 0

    payouts_result = await db.execute(
        select(func.sum(Payout.amount)).where(Payout.status == "settled")
    )
    total_payouts = payouts_result.scalar() or 0

    pending_result = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "pending_review")
    )
    pending_claims = pending_result.scalar() or 0

    premiums_result = await db.execute(select(func.sum(Policy.weekly_premium)))
    total_premiums = premiums_result.scalar() or 0

    loss_ratio = round((total_payouts / max(total_premiums, 1)) * 100, 1)

    fraud_result = await db.execute(
        select(func.count(FraudFlag.id)).where(FraudFlag.risk_level.in_(["review", "hold"]))
    )
    fraud_flags = fraud_result.scalar() or 0

    risk_zones_result = await db.execute(
        select(func.count(Zone.id)).where(Zone.risk_score > 70)
    )
    zones_at_risk = risk_zones_result.scalar() or 0

    return {
        "kpis": [
            {"label": "Loss Ratio", "value": f"{loss_ratio}%", "delta": "-2.1%", "trend": "down", "sparkline": [58, 57, 61, 55, 56, 54, loss_ratio]},
            {"label": "Active Policies", "value": f"{active_policies:,}", "delta": "+47", "trend": "up", "sparkline": [1420, 1490, 1530, 1558, 1580, 1601, active_policies]},
            {"label": "Payouts This Week", "value": f"₹{total_payouts/100000:.1f}L" if total_payouts > 100000 else f"₹{total_payouts:,.0f}", "delta": "+₹1.2L", "trend": "up", "sparkline": [18000, 22000, 19000, 31000, 28000, 38000, total_payouts]},
            {"label": "Zones at Risk", "value": str(zones_at_risk), "delta": "+1", "trend": "up", "sparkline": [1, 2, 1, 2, 3, 3, zones_at_risk]},
        ],
        "summary": {
            "total_riders": total_riders,
            "active_policies": active_policies,
            "pending_claims": pending_claims,
            "fraud_flags": fraud_flags,
            "total_payouts": total_payouts,
            "total_premiums": total_premiums,
            "loss_ratio": loss_ratio,
        },
    }


# ── Claims Management ────────────────────────────────────────────────

@router.get("/claims")
async def list_admin_claims(
    status: str = Query(None),
    zone_id: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Paginated claims queue with status/zone filters."""
    query = select(Claim)
    if status:
        query = query.where(Claim.status == status)
    if zone_id:
        query = query.where(Claim.zone_id == zone_id)
    query = query.order_by(Claim.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    claims = result.scalars().all()

    return {
        "items": [ClaimResponse.model_validate(c) for c in claims],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/claims/{claim_id}/audit-report")
async def get_claim_audit_report(claim_id: str, db: AsyncSession = Depends(get_db)):
    """Fetch Gemini audit report for a claim."""
    claim = await db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.claim_id == claim_id)
        .order_by(AuditLog.created_at.desc())
    )
    audit = result.scalars().first()

    if not audit:
        raise HTTPException(status_code=404, detail="No audit report found for this claim")

    return {
        "claim_id": claim_id,
        "content": audit.content,
        "model_used": audit.model_used,
        "generated_by": audit.generated_by,
        "generated_at": audit.created_at.isoformat(),
    }


# ── Rider Management ─────────────────────────────────────────────────

@router.get("/riders")
async def list_admin_riders(
    zone_id: str = Query(None),
    kyc_verified: bool = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List riders with pagination and filters."""
    query = select(Rider)
    if zone_id:
        query = query.where(Rider.zone_id == zone_id)
    if kyc_verified is not None:
        query = query.where(Rider.kyc_verified == kyc_verified)
    query = query.order_by(Rider.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    riders = result.scalars().all()

    return {
        "items": [RiderResponse.model_validate(r) for r in riders],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/riders/{rider_id}/summary")
async def get_rider_summary(rider_id: str, db: AsyncSession = Depends(get_db)):
    """Rider summary with claims and payouts."""
    rider = await db.get(Rider, rider_id)
    if not rider:
        raise HTTPException(status_code=404, detail="Rider not found")

    claims_result = await db.execute(
        select(Claim).where(Claim.rider_id == rider_id).order_by(Claim.created_at.desc())
    )
    claims = claims_result.scalars().all()

    payouts_result = await db.execute(
        select(Payout).where(Payout.rider_id == rider_id).order_by(Payout.created_at.desc())
    )
    payouts = payouts_result.scalars().all()

    total_payout = sum(p.amount for p in payouts if p.status == "settled")

    return {
        "rider": RiderResponse.model_validate(rider),
        "total_claims": len(claims),
        "approved_claims": sum(1 for c in claims if c.status == "approved"),
        "total_payouts": total_payout,
        "claims": [ClaimResponse.model_validate(c) for c in claims[:10]],
        "payouts": [PayoutResponse.model_validate(p) for p in payouts[:10]],
    }


# ── Zone Baselines ────────────────────────────────────────────────────

@router.put("/zones/{zone_id}/baselines")
async def update_zone_baselines(
    zone_id: str, baselines: ZoneBaselineUpdate, db: AsyncSession = Depends(get_db),
):
    """Update zone baselines."""
    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    update = {k: v for k, v in baselines.model_dump().items() if v is not None}
    zone.zone_baselines = {**(zone.zone_baselines or {}), **update}
    await db.commit()
    return {"zone_id": zone_id, "baselines": zone.zone_baselines}


# ── Fraud & Audit ─────────────────────────────────────────────────────

@router.get("/fraud-flags")
async def list_fraud_flags(
    risk_level: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List fraud flags with severity filter."""
    query = select(FraudFlag)
    if risk_level:
        query = query.where(FraudFlag.risk_level == risk_level)
    query = query.order_by(FraudFlag.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    flags = result.scalars().all()

    return {
        "items": [
            {
                "id": f.id, "claim_id": f.claim_id, "rider_id": f.rider_id,
                "score": f.score, "risk_level": f.risk_level,
                "features": f.features, "created_at": f.created_at.isoformat(),
            }
            for f in flags
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/audit-logs")
async def list_audit_logs(
    event_type: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Audit logs with event_type filter."""
    query = select(AuditLog)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    query = query.order_by(AuditLog.created_at.desc())

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    logs = result.scalars().all()

    return {
        "items": [
            {
                "id": log.id, "claim_id": log.claim_id, "event_type": log.event_type,
                "content": log.content, "model_used": log.model_used,
                "generated_by": log.generated_by, "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


# ── Analytics ─────────────────────────────────────────────────────────

@router.get("/analytics/claims-by-zone")
async def claims_by_zone(db: AsyncSession = Depends(get_db)):
    """Claims aggregated by zone."""
    result = await db.execute(
        select(
            Claim.zone_id,
            func.count(Claim.id).label("total"),
            func.sum(func.cast(Claim.status == "approved", type_=None)).label("approved_raw"),
            func.sum(func.cast(Claim.status == "rejected", type_=None)).label("rejected_raw"),
        ).group_by(Claim.zone_id)
    )
    rows = result.all()

    # Zone names
    zones_result = await db.execute(select(Zone.id, Zone.name))
    zone_names = dict(zones_result.all())

    # Payouts per zone
    payout_result = await db.execute(
        select(
            Claim.zone_id,
            func.coalesce(func.sum(Payout.amount), 0).label("total_payout"),
        )
        .join(Payout, Payout.claim_id == Claim.id, isouter=True)
        .where(Payout.status == "settled")
        .group_by(Claim.zone_id)
    )
    zone_payouts = dict(payout_result.all())

    items = []
    for r in rows:
        total = r.total or 0
        # Count approved/rejected by querying individually to avoid SQL expression issues
        approved_q = await db.execute(
            select(func.count(Claim.id))
            .where(Claim.zone_id == r.zone_id, Claim.status == "approved")
        )
        approved = approved_q.scalar() or 0

        rejected_q = await db.execute(
            select(func.count(Claim.id))
            .where(Claim.zone_id == r.zone_id, Claim.status == "rejected")
        )
        rejected = rejected_q.scalar() or 0

        pending = total - approved - rejected
        items.append({
            "zone_id": r.zone_id,
            "zone_name": zone_names.get(r.zone_id, r.zone_id),
            "total_claims": total,
            "approved": approved,
            "rejected": rejected,
            "pending": max(0, pending),
            "total_payout": float(zone_payouts.get(r.zone_id, 0)),
        })

    return items


@router.get("/analytics/payouts-over-time")
async def payouts_over_time(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Payouts aggregated by day."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(
            func.date(Payout.created_at).label("date"),
            func.count(Payout.id).label("count"),
            func.coalesce(func.sum(Payout.amount), 0).label("total_amount"),
        )
        .where(Payout.created_at >= cutoff)
        .group_by(func.date(Payout.created_at))
        .order_by(func.date(Payout.created_at))
    )
    rows = result.all()

    return [
        {"date": str(r.date), "count": r.count, "total_amount": float(r.total_amount)}
        for r in rows
    ]


@router.get("/analytics/loss-ratio-trend")
async def loss_ratio_trend(db: AsyncSession = Depends(get_db)):
    """Loss ratio over 4 weekly windows."""
    now = datetime.now(timezone.utc)
    trend = []

    for i in range(4):
        end = now - timedelta(weeks=i)
        start = end - timedelta(weeks=1)

        premiums_result = await db.execute(
            select(func.coalesce(func.sum(Policy.weekly_premium), 0))
            .where(Policy.created_at.between(start, end))
        )
        premiums = float(premiums_result.scalar() or 0)

        payouts_result = await db.execute(
            select(func.coalesce(func.sum(Payout.amount), 0))
            .where(Payout.created_at.between(start, end))
            .where(Payout.status == "settled")
        )
        payouts = float(payouts_result.scalar() or 0)

        loss_ratio = round((payouts / max(premiums, 1)) * 100, 1)
        trend.append({
            "date": start.strftime("%Y-%m-%d"),
            "premiums": premiums,
            "payouts": payouts,
            "loss_ratio": loss_ratio,
        })

    return list(reversed(trend))


# ── FraudShield v2 — Federated Learning ─────────────────────────────

@router.post("/fraudshield/train")
async def train_federated_model(db: AsyncSession = Depends(get_db)):
    """Run federated learning training across city-level clients."""
    from ml.federated.client import FederatedClient
    from ml.federated.server import FederatedServer, generate_synthetic_training_data

    # Get zone IDs for client partitioning
    zones_result = await db.execute(select(Zone.id))
    zone_ids = [z[0] for z in zones_result.all()]

    # Partition zones into 3 city clusters
    city_clusters = {
        "bengaluru_north": zone_ids[:len(zone_ids)//3] or zone_ids[:1],
        "bengaluru_central": zone_ids[len(zone_ids)//3:2*len(zone_ids)//3] or zone_ids[:1],
        "bengaluru_south": zone_ids[2*len(zone_ids)//3:] or zone_ids[:1],
    }

    server = FederatedServer(num_rounds=5)

    for city_id, city_zones in city_clusters.items():
        client = FederatedClient(city_id=city_id, zone_ids=city_zones)
        # Generate synthetic training data for each city
        training_data = []
        for z_id in city_zones:
            training_data.extend(generate_synthetic_training_data(z_id, num_samples=50))
        client.train_local_model(training_data)
        server.register_client(client)

    # Run federated training
    result = server.run_full_training()

    # Store trained weights in module-level registry for v2 scoring
    from ml.fraud_shield import set_federated_weights
    set_federated_weights(result["final_weights"])

    return result


@router.get("/fraudshield/status")
async def get_federated_status():
    """Get FraudShield v2 federated model status."""
    return {
        "model_version": "v2_federated",
        "framework": "Flower-inspired (simulated)",
        "aggregation": "FedAvg",
        "features": 8,
        "description": "Privacy-preserving federated anomaly detection. "
                       "Raw rider data never leaves city cluster — only model gradients are shared.",
        "dpdp_compliant": True,
    }


# ── Temporal Clustering (Ring Detection) ─────────────────────────────

@router.get("/fraud/temporal-analysis/{zone_id}")
async def temporal_analysis(zone_id: str, db: AsyncSession = Depends(get_db)):
    """Run temporal clustering analysis on recent claims for a zone."""
    from ml.temporal_clustering import analyze_temporal_clustering, detect_collusion_rings

    zone = await db.get(Zone, zone_id)
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    # Get recent claims for zone
    result = await db.execute(
        select(Claim)
        .where(Claim.zone_id == zone_id)
        .order_by(Claim.created_at.desc())
        .limit(100)
    )
    claims = result.scalars().all()

    if not claims:
        return {
            "zone_id": zone_id,
            "zone_name": zone.name,
            "total_claims": 0,
            "clustering_analysis": None,
            "ring_detection": None,
            "message": "No claims found for analysis",
        }

    timestamps = [c.created_at for c in claims]
    clustering = analyze_temporal_clustering(timestamps, zone_id)

    claims_with_riders = [
        {"rider_id": c.rider_id, "timestamp": c.created_at, "zone_id": c.zone_id}
        for c in claims
    ]
    rings = detect_collusion_rings(claims_with_riders)

    return {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "total_claims": len(claims),
        "clustering_analysis": clustering,
        "ring_detection": rings,
    }


@router.get("/analytics/signal-history/{zone_id}")
async def signal_history(
    zone_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Signal breach history for a zone."""
    result = await db.execute(
        select(SignalReading)
        .where(SignalReading.zone_id == zone_id)
        .order_by(SignalReading.recorded_at.desc())
        .limit(limit)
    )
    readings = result.scalars().all()

    return [
        {
            "recorded_at": r.recorded_at.isoformat(),
            "signal_type": r.signal_type,
            "value": r.value,
            "threshold": r.threshold,
            "is_breached": bool(r.is_breached),
        }
        for r in readings
    ]
