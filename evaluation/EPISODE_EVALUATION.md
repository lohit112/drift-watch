# Episode Evaluation — Task Brief Steps 13 & 15

Day-level metrics (`evaluation/evaluate.py`) are unchanged and kept as
diagnostics, per the brief's explicit instruction. This document covers
the new episode-primary metrics (`evaluation/episode_metrics.py`,
`evaluation/matching.py`) and the multi-seed regression comparing the
current (Phase 2, day-level) system against the episode system.

## Methodology (episode matching, task brief step 14)

A predicted episode matches a ground-truth event if they share a merchant
and the predicted episode's raw flagged days (not its extended resolution
window) include at least one day inside the ground-truth event's window.
Full rationale in `evaluation/matching.py`'s module docstring — reusing
the "any day overlap" rule already validated in Phase 1/2 rather than
inventing a new threshold to flatter a result.

## Multi-seed regression: current (day-level) vs episode system

Same 10 seeds as `evaluation/multi_seed_eval.py` (not reduced), 42-merchant richer benchmark. Reproduce: `python3 evaluation/episode_multi_seed_eval.py`.

| System | Metric | Mean | Median | Std | Min | Max |
|---|---|---|---|---|---|---|
| Current (day-level) | Event recall | 0.812 | 0.769 | 0.082 | 0.731 | 0.923 |
| Current (day-level) | Event precision | 0.564 | 0.560 | 0.047 | 0.483 | 0.635 |
| Current (day-level) | Event F1 | 0.663 | 0.660 | 0.043 | 0.604 | 0.724 |
| Current (day-level) | Avg latency (days) | 9.15 | 11.50 | 3.93 | 2.74 | 12.57 |
| Episode (Phase 3) | Event recall | 0.812 | 0.769 | 0.082 | 0.731 | 0.923 |
| Episode (Phase 3) | Event precision | **0.464** | 0.472 | 0.040 | 0.412 | 0.523 |
| Episode (Phase 3) | Event F1 | **0.589** | 0.582 | 0.047 | 0.527 | 0.668 |
| Episode (Phase 3) | Avg latency (days) | 9.15 | 11.50 | 3.93 | 2.74 | 12.57 |
| Episode (Phase 3) | Duplicate episode rate | 0.255 | 0.261 | 0.082 | 0.105 | 0.400 |

## Reported honestly, not hidden: episode grouping makes precision/F1 WORSE, not better

Recall and latency are IDENTICAL between the two systems (expected — the
underlying detector output never changes in this phase). But episode-level
precision (0.464) and F1 (0.589) are measurably *worse* than the
day-level numbers they're built on top of (0.564, 0.663). This matches
exactly what `evaluation/EPISODE_ABLATIONS.md` found and explains: grouping
alone doesn't reduce false positives, it reduces *fragmentation* of true
positives more than it reduces the false-positive count, which nets out
against precision's denominator. **This phase does not claim episodes make
raw detection numbers better.** What episodes genuinely improve on is
(a) the confidence-trajectory coherence problem this phase set out to fix
(see PHASE_2_EPISODE_BASELINE.md — verified fixed in
`tests/test_episode_invariants.py` and `tests/test_golden_episodes.py`),
and (b) precision specifically WHEN confidence-gating is applied on top of
grouping (see `evaluation/EPISODE_ABLATIONS.md` variant C: 0.605 → still
imperfect but the best precision of any variant tested on the original
benchmark).

## Duplicate episode rate: a real, non-trivial number

25.5% of matched ground-truth events (mean across 10 seeds) get
fragmented into more than one predicted episode. This means
`GAP_TOLERANCE_DAYS=2` (chosen from the original benchmark's gap
distribution — see `episode/grouping.py`) is not always sufficient for the
richer benchmark's harder regimes (`slow_fraud` in particular has a
30-day ramp with more opportunity for a day's z-score to dip below
threshold mid-episode). This is reported as an open item, not silently
absorbed into an average that would hide it — see PHASE_3_REPORT.md
"Remaining Weaknesses."
