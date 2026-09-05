"""
Golden cases — task brief step 14.

Three fully deterministic, reproducible scenarios that must always resolve
to a specific decision. These are the project's canonical "does the whole
loop actually work" regression tests: detector -> investigators -> evidence
-> confidence -> decision, run end to end.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift
from agents.case_builder import build_case

DAYS = 220


def _build(rng_seed, txn_fn, refund_fn, dispute_fn, cat_fn=None, geo_fn=None):
    rng = np.random.default_rng(rng_seed)
    days = np.arange(DAYS)
    txn = np.array([txn_fn(d, rng) for d in days])
    refund = np.array([refund_fn(d, rng) for d in days])
    dispute = np.array([dispute_fn(d, rng) for d in days])
    cat_entropy = np.array([cat_fn(d) if cat_fn else 1.2 for d in days])
    geo_entropy = np.array([geo_fn(d) if geo_fn else 1.1 for d in days])
    df = pd.DataFrame({
        "merchant_id": ["GOLDEN"] * DAYS, "day": days,
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": cat_entropy, "geo_entropy": geo_entropy,
        "dominant_category": ["apparel"] * DAYS, "dominant_geo": ["mumbai"] * DAYS,
    })
    return merchant_specific_drift(df)


def test_golden_risk_escalates():
    """GOLDEN_RISK: long normal period (180 days), then a coordinated,
    persistent, multi-signal drift across volume + refund + dispute +
    category/geo - the clearest possible risk signature. Expected: ESCALATE
    (checked a few days into the drift, once persistence confirms it - see
    test_strong_multi_signal_fraud_pattern_escalates_once_persistence_confirms
    in test_case_builder.py for why day-1-only checks are intentionally not
    used as the golden assertion point)."""
    onset = 180

    def txn_fn(d, rng):
        base = 50 * (1 + rng.normal(0, 0.05))
        if d >= onset:
            ramp = min(1.0, (d - onset) / 4.0)
            base *= 1 + 1.4 * ramp
        return base

    def refund_fn(d, rng):
        base = 0.03 * (1 + rng.normal(0, 0.08))
        if d >= onset:
            ramp = min(1.0, (d - onset) / 4.0)
            base *= 1 + 2.3 * ramp
        return base

    def dispute_fn(d, rng):
        base = 0.005 * (1 + rng.normal(0, 0.10))
        if d >= onset:
            ramp = min(1.0, (d - onset) / 4.0)
            base *= 1 + 3.0 * ramp
        return base

    def cat_fn(d):
        return 0.4 if d >= onset else 1.2  # concentration into one category once drifted

    def geo_fn(d):
        return 0.4 if d >= onset else 1.1

    scored = _build(101, txn_fn, refund_fn, dispute_fn, cat_fn, geo_fn)
    check_day = onset + 4  # a few days in, so contextual/persistence evidence exists
    row = scored[scored.day == check_day].iloc[0]
    case = build_case(scored, check_day, row["deviant_signal_groups"])
    assert case.decision == "ESCALATE", (
        f"GOLDEN_RISK expected ESCALATE, got {case.decision} (score={case.confidence.final_score:.2f})"
    )
    assert case.severity in ("medium", "high")


def test_golden_legitimate_does_not_escalate():
    """GOLDEN_LEGITIMATE: a clean single-signal volume spike (e.g. a sale) -
    volume up sharply, but refund/dispute/category/geo all completely flat.
    Expected: NOT ESCALATE (either MONITOR or, if the single-signal pattern
    is ambiguous enough, REQUEST_MORE_EVIDENCE - but never a confident
    risk escalation off one clean signal with everything else quiet)."""
    onset = 180

    def txn_fn(d, rng):
        base = 50 * (1 + rng.normal(0, 0.05))
        if d >= onset:
            base *= 2.2  # clean, large, one-off volume jump
        return base

    def refund_fn(d, rng):
        return 0.03 * (1 + rng.normal(0, 0.08))  # untouched

    def dispute_fn(d, rng):
        return 0.005 * (1 + rng.normal(0, 0.10))  # untouched

    scored = _build(202, txn_fn, refund_fn, dispute_fn)
    flagged = scored[(scored["predicted_drift_ms"] == 1) & (scored["day"] >= onset)]
    assert not flagged.empty, "Test setup issue: the volume spike should trip the detector"
    day = int(flagged["day"].iloc[0])
    row = scored[scored.day == day].iloc[0]
    case = build_case(scored, day, row["deviant_signal_groups"])
    assert case.decision != "ESCALATE", (
        f"GOLDEN_LEGITIMATE must not escalate on a clean single-signal volume spike, "
        f"got {case.decision} (score={case.confidence.final_score:.2f})"
    )


def test_golden_ambiguous_requests_more_evidence():
    """GOLDEN_AMBIGUOUS: conflicting evidence - refund rises sharply (looks
    risky) while dispute simultaneously falls (looks reassuring), mirroring
    the "contradictory_evidence" archetype in the richer benchmark. Expected:
    REQUEST_MORE_EVIDENCE, not a confident verdict either way."""
    onset = 180

    def txn_fn(d, rng):
        return 50 * (1 + rng.normal(0, 0.05))  # flat

    def refund_fn(d, rng):
        base = 0.03 * (1 + rng.normal(0, 0.08))
        if d >= onset:
            ramp = min(1.0, (d - onset) / 6.0)
            base *= 1 + 2.0 * ramp
        return base

    def dispute_fn(d, rng):
        base = 0.005 * (1 + rng.normal(0, 0.10))
        if d >= onset:
            ramp = min(1.0, (d - onset) / 6.0)
            base *= max(0.3, 1 - 0.5 * ramp)  # falls while refund rises
        return base

    scored = _build(303, txn_fn, refund_fn, dispute_fn)
    flagged = scored[(scored["predicted_drift_ms"] == 1) & (scored["day"] >= onset)]
    assert not flagged.empty, "Test setup issue: the refund spike should trip the detector"
    day = int(flagged["day"].iloc[-1])  # a later flagged day, once refund fully ramped
    row = scored[scored.day == day].iloc[0]
    case = build_case(scored, day, row["deviant_signal_groups"])
    assert case.decision == "REQUEST_MORE_EVIDENCE", (
        f"GOLDEN_AMBIGUOUS expected REQUEST_MORE_EVIDENCE, got {case.decision} "
        f"(score={case.confidence.final_score:.2f}, support_a={case.confidence.n_support_a}, "
        f"support_b={case.confidence.n_support_b})"
    )


if __name__ == "__main__":
    test_golden_risk_escalates()
    test_golden_legitimate_does_not_escalate()
    test_golden_ambiguous_requests_more_evidence()
    print("test_golden_cases.py: 3 golden cases passed")
