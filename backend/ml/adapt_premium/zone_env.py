"""
zone_env.py — Custom Gym Environment for AdaptPremium PPO Agent.

State space (15-dim continuous):
  [0]  risk_score_norm          — current zone risk score / 100
  [1]  imd_severity_norm        — IMD forecast severity / 100
  [2]  disruption_freq_norm     — historical disruptions / 20
  [3]  loss_ratio_w1            — loss ratio week-1 (claims paid / premium collected)
  [4]  loss_ratio_w2            — loss ratio week-2
  [5]  loss_ratio_w3            — loss ratio week-3
  [6]  loss_ratio_w4            — loss ratio week-4
  [7]  enrolled_riders_norm     — enrolled riders / 500 (normalised)
  [8]  churn_rate               — weekly churn rate [0, 1]
  [9]  imd_seasonal_norm        — 90-day seasonal forecast severity / 100
  [10] time_of_year_sin         — sin(2π × day/365) seasonal cycle
  [11] time_of_year_cos         — cos(2π × day/365) seasonal cycle
  [12] current_premium_norm     — current premium / 225 (max tier)
  [13] adverse_selection_index  — new-rider claims / total claims [0, 1]
  [14] pool_funded_ratio        — pool_balance / expected_annual_claims [0, 2]

Action space (Discrete 7):
  0: -15%,  1: -10%,  2: -5%,  3: 0%,  4: +5%,  5: +10%,  6: +15%

Reward (multi-objective, normalised to [-1, +1]):
  R = w1 * r_loss_ratio
    + w2 * r_retention
    + w3 * r_pool_stability
    + w4 * r_adverse_selection_penalty
  Weights: [0.40, 0.25, 0.20, 0.15]

    r_loss_ratio:     1 - |LR - TARGET_LR| / TARGET_LR   (target LR = 0.65)
    r_retention:      1 - churn_rate_after_change
    r_pool_stability: pool_funded_ratio / 1.5  (clipped 0-1)
    r_adverse_sel:    -adverse_selection_index  (penalty — negative)

ZoneTwin GAN integration:
  When GAN_ENABLED=True (env var), the environment generates realistic
  disruption scenarios using ZoneTwinGAN.generate() as the transition model.
  This gives the PPO agent a richer training distribution than historical
  replay alone.

IRDAI compliance:
  All premium actions are validated through pricing_constraints.py before
  the environment steps forward — illegal actions are masked to 0% change.
"""

from __future__ import annotations

import logging
import math
import os
import random
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gym — graceful import
# ---------------------------------------------------------------------------

try:
    import gymnasium as gym
    from gymnasium import spaces
    _GYM_API = "gymnasium"
except ImportError:
    try:
        import gym
        from gym import spaces
        _GYM_API = "gym"
    except ImportError:
        gym = None
        spaces = None
        _GYM_API = "none"
        logger.warning("gymnasium/gym not installed. ZoneEnv will use stub base class.")

# ---------------------------------------------------------------------------
# Action mapping
# ---------------------------------------------------------------------------

PREMIUM_DELTAS = [-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]
N_ACTIONS = len(PREMIUM_DELTAS)

# Reward weights
W_LOSS_RATIO       = 0.40
W_RETENTION        = 0.25
W_POOL_STABILITY   = 0.20
W_ADVERSE_SEL      = 0.15

TARGET_LOSS_RATIO  = 0.65   # IRDAI-informed target
MIN_POOL_RATIO     = 0.80   # Pool must stay funded at ≥80% of expected claims
MAX_EPISODE_STEPS  = 52     # One year of weekly decisions


# ---------------------------------------------------------------------------
# Base class stub when gym not installed
# ---------------------------------------------------------------------------

class _EnvStub:
    """Minimal stub when gym/gymnasium is not available."""
    def reset(self, *a, **kw):
        raise RuntimeError("gym/gymnasium not installed. pip install gymnasium")
    def step(self, *a, **kw):
        raise RuntimeError("gym/gymnasium not installed. pip install gymnasium")


# ---------------------------------------------------------------------------
# ZonePremiumEnv
# ---------------------------------------------------------------------------

_BaseEnv = (gym.Env if gym is not None else _EnvStub)


