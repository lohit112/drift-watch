"""
Runs the full Drift Watch loop end-to-end on one synthetic fraud-drift
merchant: Sentinel detection -> Investigators -> Evidence Correlator ->
Case Builder -> printed case (what the UI would render).

Also runs the same pipeline on a seasonal-spike merchant to demonstrate
that the system correctly favors Hypothesis B (legitimate) rather than
flagging every anomaly as fraud.
"""
import ast
import json
import sys
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import pandas as pd
from detection.drift_detector import merchant_specific_drift
from agents.case_builder import build_case


def run_for_merchant(scored: pd.DataFrame, merchant_id: str, label: str, prefer_true_onset: bool = False):
    history = scored[scored["merchant_id"] == merchant_id].sort_values("day")
    flagged = history[history["predicted_drift_ms"] == 1]
    print(f"\n{'=' * 70}\n{label}: {merchant_id} ({history['archetype'].iloc[0]})\n{'=' * 70}")
    if flagged.empty:
        print("No drift flagged for this merchant.")
        return

    # Prefer a flag that coincides with the labeled drift window, so the demo
    # shows the real event rather than an incidental early noise-flag.
    on_target = flagged[flagged["true_drift_any"] == 1] if prefer_true_onset else pd.DataFrame()
    chosen = on_target if not on_target.empty else flagged
    first_flag_day = int(chosen["day"].iloc[0])
    # BUGFIX (Phase 1 audit): this previously read from `flagged` (the first
    # flag overall) instead of `chosen` (the selected flag), so the signal
    # groups reported/logged could belong to a different, earlier day than
    # the one the case was actually built for. See PHASE_1_REPORT.md.
    signal_groups = chosen["deviant_signal_groups"].iloc[0]
    if isinstance(signal_groups, str):
        # CSV round-trip produces a Python-list literal string, e.g. "['volume', 'refund']".
        # ast.literal_eval only parses literal Python structures (no code execution),
        # unlike eval() which was used here previously - see PHASE_1_REPORT.md.
        signal_groups = ast.literal_eval(signal_groups)

    # PHASE 2: pass the DETECTOR'S OWN SCORED history (not raw), so
    # investigators build trigger evidence from the exact numbers the
    # detector flagged on - see PHASE_1_REPORT.md §9 / docs/EVIDENCE_MODEL.md.
    case = build_case(history, first_flag_day, signal_groups)
    print(json.dumps(case.to_dict(), indent=2, default=str))


if __name__ == "__main__":
    raw = pd.read_csv(os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv"))
    scored = merchant_specific_drift(raw)

    # pick the fraud-drift merchant that actually gets flagged during its true drift window
    fraud_ids = raw[raw["drift_kind"] == "fraud"]["merchant_id"].unique()
    fraud_merchant = None
    for mid in fraud_ids:
        sub = scored[scored["merchant_id"] == mid]
        if ((sub["predicted_drift_ms"] == 1) & (sub["true_drift_any"] == 1)).any():
            fraud_merchant = mid
            break
    fraud_merchant = fraud_merchant or fraud_ids[0]
    run_for_merchant(scored, fraud_merchant, "DEMO CASE 1 (should favor Hypothesis A - risk)", prefer_true_onset=True)

    # Note: seasonal spikes are intentionally NOT labeled true_drift in the generator
    # (they're the legitimate-explanation case, not a labeled risk event) - so we just
    # take the first flag, which naturally lands inside the spike window by construction.
    seasonal_candidates = scored[(scored["archetype"] == "seasonal") & (scored["predicted_drift_ms"] == 1)]
    if not seasonal_candidates.empty:
        seasonal_merchant = seasonal_candidates["merchant_id"].iloc[0]
        run_for_merchant(scored, seasonal_merchant, "DEMO CASE 2 (should favor Hypothesis B - legitimate)")
    else:
        print("\n(No seasonal merchant crossed the flag threshold in this run - "
              "expected, since Drift Watch is tuned for precision; see evaluation/results.csv)")
