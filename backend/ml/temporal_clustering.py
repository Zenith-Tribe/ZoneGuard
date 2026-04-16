"""
Temporal Clustering — collusion ring detection for parametric insurance fraud.

Genuine disruptions produce Poisson-distributed claim arrival times.
Coordinated fake claims produce tight temporal spikes (collusion rings).

Two pure-function analyses:
1. analyze_temporal_clustering: buckets claim timestamps, computes Poisson
   z-scores and chi-squared goodness-of-fit to flag suspicious spikes.
2. detect_collusion_rings: identifies rider groups whose claims repeatedly
   co-occur within short time windows across multiple events.

No DB dependencies — numpy only (scipy optional for exact p-values).
"""

from datetime import datetime, timedelta
from collections import defaultdict
from itertools import combinations
import math

try:
    from scipy.stats import chi2 as _chi2_dist

    def _chi2_sf(x: float, k: int) -> float:
        """Survival function P(X > x) for chi-squared with k dof."""
        return float(_chi2_dist.sf(x, k))

except ImportError:
    def _chi2_sf(x: float, k: int) -> float:
        """Approximate chi-squared survival function when scipy is unavailable.

        Uses the Wilson-Hilferty normal approximation:
            Z = ( (X/k)^(1/3) - (1 - 2/(9k)) ) / sqrt(2/(9k))
        then P(X > x) ≈ 1 - Φ(Z).
        """
        if k <= 0 or x <= 0:
            return 1.0
        # Wilson-Hilferty transformation
        a = 2.0 / (9.0 * k)
        z = ((x / k) ** (1.0 / 3.0) - (1.0 - a)) / math.sqrt(a)
        # Standard normal CDF approximation (Abramowitz & Stegun 26.2.17)
        return 1.0 - _norm_cdf(z)


def _norm_cdf(z: float) -> float:
    """Approximate standard normal CDF using the logistic approximation."""
    return 1.0 / (1.0 + math.exp(-1.7155277699214135 * z))


