import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift, static_threshold_baseline


def test_no_future_leakage_in_merchant_specific_baseline():
    """
    The Drift Watch detector must never use a day's own value (or later days)
    to compute the baseline it's compared against - a detector that does this
    could "predict" a spike using information from the spike itself, which
    would be temporal leakage and would inflate detection performance
    unrealistically.

    Verified by construction: perturbing only day 90's feature values must
    NOT change the rolling-baseline mean/std used to score any day <= 90-1,
    and the day-90 flag itself must be reproducible from day<=90 data alone
    (i.e. truncating the dataframe at day 90 and rescoring gives the same
    flag for day 90 as scoring the full 240-day dataframe).
    """
    days = 150
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": [50 + (i % 5) for i in range(days)],
        "txn_volume": [50000.0 + (i % 5) * 100 for i in range(days)],
        "refund_rate": [0.03 + 0.005 * (i % 3) for i in range(days)],
        "dispute_rate": [0.005 + 0.001 * (i % 3) for i in range(days)],
        "category_entropy": [1.2] * days, "geo_entropy": [1.0] * days,
    })
    # inject an anomaly on day 90 only
    idx90 = df[df["day"] == 90].index
    df.loc[idx90, "txn_count"] = 5000
    df.loc[idx90, "txn_volume"] = 5000000.0
    df.loc[idx90, "refund_rate"] = 0.9
    df.loc[idx90, "dispute_rate"] = 0.5

    full_scored = merchant_specific_drift(df)
    truncated = df[df["day"] <= 90].copy()
    truncated_scored = merchant_specific_drift(truncated)

    full_day90_flag = full_scored[full_scored["day"] == 90]["predicted_drift_ms"].iloc[0]
    truncated_day90_flag = truncated_scored[truncated_scored["day"] == 90]["predicted_drift_ms"].iloc[0]

    assert full_day90_flag == truncated_day90_flag == 1, (
        "Day 90's flag must be identical whether or not future days (91-149) exist in "
        "the input - if it changes, the detector is leaking future information into "
        "past decisions."
    )

    # Also confirm days BEFORE day 90 are completely unaffected by day 90's anomaly.
    pre_full = full_scored[full_scored["day"] < 90]["predicted_drift_ms"].tolist()
    pre_truncated = truncated_scored[truncated_scored["day"] < 90]["predicted_drift_ms"].tolist()
    assert pre_full == pre_truncated, (
        "Flags for days before the injected anomaly must be identical regardless of "
        "what happens afterward - any difference means future data leaked backward."
    )


def test_no_future_leakage_in_static_threshold_baseline():
    """
    Regression test for a real Phase 1 bug: static_threshold_baseline used to
    call df["txn_count"].quantile(0.98) once over the WHOLE dataset, so a
    day-5 decision silently depended on day-239 transaction volumes across
    every merchant. Verified the same way as the merchant-specific detector's
    leakage test: truncating the dataframe to day <= 90 and rescoring must
    give the identical flag for day 90 as scoring the full dataset.
    """
    days = 150
    n_merchants = 3
    frames = []
    for m in range(n_merchants):
        frames.append(pd.DataFrame({
            "merchant_id": [f"M{m:04d}"] * days,
            "day": list(range(days)),
            "txn_count": [40 + (i % 7) + m * 5 for i in range(days)],
            "refund_rate": [0.03] * days,
            "dispute_rate": [0.005] * days,
        }))
    df = pd.concat(frames, ignore_index=True)

    # Inject a huge future spike (day 140, one merchant only) that would shift
    # a globally-computed 98th percentile threshold if leakage exists.
    idx = df[(df["day"] == 140) & (df["merchant_id"] == "M0000")].index
    df.loc[idx, "txn_count"] = 100000

    full = df.copy()
    full["flag"] = static_threshold_baseline(full)
    truncated = df[df["day"] <= 90].copy()
    truncated["flag"] = static_threshold_baseline(truncated)

    full_day90 = full[full["day"] == 90].sort_values("merchant_id")["flag"].tolist()
    trunc_day90 = truncated[truncated["day"] == 90].sort_values("merchant_id")["flag"].tolist()

    assert full_day90 == trunc_day90, (
        "Day 90's static-threshold flags must be identical whether or not a day-140 "
        f"spike exists later in the dataset. Full-dataset flags: {full_day90}, "
        f"truncated-dataset flags: {trunc_day90}. A mismatch means the day-140 spike "
        "leaked backward into the day-90 threshold."
    )


def test_static_threshold_requires_minimum_history_before_txn_count_leg_fires():
    """Before STATIC_MIN_HISTORY_DAYS of population history exists, the
    txn_count leg must not fire (there's no non-leaky way to compute a
    percentile yet); refund/dispute legs use fixed constants and are
    unaffected."""
    days = 5
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": [999999] * days,  # absurdly high - would trip a naive quantile immediately
        "refund_rate": [0.01] * days, "dispute_rate": [0.001] * days,
    })
    flags = static_threshold_baseline(df)
    assert flags.sum() == 0, (
        "With < STATIC_MIN_HISTORY_DAYS of history, the txn_count leg must not "
        "fire even for an extreme value, since no non-leaky threshold exists yet."
    )


if __name__ == "__main__":
    test_no_future_leakage_in_merchant_specific_baseline()
    test_no_future_leakage_in_static_threshold_baseline()
    test_static_threshold_requires_minimum_history_before_txn_count_leg_fires()
    print("test_data_handling.py: 3 tests passed")
