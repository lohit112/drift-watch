# Multi-Seed Evaluation — Task Brief Step 8

10 independent seeds (1-10, fixed and documented — `evaluation/multi_seed_eval.py::SEEDS`), each generating an independent 42-merchant richer population (13 additional legitimate/suspicious/ambiguous regimes beyond the original 6 archetypes — see `data/synthetic_generator.py::build_richer_population`). No seed is cherry-picked or excluded. Full per-seed numbers: `evaluation/multi_seed_raw.csv`.

## Per-seed results

| Seed | Detector | Events | Detected | Recall | Precision | F1 | Avg latency | FPR (non-event days) |
|---|---|---|---|---|---|---|---|---|
| 1 | Drift Watch | 26 | 24 | 0.923 | 0.588 | 0.719 | 12.21d | 0.0057 |
| 1 | Static | 26 | 17 | 0.654 | 0.525 | 0.582 | 7.06d | 0.0316 |
| 2 | Drift Watch | 26 | 20 | 0.769 | 0.635 | 0.696 | 12.40d | 0.0046 |
| 2 | Static | 26 | 16 | 0.615 | 0.812 | 0.700 | 7.12d | 0.0058 |
| 3 | Drift Watch | 26 | 19 | 0.731 | 0.537 | 0.619 | 5.00d | 0.0055 |
| 3 | Static | 26 | 17 | 0.654 | 0.852 | 0.740 | 7.88d | 0.0049 |
| 4 | Drift Watch | 26 | 20 | 0.769 | 0.618 | 0.685 | 11.00d | 0.0053 |
| 4 | Static | 26 | 18 | 0.692 | 0.870 | 0.771 | 5.83d | 0.0026 |
| 5 | Drift Watch | 26 | 23 | 0.885 | 0.483 | 0.625 | 6.43d | 0.0066 |
| 5 | Static | 26 | 14 | 0.538 | 0.835 | 0.655 | 5.93d | 0.0036 |
| 6 | Drift Watch | 26 | 20 | 0.769 | 0.543 | 0.636 | 12.40d | 0.0066 |
| 6 | Static | 26 | 17 | 0.654 | 0.833 | 0.733 | 6.35d | 0.0050 |
| 7 | Drift Watch | 26 | 24 | 0.923 | 0.596 | 0.724 | 4.71d | 0.0054 |
| 7 | Static | 26 | 14 | 0.538 | 0.839 | 0.656 | 7.07d | 0.0025 |
| 8 | Drift Watch | 26 | 19 | 0.731 | 0.569 | 0.640 | 12.00d | 0.0048 |
| 8 | Static | 26 | 17 | 0.654 | 0.925 | 0.766 | 7.82d | 0.0017 |
| 9 | Drift Watch | 26 | 19 | 0.731 | 0.514 | 0.604 | 2.74d | 0.0047 |
| 9 | Static | 26 | 20 | 0.769 | 0.772 | 0.771 | 9.20d | 0.0088 |
| 10 | Drift Watch | 26 | 23 | 0.885 | 0.552 | 0.680 | 12.57d | 0.0054 |
| 10 | Static | 26 | 17 | 0.654 | 0.615 | 0.634 | 5.41d | 0.0343 |

## Summary statistics (10 seeds)

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

## A real, non-cherry-picked finding: the story flips on the harder benchmark

On the **original single-seed benchmark** (4 sudden, strong, coordinated fraud-drift events — see README.md/PHASE_1_REPORT.md), Drift Watch clearly beats the static comparator on every axis: higher event recall (1.0 vs 0.75), much lower latency (1.0d vs 3.67d), lower false-alert rate.

On this **richer, harder benchmark** (13 additional regimes including slow-onset, single-signal, and genuinely ambiguous/contradictory drift), the picture is more mixed and, in places, reversed:

- Drift Watch has **higher event recall** (0.812 vs 0.642 mean) — it catches more of the harder, subtler events the static comparator misses entirely.
- But Drift Watch has **lower event precision** (0.564 vs 0.788 mean) and, on this benchmark, a **slightly lower F1** (0.663 vs 0.701 mean) — its 2-independent-signal-group rule alerts on more legitimate-archetype episodes (marketing campaigns, seasonal-with-a-twist, geo/category expansion) than the static comparator does here.
- Drift Watch's **average detection latency is higher** on this benchmark (9.15d vs 6.97d mean) — several of the new regimes are intentionally slow-onset (`slow_fraud` ramps over 30 days; `missing_evidence_case` starts before a usable baseline exists) or single-signal (`refund_abuse`, `dispute_escalation`), which the 2-independent-signal-group rule takes longer to accumulate evidence for than a fast single-threshold rule does.
- Drift Watch's false-alert rate remains lower and far more STABLE (std 0.001 vs 0.012) than the static comparator's, which spikes badly on 2 of the 10 seeds (0.0316, 0.0343) — more than 6x its own median. Drift Watch shows no such seed-dependent blowups.

**This was investigated, not just reported** (per task brief step 8's "if Drift Watch performs inconsistently: investigate"): the F1/latency reversal traces directly to the new regimes' design — several of the 13 additional archetypes were built specifically to be hard (slow ramps, single-signal-only, contradictory direction) as legitimate/ambiguous test cases, and the static comparator's population-wide percentile threshold happens to be a cruder but occasionally faster tripwire for some of them (e.g. `refund_abuse` and `dispute_escalation`, which cross its fixed refund/dispute thresholds directly, with no independent-signal-group requirement to satisfy). This is not a bug in either detector — it's a genuine, previously-untested tradeoff that the original single-seed, all-strong-fraud benchmark could not reveal. See PHASE_2_REPORT.md "Remaining Weaknesses" for what this implies.

## What was NOT hidden

- No seed was excluded or re-run to get a better number.
- The reversal in F1/precision relative to the original benchmark's headline claim is reported here in full, not folded quietly into an average that would obscure it.
- Static threshold's false-alert-rate instability (2 seeds >6x its own median) is reported, not smoothed over just because it happens to favor the comparator being measured against.
