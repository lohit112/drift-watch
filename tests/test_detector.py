import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift, static_threshold_baseline, FEATURES, SIGNAL_GROUPS


def _flat_merchant_df(merchant_id="M9999", days=100, **overrides):
    """A merchant with completely constant behavior (zero variance) - an edge case."""
    base = {
        "merchant_id": merchant_id, "day": list(range(days)),
        "txn_count": [50] * days, "txn_volume": [50000.0] * days,
        "avg_txn_value": [1000.0] * days, "refund_rate": [0.03] * days,
        "dispute_rate": [0.005] * days, "category_entropy": [1.2] * days,
        "geo_entropy": [1.0] * days, "dominant_category": ["apparel"] * days,
        "dominant_geo": ["mumbai"] * days, "true_drift": [0] * days,
        "true_drift_any": [0] * days, "drift_kind": ["none"] * days,
        "archetype": ["normal"] * days,
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_zero_variance_merchant_does_not_crash_or_false_flag():
    """Constant behavior -> std is 0 -> z-score would be NaN/inf if not handled.
    drift_detector.py replaces 0 std with NaN, which makes z-scores NaN,
    which correctly evaluate as not >= Z_THRESHOLD (NaN comparisons are False)."""
    df = _flat_merchant_df()
    scored = merchant_specific_drift(df)
    assert scored["predicted_drift_ms"].sum() == 0, "A perfectly flat merchant must never be flagged"
    assert not scored["predicted_drift_ms"].isna().any()


def test_insufficient_history_does_not_flag():
    """Fewer than min_periods=20 days of history anywhere -> no flags possible,
    since rolling stats are NaN and NaN comparisons are False."""
    df = _flat_merchant_df(days=10)
    scored = merchant_specific_drift(df)
    assert scored["predicted_drift_ms"].sum() == 0


def test_signal_groups_are_independent_not_double_counted():
    """Regression test for the D5 bug (see DECISIONS.md): txn_count and
    txn_volume must count as ONE signal group ('volume'), not two, even
    though both are individually flagged as deviant features."""
    days = 80
    df = _flat_merchant_df(days=days)
    # inject a correlated volume spike only (both txn_count and txn_volume move together)
    # on days 70-75, nothing else changes
    for d in range(70, 76):
        idx = df[df["day"] == d].index
        df.loc[idx, "txn_count"] = 500
        df.loc[idx, "txn_volume"] = 500000.0

    scored = merchant_specific_drift(df)
    flagged = scored[scored["predicted_drift_ms"] == 1]
    # With MIN_SIGNALS_FOR_FLAG=2, a volume-only spike (1 independent signal
    # domain) must NOT trigger a flag on its own.
    assert flagged.empty, (
        "A pure volume spike (txn_count + txn_volume moving together) is only ONE "
        "independent signal domain and must not cross MIN_SIGNALS_FOR_FLAG=2 alone. "
        f"Got {len(flagged)} flagged rows: {flagged[['day','deviant_signal_groups']].to_dict('records')}"
    )


def test_signal_groups_cover_all_features():
    """Every feature in FEATURES must belong to exactly one SIGNAL_GROUPS entry,
    or detection silently ignores it."""
    grouped_features = set()
    for feats in SIGNAL_GROUPS.values():
        grouped_features.update(feats)
    assert set(FEATURES) == grouped_features, (
        f"Mismatch between FEATURES and SIGNAL_GROUPS: "
        f"in FEATURES but ungrouped: {set(FEATURES) - grouped_features}, "
        f"in SIGNAL_GROUPS but not in FEATURES: {grouped_features - set(FEATURES)}"
    )


def test_static_threshold_baseline_returns_binary_series():
    df = _flat_merchant_df()
    result = static_threshold_baseline(df)
    assert set(result.unique()).issubset({0, 1})
    assert len(result) == len(df)


def test_multiple_merchants_stay_isolated():
    """One merchant's drift must not affect another merchant's baseline/flags."""
    df1 = _flat_merchant_df(merchant_id="M0001", days=80)
    df2 = _flat_merchant_df(merchant_id="M0002", days=80)
    for d in range(70, 76):
        idx = df1[df1["day"] == d].index
        df1.loc[idx, "txn_count"] = 5000
        df1.loc[idx, "txn_volume"] = 5000000.0
        df1.loc[idx, "refund_rate"] = 0.9
        df1.loc[idx, "dispute_rate"] = 0.5

    combined = pd.concat([df1, df2], ignore_index=True)
    scored = merchant_specific_drift(combined)
    m1_flags = scored[(scored["merchant_id"] == "M0001") & (scored["predicted_drift_ms"] == 1)]
    m2_flags = scored[(scored["merchant_id"] == "M0002") & (scored["predicted_drift_ms"] == 1)]
    assert len(m1_flags) > 0, "M0001 has an injected multi-signal spike and should be flagged"
    assert len(m2_flags) == 0, "M0002 is untouched and must not be affected by M0001's drift"


def test_missing_values_do_not_crash_or_silently_flag():
    """
    Edge case 5 (Phase 1 audit): NaNs in a feature column must not crash the
    detector and must not silently produce a flag from garbage arithmetic.
    NaN propagates through rolling mean/std/z-score; NaN >= Z_THRESHOLD is
    False, so affected days should fail to flag rather than flag incorrectly.
    """
    df = _flat_merchant_df(days=100)
    nan_idx = df[df["day"].between(40, 45)].index
    df.loc[nan_idx, "refund_rate"] = float("nan")

    scored = merchant_specific_drift(df)  # must not raise
    assert not scored["predicted_drift_ms"].isna().any(), "predicted_drift_ms must never itself be NaN"
    # The NaN days themselves must not be flagged off the back of the missing value
    assert scored[scored["day"].isin(range(40, 46))]["predicted_drift_ms"].sum() == 0


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_detector.py: {len(fns)} tests passed")
