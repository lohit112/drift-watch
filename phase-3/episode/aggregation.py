"""
Episode evidence aggregation — task brief steps 5 (confidence trajectory),
6 (evidence accumulation), 7 (deduplication).

The central design decision: instead of computing a NEW, independent piece
of evidence for every day (which is what caused both the flip-flopping
confidence in PHASE_2_EPISODE_BASELINE.md AND would cause the duplicate-
evidence-inflation problem in task brief step 7 if done naively), evidence
for a signal group is recomputed FRESH each day FROM THE WHOLE EPISODE SPAN
SO FAR (episode_start..current_day). This has two consequences that
directly satisfy the brief's requirements:

1. Persistence is represented as a DUTY CYCLE ("deviated on 6/8 days since
   the episode began"), not as N separate "supporting" evidence items - a
   persistent 6-day refund anomaly is exactly one CONTEXTUAL evidence item,
   never six. This is what task brief step 7 asks for directly.

2. Confidence is computed from the CURRENT SNAPSHOT of the whole episode,
   not from an incrementally-updated running total - so it can go up OR
   down as new days arrive without any special-cased "undo" logic, and two
   evaluations of the same episode-to-date span always produce identical
   evidence and confidence (determinism, invariant 5 in the tests).

What DOES need explicit history-tracking, and is NOT solved by "recompute
fresh each day," is the TIMELINE a human reviewer would want to read - task
brief step 6 wants to see "day 181: refund anomaly; day 185: new geographic
cluster" as a sequence, not just today's snapshot. That's handled by
`diff_evidence_snapshots`, which compares today's snapshot against
yesterday's and appends a timeline entry ONLY for genuine changes (a new
signal group's evidence appearing, a duty cycle crossing the "sustained"
threshold, or contradicting evidence appearing/resolving) - never for an
unchanged day-over-day repeat.
"""
import pandas as pd

from detection.drift_detector import Z_THRESHOLD, BASELINE_WINDOW
from detection.signal_taxonomy import SIGNAL_GROUPS
from agents.evidence import Evidence, strength_from_z, direction_from_delta
from agents.investigators import INVESTIGATOR_NAMES, RISK_RELEVANT_GROUPS, _primary_feature, MIN_BASELINE_DAYS

SUSTAINED_DUTY_CYCLE = 0.5  # fraction of episode-to-date days deviating for a signal group to count as "persisted"


def build_episode_signal_evidence(scored_history: pd.DataFrame, episode_start: int,
                                    as_of_day: int, group_key: str) -> list[Evidence]:
    """Episode-aggregated evidence for ONE signal group, covering
    [episode_start, as_of_day] inclusive. Returns at most: 1 trigger,
    1 contextual (duty-cycle), 1 historical, 1 contradicting - never more,
    regardless of how many days are in the span (see module docstring)."""
    source = INVESTIGATOR_NAMES[group_key]
    feat = _primary_feature(group_key)
    episode_slice = scored_history[(scored_history["day"] >= episode_start) &
                                     (scored_history["day"] <= as_of_day)]

    if episode_slice.empty:
        return [Evidence(
            source=source, signal_group=group_key, evidence_type="missing",
            observation=None, baseline=None, deviation=None,
            time_window=f"episode [{episode_start}-{as_of_day}]", direction="n/a", strength="n/a",
            supports_hypothesis=None, contradicts_hypothesis=None, confidence=0.0,
            summary=f"No data available for episode [{episode_start}-{as_of_day}] - cannot assess {group_key}.",
        )]

    start_row = episode_slice.iloc[0]
    baseline_days = start_row.get(f"baseline_days_{feat}", 0)
    if pd.isna(baseline_days) or baseline_days < MIN_BASELINE_DAYS:
        return [Evidence(
            source=source, signal_group=group_key, evidence_type="missing",
            observation=float(start_row[feat]), baseline=None, deviation=None,
            time_window=f"trailing {BASELINE_WINDOW}d ending day {episode_start - 1}",
            direction="n/a", strength="n/a",
            supports_hypothesis=None, contradicts_hypothesis=None, confidence=0.0,
            summary=f"Insufficient baseline history at episode start (day {episode_start}) to assess {group_key}.",
        )]

    z_series = episode_slice[f"z_{feat}"].dropna()
    n_days = len(episode_slice)
    n_deviant_days = int((z_series.abs() >= Z_THRESHOLD).sum())
    episode_deviant = n_deviant_days > 0
    duty_cycle = n_deviant_days / n_days if n_days else 0.0

    evidence = []

    if episode_deviant:
        abs_z_full = episode_slice[f"z_{feat}"].abs()
        strongest_idx = abs_z_full.idxmax()
        strongest_row = episode_slice.loc[strongest_idx]
        strongest_z = strongest_row[f"z_{feat}"]
        strongest_day = int(strongest_row["day"])
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="trigger",
            observation=round(float(strongest_row[feat]), 4),
            baseline=round(float(strongest_row[f"baseline_mean_{feat}"]), 4),
            deviation=round(float(strongest_z), 2),
            time_window=f"strongest day in episode [{episode_start}-{as_of_day}] (day {strongest_day})",
            direction=direction_from_delta(strongest_row[feat] - strongest_row[f"baseline_mean_{feat}"]),
            strength=strength_from_z(abs(strongest_z)),
            supports_hypothesis="A", contradicts_hypothesis="B",
            confidence=min(1.0, abs(strongest_z) / 5.0),
            summary=(f"{group_key}: strongest deviation within this episode was on day {strongest_day} "
                     f"(z={strongest_z:+.2f}), out of {n_days} day(s) observed so far."),
        ))

        persists = duty_cycle >= SUSTAINED_DUTY_CYCLE
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="contextual",
            observation=round(duty_cycle, 3), baseline=SUSTAINED_DUTY_CYCLE, deviation=None,
            time_window=f"duty cycle over episode days {episode_start}-{as_of_day} ({n_days} day(s))",
            direction="n/a",
            strength="strong" if duty_cycle >= 0.8 else ("moderate" if duty_cycle >= 0.5 else "weak"),
            supports_hypothesis="A" if persists else None,
            contradicts_hypothesis="B" if persists else None,
            confidence=0.7,
            summary=(f"{group_key}: deviated on {n_deviant_days}/{n_days} day(s) since the episode began "
                     f"({duty_cycle:.0%} duty cycle) - "
                     f"{'a sustained pattern' if persists else 'not sustained across most of the episode'}."),
        ))

    prior = scored_history[scored_history["day"] < episode_start]
    prior_z = prior[f"z_{feat}"].dropna()
    n_prior_extreme = int((prior_z.abs() >= Z_THRESHOLD).sum())
    established_pattern = n_prior_extreme >= 3
    novel = n_prior_extreme == 0
    evidence.append(Evidence(
        source=source, signal_group=group_key, evidence_type="historical",
        observation=float(n_prior_extreme), baseline=None, deviation=None,
        time_window=f"entire prior history before episode start (days 0-{episode_start - 1})",
        direction="n/a",
        strength="strong" if novel else ("weak" if n_prior_extreme <= 2 else "strong"),
        supports_hypothesis=("A" if (novel and episode_deviant) else ("B" if established_pattern else None)),
        contradicts_hypothesis=("B" if (novel and episode_deviant) else ("A" if established_pattern else None)),
        confidence=0.5,
        summary=(f"{group_key}: this merchant showed a deviation of this magnitude {n_prior_extreme} "
                 f"time(s) before this episode began - "
                 f"{'never before' if novel else ('an established pattern for this merchant' if established_pattern else 'has happened before, but not enough to call it established')}."),
    ))

    if not episode_deviant and group_key in RISK_RELEVANT_GROUPS:
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="contradicting",
            observation=round(float(episode_slice[feat].mean()), 4),
            baseline=round(float(start_row[f"baseline_mean_{feat}"]), 4), deviation=None,
            time_window=f"episode days {episode_start}-{as_of_day}",
            direction="n/a", strength="weak",
            supports_hypothesis="B", contradicts_hypothesis="A",
            confidence=0.4,
            summary=f"{group_key}: never deviated across the {n_days} day(s) of this episode so far.",
        ))

    return evidence


