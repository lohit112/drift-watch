# Changelog

This changelog records the engineering progression of Drift Watch. It intentionally focuses on decisions, failures, fixes, and validation rather than listing every file change.

## Phase 1 — Correctness foundation

- Built the first merchant-specific drift detector, evidence investigators, case builder, synthetic benchmark, and CLI demo.
- Found that `txn_count` and `txn_volume` were being counted as independent risk signals even though they are algebraically correlated. Fixed the false independence by introducing signal domains.
- Fixed insufficient-history handling so early observations no longer produced misleading baseline comparisons.
- Fixed native JSON boolean serialization in case output.
- Found and fixed an event/evidence alignment bug in the demo: the selected drift day and the evidence's signal groups could come from different rows.
- Replaced unsafe `eval()`-style parsing with safe literal parsing and added malicious/malformed input coverage.
- Removed hardcoded machine-specific paths.
- Re-audited the static comparator and found real temporal leakage: its `txn_count` threshold used future observations. Replaced it with a history-only expanding threshold and accepted the resulting benchmark change instead of hiding it.
- Added regression coverage for temporal leakage, malformed payloads, missing values, and event alignment.

## Phase 2 — Evidence reasoning and evaluation

- Replaced unstructured findings with typed evidence carrying trigger, contextual, historical, contradicting, and missing semantics.
- Replaced the arbitrary confidence formula with a documented multi-component Risk Confidence Score.
- Added the missing refund investigator.
- Formalized the signal taxonomy as a shared source of truth.
- Added richer synthetic merchant archetypes and multi-seed evaluation.
- Added event-level metrics so multi-day incidents are evaluated as incidents, not as repeated daily positives.
- Compared baseline computation methods and kept the shipped mean/std method after reproducing the alternatives.
- Added golden cases and explicit failure-path tests.
- Recorded an important tradeoff honestly: on the richer benchmark, Drift Watch improved recall/false-alert behavior but did not beat the static comparator on every metric.

## Phase 3 — Stateful risk episodes

- Introduced `RiskEpisode`, gap-tolerant grouping, episode evidence aggregation, and a state machine.
- Found that evaluating one flagged day at a time caused persistent fraud episodes to oscillate between decisions. Recomputed evidence episode-to-date and made resolution depend on sustained quiet days rather than day-to-day confidence flips.
- Found a legitimate seasonal merchant repeatedly escalating. Tried an established-pattern confidence discount, observed that it could also suppress a real fraud scenario, and reverted the change. The seasonal limitation remains documented instead of being tuned away.
- Measured episode fragmentation/duplicate behavior and kept the limitation visible when grouping did not improve raw precision/F1.
- Clarified `GAP_TOLERANCE_DAYS` as the number of skipped/unflagged calendar days tolerated between flagged observations.
- Ran multi-seed episode evaluation and ablations; retained the regressions as evidence rather than cherry-picking a favorable variant.

## Phase 4 — Bounded agentic investigation

- Added typed investigation tools, an evidence registry with stable `EVID-xxx` IDs, competing hypotheses, a planner interface, bounded orchestration, failure policy, grounded synthesis, human-approval policy, and audit sequencing.
- Found a double-counting bug when multiple tools each contributed historical evidence and `historical_context` recomputed it again. Removed the duplicate path.
- Found that preloading the complete Phase 3 evidence package made the agentic investigation redundant. Changed the loop to start from the episode trigger summary so the planner has to decide what to investigate.
- Found that zero support for an alternative hypothesis did not mean that the hypothesis had been investigated. Tightened sufficiency to require actual evidence coverage.
- Found that `AgentEvidence` dropped the detector's deviation/z-score, silently weakening anomaly strength. Restored the field and regression coverage.
- Found that selective investigation could miss contradictions in quiet groups. Chose the conservative behavior (request more evidence rather than manufacture certainty) and documented the tradeoff.
- Preserved the deterministic planner/synthesizer as the reference implementation and kept the model interfaces pluggable.
- Verified bounded execution, safe failure, grounding, audit coherence, reproducibility, and human approval boundaries.

## Phase 5 — Productization

- Added a thin FastAPI layer around the existing engine rather than duplicating detection/episode/investigation logic.
- Added SQLite persistence for merchants, episodes, investigations, evidence, human decisions, and audit events.
- Added the React/Vite Risk Ops dashboard with merchant, episode, investigation, human-review, and audit views.
- Added a pluggable LLM adapter with strict output validation and deterministic fallback. No live provider call is claimed; the adapter was tested with fake transports.
- Verified API error semantics, decision immutability, approval boundaries, and absence of an executable account-action route.
- Reached a 102-test regression/integration suite with the historical Phase 1–4 behavior preserved.

## Late-night debugging highlights

Some of the hardest fixes happened during the final overnight push, especially around Phase 3/4 behavior. The useful record is not the hour on the clock; it is what changed under pressure:

- A failing golden episode exposed that the agent could escalate an ambiguous case because unexplored hypotheses were being mistaken for negative evidence. The fix was to make sufficiency depend on actual signal-group coverage and to gather historical context unconditionally after trigger coverage.
- A missing deviation field in `AgentEvidence` was caught by tracing why anomaly strength was unexpectedly low. The field was restored rather than compensating with a larger threshold weight.
- A duplicate historical-evidence path was found while combining multiple investigation tools. The duplicate path was removed and regression-tested.
- A frontend replacement initially failed as a workspace operation, so the final UI was validated as a normal filesystem project instead of relying on the coding-agent workspace.

These are recorded because they explain how the final system got from a plausible prototype to a tested, bounded, auditable one.
