# Episode Ablations — Task Brief Step 16

## What's actually ablatable

The detector's flagged days never change in this phase — episodes are a
grouping/explanation layer on the same detector output, not a new
detector. So the only things that can meaningfully differ across variants
are (a) how flagged days get bundled into alerts, and (b) whether an
alert is surfaced regardless of confidence or only once it reaches
ESCALATE. Ablations that wouldn't move any real number (e.g. "evidence
accumulation without grouping") were dropped rather than included to pad
the table, per the brief's explicit instruction.

## Variants

- **A. No episode grouping** (`gap_tolerance=0`, strict day-to-day contiguity)
- **B. Episode grouping only** (`gap_tolerance=2`, this phase's default — any flagged episode is an alert, regardless of confidence)
- **C. Grouping + confidence-gated** (`gap_tolerance=2`, but an episode only counts as a real alert if it reaches `ESCALATE` at some point — simulates what an analyst would actually be shown)
- **D. Looser gap tolerance** (`gap_tolerance=5`)

All four use the identical matching rule (`evaluation/matching.py`), varying only the grouping/gating parameter. Reproduce: `python3 evaluation/ablations.py`.

## Results — original benchmark (24 merchants, 4 fraud events)

| Variant | Recall | Precision | F1 | Duplicates | False positives |
|---|---|---|---|---|---|
| A. No grouping (gap=0) | 1.000 | 0.205 | 0.340 | 3 | 31 |
| B. Grouping (gap=2) | 1.000 | 0.143 | 0.250 | 0 | 24 |
| C. Grouping + confidence-gated | 1.000 | 0.286 | 0.444 | — | 14 alerts surfaced |
| D. Grouping (gap=5) | 1.000 | 0.148 | 0.258 | 0 | 23 |

## Results — richer benchmark (42 merchants, 26 events)

| Variant | Recall | Precision | F1 | Duplicates | False positives |
|---|---|---|---|---|---|
| A. No grouping (gap=0) | 0.846 | 0.605 | 0.705 | 13 | 34 |
| B. Grouping (gap=2) | 0.846 | 0.476 | 0.609 | 6 | 33 |
| C. Grouping + confidence-gated | 0.500 | 0.650 | 0.565 | — | 20 alerts surfaced |
| D. Grouping (gap=5) | 0.846 | 0.458 | 0.594 | 3 | 32 |

## Interpretation — including the counterintuitive part

**Confidence-gating (C) gives the biggest, clearest precision win on the
original benchmark** (0.286 vs 0.205 baseline, F1 0.444 vs 0.340) at zero
recall cost — every real fraud event still reaches ESCALATE at some point.
This is the strongest evidence in this phase that the confidence/state-
machine layer earns its keep: it suppresses roughly half the false alerts
a raw flagged-episode count would surface, without missing anything real.

**Grouping alone (B vs A) does NOT improve precision on either benchmark** —
it's mildly worse (0.205→0.143 original, 0.605→0.476 richer). This was
investigated rather than assumed away: gap-tolerant grouping reduces
fragmentation of TRUE events (duplicate count drops from 3→0 on the
original benchmark, 13→6 on the richer one — a real win for a cleaner
analyst-facing alert list), but it also merges some previously-separate
FALSE-positive noise flags into fewer counted episodes, and the true-event
fragmentation reduction turns out to be the smaller effect on precision's
denominator. Grouping's real value is qualitative (task brief's own stated
goal — "avoid creating a brand-new episode for every anomalous day" — a
genuinely cleaner alert list, one episode instead of ten), not a precision
metric win, and this phase does not pretend otherwise.

**Confidence-gating hurts recall substantially on the richer benchmark**
(0.846 → 0.500) and its F1 there (0.565) is actually worse than plain
grouping's (0.609) — the opposite of the original benchmark's result. This
was investigated: several of the richer benchmark's "ambiguous" archetypes
(`two_weak_signals`, `contradictory_evidence`, `seasonal_suspicious`) are
deliberately constructed to be genuinely ambiguous (see
`data/synthetic_generator.py`'s `RICHER_KIND_SPECS`), and correctly landing
in `REQUEST_MORE_EVIDENCE`/`INVESTIGATING` rather than confidently
escalating is arguably the RIGHT behavior for them, not a miss. Ground
truth's binary "is this a risk event" label doesn't distinguish "should
confidently escalate" from "should flag for more evidence" — so recall, as
classically defined here, penalizes exactly the humility this system is
designed to have on genuinely ambiguous cases. This is reported as a real
tension, not resolved by redefining the metric to hide it (the brief
explicitly forbids that) — see PHASE_3_REPORT.md "Remaining Weaknesses."

**Gap tolerance (B vs D, 2 vs 5) makes little difference** on either
benchmark (precision within ~0.01-0.02 of each other) — the
`GAP_TOLERANCE_DAYS=2` choice documented in `episode/grouping.py` is not
sensitive to being loosened further, which is reassuring evidence it
wasn't a fragile, overfit constant.
