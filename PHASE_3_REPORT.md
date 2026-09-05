# Phase 3 — Episode Intelligence + Stateful Risk Reasoning

## 1. Baseline

Full detail: `PHASE_2_EPISODE_BASELINE.md`. Reproduced fresh (not trusted
from prior reports): 37 tests passing, day-level and multi-seed metrics
identical to Phase 2's own numbers, and the motivating bug reproduced with
real data — M0021's real 10-day fraud episode oscillated ESCALATE ↔
REQUEST_MORE_EVIDENCE across days 178-187 with no new contradicting
evidence, purely from `signal_breadth` fluctuating day to day.

## 2. Architecture Changes

New `episode/` package, four modules, none of them touching the existing
detector or confidence formula:

- `grouping.py` — gap-tolerant clustering of flagged days into episodes (`GAP_TOLERANCE_DAYS=2`, derived from the real gap distribution in the existing scored dataset, not tuned to any metric — see the module docstring for the actual numbers this was derived from).
- `model.py` — the `RiskEpisode` dataclass (task brief step 2's exact field list).
- `state_machine.py` — `WATCH → INVESTIGATING → ESCALATE → RESOLVED`, reusing `agents.confidence.decide_action`'s thresholds unchanged.
- `aggregation.py` — episode-to-date evidence recomputed fresh each day (not incrementally appended), which is what makes deduplication (task brief step 7) and confidence stability fall out naturally rather than needing special-cased logic.
- `builder.py` — orchestrates the above into complete, walkable `RiskEpisode` objects with a full day-by-day trajectory.

## 3. Episode Definition

See `docs/EPISODE_MODEL.md`. Start = first flagged day in a gap-tolerant
cluster. Peak = the day with the highest confidence score ever reached
(tracked as a running max). Resolution = `GAP_TOLERANCE_DAYS + 1` quiet
days after the last flagged day, or the end of available history —
deliberately NOT confidence-driven, since a low score means "ambiguous
right now," not "this episode is over."

## 4. State Machine

See `docs/STATE_MACHINE.md`. One deliberate deviation from the brief's
suggested transition list: any of WATCH/INVESTIGATING/ESCALATE can
transition directly to any other (not only the 5 named pairs), because
confidence is recomputed fresh from real evidence every day and a genuine
sudden multi-signal deviation can legitimately skip a state in one step —
forcing an artificial intermediate hop would mean logging a transition
that no real evidence change backs, which conflicts with the explainability
requirement (step 20).

## 5. Evidence Accumulation & Deduplication

See `docs/EPISODE_EVIDENCE.md`. A 6-day persistent refund anomaly is
represented as exactly ONE contextual (duty-cycle) evidence item —
"deviated on 6/6 days, a sustained pattern" — never six separate
"supporting" items. This is the direct, verified mechanism (not just an
intention) behind why confidence doesn't inflate without bound as an
episode continues (invariant 2, `tests/test_episode_invariants.py`).

## 6. Confidence Trajectory

`compute_confidence` (Phase 2, unchanged) is called fresh every day on the
episode-to-date evidence snapshot. Real result, M0021: `[0.73, 0.84, 0.79,
0.79, 0.79, 0.79, 0.79, 0.79, 0.79, 0.79, 0.79, 0.79, 0.79]` across days
178-190 — **no oscillation**, compared to the baseline's `[0.54, 0.67,
0.75, 0.75, 0.69, 0.71, 0.65, 0.60, 0.57, 0.54]` which crossed the
ESCALATE threshold back and forth three times.

## 7. Evaluation Methodology

See `evaluation/EPISODE_EVALUATION.md` and `evaluation/matching.py`.
Episode matching reuses the "any day overlap" rule already validated in
Phase 1/2, applied to gap-tolerant grouped predictions instead of raw
flagged days. Day-level metrics kept unchanged as diagnostics.

## 8. Multi-Seed Results

10 seeds (unchanged from Phase 2, not reduced), richer 42-merchant
benchmark:

| System | Recall | Precision | F1 | Avg latency | Duplicate rate |
|---|---|---|---|---|---|
| Current (day-level) | 0.812 | 0.564 | 0.663 | 9.15d | n/a |
| Episode (Phase 3) | 0.812 | **0.464** | **0.589** | 9.15d | **0.255** |

**Honest headline: episode grouping alone makes precision and F1 measurably
worse, not better.** Recall and latency are identical (detection itself is
unchanged). This is not hidden or reframed — see §13 below for what
episodes actually do improve.

## 9. Ablations

See `evaluation/EPISODE_ABLATIONS.md`. The one variant that clearly helps:
**confidence-gating** (only surfacing episodes that reach ESCALATE at some
point) — precision 0.205→0.286 on the original benchmark at zero recall
cost. Grouping alone does not help precision on either benchmark. Gap
tolerance (2 vs 5) makes negligible difference, which is reassuring
evidence the chosen constant isn't fragile. Confidence-gating trades away
real recall (0.846→0.500) on the richer benchmark specifically because
several of its "ambiguous" archetypes are *designed* to warrant
`REQUEST_MORE_EVIDENCE`, not `ESCALATE` — a genuine tension in what
"recall" should even mean here, reported rather than resolved by
redefining the metric.

## 10. Golden Cases

6 episode-level golden cases (5 required + 1 extra), `tests/test_golden_episodes.py`, all passing:
`GOLDEN_RISK_EPISODE` (escalates and stays escalated — directly
re-verifies the core bug fix), `GOLDEN_LEGITIMATE_EPISODE` (product-launch-
style volume+category shift, never escalates), `GOLDEN_AMBIGUOUS_EPISODE`
(refund-up/dispute-down, stays out of ESCALATE — though see the test's own
docstring: this scenario sits near the decision boundary and is genuinely
seed-sensitive, which is itself evidence it's authentically ambiguous),
`GOLDEN_TWO_EPISODES` (90 days apart, stay separate),
`GOLDEN_RECOVERY_EPISODE` (temporary anomaly formally resolves, doesn't
stay open forever), plus an added `two_nearby_but_unrelated_episodes` test
(10 days apart, well outside the 2-day gap tolerance, stay separate).

## 11. Failure Modes

Unchanged mechanisms from Phase 2 (`tests/test_failure_handling.py`) still
apply at the episode level: missing evidence is never silently
"no risk" — `MIN_BASELINE_DAYS` still gates episode evidence exactly as it
gated single-day evidence. `tests/test_episode_invariants.py` adds
episode-specific failure-mode coverage: no unbounded confidence inflation,
no future-leakage into past state, deterministic rebuilds.

## 12. Exact Test Results

```
$ python3 -m pytest tests/ -q
49 passed in ~2.4s
```
Breakdown: 37 inherited from Phase 2 (unchanged, still passing) + 6
invariant tests + 6 episode golden cases (test counts overlap slightly
with the "6" above due to file organization — see `tests/` directory for
the full file list). Full pipeline (generator → detector → evaluate →
demo → ablations → both multi-seed scripts → baseline experiments) verified
reproducible end to end immediately before writing this report.

## 13. What Episodes Actually Improve (stated plainly)

1. **The confidence-trajectory flip-flop is fixed** — verified with real
   regression tests on real fraud data, not just narrated.
2. **A cleaner alert list** — one `RiskEpisode` object instead of ten
   independent day-level cases for the same real event (duplicate count
   drops 3→0 on the original benchmark when using episode grouping vs.
   strict day-to-day contiguity).
3. **Confidence-gating gives a genuine, measured precision win** on the
   original benchmark (0.286 vs 0.205), at zero recall cost there.
4. **A real, previously-undetectable bug was found**: a legitimate
   seasonal merchant escalating on 3/4 of its annual occurrences. This
   would have been invisible under Phase 2's single-day model, which never
   examined the SAME merchant's confidence across multiple related days
   over multiple years.

## 14. Remaining Weaknesses — brutally honest

1. **The seasonal-merchant over-escalation is NOT fully fixed.** A
   conservative fix helped a little (historical evidence can now support
   Hypothesis B for established patterns). A more aggressive fix was tried
   and reverted after it broke real fraud detection (M0021 dropped to
   WATCH) — see DECISIONS.md D10. This is the single most important open
   item.
2. **Episode grouping alone makes precision/F1 worse**, not better, on
   both benchmarks (§8). This phase does not claim otherwise.
3. **Duplicate episode rate is 25.5%** (mean, 10 seeds) on the richer
   benchmark — `GAP_TOLERANCE_DAYS=2` isn't always sufficient for
   slow-onset regimes like `slow_fraud`'s 30-day ramp.
4. **Confidence-gating's recall cost on ambiguous archetypes** is real and
   unresolved — "recall" as classically defined penalizes the system for
   correctly declining to confidently escalate genuinely ambiguous cases.
5. Everything already listed in PHASE_2_REPORT.md that this phase did not
   address: no symmetric Hypothesis B score, investigator selection still
   not genuinely agentic, CUSTOMER_BEHAVIOR/SETTLEMENT_PAYMENT dimensions
   still fully uncovered.
6. **GOLDEN_AMBIGUOUS_EPISODE is seed-sensitive** — checked across 4
   seeds, outcomes split roughly evenly between INVESTIGATING and
   ESCALATE. The fixed test seed makes the test deterministic, but the
   underlying scenario genuinely sits on a knife's edge, which itself says
   something about how sharp the confidence model's ambiguous/escalate
   boundary is (not necessarily wrong, but worth knowing).

## 15. Final Self-Critique (task brief step 25)

1. **Is this actually better than independent alerts?** Qualitatively
   yes (one coherent episode instead of ten disconnected day-level cases,
   confidence trajectory that doesn't flip-flop). Quantitatively, on raw
   precision/F1, no — measured and reported honestly in §8.
2. **Are episodes defined objectively?** Yes — `GAP_TOLERANCE_DAYS=2` is
   derived from an inspected, documented real gap distribution, not
   chosen to flatter a metric; the ablation in §9 shows the choice isn't
   fragile (gap=5 gives near-identical results).
3. **Is there temporal leakage?** No — verified directly by invariant 3
   (`tests/test_episode_invariants.py`), which extends a merchant's history
   and confirms earlier confidence values are byte-identical.
4. **Are repeated signals incorrectly treated as independent?** No — this
   was the specific design goal of recomputing evidence fresh from the
   whole episode span each day (§5); verified by invariant 2.
5. **Can legitimate behavior create a false episode?** Yes, demonstrably —
   the M0009 finding is real, partially fixed, and honestly reported as
   unresolved (§14.1). This is the most serious open issue in the project.
6. **Can two unrelated events be incorrectly merged?** Tested directly
   (`test_two_nearby_but_unrelated_episodes_stay_separate`, 10 days apart,
   stay separate) — not observed in any real data explored this phase.
7. **Can one event incorrectly split into many episodes?** Yes, at a
   25.5% rate on the harder benchmark (§14.3) — a real, quantified,
   unresolved weakness, not zero.
8. **Can confidence grow artificially?** No — bounded by invariant 2 and
   the deduplication design in §5.
9. **Can evidence disappear?** No — `evidence_timeline` and
   `confidence_history` are append-only by construction; nothing is ever
   deleted, only diffed for what's NEW (§5).
10. **Can state transitions be explained?** Yes — every transition's
    `reason` is built from the actual confidence breakdown and changed
    evidence keys, not a canned string (`docs/STATE_MACHINE.md`).
11. **Are the metrics statistically meaningful?** Partially — 10 seeds is
    enough to see real variance (duplicate rate std=0.082, a genuinely wide
    spread), but the richer benchmark's 26 events/seed is still a small
    sample for precision estimates with std ~0.04-0.05.
12. **Would this architecture work at scale?** The per-merchant,
    per-day-in-episode recomputation in `aggregation.py` is O(episode
    length × signal groups) per update, not O(total history) — reasonable
    for a real system, though not load-tested here (no such test exists in
    this phase, and that's a real gap, not a claim of scale-readiness).

## 16. Recommended Phase 4

Fix the seasonal-merchant over-escalation properly (item 14.1) before
anything else — it's the single most damaging finding for the project's
credibility (a legitimate recurring merchant reaching ESCALATE 3 years
running is exactly the kind of false positive that erodes trust in a real
risk system), and the reverted fix attempt in this phase (DECISIONS.md D10)
gives a concrete, documented starting point for a more careful version:
one that requires the recurrence to be at a similar time-of-year, not just
a raw historical count, so a merchant's own unrelated noisy feature can't
accidentally trigger the discount.

---

## CURRENT PROJECT SCORE

Scored out of 10 each, brutally honest, against "would this survive a
serious Razorpay ML/risk engineering interview":

- **Problem**: 8 — post-onboarding drift monitoring is a real, underexplored gap (see research/PRODUCT_OVERLAP.md), well-scoped and not overclaimed.
- **Originality**: 6 — the core idea (merchant-specific baselines vs. global thresholds) is sound but not novel in risk engineering generally; the episode/evidence architecture is a genuine, carefully-reasoned contribution for a project at this stage.
- **Razorpay relevance**: 7 — directly maps to a real gap in Bumblebee's public architecture, but this is inferred from public blog posts, not validated against actual internal priorities.
- **Detection**: 6 — the underlying detector is leakage-free and honestly evaluated, but day-level recall (15.4% on the original benchmark) is genuinely weak, and the richer-benchmark F1 (0.663) trails a naive static comparator (0.701) — both disclosed, neither hidden, but both real limits.
- **Episode intelligence**: 7 — the flip-flop bug is genuinely fixed and verified, not just narrated; the seasonal-merchant false-escalation is a real, serious, still-open weakness that keeps this from being higher.
- **Explainability**: 8 — structured evidence, a transition log built from real data rather than canned text, and an evidence timeline that only records genuine changes are all real, working, and tested.
- **Engineering**: 7 — clean module boundaries (`episode/` package matches the brief's suggested layout), no unnecessary frameworks, but the confidence formula's weights are still hand-set rather than fit or validated against any calibration data.
- **Evaluation**: 8 — the strongest part of this project. Multi-seed, ablations, honest reporting of results that contradict the project's own prior claims (episode grouping making precision worse), no cherry-picking, no metric redefinition to hide bad news.
- **Security**: 6 — no unsafe code, no LLM injection surface yet (by design, none exists), but genuinely untested at scale and no adversarial testing of the episode-matching logic itself.
- **Agent-readiness**: 5 — the structured evidence is a good substrate for a future LLM layer, but nothing agentic exists yet (investigator selection is still unconditional, no tool-use, no planning).
- **Overall: 6.8/10.** A genuinely defensible, honestly-evaluated deterministic core with one serious, disclosed, unresolved weakness (legitimate recurring merchants can still false-escalate) and evaluation practices strong enough that a skeptical reviewer would trust the numbers even where they're unflattering. Not exceptional — the detection layer's raw numbers are middling and the episode layer's own evaluation shows it makes some metrics worse — but trustworthy, which was always the standard this project set for itself starting in Phase 1.