class ZonePremiumEnv(_BaseEnv):
    """
    Custom Gym environment for weekly zone premium pricing decisions.

    One episode = 52 weeks (one policy year).
    One step = one weekly pricing decision.
    """

    STATE_DIM = 15

    def __init__(
        self,
        zone_id: str = "bellandur",
        zone_type: str = "flood-prone",
        initial_premium: float = 139.0,
        initial_riders: int = 150,
        use_gan_rollouts: bool = False,
        seed: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.zone_id = zone_id
        self.zone_type = zone_type
        self.initial_premium = initial_premium
        self.initial_riders = initial_riders
        self.use_gan_rollouts = use_gan_rollouts and os.getenv("GAN_ENABLED", "false").lower() == "true"
        self._seed = seed
        self._rng = np.random.default_rng(seed)

        # GAN rollout model (lazy loaded)
        self._gan = None

        if spaces is not None:
            self.action_space = spaces.Discrete(N_ACTIONS)
            self.observation_space = spaces.Box(
                low=np.zeros(self.STATE_DIM, dtype=np.float32),
                high=np.ones(self.STATE_DIM, dtype=np.float32) * 2.0,
                dtype=np.float32,
            )

        # Import pricing constraints
        try:
            from ml.adapt_premium.pricing_constraints import IRDAIConstraints
            self._constraints = IRDAIConstraints(zone_type=zone_type)
        except ImportError:
            self._constraints = None

        self._state: np.ndarray = np.zeros(self.STATE_DIM, dtype=np.float32)
        self._step_count: int = 0
        self._week: int = 0
        self._current_premium: float = initial_premium
        self._enrolled_riders: float = float(initial_riders)

    # ------------------------------------------------------------------
    # Gym interface
    # ------------------------------------------------------------------

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> tuple[np.ndarray, dict]:
        if seed is not None:
            self._rng = np.random.default_rng(seed)

        self._step_count = 0
        self._week = 0
        self._current_premium = self.initial_premium
        self._enrolled_riders = float(self.initial_riders)
        self._state = self._sample_initial_state()

        return self._state.copy(), {"zone_id": self.zone_id}

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """
        Apply a premium adjustment action and advance one week.

        Returns: (next_state, reward, terminated, truncated, info)
        """
        assert 0 <= action < N_ACTIONS, f"Invalid action {action}"

        # Validate with IRDAI constraints (mask illegal actions to no-change)
        delta_pct = PREMIUM_DELTAS[action]
        if self._constraints is not None:
            delta_pct, _ = self._constraints.validate_delta(
                self._current_premium, delta_pct
            )

        # Apply premium change
        new_premium = self._current_premium * (1.0 + delta_pct)

        # Simulate week transition (GAN or stochastic fallback)
        week_data = self._simulate_week(new_premium)

        # Compute reward
        reward = self._compute_reward(week_data, delta_pct)

        # Update state
        self._current_premium = new_premium
        self._enrolled_riders = week_data["enrolled_riders_end"]
        self._week += 1
        self._step_count += 1
        self._state = self._build_state(week_data)

        terminated = False
        truncated = self._step_count >= MAX_EPISODE_STEPS

        info = {
            "week": self._week,
            "premium": round(new_premium, 2),
            "delta_pct": round(delta_pct * 100, 1),
            "loss_ratio": round(week_data["loss_ratio"], 4),
            "churn_rate": round(week_data["churn_rate"], 4),
            "enrolled_riders": int(week_data["enrolled_riders_end"]),
            "pool_funded_ratio": round(week_data["pool_funded_ratio"], 4),
            "reward_breakdown": week_data.get("reward_breakdown", {}),
        }

        return self._state.copy(), reward, terminated, truncated, info

    # ------------------------------------------------------------------
    # State construction
    # ------------------------------------------------------------------

    def _sample_initial_state(self) -> np.ndarray:
        """Sample a plausible initial zone state."""
        state = np.zeros(self.STATE_DIM, dtype=np.float32)
        # Zone risk features
        state[0] = float(self._rng.uniform(0.4, 0.85))    # risk_score
        state[1] = float(self._rng.uniform(0.2, 0.7))     # imd_severity
        state[2] = float(self._rng.uniform(0.1, 0.5))     # disruption_freq
        # Loss ratios (4 weeks history, initialise near target)
        for i in range(3, 7):
            state[i] = float(self._rng.normal(TARGET_LOSS_RATIO, 0.08))
        # Rider stats
        state[7] = min(2.0, self._enrolled_riders / 500.0)
        state[8] = float(self._rng.uniform(0.02, 0.08))   # churn_rate
        # Seasonal
        state[9] = float(self._rng.uniform(0.3, 0.8))     # imd_seasonal
        day = int(self._rng.integers(0, 365))
        state[10] = float(math.sin(2 * math.pi * day / 365))
        state[11] = float(math.cos(2 * math.pi * day / 365))
        # Current premium norm
        state[12] = self._current_premium / 225.0
        state[13] = float(self._rng.uniform(0.05, 0.25))  # adverse_selection
        state[14] = float(self._rng.uniform(0.8, 1.5))    # pool_funded_ratio
        return state

    def _build_state(self, week_data: dict) -> np.ndarray:
        state = np.zeros(self.STATE_DIM, dtype=np.float32)
        state[0] = float(self._state[0])  # risk_score unchanged within episode
        state[1] = week_data.get("imd_severity", float(self._state[1]))
        state[2] = float(self._state[2])
        # Shift loss ratio window
        state[3] = week_data["loss_ratio"]
        state[4:7] = self._state[3:6]  # shift history
        # Rider stats
        state[7] = min(2.0, week_data["enrolled_riders_end"] / 500.0)
        state[8] = week_data["churn_rate"]
        # Seasonal advance
        day_norm = (self._week % 52) / 52.0
        state[10] = float(math.sin(2 * math.pi * day_norm))
        state[11] = float(math.cos(2 * math.pi * day_norm))
        state[12] = self._current_premium / 225.0
        state[13] = week_data.get("adverse_selection_index", float(self._state[13]))
        state[14] = week_data["pool_funded_ratio"]
        state[9] = week_data.get("imd_seasonal_norm", float(self._state[9]))
        return state

    # ------------------------------------------------------------------
    # Week simulation
    # ------------------------------------------------------------------

    def _simulate_week(self, new_premium: float) -> dict:
        """Simulate one week of zone operations."""
        if self.use_gan_rollouts and self._gan is not None:
            return self._simulate_week_gan(new_premium)
        return self._simulate_week_stochastic(new_premium)

    def _simulate_week_stochastic(self, new_premium: float) -> dict:
        """Stochastic simulation without GAN."""
        # Seasonal disruption probability
        is_monsoon = 150 <= (self._week * 7) % 365 <= 270
        disruption_prob = 0.35 if is_monsoon else 0.10
        disruption = float(self._rng.uniform(0, 1)) < disruption_prob

        # Claims simulation
        disruption_multiplier = 3.5 if disruption else 1.0
        base_claim_rate = float(self._state[0]) * 0.3  # risk_score → claim rate
        claim_rate = base_claim_rate * disruption_multiplier
        expected_claims_paid = claim_rate * self._enrolled_riders * 4290 / 52
        premium_collected = self._enrolled_riders * new_premium
        loss_ratio = expected_claims_paid / max(premium_collected, 1.0)

        # Churn: high premium or low loss ratio → higher churn
        premium_sensitivity = max(0, (new_premium / self.initial_premium) - 1.0) * 0.3
        churn_rate = float(np.clip(
            0.04 + premium_sensitivity + self._rng.normal(0, 0.01),
            0.0, 0.3,
        ))

        # New riders (offset churn with natural growth)
        new_riders = float(self._rng.poisson(max(3, self._enrolled_riders * 0.05)))
        leaving = int(self._enrolled_riders * churn_rate)
        enrolled_end = max(10.0, self._enrolled_riders - leaving + new_riders)

        # Adverse selection
        adverse_sel = float(np.clip(
            self._state[13] + self._rng.normal(0, 0.02),
            0.0, 1.0,
        ))

        # Pool stability
        pool_ratio = float(np.clip(
            self._state[14] + (1 - loss_ratio) * 0.05 + self._rng.normal(0, 0.02),
            0.1, 2.0,
        ))

        # IMD severity — drift
        imd = float(np.clip(
            self._state[1] + (0.1 if is_monsoon else -0.02) + self._rng.normal(0, 0.05),
            0.0, 1.0,
        ))

        return {
            "loss_ratio": float(np.clip(loss_ratio, 0.0, 3.0)),
            "churn_rate": churn_rate,
            "enrolled_riders_end": enrolled_end,
            "adverse_selection_index": adverse_sel,
            "pool_funded_ratio": pool_ratio,
            "imd_severity": imd,
            "imd_seasonal_norm": imd,
            "disruption": disruption,
        }

    def _simulate_week_gan(self, new_premium: float) -> dict:
        """Use ZoneTwinGAN for richer transition dynamics."""
        try:
            week_day = DAYS_OF_WEEK[self._week % 7] if False else "mon"
            season = (
                "monsoon" if 150 <= (self._week * 7) % 365 <= 270
                else "pre_monsoon" if (self._week * 7) % 365 < 150
                else "winter"
            )
            from ml.zone_twin_gan import DAYS_OF_WEEK
            scenario = self._gan.generate(
                n=1, zone_type=self.zone_type, season=season,
                day_of_week="mon", time_of_day="morning",
            )[0]

            # Map GAN output to week simulation
            inactivity = scenario["s4_inactivity_pct"] / 100.0
            order_drop = (100 - scenario["s3_order_pct"]) / 100.0
            claim_rate = inactivity * 0.5 + order_drop * 0.3
            premium_collected = self._enrolled_riders * new_premium
            claims_paid = claim_rate * self._enrolled_riders * 4290 / 52
            loss_ratio = claims_paid / max(premium_collected, 1.0)

            churn = float(np.clip(0.04 + max(0, (new_premium / self.initial_premium) - 1) * 0.3, 0, 0.3))
            enrolled_end = max(10.0, self._enrolled_riders * (1 - churn) + self._rng.poisson(5))

            return {
                "loss_ratio": float(np.clip(loss_ratio, 0.0, 3.0)),
                "churn_rate": churn,
                "enrolled_riders_end": enrolled_end,
                "adverse_selection_index": float(self._state[13]),
                "pool_funded_ratio": float(np.clip(self._state[14] + (1 - loss_ratio) * 0.05, 0.1, 2.0)),
                "imd_severity": scenario["s1_rainfall"] / 100.0,
                "imd_seasonal_norm": scenario["s1_rainfall"] / 100.0,
                "disruption": inactivity > 0.4,
            }
        except Exception as e:
            logger.warning("GAN rollout failed (%s) — falling back to stochastic.", e)
            return self._simulate_week_stochastic(new_premium)

    def attach_gan(self, gan: object) -> None:
        """Attach a trained ZoneTwinGAN model for rollout simulation."""
        self._gan = gan
        logger.info("ZonePremiumEnv[%s]: GAN attached.", self.zone_id)

    # ------------------------------------------------------------------
    # Reward
    # ------------------------------------------------------------------

    def _compute_reward(self, week_data: dict, delta_pct: float) -> float:
        """Compute multi-objective reward."""
        lr = week_data["loss_ratio"]
        churn = week_data["churn_rate"]
        pool = week_data["pool_funded_ratio"]
        adv_sel = week_data["adverse_selection_index"]

        # Loss ratio component: penalise deviation from TARGET_LR
        r_loss = 1.0 - abs(lr - TARGET_LOSS_RATIO) / max(TARGET_LOSS_RATIO, 1e-6)
        r_loss = float(np.clip(r_loss, -1.0, 1.0))

        # Retention component
        r_retention = 1.0 - churn / 0.3  # normalise by max churn
        r_retention = float(np.clip(r_retention, -1.0, 1.0))

        # Pool stability
        r_pool = min(1.0, pool / 1.5)

        # Adverse selection penalty (negative contribution)
        r_adverse = -adv_sel

        reward = (
            W_LOSS_RATIO     * r_loss
            + W_RETENTION    * r_retention
            + W_POOL_STABILITY * r_pool
            + W_ADVERSE_SEL  * r_adverse
        )

        week_data["reward_breakdown"] = {
            "r_loss_ratio": round(r_loss, 4),
            "r_retention": round(r_retention, 4),
            "r_pool_stability": round(r_pool, 4),
            "r_adverse_sel": round(r_adverse, 4),
            "total": round(reward, 4),
        }

        return float(reward)

    def render(self, mode: str = "human") -> None:
        print(
            f"ZonePremiumEnv[{self.zone_id}] Week={self._week} "
            f"Premium=₹{self._current_premium:.0f} "
            f"Riders={int(self._enrolled_riders)}"
        )
