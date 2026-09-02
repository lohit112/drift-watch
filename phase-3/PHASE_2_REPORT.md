# Phase 2 — Detection Intelligence + Evidence Reasoning

## Executive Summary

Phase 2 rebuilt the investigation/reasoning layer around structured,
typed evidence instead of ad hoc natural-language findings, and replaced
the undocumented heuristic confidence formula with a defensible, weighted
Risk Confidence Score. The specific Phase 1 weakness this phase targeted —
the flagship fraud demo case producing a low-confidence "Monitor only"
verdict despite a genuinely correct detector flag — is fixed, and the fix
is verifiable end to end with a real regression test
(`tests/test_case_builder.py::test_strong_multi_signal_fraud_pattern_escalates_once_persistence_confirms`).

The benchmark was also substantially expanded (6 archetypes → 19, covering
legitimate/suspicious/ambiguous regimes) and evaluated across 10 seeds. This
surfaced a genuine, non-cherry-picked finding: on the harder, more diverse
benchmark, Drift Watch's event-level F1 and latency are actually **slightly
worse** than the naive static-threshold comparator's, even though Drift
Watch still wins clearly on the original benchmark and on false-alert
stability. This is reported in full, not hidden, in
`evaluation/MULTI_SEED_EVALUATION.md`.

## Baseline vs New System

See `PHASE_2_BASELINE.md` for the full pre-change snapshot. Summary of what changed:

| | Phase 1 (baseline) | Phase 2 |
|---|---|---|
| Evidence | Unstructured `Finding` (summary string + ad hoc dict) | Structured `Evidence` dataclass with 5 typed categories (trigger/contextual/historical/contradicting/missing) |
| Investigators | 4 (volume, dispute, geography, category) — **refund had no dedicated investigator**, a real Phase 1 gap found this session | 5, one per independent signal group |
| Trigger evidence source | Recomputed 5-day trailing average, independent of the detector | The detector's own `baseline_mean_<feat>`/`baseline_std_<feat>`/`z_<feat>` columns — cannot disagree with the detector by construction |
| Confidence | `min(0.95, 0.15 + 0.22 * n_risk_signals)`, unexplained constants | 5-component weighted Risk Confidence Score, documented in `docs/CONFIDENCE_MODEL.md` |
| Decision | 3-tier severity only (low/medium/high), always "Monitor" at low | 3-way decision: ESCALATE / MONITOR / REQUEST_MORE_EVIDENCE |
| Flagship demo case (M0021, day 178) | `confidence_risk=0.15`, "Monitor only" | `final_score=0.54`, `REQUEST_MORE_EVIDENCE` (honestly reflects 1 day of evidence); `final_score=0.75`, `ESCALATE` by day 180 once persistence confirms |
| Benchmark | 6 archetypes, 24 merchants, 1 seed | 19 archetypes (+13 new), 42 merchants, evaluated across 10 seeds |
| Signal taxonomy | Implicit in detector code only | Formalized in `detection/signal_taxonomy.py`, shared by detector + investigators + confidence model |

## Detection Method

The detector itself (`detection/drift_detector.py::merchant_specific_drift`)
is **unchanged in Phase 2** except for exposing its own baseline mean/std/day-count
as columns, specifically so investigators can consume them (see Evidence
Model below). No leakage was reintroduced — `shift(1)` semantics preserved
exactly; all 19 Phase 1 tests plus new Phase 2 tests confirm this
(37 total, all passing).

## Baseline Experiments

Full results: `evaluation/BASELINE_EXPERIMENTS.md`. Compared the shipped
rolling mean/std against rolling median/MAD and EWMA on two datasets.
**Decision: kept rolling mean/std** — it has the best F1 on both datasets
and is 5-9x faster than median/MAD; neither alternative gave a "materially
better" robustness improvement per the task brief's own bar. A genuinely
counterintuitive finding was surfaced and reported rather than hidden:
EWMA had the *highest* average latency (8.95 days) of the three methods on
the richer benchmark, the opposite of the usual assumption that
exponential weighting "reacts faster."

