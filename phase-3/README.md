# Drift Watch

**Autonomous merchant risk-drift detection & investigation agent — a buildathon prototype inspired by publicly documented Razorpay engineering/product challenges. Not affiliated with, endorsed by, or built using any non-public Razorpay data or systems.**

## Problem

Merchant risk review at payment platforms happens almost entirely at onboarding. Razorpay's own engineering blog describes their internal onboarding-risk system (Bumblebee) handling 10,000-12,000 manual-equivalent reviews a month — but once a merchant is approved, there's no publicly documented system that continuously re-evaluates behavior afterward. Risk is not static: a legitimate merchant can be compromised, pivot into riskier activity, or begin laundering through a previously clean account, and none of that surfaces until damage has already accumulated.

## Solution

Drift Watch continuously monitors already-approved merchants against **their own historical baseline** (not a single global threshold), detects correlated behavioral drift across transaction, dispute, geography, and category signals, investigates using specialized evidence-gathering agents, and builds a reviewable case — complete with a risk hypothesis, a competing legitimate-explanation hypothesis, confidence, and a recommended (never autonomous) action.

## Why AI / why agentic

Simple threshold rules can't account for the fact that every merchant's "normal" is different, and a bare anomaly score can't distinguish a Diwali sale from account compromise. The system needs to reason across multiple correlated signals, weigh competing explanations, and produce an auditable case a human can act on in seconds — that's an investigation, not a classification.

## Status

This is a **working core loop**, not yet a full product. See `PROJECT_STATE.md` for exactly what's built, what's tested, real evaluation numbers (not fabricated), and known open issues. Honesty about the current state is intentional — see `DECISIONS.md` for why.

What works right now, end to end, runnable from a clean checkout:
- Synthetic merchant event generation across 6 archetypes with ground-truth labels
- Merchant-specific statistical drift detection (rolling baseline + z-scores + independent signal-domain correlation)
- 4 specialized investigator agents (transaction, dispute, geography, merchant profile)
- Evidence correlation + case building with competing hypotheses, confidence, and audit log
- An evaluation harness with real precision/recall/F1/false-positive-rate/detection-latency numbers, compared against a static-threshold baseline

What's not built yet: frontend, FastAPI backend/persistence, real LLM integration (currently a documented rule-based stand-in — see `agents/case_builder.py`), and adversarial security testing against that LLM integration.

## Architecture

```
Merchant events (synthetic, labeled)
        |
Sentinel — merchant-specific rolling baseline, z-scores, independent
           signal-domain correlation (detection/drift_detector.py)
        |
Investigators — Transaction / Dispute / Geography / Merchant Profile
                 (agents/investigators.py)
        |
Evidence Correlator + Case Builder — hypotheses, confidence, audit log
        (agents/case_builder.py)
        |
Human approval gate (no autonomous account action, ever)
```

## Running it

```bash
pip install --break-system-packages pandas numpy scikit-learn
python3 data/synthetic_generator.py     # generates data/synthetic_merchant_events.csv
python3 detection/drift_detector.py     # scores it, writes detection/scored_events.csv
python3 evaluation/evaluate.py          # real precision/recall/F1/FPR numbers
python3 scripts/run_demo_case.py        # full end-to-end case, printed as JSON
```

## Evaluation (synthetic data, real numbers)

| Detector | Precision | Recall | F1 | False positive rate | Fraud-drift merchants missed | Avg detection latency |
|---|---|---|---|---|---|---|
| Static global threshold | 0.561 | 0.520 | 0.540 | 2.02% | 1 of 4 | 3.67 days |
| Drift Watch (merchant-specific) | 0.519 | 0.154 | 0.237 | 0.71% | 0 of 4 | 1.0 days |

Event-level (the number to lead with — see PROJECT_STATE.md for why): Drift Watch catches 4/4 fraud-drift episodes (100% event recall) at 1.0 day average latency, vs. 3/4 (75%) at 3.67 days for the static comparator.

Honest tradeoff: Drift Watch generates far fewer false alarms and catches every fraud-drift merchant faster, at the cost of day-level recall, which is the top priority for the next iteration (see PROJECT_STATE.md).

Note on the static comparator's numbers: a Phase 1 audit found and fixed a real temporal-leakage bug in `static_threshold_baseline` (its transaction-count threshold was originally computed from the entire dataset, including future days, before being made day-indexed and history-only). The table above reflects the corrected, leak-free numbers. Drift Watch's own numbers were unaffected — the bug was only in the comparison strawman.

## Razorpay integration: actual vs. simulated

All data is synthetic, generated by `data/synthetic_generator.py`. No real Razorpay API, production data, or partnership is used or claimed anywhere in this project.

## Repository layout

```
drift-watch/
├── research/        RAZORPAY_RESEARCH.md, PRODUCT_OVERLAP.md, COMPETITIVE_ANALYSIS.md
├── docs/            PRODUCT_SPEC.md
├── data/            synthetic_generator.py
├── detection/        drift_detector.py (statistical layer)
├── agents/          investigators.py, case_builder.py
├── evaluation/      evaluate.py
├── scripts/         run_demo_case.py
├── PROJECT_STATE.md
├── DECISIONS.md
├── SECURITY.md
└── README.md
```

## Future

With a real FastAPI backend, persistence, and the LLM integration wired in (see PROJECT_STATE.md next-session priorities), this becomes deployable as a real Agent Studio-style agent — a natural extension of Razorpay's existing agentic risk-tooling pattern (Bumblebee for onboarding, Drift Watch for the ongoing relationship).
