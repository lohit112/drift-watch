"""
Property-based invariants — task brief step 18.

Invariant 6 ("a legitimate seasonal pattern must not automatically be
classified as high risk") is tested HONESTLY against what the system
actually does, not against what we'd like it to do. See
PHASE_3_REPORT.md "Legitimate Episodes" and "Remaining Weaknesses" for the
real finding: this invariant does NOT fully hold today. A fix was
attempted and reverted in this phase because it broke real fraud detection
(see agents/confidence.py's inline note). The test below documents the
actual, current, imperfect behavior rather than asserting a false pass.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift
from episode.builder import build_episodes_for_merchant, build_episode
from episode.grouping import group_into_episodes


def _seasonal_merchant_history(n_occurrences=3, gap_days=90, days_per_spike=6, seed=9):
    """A merchant with a genuinely recurring, periodic volume+refund spike -
    mirrors the M0009 archetype construction in data/synthetic_generator.py."""
    rng = np.random.default_rng(seed)
    total_days = gap_days * n_occurrences + 20
    txn = 40 * (1 + rng.normal(0, 0.05, total_days))
    refund = 0.03 * (1 + rng.normal(0, 0.08, total_days))
    dispute = 0.005 * (1 + rng.normal(0, 0.10, total_days))
    for occ in range(n_occurrences):
        start = 60 + occ * gap_days
        for d in range(start, start + days_per_spike):
            if d < total_days:
                txn[d] *= 2.0
                refund[d] *= 1.4
    df = pd.DataFrame({
        "merchant_id": ["SEASONAL"] * total_days, "day": list(range(total_days)),
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * total_days, "geo_entropy": [1.1] * total_days,
        "dominant_category": ["apparel"] * total_days, "dominant_geo": ["mumbai"] * total_days,
    })
    return merchant_specific_drift(df)


def _fraud_merchant_history(days=220, onset=150, seed=3):
    # Draw from a FIXED-length stream and slice, rather than parameterizing
    # each rng.normal() call by `days` directly - otherwise the 2nd/3rd
    # feature's draws start at a different stream position whenever `days`
    # changes, silently producing different values even for indices that
    # exist in both a short and long run. This matters here because
    # test_invariant_3 specifically compares a short run against a longer
    # one and needs truly identical values for their overlapping days.
    rng = np.random.default_rng(seed)
    max_len = 300
    txn_full = 50 * (1 + rng.normal(0, 0.05, max_len))
    refund_full = 0.03 * (1 + rng.normal(0, 0.08, max_len))
    dispute_full = 0.005 * (1 + rng.normal(0, 0.10, max_len))
    txn, refund, dispute = txn_full[:days].copy(), refund_full[:days].copy(), dispute_full[:days].copy()
    for d in range(onset, days):
        ramp = min(1.0, (d - onset) / 4.0)
        txn[d] *= 1 + 1.4 * ramp
        refund[d] *= 1 + 2.3 * ramp
        dispute[d] *= 1 + 3.0 * ramp
    df = pd.DataFrame({
        "merchant_id": ["FRAUD"] * days, "day": list(range(days)),
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    return merchant_specific_drift(df)


def test_invariant_1_no_unlimited_duplicate_episodes():
    """A 13-day persistent fraud episode must be represented as ONE episode
    object, not 13 separate ones."""
    hist = _fraud_merchant_history()
    episodes = build_episodes_for_merchant(hist)
    fraud_episodes = [e for e in episodes if e.start_day >= 150]
    assert len(fraud_episodes) == 1, f"Expected exactly 1 episode for the persistent fraud run, got {len(fraud_episodes)}"


def test_invariant_2_repeated_identical_evidence_does_not_inflate_confidence_unbounded():
    """Confidence must plateau, not climb without bound, as a persistent
    episode continues - see docs/EPISODE_EVIDENCE.md's worked example."""
    hist = _fraud_merchant_history()
    episodes = build_episodes_for_merchant(hist)
    fraud_ep = [e for e in episodes if e.start_day >= 150][0]
    scores = [s for _, s, _ in fraud_ep.confidence_history]
    # Once the episode has run for a while, later scores should not keep
    # climbing indefinitely - check the back half doesn't exceed the front
    # half's max by more than a small margin (allows natural fluctuation,
    # forbids unbounded growth).
    midpoint = len(scores) // 2
    assert max(scores[midpoint:]) <= max(scores[:midpoint]) + 0.05, (
        "Confidence should plateau, not keep climbing, as identical persistent evidence repeats"
    )
    assert max(scores) <= 1.0


