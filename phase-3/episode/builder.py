"""
Episode builder — orchestrates episode/grouping.py, episode/aggregation.py,
and episode/state_machine.py into complete RiskEpisode objects with a full
day-by-day confidence trajectory, evidence timeline, and transition log
(task brief step 12: "the case builder should consume the entire episode").

For each grouped EpisodeSpan (episode/grouping.py), this walks EVERY
calendar day from the span's start_day through its formal resolution day
(not just the flagged days - a 1-2 day gap inside the gap-tolerance window
still gets a confidence re-assessment, since the episode is still open),
recomputing episode-to-date evidence and confidence fresh each day
(episode/aggregation.py), and only appending a state transition / timeline
entry when something actually changed (episode/state_machine.py /
diff_evidence_snapshots) - this is what keeps the transition_log and
evidence_timeline meaningful rather than one entry per day regardless of
change.
"""
from dataclasses import replace

import pandas as pd

from agents.confidence import compute_confidence
from agents.case_builder import HYPOTHESIS_A_TEXT, HYPOTHESIS_B_TEXT
from episode.grouping import group_into_episodes, GAP_TOLERANCE_DAYS
from episode.model import RiskEpisode
from episode.state_machine import transition
from episode.aggregation import (
    run_episode_investigators, evidence_snapshot_by_key, diff_evidence_snapshots,
)


def _episode_id(merchant_id: str, start_day: int) -> str:
    return f"DW-{merchant_id}-{start_day:04d}"


def build_episode(scored_history: pd.DataFrame, merchant_id: str, start_day: int,
                    end_day: int, resolve_day: int) -> RiskEpisode:
    """Walks days [start_day, resolve_day] for one episode span, producing a
    fully-populated RiskEpisode with confidence_history, evidence_timeline,
    and transition_log built incrementally and never overwritten."""
    episode = RiskEpisode(
        episode_id=_episode_id(merchant_id, start_day), merchant_id=merchant_id,
        start_day=start_day, current_day=start_day, end_day=None, status="WATCH",
        trigger_events=[], signal_groups=set(), peak_day=None, peak_score=0.0,
        confidence_history=[], evidence_timeline=[], supporting_evidence=[],
        contradicting_evidence=[], missing_evidence=[],
        hypothesis_a=HYPOTHESIS_A_TEXT, hypothesis_b=HYPOTHESIS_B_TEXT,
        recommended_action="", transition_log=[],
    )

    flagged_mask = scored_history["predicted_drift_ms"] == 1
    trigger_days = sorted(scored_history.loc[flagged_mask & (scored_history["day"] >= start_day) &
                                               (scored_history["day"] <= end_day), "day"].tolist())
    episode.trigger_events = trigger_days

    prev_snapshot: dict = {}
    old_state = None

    for day in range(start_day, resolve_day + 1):
        is_final_day = day == resolve_day
        evidence = run_episode_investigators(scored_history, start_day, day)
        confidence = compute_confidence(evidence)
        snapshot = evidence_snapshot_by_key(evidence)
        new_entries = diff_evidence_snapshots(prev_snapshot, snapshot, day)
        episode.evidence_timeline.extend(new_entries)
        changed_keys = [(e["signal_group"], e["evidence_type"]) for e in new_entries]

        force_resolve = is_final_day and day > end_day
        t = transition(day, old_state, confidence, changed_keys,
                        force_resolve=force_resolve,
                        resolve_reason=(f"No further deviation for {day - end_day} day(s) after the last "
                                        f"flagged day (day {end_day}); episode formally closed."
                                        if force_resolve else ""))
        episode.transition_log.append(t)
        episode.confidence_history.append((day, confidence.final_score, t.new_state))
        episode.status = t.new_state
        episode.current_day = day

        if confidence.final_score >= episode.peak_score:
            episode.peak_score = confidence.final_score
            episode.peak_day = day

        for e in evidence:
            if e.evidence_type == "trigger":
                episode.signal_groups.add(e.signal_group)

        episode.supporting_evidence = [e for e in evidence if e.supports_hypothesis == "A"]
        episode.contradicting_evidence = [e for e in evidence if e.supports_hypothesis == "B"]
        episode.missing_evidence = [e for e in evidence if e.evidence_type == "missing"]

        old_state = t.new_state
        prev_snapshot = snapshot

        if t.new_state == "RESOLVED":
            episode.end_day = day
            last_active = next((s for _, _, s in reversed(episode.confidence_history) if s != "RESOLVED"), "WATCH")
            episode.resolution = {
                "day": day, "outcome": last_active,
                "reason": (f"Resolved having last reached {last_active} "
                           f"(peak confidence {episode.peak_score:.2f} on day {episode.peak_day})."),
            }
            break

    from agents.confidence import decide_action
    final_confidence = compute_confidence(run_episode_investigators(scored_history, start_day,
                                                                       min(episode.current_day, end_day)))
    _, _, episode.recommended_action = decide_action(final_confidence)

    return episode


def build_episodes_for_merchant(scored_history: pd.DataFrame,
                                  pred_col: str = "predicted_drift_ms",
                                  gap_tolerance: int = GAP_TOLERANCE_DAYS) -> list[RiskEpisode]:
    """Full pipeline for one merchant: group flagged days into episode
    spans, then build a complete RiskEpisode (with trajectory/timeline/
    transitions/resolution) for each span."""
    scored_history = scored_history.sort_values("day")
    merchant_id = scored_history["merchant_id"].iloc[0]
    max_day = int(scored_history["day"].max())
    spans = group_into_episodes(scored_history, pred_col=pred_col, gap_tolerance=gap_tolerance)

    episodes = []
    for span in spans:
        resolve_day = min(span.end_day + gap_tolerance + 1, max_day)
        episodes.append(build_episode(scored_history, merchant_id, span.start_day, span.end_day, resolve_day))
    return episodes
