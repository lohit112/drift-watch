# Phase 1 Baseline — State Before This Session's Fixes

This records the repository's behavior exactly as delivered in the ZIP,
reproduced from a clean checkout before any code in this session was
modified. (The repository had already been through one prior correctness
pass — see AUDIT_REPORT.md/PHASE_1_REPORT.md from that session — so this is
the baseline for *this* session's work, not the project's original state.)

## Environment

```
Python 3.12.3
pip install --break-system-packages pandas numpy scikit-learn
```

## 1. Data generation

Command:
```
python3 data/synthetic_generator.py
```
Output:
```
Generated 5760 rows for 24 merchants -> .../data/synthetic_merchant_events.csv
archetype
fraud_drift       4
geo_expansion     3
growing           3
normal            8
product_launch    3
seasonal          3
```
Reran and diffed against the CSV shipped in the ZIP: **byte-identical**. Generation is genuinely deterministic (seeded `np.random.default_rng(42)`).

## 2. Detector

Command:
```
python3 detection/drift_detector.py
```
Output:
```
Merchant-specific baseline flagged 81 / 5760 merchant-days
Static threshold flagged 248 / 5760 merchant-days
```
(81/5760 for the merchant-specific detector matches PROJECT_STATE.md's claim exactly. The static-threshold count of 248 is **before** this session's leakage fix — see PHASE_1_REPORT.md; after the fix it becomes 253, a small but real change.)

## 3. Evaluation

Command:
```
python3 evaluation/evaluate.py
```
Output (before this session's fix):
```
=== Detection performance (day-level, as originally defined) ===
                                detector  precision  recall    f1  false_positive_rate  true_positives  false_positives  false_negatives
                 Static global threshold      0.573   0.520 0.545               0.0193             142              106              131
Drift Watch (merchant-specific baseline)      0.519   0.154 0.237               0.0071              42               39              231

=== Detection latency (fraud-drift merchants only, day-level onset) ===
Static: {'merchants_with_fraud_drift': 4, 'merchants_missed_entirely': 1, 'avg_detection_latency_days': 3.67, 'max_detection_latency_days': 4}
Drift Watch: {'merchants_with_fraud_drift': 4, 'merchants_missed_entirely': 0, 'avg_detection_latency_days': 1.0, 'max_detection_latency_days': 1}

=== Event-level evaluation ===
Static global threshold: {'events_total': 4, 'events_detected': 3, 'event_recall': 0.75, 'avg_event_detection_latency_days': 3.67, 'false_alert_rate_nonevent_days': 0.0193}
Drift Watch (merchant-specific baseline): {'events_total': 4, 'events_detected': 4, 'event_recall': 1.0, 'avg_event_detection_latency_days': 1.0, 'false_alert_rate_nonevent_days': 0.0071}
```
This matches README.md and PROJECT_STATE.md's reported numbers exactly — **confirmed, not fabricated**.

## 4. Test suite

Command:
```
python3 -m pytest tests/ -v
```
Output: **14 passed**, 81 `DeprecationWarning`s (all from `datetime.datetime.utcnow()` in `case_builder.py`). No failures, no errors.

## 5. Demo script

Command:
```
python3 scripts/run_demo_case.py
```
Output: two full case JSONs, no errors. Manually traced (per task §19): `merchant_id`, `flagged_day`, and `deviant_signal_groups` all refer to the same row for both demo merchants — the event/evidence alignment bugfix from the prior session holds. **However**, tracing further into the investigator findings for Demo Case 1 (M0021, fraud-drift, flagged on day 178 — the first day of its drift episode) revealed that all 4 investigators report `supports_risk: false`, producing `confidence_risk: 0.15`, `severity: low`, `"Monitor - no action needed"` — for a merchant the ground truth confirms is actively drifting into fraud. This is not a data-alignment bug (the day and evidence genuinely match) — it's a real, previously undocumented methodological weakness in how investigator evidence windows relate to the detector's per-day flag. See PHASE_1_REPORT.md §9 for the full trace and root cause.

## 6. Unsafe code scan

```
grep -rn "eval(\|exec(\|pickle.loads(\|subprocess\|os.system" --include="*.py" .
```
No occurrences outside a comment and a docstring referencing the already-fixed `eval()` bug and `subprocess` by name (in a test docstring explaining the test does *not* use subprocess). No live unsafe code found.

## 7. Path/environment scan

```
grep -rn "/home/claude\|/mnt/\|/Users/" --include="*.py" .
```
No hardcoded paths found. All entry points use `os.path.dirname(os.path.abspath(__file__))` to derive `REPO_ROOT`. Confirmed runnable from any checkout location.

## Summary

The repository's own reported baseline numbers were independently reproduced exactly, with one exception: the static-threshold comparator's numbers were quietly leakage-affected the whole time (documented as a known-but-deferred issue in PROJECT_STATE.md, not hidden — just not yet fixed). This session fixes that specific issue; see PHASE_1_REPORT.md for the honest before/after.
