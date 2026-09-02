"""
Episode matching — task brief step 14.

Matching rule (documented up front, not chosen post-hoc to flatter a
result): a PREDICTED episode matches a GROUND-TRUTH event if and only if
they belong to the same merchant AND the predicted episode's raw
`trigger_events` (its actual flagged days, NOT the extended
resolution window - see docs/EPISODE_MODEL.md on why resolution always
trails the last flagged day) contains at least one day inside
`[gt_start, gt_end]` inclusive.

This is the same "any day overlap" rule already used by
`evaluation.evaluate.event_table` for day-level event matching (task brief
step 14 explicitly allows reusing an existing reasonable rule rather than
inventing a new one) — extended here to operate on GROUPED predicted
episodes (via `episode.grouping.group_into_episodes`, gap-tolerant) instead
of raw individual flagged days. Using `trigger_events` rather than the full
`[start_day, end_day]` resolution window for the overlap check specifically
avoids inflating precision: an episode's resolution window extends
`GAP_TOLERANCE_DAYS + 1` days past the real behavior, and letting THAT
count toward overlap would make near-miss episodes look like genuine
matches.
"""
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from episode.grouping import group_into_episodes, GAP_TOLERANCE_DAYS
from evaluation.evaluate import event_table


@dataclass
class EpisodeMatch:
    merchant_id: str
    gt_start: int
    gt_end: int
    drift_kind: str
    matched: bool
    predicted_start: Optional[int]
    predicted_end: Optional[int]           # last trigger day of the matched predicted episode
    first_detection_day: Optional[int]
    detection_latency: Optional[int]
    start_error: Optional[int]              # predicted_start - gt_start (matched only)
    n_matching_predicted_episodes: int      # >1 means the true event got fragmented into duplicates


def match_episodes(scored_df: pd.DataFrame, pred_col: str = "predicted_drift_ms",
                     gap_tolerance: int = GAP_TOLERANCE_DAYS) -> list[EpisodeMatch]:
    """Matches every ground-truth event (from `evaluation.evaluate.event_table`,
    unchanged - task brief step 13 explicitly keeps day-level ground truth as
    the source of true events) against GROUPED predicted episodes for that
    merchant."""
    gt_events = event_table(scored_df, pred_col)
    matches = []

    for mid, g in scored_df.groupby("merchant_id"):
        merchant_gt = gt_events[gt_events["merchant_id"] == mid]
        if merchant_gt.empty:
            continue
        predicted_spans = group_into_episodes(g, pred_col=pred_col, gap_tolerance=gap_tolerance)

        for _, gt in merchant_gt.iterrows():
            gt_start, gt_end = int(gt["event_start"]), int(gt["event_end"])
            overlapping = [
                span for span in predicted_spans
                if any(gt_start <= d <= gt_end for d in span.flagged_days)
            ]
            if overlapping:
                first_span = min(overlapping, key=lambda s: s.start_day)
                first_detection_day = min(d for d in first_span.flagged_days if gt_start <= d <= gt_end)
                matches.append(EpisodeMatch(
                    merchant_id=mid, gt_start=gt_start, gt_end=gt_end, drift_kind=gt["drift_kind"],
                    matched=True, predicted_start=first_span.start_day, predicted_end=first_span.end_day,
                    first_detection_day=first_detection_day,
                    detection_latency=first_detection_day - gt_start,
                    start_error=first_span.start_day - gt_start,
                    n_matching_predicted_episodes=len(overlapping),
                ))
            else:
                matches.append(EpisodeMatch(
                    merchant_id=mid, gt_start=gt_start, gt_end=gt_end, drift_kind=gt["drift_kind"],
                    matched=False, predicted_start=None, predicted_end=None,
                    first_detection_day=None, detection_latency=None, start_error=None,
                    n_matching_predicted_episodes=0,
                ))
    return matches


def false_positive_episodes(scored_df: pd.DataFrame, pred_col: str = "predicted_drift_ms",
                              gap_tolerance: int = GAP_TOLERANCE_DAYS) -> list[dict]:
    """Predicted episodes that don't overlap ANY ground-truth event for
    their merchant at all - used for false-alerts-outside-episodes and
    false-alerts-per-merchant (task brief step 13)."""
    gt_events = event_table(scored_df, pred_col)
    false_positives = []
    for mid, g in scored_df.groupby("merchant_id"):
        merchant_gt = gt_events[gt_events["merchant_id"] == mid]
        predicted_spans = group_into_episodes(g, pred_col=pred_col, gap_tolerance=gap_tolerance)
        for span in predicted_spans:
            overlaps_any = any(
                any(int(gt["event_start"]) <= d <= int(gt["event_end"]) for d in span.flagged_days)
                for _, gt in merchant_gt.iterrows()
            )
            if not overlaps_any:
                false_positives.append({"merchant_id": mid, "start_day": span.start_day, "end_day": span.end_day})
    return false_positives
