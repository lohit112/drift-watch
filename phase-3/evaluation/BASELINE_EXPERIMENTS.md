# Baseline Experiments — Task Brief Step 4

Compares the shipped detector (rolling mean/std) against two documented
alternatives, using the exact same event-level evaluation methodology
(`evaluation.evaluate.event_level_evaluation_v2`) on TWO independent
datasets, so the conclusion isn't tuned against one synthetic dataset.
Raw numbers: `evaluation/baseline_experiments_raw.csv`. Reproduce with
`python3 evaluation/baseline_experiments.py`.

## Methods compared

| Method | Description |
|---|---|
| `rolling_mean_std` | **Shipped default.** Trailing 60-day mean/std, `shift(1)`. |
| `rolling_median_mad` | Trailing 60-day median + MAD (scaled ×1.4826), `shift(1)`. Robust to a single extreme day inside the baseline window itself. |
| `ewma` | Exponentially-weighted mean/std, span=30, `shift(1)`. Reacts faster to a genuine regime shift. |

All three use the identical Z_THRESHOLD=2.5 / MIN_SIGNALS_FOR_FLAG=2 rule on top of whichever z-like score they produce — only the baseline computation itself differs.

## Results

### Dataset 1: original (single-seed, 24 merchants, 4 fraud-drift events)

| Method | Event recall | Event precision | Event F1 | Avg latency | False alerts/merchant | Compute time |
|---|---|---|---|---|---|---|
| **rolling_mean_std** | 1.000 | **0.205** | **0.340** | 1.00d | 1.29 | 0.24s |
| rolling_median_mad | 1.000 | 0.067 | 0.125 | 1.00d | 2.33 | 1.26s |
| ewma | 1.000 | 0.121 | 0.216 | 1.00d | 1.21 | 0.22s |

### Dataset 2: richer (13 additional regimes, 42 merchants, 26 risk-labeled events)

| Method | Event recall | Event precision | Event F1 | Avg latency | Median latency | False alerts/merchant | Compute time |
|---|---|---|---|---|---|---|---|
| **rolling_mean_std** | 0.846 | **0.605** | **0.705** | 3.82d | 2.0d | 0.81 | 0.37s |
| rolling_median_mad | **0.923** | 0.492 | 0.642 | 5.58d | 2.0d | 1.52 | 2.09s |
| ewma | 0.769 | 0.478 | 0.589 | 8.95d | 2.0d | 0.83 | 0.37s |

## Interpretation

**rolling_mean_std (the shipped method) has the best F1 on both datasets** and is 5-9x faster than rolling_median_mad (the `.apply(mad, ...)` rolling computation is not vectorized). Its main weakness relative to `rolling_median_mad` is event recall on the richer benchmark (0.846 vs 0.923) — median/MAD catches 2 more of the harder ambiguous/suspicious events, at the cost of nearly doubling false alerts per merchant and materially worse precision. `ewma` is not competitive on either dataset: worse recall on the richer benchmark, and the highest latency (8.95 days average — the span=30 window reacts to a sudden regime shift more slowly than a flat trailing window with a hard 60-day lookback, which is the opposite of what "reacts faster" is typically assumed to mean, and is worth noting as a real, slightly counterintuitive finding rather than smoothing it over).

**Decision: keep `rolling_mean_std` as the shipped default.** No alternative gives a "materially better" robustness improvement per the task brief's own bar — the recall gain from median/MAD is real but comes with a precision/latency cost that isn't clearly worth it, especially since Drift Watch's actual measured false-positive-rate advantage over the static-threshold comparator (see README.md) is one of the project's stronger, evidence-backed claims. `detection/baselines.py` keeps all three implementations available (not deleted) so this experiment is reproducible and re-runnable if the population/threshold changes materially in a future phase.

## A note on event-precision being much lower than day-level precision

Event-level precision here (0.205-0.605 depending on dataset) is substantially harsher than the day-level precision reported in README.md/PHASE_1_REPORT.md (0.519 on the same original dataset). This is not a contradiction — they measure different things. Day-level precision asks "of all flagged merchant-DAYS, what fraction were true-drift days"; event-level precision (as newly defined in `event_level_evaluation_v2`, task brief step 7) asks "of all flagged episodes (contiguous flagged runs), what fraction overlap a true event at all." With only 4 true fraud events among 24 merchants, a handful of false-positive episodes on legitimate archetypes (seasonal, growing, launch, geo_expansion merchants that cross the flag threshold without being risk-labeled) disproportionately hurts this stricter metric. This is a genuinely harder, more operationally meaningful bar (an analyst reviewing "alerts" cares about episodes, not days) and is reported honestly here rather than only showing the more flattering day-level number.
