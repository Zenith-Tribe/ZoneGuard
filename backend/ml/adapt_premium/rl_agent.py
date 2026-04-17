"""
rl_agent.py — PPO Agent for AdaptPremium Zone Premium Pricing.

Uses Stable Baselines3 PPO to train a weekly premium adjustment policy.

Key design decisions:
  1. Shadow mode — during initial deployment the agent runs alongside the
     existing XGBoost rule-based scorer. Actions are logged but NOT applied
     to live premiums until ADAPT_PREMIUM_SHADOW_MODE=false.
  2. Personalised pricing — after zone-level PPO decision, RiderPricingEngine
     applies within-band personalisation.
  3. GAN rollout training — when GAN_ENABLED=true, ZoneTwinGAN provides
     richer counterfactual scenarios during training (transfer learning between
     AdaptPremium and ZoneTwin).
  4. Model persistence — weights saved to PPO_MODEL_PATH env var path.

Environment variables:
  ADAPT_PREMIUM_SHADOW_MODE=true    — log decisions but don't apply (default)
  PPO_MODEL_PATH=/models/adapt_ppo  — model save/load path
  GAN_ENABLED=true                  — use ZoneTwinGAN rollouts in env

Install:
  pip install stable-baselines3 gymnasium
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

SHADOW_MODE = os.getenv("ADAPT_PREMIUM_SHADOW_MODE", "true").lower() == "true"
PPO_MODEL_PATH = os.getenv("PPO_MODEL_PATH", "/models/adapt_ppo")

# ---------------------------------------------------------------------------
# Stable Baselines3 — graceful import
# ---------------------------------------------------------------------------

try:
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env
    from stable_baselines3.common.vec_env import DummyVecEnv
    _SB3 = True
except ImportError:
    PPO = None
    _SB3 = False
    logger.warning(
        "stable-baselines3 not installed. AdaptPremiumAgent will use "
        "rule-based fallback policy."
    )


# ---------------------------------------------------------------------------
# AdaptPremiumAgent
# ---------------------------------------------------------------------------

class AdaptPremiumAgent:
    """
    PPO-based weekly premium adjustment agent.

    Usage:
        agent = AdaptPremiumAgent(zone_id="bellandur", zone_type="flood-prone")
        agent.train(total_timesteps=200_000)
        action, meta = agent.predict_action(state_features)
        recommendation = agent.get_recommendation(zone_data, rider_data)
    """

    PREMIUM_DELTAS = [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]

    def __init__(
        self,
        zone_id: str = "bellandur",
        zone_type: str = "flood-prone",
        initial_premium: float = 139.0,
        initial_riders: int = 150,
    ) -> None:
        self.zone_id = zone_id
        self.zone_type = zone_type
        self.initial_premium = initial_premium
        self.is_trained = False
        self._ppo_model = None
        self._env = None
        self._decision_log: list[dict] = []

        # Lazy-build env
        self._initial_riders = initial_riders

    def _build_env(self) -> object:
        """Construct and validate the Gym environment."""
        from ml.adapt_premium.zone_env import ZonePremiumEnv
        env = ZonePremiumEnv(
            zone_id=self.zone_id,
            zone_type=self.zone_type,
            initial_premium=self.initial_premium,
            initial_riders=self._initial_riders,
            use_gan_rollouts=os.getenv("GAN_ENABLED", "false").lower() == "true",
        )
        return env

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(
        self,
        total_timesteps: int = 200_000,
        n_envs: int = 4,
        learning_rate: float = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        verbose: int = 1,
    ) -> dict:
        """
        Train the PPO agent.

        Args:
            total_timesteps: Total environment steps for training.
            n_envs:          Parallel environments (DummyVecEnv).
            learning_rate:   Adam learning rate.
            n_steps:         Steps per rollout buffer.
            batch_size:      Mini-batch size for PPO updates.
            n_epochs:        PPO epochs per update.
            verbose:         Verbosity (0=silent, 1=info).

        Returns:
            Training summary dict.
        """
        if not _SB3:
            logger.error("stable-baselines3 not installed. Cannot train PPO agent.")
            return {"error": "sb3_not_installed"}

        logger.info(
            "AdaptPremiumAgent[%s]: starting PPO training (%d timesteps).",
            self.zone_id, total_timesteps,
        )

        def make_env():
            return self._build_env()

        vec_env = DummyVecEnv([make_env] * n_envs)

        self._ppo_model = PPO(
            policy="MlpPolicy",
            env=vec_env,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            n_epochs=n_epochs,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,  # entropy bonus for exploration
            verbose=verbose,
            tensorboard_log=os.path.join(PPO_MODEL_PATH, "tb_logs"),
        )

        self._ppo_model.learn(total_timesteps=total_timesteps)
        self.is_trained = True

        # Save model
        self.save(PPO_MODEL_PATH)

        logger.info(
            "AdaptPremiumAgent[%s]: training complete. Saved to %s.",
            self.zone_id, PPO_MODEL_PATH,
        )

        return {
            "zone_id": self.zone_id,
            "total_timesteps": total_timesteps,
            "n_envs": n_envs,
            "model_path": PPO_MODEL_PATH,
            "status": "trained",
        }

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_action(
        self,
        state: np.ndarray,
        deterministic: bool = True,
    ) -> tuple[int, dict]:
        """
        Predict the best premium adjustment action for a given state.

        Args:
            state:        15-dim state vector (see zone_env.py).
            deterministic: Use deterministic policy (no exploration noise).

        Returns:
            (action_index, metadata)
        """
        if self._ppo_model is not None and self.is_trained:
            obs = state.reshape(1, -1)
            action, _ = self._ppo_model.predict(obs, deterministic=deterministic)
            action_idx = int(action[0])
        else:
            # Fallback: loss-ratio-guided heuristic
            action_idx = self._heuristic_action(state)

        delta_pct = self.PREMIUM_DELTAS[action_idx]
        meta = {
            "action_index": action_idx,
            "delta_pct": round(delta_pct * 100, 1),
            "delta_label": f"{'+' if delta_pct > 0 else ''}{delta_pct*100:.0f}%",
            "model": "ppo" if (self.is_trained and self._ppo_model) else "heuristic_fallback",
            "shadow_mode": SHADOW_MODE,
        }

        return action_idx, meta

    def _heuristic_action(self, state: np.ndarray) -> int:
        """
        Simple loss-ratio heuristic when PPO is not yet trained.

        If LR > 0.75 → increase premium (+10%)
        If LR < 0.50 → decrease premium (-10%)
        Else → hold
        """
        lr = float(state[3]) if len(state) > 3 else 0.65
        if lr > 0.75:
            return 5   # +10%
        elif lr < 0.50:
            return 1   # -10%
        return 3       # 0%

    def get_recommendation(
        self,
        zone_data: dict,
        rider_tenure_weeks: int = 0,
        loss_ratios_4w: Optional[list[float]] = None,
        churn_rate: float = 0.05,
        enrolled_riders: int = 100,
        imd_seasonal: float = 0.5,
        pool_funded_ratio: float = 1.2,
    ) -> dict:
        """
        High-level interface: given zone data, return premium recommendation.

        Compatible with zone_risk_scorer.calculate_zone_premium() signature
        for shadow mode side-by-side comparison.

        Args:
            zone_data:          Dict from existing zone_risk_scorer interface.
            rider_tenure_weeks: Rider's tenure (for personalisation).
            loss_ratios_4w:     4-week loss ratio history.
            churn_rate:         Current weekly churn rate.
            enrolled_riders:    Current enrolled rider count.
            imd_seasonal:       IMD 90-day forecast severity.
            pool_funded_ratio:  Pool balance / expected annual claims.

        Returns:
            Recommendation dict with action, premium, delta_pct, reasoning.
        """
        from ml.zone_risk_scorer import calculate_zone_premium

        # Build state vector from zone_data
        risk_result = calculate_zone_premium(zone_data, rider_tenure_weeks)
        risk_score_norm = risk_result["risk_score"] / 100.0
        current_premium = float(risk_result["premium"])

        if loss_ratios_4w is None:
            loss_ratios_4w = [0.65, 0.65, 0.65, 0.65]
        while len(loss_ratios_4w) < 4:
            loss_ratios_4w = [0.65] + loss_ratios_4w

        import math
        week_of_year = 26  # Approximate mid-year default
        state = np.array([
            risk_score_norm,
            zone_data.get("imd_severity", 40) / 100.0,
            zone_data.get("historical_disruptions", 3) / 20.0,
            float(loss_ratios_4w[-1]),
            float(loss_ratios_4w[-2]),
            float(loss_ratios_4w[-3]),
            float(loss_ratios_4w[-4]),
            min(2.0, enrolled_riders / 500.0),
            float(np.clip(churn_rate, 0, 1)),
            float(np.clip(imd_seasonal, 0, 1)),
            math.sin(2 * math.pi * week_of_year / 52),
            math.cos(2 * math.pi * week_of_year / 52),
            current_premium / 225.0,
            0.10,  # adverse_selection_index — default
            float(np.clip(pool_funded_ratio, 0.1, 2.0)),
        ], dtype=np.float32)

        action_idx, meta = self.predict_action(state)
        delta_pct = self.PREMIUM_DELTAS[action_idx]
        new_premium = float(np.clip(
            current_premium * (1.0 + delta_pct),
            39.0, 225.0,
        ))

        # Log for shadow mode comparison
        entry = {
            "zone_id": zone_data.get("zone_id", "unknown"),
            "existing_premium": current_premium,
            "rl_recommended_premium": round(new_premium, 2),
            "delta_pct": round(delta_pct * 100, 1),
            "action_meta": meta,
            "existing_risk_score": risk_result["risk_score"],
        }
        self._decision_log.append(entry)

        if SHADOW_MODE:
            # In shadow mode, return existing result with RL recommendation appended
            result = risk_result.copy()
            result["rl_shadow_recommendation"] = {
                "recommended_premium": round(new_premium, 2),
                "delta_pct": round(delta_pct * 100, 1),
                "action": meta["delta_label"],
                "model": meta["model"],
                "shadow_mode": True,
                "note": "RL recommendation logged but NOT applied. Set ADAPT_PREMIUM_SHADOW_MODE=false to activate.",
            }
            return result

        # Live mode — return RL-adjusted premium
        result = risk_result.copy()
        result["premium"] = round(new_premium, 2)
        result["premium_source"] = "adapt_premium_rl"
        result["rl_action"] = meta
        return result

    def get_shadow_comparison(self, n_recent: int = 10) -> list[dict]:
        """Return recent shadow mode comparison log entries."""
        return self._decision_log[-n_recent:]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Save PPO model weights to disk."""
        if self._ppo_model is None:
            logger.warning("AdaptPremiumAgent.save: no model to save.")
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._ppo_model.save(path)
        logger.info("AdaptPremiumAgent[%s]: saved to %s.", self.zone_id, path)

    def load(self, path: Optional[str] = None) -> bool:
        """Load PPO model from disk. Returns True on success."""
        if not _SB3:
            return False
        load_path = path or PPO_MODEL_PATH
        if not Path(f"{load_path}.zip").exists():
            logger.warning("AdaptPremiumAgent: model not found at %s.", load_path)
            return False
        try:
            env = DummyVecEnv([self._build_env])
            self._ppo_model = PPO.load(load_path, env=env)
            self.is_trained = True
            logger.info("AdaptPremiumAgent[%s]: loaded from %s.", self.zone_id, load_path)
            return True
        except Exception as e:
            logger.error("AdaptPremiumAgent: load failed — %s", e)
            return False
