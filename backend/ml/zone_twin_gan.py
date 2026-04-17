"""
zone_twin_gan.py — ZoneTwin GAN v3: Conditional Wasserstein GAN for Zone Simulation.

Replaces the logistic-curve counterfactual model in zone_twin.py with a
learned cGAN that generates realistic (S1, S2, S3, S4, rider_dark_count)
tuples conditioned on:
  • zone_type       (one-hot: low / medium / high / flood-prone)
  • season          (one-hot: pre_monsoon / monsoon / post_monsoon / winter)
  • day_of_week     (one-hot: Mon-Sun)
  • time_of_day     (one-hot: morning / afternoon / evening / night)
  • signal_history  (48 × 4 continuous values = 192-dim)

Architecture:
  Generator G(z, c) → (S1, S2, S3, S4, dark_count)
    z ~ N(0, I_100)  latent noise
    c = concat(zone_type, season, dow, tod, signal_history)
    Layers: 3 × (Linear → LayerNorm → LeakyReLU) → Linear → Sigmoid

  Critic D(x, c) → R  (no sigmoid — WGAN)
    Layers: 3 × (Linear → LayerNorm → LeakyReLU) → Linear

Training:
  WGAN-GP (Gulrajani et al. 2017): gradient penalty replaces weight clipping.
  λ_gp = 10   (standard Gulrajani value)
  n_critic = 5  (critic updates per generator update)

Applications:
  1. Pre-season simulation — generate 10k scenarios before monsoon
  2. New zone bootstrapping — warm-start a zone with no history
  3. Stress-test reinsurance pool against extreme weather scenarios
  4. Augment FedShield training data with synthetic fraud scenarios

Hackathon note:
  When ZONE_HISTORY_PATH env var is not set, bootstrap_synthetic_history()
  generates 730 days of plausible daily records per zone using ZONE_BASELINES
  from zone_twin.py. This is clearly a simulation — documented below.

Install:
  pip install torch
"""

from __future__ import annotations

import logging
import math
import os
import random
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PyTorch — graceful optional import
# ---------------------------------------------------------------------------

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    _TORCH = True
except ImportError:
    _TORCH = False
    logger.warning(
        "torch not installed. ZoneTwinGAN will use numpy statistical fallback."
    )

# ---------------------------------------------------------------------------
# Condition encoding constants
# ---------------------------------------------------------------------------

ZONE_TYPES = ["low", "medium", "high", "flood-prone"]
SEASONS = ["pre_monsoon", "monsoon", "post_monsoon", "winter"]
DAYS_OF_WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIMES_OF_DAY = ["morning", "afternoon", "evening", "night"]

SIGNAL_HISTORY_STEPS = 48   # 48 × 15min = 12 hours
SIGNAL_DIM = 4               # S1, S2, S3, S4

# Condition vector dimension
COND_DIM = (
    len(ZONE_TYPES)        # 4
    + len(SEASONS)         # 4
    + len(DAYS_OF_WEEK)    # 7
    + len(TIMES_OF_DAY)    # 4
    + SIGNAL_HISTORY_STEPS * SIGNAL_DIM   # 192
)  # = 211

LATENT_DIM = 100
OUTPUT_DIM = 5   # S1, S2, S3, S4, rider_dark_pct


# ---------------------------------------------------------------------------
# One-hot helpers
# ---------------------------------------------------------------------------

def _onehot(value: str, categories: list[str]) -> list[float]:
    vec = [0.0] * len(categories)
    idx = categories.index(value) if value in categories else 0
    vec[idx] = 1.0
    return vec


