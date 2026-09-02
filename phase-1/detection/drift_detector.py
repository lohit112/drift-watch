"""
Drift Watch — statistical detection layer.

Deterministic, explainable detection: no LLM calls here. This layer's job is
purely numerical — decide which merchant-days show a meaningful deviation
from that merchant's OWN historical behavior, using rolling baselines,
EWMA, and z-scores per feature. The output feeds the agent/reasoning layer
(see agents/), which is responsible for correlation, hypothesis generation,
and explanation — NOT for recomputing these numbers.
"""
import numpy as np
import pandas as pd

FEATURES = ["txn_count", "txn_volume", "refund_rate", "dispute_rate",
            "category_entropy", "geo_entropy"]

# txn_count and txn_volume are algebraically correlated (volume ~ count * avg_value),
# so they must NOT count as two independent signals toward the correlation threshold -
# doing so double-counts a single real signal and was inflating false positives in v0
# (see DECISIONS.md). Signals are grouped into independent domains instead.
SIGNAL_GROUPS = {
    "volume": ["txn_count", "txn_volume"],
    "refund": ["refund_rate"],
    "dispute": ["dispute_rate"],
    "category_mix": ["category_entropy"],
    "geo_mix": ["geo_entropy"],
}

BASELINE_WINDOW = 60      # days used to establish each merchant's own baseline
Z_THRESHOLD = 2.5         # per-feature deviation threshold
MIN_SIGNALS_FOR_FLAG = 2  # require deviation across >=2 independent signal domains


def merchant_specific_drift(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each merchant, compute a rolling baseline (mean/std over the
    preceding BASELINE_WINDOW days) and flag days where >= MIN_SIGNALS_FOR_FLAG
    features deviate beyond Z_THRESHOLD standard deviations from that
    merchant's own recent baseline (not a global threshold).
    """
    df = df.sort_values(["merchant_id", "day"]).copy()
    out_rows = []

    for mid, g in df.groupby("merchant_id"):
        g = g.reset_index(drop=True)
        z_scores = pd.DataFrame(index=g.index)

        for feat in FEATURES:
            roll_mean = g[feat].rolling(BASELINE_WINDOW, min_periods=20).mean().shift(1)
            roll_std = g[feat].rolling(BASELINE_WINDOW, min_periods=20).std().shift(1).replace(0, np.nan)
            z_scores[feat] = (g[feat] - roll_mean) / roll_std

        abs_z = z_scores.abs()
        feature_flags = (abs_z >= Z_THRESHOLD)

        # collapse feature-level flags into independent signal-domain flags
        group_flags = pd.DataFrame(index=g.index)
        for group_name, feats in SIGNAL_GROUPS.items():
            group_flags[group_name] = feature_flags[feats].any(axis=1)
        n_signal_groups = group_flags.sum(axis=1)

        g["n_deviant_signals"] = n_signal_groups
        g["deviant_features"] = feature_flags.apply(
            lambda row: [f for f, v in row.items() if v], axis=1
        )
        g["deviant_signal_groups"] = group_flags.apply(
            lambda row: [k for k, v in row.items() if v], axis=1
        )
        g["predicted_drift_ms"] = (n_signal_groups >= MIN_SIGNALS_FOR_FLAG).astype(int)
        for feat in FEATURES:
            g[f"z_{feat}"] = z_scores[feat]

        out_rows.append(g)

    return pd.concat(out_rows, ignore_index=True)


STATIC_MIN_HISTORY_DAYS = 30  # days of population history required before the txn_count leg can fire


def static_threshold_baseline(df: pd.DataFrame) -> pd.Series:
    """
    A naive population-wide static-threshold detector, used ONLY as the
    'traditional system' comparison point in evaluation — this is what we
    are arguing against, not what Drift Watch ships.

    PHASE 1 FIX (temporal leakage): the txn_count leg previously used
    `df["txn_count"].quantile(0.98)` computed ONCE over the entire dataset,
    including every merchant's future days. A static threshold system
    deployed on day 5 cannot know what transaction volumes look like on
    day 239 — that is future information leaking into a "today" decision,
    exactly the leakage category this project is designed to guard against.
    This was flagged but explicitly deferred in the prior session
    (see PHASE_1_REPORT.md / PROJECT_STATE.md); it is fixed here because it
    directly affects the comparison numbers used in README/evaluation.

    Fix: the txn_count threshold is now an EXPANDING, day-indexed 98th
    percentile computed only from rows with day < current day (population-
    wide, across all merchants — this baseline is still not merchant-
    specific, only no longer clairvoyant). Before STATIC_MIN_HISTORY_DAYS of
    population history exists, the txn_count leg cannot fire at all (refund/
    dispute legs, which use fixed constants rather than data-derived
    thresholds, are unaffected and always active).
    """
    df = df.copy()
    unique_days = sorted(df["day"].unique())
    day_values = df.groupby("day")["txn_count"].apply(list).to_dict()

    thresholds = {}
    history: list = []
    for d in unique_days:
        thresholds[d] = (
            pd.Series(history).quantile(0.98) if len(history) >= STATIC_MIN_HISTORY_DAYS else float("inf")
        )
        history.extend(day_values[d])

    txn_threshold = df["day"].map(thresholds)
    return (
        (df["refund_rate"] > 0.12) |
        (df["dispute_rate"] > 0.02) |
        (df["txn_count"] > txn_threshold)
    ).astype(int)


if __name__ == "__main__":
    import os
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raw = pd.read_csv(os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv"))
    scored = merchant_specific_drift(raw)
    scored["predicted_drift_static"] = static_threshold_baseline(raw)
    out_path = os.path.join(REPO_ROOT, "detection", "scored_events.csv")
    scored.to_csv(out_path, index=False)

    flagged = scored[scored["predicted_drift_ms"] == 1]
    print(f"Merchant-specific baseline flagged {len(flagged)} / {len(scored)} merchant-days")
    print(f"Static threshold flagged {int(scored['predicted_drift_static'].sum())} / {len(scored)} merchant-days")
    print("\nSample flagged rows (merchant-specific):")
    print(flagged[["merchant_id", "day", "archetype", "drift_kind",
                    "n_deviant_signals", "deviant_features"]].head(10).to_string(index=False))
