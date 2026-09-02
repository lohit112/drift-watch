# Razorpay Research Report

*Compiled Aug 21, 2026 from Razorpay's own blog, engineering blog, and public announcements. No internal/confidential sources used.*

## 1. Razorpay's AI strategy, in one line

Razorpay is moving from "payments infrastructure" to "agentic financial infrastructure" — autonomous agents that observe, reason, and execute financial/operational tasks on a merchant's behalf, not just dashboards that report numbers.

## 2. Agent Studio (public-facing, merchant-deployable)

Launched at FTX 2026, built on Anthropic's Claude Agent SDK. A marketplace where merchants deploy pre-built or custom (no-code, natural-language-defined) agents. Production agents at launch:

- **Dispute Responder / Dispute Expert** — pulls evidence from Razorpay + connected platforms (Shopify, Shiprocket), scores win probability, auto-submits or drafts chargeback responses before the deadline.
- **Subscription Recovery** — smarter retry logic on failed subscription payments; voice-based (ElevenLabs) outreach to at-risk subscribers in English/Hindi.
- **Abandoned Cart Conversion** — re-engages checkout drop-offs via WhatsApp/voice/email (built with Nugget by Zomato, SuperU).
- **Cashflow Forecaster** — predicts cash position 3–7 days out; payroll/shortfall alerts.
- **RTO Shield** — flags high-risk cash-on-delivery orders pre-dispatch (LLM address validation + pincode risk intelligence).
- **RTO Insights** — analytics on return patterns by pincode/product/customer.
- Settlement/vendor agents — WhatsApp settlement digests, automated vendor payouts with TDS handling.
- "Build your own agent" — no-code natural-language agent builder on the same platform.

Explicit design principle from Razorpay's own "Principles, Guardrails, and Merchant Control" post: every agent operates within merchant-defined boundaries, usage-based pricing, no autonomous action without disclosed scope.

## 3. Bumblebee (internal risk system — the most relevant precedent)

Razorpay's internal multi-agent system for **merchant onboarding risk review**. Original problem: 10,000–12,000 manual website reviews/month, ~4 minutes each (700–800 human-hours/month), inconsistent judgment between human reviewers, a third-party content-screening vendor generating ~50 alerts/month at <10% precision.

Architecture lesson from their engineering blog (worth citing in our own docs): they tried a single "smart" agent first (via n8n, a visual workflow tool), it didn't scale, they rebuilt as specialized sub-agents ("Fetchers") with separated planning, evidence-gathering, and analysis roles. Key quote-worthy insight (paraphrased, not verbatim): the hard part wasn't the model, it was the architecture — knowing when to split responsibilities across specialized agents rather than one generalist agent.

**This is the most important precedent for Drift Watch** — it validates (a) the multi-agent evidence-gathering pattern, (b) that Razorpay's own engineers value architectural discipline over "wire up an LLM" solutions, and (c) that this is exactly the kind of system Razorpay's risk org has proven the taste to evaluate well.

## 4. Other internal AI systems (context, not overlap)

- **Security triage agent** — SAST triage, 750→2 hours, context-aware, multi-tier (L1 triage, L2 auto-remediation with PRs).
- **On-call/incident agent ("Project Viveka")** — cuts incident investigation from 30 min to 90 sec.

These show a company-wide pattern: identify a slow, judgment-heavy, high-volume human process, and replace it with an agent that reasons over evidence rather than a single classifier score. Drift Watch should read as "another instance of this pattern," applied to a gap Bumblebee doesn't cover.

## 5. What Bumblebee explicitly does NOT do (the gap)

Bumblebee's stated scope is **onboarding-time** website/merchant review. Nothing in Razorpay's public material describes **continuous, post-onboarding behavioral monitoring** of merchants that have already passed risk review. That's the white space Drift Watch occupies — see PRODUCT_OVERLAP.md for the full comparison.
