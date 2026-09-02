# Phase 1 Audit — Initial Inventory

_This document records what was actually found in the repository before any
new changes were made in this session. The repository arrived having
already been through one prior "Phase 1 correctness pass" (see the
pre-existing AUDIT_REPORT.md, PHASE_1_BASELINE.md, PHASE_1_REPORT.md,
PROJECT_STATE.md). Per instructions, none of those documents' claims were
trusted — every one was independently re-verified by reading the code and
re-running the pipeline from a clean state. Findings from that
re-verification (including one real bug the prior pass explicitly deferred,
and one stale/false claim in AUDIT_REPORT.md) are in PHASE_1_REPORT.md._

## Repository structure

```
drift-watch/
├── data/synthetic_generator.py        merchant event generator (deterministic, seed=42)
├── data/synthetic_merchant_events.csv generated output (regenerated this session, byte-identical)
├── detection/drift_detector.py        merchant-specific z-score detector + static-threshold comparator
├── detection/scored_events.csv        detector output (regenerated this session)
├── agents/investigators.py            4 evidence-gathering functions (Transaction/Dispute/Geography/Profile)
├── agents/case_builder.py             correlation, hypotheses, confidence, audit log
├── evaluation/evaluate.py             day-level + event-level precision/recall/F1/FPR/latency
├── evaluation/results.csv, event_level_results.csv   evaluation output (regenerated this session)
├── scripts/run_demo_case.py           end-to-end CLI demo (fraud + seasonal merchant)
├── tests/                             14 tests on arrival, 19 after this session
├── research/, docs/                   positioning/spec docs, not executable
├── frontend/, backend/                empty (.gitkeep only) — correctly not claimed as built
├── README.md, PROJECT_STATE.md, DECISIONS.md, SECURITY.md, AUDIT_REPORT.md,
│   PHASE_1_BASELINE.md, PHASE_1_REPORT.md   prior-session docs, truth-checked this session
└── requirements.txt                   pandas, numpy, scikit-learn
```

## Main entry points

Each is a standalone script, runnable independently, in this order:
1. `python3 data/synthetic_generator.py` → writes `data/synthetic_merchant_events.csv`
2. `python3 detection/drift_detector.py` → reads the CSV above, writes `detection/scored_events.csv`
3. `python3 evaluation/evaluate.py` → reads `scored_events.csv`, writes `evaluation/results.csv` and `evaluation/event_level_results.csv`
4. `python3 scripts/run_demo_case.py` → reads the raw CSV, re-scores in-process, prints two full case JSONs to stdout

No `main.py`, no package entry point, no server. This matches the README's stated scope exactly (no frontend/backend/persistence claimed).

## Data flow (confirmed against actual code, not assumed)

```
synthetic_generator.py (RNG seed=42)
      |  data/synthetic_merchant_events.csv (5760 rows, 24 merchants, 240 days each)
      v
drift_detector.merchant_specific_drift()   -- per-merchant, rolling 60-day mean/std, shift(1), z >= 2.5, >=2 independent signal domains
drift_detector.static_threshold_baseline() -- fixed refund/dispute thresholds + txn_count percentile (comparison strawman only)
      |  detection/scored_events.csv
      v
scripts/run_demo_case.py selects one flagged day per demo merchant
      |  (day, deviant_signal_groups) — same row, see event-alignment bugfix already applied
      v
agents.investigators.run_all_investigators(history, flagged_day)  -- 4 functions, each does its own baseline/recent windowing
      |  list[Finding]
      v
agents.case_builder.build_case()  -- rule-based correlation -> hypothesis A/B, confidence, severity, audit log
      |  RiskCase (printed as JSON)
      v
evaluation.evaluate.py  -- separately scores detection/scored_events.csv against ground truth, day-level and event-level
```

This matches the architecture diagram in README.md. No divergence found.

## Detector implementation

`detection/drift_detector.py::merchant_specific_drift` — per merchant, per feature: rolling mean/std over a trailing 60-day window (`min_periods=20`), **shifted by 1 day** before comparison, so day T's z-score never uses day T's own value. Features are grouped into 5 independent `SIGNAL_GROUPS` (volume, refund, dispute, category_mix, geo_mix) specifically so that `txn_count`/`txn_volume` — which are algebraically related — count as one signal, not two. A day is flagged when `n_deviant_signals >= 2`. Confirmed correct and leak-free (see Temporal Leakage Audit below).

