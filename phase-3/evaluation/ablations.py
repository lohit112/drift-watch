"""
Ablation experiments — task brief step 16.

A note on what's actually ablatable here: the DETECTOR's flagged days
(`predicted_drift_ms`) do not change anywhere in this phase - episodes are
a grouping/explanation layer on top of the same detector output, not a new
detector. So "no episode grouping vs. full episode system" cannot show a
difference in which days get flagged; it CAN show a real difference in
(a) how those flagged days get bundled into alerts an analyst would
actually see, and (b) whether an alert is only surfaced once confidence
crosses the ESCALATE threshold vs. surfaced on every flagged episode
regardless of confidence. Those are the two things this ablation ladder
actually varies - proposed ablations that wouldn't change any real number
(e.g. "evidence accumulation only" without grouping) were dropped rather
than included to pad out a table, per the task brief's explicit
instruction not to include an ablation "merely because it looks
impressive."

A. No episode grouping (gap_tolerance=0, strict day-to-day contiguity) -
   the Phase 2 baseline methodology (evaluation.evaluate.event_level_evaluation_v2).
B. Episode grouping only (gap_tolerance=2, this phase's default) - any
   flagged episode counts as an alert, regardless of confidence.
C. Episode grouping + confidence gating (gap_tolerance=2, but an episode
   only counts as a "real alert" if it reaches ESCALATE state at some point) -
   the full system's actual analyst-facing behavior.
D. Episode grouping with a looser gap tolerance (gap_tolerance=5) - tests
   sensitivity to the specific gap choice documented in episode/grouping.py.
"""
import os
import sys
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from evaluation.matching import match_episodes, false_positive_episodes
from evaluation.episode_metrics import episode_level_evaluation
from episode.builder import build_episodes_for_merchant


def run_ablation_confidence_gated(scored_df: pd.DataFrame, gap_tolerance: int = 2) -> dict:
    """Same matching as episode_level_evaluation, but a matched/false-positive
    episode only counts as a real ALERT if it reaches ESCALATE at some point
    in its trajectory - simulates what an analyst would actually see."""
    matches = match_episodes(scored_df, pred_col="predicted_drift_ms", gap_tolerance=gap_tolerance)
    fps = false_positive_episodes(scored_df, pred_col="predicted_drift_ms", gap_tolerance=gap_tolerance)

    escalated_spans = {}
    for mid, g in scored_df.groupby("merchant_id"):
        episodes = build_episodes_for_merchant(g, gap_tolerance=gap_tolerance)
        escalated_spans[mid] = {e.start_day for e in episodes
                                 if any(t.new_state == "ESCALATE" for t in e.transition_log)}

    def span_escalated(mid, start_day):
        return start_day in escalated_spans.get(mid, set())

    n_events = len(matches)
    n_detected_and_escalated = sum(1 for m in matches if m.matched and span_escalated(m.merchant_id, m.predicted_start))
    tp_predicted = sum(1 for m in matches if m.matched and span_escalated(m.merchant_id, m.predicted_start))
    fp_escalated = sum(1 for fp in fps if span_escalated(fp["merchant_id"], fp["start_day"]))

    recall = n_detected_and_escalated / n_events if n_events else None
    denom = tp_predicted + fp_escalated
    precision = tp_predicted / denom if denom else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None

    return {
        "variant": "C. grouping + confidence-gated (ESCALATE only)",
        "events_total": n_events, "events_detected": n_detected_and_escalated,
        "event_recall": round(recall, 3) if recall is not None else None,
        "event_precision": round(precision, 3) if precision is not None else None,
        "event_f1": round(f1, 3) if f1 is not None else None,
        "alerts_surfaced": denom,
    }


def run_ablations(scored_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    a = episode_level_evaluation_via_gap(scored_df, gap_tolerance=0)
    a["variant"] = "A. no episode grouping (gap=0, Phase 2 day-level)"
    rows.append(a)

    b = episode_level_evaluation(scored_df)
    b["variant"] = "B. episode grouping only (gap=2, any flagged episode = alert)"
    rows.append(b)

    c = run_ablation_confidence_gated(scored_df, gap_tolerance=2)
    rows.append(c)

    d = episode_level_evaluation_via_gap(scored_df, gap_tolerance=5)
    d["variant"] = "D. episode grouping, looser gap tolerance (gap=5)"
    rows.append(d)

    return pd.DataFrame(rows)


def episode_level_evaluation_via_gap(scored_df: pd.DataFrame, gap_tolerance: int) -> dict:
    from evaluation.matching import match_episodes, false_positive_episodes
    matches = match_episodes(scored_df, gap_tolerance=gap_tolerance)
    fps = false_positive_episodes(scored_df, gap_tolerance=gap_tolerance)
    n_events = len(matches)
    n_detected = sum(1 for m in matches if m.matched)
    n_tp_predicted = sum(m.n_matching_predicted_episodes for m in matches if m.matched)
    duplicate_events = sum(1 for m in matches if m.matched and m.n_matching_predicted_episodes > 1)
    total_predicted = n_tp_predicted + len(fps)
    recall = n_detected / n_events if n_events else None
    precision = n_tp_predicted / total_predicted if total_predicted else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {
        "events_total": n_events, "events_detected": n_detected,
        "event_recall": round(recall, 3) if recall is not None else None,
        "event_precision": round(precision, 3) if precision is not None else None,
        "event_f1": round(f1, 3) if f1 is not None else None,
        "duplicate_episode_count": duplicate_events,
        "false_positive_episodes": len(fps),
    }


if __name__ == "__main__":
    from detection.drift_detector import merchant_specific_drift
    from data.synthetic_generator import build_richer_population

    raw = pd.read_csv(os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv"))
    scored = merchant_specific_drift(raw)
    richer = build_richer_population(seed=42)
    scored_richer = merchant_specific_drift(richer)

    print("=== Original benchmark ===")
    print(run_ablations(scored).to_string(index=False))
    print("\n=== Richer benchmark ===")
    print(run_ablations(scored_richer).to_string(index=False))
