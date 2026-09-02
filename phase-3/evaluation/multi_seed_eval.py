"""
Multi-seed evaluation — task brief step 8.

Runs the full richer-population benchmark (13 additional regimes across
legitimate/suspicious/ambiguous behavior) over 10 independent seeds, for
BOTH Drift Watch (merchant-specific baseline) and the static-threshold
comparator, and reports mean/median/std/min/max for the key event-level
metrics. No seed is cherry-picked or hidden - every seed's numbers are
written to evaluation/multi_seed_raw.csv.
"""
import os
import sys
import pandas as pd
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data.synthetic_generator import build_richer_population
from detection.drift_detector import merchant_specific_drift, static_threshold_baseline
from evaluation.evaluate import event_level_evaluation_v2

SEEDS = list(range(1, 11))  # 10 independent seeds, documented and fixed


def run_seed(seed: int) -> pd.DataFrame:
    df = build_richer_population(seed=seed)
    scored = merchant_specific_drift(df)
    scored["predicted_drift_static"] = static_threshold_baseline(df)

    rows = []
    for pred_col, label in [("predicted_drift_ms", "Drift Watch"), ("predicted_drift_static", "Static threshold")]:
        ev = event_level_evaluation_v2(scored, pred_col)
        ev["seed"] = seed
        ev["detector"] = label
        rows.append(ev)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    all_rows = pd.concat([run_seed(s) for s in SEEDS], ignore_index=True)
    all_rows.to_csv(os.path.join(REPO_ROOT, "evaluation", "multi_seed_raw.csv"), index=False)

    metrics = ["event_recall", "event_precision", "event_f1", "avg_latency_days", "false_alert_rate_nonevent_days"]
    summary_rows = []
    for detector, g in all_rows.groupby("detector"):
        for m in metrics:
            vals = g[m].dropna()
            summary_rows.append({
                "detector": detector, "metric": m,
                "mean": round(vals.mean(), 3), "median": round(vals.median(), 3),
                "std": round(vals.std(), 3), "min": round(vals.min(), 3), "max": round(vals.max(), 3),
                "n_seeds": len(vals),
            })
    summary = pd.DataFrame(summary_rows)
    print(all_rows[["seed", "detector", "events_total", "events_detected", "event_recall",
                     "event_precision", "event_f1", "avg_latency_days",
                     "false_alert_rate_nonevent_days"]].to_string(index=False))
    print()
    print(summary.to_string(index=False))
    summary.to_csv(os.path.join(REPO_ROOT, "evaluation", "multi_seed_summary.csv"), index=False)
