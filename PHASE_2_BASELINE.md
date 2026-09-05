# Phase 2 Baseline — State Before Any Phase 2 Changes

Recorded immediately after confirming Phase 1's deliverables still hold,
before touching any code in this phase.

## 1. Test suite
```
$ python3 -m pytest tests/ -q
19 passed in 1.04s
```

## 2. Detector
```
$ python3 detection/drift_detector.py
Merchant-specific baseline flagged 81 / 5760 merchant-days
Static threshold flagged 253 / 5760 merchant-days
```

## 3. Evaluation (single seed, seed=42)
Day-level:
| Detector | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| Static global threshold | 0.561 | 0.520 | 0.540 | 2.02% |
| Drift Watch (merchant-specific) | 0.519 | 0.154 | 0.237 | 0.71% |

Event-level:
| Detector | Event recall | Avg latency | False alert rate |
|---|---|---|---|
| Static global threshold | 0.75 (3/4) | 3.67d | 2.02% |
| Drift Watch (merchant-specific) | 1.0 (4/4) | 1.0d | 0.71% |

## 4. Demo behavior
Demo Case 1 (M0021, fraud-drift, flagged day 178 — the first day of a 10-day
flagged run coinciding with the true drift window): `confidence_risk: 0.15`,
`severity: low`, `"Monitor - no action needed"`. All 4 investigators report
`supports_risk: false` because their 5-day trailing "recent" window (days
174-178) is diluted by 3-4 pre-drift days.

Demo Case 2 (M0009, seasonal, flagged day 41): `confidence_risk: 0.37`,
`severity: low`.

## 5. Known weaknesses carried in from Phase 1 (PHASE_1_REPORT.md §9)
1. Investigator evidence windows can undercut a correct detector flag — this
   is the #1 Phase 2 target per the Phase 1 recommendation.
2. Confidence formula (`0.15 + 0.22 * n_risk_signals`) is an uncalibrated,
   undocumented heuristic.
3. Case builder always runs all 4 investigators regardless of trigger.
4. Day-level recall (15.4%) is weak (event-level recall is the stronger,
   more honest number).
5. Single random seed (42) — no cross-seed validation exists.
6. Only 4 fraud-drift merchants and 3 of each other archetype in the
   benchmark — thin coverage of ambiguous/mixed scenarios.
7. Signal grouping exists (`SIGNAL_GROUPS`) but there's no explicit written
   taxonomy document, and correlation between refund/dispute (both can rise
   together under real fraud) isn't examined, only volume/count.
8. Evidence is unstructured free text (`Finding.summary`, `Finding.detail`
   dict with ad hoc keys) — no consistent schema across investigators.

This is the state Phase 2 starts from. All comparisons in
PHASE_2_REPORT.md are against these exact numbers.
