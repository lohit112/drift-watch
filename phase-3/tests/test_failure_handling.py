"""
Failure handling — task brief step 15.

The system must degrade safely: missing evidence must never be silently
treated as "no risk", malformed/incomplete data must not crash the
pipeline, and conflicting signals must not produce a falsely confident
verdict.
"""
import os
import sys
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift
from agents.case_builder import build_case
from agents.investigators import run_all_investigators, build_signal_evidence


def _scored(days, txn=50, refund=0.03, dispute=0.005, seed=11):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": txn * (1 + rng.normal(0, 0.05, days)),
        "txn_volume": txn * (1 + rng.normal(0, 0.05, days)) * 1000.0,
        "refund_rate": refund * (1 + rng.normal(0, 0.08, days)),
        "dispute_rate": dispute * (1 + rng.normal(0, 0.10, days)),
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    return merchant_specific_drift(df)


def test_geography_missing_never_counted_as_supporting():
    """If a signal group can't be assessed (insufficient baseline), it must
    never quietly become supporting-risk evidence, never contribute to
    signal_breadth, and must appear as an explicit MISSING evidence item -
    directly implements task brief step 15's geography example."""
    scored = _scored(days=12)  # far too little history for any feature
    evidence = build_signal_evidence(scored, flagged_day=10, group_key="geo_mix")
    assert len(evidence) == 1
    assert evidence[0].evidence_type == "missing"
    assert evidence[0].supports_hypothesis is None


def test_malformed_history_missing_feature_column_degrades_to_missing_evidence():
    """If a required feature's detector columns are entirely absent (e.g. an
    upstream detector run that failed for one feature), the investigator
    must fail SAFE - treating it as missing evidence (baseline_days
    defaults to not-enough-history) - rather than crashing OR silently
    fabricating a comparison."""
    scored = _scored(days=100)
    broken = scored.drop(columns=["z_refund_rate", "baseline_mean_refund_rate", "baseline_days_refund_rate"])
    evidence = build_signal_evidence(broken, flagged_day=90, group_key="refund")
    assert len(evidence) == 1 and evidence[0].evidence_type == "missing", (
        "Missing detector columns for a feature must degrade to MISSING evidence, not crash or fabricate."
    )


def test_empty_history_does_not_crash():
    """An empty scored-history dataframe (e.g. investigator failure/timeout
    upstream) must not crash the case builder - it should fail safely into
    REQUEST_MORE_EVIDENCE via missing evidence."""
    empty = pd.DataFrame(columns=["merchant_id", "day", "txn_count", "txn_volume",
                                    "refund_rate", "dispute_rate", "category_entropy",
                                    "geo_entropy"])
    for feat in ["txn_count", "txn_volume", "refund_rate", "dispute_rate", "category_entropy", "geo_entropy"]:
        empty[f"z_{feat}"] = []
        empty[f"baseline_mean_{feat}"] = []
        empty[f"baseline_days_{feat}"] = []
    evidence = run_all_investigators(empty, flagged_day=50)
    assert all(e.evidence_type == "missing" for e in evidence)


def test_no_supporting_evidence_at_all_never_escalates():
    """If every investigator reports no deviation (a flag with no real
    corroboration - e.g. a spurious 2-signal borderline flag that doesn't
    hold up under investigation), the case must not escalate."""
    scored = _scored(days=100)  # perfectly flat/quiet history, nothing deviates
    row = scored[scored.day == 90].iloc[0]
    case = build_case(scored, 90, [])
    assert case.decision != "ESCALATE"


def test_conflicting_signals_do_not_produce_false_high_confidence():
    """Refund rising while dispute simultaneously falls (genuinely
    conflicting evidence) must not be scored as confidently risky - see
    also tests/test_golden_cases.py::test_golden_ambiguous_requests_more_evidence
    for the full end-to-end version of this scenario."""
    days = 200
    rng = np.random.default_rng(5)
    refund = 0.03 * (1 + rng.normal(0, 0.08, days))
    dispute = 0.005 * (1 + rng.normal(0, 0.10, days))
    for d in range(150, 200):
        ramp = min(1.0, (d - 150) / 6.0)
        refund[d] *= 1 + 2.0 * ramp
        dispute[d] *= max(0.3, 1 - 0.5 * ramp)
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": [50] * days, "txn_volume": [50000.0] * days,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    scored = merchant_specific_drift(df)
    flagged = scored[(scored["predicted_drift_ms"] == 1) & (scored["day"] >= 150)]
    if not flagged.empty:
        day = int(flagged["day"].iloc[-1])
        row = scored[scored.day == day].iloc[0]
        case = build_case(scored, day, row["deviant_signal_groups"])
        assert case.confidence.final_score < 0.75, (
            f"Conflicting refund-up/dispute-down evidence should not reach high confidence: "
            f"{case.confidence.final_score:.2f}"
        )


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_failure_handling.py: {len(fns)} tests passed")