def analyze_temporal_clustering(
    claim_timestamps: list[datetime],
    zone_id: str,
    window_minutes: int = 5,
    min_cluster_size: int = 3,
    poisson_threshold: float = 3.0,
) -> dict:
    """Analyze claim timestamps for suspicious temporal clustering.

    Buckets timestamps into fixed-width windows, fits a Poisson model,
    and flags windows whose z-scores exceed the threshold.

    Args:
        claim_timestamps: list of claim creation datetimes.
        zone_id: zone identifier for labeling.
        window_minutes: bucket width in minutes.
        min_cluster_size: minimum claims in a window to form a cluster.
        poisson_threshold: z-score above which a bucket is a "spike".

    Returns:
        dict with clustering_coefficient, is_suspicious, detected_clusters,
        poisson_analysis, and recommendation.
    """
    safe_defaults = {
        "zone_id": zone_id,
        "total_claims": len(claim_timestamps),
        "window_minutes": window_minutes,
        "clustering_coefficient": 0.0,
        "is_suspicious": False,
        "detected_clusters": [],
        "poisson_analysis": {
            "expected_rate": 0.0,
            "observed_max_rate": 0.0,
            "chi_squared_stat": 0.0,
            "p_value": 1.0,
        },
        "recommendation": "normal",
    }

    if len(claim_timestamps) < 2:
        return safe_defaults

    # Sort timestamps
    sorted_ts = sorted(claim_timestamps)
    t_min = sorted_ts[0]
    t_max = sorted_ts[-1]

    # Build buckets covering the full time range
    total_span = (t_max - t_min).total_seconds()
    window_seconds = window_minutes * 60

    # Use a minimum number of buckets so that claims crammed into a tiny
    # time span are compared against what a healthy spread would look like.
    # At least max(len/2, 5) buckets — if all claims land in one bucket
    # the empty buckets drive lambda down and produce a clear spike.
    span_buckets = math.ceil(total_span / window_seconds) + 1 if total_span > 0 else 1
    min_buckets = max(5, len(claim_timestamps) // 2)
    num_buckets = max(span_buckets, min_buckets)

    # Count claims per bucket
    bucket_counts = [0] * num_buckets
    for ts in sorted_ts:
        offset = (ts - t_min).total_seconds()
        idx = min(int(offset / window_seconds), num_buckets - 1)
        bucket_counts[idx] += 1

    # Poisson rate (lambda): mean claims per bucket
    lam = sum(bucket_counts) / num_buckets
    observed_max = max(bucket_counts)

    # Z-scores per bucket
    sqrt_lam = math.sqrt(lam) if lam > 0 else 1.0
    z_scores = [(c - lam) / sqrt_lam for c in bucket_counts]

    # Chi-squared goodness-of-fit
    expected = lam  # expected count per bucket under Poisson
    if expected > 0:
        chi2_stat = sum((c - expected) ** 2 / expected for c in bucket_counts)
    else:
        chi2_stat = 0.0

    dof = max(1, num_buckets - 1)
    p_value = _chi2_sf(chi2_stat, dof)

    # Clustering coefficient: fraction of claims in spike buckets
    spike_claims = sum(
        c for c, z in zip(bucket_counts, z_scores) if z > poisson_threshold
    )
    clustering_coeff = spike_claims / len(claim_timestamps) if claim_timestamps else 0.0

    # Detect contiguous clusters
    detected_clusters = []
    i = 0
    while i < num_buckets:
        if bucket_counts[i] >= min_cluster_size:
            # Start of a cluster — extend while adjacent buckets also qualify
            cluster_start_idx = i
            cluster_claim_count = 0
            max_z = z_scores[i]
            while i < num_buckets and bucket_counts[i] >= min_cluster_size:
                cluster_claim_count += bucket_counts[i]
                max_z = max(max_z, z_scores[i])
                i += 1
            cluster_end_idx = i - 1

            window_start = t_min + timedelta(seconds=cluster_start_idx * window_seconds)
            window_end = t_min + timedelta(seconds=(cluster_end_idx + 1) * window_seconds)

            detected_clusters.append({
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "claim_count": cluster_claim_count,
                "z_score": round(max_z, 3),
            })
        else:
            i += 1

    # Suspicion logic
    is_suspicious = clustering_coeff > 0.6 or p_value < 0.01

    # Recommendation
    if is_suspicious:
        recommendation = "investigate"
    elif clustering_coeff > 0.3 or p_value < 0.05:
        recommendation = "monitor"
    else:
        recommendation = "normal"

    return {
        "zone_id": zone_id,
        "total_claims": len(claim_timestamps),
        "window_minutes": window_minutes,
        "clustering_coefficient": round(clustering_coeff, 4),
        "is_suspicious": is_suspicious,
        "detected_clusters": detected_clusters,
        "poisson_analysis": {
            "expected_rate": round(lam, 4),
            "observed_max_rate": float(observed_max),
            "chi_squared_stat": round(chi2_stat, 4),
            "p_value": round(p_value, 6),
        },
        "recommendation": recommendation,
    }


def detect_collusion_rings(
    claims_with_riders: list[dict],
    time_window_minutes: int = 10,
    min_co_occurrences: int = 2,
) -> dict:
    """Detect groups of riders whose claim timestamps repeatedly co-occur.

    For every pair of riders, counts how many times their claims fall within
    `time_window_minutes` of each other. Pairs exceeding `min_co_occurrences`
    are merged into rings via connected-component grouping.

    Args:
        claims_with_riders: list of dicts with keys rider_id, timestamp, zone_id.
        time_window_minutes: maximum time gap (minutes) for two claims to be
            considered co-occurring.
        min_co_occurrences: minimum co-occurrence count to flag a pair.

    Returns:
        dict with suspected_rings, total_riders_analyzed, rings_detected.
    """
    if not claims_with_riders:
        return {
            "suspected_rings": [],
            "total_riders_analyzed": 0,
            "rings_detected": 0,
        }

    # Group timestamps by rider
    rider_timestamps: dict[str, list[datetime]] = defaultdict(list)
    for claim in claims_with_riders:
        rider_timestamps[claim["rider_id"]].append(claim["timestamp"])

    # Sort each rider's timestamps
    for rid in rider_timestamps:
        rider_timestamps[rid].sort()

    rider_ids = list(rider_timestamps.keys())
    window_td = timedelta(minutes=time_window_minutes)

    # Count pairwise co-occurrences
    pair_co_occurrences: dict[tuple[str, str], list[datetime]] = defaultdict(list)

    for r1, r2 in combinations(rider_ids, 2):
        ts1 = rider_timestamps[r1]
        ts2 = rider_timestamps[r2]
        window_secs = window_td.total_seconds()
        # Two-pointer sweep for co-occurring timestamps
        j_start = 0
        for t1 in ts1:
            # Advance lower bound past entries too far in the past
            while j_start < len(ts2) and (t1 - ts2[j_start]).total_seconds() > window_secs:
                j_start += 1
            for j in range(j_start, len(ts2)):
                diff = abs((t1 - ts2[j]).total_seconds())
                if diff <= window_secs:
                    midpoint = t1 + (ts2[j] - t1) / 2
                    pair_co_occurrences[(r1, r2)].append(midpoint)
                    break  # count each t1 at most once per pair
                elif ts2[j] > t1 + window_td:
                    break

    # Filter pairs meeting the threshold
    flagged_pairs: dict[tuple[str, str], list[datetime]] = {}
    for pair, timestamps in pair_co_occurrences.items():
        if len(timestamps) >= min_co_occurrences:
            flagged_pairs[pair] = timestamps

    # Merge flagged pairs into connected components (rings)
    if not flagged_pairs:
        return {
            "suspected_rings": [],
            "total_riders_analyzed": len(rider_ids),
            "rings_detected": 0,
        }

    # Union-Find for connected components
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r1, r2 in flagged_pairs:
        parent.setdefault(r1, r1)
        parent.setdefault(r2, r2)
        union(r1, r2)

    # Group by component
    components: dict[str, set[str]] = defaultdict(set)
    for rid in parent:
        components[find(rid)].add(rid)

    # Build result rings
    suspected_rings = []
    for members in components.values():
        if len(members) < 2:
            continue
        # Collect all co-occurrence timestamps for this ring
        ring_timestamps: list[datetime] = []
        for pair, ts_list in flagged_pairs.items():
            if pair[0] in members or pair[1] in members:
                ring_timestamps.extend(ts_list)
        # Deduplicate and sort
        ring_timestamps = sorted(set(ring_timestamps))

        # Total co-occurrences among ring members
        co_count = sum(
            len(ts_list)
            for pair, ts_list in flagged_pairs.items()
            if pair[0] in members and pair[1] in members
        )

        suspected_rings.append({
            "rider_ids": sorted(members),
            "co_occurrence_count": co_count,
            "timestamps": [t.isoformat() for t in ring_timestamps],
        })

    # Sort rings by co-occurrence count descending
    suspected_rings.sort(key=lambda r: r["co_occurrence_count"], reverse=True)

    return {
        "suspected_rings": suspected_rings,
        "total_riders_analyzed": len(rider_ids),
        "rings_detected": len(suspected_rings),
    }
