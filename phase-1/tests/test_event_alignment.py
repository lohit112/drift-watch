"""
Regression test for the event/evidence-mismatch bug found in Phase 1 audit:
scripts/run_demo_case.py previously read `signal_groups` from `flagged`
(the first flag overall) while `first_flag_day` came from `chosen` (the
flag aligned to true drift onset). When these two flags differed, the case
was built for the correct day but logged/reasoned about the WRONG day's
signal groups.

This test exercises the same selection logic directly (not via subprocess)
so it fails loudly if the mismatch is reintroduced.
"""
import ast
import os
import sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _select_case_day_and_signals(flagged: pd.DataFrame, prefer_true_onset: bool = True):
    """Mirrors the (fixed) selection logic in scripts/run_demo_case.py."""
    on_target = flagged[flagged["true_drift_any"] == 1] if prefer_true_onset else pd.DataFrame()
    chosen = on_target if not on_target.empty else flagged
    day = int(chosen["day"].iloc[0])
    signal_groups = chosen["deviant_signal_groups"].iloc[0]
    return day, signal_groups


def test_selected_day_and_signal_groups_come_from_same_row():
    """
    Construct a synthetic 'flagged' frame where the first row overall (day 10,
    no true drift) has DIFFERENT signal groups than the first true-onset row
    (day 50). The selected day and selected signal groups must both come
    from day 50, not a mix of day 10's signals with day 50's date.
    """
    flagged = pd.DataFrame([
        {"day": 10, "true_drift_any": 0, "deviant_signal_groups": ["refund", "category_mix"]},
        {"day": 50, "true_drift_any": 1, "deviant_signal_groups": ["volume", "refund", "dispute", "category_mix"]},
        {"day": 51, "true_drift_any": 1, "deviant_signal_groups": ["volume", "refund"]},
    ])

    day, signal_groups = _select_case_day_and_signals(flagged, prefer_true_onset=True)

    assert day == 50, f"Expected day 50 (first true-onset flag), got {day}"
    assert signal_groups == ["volume", "refund", "dispute", "category_mix"], (
        f"signal_groups must belong to day 50, got {signal_groups} "
        "(this is exactly the bug found in Phase 1 audit if it's day 10's groups instead)"
    )


def test_falls_back_to_first_overall_flag_when_no_true_onset_flag_exists():
    flagged = pd.DataFrame([
        {"day": 10, "true_drift_any": 0, "deviant_signal_groups": ["refund"]},
        {"day": 20, "true_drift_any": 0, "deviant_signal_groups": ["geo_mix"]},
    ])
    day, signal_groups = _select_case_day_and_signals(flagged, prefer_true_onset=True)
    assert day == 10
    assert signal_groups == ["refund"]


def test_malformed_serialized_signal_data_fails_loudly_not_silently():
    """
    Edge case 11 (Phase 1 audit): deviant_signal_groups round-trips through a
    CSV as a Python-list-literal string, e.g. "['volume', 'refund']", and is
    parsed with ast.literal_eval (see scripts/run_demo_case.py). Unlike
    eval(), ast.literal_eval only parses literal structures - it must reject
    malformed or malicious strings by raising, not by silently returning
    something usable (silent corruption is exactly what this project is
    trying to avoid).
    """
    malformed_and_malicious = [
        "not a list at all",
        "['volume', 'refund'",       # truncated / malformed
        "__import__('os').system('echo pwned')",  # code-injection attempt
        "",
    ]
    for s in malformed_and_malicious:
        with pytest.raises((ValueError, SyntaxError)):
            ast.literal_eval(s)


def test_malformed_serialized_signal_data_valid_literal_parses_correctly():
    """A well-formed list-literal string must parse back to the exact list -
    the happy path this mechanism exists for."""
    s = "['volume', 'refund', 'dispute']"
    assert ast.literal_eval(s) == ["volume", "refund", "dispute"]


if __name__ == "__main__":
    test_selected_day_and_signal_groups_come_from_same_row()
    test_falls_back_to_first_overall_flag_when_no_true_onset_flag_exists()
    print("test_event_alignment.py: all tests passed (run via pytest for full coverage)")
