# Phase 1 — Correctness & Reproducibility

_Session 4 — independent re-audit, Aug 24 2026. This report supersedes the
prior PHASE_1_REPORT.md, which is not preserved verbatim because one of its
claims (confidence formula "fixed") did not match the code. See §3 and §9._

## 1. Executive Summary

The repository arrived having already been through one prior correctness
pass (documented in AUDIT_REPORT.md and the prior PROJECT_STATE.md). That
prior pass's claims were re-verified from scratch rather than trusted. Most
of it held up: data generation is genuinely deterministic, the detector's
reported metrics reproduce exactly, the previously-fixed event/evidence
alignment bug and the `eval()` → `ast.literal_eval` fix are real and now
covered by regression tests, and there is no unsafe code or hardcoded path
anywhere in the live pipeline.

Two things did not hold up under re-verification:

1. A **real, unfixed temporal-leakage bug** in the static-threshold
   comparison baseline (its transaction-count threshold was computed once
   over the entire dataset, including future days) — flagged by the prior
   session but explicitly deferred. Fixed this session.
2. A **false claim** in AUDIT_REPORT.md that the arbitrary confidence
   formula had been "fixed" — it had not been touched.

One new, previously undocumented weakness was also found: the project's own
flagship demo case produces a low-confidence "Monitor only" recommendation
for a merchant that is, by ground truth, genuinely mid-fraud-drift, because
of a mismatch between the detector's per-day sensitivity and the
investigators' 5-day evidence-averaging window. This is not a data bug (the
day and evidence genuinely match, verified per §19 of the task brief) — it's
a methodological gap, documented but deliberately not redesigned, per the
Phase 1 scope rule against redesigning confidence/investigator logic.

## 2. Baseline

See PHASE_1_BASELINE.md for full commands and raw output. Summary:

| Check | Result |
|---|---|
| Data generation determinism | PASS — byte-identical rerun |
| Detector flag count | 81/5760 merchant-days (merchant-specific), matches all prior claims |
| Day-level metrics (as shipped) | Static: P 0.573 / R 0.520 / F1 0.545 / FPR 1.93%. Drift Watch: P 0.519 / R 0.154 / F1 0.237 / FPR 0.71%. All reproduced exactly. |
| Event-level metrics (as shipped) | Static: 3/4 events, 3.67d latency. Drift Watch: 4/4 events, 1.0d latency. Reproduced exactly. |
| Test suite (as shipped) | 14 passed, 0 failed, 81 deprecation warnings |
| Demo script (as shipped) | Runs cleanly, correct day/evidence alignment, but produces a low-confidence result for the fraud demo case (see §9) |

## 3. Bugs Found

### Bug 1 — Temporal leakage in the static-threshold comparator (Medium-High severity)
- **File / function**: `detection/drift_detector.py::static_threshold_baseline`
- **Root cause**: `df["txn_count"].quantile(0.98)` was computed once over the entire input dataframe — every merchant, all 240 days — so a "detection" for day 5 depended on transaction volumes recorded on day 239. This is exactly the failure mode described in the task brief's Temporal Leakage Audit section: "the entire dataset is used to calculate a baseline."
- **Impact**: The static-threshold comparator's day-level and event-level metrics (precision, FPR) were computed under an unrealistic, clairvoyant threshold. It is the comparison strawman Drift Watch is measured against in README.md and PROJECT_STATE.md, so leakage here quietly inflates or deflates the comparison table's fairness. Drift Watch's own detector (`merchant_specific_drift`) was unaffected — it already used `shift(1)` correctly.
- **Note**: This bug was known to the prior session (documented in PROJECT_STATE.md as "found and documented, but did NOT fix... explicitly out of scope for this phase"). Per this session's explicit instructions ("If leakage exists: reproduce it, fix it, add a regression test, rerun all metrics. Do NOT preserve old metrics merely because they were better"), it was fixed rather than deferred again.

### Bug 2 — False claim in AUDIT_REPORT.md (documentation-truth-check finding, not a code bug)
- **File**: `AUDIT_REPORT.md`, §4 bug #1
- **Root cause**: The document states the arbitrary confidence formula `0.15 + 0.22 * n_risk_signals` was "Fixed this session." Direct inspection of `agents/case_builder.py` shows this formula is byte-for-byte unchanged.
- **Impact**: Anyone reading AUDIT_REPORT.md in isolation would believe the confidence model had been calibrated. It has not. PROJECT_STATE.md, by contrast, correctly and consistently lists this as an open item — the inconsistency is isolated to AUDIT_REPORT.md.
- **Fix applied**: Not editing AUDIT_REPORT.md's historical text (it's a dated session log, not living documentation), but PROJECT_STATE.md's "next session priorities" now explicitly calls out that this claim was false so it isn't repeated.

