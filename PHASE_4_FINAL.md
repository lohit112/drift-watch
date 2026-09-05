# Phase 4 — Final Report (Agentic Investigation Layer)

_Date: Sep 5, 2026. Starting point: `drift-watch-phase4-current.zip` (mid-flight
Phase 4 checkpoint: full `agent/` package + 2 agent test files, 1 of 70 tests
failing, docs/PHASE_4_ARCHITECTURE.md and several referenced artifacts missing).
Phases 1–3 untouched except where noted below._

## Completion status: **COMPLETE**

All Phase 4 task-brief items are implemented and verified: typed tool
interfaces (step 3), grounded synthesis with evidence citations (step 4),
4-hypothesis model reusing the Phase 2 confidence math unchanged (step 5),
evidence-seeking planner with pluggable model interfaces (steps 6 & 9),
bounded investigation loop with hard budget caps (steps 7–8), failure policy
where a failed step never increases risk (step 11), sufficiency evaluated from
current evidence rather than tool counts (step 10), structured case output
with approval gate and full audit trail (steps 13–14), prompt-injection trust
boundary (step 15), CLI demo (step 18), and 70 passing tests including the
step-17 checklist (step 17).

## What this session changed (and why)

**Checkpoint state:** 69/70 tests passing. The failure was
`test_agent_planner_and_loop.py::test_conflicting_evidence_produces_request_more_evidence`,
which imports the deterministic layer's `GOLDEN_AMBIGUOUS_EPISODE` scenario
(refund up / dispute down, seed 303) bit-identically and requires the agent
loop not to ESCALATE it.

**Root cause — a genuine bug, not a threshold problem.** Diagnosis (numeric
trace on the real scenario, same episode, same day):

- The agent loop investigates only the episode's deviant signal groups (by
  design — tests #1/#3 assert a planner "must not investigate a group that
  never deviated"), and deliberately does not pre-load Phase 3's
  contradicting evidence for quiet groups.
- The evidence pool was therefore one-sided: LEGITIMATE_GROWTH and
  SEASONAL_PATTERN sat at 0.0 not because they were checked and rejected, but
  because nothing that could produce their evidence had ever run. On that
  pool, evidence_balance is trivially 1.0 and RISK_DRIFT scored 0.708.
- `evaluate_sufficiency` read "not ambiguous" off that artifact → SUFFICIENT
  → synthesis → ESCALATE. The deterministic layer, investigating all 5 groups,
  computed 0.62 → REQUEST_MORE_EVIDENCE on the same episode. The agent layer
  was MORE escalation-prone than the layer it wraps — violating
  `agent/failures.py`'s governing rule that a failed (or never-made) check
  must never increase risk.

**Fix (no threshold changed anywhere):**
1. `agent/loop.py::evaluate_sufficiency` — SUFFICIENT now additionally
   requires **signal-group coverage**: every taxonomy signal group must have
   at least one episode-window evidence item (trigger / contextual /
   contradicting / missing). Bare `historical` entries do not count: they
   describe prior history, not the group's behavior during this episode.
2. `agent/planner.py` — `historical_context` is now asked unconditionally once
   the trigger groups are covered, restoring the planner's own documented
   priority-2 order. The previous score-gated version
   (`_needs_more_evidence_before_deciding` + `decide_action_from_score`, now
   removed as dead code) let a partial-pool RISK_DRIFT lead of 0.708 skip the
   one question that could change it. This is strictly MORE evidence
   gathered, not a tuned stop.

**Verified consequences (real runs, not fabricated):**
- Seed-303 conflicting episode: REQUEST_MORE_EVIDENCE — now agrees with the
  deterministic layer's INVESTIGATING resolution.
- M0021 flagship fraud episode: still ESCALATE (0.785, 5/5 groups covered, 9
  evidence items, fully grounded narrative, PENDING_HUMAN_REVIEW).
- M0009 (seasonal merchant whose false escalation is the documented Phase 3
  open limitation, DECISIONS.md D10): the agent layer now returns
  REQUEST_MORE_EVIDENCE instead of ESCALATE — a real improvement obtained by
  honest coverage accounting rather than a tuned discount. The deterministic
  episode layer's own over-escalation remains open (unchanged scope).
- Full suite: 70/70 pass, including all 23 Phase 3 regression tests.

## Test results

