# Project State

_Last updated: Sep 5, 2026 (session 8 — Phase 5: productization, demo, optional real-LLM adapter)_

## Session 8 — Phase 5 (this update)
Full detail in PHASE_5_FINAL.md and README.md. Summary:
- **Backend (P0)**: FastAPI app (`backend/main.py`) over the existing engine via a thin adapter (`backend/engine.py`) — detection/episode/investigation logic is CALLED, not duplicated. All required endpoints implemented (health, merchants, merchant detail+timeline, episodes, episode detail, investigate, approve, override, audit) plus request-evidence for the review UI. Typed pydantic responses; 404/409/422 semantics; decisions are final (second decision → 409); no endpoint exists that can execute an account action (asserted by test).
- **Persistence (P0)**: stdlib SQLite (`backend/db.py`) — merchants, episodes, investigations, investigation_evidence, human_decisions, audit_events; seeded from the engine, durable across reopen (tested). No Redis/Kafka/microservices by design.
- **Frontend (P0)**: React + Vite Risk Ops dashboard (`frontend/`) with Dashboard / Merchant detail / Investigation / Human Review views, zero UI dependencies, Razorpay Blade-flavored light theme (navy #0C2451, brand blue #2B84EB). Built bundle is served by the backend at `/`; `npm run dev` proxies for development. The UI makes ESCALATE ≠ automatic action explicit everywhere (topbar + autonomy explainer under the recommendation banner).
- **Real-LLM adapter (P1)**: `backend/llm.py` implements the existing `PlannerModel`/`SynthesisModel` interfaces with strict-JSON output, a tool allowlist, registry-locked evidence citations, and the recommendation ALWAYS computed by the shared deterministic rule (`agent/synthesis.py::recommendation_for` — extracted verbatim from the Phase 4 implementation; behavior identical, all prior tests pass). Deterministic implementations remain the default AND the fallback on every failure mode. Credentials only via env/.env (`.env.example` added). Honest status: tested against fake transports; no live provider call was made, so no real-LLM claim.
- **Security (P1)**: merchant-derived text sanitized before any prompt; malformed model output / invented tools / invented evidence citations rejected with deterministic fallback (each tested); approval bypass impossible (invalid decisions raise, pre-investigation decisions 409, no executable-action route exists).
- **Tests**: 70 → **102, all passing** (new: test_backend_api.py, test_persistence.py, test_llm_adapter.py). All Phase 1-4 behavior preserved.
- **Demo**: full 17-step M0021 flow works live and deterministically (dashboard → merchant → episode DW-M0021-0178 → investigate → evidence/hypotheses/synthesis → ESCALATE → PENDING_HUMAN_REVIEW → approve/override → audit trail); M0009 shows REQUEST_MORE_EVIDENCE and the override path.
- Known limitations carried forward honestly: synthetic data only; LLM adapter unexercised against a live provider; SQLite + single-process uvicorn is demo-grade; Phase 4's narrow-episode conservatism and the D10 deterministic-layer seasonal over-escalation remain documented.

## Prior session summary (session 7 — Phase 4: agentic investigation layer)
Full detail in PHASE_4_FINAL.md, docs/PHASE_4_ARCHITECTURE.md, and the `agent/` package docstrings. Summary:
- New `agent/` package: `tools.py` (5 investigation tools wrapping Phase 3's own `build_episode_signal_evidence` — they compute nothing new statistically; ground-truth columns are structurally unreadable by tools), `evidence.py` (EvidenceRegistry with stable EVID-xxx ids), `hypotheses.py` (4-hypothesis state reusing `agents.confidence.compute_confidence` UNCHANGED for RISK_DRIFT), `planner.py` (evidence-seeking `DeterministicPlanner` + pluggable `PlannerModel` interface, explicitly labeled mock), `loop.py` (bounded orchestration only; every decision point delegated to a named component), `synthesis.py` (template-based, grounded — every claim cites a registry evidence_id), `failures.py` ("a failed step never increases risk"), `policy.py` (every ESCALATE starts PENDING_HUMAN_REVIEW; `record_human_decision` is the only approval transition and has no automated caller), `audit.py` (deterministic sequence numbers), `demo.py` (`python -m agent.demo --merchant M0021`).
- **Found and fixed a genuine one-sided-evidence-pool bug via the failing golden regression**: the agent layer investigates only a narrow episode's deviant signal groups (by design), so competing hypotheses sat at 0.0 *because nothing could produce their evidence*, and "not ambiguous" was read off that artifact — the agent ESCALATEd (RISK_DRIFT 0.708) the exact refund-up/dispute-down episode the deterministic layer correctly held at 0.62/REQUEST_MORE_EVIDENCE. Fix (no thresholds touched): SUFFICIENT now also requires every signal group to have episode-window evidence (bare "historical" entries don't count), and the planner asks its documented historical_context question unconditionally after trigger coverage instead of gating it on the partial-pool score (the score-gated `_needs_more_evidence_before_deciding` was removed as the bug it was).
- Verified consequences on real runs: seed-303 conflicting episode now REQUEST_MORE_EVIDENCE (agrees with deterministic layer); M0021 flagship still ESCALATE (0.785, fully grounded, PENDING_HUMAN_REVIEW); M0009 — the seasonal false-escalation case of DECISIONS.md D10 — is no longer over-escalated by the agent layer (REQUEST_MORE_EVIDENCE via honest coverage accounting, not a tuned discount); the deterministic episode layer's own D10 limitation remains open.
- Known, accepted tradeoff (documented, not hidden): genuinely narrow fraud episodes resolve to REQUEST_MORE_EVIDENCE at the agent layer because quiet groups are never investigated (tests #1/#3 forbid it) — the conservative direction, and the direct consequence of that design.
- Test suite: 49 → 70, all passing, including the full Phase 3 regression set (episode invariants, golden episodes/cases, confidence model). Phases 1–3 source files untouched.
- Bounded execution, grounding, safe failure, audit-trail coherence, approval boundary, and reproducibility verified by direct scripted checks against the real dataset (see PHASE_4_FINAL.md).

## Prior session summary (session 6 — Phase 3: episode intelligence + stateful risk reasoning)
Full detail in PHASE_2_EPISODE_BASELINE.md, docs/EPISODE_MODEL.md, docs/STATE_MACHINE.md, docs/EPISODE_EVIDENCE.md, evaluation/EPISODE_EVALUATION.md, evaluation/EPISODE_ABLATIONS.md, PHASE_3_REPORT.md. Summary:
- New `episode/` package: `grouping.py` (gap-tolerant clustering, gap=2 derived from real data), `model.py` (`RiskEpisode` dataclass), `state_machine.py` (WATCH/INVESTIGATING/ESCALATE/RESOLVED), `aggregation.py` (episode-to-date evidence with duty-cycle persistence, deduplicated by construction), `builder.py` (orchestrator).
- **Fixed the confidence-trajectory flip-flop** documented in PHASE_2_EPISODE_BASELINE.md: M0021's real 10-day fraud episode previously oscillated ESCALATE/REQUEST_MORE_EVIDENCE day to day; now stays consistently ESCALATE (0.79) from day 178 through resolution. Verified with real regression tests (`tests/test_episode_invariants.py`, `tests/test_golden_episodes.py`), not just the one demo case.
- **Found and partially fixed a real false-escalation bug**: a legitimate recurring seasonal merchant (M0009) was escalating on 3/4 of its annual occurrences. One conservative fix shipped (historical evidence can now support Hypothesis B for established patterns, not just "not support A"). A more aggressive fix was tried and REVERTED after it broke real fraud detection (see DECISIONS.md D10) — this remains a documented, unresolved limitation, not swept under the rug.
- 6 property-based invariant tests, 6 episode-level golden cases (5 required + 1 extra robustness scenario), all passing honestly — including one invariant test that documents the seasonal-escalation limitation directly rather than asserting a false pass.
- Ablations (`evaluation/EPISODE_ABLATIONS.md`): confidence-gating (only surfacing episodes that reach ESCALATE) gives the clearest precision win (0.205→0.286 on the original benchmark, zero recall cost); grouping alone does NOT improve precision on either benchmark (a real, reported-not-hidden finding); confidence-gating trades away too much recall on the richer benchmark's deliberately-ambiguous archetypes.
- Multi-seed regression (10 seeds, unchanged from Phase 2): episode-level precision/F1 are measurably worse than day-level (0.464 vs 0.564 precision, 0.589 vs 0.663 F1) — recall and latency are identical since detection itself didn't change. Reported honestly per `evaluation/EPISODE_EVALUATION.md`.
- Test suite: 37 → 49, all passing.

## Prior session summary (session 5 — Phase 2: detection intelligence + evidence reasoning)
Full detail in PHASE_2_BASELINE.md, docs/EVIDENCE_MODEL.md, docs/CONFIDENCE_MODEL.md, evaluation/BASELINE_EXPERIMENTS.md, evaluation/MULTI_SEED_EVALUATION.md, PHASE_2_REPORT.md. Summary:
- Replaced unstructured `Finding` objects with typed `Evidence` (trigger/contextual/historical/contradicting/missing) built directly from the detector's own baseline columns — structurally fixes the Phase 1 §9 temporal-mismatch weakness (verified: the flagship fraud case now escalates by day 180 of its onset, once persistence confirms it, instead of permanently reading "Monitor only").
- Replaced the heuristic confidence formula with a documented, 5-component Risk Confidence Score (`agents/confidence.py`) and a 3-way decision (ESCALATE/MONITOR/REQUEST_MORE_EVIDENCE).
- Added a Refund Investigator - Phase 1 never had one despite `refund` being one of the 5 signal groups, a real gap found this session.
- Formalized the signal taxonomy (`detection/signal_taxonomy.py`) as a shared source of truth; documented 2 of 7 taxonomy dimensions (customer behavior, settlement/payment) as fully uncovered.
- Expanded the synthetic benchmark from 6 to 19 archetypes (`build_richer_population`), evaluated across 10 independent seeds.
- **Honest, non-cherry-picked finding**: on the harder 19-archetype benchmark, Drift Watch's event F1 (0.663) and latency (9.15d) are slightly worse than the naive static-threshold comparator's (0.701, 6.97d), even though recall is higher and false-alert rate is lower and far more stable. This reverses part of the Phase 1 headline claim, which was only measured on 4 fast, strong, coordinated fraud events. See evaluation/MULTI_SEED_EVALUATION.md.
- Compared 3 baseline computation methods (rolling mean/std, rolling median/MAD, EWMA); kept the shipped mean/std method (best F1, fastest) after reproducing all 3 on 2 datasets.
- Added 3 golden-case tests, 8 confidence-model unit tests, 5 failure-handling tests. Test suite: 19 → 37, all passing.

## Prior session summary (session 4 — independent Phase 1 re-audit, Aug 24 2026)
A fresh Phase 1 audit was run treating the repository as the only source of truth (prior session's docs were not trusted, only used as leads to verify). Full detail in PHASE_1_AUDIT.md, PHASE_1_BASELINE.md, docs/TEMPORAL_WINDOWS.md, PHASE_1_REPORT.md. Summary:
- **Confirmed accurate**: data generation determinism, detector's own 81/5760 flag count, day-level and event-level metrics, the previously-fixed event/evidence alignment bug and `eval()`→`ast.literal_eval` fix, no hardcoded paths, no unsafe code in the live pipeline. 14/14 prior tests genuinely pass.
- **Found 1 real, previously deferred bug and fixed it**: `static_threshold_baseline`'s txn_count leg computed a single `.quantile(0.98)` over the entire dataset (all future days included) — real temporal leakage in the comparison strawman. Fixed to an expanding, history-only, day-indexed quantile with a minimum-history warm-up. This changed the static comparator's day-level precision from 0.573 → 0.561 and FPR from 1.93% → 2.02% (small but real; Drift Watch's own numbers are unaffected). 2 new regression tests added.
- **Found 1 stale/false documentation claim**: AUDIT_REPORT.md §4 claimed the arbitrary confidence formula was "fixed this session" — it was not; the code is unchanged (`0.15 + 0.22 * n_risk_signals`). Flagged; AUDIT_REPORT.md's claim should be treated as incorrect, not the code.
- **Found 1 new, previously undocumented methodological weakness**: the flagship demo case (M0021, fraud-drift) gets flagged correctly on day 178 (first day of a 10-day flagged run matching the true drift window), but the investigators' 5-day trailing-average evidence window is diluted enough by pre-drift days that all 4 investigators report `supports_risk: false`, producing `confidence_risk: 0.15` / `severity: low` / "Monitor only" for a merchant that is, by ground truth, actively fraud-drifting. Not fixed (redesigning investigator windows is out of Phase 1 scope per the task brief) — documented in docs/TEMPORAL_WINDOWS.md and flagged as the top Phase 2/demo-selection priority, since it currently undercuts the project's own walkthrough.
- Added 5 new regression tests (14 → 19): static-baseline leakage, static-baseline minimum-history warm-up, malformed/malicious `ast.literal_eval` payload handling, missing-value (NaN) handling in the detector. Fixed a `datetime.datetime.utcnow()` deprecation warning (81 occurrences across the test run) by switching to `datetime.now(timezone.utc)`.

## Prior session summary (session 3 — Phase 1 correctness pass, Aug 21 2026)

## Current concept
Drift Watch — autonomous post-onboarding merchant risk-drift detection & investigation agent. Track: AI Risk Manager.

## Architecture (current)
Sentinel (statistical drift detector, merchant-specific baseline) → 4 Investigator sub-agents (Transaction, Dispute, Geography, Merchant Profile) → Evidence Correlator + Case Builder (currently rule-based, designed with an explicit seam for an LLM call) → structured case with Hypothesis A/B, confidence, recommended action, full audit log.

## Completed this session
- Research: RAZORPAY_RESEARCH.md, PRODUCT_OVERLAP.md, COMPETITIVE_ANALYSIS.md
- Product spec: docs/PRODUCT_SPEC.md (problem, users, journey, data model, eval methodology, security model, demo scenario)
- Synthetic data generator (`data/synthetic_generator.py`) — 6 merchant archetypes (normal, seasonal, growing, product_launch, geo_expansion, fraud_drift), 240 days, ground-truth drift labels
- Detection layer (`detection/drift_detector.py`) — merchant-specific rolling baseline + z-score + independent signal-domain grouping; static-threshold baseline for comparison
- Investigator agents (`agents/investigators.py`) — 4 specialized evidence-gathering functions
- Case builder (`agents/case_builder.py`) — correlation, hypothesis generation, confidence scoring, audit log
- Evaluation harness (`evaluation/evaluate.py`) — precision/recall/F1/FPR/detection-latency, real numbers on synthetic data (see evaluation/results.csv)
- End-to-end demo script (`scripts/run_demo_case.py`) — runs full loop, prints reviewable case JSON

## Real results from this session (synthetic data, not fabricated)
| Detector | Precision | Recall | F1 | FPR | Merchants w/ fraud drift missed | Avg detection latency |
|---|---|---|---|---|---|---|
| Static global threshold | 0.573 | 0.520 | 0.545 | 1.93% | 1 of 4 | 3.67 days |
| Drift Watch (merchant-specific) | 0.519 | 0.154 | 0.237 | 0.71% | 0 of 4 | 1.0 days |

Honest read: Drift Watch trades day-level recall for far fewer false positives and catches every fraud-drift merchant faster. This is a defensible design point (fewer, higher-quality investigation triggers) but the day-level recall number (15%) is genuinely weak and should be improved, not hidden, before submission.

## Known bugs fixed this session (kept for transparency / self-critique material)
1. `txn_count` and `txn_volume` are algebraically correlated; originally counted as 2 independent signals toward the correlation threshold, inflating false positives. Fixed by grouping into independent signal domains (`SIGNAL_GROUPS`).
2. Investigators assumed a fixed 60-day baseline lookback; early flags (before day ~75) had no valid baseline and printed a meaningless "shifted from 'unknown'" line. Fixed with a graceful fallback baseline window + explicit "insufficient history" finding.
3. numpy bool values were serializing as the strings `"True"`/`"False"` instead of JSON booleans in case output. Fixed by casting `supports_risk` to native `bool`.

## Session 2/3 — Phase 1 correctness audit (this update)
See AUDIT_REPORT.md, PHASE_1_BASELINE.md, and PHASE_1_REPORT.md for full detail. Summary:
- **Confirmed 3 real correctness bugs** in the demo script and portability: an event/evidence mismatch (signal groups reported for the wrong day in some cases), an unsafe `eval()`, and hardcoded absolute paths across 5 files. All 3 fixed and verified.
- **Added 14 regression/edge-case tests** across `tests/test_event_alignment.py`, `tests/test_detector.py`, `tests/test_data_handling.py`, `tests/test_case_builder.py`. All pass. Most important addition: a direct temporal-leakage test proving Drift Watch's own detector never uses future data to score a past day.
- **Added event-level evaluation** (`evaluation/evaluate.py`) alongside the existing day-level metrics (day-level metrics unchanged, kept for comparison). This reveals the previously-reported 15.4% day-level recall was understating real performance: **event-level recall is 100% (4/4 fraud-drift episodes detected), vs. 75% for the static baseline**, with a 4x lower false-alert rate. This is now the headline number, not day-level recall.
- **Found and documented, but did NOT fix** (explicitly out of scope for this phase): the static-threshold comparison baseline computes its quantile globally across the whole dataset (a form of temporal leakage specific to that strawman, not to Drift Watch itself), and the arbitrary confidence formula in `case_builder.py`. Both are now the top Phase 2 candidates.

## Updated evaluation numbers (event-level, added this session — the number to lead with)
| Detector | Event recall | Avg detection latency | False alert rate (non-event days) |
|---|---|---|---|
| Static global threshold | 75% (3/4) | 3.67 days | 1.93% |
| Drift Watch (merchant-specific) | **100% (4/4)** | **1.0 days** | **0.71%** |

Day-level metrics (unchanged from session 1, kept alongside — see README/PHASE_1_REPORT for why both are shown): precision 0.519/0.573, recall 0.154/0.520, F1 0.237/0.545 for Drift Watch/static respectively.

## Current frontier: REAL LLM BEHIND THE AGENTIC SEAM

The deterministic core plus the agentic orchestration layer are now complete:
Phase 4 added the evidence-seeking planner, typed tools, grounded synthesis,
bounded loop, failure policy, and human-approval boundary (see PHASE_4_FINAL.md
and docs/PHASE_4_ARCHITECTURE.md). What remains deliberately deterministic is
the planner's and synthesis model's *implementation* — both sit behind
pluggable interfaces (`PlannerModel`, `SynthesisModel`) with explicitly-labeled
mock implementations, which is the designed seam for a real LLM. Plugging one
in requires the injection-verification checklist in
docs/PHASE_4_ARCHITECTURE.md "Security" (adversarial tests over every field
the model reads, model output only entering via the grounded-template path,
and the model never writing a number that didn't come from an AgentEvidence)
— per DECISIONS.md D4, the confidence/decision math stays out of the model's
hands either way. Do not start this until explicitly asked to.

## Remaining deterministic-layer hardening (parallel track, not blocking the agentic layer)
1. **Reduce episode false-positive fragmentation on slow-onset regimes.** Duplicate episode rate is 25.5% (mean, 10 seeds) on the richer benchmark — `GAP_TOLERANCE_DAYS=2` (derived from the original benchmark's fraud archetypes) isn't always enough for `slow_fraud`'s 30-day ramp. Consider an adaptive gap tolerance keyed to a regime's observed onset speed, rather than one fixed constant.
2. **Resolve the seasonal-merchant over-escalation properly** (M0009 still escalates on 3/4 occurrences) — the reverted `ESTABLISHED_PATTERN_DISCOUNT` approach (see DECISIONS.md D10) needs to distinguish "this SPECIFIC deviation recurs for this merchant" from "this merchant has some noisy feature somewhere in 200+ days of history" before it's safe to ship — likely needs the historical check to require the recurrence be at a similar time-of-year/periodicity, not just a raw count.
3. Recover episode-level precision without giving up the confidence-gating recall on ambiguous archetypes — investigate a middle ground between "any flagged episode is an alert" and "only ESCALATE episodes are alerts" (e.g. surface INVESTIGATING episodes as lower-priority queue items rather than dropping them).
4. Build a symmetric Hypothesis B numeric score (still qualitative/evidence-list only, unchanged from Phase 2 scope).
5. Add CUSTOMER_BEHAVIOR and SETTLEMENT/PAYMENT signal groups (still fully uncovered).
6. FastAPI backend wrapping episode/detection/agents modules + PostgreSQL for persistence (episodes are a natural fit for a real table now that they're stateful objects).
7. Minimal frontend: merchant list by episode status, episode detail view (confidence trajectory chart + evidence timeline + transition log + hypotheses + approval buttons).
8. Prompt-injection adversarial tests once the agentic/LLM layer exists.

## Current competitive self-score (honest, reflects current repository state — see PHASE_4_FINAL.md and PHASE_3_REPORT.md for the phase-level breakdowns)
Problem 8 · Originality 6 · Razorpay relevance 7 · Detection 6 (leakage-free and honestly evaluated — Phase 1 found and fixed the static comparator's temporal leakage, verified still fixed in every subsequent phase's reruns; day-level recall and richer-benchmark F1 remain genuinely weak, both disclosed) · Episode intelligence 7 (the confidence flip-flop is genuinely fixed and regression-tested; the seasonal-merchant false-escalation is real, partially fixed — the Phase 4 agent layer no longer over-escalates M0009 — but still open at the deterministic episode layer) · Explainability 8 · Engineering 7 · Evaluation 8 (the project's strongest asset — multi-seed, ablations, and a consistent record of reporting findings that contradict its own prior claims rather than hiding them) · Security 7 (structural approval boundary + no free-text injection surface + grounded synthesis; still no adversarial tests against a real LLM because none is wired in) · Agent-readiness 7 (genuine agentic layer now exists — evidence-seeking planner, typed tools, bounded loop, failure policy, audit trail, pluggable model seams — but the planner/synthesis implementations are labeled deterministic mocks, and narrow episodes resolve conservatively to REQUEST_MORE_EVIDENCE by documented design) · **Overall 7.1/10**.

**What would make a Razorpay engineer push back today**: no frontend/backend, the planner and synthesis are deterministic mocks behind their interfaces (a real LLM is the designed next step, with the injection checklist in docs/PHASE_4_ARCHITECTURE.md), the agent layer is deliberately more conservative than the deterministic layer on narrow episodes (REQUEST_MORE_EVIDENCE instead of ESCALATE — defensible, but a reviewer will ask about it), and a legitimate recurring seasonal merchant can still false-escalate at the deterministic episode layer (DECISIONS.md D10). All four are explicit, tracked priorities — not surprises.

