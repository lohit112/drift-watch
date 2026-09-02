import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.case_builder import build_case
from agents.investigators import run_all_investigators


def _make_history(days=200, txn_count=50, refund_rate=0.03, dispute_rate=0.005,
                   category="apparel", geo="mumbai"):
    return pd.DataFrame({
        "merchant_id": ["M0001"] * days, "day": list(range(days)),
        "txn_count": [txn_count] * days, "txn_volume": [txn_count * 1000.0] * days,
        "refund_rate": [refund_rate] * days, "dispute_rate": [dispute_rate] * days,
        "dominant_category": [category] * days, "dominant_geo": [geo] * days,
    })


def test_case_has_evidence_for_both_hypotheses_structure():
    """Every case, regardless of outcome, must expose both hypotheses -
    the point of the product is competing explanations, not a bare verdict."""
    history = _make_history()
    case = build_case(history, flagged_day=100, deviant_signal_groups=["volume", "refund"])
    d = case.to_dict()
    assert "hypothesis_a_risk" in d and "hypothesis_b_legitimate" in d
    assert isinstance(d["evidence_for_a"], list)
    assert isinstance(d["evidence_for_b"], list)


def test_no_autonomous_high_impact_action_string():
    """The recommended action for ANY severity must never claim to autonomously
    suspend/restrict an account - only escalate/monitor/verify. This directly
    protects the 'no autonomous account action' product requirement."""
    history = _make_history()
    for signals in [["volume"], ["volume", "refund"], ["volume", "refund", "dispute"],
                     ["volume", "refund", "dispute", "category_mix"]]:
        case = build_case(history, flagged_day=100, deviant_signal_groups=signals)
        forbidden_terms = ["suspend", "terminate", "block account", "freeze account"]
        action_lower = case.recommended_action.lower()
        for term in forbidden_terms:
            assert term not in action_lower, (
                f"Recommended action must never autonomously suspend/terminate: got '{case.recommended_action}'"
            )


def test_audit_log_is_chronological_and_nonempty():
    history = _make_history()
    case = build_case(history, flagged_day=100, deviant_signal_groups=["volume", "refund"])
    assert len(case.audit_log) >= 4, "Expect at least: sentinel note, 4 investigator notes, correlator, case builder, routing"
    timestamps = [entry["timestamp"] for entry in case.audit_log]
    assert timestamps == sorted(timestamps), "Audit log must be in chronological order"


def test_confidence_is_bounded():
    history = _make_history()
    for signals in [[], ["volume"], ["volume", "refund", "dispute", "category_mix", "geo_mix"]]:
        case = build_case(history, flagged_day=100, deviant_signal_groups=signals)
        assert 0.0 <= case.confidence_risk <= 0.95, f"confidence_risk out of expected bounds: {case.confidence_risk}"


def test_investigators_return_four_findings():
    history = _make_history()
    findings = run_all_investigators(history, flagged_day=100)
    assert len(findings) == 4
    names = {f.investigator for f in findings}
    assert names == {"Transaction Investigator", "Dispute Investigator",
                      "Geography Investigator", "Merchant Profile Investigator"}


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_case_builder.py: {len(fns)} tests passed")