def encode_condition(
    zone_type: str,
    season: str,
    day_of_week: str,
    time_of_day: str,
    signal_history: Optional[list[list[float]]] = None,
) -> np.ndarray:
    """
    Encode conditioning variables into a flat vector.

    Args:
        zone_type:      One of ZONE_TYPES.
        season:         One of SEASONS.
        day_of_week:    One of DAYS_OF_WEEK.
        time_of_day:    One of TIMES_OF_DAY.
        signal_history: 48 × 4 list of [S1, S2, S3, S4] readings.
                        If None, zero-filled (new zone scenario).

    Returns:
        np.ndarray of shape (COND_DIM,) — float32.
    """
    parts: list[float] = []
    parts += _onehot(zone_type, ZONE_TYPES)
    parts += _onehot(season, SEASONS)
    parts += _onehot(day_of_week, DAYS_OF_WEEK)
    parts += _onehot(time_of_day, TIMES_OF_DAY)

    if signal_history is not None:
        for step in signal_history[-SIGNAL_HISTORY_STEPS:]:
            # Normalise to [0,1]
            parts += [min(1.0, max(0.0, v / 100.0)) for v in step[:SIGNAL_DIM]]
        # Pad if history is shorter than 48 steps
        pad_steps = SIGNAL_HISTORY_STEPS - min(len(signal_history), SIGNAL_HISTORY_STEPS)
        parts += [0.0] * (pad_steps * SIGNAL_DIM)
    else:
        parts += [0.0] * (SIGNAL_HISTORY_STEPS * SIGNAL_DIM)

    return np.array(parts, dtype=np.float32)


# ---------------------------------------------------------------------------
# Generator and Critic (PyTorch path)
# ---------------------------------------------------------------------------

