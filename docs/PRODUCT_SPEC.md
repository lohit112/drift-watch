# Drift Watch — Product Spec

## Problem statement

Merchant risk review at payment platforms happens almost entirely at onboarding. Once a merchant is approved, monitoring tends to be reactive (a dispute gets filed, a fraud alert fires) rather than continuous. But merchant risk is not static — a legitimate business can be compromised, pivot into a riskier category, or begin laundering through a previously clean account, and none of that shows up until damage (chargebacks, regulatory exposure, reputational risk) has already accumulated. Risk analysts, meanwhile, are already stretched reviewing onboarding volume (see Bumblebee's 10-12k/month figure) — they have no bandwidth to proactively re-review approved merchants.

## Target user

Primary: a **risk operations analyst** at a payments platform, reviewing surfaced cases.
Secondary (future extension, not in v1): the merchant themselves, receiving transparency into why they were flagged.

## User journey (v1)

1. Analyst opens the Drift Watch dashboard — sees a list of merchants by health state (Normal / Watch / Investigate / Escalate).
2. A merchant transitions from Normal → Watch. Analyst clicks in.
3. Sees the behavioral timeline: baseline period, then the point drift began, annotated with which signals moved.
4. Sees the investigation trail: which sub-agents fired, what each found, in what order (audit log).
5. Sees the case: Hypothesis A (risk explanation) vs Hypothesis B (legitimate explanation), evidence for each, confidence score, recommended action.
6. Analyst approves the recommended action, overrides it, or requests more evidence. Decision is logged and feeds back into future baseline/confidence calibration.

## Core workflows

- **Continuous monitoring** — new merchant events ingested, rolled into each merchant's baseline.
- **Drift detection** — statistical layer flags merchants whose recent behavior deviates meaningfully from their own history.
- **Investigation** — for flagged merchants, specialized fetchers gather evidence across transaction, dispute, geography, and profile domains.
- **Correlation & case building** — the planner/reasoner correlates evidence, generates competing hypotheses, assigns confidence, and drafts a structured case.
- **Human review** — analyst approves/overrides/requests more evidence; outcome recorded.
- **Feedback loop** — recorded outcomes adjust future baseline sensitivity per merchant (basic v1: track false-positive rate per detector type and surface it, rather than a full online-learning loop).

## Agent architecture

See ARCHITECTURE.md (generated alongside the code) for the full diagram. Summary: Sentinel (drift detection) → Planner → {Transaction, Dispute, Geography, Merchant Profile} Investigators → Evidence Correlator → Case Builder → Human Approval Gate → Outcome Log → Baseline Update.

## Data model (v1, simplified)

- `merchants(merchant_id, name, category, onboarded_date, geography_home)`
- `transactions(txn_id, merchant_id, timestamp, amount, category, geography, payment_method, customer_id)`
- `disputes(dispute_id, merchant_id, txn_id, timestamp, reason_code, status)`
- `merchant_daily_features(merchant_id, date, txn_count, txn_volume, avg_txn_value, refund_rate, dispute_rate, category_entropy, geo_entropy, ...)`
- `drift_events(event_id, merchant_id, detected_at, signals[], severity)`
- `cases(case_id, merchant_id, drift_event_id, hypothesis_a, hypothesis_b, evidence[], confidence, recommended_action, status, reviewer_decision, decided_at)`
- `audit_log(log_id, case_id, agent_name, action, timestamp, detail)`

## Evaluation methodology

Synthetic dataset with ground-truth labels (see `data/` generator): normal, seasonal, growing, product-launch, geo-expansion, and fraud-drift merchant archetypes. Metrics: precision/recall/F1 on drift-event detection against ground truth, false-positive rate, detection latency (days from true onset to first flag). Baseline comparison: static global-threshold rule vs. Drift Watch's merchant-specific baseline approach, run on the same dataset.

## Security model

- All merchant-supplied text (website copy, policy pages, dispute descriptions) is treated as untrusted data, never as instructions — explicit prompt-injection resistance testing required (see SECURITY.md).
- No autonomous irreversible action. Every recommended action requires human approval before execution.
- Every case and every agent step is logged with reason, confidence, timestamp, and rollback path.
- Synthetic data only; explicitly labeled as such everywhere in UI, README, and pitch.

## Demo scenario

The "180-day healthy merchant, then correlated drift over days 181-185" scenario described in the original brief — transaction volume spike, new category, refund-rate spike, dispute spike, geography shift — with the system correctly generating both the fraud hypothesis and a legitimate "seasonal promotion" hypothesis, assigning confidence, and recommending escalation rather than auto-action.