| Suite | Result |
|---|---|
| Full suite (`pytest tests/`) | **70 passed, 0 failed** (was 69/70) |
| Phase 3 regression subset (`test_episode_invariants.py`, `test_golden_episodes.py`, `test_golden_cases.py`, `test_confidence_model.py`) | 23 passed |
| Phase 1/2 regression (`test_detector.py`, `test_event_alignment.py`, `test_data_handling.py`, `test_case_builder.py`, `test_failure_handling.py`) | all passed (within the 70) |

## End-to-end verification (scripted against the real dataset)

- **Bounded execution:** M0021 investigation used 3/5 tool calls and 3/6
  iterations and returned normally; a greedy/never-stopping planner is capped
  by the budget (tests #5, #6).
- **Grounding:** every `EVID-xxx` cited in the final narrative exists in the
  investigation's registry (`check_grounding` → fully_grounded=True,
  rejected_claims=[]); the synthesis layer is template-based and cannot write
  a number that didn't come from an `AgentEvidence` field.
- **Safe failure:** a forced `TOOL_EXCEPTION` produced zero evidence, was
  recorded in the audit trail, and lowered the RISK_DRIFT score (0.785 →
  0.653) with a REQUEST_MORE_EVIDENCE outcome — failure never fabricates risk.
- **Audit trail:** 13 events, strictly sequential, covering
  investigation_started, loaded_episode_baseline_evidence, planner_decision
  (with reason), tool_call (with evidence ids), hypothesis_update (before/after
  scores), recommendation, approval_required.
- **Human approval boundary:** ESCALATE → PENDING_HUMAN_REVIEW;
  `record_human_decision` is the only approval-transition function and has no
  automated caller; invalid decisions raise.
- **Reproducibility:** identical runs produce identical tool sequences and
  hypothesis states.

## Demo command

```
python -m agent.demo --merchant M0021
```

(from the repository root; `--merchant` accepts any ID in
`data/synthetic_merchant_events.csv`, e.g. M0009 for the seasonal case).

## Files changed in this session

- `agent/loop.py` — sufficiency coverage condition (the fix), coverage
  helper, docstring corrections.
- `agent/planner.py` — unconditional `historical_context` after trigger
  coverage; removed `_needs_more_evidence_before_deciding` and
  `decide_action_from_score`; docstring updated.
- `agent/audit.py`, `agent/failures.py`, `agent/policy.py` — stale test-file
  references in docstrings corrected (no behavior change).
- `docs/PHASE_4_ARCHITECTURE.md` — **created** (referenced 4× from code
  docstrings; records the design and the bug account above).
- `PHASE_4_FINAL.md` — **created** (this file).
- `PROJECT_STATE.md` — updated with the Phase 4 session summary.

No detection/, episode/, agents/, evaluation/, or data/ files were touched —
Phases 1–3 are byte-identical apart from nothing; their tests all pass
unchanged.

## Known limitations (honest, tracked — not hidden)

1. **Narrow-episode conservatism (new, deliberate).** A genuine fraud episode
   that moves only some signal groups resolves to REQUEST_MORE_EVIDENCE at the
   agent layer (the quiet groups were never investigated — by design per tests
   #1/#3 — so coverage can't complete). This is the safe direction (human
   review queue, not a silent drop) and matches the deterministic layer's
   verdict on ambiguous cases, but it makes the agent layer strictly more
   conservative than the deterministic layer for narrow episodes. Widening it
   means revisiting the "don't investigate non-deviant groups" design, not
   tuning a threshold.
2. **Seasonal-merchant over-escalation persists at the deterministic episode
   layer** (DECISIONS.md D10, M0009 escalates on 3/4 occurrences). The agent
   layer now declines to escalate M0009, but the Phase 3 limitation itself is
   unresolved.
3. **Planner/synthesis are deterministic mocks**, explicitly labeled as such.
   No LLM is wired in; the pluggable interfaces are the seam. Prompt-injection
   guarantees are structural (no free-text fields, grounded templates, human
   approval), not a claim of LLM-injection immunity — see
   docs/PHASE_4_ARCHITECTURE.md "Security" for what a real LLM would need.
4. **Hypothesis model asymmetry** — only RISK_DRIFT's score has Phase 2 rigor;
   LEGITIMATE_GROWTH/SEASONAL_PATTERN are derived, not independently
   calibrated.
5. **No persistent backend/FastAPI/frontend** — future work, unchanged from
   PROJECT_STATE.md.