### Non-bug — `datetime.utcnow()` deprecation (code quality, not correctness)
- **File**: `agents/case_builder.py`
- Produced 81 `DeprecationWarning`s per full test run. Not a correctness issue (UTC semantics unchanged), but noisy and trivially fixed. Fixed this session.

### Investigated and confirmed NOT bugs
- **Event/evidence alignment** (task §7): re-traced `scripts/run_demo_case.py`'s selection logic end-to-end. `first_flag_day` and `signal_groups` both come from `chosen.iloc[0]` — the same row. Confirmed with a targeted regression test (`test_event_alignment.py`) using a synthetic frame where the first-overall row and first-true-onset row deliberately carry different signal groups.
- **Detector temporal leakage** (task §8): `shift(1)` on both rolling mean and std confirmed via code inspection and a construction-based regression test (perturbing day 90 only and confirming days <90 are unaffected, and day 90's own flag is stable whether or not future days exist in the input).
- **Unsafe code** (task §9): no `eval`, `exec`, `pickle.loads`, `subprocess`, or `os.system` found in any live code path. The one historical `eval()` usage was already replaced with `ast.literal_eval` by the prior session; verified this parses correctly and raises (not silently corrupts) on malformed/malicious input.
- **Hardcoded paths** (task §10): no occurrences of `/home/claude`, `/mnt/`, or other absolute local paths anywhere in `.py` files. Every entry point derives `REPO_ROOT` from `os.path.dirname(os.path.abspath(__file__))`.

## 4. Fixes Applied

1. `detection/drift_detector.py::static_threshold_baseline` rewritten to compute an expanding, day-indexed, population-wide 98th-percentile threshold for `txn_count`, using only rows with `day < current_day`. Added `STATIC_MIN_HISTORY_DAYS = 30`: before that much history accumulates, the txn_count leg cannot fire (the refund/dispute legs, being fixed constants rather than data-derived, are unaffected and always active).
2. `agents/case_builder.py`: `datetime.datetime.utcnow()` → `datetime.datetime.now(datetime.timezone.utc)`.
3. `PROJECT_STATE.md`, `README.md`: updated to the corrected metrics and to explicitly flag the AUDIT_REPORT.md documentation error so it isn't repeated as fact.
4. New `docs/TEMPORAL_WINDOWS.md`: maps every temporal window in the system (detector baseline, static comparator, investigator baseline/recent, evaluation day/event windows, synthetic-data drift windows) with an explicit leakage-check verdict for each.
5. New `PHASE_1_AUDIT.md`, `PHASE_1_BASELINE.md`: fresh initial-inventory and pre-fix baseline documents per task §5/§6, independent of the prior session's versions.

## 5. Tests Added (14 → 19)

1. `tests/test_data_handling.py::test_no_future_leakage_in_static_threshold_baseline` — constructs a 3-merchant, 150-day dataset, injects a huge spike on day 140 for one merchant, and confirms day-90 flags are identical whether the dataframe is truncated at day 90 or includes the day-140 spike. Regression test for Bug 1.
2. `tests/test_data_handling.py::test_static_threshold_requires_minimum_history_before_txn_count_leg_fires` — confirms an absurdly high `txn_count` value does not trigger a flag before `STATIC_MIN_HISTORY_DAYS` of population history exists.
3. `tests/test_event_alignment.py::test_malformed_serialized_signal_data_fails_loudly_not_silently` — confirms `ast.literal_eval` raises `ValueError`/`SyntaxError` (rather than silently returning something usable) on malformed strings and on a code-injection-style payload (task §13, edge case 11).
4. `tests/test_event_alignment.py::test_malformed_serialized_signal_data_valid_literal_parses_correctly` — happy-path check that a well-formed list-literal string parses back correctly.
5. `tests/test_detector.py::test_missing_values_do_not_crash_or_silently_flag` — injects `NaN` into `refund_rate` for a run of days and confirms the detector neither crashes nor silently flags those days, and `predicted_drift_ms` is never itself `NaN` (task §13, edge case 5).

## 6. Test Results

```
$ python3 -m pytest tests/ -q
...................
19 passed in 1.11s
```
No warnings (the `datetime.utcnow()` deprecation warning present in the baseline run is gone).

## 7. Temporal Integrity

Full detail in `docs/TEMPORAL_WINDOWS.md`. Every window in the system was traced and checked for leakage:

| Window | Leakage found? | Status |
|---|---|---|
| Detector baseline (merchant-specific, `shift(1)`) | No | Confirmed clean |
| Static-threshold comparator | **Yes** | **Fixed this session** |
| Investigator baseline/recent windows | No | Confirmed clean (but see §9 for a non-leakage weakness) |
| Evaluation windows (day-level, event-level) | No | Confirmed clean |

## 8. End-to-End Verification

| Stage | Result |
|---|---|
| Data generation | PASS |
| Detector | PASS |
| Evaluation | PASS |
| Demo | PASS (runs cleanly; see §9 for a non-blocking methodological weakness in the output it produces) |
| Event/evidence alignment | PASS |
| Temporal integrity | PASS (after Bug 1 fix) |

## 9. Remaining Weaknesses — brutally honest

1. **Investigator evidence windows can undercut a correct detector flag.** Traced concretely on the actual demo merchant, M0021 (fraud-drift, `drift_start_day=177`): the detector correctly flags all of days 178-187 (10 consecutive days, exactly matching the true drift window). `scripts/run_demo_case.py`'s "prefer the first flag inside the true drift window" logic picks day 178 — the very first, and weakest-evidence, day in that run. At that point the investigators' 5-day trailing "recent" window (days 174-178) still contains 3-4 pre-drift days, diluting the average enough that all 4 investigators report `supports_risk: false`. The resulting case: `confidence_risk: 0.15`, `severity: low`, `"Monitor - no action needed"` — for a merchant that ground truth confirms is actively fraud-drifting. Spot-checking a later day in the same run (day 182) gives `confidence_risk: 0.37` — still "low" severity, but a materially different, more coherent story. This is not data corruption (the day and evidence genuinely correspond to each other, verified per §19), it's a real design gap between the detector's per-day sensitivity and the investigators' multi-day averaging. **Not fixed** — redesigning investigator windows or the demo's day-selection heuristic is Phase 2/3 territory per the task brief's explicit "do not redesign confidence yet" instruction, but it is now the single highest-priority item for whoever picks up Phase 2, because it currently undermines the project's own walkthrough.
2. **Confidence formula remains uncalibrated.** `confidence_risk = min(0.95, 0.15 + 0.22 * n_risk_signals)` is a heuristic with no statistical grounding. This was true on arrival, is still true now, and was incorrectly reported as fixed in AUDIT_REPORT.md (see Bug 2). Not fixed this session, by design — this is explicitly Phase 2 scope.
3. **Case builder is not genuinely agentic.** All 4 investigators run unconditionally on every flag, regardless of which signal group actually triggered it. A refund-only trigger still runs the Geography Investigator. This was already correctly flagged by the prior session and remains unresolved.
4. **Day-level recall (15.4%) is genuinely weak**, even though event-level recall (100%) tells a much better story. Both are reported side by side, not cherry-picked — but a reviewer focused only on day-level numbers would see a real weakness.
5. **Single random seed.** All results come from one seeded synthetic dataset instance (`np.random.default_rng(42)`). No cross-seed validation exists; a skeptical reviewer could reasonably ask whether the numbers are seed-dependent.
6. **No frontend, backend, persistence, or real LLM integration** — by design for this phase, but still genuinely absent, not simulated or mocked to look otherwise.
7. **No adversarial security testing** — meaningless until a real LLM call exists in the case builder; SECURITY.md correctly says so and doesn't overclaim.

## 10. Phase 2 Recommendation

Do **not** start Phase 2. If asked to recommend the single next highest-value engineering phase: reconcile the investigator evidence windows with the detector's per-day sensitivity (item 1 in §9), because it directly affects whether the flagship demo case tells a coherent story — a Razorpay reviewer clicking through the one worked example the project ships would currently see "Monitor only" recommended for a merchant the system itself has correctly identified as actively fraud-drifting. Everything else in §9 is real but lower-urgency than that specific credibility gap.
