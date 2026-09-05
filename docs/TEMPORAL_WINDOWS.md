# Temporal Windows — Actual Current Behavior

This documents every temporal window in the codebase as it actually behaves,
not as it ideally should. Where windows are intentionally different, that's
noted; where the difference is an unaddressed weakness (not a correctness
bug — no leakage, no crash), that's noted too.

## 1. Detector baseline window (`detection/drift_detector.py`)

- **Window**: trailing 60 days (`BASELINE_WINDOW = 60`), `min_periods=20`, `shift(1)`.
- **Meaning**: day T's z-score uses the mean/std of days `[T-60, T-1]` (at most), and never day T itself. Requires at least 20 valid prior days before it will compute anything (fewer → `NaN` → never flags).
- **Leakage check**: PASS. `shift(1)` guarantees day T's own value is excluded from its own baseline. Verified both by code inspection and by `tests/test_data_handling.py::test_no_future_leakage_in_merchant_specific_baseline` (day-90 flag is identical whether the dataframe is truncated at day 90 or includes days up to 149).

## 2. Static-threshold comparator window (`detection/drift_detector.py::static_threshold_baseline`)

- **Window (before this session's fix)**: none — a single `.quantile(0.98)` computed once over the **entire** dataset (all merchants, all 240 days). This meant a "detection" on day 5 depended on transaction volumes recorded on day 239. **This was temporal leakage**, fixed this session.
- **Window (after fix)**: expanding, day-indexed 98th percentile using only population-wide rows with `day < current_day`. Requires `STATIC_MIN_HISTORY_DAYS = 30` days of accumulated history before the txn_count leg can fire at all; before that, only the fixed-constant refund/dispute legs are active (those were never leaky — they're hardcoded thresholds, not data-derived).
- **Leakage check**: PASS (after fix). Verified with `tests/test_data_handling.py::test_no_future_leakage_in_static_threshold_baseline` (day-90 flags identical with/without a day-140 spike present in the input) and `test_static_threshold_requires_minimum_history_before_txn_count_leg_fires`.
- **Intentional asymmetry**: this window is population-wide (all merchants pooled), not merchant-specific — that's the point of it being the "traditional system" strawman Drift Watch is arguing against, per DECISIONS.md D3.

## 3. Investigator baseline/recent window (`agents/investigators.py::_baseline_window`)

- **Baseline window**: `[flagged_day - recent_span - 60, flagged_day - recent_span)`, i.e. up to 60 days ending 5 days before the flagged day. Falls back to whatever history exists if less than 60 days are available; refuses to compute a comparison at all (`has_baseline=False`) if fewer than `min_baseline_days=15` days are available.
- **Recent window**: `(flagged_day - recent_span, flagged_day]`, i.e. the 5 days ending on and including the flagged day (`recent_span=5`).
- **Leakage check**: PASS. Both windows are bounded above by `flagged_day`; nothing beyond the flagged day is ever read.
- **Intentional difference from the detector's window**: yes — the detector reacts to single-day z-score deviations; the investigators evaluate a 5-day trailing average around the flag to avoid over-reacting to one noisy day. This is a reasonable design choice in isolation.
- **Weakness found this session (not a leakage bug, not fixed — documented per Phase 1 scope)**: because the detector can (and does) fire on day 1 of a multi-day drift episode, the investigators' 5-day "recent" window at that point still contains 3-4 pre-drift days, diluting the average enough to report `supports_risk: false` across all four investigators. Traced concretely on the actual demo merchant (M0021, fraud-drift, `drift_start_day=177`): the detector correctly flags days 178-187 (10 consecutive days, matching the true drift window), but `run_demo_case.py`'s "pick the first flag inside the true drift window" selection logic picks day 178 — the single weakest-evidence day in that whole run — for the flagship demo case. The resulting case shows `confidence_risk: 0.15`, `severity: low`, `"Monitor - no action needed"` for a merchant that is, by ground truth, actively mid-fraud-drift. Picking a later day in the same flagged run (e.g. day 182, `confidence_risk: 0.37` per a spot check) tells a more coherent story. This is a genuine methodological gap between the detector's per-day sensitivity and the investigators' multi-day evidence window — not something to redesign in Phase 1 (see task brief §14), but it should be the top Phase 2/demo-selection priority, since it currently undermines the project's own flagship walkthrough. See PHASE_1_REPORT.md §9 and §10.

## 4. Evaluation windows (`evaluation/evaluate.py`)

- **Day-level**: no window — every `(merchant_id, day)` row with a ground-truth label is scored as an independent example.
- **Event-level**: a "window" is a contiguous run of `true_drift == 1` days per merchant; an event counts as detected if any flag lands anywhere inside `[event_start, event_end]`, and latency is `first_flag_day - event_start` (never negative by construction, since flags before `event_start` don't fall in the window and flags are matched only within it).
- **Leakage check**: PASS for both — no evaluation window ever uses a flag from before the event started to "detect" a later event, and the event-level window is defined purely from ground truth, not from any of the detector's own outputs.

## 5. Synthetic data drift windows (`data/synthetic_generator.py`)

- Each drifting merchant has a single `drift_start_day` (randomized within an archetype-specific range) after which `true_drift`/`true_drift_any` are 1 for every remaining day through day 239 (drift never "ends" once started, for any archetype). This is a modeling choice (drift is treated as a persistent regime change, not a transient event) — worth knowing when reading event-level metrics, since every fraud-drift merchant contributes exactly one, long, single event by construction rather than multiple discrete episodes.

## Summary table

| Window | Bounded by flagged/current day? | Leakage found? | Fixed? |
|---|---|---|---|
| Detector baseline (merchant-specific) | Yes (`shift(1)`) | No | N/A |
| Static-threshold comparator | No (before this session) | **Yes** | **Yes, this session** |
| Investigator baseline/recent | Yes | No | N/A |
| Evaluation (day-level, event-level) | Yes | No | N/A |
