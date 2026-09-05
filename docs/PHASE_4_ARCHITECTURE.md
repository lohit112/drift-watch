# Phase 4 Architecture — Agentic Investigation Layer

_Status: final (Phase 4 complete). This document is referenced directly from
module docstrings in `agent/`; it records the design decisions and the
genuine bugs found and fixed during the phase's own testing._

## What Phase 4 adds

Phases 1–3 built a deterministic core: statistical drift detection (Phase 1),
typed multi-temporal evidence + a documented confidence model (Phase 2), and
stateful episodes with a confidence trajectory (Phase 3). Phase 4 adds the
agentic layer on top, per the brief:

```
RiskEpisode (Phase 3)
   │
   ▼
InvestigationLoop (agent/loop.py) ── pure orchestration, no risk judgments
   │
   ├─ PlannerModel        (agent/planner.py)   "what to investigate next"
   ├─ InvestigationTool[] (agent/tools.py)     "gather evidence" (wraps Phase 3
   │                                            aggregation; computes nothing new)
   ├─ EvidenceRegistry    (agent/evidence.py)  stable EVID-xxx ids, traceability
   ├─ FailurePolicy       (agent/failures.py)  "a failed step never increases risk"
   ├─ HypothesisState     (agent/hypotheses.py) 4 hypotheses; reuses
   │                                            agents.confidence UNCHANGED
   ├─ evaluate_sufficiency (agent/loop.py)     "do we have enough evidence"
   ├─ SynthesisModel      (agent/synthesis.py) grounded, template-based case
   └─ ApprovalPolicy      (agent/policy.py)    every ESCALATE starts
                                                PENDING_HUMAN_REVIEW; there is
                                                NO code path that executes an
                                                account action
```

Every decision point is a named, independently testable component. `PlannerModel`
and `SynthesisModel` are pluggable interfaces: the shipped implementations are
explicitly deterministic/mock (labeled as such throughout — no fake LLM), and a
real LLM could be swapped in behind the same interface without touching the loop.

## Why the loop doesn't pre-load full episode evidence

`RiskEpisode` (Phase 3) already carries `supporting_evidence`,
`contradicting_evidence`, and `missing_evidence` from the deterministic layer's
own investigation of ALL 5 signal groups. The loop pre-loads ONLY
`missing_evidence` (genuine carried-over knowledge gaps). Pre-loading the rest
would make the agent's own tool calls redundant — Phase 3 would already have
answered every question, and there would be nothing left to investigate,
defeating the purpose of the phase. The planner instead reads
`episode.signal_groups` to know WHAT triggered, without already knowing
everything a deeper investigation would find.

Consequence (important, and the source of the phase's one real bug — see
" bugs found and fixed" below): the agent's evidence pool is intentionally
PARTIAL. The confidence math must never treat "not investigated" as "checked
and clean."

## Hypothesis model

Four explicit hypotheses (`agent/hypotheses.py`): RISK_DRIFT,
LEGITIMATE_GROWTH, SEASONAL_PATTERN, INSUFFICIENT_EVIDENCE.

- RISK_DRIFT reuses `agents.confidence.compute_confidence` UNCHANGED on the
  agent-gathered evidence pool (reconstructed into core `Evidence` objects).
- LEGITIMATE_GROWTH and SEASONAL_PATTERN are derived from Hypothesis-B-supporting
  evidence, split by kind: "contradicting" (a group that never deviated) is
  generic time-independent B-evidence; "historical" evidence of an established
  recurring pattern is the more specific SEASONAL signal, discounted by signal
  breadth (a real seasonal bump moves 1–2 groups; a coordinated 5-group
  deviation is what fraud looks like — requiring LOW breadth alongside
  recurrence is what keeps this signal from repeating DECISIONS.md D10's
  reverted-discount mistake).
- INSUFFICIENT_EVIDENCE is not a residual bucket: it leads specifically when
  MISSING evidence exists or the real hypotheses are too close to separate.

Documented simplification: only RISK_DRIFT's score has the same rigor as the
Phase 2 model; the other three are derived, not independently calibrated
(symmetry is a tracked future-work item, not a hidden gap).

## Sufficiency: the one-sided-pool bug (found and fixed this phase)