## Signal Grouping

Formalized in `detection/signal_taxonomy.py` as the single shared source of
truth for the detector, investigators, and confidence model. 5 of 7
taxonomy dimensions from the task brief are implemented (VOLUME, REFUND,
DISPUTE, CATEGORY, GEOGRAPHY); CUSTOMER_BEHAVIOR and SETTLEMENT/PAYMENT
have **no corresponding feature in the current dataset** and are
explicitly documented as uncovered gaps (`UNCOVERED_DIMENSIONS` in the same
file), not silently omitted.

## Evidence Model

Full detail: `docs/EVIDENCE_MODEL.md`. Five evidence types (trigger,
contextual, historical, contradicting, missing) per signal group, per
flagged day. The core fix: TRIGGER evidence is built directly from the
detector's own stored baseline columns, never recomputed — this is what
makes the temporal mismatch found in Phase 1 (§9) structurally impossible
to reintroduce, rather than just patched for one case.

## Confidence Model

Full detail: `docs/CONFIDENCE_MODEL.md`. Explicitly named "Risk Confidence
Score" (never "probability" — not calibrated against outcome data). Five
weighted, documented components: anomaly_strength (0.30), signal_breadth
(0.20), temporal_persistence (0.20), evidence_balance (0.20), novelty
(0.10), with a separate missing-evidence cap applied after the weighted sum
rather than averaged into it. 8 unit tests
(`tests/test_confidence_model.py`) cover the full required matrix: weak
signal, strong signal, multiple independent signals, contradictory
evidence, missing evidence, strong legitimate explanation, plus bounds and
no-evidence-at-all safety checks — all passing.

## Competing Hypotheses

Every case still carries `hypothesis_a`/`hypothesis_b` text plus
`evidence_for_a`/`evidence_for_b`/`evidence_missing` lists derived directly
from the structured evidence (not a separate parallel computation). As
documented in `docs/CONFIDENCE_MODEL.md` Limitations, Hypothesis B does not
get a fully symmetric numeric score in this phase — only Hypothesis A's
Risk Confidence Score was in scope per the task brief's step 12 (singular:
"replace the existing... confidence model" for risk). This asymmetry is a
real, acknowledged simplification, not hidden.

## Golden Cases

Three deterministic scenarios (`tests/test_golden_cases.py`), all passing:

- **GOLDEN_RISK**: coordinated, persistent, 4-signal drift → `ESCALATE` (checked 4 days into onset, once persistence evidence exists).
- **GOLDEN_LEGITIMATE**: clean single-signal volume spike, everything else flat → does not escalate.
- **GOLDEN_AMBIGUOUS**: refund rises while dispute simultaneously falls → `REQUEST_MORE_EVIDENCE`.

None of these were tuned by adjusting thresholds until they passed — the
underlying confidence formula was fixed first (via the unit tests above),
and the golden cases were verified against it, not the reverse.

## Multi-Seed Results

Full detail: `evaluation/MULTI_SEED_EVALUATION.md`. 10 seeds, richer
42-merchant population, 26 ground-truth events each. Headline numbers
(mean ± std across seeds):

| Detector | Event recall | Event precision | Event F1 | Avg latency | False alert rate |
|---|---|---|---|---|---|
| Drift Watch | 0.812 ± 0.082 | 0.564 ± 0.047 | 0.663 ± 0.043 | 9.15d ± 3.93 | 0.005 ± 0.001 |
| Static threshold | 0.642 ± 0.068 | 0.788 ± 0.123 | 0.701 ± 0.066 | 6.97d ± 1.14 | 0.010 ± 0.012 |

