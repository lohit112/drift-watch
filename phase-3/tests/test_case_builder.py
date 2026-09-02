import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.case_builder import build_case
from agents.investigators import run_all_investigators
from detection.drift_detector import merchant_specific_drift


def _make_scored_history(days=200, txn_count=50, refund_rate=0.03, dispute_rate=0.005,
                          category="apparel", geo="mumbai", spike_day=None, spike_mult=3.0,
                          seed=7):
    """Builds a flat merchant history with a little realistic noise (so
    rolling std isn't zero), optionally injects a spike on `spike_day`, and
    runs it through the REAL detector - matching how build_case is actually
    called in production (on the detector's own scored output, not raw
    data). See agents/investigators.py module docstring for why this
    matters."""
    rng = np.random.default_rng(seed)
    txn = txn_count * (1 + rng.normal(0, 0.05, days))
    refund = refund_rate * (1 + rng.normal(0, 0.08, days))
    dispute = dispute_rate * (1 + rng.normal(0, 0.10, days))
    if spike_day is not None:
        txn[spike_day] *= spike_mult
        refund[spike_day] *= spike_mult
        dispute[spike_day] *= spike_mult
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": [category] * days, "dominant_geo": [geo] * days,
    })
    return merchant_specific_drift(df)


def test_case_has_evidence_for_both_hypotheses_structure():
    """Every case, regardless of outcome, must expose both hypotheses -
    the point of the product is competing explanations, not a bare verdict."""
    history = _make_scored_history(spike_day=150, spike_mult=4.0)
    case = build_case(history, flagged_day=150, deviant_signal_groups=["volume", "refund"])
    d = case.to_dict()
    assert "hypothesis_a_risk" in d and "hypothesis_b_legitimate" in d
    assert isinstance(d["evidence_for_a"], list)
    assert isinstance(d["evidence_for_b"], list)
    assert d["decision"] in ("ESCALATE", "MONITOR", "REQUEST_MORE_EVIDENCE")


def test_no_autonomous_high_impact_action_string():
    """The recommended action for ANY decision must never claim to
    autonomously suspend/restrict an account - only escalate/monitor/verify/
    request more evidence. Directly protects the 'no autonomous account
    action' product requirement."""
    history = _make_scored_history(spike_day=150, spike_mult=4.0)
    for signals in [["volume"], ["volume", "refund"], ["volume", "refund", "dispute"],
                     ["volume", "refund", "dispute", "category_mix"]]:
        case = build_case(history, flagged_day=150, deviant_signal_groups=signals)
        forbidden_terms = ["suspend", "terminate", "block account", "freeze account"]
        action_lower = case.recommended_action.lower()
        for term in forbidden_terms:
            assert term not in action_lower, (
                f"Recommended action must never autonomously suspend/terminate: got '{case.recommended_action}'"
            )


def test_audit_log_is_chronological_and_nonempty():
    history = _make_scored_history(spike_day=150, spike_mult=4.0)
    case = build_case(history, flagged_day=150, deviant_signal_groups=["volume", "refund"])
    assert len(case.audit_log) >= 4, "Expect at least: sentinel note, investigator notes, correlator, decision, routing"
    timestamps = [entry["timestamp"] for entry in case.audit_log]
    assert timestamps == sorted(timestamps), "Audit log must be in chronological order"


def test_confidence_is_bounded():
    history = _make_scored_history(spike_day=150, spike_mult=4.0)
    for signals in [[], ["volume"], ["volume", "refund", "dispute", "category_mix", "geo_mix"]]:
        case = build_case(history, flagged_day=150, deviant_signal_groups=signals)
        score = case.confidence.final_score
        assert 0.0 <= score <= 1.0, f"Risk Confidence Score out of bounds: {score}"


def test_investigators_return_five_signal_groups():
    """Phase 2: one investigator per independent signal group (volume, refund,
    dispute, category_mix, geo_mix) - refund now has its own investigator,
    which Phase 1 did not (a real, previously undocumented gap - see
    PHASE_2_REPORT.md)."""
    history = _make_scored_history(spike_day=150, spike_mult=4.0)
    evidence = run_all_investigators(history, flagged_day=150)
    groups = {e.signal_group for e in evidence}
    assert groups == {"volume", "refund", "dispute", "category_mix", "geo_mix"}
    sources = {e.source for e in evidence}
    assert sources == {"Volume Investigator", "Refund Investigator", "Dispute Investigator",
                        "Category Investigator", "Geography Investigator"}


def test_missing_evidence_never_silently_counted_as_no_risk():
    """A merchant flagged before it has enough baseline history must produce
    MISSING evidence (not silently-false 'no deviation') and the case must
    route to REQUEST_MORE_EVIDENCE, never a confident MONITOR/legitimate
    verdict built on evidence that was never actually gathered."""
    history = _make_scored_history(days=25, spike_day=10, spike_mult=5.0)
    case = build_case(history, flagged_day=10, deviant_signal_groups=["volume"])
    assert len(case.evidence_missing) > 0, "Expected missing evidence with only 10 days of prior history"
    assert case.decision == "REQUEST_MORE_EVIDENCE"


def test_strong_multi_signal_fraud_pattern_escalates_once_persistence_confirms():
    """A strong, multi-day, multi-signal spike (mirroring the fraud
    archetype's ramp) should reach ESCALATE once contextual (3d/7d) windows
    confirm the deviation persists - not just on the single trigger day.
    This is the resolution to the Phase 1 §9 finding: the fix is not to
    force agreement, but to let persistence (not just the trigger) drive
    confidence up over the following days."""
    days = 200
    rng = np.random.default_rng(3)
    txn = 50 * (1 + rng.normal(0, 0.05, days))
    refund = 0.03 * (1 + rng.normal(0, 0.08, days))
    dispute = 0.005 * (1 + rng.normal(0, 0.10, days))
    spike_start = 150
    for d in range(spike_start, spike_start + 8):
        ramp = min(1.0, (d - spike_start) / 4.0)
        txn[d] *= 1 + 1.4 * ramp
        refund[d] *= 1 + 2.3 * ramp
        dispute[d] *= 1 + 3.0 * ramp
    df = pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    scored = merchant_specific_drift(df)
    day3 = scored[scored.day == spike_start + 3].iloc[0]
    case = build_case(scored, spike_start + 3, day3["deviant_signal_groups"])
    assert case.decision == "ESCALATE", (
        f"Expected ESCALATE by day 3 of a sustained multi-signal spike, got {case.decision} "
        f"(score={case.confidence.final_score:.2f})"
    )


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_case_builder.py: {len(fns)} tests passed")