`evaluate_sufficiency` originally declared SUFFICIENT when the episode's own
deviant ("trigger") signal groups had been investigated and the hypothesis
state was "not ambiguous." Testing against the deterministic golden scenario
`GOLDEN_AMBIGUOUS_EPISODE` (refund up / dispute down, seed 303, imported
bit-identically into `tests/test_agent_planner_and_loop.py`) exposed a genuine
bug, not a threshold problem:

1. The planner (by design — see its docstring and tests #1/#3) only investigates
   the episode's deviant groups; the loop deliberately does not pre-load Phase 3's
   contradicting evidence for the quiet groups.
2. So LEGITIMATE_GROWTH and SEASONAL_PATTERN sat at 0.0 not because they had
   been checked and rejected, but because nothing that could produce their
   evidence had ever run. "Not ambiguous" was an artifact of the one-sided pool
   (evidence_balance is trivially 1.0 when the pool contains only A-supporting
   items).
3. The agent layer therefore ESCALATED the same episode at the same day that the
   deterministic layer — investigating all 5 groups — held at 0.62 /
   REQUEST_MORE_EVIDENCE. The agent layer was MORE escalation-prone than the
   layer it wraps, violating `agent/failures.py`'s governing rule ("a failed
   investigation step must never increase risk" — an absent check is a failed
   check).

Fix (no thresholds changed anywhere):
- `evaluate_sufficiency` now also requires **signal-group coverage**: every
  signal group in the taxonomy must have at least one EPISODE-WINDOW evidence
  item (trigger / contextual / contradicting / missing). Bare "historical"
  entries do not count — they describe prior history, not the group's behavior
  during this episode.
- `DeterministicPlanner` now asks its own documented priority-2 question
  (`historical_context`) unconditionally once the trigger groups are covered,
  instead of gating it on the current partial-pool score. An earlier
  score-gated version (`_needs_more_evidence_before_deciding`) let a
  partial-pool RISK_DRIFT lead of 0.708 skip the one question that could change
  it; that gate was removed (dead code deleted), and with it the module-level
  `decide_action_from_score` helper.

Net behavioral effect, verified against real cases:
- Seed-303 conflicting episode: REQUEST_MORE_EVIDENCE (agrees with the
  deterministic layer's INVESTIGATING resolution).
- M0021 (flagship 5-group fraud episode): still ESCALATE — its `mix_behavior`
  trigger tool also produced contradicting evidence for the quiet `geo_mix`
  group, completing coverage honestly.
- M0009 (the seasonal merchant whose false escalation is the documented Phase 3
  open limitation, DECISIONS.md D10): the agent layer now returns
  REQUEST_MORE_EVIDENCE instead of ESCALATE — a real improvement, achieved by
  honest coverage accounting rather than a tuned discount.
- Known, accepted tradeoff: a genuinely narrow fraud episode (some deviant
  groups, quiet groups never investigated because the planner is not permitted
  to investigate non-deviant groups) resolves to REQUEST_MORE_EVIDENCE rather
  than ESCALATE. This is the conservative direction (human review queue, not a
  silent drop), and it is the direct consequence of tests #1/#3's deliberate
  "don't investigate what didn't deviate" design. Widening it would require
  revisiting that design, not tuning a threshold.

## Security

- No autonomous action: `agent/policy.py` is the hard boundary. Every
  recommendation starts `PENDING_HUMAN_REVIEW`; `record_human_decision` is the
  only function that can change an approval status and has no automated caller.
- Prompt-injection trust boundary: the pipeline has no free-text merchant
  field. Merchant-controlled values (`dominant_category`, `dominant_geo`) come
  from fixed categorical vocabularies. `sanitize_merchant_text` exists and is
  tested so a future free-text field inherits the defensive pattern
  (merchant text is data to quote, never instructions; it plays no role in
  tool selection or policy).
- Honestly stated limitation: this is not a claim of prompt-injection immunity
  for a future LLM-backed planner/synthesis. Before plugging in a real LLM you
  would additionally need: adversarial injection tests over every field the
  model reads, a verification that model output can only enter via the same
  grounded-template path (never as raw narrative), and a rule that the model
  can never write numbers that didn't come from an `AgentEvidence` object.
  The deterministic scores/decision math stay out of the model's hands either
  way (DECISIONS.md D4).