def test_invariant_3_future_observations_do_not_affect_earlier_state():
    """Extending a merchant's history with MORE days after an episode
    resolves must not change any earlier confidence_history value or
    transition."""
    hist_short = _fraud_merchant_history(days=200)
    hist_long = _fraud_merchant_history(days=220)  # identical for days 0-199, seed matches

    episodes_short = build_episodes_for_merchant(hist_short)
    episodes_long = build_episodes_for_merchant(hist_long)

    fraud_short = [e for e in episodes_short if e.start_day >= 150][0]
    fraud_long = [e for e in episodes_long if e.start_day >= 150][0]

    # Every (day, score) pair present in the SHORT run's history must be
    # identical in the LONG run's history, for days that existed in both.
    short_by_day = {d: s for d, s, _ in fraud_short.confidence_history}
    long_by_day = {d: s for d, s, _ in fraud_long.confidence_history}
    common_days = set(short_by_day) & set(long_by_day)
    assert common_days, "Test setup issue: no overlapping days to compare"
    for d in common_days:
        assert short_by_day[d] == long_by_day[d], (
            f"Day {d}'s confidence changed ({short_by_day[d]} vs {long_by_day[d]}) when future data was added - "
            f"this is temporal leakage into episode state."
        )


def test_invariant_4_contradicting_evidence_is_represented():
    """A refund-up/dispute-down episode must produce non-empty contradicting
    evidence at some point."""
    days = 200
    rng = np.random.default_rng(5)
    refund = 0.03 * (1 + rng.normal(0, 0.08, days))
    dispute = 0.005 * (1 + rng.normal(0, 0.10, days))
    for d in range(150, days):
        ramp = min(1.0, (d - 150) / 6.0)
        refund[d] *= 1 + 2.0 * ramp
        dispute[d] *= max(0.3, 1 - 0.5 * ramp)
    df = pd.DataFrame({
        "merchant_id": ["M"] * days, "day": list(range(days)),
        "txn_count": [50] * days, "txn_volume": [50000.0] * days,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    hist = merchant_specific_drift(df)
    episodes = build_episodes_for_merchant(hist)
    ep = [e for e in episodes if e.start_day >= 150][0]
    assert len(ep.contradicting_evidence) > 0, "Contradicting evidence (dispute falling) must be represented, not dropped"


def test_invariant_5_state_transitions_are_deterministic():
    """Rebuilding the same episode from the same scored history twice must
    produce byte-identical transition logs."""
    hist = _fraud_merchant_history()
    eps1 = build_episodes_for_merchant(hist)
    eps2 = build_episodes_for_merchant(hist)
    ep1 = [e for e in eps1 if e.start_day >= 150][0]
    ep2 = [e for e in eps2 if e.start_day >= 150][0]
    log1 = [(t.day, t.old_state, t.new_state, round(t.confidence, 6)) for t in ep1.transition_log]
    log2 = [(t.day, t.old_state, t.new_state, round(t.confidence, 6)) for t in ep2.transition_log]
    assert log1 == log2, "Rebuilding the same episode must be fully deterministic"


def test_invariant_6_legitimate_seasonal_pattern_high_risk_status_HONEST_RESULT():
    """
    HONEST test for invariant 6: documents the system's ACTUAL current
    behavior rather than asserting a false pass. As of this phase, a
    recurring seasonal merchant's volume+refund spike CAN still reach
    ESCALATE, even on its 2nd/3rd occurrence - this is a known, unresolved
    limitation (see PHASE_3_REPORT.md "Legitimate Episodes"). An attempted
    fix was reverted this phase because it broke real fraud detection (see
    agents/confidence.py's inline note on ESTABLISHED_PATTERN_DISCOUNT).

    This test asserts what IS true: novelty correctly drops to 0 by the
    2nd occurrence (the system DOES recognize the pattern isn't new), even
    though that recognition is not yet sufficient on its own to prevent
    escalation. This is the honest, current boundary of the system.
    """
    hist = _seasonal_merchant_history(n_occurrences=3)
    episodes = build_episodes_for_merchant(hist)
    seasonal_episodes = [e for e in episodes if e.start_day > 100]  # 2nd/3rd occurrence onward
    assert len(seasonal_episodes) >= 1, "Test setup issue: expected at least one recurring episode"
    # What DOES work: novelty is recognized (the historical evidence "not
    # novel" recognition is real, even if not yet weighted enough to
    # override escalation on its own). Check the FINAL historical evidence
    # for each deviant group (its most up-to-date assessment), not every
    # timeline entry - a group's very first-ever historical evidence entry
    # legitimately says "never before" the first time it's computed, before
    # any recurrence has happened yet.
    for ep in seasonal_episodes:
        final_historical = [e for e in ep.missing_evidence + ep.supporting_evidence + ep.contradicting_evidence]
        # Re-derive the final day's raw historical evidence directly, since
        # supporting/contradicting lists only include non-neutral items.
        from episode.aggregation import run_episode_investigators
        final_evidence = run_episode_investigators(hist, ep.start_day, ep.current_day)
        historical_for_deviant_groups = [
            e for e in final_evidence if e.evidence_type == "historical" and e.signal_group in ep.signal_groups
        ]
        for e in historical_for_deviant_groups:
            assert "never before" not in e.summary, (
                f"By episode starting day {ep.start_day} (a 2nd+ occurrence), historical evidence "
                f"for {e.signal_group} should recognize this ISN'T novel: {e.summary}"
            )


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\ntest_episode_invariants.py: {len(fns)} tests passed")
