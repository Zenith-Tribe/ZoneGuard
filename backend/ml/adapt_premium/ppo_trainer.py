"""
ppo_trainer.py — AdaptPremium PPO Training Loop.

Responsibilities:
  1. Train the PPO agent across all 10 Bengaluru zones.
  2. Evaluate in shadow mode: run trained agent alongside existing
     ZoneRisk Scorer and log the delta for every Monday recalculation.
  3. Produce a training summary report with per-zone performance metrics.
  4. Optionally attach a ZoneTwinGAN model to the environment for
     GAN-augmented rollout training (transfer learning bridge).

Run directly:
  python -m ml.adapt_premium.ppo_trainer --zone all --timesteps 200000

Environment variables:
  ADAPT_PREMIUM_SHADOW_MODE  — see rl_agent.py
  PPO_MODEL_PATH             — save path
  GAN_ENABLED                — use GAN rollouts
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Zone configuration (mirrors ZONE_BASELINES from zone_twin.py)
# ---------------------------------------------------------------------------

ZONE_CONFIGS = {
    "hsr":             {"zone_type": "medium",     "initial_premium": 89.0,  "initial_riders": 180},
    "koramangala":     {"zone_type": "medium",     "initial_premium": 89.0,  "initial_riders": 220},
    "whitefield":      {"zone_type": "low",        "initial_premium": 39.0,  "initial_riders": 300},
    "indiranagar":     {"zone_type": "medium",     "initial_premium": 89.0,  "initial_riders": 200},
    "electronic-city": {"zone_type": "low",        "initial_premium": 39.0,  "initial_riders": 250},
    "bellandur":       {"zone_type": "flood-prone","initial_premium": 225.0, "initial_riders": 120},
    "btm-layout":      {"zone_type": "high",       "initial_premium": 139.0, "initial_riders": 160},
    "jp-nagar":        {"zone_type": "high",       "initial_premium": 139.0, "initial_riders": 150},
    "yelahanka":       {"zone_type": "low",        "initial_premium": 39.0,  "initial_riders": 130},
    "hebbal":          {"zone_type": "high",       "initial_premium": 139.0, "initial_riders": 140},
}


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------

class AdaptPremiumTrainer:
    """
    Orchestrates PPO training across multiple zones.

    Usage:
        trainer = AdaptPremiumTrainer()
        summary = trainer.train_all_zones(total_timesteps=200_000)
        shadow_report = trainer.run_shadow_evaluation(weeks=52)
    """

    def __init__(
        self,
        output_dir: str = PPO_MODEL_PATH := os.getenv("PPO_MODEL_PATH", "/models/adapt_ppo"),
        gan_model_dir: Optional[str] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.gan_model_dir = gan_model_dir
        self._agents: dict = {}
        self._training_results: dict = {}

    def train_zone(
        self,
        zone_id: str,
        total_timesteps: int = 200_000,
        attach_gan: bool = False,
    ) -> dict:
        """Train a single zone agent."""
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent

        config = ZONE_CONFIGS.get(zone_id, {"zone_type": "medium", "initial_premium": 89.0, "initial_riders": 150})

        logger.info("AdaptPremiumTrainer: training zone=%s type=%s.", zone_id, config["zone_type"])

        agent = AdaptPremiumAgent(
            zone_id=zone_id,
            zone_type=config["zone_type"],
            initial_premium=config["initial_premium"],
            initial_riders=config["initial_riders"],
        )

        # Optionally attach GAN to environment
        if attach_gan and self.gan_model_dir:
            try:
                from ml.zone_twin_gan import ZoneTwinGAN
                gan = ZoneTwinGAN(zone_id=zone_id)
                gan_path = Path(self.gan_model_dir) / f"{zone_id}_gan.pt"
                if gan_path.exists():
                    gan.load(str(gan_path))
                    agent._env = agent._build_env()
                    agent._env.attach_gan(gan)
                    logger.info("AdaptPremiumTrainer: GAN attached for zone %s.", zone_id)
            except Exception as e:
                logger.warning("Could not attach GAN for %s: %s", zone_id, e)

        model_path = str(self.output_dir / f"{zone_id}_ppo")
        start = time.time()
        result = agent.train(
            total_timesteps=total_timesteps,
            n_envs=min(4, os.cpu_count() or 1),
            verbose=0,
        )
        elapsed = time.time() - start

        result["elapsed_seconds"] = round(elapsed, 1)
        result["model_path"] = model_path

        self._agents[zone_id] = agent
        self._training_results[zone_id] = result
        return result

    def train_all_zones(
        self,
        total_timesteps: int = 200_000,
        attach_gan: bool = False,
    ) -> dict:
        """Train agents for all 10 Bengaluru zones."""
        summary: dict = {
            "started_at": datetime.utcnow().isoformat(),
            "total_timesteps_per_zone": total_timesteps,
            "zones": {},
        }

        for zone_id in ZONE_CONFIGS:
            try:
                result = self.train_zone(zone_id, total_timesteps, attach_gan)
                summary["zones"][zone_id] = result
            except Exception as e:
                logger.error("Training failed for zone %s: %s", zone_id, e)
                summary["zones"][zone_id] = {"error": str(e)}

        summary["completed_at"] = datetime.utcnow().isoformat()
        summary["zones_succeeded"] = sum(
            1 for r in summary["zones"].values() if "error" not in r
        )

        # Persist summary
        summary_path = self.output_dir / "training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)
        logger.info("AdaptPremiumTrainer: summary saved to %s.", summary_path)

        return summary

    # ------------------------------------------------------------------
    # Shadow evaluation
    # ------------------------------------------------------------------

    def run_shadow_evaluation(
        self,
        weeks: int = 52,
        zones: Optional[list[str]] = None,
    ) -> dict:
        """
        Run shadow mode evaluation: compare RL agent vs existing ZoneRisk Scorer
        across N weeks for each zone.

        Returns a comparison report with:
          - Mean premium delta (RL vs rule-based)
          - Simulated loss ratio improvement
          - Per-zone recommendation breakdown
        """
        from ml.zone_risk_scorer import calculate_zone_premium
        from ml.adapt_premium.rl_agent import AdaptPremiumAgent

        eval_zones = zones or list(ZONE_CONFIGS.keys())
        report: dict = {
            "evaluation_weeks": weeks,
            "shadow_mode": True,
            "zones": {},
        }

        for zone_id in eval_zones:
            config = ZONE_CONFIGS.get(zone_id, {})
            agent = self._agents.get(zone_id) or AdaptPremiumAgent(
                zone_id=zone_id,
                zone_type=config.get("zone_type", "medium"),
                initial_premium=config.get("initial_premium", 89.0),
                initial_riders=config.get("initial_riders", 150),
            )

            # Load saved model if available
            agent.load(str(self.output_dir / f"{zone_id}_ppo"))

            zone_comparisons: list[dict] = []
            premium_rl = config.get("initial_premium", 89.0)
            premium_rule = config.get("initial_premium", 89.0)
            lr_history: list[float] = [0.65, 0.65, 0.65, 0.65]

            for week in range(1, weeks + 1):
                # Simulate a week of data
                rng = np.random.default_rng(hash(zone_id) + week)
                zone_data = {
                    "zone_id": zone_id,
                    "historical_disruptions": int(rng.integers(2, 8)),
                    "imd_severity": float(rng.uniform(30, 80)),
                    "risk_tier": config.get("zone_type", "medium"),
                    "recent_claims": int(rng.integers(1, 10)),
                    "active_riders": config.get("initial_riders", 150),
                }

                # RL recommendation
                rl_result = agent.get_recommendation(
                    zone_data,
                    loss_ratios_4w=lr_history,
                    churn_rate=float(rng.uniform(0.02, 0.08)),
                    enrolled_riders=config.get("initial_riders", 150),
                )

                # Existing rule-based
                rule_result = calculate_zone_premium(zone_data)

                # Simulate outcome loss ratio
                sim_lr = float(rng.beta(4, 6))  # ~0.4-0.8 range
                lr_history = lr_history[1:] + [sim_lr]

                zone_comparisons.append({
                    "week": week,
                    "rule_premium": rule_result["premium"],
                    "rl_premium": rl_result.get("rl_shadow_recommendation", {}).get("recommended_premium", rl_result["premium"]),
                    "simulated_lr": round(sim_lr, 4),
                })

            rl_premiums = [c["rl_premium"] for c in zone_comparisons]
            rule_premiums = [c["rule_premium"] for c in zone_comparisons]
            lrs = [c["simulated_lr"] for c in zone_comparisons]

            report["zones"][zone_id] = {
                "mean_rl_premium": round(float(np.mean(rl_premiums)), 2),
                "mean_rule_premium": round(float(np.mean(rule_premiums)), 2),
                "mean_premium_delta": round(float(np.mean(rl_premiums)) - float(np.mean(rule_premiums)), 2),
                "mean_simulated_lr": round(float(np.mean(lrs)), 4),
                "lr_target_gap": round(abs(float(np.mean(lrs)) - 0.65), 4),
                "weekly_comparisons": zone_comparisons[-4:],  # Last 4 weeks sample
            }

        return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="AdaptPremium PPO Trainer")
    parser.add_argument("--zone", default="all", help="Zone ID or 'all'")
    parser.add_argument("--timesteps", type=int, default=200_000)
    parser.add_argument("--shadow-eval", action="store_true", help="Run shadow evaluation after training")
    parser.add_argument("--gan", action="store_true", help="Attach ZoneTwinGAN rollouts")
    args = parser.parse_args()

    trainer = AdaptPremiumTrainer()

    if args.zone == "all":
        summary = trainer.train_all_zones(total_timesteps=args.timesteps, attach_gan=args.gan)
    else:
        summary = {"zones": {args.zone: trainer.train_zone(args.zone, args.timesteps, args.gan)}}

    print(json.dumps({k: v for k, v in summary.items() if k != "zones"}, indent=2))

    if args.shadow_eval:
        report = trainer.run_shadow_evaluation(weeks=52)
        print("\n=== Shadow Evaluation ===")
        for zone_id, stats in report["zones"].items():
            print(f"  {zone_id}: RL={stats['mean_rl_premium']:.0f} Rule={stats['mean_rule_premium']:.0f} ΔLR={stats['lr_target_gap']:.3f}")


if __name__ == "__main__":
    main()
