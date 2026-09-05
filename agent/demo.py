"""
CLI demo (Phase 4) — task brief step 18.

Usage:
    python3 -m agent.demo --merchant M0021

Every number in the output comes from an actual run of InvestigationLoop
against the real scored dataset - nothing here is hardcoded or fabricated.
"""
import argparse
import os
import sys

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from detection.drift_detector import merchant_specific_drift
from episode.builder import build_episodes_for_merchant
from agent.loop import InvestigationLoop


def run_demo(merchant_id: str):
    raw = pd.read_csv(os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv"))
    scored = merchant_specific_drift(raw)
    hist = scored[scored["merchant_id"] == merchant_id]
    if hist.empty:
        print(f"No data found for merchant {merchant_id}.")
        return

    episodes = build_episodes_for_merchant(hist)
    if not episodes:
        print(f"No episodes found for merchant {merchant_id} (never flagged).")
        return

    episode = max(episodes, key=lambda e: e.peak_score)  # the most notable episode for this merchant

    print("=" * 70)
    print("DRIFT WATCH - AI INVESTIGATION (Phase 4, deterministic/mock planner+synthesis)")
    print("=" * 70)
    print(f"\nEpisode:\n    {merchant_id}\n    Start: day {episode.start_day}\n"
          f"    Peak confidence (Phase 3 deterministic episode score): {episode.peak_score:.2f} on day {episode.peak_day}\n"
          f"    Phase 3 status at resolution: {episode.status}")

    print("\nInitial hypotheses:")
    print("    RISK_DRIFT")
    print("    LEGITIMATE_GROWTH")
    print("    SEASONAL_PATTERN")
    print("    INSUFFICIENT_EVIDENCE")

    loop = InvestigationLoop()
    result = loop.run(episode, hist)

    for record in result.tool_call_records:
        print(f"\nPlanner:")
        planner_events = [e for e in result.audit_trail.events() if e.event_type == "planner_decision"]
        matching = [e for e in planner_events if e.detail.get("selected_tool") == record.tool_name]
        reason = matching[0].detail["reason"] if matching else record.question
        print(f"    {reason}")
        print(f"\nTool:\n    {record.tool_name}")
        if record.status.value == "SUCCESS":
            print(f"\nEvidence:")
            for eid in record.evidence_ids_produced:
                ev = result.registry.get(eid)
                print(f"    {eid}  [{ev.evidence_type}] {ev.interpretation}")
        else:
            print(f"\nTool failed: {record.failure_reason.value if record.failure_reason else 'unknown'}")

    print("\nFinal hypothesis scores:")
    for label, h in result.hypothesis_state.to_dict().items():
        print(f"    {label:22s} {h['support_score']:.3f}  ({h['status']})")

    print(f"\nFinal assessment:\n    {result.synthesized_case.leading_hypothesis}")
    print(f"\nRecommendation:\n    {result.synthesized_case.recommendation.value}")
    print(f"\nApproval:\n    {result.approval_status.value}")

    audit_events = result.audit_trail.events()
    n_tools = len(set(t.tool_name for t in result.tool_call_records))
    print(f"\nAudit:\n    {len(audit_events)} investigation events\n"
          f"    {n_tools} tool(s) used\n"
          f"    {len(result.registry)} evidence item(s)")
    print(f"\nCase narrative:\n    {result.synthesized_case.narrative}")
    print("\n" + "=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drift Watch AI Investigation demo")
    parser.add_argument("--merchant", required=True, help="Merchant ID, e.g. M0021")
    args = parser.parse_args()
    run_demo(args.merchant)
