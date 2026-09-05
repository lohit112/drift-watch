"""
Baseline experiments — task brief step 4.

Compares the shipped rolling-mean/std detector against two documented
alternatives (rolling median/MAD, EWMA) using the SAME evaluation
methodology (day-level + event-level) on TWO independent datasets: the
original single-seed population and the richer multi-regime population, so
results aren't tuned against one synthetic dataset only (task brief
explicit requirement).

Writes evaluation/BASELINE_EXPERIMENTS.md with the actual numbers. Does not
change what ships by default (detection/drift_detector.py) unless a
candidate is materially better — see the report's conclusion section for
the actual decision made.
"""
import os
import sys
import time
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from detection.baselines import BASELINE_METHODS
from detection.signal_taxonomy import SIGNAL_GROUPS
from data.synthetic_generator import build_richer_population
from evaluation.evaluate import event_level_evaluation_v2

FEATURES = ["txn_count", "txn_volume", "refund_rate", "dispute_rate", "category_entropy", "geo_entropy"]
Z_THRESHOLD = 2.5
MIN_SIGNALS_FOR_FLAG = 2


def score_with_method(df: pd.DataFrame, method_name: str) -> pd.DataFrame:
    method_fn = BASELINE_METHODS[method_name]
    df = df.sort_values(["merchant_id", "day"]).copy()
    out_rows = []
    for mid, g in df.groupby("merchant_id"):
        g = g.reset_index(drop=True)
        z_scores = pd.DataFrame(index=g.index)
        for feat in FEATURES:
            z_scores[feat] = method_fn(g, feat)
        feature_flags = z_scores.abs() >= Z_THRESHOLD
        group_flags = pd.DataFrame(index=g.index)
        for group_name, group in SIGNAL_GROUPS.items():
            group_flags[group_name] = feature_flags[list(group.features)].any(axis=1)
        g["predicted_drift"] = (group_flags.sum(axis=1) >= MIN_SIGNALS_FOR_FLAG).astype(int)
        out_rows.append(g)
    return pd.concat(out_rows, ignore_index=True)


def run_experiment(df: pd.DataFrame, dataset_label: str) -> pd.DataFrame:
    rows = []
    for method_name in BASELINE_METHODS:
        t0 = time.time()
        scored = score_with_method(df, method_name)
        elapsed = time.time() - t0
        ev = event_level_evaluation_v2(scored, "predicted_drift")
        ev["method"] = method_name
        ev["dataset"] = dataset_label
        ev["compute_seconds"] = round(elapsed, 3)
        rows.append(ev)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    original = pd.read_csv(os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv"))
    richer = build_richer_population(seed=42)

    results_original = run_experiment(original, "original (single-seed, 24 merchants)")
    results_richer = run_experiment(richer, "richer (13 additional regimes, 42 merchants)")
    all_results = pd.concat([results_original, results_richer], ignore_index=True)

    cols = ["dataset", "method", "events_total", "events_detected", "missed_events",
            "event_recall", "event_precision", "event_f1", "avg_latency_days",
            "median_latency_days", "false_alerts_per_merchant",
            "false_alert_rate_nonevent_days", "compute_seconds"]
    print(all_results[cols].to_string(index=False))
    all_results.to_csv(os.path.join(REPO_ROOT, "evaluation", "baseline_experiments_raw.csv"), index=False)