def run_episode_investigators(scored_history: pd.DataFrame, episode_start: int, as_of_day: int) -> list[Evidence]:
    all_evidence: list[Evidence] = []
    for group_key in SIGNAL_GROUPS:
        all_evidence.extend(build_episode_signal_evidence(scored_history, episode_start, as_of_day, group_key))
    return all_evidence


def evidence_snapshot_by_key(evidence: list[Evidence]) -> dict:
    """(signal_group, evidence_type) -> Evidence. At most one entry per key
    by construction of build_episode_signal_evidence."""
    return {(e.signal_group, e.evidence_type): e for e in evidence}


def diff_evidence_snapshots(prev_by_key: dict, new_by_key: dict, day: int) -> list[dict]:
    """
    Task brief step 6/7: returns timeline entries for genuine CHANGES only:
      - a (group, evidence_type) key appears for the first time -> "new"
      - a 'contextual' duty-cycle crosses the SUSTAINED_DUTY_CYCLE threshold
        in either direction -> "strengthened" / "weakened"
      - a key present before disappears (rare - e.g. insufficient-baseline
        resolving into real evidence removes the 'missing' key) -> "resolved"
    Never emits an entry for a key that is present in both snapshots with
    no meaningful change - this is what prevents "day 181/182/183: refund
    anomaly" from appearing three times for one persistent finding.
    """
    entries = []
    for key, ev in new_by_key.items():
        group, etype = key
        if key not in prev_by_key:
            entries.append({"day": day, "signal_group": group, "evidence_type": etype,
                             "change": "new", "summary": ev.summary})
            continue
        prev_ev = prev_by_key[key]
        if etype == "contextual" and prev_ev.observation is not None and ev.observation is not None:
            crossed_up = prev_ev.observation < SUSTAINED_DUTY_CYCLE <= ev.observation
            crossed_down = prev_ev.observation >= SUSTAINED_DUTY_CYCLE > ev.observation
            if crossed_up:
                entries.append({"day": day, "signal_group": group, "evidence_type": etype,
                                 "change": "strengthened", "summary": ev.summary})
            elif crossed_down:
                entries.append({"day": day, "signal_group": group, "evidence_type": etype,
                                 "change": "weakened", "summary": ev.summary})
    for key in prev_by_key:
        if key not in new_by_key:
            group, etype = key
            entries.append({"day": day, "signal_group": group, "evidence_type": etype,
                             "change": "resolved", "summary": f"{group} {etype} evidence no longer applicable."})
    return entries
