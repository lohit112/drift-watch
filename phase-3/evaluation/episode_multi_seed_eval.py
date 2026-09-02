"""
Multi-seed regression: CURRENT SYSTEM (day-level, Phase 2's
evaluation.evaluate.event_level_evaluation_v2) vs EPISODE SYSTEM
(evaluation.episode_metrics.episode_level_evaluation) — task brief step 15.

Same 10 seeds as evaluation/multi_seed_eval.py (SEEDS = 1..10), NOT
reduced, per the brief's explicit instruction.
"""
import os
import sys
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data.synthetic_generator import build_richer_population
from detection.drift_detector import merchant_specific_drift
from evaluation.evaluate import event_level_evaluation_v2
from evaluation.episode_metrics import episode_level_evaluation
from evaluation.matching import match_episodes

SEEDS = list(range(1, 11))


def run_seed(seed: int) -> pd.DataFrame:
    df = build_richer_population(seed=seed)
    scored = merchant_specific_drift(df)

    day_level = event_level_evaluation_v2(scored, "predicted_drift_ms")
    day_level["system"] = "Current (day-level, Phase 2)"
    day_level["seed"] = seed
    day_level["duplicate_episode_rate"] = None

    ep_level = episode_level_evaluation(scored, "predicted_drift_ms")
    ep_level["system"] = "Episode (Phase 3)"
    ep_level["seed"] = seed

    return pd.DataFrame([day_level, ep_level])


if __name__ == "__main__":
    all_rows = pd.concat([run_seed(s) for s in SEEDS], ignore_index=True)
    all_rows.to_csv(os.path.join(REPO_ROOT, "evaluation", "episode_multi_seed_raw.csv"), index=False)

    metrics = ["event_recall", "event_precision", "event_f1",
               "false_alert_rate_nonevent_days" if "false_alert_rate_nonevent_days" in all_rows else None]
    summary_rows = []
    for system, g in all_rows.groupby("system"):
        for m in ["event_recall", "event_precision", "event_f1"]:
            vals = g[m].dropna()
            summary_rows.append({
                "system": system, "metric": m,
                "mean": round(vals.mean(), 3), "median": round(vals.median(), 3),
                "std": round(vals.std(), 3), "min": round(vals.min(), 3), "max": round(vals.max(), 3),
            })
        if g["avg_latency_days"].notna().any():
            vals = g["avg_latency_days"].dropna()
        else:
            vals = g["avg_detection_latency_days"].dropna()
        summary_rows.append({
            "system": system, "metric": "avg_latency_days",
            "mean": round(vals.mean(), 3), "median": round(vals.median(), 3),
            "std": round(vals.std(), 3), "min": round(vals.min(), 3), "max": round(vals.max(), 3),
        })
        if "duplicate_episode_rate" in g.columns and g["duplicate_episode_rate"].notna().any():
            vals = g["duplicate_episode_rate"].dropna()
            summary_rows.append({
                "system": system, "metric": "duplicate_episode_rate",
                "mean": round(vals.mean(), 3), "median": round(vals.median(), 3),
                "std": round(vals.std(), 3), "min": round(vals.min(), 3), "max": round(vals.max(), 3),
            })

    summary = pd.DataFrame(summary_rows)
    print(summary.to_string(index=False))
    summary.to_csv(os.path.join(REPO_ROOT, "evaluation", "episode_multi_seed_summary.csv"), index=False)