if _TORCH:
    class _Generator(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            in_dim = LATENT_DIM + COND_DIM
            self.net = nn.Sequential(
                nn.Linear(in_dim, 256),
                nn.LayerNorm(256),
                nn.LeakyReLU(0.2),
                nn.Linear(256, 128),
                nn.LayerNorm(128),
                nn.LeakyReLU(0.2),
                nn.Linear(128, 64),
                nn.LayerNorm(64),
                nn.LeakyReLU(0.2),
                nn.Linear(64, OUTPUT_DIM),
                nn.Sigmoid(),   # output in [0, 1]
            )

        def forward(self, z: "torch.Tensor", cond: "torch.Tensor") -> "torch.Tensor":
            x = torch.cat([z, cond], dim=1)
            return self.net(x)

    class _Critic(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            in_dim = OUTPUT_DIM + COND_DIM
            self.net = nn.Sequential(
                nn.Linear(in_dim, 256),
                nn.LayerNorm(256),
                nn.LeakyReLU(0.2),
                nn.Linear(256, 128),
                nn.LayerNorm(128),
                nn.LeakyReLU(0.2),
                nn.Linear(128, 64),
                nn.LayerNorm(64),
                nn.LeakyReLU(0.2),
                nn.Linear(64, 1),
                # No sigmoid — WGAN
            )

        def forward(self, x: "torch.Tensor", cond: "torch.Tensor") -> "torch.Tensor":
            inp = torch.cat([x, cond], dim=1)
            return self.net(inp)


# ---------------------------------------------------------------------------
# Synthetic history bootstrap (no torch required)
# ---------------------------------------------------------------------------

def bootstrap_synthetic_history(
    zone_id: str,
    n_days: int = 730,
    seed: Optional[int] = None,
) -> list[dict]:
    """
    Generate n_days of daily synthetic signal records for a zone.

    Uses ZONE_BASELINES from zone_twin.py as statistical priors.
    Output records match the training data format for ZoneTwinGAN.fit().

    THIS IS SIMULATED DATA — clearly marked in record metadata.
    For production, replace with real QuadSignal historical data.
    """
    # Import here to avoid circular dependency
    try:
        from ml.zone_twin import ZONE_BASELINES
        baseline = ZONE_BASELINES.get(zone_id, ZONE_BASELINES.get("hsr", {}))
    except ImportError:
        baseline = {
            "avg_rainfall_mm": 25, "avg_mobility": 88, "avg_inactivity_pct": 8,
            "disruption_rainfall_threshold": 55, "flood_correlation": 0.75,
        }

    rng = np.random.default_rng(seed if seed is not None else hash(zone_id) % (2**31))
    records: list[dict] = []

    avg_rain = baseline.get("avg_rainfall_mm", 25)
    avg_mob = baseline.get("avg_mobility", 88)
    avg_inact = baseline.get("avg_inactivity_pct", 8)
    flood_corr = baseline.get("flood_correlation", 0.7)

    for day in range(n_days):
        # Seasonal index (day 0 = Jan 1)
        day_of_year = day % 365
        # Monsoon: June–September ≈ days 150–270
        is_monsoon = 150 <= day_of_year <= 270
        season_mult = 2.5 if is_monsoon else 0.6

        rainfall = float(rng.exponential(avg_rain * season_mult))
        mobility = float(np.clip(avg_mob + rng.normal(0, 5), 30, 100))
        inactivity = float(np.clip(
            avg_inact * (1 + flood_corr * (rainfall / max(baseline.get("disruption_rainfall_threshold", 55), 1))),
            0, 90,
        ))

        season = (
            "monsoon" if is_monsoon else
            "pre_monsoon" if day_of_year < 150 else
            "post_monsoon" if day_of_year < 330 else
            "winter"
        )

        records.append({
            "zone_id": zone_id,
            "day_index": day,
            "season": season,
            "day_of_week": DAYS_OF_WEEK[day % 7],
            "s1_rainfall": round(rainfall, 2),
            "s2_mobility": round(mobility, 2),
            "s3_order_pct": round(float(np.clip(100 - inactivity * 0.8, 10, 100)), 2),
            "s4_inactivity_pct": round(inactivity, 2),
            "rider_dark_pct": round(float(np.clip(inactivity * 1.1, 0, 95)), 2),
            "synthetic": True,  # clearly marked
        })

    return records


# ---------------------------------------------------------------------------
# ZoneTwinGAN — public class
# ---------------------------------------------------------------------------

class ZoneTwinGAN:
    """
    Conditional WGAN for per-zone synthetic scenario generation.

    Usage:
        gan = ZoneTwinGAN(zone_id="bellandur")
        # Training:
        history = gan.fit(records, epochs=500)
        # Inference:
        scenarios = gan.generate(n=1000, zone_type="flood-prone",
                                 season="monsoon", day_of_week="wed",
                                 time_of_day="evening")
        # Nowcast:
        forecast = gan.nowcast_72h(signal_history=[...])
    """

    LAMBDA_GP = 10.0
    N_CRITIC = 5

    def __init__(
        self,
        zone_id: str,
        latent_dim: int = LATENT_DIM,
        lr: float = 1e-4,
        device: str = "cpu",
    ) -> None:
        self.zone_id = zone_id
        self.latent_dim = latent_dim
        self.is_trained = False
        self._training_loss: list[dict] = []

        if _TORCH:
            self._device = torch.device(device)
            self._G = _Generator().to(self._device)
            self._D = _Critic().to(self._device)
            self._opt_G = optim.Adam(self._G.parameters(), lr=lr, betas=(0.0, 0.9))
            self._opt_D = optim.Adam(self._D.parameters(), lr=lr, betas=(0.0, 0.9))
            logger.info("ZoneTwinGAN[%s]: PyTorch WGAN-GP on %s.", zone_id, device)
        else:
            # Store statistics for numpy fallback
            self._stats: dict = {}
            logger.info("ZoneTwinGAN[%s]: NumPy statistical fallback.", zone_id)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def fit(
        self,
        records: list[dict],
        epochs: int = 500,
        batch_size: int = 64,
        log_every: int = 50,
    ) -> list[dict]:
        """
        Train the cGAN on historical zone records.

        Args:
            records:    List of record dicts from bootstrap_synthetic_history()
                        or real QuadSignal history.
            epochs:     Training epochs.
            batch_size: Mini-batch size.
            log_every:  Log loss every N epochs.

        Returns:
            Training loss history.
        """
        if not records:
            logger.warning("ZoneTwinGAN[%s]: no records to train on.", self.zone_id)
            return []

        if not _TORCH:
            return self._fit_numpy(records)

        # Build tensors from records
        X, C = self._records_to_tensors(records)
        n = X.shape[0]

        for epoch in range(1, epochs + 1):
            # --- Critic updates (N_CRITIC per generator step) ---
            d_losses = []
            for _ in range(self.N_CRITIC):
                idx = torch.randint(0, n, (min(batch_size, n),))
                x_real = X[idx].to(self._device)
                c_real = C[idx].to(self._device)

                z = torch.randn(len(idx), self.latent_dim).to(self._device)
                x_fake = self._G(z, c_real).detach()

                # WGAN-GP critic loss
                d_real = self._D(x_real, c_real).mean()
                d_fake = self._D(x_fake, c_real).mean()
                gp = self._gradient_penalty(x_real, x_fake, c_real)
                d_loss = d_fake - d_real + self.LAMBDA_GP * gp

                self._opt_D.zero_grad()
                d_loss.backward()
                self._opt_D.step()
                d_losses.append(d_loss.item())

            # --- Generator update ---
            idx = torch.randint(0, n, (min(batch_size, n),))
            c_batch = C[idx].to(self._device)
            z = torch.randn(len(idx), self.latent_dim).to(self._device)
            x_fake = self._G(z, c_batch)
            g_loss = -self._D(x_fake, c_batch).mean()

            self._opt_G.zero_grad()
            g_loss.backward()
            self._opt_G.step()

            if epoch % log_every == 0:
                entry = {
                    "epoch": epoch,
                    "d_loss": round(float(np.mean(d_losses)), 4),
                    "g_loss": round(g_loss.item(), 4),
                }
                self._training_loss.append(entry)
                logger.debug("ZoneTwinGAN[%s] epoch %d: %s", self.zone_id, epoch, entry)

        self.is_trained = True
        logger.info(
            "ZoneTwinGAN[%s]: training complete (%d epochs, %d records).",
            self.zone_id, epochs, len(records),
        )
        return self._training_loss

    def _gradient_penalty(
        self,
        x_real: "torch.Tensor",
        x_fake: "torch.Tensor",
        cond: "torch.Tensor",
    ) -> "torch.Tensor":
        """WGAN-GP gradient penalty (Gulrajani et al. 2017)."""
        alpha = torch.rand(x_real.size(0), 1).to(self._device)
        interpolated = (alpha * x_real + (1 - alpha) * x_fake).requires_grad_(True)
        d_interp = self._D(interpolated, cond)
        gradients = torch.autograd.grad(
            outputs=d_interp,
            inputs=interpolated,
            grad_outputs=torch.ones_like(d_interp),
            create_graph=True,
            retain_graph=True,
        )[0]
        grad_norm = gradients.view(gradients.size(0), -1).norm(2, dim=1)
        return ((grad_norm - 1) ** 2).mean()

    def _records_to_tensors(
        self, records: list[dict]
    ) -> tuple["torch.Tensor", "torch.Tensor"]:
        """Convert records to (output_tensor, condition_tensor)."""
        X_list, C_list = [], []
        for r in records:
            # Output: [s1_norm, s2_norm, s3_norm, s4_norm, dark_pct_norm]
            x = [
                min(1.0, r.get("s1_rainfall", 0) / 100.0),
                min(1.0, r.get("s2_mobility", 100) / 100.0),
                min(1.0, r.get("s3_order_pct", 100) / 100.0),
                min(1.0, r.get("s4_inactivity_pct", 0) / 100.0),
                min(1.0, r.get("rider_dark_pct", 0) / 100.0),
            ]
            X_list.append(x)

            # Condition
            c = encode_condition(
                zone_type=r.get("zone_type", "medium"),
                season=r.get("season", "monsoon"),
                day_of_week=r.get("day_of_week", "mon"),
                time_of_day=r.get("time_of_day", "morning"),
                signal_history=r.get("signal_history", None),
            )
            C_list.append(c)

        X = torch.tensor(X_list, dtype=torch.float32)
        C = torch.tensor(np.array(C_list), dtype=torch.float32)
        return X, C

    def _fit_numpy(self, records: list[dict]) -> list[dict]:
        """Store mean/std statistics as numpy fallback when torch unavailable."""
        arr = np.array([
            [r.get("s1_rainfall", 0), r.get("s2_mobility", 100),
             r.get("s3_order_pct", 100), r.get("s4_inactivity_pct", 0),
             r.get("rider_dark_pct", 0)]
            for r in records
        ], dtype=np.float32)
        self._stats = {
            "mean": arr.mean(axis=0).tolist(),
            "std": np.maximum(arr.std(axis=0), 1e-6).tolist(),
        }
        self.is_trained = True
        return [{"epoch": 0, "method": "numpy_stats"}]

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def generate(
        self,
        n: int = 1000,
        zone_type: str = "medium",
        season: str = "monsoon",
        day_of_week: str = "mon",
        time_of_day: str = "morning",
        signal_history: Optional[list[list[float]]] = None,
    ) -> list[dict]:
        """
        Generate n synthetic (S1, S2, S3, S4, rider_dark_pct) tuples.

        Returns:
            List of n dicts with keys:
              s1_rainfall, s2_mobility, s3_order_pct, s4_inactivity_pct,
              rider_dark_pct, zone_type, season, day_of_week, time_of_day,
              synthetic=True
        """
        cond_vec = encode_condition(zone_type, season, day_of_week, time_of_day, signal_history)

        if _TORCH and self.is_trained:
            return self._generate_torch(n, cond_vec, zone_type, season, day_of_week, time_of_day)
        else:
            return self._generate_numpy(n, zone_type, season, day_of_week, time_of_day)

    def _generate_torch(
        self, n: int, cond_vec: np.ndarray,
        zone_type: str, season: str, day_of_week: str, time_of_day: str,
    ) -> list[dict]:
        self._G.eval()
        with torch.no_grad():
            z = torch.randn(n, self.latent_dim).to(self._device)
            c = torch.tensor(cond_vec, dtype=torch.float32).unsqueeze(0).repeat(n, 1).to(self._device)
            out = self._G(z, c).cpu().numpy()

        results = []
        for row in out:
            results.append({
                "s1_rainfall":       round(float(row[0]) * 100, 2),
                "s2_mobility":       round(float(row[1]) * 100, 2),
                "s3_order_pct":      round(float(row[2]) * 100, 2),
                "s4_inactivity_pct": round(float(row[3]) * 100, 2),
                "rider_dark_pct":    round(float(row[4]) * 100, 2),
                "zone_type": zone_type, "season": season,
                "day_of_week": day_of_week, "time_of_day": time_of_day,
                "synthetic": True, "generator": "cgan_wgan_gp",
            })
        return results

    def _generate_numpy(
        self, n: int,
        zone_type: str, season: str, day_of_week: str, time_of_day: str,
    ) -> list[dict]:
        """Statistical sampling fallback."""
        if not self._stats:
            # Untrained fallback
            mean = [30, 80, 70, 15, 12]
            std = [20, 10, 20, 10, 8]
        else:
            mean = self._stats["mean"]
            std = self._stats["std"]

        rng = np.random.default_rng()
        samples = rng.normal(mean, std, size=(n, OUTPUT_DIM))
        samples = np.clip(samples, 0, 100)

        results = []
        for row in samples:
            results.append({
                "s1_rainfall":       round(float(row[0]), 2),
                "s2_mobility":       round(float(row[1]), 2),
                "s3_order_pct":      round(float(row[2]), 2),
                "s4_inactivity_pct": round(float(row[3]), 2),
                "rider_dark_pct":    round(float(row[4]), 2),
                "zone_type": zone_type, "season": season,
                "day_of_week": day_of_week, "time_of_day": time_of_day,
                "synthetic": True, "generator": "numpy_fallback",
            })
        return results

    def nowcast_72h(
        self,
        signal_history: list[list[float]],
        zone_type: str = "medium",
        season: str = "monsoon",
        n_paths: int = 200,
    ) -> dict:
        """
        Generate 72-hour probabilistic forecast (p10/p50/p90) using
        iterative GAN rollouts.

        Each 15-minute step generates a new (S1–S4) tuple conditioned on
        the rolling history window. Repeats n_paths times to build
        percentile bands.

        Args:
            signal_history: Recent 48-step (12h) signal history [[S1,S2,S3,S4], ...]
            zone_type:      Zone classification.
            season:         Current season.
            n_paths:        Monte Carlo paths for percentile estimation.

        Returns:
            Dict with 288 steps (72h × 4 per hour) × p10/p50/p90 per signal.
        """
        STEPS_72H = 288  # 72h × 4 per hour

        all_paths: list[list[list[float]]] = []

        for _ in range(n_paths):
            path: list[list[float]] = []
            history = list(signal_history[-SIGNAL_HISTORY_STEPS:])

            for step_idx in range(STEPS_72H):
                # Time of day from step index
                hour = (step_idx // 4) % 24
                tod = (
                    "morning" if 6 <= hour < 12 else
                    "afternoon" if 12 <= hour < 17 else
                    "evening" if 17 <= hour < 21 else
                    "night"
                )
                dow = DAYS_OF_WEEK[step_idx // (4 * 24) % 7]

                scenario = self.generate(
                    n=1, zone_type=zone_type, season=season,
                    day_of_week=dow, time_of_day=tod,
                    signal_history=history,
                )[0]

                step_vals = [
                    scenario["s1_rainfall"],
                    scenario["s2_mobility"],
                    scenario["s3_order_pct"],
                    scenario["s4_inactivity_pct"],
                ]
                path.append(step_vals)
                # Rolling update of history
                history.append(step_vals)
                if len(history) > SIGNAL_HISTORY_STEPS:
                    history.pop(0)

            all_paths.append(path)

        # Compute percentiles across paths
        paths_arr = np.array(all_paths)  # (n_paths, STEPS_72H, 4)
        p10 = np.percentile(paths_arr, 10, axis=0).tolist()
        p50 = np.percentile(paths_arr, 50, axis=0).tolist()
        p90 = np.percentile(paths_arr, 90, axis=0).tolist()

        return {
            "zone_id": self.zone_id,
            "horizon_hours": 72,
            "steps": STEPS_72H,
            "step_interval_minutes": 15,
            "n_monte_carlo_paths": n_paths,
            "percentiles": {
                "p10": p10,
                "p50": p50,
                "p90": p90,
            },
            "signal_labels": ["S1_rainfall", "S2_mobility", "S3_order_pct", "S4_inactivity_pct"],
            "synthetic": True,
        }

    # ------------------------------------------------------------------
    # Stress test & reinsurance pool utility
    # ------------------------------------------------------------------

    def stress_test_reinsurance(
        self,
        n_scenarios: int = 5000,
        extreme_season: str = "monsoon",
        zone_type: str = "flood-prone",
    ) -> dict:
        """
        Generate extreme weather scenarios for reinsurance pool stress-testing.

        Returns summary statistics on worst-case rider_dark_pct distributions.
        """
        scenarios = self.generate(
            n=n_scenarios,
            zone_type=zone_type,
            season=extreme_season,
            day_of_week="mon",
            time_of_day="evening",
        )

        dark_pcts = [s["rider_dark_pct"] for s in scenarios]
        arr = np.array(dark_pcts)

        return {
            "zone_id": self.zone_id,
            "n_scenarios": n_scenarios,
            "zone_type": zone_type,
            "season": extreme_season,
            "rider_dark_pct": {
                "mean": round(float(arr.mean()), 2),
                "p50": round(float(np.percentile(arr, 50)), 2),
                "p90": round(float(np.percentile(arr, 90)), 2),
                "p95": round(float(np.percentile(arr, 95)), 2),
                "p99": round(float(np.percentile(arr, 99)), 2),
                "max": round(float(arr.max()), 2),
            },
            "extreme_event_rate": round(float((arr > 70).mean()), 4),
            "synthetic": True,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        if not _TORCH:
            logger.warning("save: torch not available, skipping.")
            return
        torch.save({
            "generator": self._G.state_dict(),
            "critic": self._D.state_dict(),
            "zone_id": self.zone_id,
            "training_loss": self._training_loss,
        }, path)
        logger.info("ZoneTwinGAN[%s]: saved to %s.", self.zone_id, path)

    def load(self, path: str) -> None:
        if not _TORCH:
            return
        state = torch.load(path, map_location=self._device)
        self._G.load_state_dict(state["generator"])
        self._D.load_state_dict(state["critic"])
        self._training_loss = state.get("training_loss", [])
        self.is_trained = True
        logger.info("ZoneTwinGAN[%s]: loaded from %s.", self.zone_id, path)
