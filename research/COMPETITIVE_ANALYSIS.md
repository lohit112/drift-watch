# Competitive & Technical Landscape

## Adjacent technical concepts we're deliberately borrowing from

- **Concept drift detection** (ML literature): the idea that a model/baseline trained on past behavior degrades as the underlying data distribution shifts. Drift Watch applies this at the *merchant* level rather than a global model level — each merchant has its own "distribution," and drift is measured against that merchant's own history, not a population-wide rule.
- **Change-point detection / EWMA / rolling z-scores**: standard statistical tools for "has this series shifted," cheaper and more explainable than an ML classifier for numeric time series. We use these for the *detection* layer, reserving the LLM/agent layer for reasoning and hypothesis generation — not recomputing statistics.
- **Multi-agent evidence gathering** (Bumblebee precedent, also broader "tool-using agent" pattern): specialized sub-agents each own one investigative domain (transactions, disputes, geography, merchant profile) and report structured findings to a correlator/planner, rather than one agent trying to do everything.
- **Explainable AI / human-in-the-loop risk review**: the case builder's job is to produce a reviewable artifact (hypotheses, evidence, confidence, competing explanation) rather than a bare score — closer to how a human risk analyst would write up a case.

## Why generic fraud-detection hackathon projects tend to score poorly (things to avoid)

1. **Single global threshold** ("refund rate > 5% = risky") — ignores that merchants have wildly different normal baselines (a returns-heavy apparel merchant vs. a digital-goods merchant). Judges who work in risk will notice this immediately.
2. **Score without explanation** — "risk = 87" with no reasoning trail is indistinguishable from a black-box classifier; doesn't demonstrate agentic behavior, just inference.
3. **No false-positive handling** — treating every anomaly as fraud (ignoring legitimate causes like sales, launches, geographic expansion) reads as naive.
4. **Autonomous punitive action** — auto-suspending merchants without human review is both a bad product decision and a red flag in a security/guardrails review.
5. **Fabricated "production" framing** — claiming Razorpay data/partnership without basis is a fast way to lose credibility with people who actually work there.

Drift Watch's differentiators map directly against each of these five failure modes — that mapping should show up explicitly in the pitch and README, not just be implicit.
