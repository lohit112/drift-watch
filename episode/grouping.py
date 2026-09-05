"""
Episode grouping — task brief step 3.

Groups a merchant's flagged days into risk episodes using temporal
proximity with a bounded gap tolerance, rather than requiring strict
day-to-day contiguity (which would fragment one real drift episode into
many whenever a single day's noise happens to drop below the z-threshold).

TERMINOLOGY (made explicit here after a documentation review found the
prior wording ambiguous - the GROUPING BEHAVIOR ITSELF is unchanged):

GAP_TOLERANCE_DAYS is the maximum number of SKIPPED (unflagged) calendar
days allowed between two flagged days for them to still belong to the same
episode - it is NOT the maximum day-index difference between them. Two
flagged days `d` and `previous_flagged_day` belong to the same episode iff:

    d - previous_flagged_day <= GAP_TOLERANCE_DAYS + 1

The `+ 1` is there because a day-index difference of 1 means the two
flagged days are back-to-back with ZERO days skipped in between, not one.
Worked example with GAP_TOLERANCE_DAYS = 2:

    day-index difference | skipped days in between | same episode?
    1                     | 0 (back-to-back)         | yes
    2                     | 1                        | yes
    3                     | 2                        | yes (== the tolerance)
    4                     | 3                        | no  (new episode starts)

GAP_TOLERANCE_DAYS was chosen by inspecting the ACTUAL gap distribution in
the existing scored dataset (see PHASE_2_EPISODE_BASELINE.md and the
analysis run before writing this file), not tuned to maximize any
evaluation metric:

- Real, continuous fraud-drift episodes (M0021, M0022, M0023, M0024) show
  at most 2 SKIPPED days between flagged days that are evidently part of
  the same episode (e.g. M0023: flagged on day 183, then day 185 - 1
  skipped day, day 184 - still one continuous episode).
- Genuinely separate occurrences (the seasonal merchants M0009/M0010/M0011,
  which flag briefly during each year's festival window) are separated by
  70-90+ SKIPPED days between occurrences - nowhere close to the
  fraud-episode internal gaps.

A tolerance of 2 skipped days bridges the observed within-episode noise
without coming remotely close to merging genuinely separate occurrences.
This is documented explicitly so the choice can be checked against the
data it was derived from, rather than treated as a black-box constant.
"""
from dataclasses import dataclass

GAP_TOLERANCE_DAYS = 2  # max SKIPPED (unflagged) calendar days tolerated within one episode - see module docstring


@dataclass(frozen=True)
class EpisodeSpan:
    merchant_id: str
    start_day: int
    end_day: int          # last flagged day (inclusive) - NOT the same as "resolved"
    flagged_days: tuple    # all individual flagged days within [start_day, end_day]


def group_into_episodes(scored_history, pred_col: str = "predicted_drift_ms",
                          gap_tolerance: int = GAP_TOLERANCE_DAYS) -> list[EpisodeSpan]:
    """
    Groups one merchant's flagged days into episodes. Two consecutive
    flagged days belong to the same episode if the number of SKIPPED
    (unflagged) calendar days between them is <= gap_tolerance - i.e. if
    their day-index difference is <= gap_tolerance + 1 (see module
    docstring's worked example for why the +1 is there). A larger gap
    starts a new episode.

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
        # gap_tolerance = max SKIPPED days allowed; a day-index difference
        # of (gap_tolerance + 1) corresponds to exactly gap_tolerance days
        # skipped in between (see module docstring's worked example).
        if d - current[-1] <= gap_tolerance + 1:
            current.append(d)
        else:
            episodes.append(EpisodeSpan(merchant_id, current[0], current[-1], tuple(current)))
            current = [d]
    episodes.append(EpisodeSpan(merchant_id, current[0], current[-1], tuple(current)))
    return episodes
