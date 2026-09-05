# Risk Confidence Score — Task Brief Step 12

Implemented in `agents/confidence.py`. Explicitly named **Risk Confidence
Score**, not "probability" — it is not calibrated against observed outcome
frequencies (there is no historical ground-truth outcome dataset to
calibrate against; the synthetic ground truth used for evaluation is not
the same as calibration data — see Limitations).

## 1. Formula

```
raw_score =   0.30 * anomaly_strength
            + 0.20 * signal_breadth
            + 0.20 * temporal_persistence
            + 0.20 * evidence_balance
            + 0.10 * novelty

final_score = raw_score, UNLESS any signal group's evidence is MISSING, in
              which case:
              final_score = min(raw_score * (1 - 0.12 * n_missing_groups),
                                 0.75)
```

All five components are independently normalized to `[0, 1]` before
weighting; `final_score` is clipped to `[0, 1]`.

## 2. Components

- **anomaly_strength** (weight 0.30): mean `|z|` across TRIGGER evidence
  items that support Hypothesis A, divided by 6.0 and capped at 1.0. A z of
  6+ (routinely seen on dispute_rate at fraud onset — see
  PHASE_2_BASELINE.md) saturates this component.
- **signal_breadth** (weight 0.20): count of independent deviant signal
  groups (see `detection/signal_taxonomy.py`) divided by the fixed total
  of 5 groups. Fixed denominator, not the number of groups present in
  whatever evidence happens to be passed in — this matters for testability
  (see `tests/test_confidence_model.py`) as well as production correctness.
- **temporal_persistence** (weight 0.20): fraction of CONTEXTUAL (3-day/
  7-day) evidence, restricted to groups whose TRIGGER fired, that still
  supports Hypothesis A. A trigger with zero persisting contextual support
  scores 0 here — deliberately kept as its own component rather than
  folded into anomaly_strength, so a strong-but-unconfirmed single-day
  spike (e.g. day 1 of a real fraud onset) is visibly different from a
  strong AND confirmed one (day 3-4 of the same episode). This is the
  direct mechanism that resolves PHASE_1_REPORT.md §9: the same underlying
  episode now produces a low score on day 1 (honestly reflecting only one
  day of evidence) and a much higher score by day 3-4 once persistence
  confirms it (see `tests/test_case_builder.py::test_strong_multi_signal_fraud_pattern_escalates_once_persistence_confirms`).
- **evidence_balance** (weight 0.20): `(n_support_A - n_support_B) / (n_support_A + n_support_B)`, rescaled from `[-1, 1]` to `[0, 1]`. Counts across ALL evidence types (trigger + contextual + historical + contradicting), not just the trigger.
- **novelty** (weight 0.10): fraction of HISTORICAL evidence (for deviant
  groups only) reporting this deviation magnitude has never happened
  before for this specific merchant. Smallest weight deliberately — many
  legitimate first-time events (a merchant's first-ever sale, first-ever
  geo expansion) also look "novel," so this is the weakest standalone
  signal of the five.

## 3. Normalization

Each component is bounded to `[0, 1]` at the point it's computed (see
inline `min(1.0, ...)` calls in `compute_confidence`), so the weighted sum
is guaranteed to land in `[0, 1]` before the missing-evidence step, and the
final clip is a belt-and-suspenders bound, not load-bearing.

## 4. Weight rationale

`anomaly_strength` and `evidence_balance` get the largest share (0.30 and
0.20, tied with breadth/persistence at 0.20) because they are the most
directly diagnostic components — "how extreme was it" and "does the
overall evidence pool lean toward risk." `novelty` gets the smallest share
(0.10) because it's the weakest standalone indicator, as explained above.
These weights are a documented, defensible starting point, not derived
from any optimization procedure — see Limitations.

## 5. Examples (from real runs, not fabricated)

- **M0021 (fraud-drift), day 178** (1 day into onset): `anomaly_strength=0.63, signal_breadth=0.80, temporal_persistence=0.13, evidence_balance=0.83, novelty=0.0` → `final_score=0.54` → `REQUEST_MORE_EVIDENCE`. Honest: only one day of evidence exists yet.
- **M0021, day 180** (3 days into onset): `temporal_persistence=0.83` (up from 0.13) → `final_score=0.75` → `ESCALATE`, severity high.
- **GOLDEN_LEGITIMATE** (clean single-signal volume spike, everything else flat): `signal_breadth=0.20, evidence_balance` pulled down by contradicting evidence from 4 quiet groups → does not reach `ESCALATE`.
- **GOLDEN_AMBIGUOUS** (refund up, dispute down simultaneously): `evidence_balance` near 0.5 (roughly equal support for A and B) → lands in the `[0.38, 0.62]` ambiguous zone → `REQUEST_MORE_EVIDENCE`.

## 6. Failure modes

- A merchant with a strong trigger but zero persistence (a single extreme
  day that reverts immediately) will score moderately, not low — the
  `temporal_persistence` component only weighs 0.20, so a very high
  `anomaly_strength` can still push the score into `ESCALATE` off one
  extreme day if breadth and balance also happen to be high. This is a
  known tradeoff, not a bug: a large enough single-day spike (e.g. a real
  compromised-credential test transaction) genuinely should be able to
  escalate without waiting for persistence, even though most incremental,
  ramping fraud benefits from the persistence check.
- Because `evidence_balance` counts contextual/historical items alongside
  trigger items, a signal group with many contextual sub-observations can
  numerically outweigh a group with fewer but stronger observations. This
  is a real limitation of simple counting.

## 7. Limitations

- **Not a calibrated probability.** No historical outcome dataset exists to
  calibrate against; weights are documented and defensible but not fit to
  data. Calling this a "probability" anywhere would be a false claim - it
  is called a Risk Confidence Score throughout the codebase and UI-facing
  output.
- **Hypothesis B has no equivalent full numeric score.** Task brief step 12
  asked specifically to replace the RISK confidence heuristic; Hypothesis B
  strength remains represented only via its own evidence list
  (`evidence_for_b`) and the implicit `evidence_balance` component, not a
  fully symmetric scoring formula. A genuinely symmetric two-sided model is
  deferred to Phase 3.
- **Single-day case snapshots.** `build_case` scores one flagged day at a
  time; it does not (yet) aggregate confidence across a whole multi-day
  episode. Day-to-day breadth fluctuations within the same real episode
  (e.g. some days show 2 deviant groups, others show 3) can cause the
  decision to fluctuate between `ESCALATE` and `REQUEST_MORE_EVIDENCE` day
  to day within a single true event — observed directly on M0021 (day 182
  escalates, day 185 requests more evidence, same underlying episode). See
  PHASE_2_REPORT.md "Remaining Weaknesses."
