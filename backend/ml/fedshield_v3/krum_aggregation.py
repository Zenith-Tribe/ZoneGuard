"""
krum_aggregation.py — Byzantine Fault-Tolerant Krum Aggregation for FedShield v3.

Background:
  Blanchard et al. (2017) "Machine Learning with Adversaries: Byzantine
  Tolerant Gradient Descent" introduced Krum as a provably Byzantine-robust
  aggregation rule.

  In a federation of n clients where up to f are Byzantine (adversarial):
    • For each client i, compute the sum of squared L2 distances to its
      (n - f - 2) nearest neighbours.
    • Select the client with the LOWEST such score — it is the most
      "central" client and least likely to be an outlier/poison submission.

  Multi-Krum selects the m best clients and averages them (m > 1).

This module:
  1. Implements Krum and Multi-Krum on the dict-based weight format used
     by FederatedAnomalyModel.get_weights().
  2. Provides a KrumAggregationStrategy class that drops in as a replacement
     for FederatedServer.aggregate_weights().
  3. Includes a Byzantine detection report so poisoned nodes are logged.

References:
  Blanchard, P. et al. (2017). arXiv:1703.02757
  El Mhamdi, E. et al. (2018). arXiv:1802.07927 (Bulyan — future work)
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Default assumption: up to 1/3 of clients could be Byzantine
DEFAULT_BYZANTINE_FRACTION = 0.33


# ---------------------------------------------------------------------------
# Weight dict → flat numpy vector helpers
# ---------------------------------------------------------------------------

def _flatten_weights(weights: dict) -> np.ndarray:
    """
    Convert a FederatedAnomalyModel weight dict to a flat 1-D numpy array.

    Order is deterministic: sorted param_keys × sorted feat_names.
    """
    values: list[float] = []
    for param_key in sorted(weights.keys()):
        for feat_name in sorted(weights[param_key].keys()):
            values.append(float(weights[param_key][feat_name]))
    return np.array(values, dtype=np.float64)


def _unflatten_weights(flat: np.ndarray, template: dict) -> dict:
    """
    Restore a flat numpy array back into a weight dict.

    Args:
        flat:     1-D numpy array (same order as _flatten_weights).
        template: A sample weight dict to infer structure from.

    Returns:
        Weight dict matching FederatedAnomalyModel format.
    """
    restored: dict = {}
    idx = 0
    for param_key in sorted(template.keys()):
        restored[param_key] = {}
        for feat_name in sorted(template[param_key].keys()):
            restored[param_key][feat_name] = float(flat[idx])
            idx += 1
    return restored


# ---------------------------------------------------------------------------
# Core Krum algorithm
# ---------------------------------------------------------------------------

def _pairwise_squared_distances(vectors: list[np.ndarray]) -> np.ndarray:
    """
    Compute n×n matrix of squared L2 distances between gradient vectors.
    """
    n = len(vectors)
    D = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        for j in range(i + 1, n):
            diff = vectors[i] - vectors[j]
            d2 = float(np.dot(diff, diff))
            D[i, j] = D[j, i] = d2
    return D


def krum_select(
    client_weights: list[dict],
    byzantine_count: Optional[int] = None,
) -> tuple[dict, int, dict]:
    """
    Krum: select the single most Byzantine-robust client's weights.

    Args:
        client_weights:  List of weight dicts, one per client.
        byzantine_count: Assumed number of Byzantine clients (f).
                         Defaults to floor(n * DEFAULT_BYZANTINE_FRACTION).

    Returns:
        Tuple of:
          • selected_weights (dict)  — weights of the selected client
          • selected_index   (int)   — index in client_weights
          • report           (dict)  — Byzantine detection diagnostics
    """
    n = len(client_weights)
    if n == 0:
        raise ValueError("krum_select: received empty client list.")
    if n == 1:
        return client_weights[0], 0, {"n_clients": 1, "f_assumed": 0, "scores": [0.0]}

    f = byzantine_count if byzantine_count is not None else int(n * DEFAULT_BYZANTINE_FRACTION)
    f = min(f, n - 2)  # Cannot assume more than n-2 Byzantine

    # Neighbours to consider: n - f - 2
    k = max(1, n - f - 2)

    # Flatten all weights to vectors
    vectors = [_flatten_weights(w) for w in client_weights]

    D = _pairwise_squared_distances(vectors)

    # For each client, sum distances to k nearest neighbours
    krum_scores: list[float] = []
    for i in range(n):
        distances_to_others = sorted(D[i, j] for j in range(n) if j != i)
        score = sum(distances_to_others[:k])
        krum_scores.append(score)

    selected_idx = int(np.argmin(krum_scores))

    # Identify likely Byzantine clients (score > median * 3)
    median_score = float(np.median(krum_scores))
    suspected_byzantine = [
        i for i, s in enumerate(krum_scores)
        if s > median_score * 3.0 and i != selected_idx
    ]

    report = {
        "n_clients": n,
        "f_assumed": f,
        "k_neighbours": k,
        "krum_scores": [round(s, 6) for s in krum_scores],
        "selected_index": selected_idx,
        "selected_score": round(krum_scores[selected_idx], 6),
        "suspected_byzantine_indices": suspected_byzantine,
        "n_suspected_byzantine": len(suspected_byzantine),
    }

    if suspected_byzantine:
        logger.warning(
            "Krum: %d suspected Byzantine clients detected: indices %s",
            len(suspected_byzantine),
            suspected_byzantine,
        )

    return client_weights[selected_idx], selected_idx, report


def multi_krum_select(
    client_weights: list[dict],
    sample_counts: list[int],
    m: Optional[int] = None,
    byzantine_count: Optional[int] = None,
) -> tuple[dict, list[int], dict]:
    """
    Multi-Krum: select m clients and average their weights.

    More robust than vanilla Krum while retaining Byzantine tolerance.
    Averages the m clients with lowest Krum scores using sample-weighted
    FedAvg, so honest high-data clients have more influence.

    Args:
        client_weights:  List of weight dicts.
        sample_counts:   Training sample count per client.
        m:               Number of clients to select.
                         Defaults to ceil(n / 2) — majority selection.
        byzantine_count: Assumed Byzantine count (f).

    Returns:
        Tuple of:
          • aggregated_weights (dict)  — FedAvg of m selected clients
          • selected_indices   (list)  — indices of selected clients
          • report             (dict)  — Byzantine detection diagnostics
    """
    n = len(client_weights)
    if n == 0:
        raise ValueError("multi_krum_select: empty client list.")

    f = byzantine_count if byzantine_count is not None else int(n * DEFAULT_BYZANTINE_FRACTION)
    f = min(f, n - 2)
    k = max(1, n - f - 2)

    if m is None:
        m = math.ceil(n / 2)
    m = min(m, n)

    vectors = [_flatten_weights(w) for w in client_weights]
    D = _pairwise_squared_distances(vectors)

    krum_scores: list[float] = []
    for i in range(n):
        distances_to_others = sorted(D[i, j] for j in range(n) if j != i)
        krum_scores.append(sum(distances_to_others[:k]))

    # Select m clients with lowest Krum scores
    ranked_indices = sorted(range(n), key=lambda i: krum_scores[i])
    selected_indices = ranked_indices[:m]
    excluded_indices = ranked_indices[m:]

    # Sample-weighted FedAvg over selected clients
    selected_weights = [client_weights[i] for i in selected_indices]
    selected_counts = [sample_counts[i] for i in selected_indices]
    total = sum(selected_counts)

    if total == 0:
        aggregated = selected_weights[0]
    else:
        template = selected_weights[0]
        param_keys = sorted(template.keys())
        feat_names = {pk: sorted(template[pk].keys()) for pk in param_keys}

        aggregated = {pk: {} for pk in param_keys}
        for pk in param_keys:
            for fn in feat_names[pk]:
                aggregated[pk][fn] = sum(
                    selected_weights[i][pk][fn] * selected_counts[i]
                    for i in range(len(selected_indices))
                ) / total

    # Suspected Byzantine: excluded AND score > median * 2
    all_scores = krum_scores
    median_score = float(np.median(all_scores))
    suspected = [i for i in excluded_indices if all_scores[i] > median_score * 2.0]

    report = {
        "n_clients": n,
        "m_selected": m,
        "f_assumed": f,
        "k_neighbours": k,
        "krum_scores": [round(s, 6) for s in krum_scores],
        "selected_indices": selected_indices,
        "excluded_indices": excluded_indices,
        "suspected_byzantine_indices": suspected,
        "n_suspected_byzantine": len(suspected),
        "selected_total_samples": total,
    }

    if suspected:
        logger.warning(
            "Multi-Krum: %d suspected Byzantine clients excluded: indices %s",
            len(suspected),
            suspected,
        )

    return aggregated, selected_indices, report


# ---------------------------------------------------------------------------
# Drop-in strategy class
# ---------------------------------------------------------------------------

class KrumAggregationStrategy:
    """
    Drop-in replacement for FederatedServer.aggregate_weights().

    Usage:
        strategy = KrumAggregationStrategy(use_multi_krum=True, m=3)
        aggregated, report = strategy.aggregate(client_weights, sample_counts)
    """

    def __init__(
        self,
        use_multi_krum: bool = True,
        m: Optional[int] = None,
        byzantine_count: Optional[int] = None,
    ) -> None:
        self.use_multi_krum = use_multi_krum
        self.m = m
        self.byzantine_count = byzantine_count
        self._reports: list[dict] = []

    def aggregate(
        self,
        client_weights: list[dict],
        sample_counts: list[int],
    ) -> tuple[dict, dict]:
        """
        Aggregate client weights using Krum or Multi-Krum.

        Returns:
            (aggregated_weights, report)
        """
        if len(client_weights) < 2:
            logger.warning("KrumStrategy: only %d client(s) — skipping Krum, returning direct.", len(client_weights))
            report = {"n_clients": len(client_weights), "bypassed": True}
            self._reports.append(report)
            return client_weights[0] if client_weights else {}, report

        if self.use_multi_krum:
            agg, _, report = multi_krum_select(
                client_weights,
                sample_counts,
                m=self.m,
                byzantine_count=self.byzantine_count,
            )
        else:
            agg, _, report = krum_select(
                client_weights,
                byzantine_count=self.byzantine_count,
            )

        self._reports.append(report)
        return agg, report

    @property
    def aggregation_history(self) -> list[dict]:
        """Return all past aggregation reports (for audit logging)."""
        return self._reports