**The honest finding**: on this harder, more diverse benchmark, Drift
Watch's F1 and latency are both slightly *worse* than the static
comparator's, even though its recall is higher and its false-alert rate is
both lower and far more stable across seeds. This reverses part of the
Phase 1 headline claim (which was measured only on 4 fast, strong,
coordinated fraud events) and is investigated, not hidden, in the linked
document: several of the 13 new archetypes were deliberately built to be
slow-onset or single-signal, which the 2-independent-signal-group rule
takes longer to accumulate evidence for than a cruder fixed threshold does.

## Baseline Comparison

Same events, same evaluation methodology, leakage-free comparator (Phase 1
already fixed the static threshold's own leakage bug) — see the multi-seed
table above and `evaluation/BASELINE_EXPERIMENTS.md`. The honest tradeoff:
Drift Watch is the more conservative, more stable detector (lower and
far-less-variable false-alert rate) that catches more of the harder events
but takes longer and alerts on more legitimate episodes to do so, on this
specific harder benchmark. On the original, simpler benchmark it is
unambiguously better on every axis.

## Failure Modes

`tests/test_failure_handling.py` (5 tests, all passing): missing evidence
never counted as supporting either hypothesis; a feature's detector columns
being entirely absent degrades to MISSING evidence rather than crashing or
fabricating a value; an empty scored-history dataframe degrades safely; a
flag with no real investigative corroboration never escalates; conflicting
refund-up/dispute-down evidence never produces false high confidence.

## Remaining Weaknesses — brutally honest

1. **Single-day case snapshots.** `build_case` scores one flagged day at a
   time, not a whole episode. Directly observed on M0021: day 180
   `ESCALATE`, day 182 `ESCALATE`, day 185 `REQUEST_MORE_EVIDENCE` — same
   underlying persistent fraud episode, fluctuating decision, because
   `signal_breadth` varies day to day within the episode. Top Phase 3
   priority.
2. **The multi-seed reversal (F1/latency worse than the naive comparator on
   the harder benchmark)** is real and unresolved. It doesn't mean Drift
   Watch is "worse" — its false-alert stability is genuinely better — but
   the headline "Drift Watch beats the baseline on every axis" claim from
   Phase 1 no longer holds once the benchmark is harder and more diverse.
   Future work should explore whether a lower `MIN_SIGNALS_FOR_FLAG` (e.g.
   requiring only 1 signal group for very high-z anomalies) recovers
   recall/latency on slow/single-signal regimes without giving up the
   false-alert stability advantage.
3. **Hypothesis B has no symmetric numeric score** (see Confidence Model
   Limitations) — deferred by explicit task-brief scoping, but still a gap.
4. **CUSTOMER_BEHAVIOR and SETTLEMENT/PAYMENT taxonomy dimensions are
   completely unimplemented** — no feature exists for either in the
   current dataset.
5. **CONTRADICTING evidence treats all 5 signal groups as equally
   risk-relevant** regardless of what actually triggered the flag — a
   simplification, documented in `docs/EVIDENCE_MODEL.md`.
6. **rolling_median_mad catches 2 more of the harder benchmark's events
   than the shipped method**, at a real precision/latency cost — the
   tradeoff decision (keep mean/std) is defensible but not free.
7. Everything already listed in `PHASE_1_REPORT.md` §9 that Phase 2 did NOT
   address: confidence is still not a calibrated probability by design
   (now at least documented and componentized, per task brief step 12's
   explicit instruction not to claim calibration); case builder still runs
   all 5 investigators unconditionally rather than selecting them
   dynamically (still not "genuinely agentic" tool selection).

## Recommended Phase 3

Aggregate confidence across a whole flagged episode (contiguous flagged
days for one merchant), not just a single day snapshot — this is the
single highest-value fix given weakness #1 above, and would likely also
narrow the multi-seed F1/latency gap in weakness #2, since a persistent
low-breadth episode would accumulate corroborating days into one
confidence trajectory instead of flip-flopping between ESCALATE and
REQUEST_MORE_EVIDENCE day to day.