`static_threshold_baseline` — the "traditional system" comparison strawman. **Contained a real temporal-leakage bug on arrival** (global `.quantile(0.98)` over the entire dataset). Fixed this session — see PHASE_1_REPORT.md.

## Investigation implementation

`agents/investigators.py` — 4 pure functions, each computing a baseline window (up to 60 days, ending `recent_span=5` days before the flagged day) vs. a "recent" window (the `recent_span` days up to and including the flagged day). Falls back to an explicit "insufficient baseline history" finding when fewer than 15 baseline days exist, rather than fabricating a comparison. No leakage found (windows are always `<= flagged_day`). **A real methodological weakness was found**: the 5-day "recent" window can dilute a genuine single-day onset spike when the detector fires on day 1 of a drift episode — see PHASE_1_REPORT.md §9.

## Case generation

`agents/case_builder.py::build_case` — deterministic rule-based correlation, not an LLM call (explicitly documented as a seam, not yet wired — matches README/PROJECT_STATE claims). Confidence is `min(0.95, 0.15 + 0.22 * n_risk_signals)`, an undisguised, undocumented-as-calibrated heuristic. This matches what PROJECT_STATE.md says ("not statistically calibrated") — but contradicts AUDIT_REPORT.md, which claims this was "fixed this session." It was not; the formula in the code is unchanged. See PHASE_1_REPORT.md documentation-truth-check findings.

## Evaluation methodology

`evaluation/evaluate.py` provides both day-level metrics (precision/recall/F1/FPR via scikit-learn, treating every drifted day as an independent example) and event-level metrics (added in the prior session: contiguous `true_drift==1` runs per merchant count as one event, detected if any day in the window is flagged). Both are legitimate, clearly labeled, and neither overwrites the other. Ground truth (`true_drift`) is fraud-drift only; seasonal/launch/geo-expansion drift is intentionally unlabeled as "should flag" (it's the Hypothesis-B legitimate-explanation test case, not a missed detection).

## Demo pipeline

`scripts/run_demo_case.py` — picks a fraud-drift merchant that gets flagged during its true drift window, and a seasonal merchant expected to resolve to Hypothesis B. Uses `ast.literal_eval` (not `eval`) to parse the CSV-round-tripped list-literal string. Selects `day` and `deviant_signal_groups` from the same row (`chosen`), consistent with the fix already applied in the prior session and re-verified here with a passing regression test.

## Existing tests (on arrival)

`tests/test_detector.py` (6), `tests/test_data_handling.py` (1), `tests/test_case_builder.py` (5), `tests/test_event_alignment.py` (2) — 14 total, all passing on arrival, all still passing after this session's changes. Coverage coincides closely with the audit categories in the task brief (zero-variance, insufficient history, multi-merchant isolation, signal-group independence, event/evidence alignment, one temporal-leakage test for the merchant-specific detector). Gaps found and closed this session: no leakage test for the static-threshold baseline (the one that actually had a bug), no malformed/malicious-payload test for the `ast.literal_eval` parse, no missing-value (NaN) test, no deprecation-free timestamp. See PHASE_1_REPORT.md §5.

## Existing documentation

README.md, PROJECT_STATE.md, DECISIONS.md, SECURITY.md are accurate and consistent with the code, with one exception found: AUDIT_REPORT.md §4 bug #1 claims the confidence formula "Fixed this session" — false, the code is unchanged. Flagged and corrected in PHASE_1_REPORT.md.

## Dependencies

`requirements.txt`: `pandas>=2.0`, `numpy>=1.24`, `scikit-learn>=1.3`. No unpinned/unnecessary packages. `pytest` is used for the test suite but is not in requirements.txt — added as a dev dependency note in PHASE_1_REPORT.md rather than requirements.txt itself, since it's not needed to run the product pipeline.

## Known technical debt (unchanged from prior session's honest self-assessment, re-verified accurate)

- Case builder always runs all 4 investigators regardless of trigger signal — not genuinely agentic tool selection yet.
- Confidence formula is an undocumented-as-calibrated heuristic.
- No LLM integration anywhere (by design, for this phase).
- No frontend/backend/persistence (by design, for this phase).
- Day-level recall (15.4%) is low; event-level recall (100%) is the more operationally meaningful number but day-level is kept alongside, not hidden.
- **New this session**: investigator evidence windows can under-support a detector flag that fires on day 1 of a drift episode (see PHASE_1_REPORT.md §9) — a real, previously undocumented weakness.
