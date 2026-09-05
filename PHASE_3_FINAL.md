# Phase 3 Final — Verified Cleanup Pass

This is a verification and documentation-cleanup pass over the completed
Phase 3 work — no redesign, no threshold changes, no new features, per
the instruction that produced this document. Every number below was
re-run in this session, not copied from prior reports.

## Cleanup actually performed

1. **GAP_TOLERANCE_DAYS terminology made explicit**, in `episode/grouping.py`,
   `docs/EPISODE_MODEL.md`, and `docs/STATE_MACHINE.md`: it is the maximum
   number of SKIPPED (unflagged) calendar days tolerated between two
   flagged days, not the maximum day-index difference — the code
   (`d - previous_flagged_day <= GAP_TOLERANCE_DAYS + 1`) was already
   correct; only the prose around it was ambiguous. Confirmed
   no behavior change: 49/49 tests pass identically before and after.
2. **Removed a stale, false claim** in `PROJECT_STATE.md`'s old
   "Current competitive self-score" section, which still said "static
   baseline leakage still needs fixing" and "static baseline has
   undisclosed-until-now leakage" — both false since Phase 1 fixed this
   and every subsequent phase's reruns have verified it stays fixed.
   Replaced with a score section that reflects the actual current
   repository state (matches `PHASE_3_REPORT.md`'s score).
3. **Reorganized `PROJECT_STATE.md`'s "next steps"** so the top-line
   bottleneck is explicitly named as real agentic investigation, with the
   deterministic core (detector → evidence → episodes → confidence →
   state machine) framed as the foundation it now is, and the remaining
   deterministic-layer gaps (duplicate fragmentation, seasonal
   over-escalation, etc.) moved to an explicitly parallel, non-blocking
   track — not implemented, only re-labeled.
4. Verified the three disclosures the instructions called out by name are
   still present, explicit, and unweakened: the 25.5% duplicate episode
   rate, the seasonal false-escalation limitation, and the fact that
   episode grouping does NOT improve raw precision/F1 (it makes both
   measurably worse — `evaluation/EPISODE_EVALUATION.md`'s own section
   heading says this outright).

## Verified architecture (unchanged from Phase 3, confirmed still accurate)

```
detection/drift_detector.py       per-merchant z-score detector, unchanged since Phase 1
detection/signal_taxonomy.py      5 independent signal groups (volume/refund/dispute/category/geo)
agents/evidence.py                typed Evidence (trigger/contextual/historical/contradicting/missing)
agents/investigators.py           single-day evidence, one investigator per signal group
agents/confidence.py              5-component Risk Confidence Score + 3-way decision (unchanged since Phase 2)
episode/grouping.py               gap-tolerant clustering (GAP_TOLERANCE_DAYS=2, terminology now explicit)
episode/model.py                  RiskEpisode dataclass
episode/state_machine.py          WATCH / INVESTIGATING / ESCALATE / RESOLVED
episode/aggregation.py            episode-to-date evidence, recomputed fresh each day (not incrementally appended)
episode/builder.py                orchestrator - walks a merchant's history, builds complete episodes
evaluation/matching.py            episode-to-ground-truth matching (any-day-overlap rule)
evaluation/episode_metrics.py     episode-primary metrics (day-level metrics kept as diagnostics)
```

## Verified test count

```
$ python3 -m pytest tests/ -q
49 passed in ~3s
```
9 test files, 49 individual test functions, all passing, re-run in this
session immediately before writing this document.

## Verified benchmark numbers (re-run this session, not copied)

**Original benchmark (24 merchants, seed=42), day-level:**
| Detector | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| Static global threshold | 0.561 | 0.520 | 0.540 | 2.02% |
| Drift Watch | 0.519 | 0.154 | 0.237 | 0.71% |

**Original benchmark, event-level:** Static 3/4 events (0.75 recall, 3.67d
latency); Drift Watch 4/4 (1.0 recall, 1.0d latency).

**Multi-seed (10 seeds, 42-merchant richer benchmark) — day-level system vs episode system:**
| System | Recall | Precision | F1 | Avg latency | Duplicate rate |
|---|---|---|---|---|---|
| Current (day-level) | 0.812 | 0.564 | 0.663 | 9.15d | n/a |
| Episode (Phase 3) | 0.812 | 0.464 | 0.589 | 9.15d | 0.255 |

**Ablations (original benchmark):** confidence-gating gives the only clear
precision win (0.286 vs. 0.205 plain-grouping baseline, zero recall cost).
Plain grouping alone does not improve precision on either benchmark.

**Baseline method comparison (rolling mean/std vs. median/MAD vs. EWMA):**
rolling mean/std remains best F1 on both datasets and 5-9x faster; kept as
the shipped default — no change made in this pass.

Every one of these numbers was reproduced fresh in this session's pipeline
run and matches the previously-reported figures exactly.

## Genuine improvements (this phase, confirmed still holding)

1. **The confidence-trajectory flip-flop is fixed and stays fixed.**
   M0021's real 10-day fraud episode: `[0.73, 0.84, 0.79, 0.79, 0.79, 0.79,
   0.79, 0.79, 0.79, 0.79, 0.79, 0.79, 0.79]` — no oscillation, re-verified
   this session. Covered by 6 invariant tests and 6 episode golden cases.
2. **A real false-escalation bug was found** (a legitimate seasonal
   merchant escalating on 3/4 of its annual occurrences) — something the
   Phase 2 single-day model structurally could not have surfaced, since it
   never examined a merchant's confidence across multiple related days.
3. **Confidence-gating gives a genuine, measured precision improvement**
   on the original benchmark, at zero recall cost there.
4. **A bad fix was caught and reverted before shipping** — the
   `ESTABLISHED_PATTERN_DISCOUNT` attempt broke real fraud detection and
   was rolled back the same session it was tried, documented in
   `DECISIONS.md` D10 rather than either silently kept or silently dropped
   without explanation.

## Genuine regressions (this phase, confirmed still holding)

1. **Episode-level precision and F1 are measurably worse than day-level**,
   on both the ablation experiments and the 10-seed regression — 0.464 vs
   0.564 precision, 0.589 vs 0.663 F1, identical recall and latency. This
   is not a claim episodes make detection better; they don't, and this
   document does not soften that.
2. **25.5% of matched events fragment into more than one predicted
   episode** on the richer benchmark (mean, 10 seeds) — `GAP_TOLERANCE_DAYS=2`
   is insufficient for some slower-onset regimes.

## Known limitations (unresolved, unchanged from PHASE_3_REPORT.md)

- Seasonal-merchant over-escalation is only partially fixed (see
  DECISIONS.md D10 for the reverted attempt and why it was reverted).
- Confidence-gating trades away real recall on the richer benchmark's
  deliberately-ambiguous archetypes — a genuine, unresolved tension in
  what "recall" should even measure for a system designed to sometimes say
  "I'm not sure."
- No symmetric Hypothesis B numeric score.
- CUSTOMER_BEHAVIOR and SETTLEMENT_PAYMENT signal-taxonomy dimensions
  remain fully uncovered — no feature exists for either.
- No load-testing of the episode builder at scale.

## Why the deterministic core is ready for an agentic layer

Three phases of independent, reproducible verification have established
something specific enough to build on: a leakage-free detector (verified
fresh in this session, not just claimed), a structured multi-temporal
evidence model with documented deduplication guarantees (verified by
invariant tests, not just described), a confidence model with named,
weighted components rather than unexplained constants, and — as of this
phase — a stateful episode object with an append-only evidence timeline
and a transition log whose reasons are built from real computed values,
not canned text. That combination is exactly the substrate a real agentic
layer needs: something to ground an LLM's hypothesis generation and
narrative synthesis in, and something whose confidence/decision math the
LLM should be prevented from touching directly (per DECISIONS.md D4). What
the deterministic core cannot do on its own — and what makes it the wrong
place to keep investing further before building the agentic layer — is
decide WHICH investigators to run for a given trigger (it always runs all
5), or generate a hypothesis the fixed rule table didn't anticipate, or
explain a case in language a human reviewer would actually want to read
rather than a structured dump. Those are agentic problems, not
statistical ones, and the deterministic core has been pushed about as far
as it usefully can be without one. The unresolved deterministic-layer
weaknesses documented above (seasonal over-escalation, episode
fragmentation) are real and should still get fixed, but neither of them
blocks starting the agentic layer — they can be hardened in parallel, as
now reflected in `PROJECT_STATE.md`.

## Final verification statement

`python3 -m pytest tests/ -q` → 49 passed. Full pipeline (generator →
detector → evaluate → demo → baseline experiments → both multi-seed
scripts → ablations) re-run end to end in this session; every reported
number matches. No thresholds changed. No metrics tuned. No new features
added. No redesign performed.
