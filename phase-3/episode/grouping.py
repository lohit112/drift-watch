"""
Episode grouping — task brief step 3.

Groups a merchant's flagged days into risk episodes using temporal
proximity with a bounded gap tolerance, rather than requiring strict
day-to-day contiguity (which would fragment one real drift episode into
many whenever a single day's noise happens to drop below the z-threshold).

GAP_TOLERANCE_DAYS was chosen by inspecting the ACTUAL gap distribution in
the existing scored dataset (see PHASE_2_EPISODE_BASELINE.md and the
analysis run before writing this file), not tuned to maximize any
evaluation metric:

- Real, continuous fraud-drift episodes (M0021, M0022, M0023, M0024) show
  internal gaps of at most 2 days between flagged days that are evidently
  part of the same episode (e.g. M0023: ...183, [gap=2], 185, 186...).
- Genuinely separate occurrences (the seasonal merchants M0009/M0010/M0011,
  which flag briefly during each year's festival window) are separated by
  70-90+ days between occurrences - nowhere close to the fraud-episode
  internal gaps.

A gap tolerance of 2 bridges the observed within-episode noise without
coming remotely close to merging genuinely separate occurrences. This is
documented explicitly so the choice can be checked against the data it was
derived from, rather than treated as a black-box constant.
"""
from dataclasses import dataclass

GAP_TOLERANCE_DAYS = 2


@dataclass(frozen=True)
class EpisodeSpan:
    merchant_id: str
    start_day: int
    end_day: int          # last flagged day (inclusive) - NOT the same as "resolved"
    flagged_days: tuple    # all individual flagged days within [start_day, end_day]


def group_into_episodes(scored_history, pred_col: str = "predicted_drift_ms",
                          gap_tolerance: int = GAP_TOLERANCE_DAYS) -> list[EpisodeSpan]:
    """
    Groups one merchant's flagged days into episodes. Two flagged days
    belong to the same episode if the gap between them is <= gap_tolerance;
    a gap larger than that starts a new episode.

    This only determines episode BOUNDARIES (start_day/end_day/flagged_days).
    It does not decide state, confidence, or resolution - see
    episode/state_machine.py and episode/builder.py for those.
    """
    g = scored_history.sort_values("day")
    flagged_days = sorted(g[g[pred_col] == 1]["day"].tolist())
    merchant_id = g["merchant_id"].iloc[0] if len(g) else None
    if not flagged_days:
        return []

    episodes = []
    current = [flagged_days[0]]
    for d in flagged_days[1:]:
        if d - current[-1] <= gap_tolerance + 1:  # +1 because gap_tolerance counts SKIPPED days
            current.append(d)
        else:
            episodes.append(EpisodeSpan(merchant_id, current[0], current[-1], tuple(current)))
            current = [d]
    episodes.append(EpisodeSpan(merchant_id, current[0], current[-1], tuple(current)))
    return episodes
