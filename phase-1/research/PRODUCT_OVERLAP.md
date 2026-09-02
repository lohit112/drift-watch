# Product Overlap Analysis

For each existing Razorpay system, we answer: what it does, what it monitors/automates, what's publicly documented, and what Drift Watch deliberately does NOT duplicate.

## Bumblebee (internal merchant onboarding risk)

- **Does**: reviews a merchant's website/policies/social presence at signup or when flagged, in seconds, via specialized evidence-gathering sub-agents ("Fetchers").
- **Monitors**: point-in-time signals at onboarding — website content, policy pages, content screening.
- **Automates**: the initial go/no-go and manual review workload.
- **Publicly documented**: yes, via Razorpay Engineering blog (Dec 2025).
- **Drift Watch does NOT**: replace or re-implement onboarding review. Drift Watch assumes the merchant already passed this stage.
- **Why Drift Watch is a legitimate extension**: Bumblebee answers "should we approve this merchant." Drift Watch answers "should we re-open the file on a merchant we already approved." Same investigative philosophy (evidence over score), different point in the merchant lifecycle — onboarding vs. ongoing.

## RTO Shield / RTO Insights

- **Does**: flags high-risk cash-on-delivery orders before dispatch (address validation, pincode risk); analyzes return patterns.
- **Scope**: COD/logistics-specific, order-level, not general merchant-behavior risk.
- **Drift Watch does NOT**: touch COD/logistics decisions at all.
- **Distinction**: RTO Shield is a narrow, single-signal-domain tool (COD returns). Drift Watch is merchant-level, multi-signal, and domain-agnostic (works whether the merchant does COD or not).

## Dispute Responder / Dispute Expert

- **Does**: reactive — responds to a chargeback *after* it's filed, gathers evidence, submits a rebuttal.
- **Drift Watch does NOT**: respond to individual disputes or build rebuttal evidence for a chargeback case.
- **Distinction**: Dispute Responder is reactive and transaction-scoped ("defend this one dispute"). Drift Watch is proactive and merchant-scoped ("has this merchant's overall behavior changed enough to warrant a look") — dispute *velocity* is one input signal into Drift Watch, not the object being defended.

## Subscription Recovery / Abandoned Cart Conversion

- **Does**: revenue-recovery agents aimed at the merchant's customers (retry failed payments, win back abandoned carts).
- **Drift Watch does NOT**: touch customer-facing recovery at all. Different actor (Razorpay↔merchant risk relationship, not merchant↔customer revenue relationship).

## Cashflow Forecaster

- **Does**: predicts a merchant's own cash position 3–7 days out for the merchant's benefit.
- **Drift Watch does NOT**: forecast cash flow. Different beneficiary too — Cashflow Forecaster serves the merchant; Drift Watch serves Razorpay's risk function (though a defensible future extension is surfacing "why we flagged you" back to good-faith merchants for transparency).

## Net conclusion

No existing public Razorpay agent continuously re-evaluates an **already-approved** merchant's behavior over time using a **merchant-specific behavioral baseline**, correlates multiple signal types, generates competing hypotheses (fraud vs. legitimate business change), and produces an evidence-backed case for human review. That is Drift Watch's specific, defensible white space.

If, during build, any feature starts to converge with the above (e.g., "let's also auto-respond to disputes") — stop and cut it. Scope discipline is itself a credibility signal for judges who ship these exact products.
