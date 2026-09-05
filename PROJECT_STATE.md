# Project State

_Last updated: Aug 24, 2026 (session 4 — independent Phase 1 re-audit)_

## Session 4 — independent re-audit (this update)
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

## Next session priorities (in order — updated post-session-4 re-audit)
1. **Reconcile investigator evidence windows with the detector's per-day sensitivity** (or change demo-day selection to prefer a day with stronger corroborating evidence within the flagged run) — top priority, since the current mismatch produces a "Monitor only" recommendation for the flagship fraud demo case. See docs/TEMPORAL_WINDOWS.md §3.
2. Replace the arbitrary confidence formula (`0.15 + 0.22 * n_risk_signals`) with defensible, documented components (detector strength, signal magnitude, signal independence, temporal consistency, evidence quality, hypothesis separation). Note: AUDIT_REPORT.md previously claimed this was already done — it was not; do not skip this item.
3. Make the case builder's investigator selection genuinely agentic — currently all 4 investigators always run regardless of which signal group triggered the flag; a real planner would skip investigators clearly irrelevant to the trigger (e.g. skip Geography Investigator on a pure refund-rate trigger). This is the top "agentic depth" credibility gap per AUDIT_REPORT.md.
4. Wire the real Claude API call into case_builder.py for narrative generation, with grounding-evidence-only prompting.
5. FastAPI backend wrapping the existing detection/agents modules + PostgreSQL for persistence.
6. Minimal frontend: merchant list by health state, case detail view (timeline + evidence + hypotheses + approval buttons).
7. Prompt-injection adversarial tests once the LLM integration exists.

## Current competitive self-score (honest, updated post-Phase-1)
Problem 8 · Novelty 8 · Razorpay alignment 8 · Agentic behavior 5 (audit downgraded this from 6 — case builder runs a fixed pipeline, not genuine tool selection; see AUDIT_REPORT.md) · Technical depth 7 · ML quality 7 (event-level numbers are strong; static baseline leakage still needs fixing) · Explainability 8 · Security 4 (not yet tested against real LLM) · UX 2 (no frontend yet) · Demo 6 (CLI only, but now correctly aligned end-to-end and backed by real event-level numbers) · Business impact 6 (estimated, not measured against real ops data) · Engineering maturity 9 (honest bug log, reproducible baseline, 14 passing regression tests, found-but-deferred issues explicitly flagged rather than hidden)

**What would make a Razorpay engineer reject this today**: no frontend, reasoning layer isn't actually agentic yet (fixed pipeline, not a planner), static baseline has undisclosed-until-now leakage. All three are the explicit next-session priorities above — not surprises, tracked ones.

