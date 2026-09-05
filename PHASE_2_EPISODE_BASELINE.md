# Phase 2 (Episode Intelligence) Baseline

Recorded by re-running the pipeline from scratch, per the brief's explicit
instruction not to trust previous reports without reproduction. Every
number below was reproduced fresh in this session.

## 1. Test suite
```
$ python3 -m pytest tests/ -q
37 passed in 1.11s
```

## 2. Golden cases (day-level, pre-episode)
```
$ python3 -m pytest tests/test_golden_cases.py -v
test_golden_risk_escalates PASSED
test_golden_legitimate_does_not_escalate PASSED
test_golden_ambiguous_requests_more_evidence PASSED
3 passed in 0.35s
```

## 3. Detector
```
Merchant-specific baseline flagged 81 / 5760 merchant-days
Static threshold flagged 253 / 5760 merchant-days
```

## 4. Single-seed evaluation (original 24-merchant benchmark, seed=42)

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

## 5. Multi-seed evaluation (10 seeds, 42-merchant richer benchmark, 26 events/seed)

| Detector | Metric | Mean | Median | Std | Min | Max |
|---|---|---|---|---|---|---|
| Drift Watch | Event recall | 0.812 | 0.769 | 0.082 | 0.731 | 0.923 |
| Drift Watch | Event precision | 0.564 | 0.560 | 0.047 | 0.483 | 0.635 |
| Drift Watch | Event F1 | 0.663 | 0.660 | 0.043 | 0.604 | 0.724 |
| Drift Watch | Avg latency (days) | 9.15 | 11.50 | 3.93 | 2.74 | 12.57 |
| Drift Watch | False alert rate | 0.005 | 0.005 | 0.001 | 0.005 | 0.007 |
| Static threshold | Event recall | 0.642 | 0.654 | 0.068 | 0.538 | 0.769 |
| Static threshold | Event precision | 0.788 | 0.834 | 0.123 | 0.525 | 0.925 |
| Static threshold | Event F1 | 0.701 | 0.716 | 0.066 | 0.582 | 0.771 |
| Static threshold | Avg latency (days) | 6.97 | 7.07 | 1.14 | 5.41 | 9.20 |
| Static threshold | False alert rate | 0.010 | 0.005 | 0.012 | 0.002 | 0.034 |

Seeds used: 1-10, fixed in `evaluation/multi_seed_eval.py::SEEDS`. Not reduced for this phase, per the brief's explicit instruction.

## 6. Demo
Runs cleanly (`scripts/run_demo_case.py`, exit 0). Both demo cases still
build single-day cases only — this is exactly what episode intelligence
replaces.

## 7. The core known weakness (reproduced with real numbers, not asserted)

`agents/case_builder.py::build_case` scores one flagged day in isolation.
Run against M0021's actual 10-day fraud episode (days 178-187, contiguous,
entirely within the true drift window):

| Day | Decision | Score | Breadth | Persistence |
|---|---|---|---|---|
| 178 | REQUEST_MORE_EVIDENCE | 0.540 | 0.80 | 0.12 |
| 179 | ESCALATE | 0.670 | 0.60 | 0.50 |
| 180 | ESCALATE | 0.747 | 0.60 | 0.83 |
| 181 | ESCALATE | 0.747 | 0.60 | 0.83 |
| 182 | ESCALATE | 0.686 | 0.60 | 0.67 |
| 183 | ESCALATE | 0.709 | 0.60 | 1.00 |
| 184 | ESCALATE | 0.654 | 0.60 | 1.00 |
| **185** | **REQUEST_MORE_EVIDENCE** | 0.597 | 0.40 | 1.00 |
| **186** | **REQUEST_MORE_EVIDENCE** | 0.574 | 0.40 | 1.00 |
| **187** | **REQUEST_MORE_EVIDENCE** | 0.538 | 0.40 | 0.75 |

A single, continuous, real fraud episode oscillates between ESCALATE and
REQUEST_MORE_EVIDENCE with no new contradicting information — purely
because `signal_breadth` (independent deviant groups that specific day)
fluctuates as the fraud archetype's refund/dispute ramp partially
normalizes while volume/category continue drifting. This is the exact
failure mode the brief describes and the episode system in this phase is
built to fix.

## 8. Current architecture (what exists before this phase)

- `detection/drift_detector.py` — per-day, per-merchant z-score detector (unchanged target for this phase).
- `agents/evidence.py`, `agents/investigators.py` — single-day structured evidence (trigger/contextual/historical/contradicting/missing), 5 investigators (one per signal group in `detection/signal_taxonomy.py`).
- `agents/confidence.py` — 5-component Risk Confidence Score + 3-way `decide_action` (ESCALATE/MONITOR/REQUEST_MORE_EVIDENCE). **Reused unchanged in this phase** — episode intelligence changes what evidence is fed into `compute_confidence`, not the formula itself.
- `agents/case_builder.py` — single-day `RiskCase`.
- `evaluation/evaluate.py` — day-level metrics (Phase 1) + `event_level_evaluation_v2`/`event_table` (Phase 2, contiguous ground-truth-run based, no episode grouping of *predictions* yet — predictions are still scored one flagged day at a time against the nearest ground-truth event window).

This is the starting point for the episode-intelligence work documented in
`docs/EPISODE_MODEL.md` onward.
