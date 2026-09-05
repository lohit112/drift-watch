# Episode Evidence Accumulation & Deduplication — Task Brief Steps 5-8

## The core design decision

Episode evidence (`episode/aggregation.py::build_episode_signal_evidence`)
is recomputed FRESH each day from the WHOLE episode span so far
(`episode_start` → `as_of_day`), rather than incrementally appended to a
running list. This single decision satisfies three requirements at once:

1. **Confidence trajectory (step 5)**: `agents.confidence.compute_confidence`
   is called on a fresh, complete snapshot every day — so the score can
   genuinely go up or down as new information arrives, with no special-case
   "undo" logic needed for a day that turns out to look calmer.
2. **Deduplication (step 7)**: a signal group that's been deviating for 6
   consecutive days is represented as exactly ONE `contextual` evidence item
   ("deviated on 6/6 days — a sustained pattern"), never as six separate
   "supporting" items. Confidence's `evidence_balance` component counts
   evidence ITEMS, so this is what prevents a persistent anomaly from
   inflating confidence just by lasting longer — see the worked example
   below.
3. **Peak vs. persistent drift (step 8)**: the `contextual` evidence's duty
   cycle (`n_deviant_days / n_days`) directly distinguishes a one-day spike
   that didn't recur (duty cycle ~0.15 in a week-long episode) from a
   persistent moderate anomaly (duty cycle ~0.85) — both get exactly one
   evidence item, but the item itself says which kind it is.

## Worked example: why this doesn't let repeated identical signals inflate confidence

Consider a refund anomaly that fires on days 181, 182, and 183 of an
episode that started day 181:

- Day 181: `episode_slice` = [181]. `n_deviant_days=1`, duty_cycle=1.0.
  ONE trigger + ONE contextual evidence item for `refund`.
- Day 182: `episode_slice` = [181, 182]. `n_deviant_days=2`, duty_cycle=1.0.
  Still exactly ONE trigger + ONE contextual item — the trigger's
  `observation`/`deviation` fields may update (if day 182 was a stronger
  deviation than day 181), but there are never two "refund trigger" items
  in the same day's evidence list.
- Day 183: same shape again.

`compute_confidence`'s `evidence_balance` component
(`n_support_a / (n_support_a + n_support_b)`) counts EVIDENCE ITEMS, and
refund contributes exactly 2 items (trigger + contextual) on every one of
these three days, regardless of how many days the anomaly has actually
persisted. The duty cycle NUMBER inside the contextual item can still
communicate "this has held for 3 days straight," but it does so as
information within one item, not by manufacturing more items — this is
the literal mechanism that satisfies task brief step 7's "represent it
appropriately... rather than three independent pieces of evidence."

## The timeline is diffed, not dumped

`episode/aggregation.py::diff_evidence_snapshots` compares today's
`(signal_group, evidence_type) → Evidence` snapshot against yesterday's and
only appends a timeline entry for a genuine change:

- a key appears for the first time → `"new"`
- a `contextual` duty cycle crosses the 0.5 "sustained" threshold → `"strengthened"`/`"weakened"`
- a key disappears (e.g. insufficient-baseline resolving into real evidence) → `"resolved"`

An unchanged day-over-day snapshot produces ZERO new timeline entries. This
is what keeps `evidence_timeline` a genuine narrative
("day 181: refund anomaly emerges → day 183: dispute anomaly emerges,
now 2 independent signal groups → day 185: refund duty cycle crosses
sustained") instead of a daily repeat of the same finding.

## Peak vs. persistent — real example (M0021 fraud episode, days 178-190)

- `refund` duty cycle reaches 100% almost immediately (the fraud archetype
  ramps refund_rate hard from day 1).
- `category_mix` duty cycle builds more slowly as the category shift takes
  a few days to fully concentrate.
- The episode's `peak_score`/`peak_day` (0.84 on day 179) captures the
  moment breadth+persistence were both highest — distinct from `end_day`
  (190, when the episode formally resolves), and distinct from
  `start_day` (178, the first flagged day). All three are genuinely
  different days in this real run, exactly as task brief step 9 expects.

## Known limitation (not hidden)

`CONTRADICTING` evidence uses the same all-5-groups-are-risk-relevant
assumption as the single-day investigators
(`agents/investigators.py::RISK_RELEVANT_GROUPS`) — unchanged from Phase 2,
still a real simplification, still documented rather than silently
carried over unremarked.
