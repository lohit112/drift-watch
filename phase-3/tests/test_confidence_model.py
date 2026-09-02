"""
Unit tests for agents/confidence.py — task brief step 12's required test
matrix: weak signal, strong signal, multiple independent signals, correlated
signals, contradictory evidence, missing evidence, strong legitimate
explanation. These test the confidence math directly against hand-built
Evidence lists (not through the full detector pipeline), so each scenario
is isolated and unambiguous about which component it's exercising.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.evidence import Evidence
from agents.confidence import compute_confidence, decide_action


def _ev(signal_group, evidence_type, deviation, supports, contradicts, confidence=0.6):
    return Evidence(
        source=f"{signal_group} test", signal_group=signal_group, evidence_type=evidence_type,
        observation=1.0, baseline=0.5, deviation=deviation, time_window="test",
        direction="up" if (deviation or 0) > 0 else "n/a",
        strength="strong" if deviation and abs(deviation) >= 4 else "moderate",
        supports_hypothesis=supports, contradicts_hypothesis=contradicts, confidence=confidence,
        summary="test evidence",
    )


def test_weak_signal_yields_low_confidence():
    evidence = [
        _ev("volume", "trigger", 2.6, "A", "B"),
        _ev("volume", "contextual", 1.0, None, None),
        _ev("volume", "historical", None, None, None),
    ]
    c = compute_confidence(evidence)
    # 1 of 5 independent groups deviating, barely over threshold, with no
    # persistence support - should land well below the ESCALATE threshold.
    assert c.final_score < 0.62, f"A single weak (barely-threshold) signal should not reach ESCALATE territory: {c.final_score}"
    decision, _, _ = decide_action(c)
    assert decision != "ESCALATE"


def test_strong_signal_yields_higher_confidence_than_weak():
    weak = [_ev("volume", "trigger", 2.6, "A", "B")]
    strong = [_ev("volume", "trigger", 8.0, "A", "B")]
    c_weak = compute_confidence(weak)
    c_strong = compute_confidence(strong)
    assert c_strong.anomaly_strength > c_weak.anomaly_strength
    assert c_strong.final_score >= c_weak.final_score


def test_multiple_independent_signals_score_higher_than_one():
    one_group = [_ev("volume", "trigger", 5.0, "A", "B")]
    five_groups = [_ev(g, "trigger", 5.0, "A", "B")
                   for g in ["volume", "refund", "dispute", "category_mix", "geo_mix"]]
    c_one = compute_confidence(one_group)
    c_five = compute_confidence(five_groups)
    assert c_five.signal_breadth > c_one.signal_breadth
    assert c_five.final_score > c_one.final_score


def test_contradictory_evidence_pulls_confidence_down():
    supporting_only = [_ev("volume", "trigger", 5.0, "A", "B"),
                        _ev("refund", "trigger", 5.0, "A", "B")]
    with_contradiction = supporting_only + [
        _ev("dispute", "contradicting", -0.5, "B", "A"),
        _ev("category_mix", "contradicting", -0.2, "B", "A"),
        _ev("geo_mix", "contradicting", -0.1, "B", "A"),
    ]
    c_clean = compute_confidence(supporting_only)
    c_contradicted = compute_confidence(with_contradiction)
    assert c_contradicted.evidence_balance < c_clean.evidence_balance
    assert c_contradicted.final_score < c_clean.final_score


def test_missing_evidence_caps_confidence_and_forces_request_more_evidence():
    evidence = [
        _ev("volume", "trigger", 8.0, "A", "B"),
        _ev("refund", "trigger", 8.0, "A", "B"),
        Evidence(source="Dispute test", signal_group="dispute", evidence_type="missing",
                 observation=None, baseline=None, deviation=None, time_window="n/a",
                 direction="n/a", strength="n/a", supports_hypothesis=None,
                 contradicts_hypothesis=None, confidence=0.0, summary="missing"),
    ]
    c = compute_confidence(evidence)
    assert c.final_score <= 0.75, "Any missing evidence must cap confidence per MAX_CONFIDENCE_WITH_ANY_MISSING"
    decision, severity, action = decide_action(c)
    assert decision == "REQUEST_MORE_EVIDENCE"


def test_strong_legitimate_explanation_yields_low_or_ambiguous_not_escalate():
    """All evidence pointing to B (legitimate) - confidence in A must be low
    enough that decide_action never returns ESCALATE."""
    evidence = [_ev(g, "contradicting", -0.5, "B", "A")
                for g in ["volume", "refund", "dispute", "category_mix", "geo_mix"]]
    c = compute_confidence(evidence)
    decision, severity, action = decide_action(c)
    assert decision != "ESCALATE"


def test_confidence_never_exceeds_bounds():
    extreme = [_ev(g, "trigger", 50.0, "A", "B")
               for g in ["volume", "refund", "dispute", "category_mix", "geo_mix"]] * 5
    c = compute_confidence(extreme)
    assert 0.0 <= c.final_score <= 1.0


def test_no_evidence_at_all_is_low_confidence_not_crash():
    """No evidence at all should never crash, and should land at a low,
    non-committal score (a neutral evidence_balance prior of 0.5 still
    contributes a small amount by design - see compute_confidence - so this
    is intentionally 'low', not exactly zero)."""
    c = compute_confidence([])
    assert c.final_score <= 0.15
    decision, severity, action = decide_action(c)
    assert decision == "MONITOR"


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_confidence_model.py: {len(fns)} tests passed")
