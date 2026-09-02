# Decisions Log

### D1 — Track: AI Risk Manager, not AI Growth & Agentic Commerce
The Growth/Agentic Commerce track is where Razorpay is investing most publicly (Claude+Zepto/Swiggy/Zomato checkout partnership), which means both the highest visibility and the highest existing-product overlap risk. AI Risk Manager is less crowded publicly and maps directly onto Razorpay's own internal engineering culture (Bumblebee), which we judged more likely to produce a genuine "let's talk about your architecture" reaction from a hiring panel than a flashier but thinner growth demo.

### D2 — Concept: post-onboarding drift, not onboarding review
Bumblebee already owns onboarding-time merchant risk review, extremely well, per Razorpay's own engineering blog. Building another onboarding-risk tool would read as a worse clone of something the judges ship internally. Post-onboarding continuous monitoring is explicitly *not* covered in any public Razorpay material we found — see research/PRODUCT_OVERLAP.md.

### D3 — Merchant-specific baseline, not global thresholds
A single global refund-rate or dispute-rate threshold treats a returns-heavy apparel merchant the same as a digital-goods merchant with near-zero returns. We use each merchant's own trailing history as the baseline, evaluated via z-scores against a rolling mean/std (EWMA-style), specifically because the original brief and our own competitive analysis flagged "single global threshold" as the #1 signal of an unsophisticated hackathon fraud project.

### D4 — Deterministic statistics for detection, LLM reserved for reasoning
Per the original design brief: numeric aggregation, thresholds, and time-series comparisons are handled by pandas/numpy, not an LLM. The LLM's job (currently a documented seam, not yet wired to a real API call — see PROJECT_STATE.md) is narrative generation and hypothesis framing over evidence the deterministic layer already computed and verified. This is a direct response to prompt-injection risk: a merchant can't talk their way out of a flag by writing something in a policy page, because the flag itself never touches the LLM.

### D5 — Independent signal-domain grouping (fixing a real bug)
Originally grouped `txn_count` and `txn_volume` as two separate signals toward the "≥2 correlated signals" flagging threshold. Since volume ≈ count × avg_value, these are not independent — this was double-counting one real signal and inflating false positives (see PROJECT_STATE.md bug log). Fixed by explicitly grouping features into independent signal domains (volume, refund, dispute, category_mix, geo_mix) before counting toward the correlation threshold. Kept in this log because the fix materially changed the evaluation numbers (false positive rate dropped from 2.08% to 0.71%) and that's exactly the kind of engineering judgment worth being able to describe in a panel interview.

### D6 — No autonomous account action, ever
Every recommended action in the case builder routes to a human approval gate. This was a hard requirement in the original brief and we treated it as non-negotiable rather than a nice-to-have, including in the demo script's audit log, which explicitly logs "Routed to human approval gate - no autonomous account action taken" on every case.

### D7 — Synthetic data only, explicitly labeled
No production Razorpay data is used or claimed. The generator (`data/synthetic_generator.py`) and every downstream artifact (README, PROJECT_SPEC, demo output) label the data as synthetic. This is both an ethical requirement from the original brief and a credibility issue — claiming access to real transaction data we don't have would be an easy, embarrassing thing for a Razorpay engineer to catch.
