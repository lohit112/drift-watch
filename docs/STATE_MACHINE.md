# Episode State Machine — Task Brief Step 4

## States

| State | Meaning | Confidence band (via `agents.confidence.decide_action`) |
|---|---|---|
| `WATCH` | Weak drift detected; evidence insufficient to act on. | `MONITOR` decision (score < 0.38, or clearly favors Hypothesis B) |
| `INVESTIGATING` | Multiple signals/evidence exist but don't clearly separate the two hypotheses. | `REQUEST_MORE_EVIDENCE` decision (score in `[0.38, 0.62]`) |
| `ESCALATE` | Evidence and confidence exceed the policy threshold for human review. | `ESCALATE` decision (score > 0.62) |
| `RESOLVED` | The episode has formally closed. Terminal — no further transitions permitted. | Not confidence-driven — see below. |

`WATCH`/`INVESTIGATING`/`ESCALATE` reuse the EXACT SAME thresholds as the
Phase 2 single-day `decide_action` (`agents/confidence.py`) — deliberately,
so a given confidence score means the same thing whether it came from a
single day or an episode-to-date aggregate. `episode/state_machine.py`'s
`DECISION_TO_STATE` is a direct, unconditional mapping.

## Why RESOLVED is NOT confidence-driven

`RESOLVED` is a structural event: it fires once `GAP_TOLERANCE_DAYS` skipped
(unflagged) calendar days have elapsed after the episode's flagged run,
confirmed by one further day (see `episode/grouping.py`'s docstring for the
precise definition of `GAP_TOLERANCE_DAYS` and a worked example) - or the
merchant's available history ends. This is deliberate — a low confidence score doesn't mean an episode is over, it
means the evidence right now looks weak; the episode only actually ends
when the underlying behavioral drift has genuinely stopped producing
flagged days. Mixing the two (e.g. auto-resolving whenever confidence
drops low) would silently close episodes that are still ongoing but
currently ambiguous — exactly the flip-flop failure this phase exists to
fix, just moved into `RESOLVED` instead of oscillating between the other
three states.

## One deliberate deviation from the brief's suggested transition list

The brief's step 4 example lists these named transitions:
```
WATCH → NORMAL
INVESTIGATING → WATCH
INVESTIGATING → ESCALATE
ESCALATE → RESOLVED
ESCALATE → WATCH
```

This implementation permits **any** WATCH/INVESTIGATING/ESCALATE state to
transition to any other WATCH/INVESTIGATING/ESCALATE state (all reachable
from all, except nothing leaves `RESOLVED`), rather than only the 5 listed
pairs. Reasoning: confidence is recomputed fresh from the whole
episode-to-date evidence every day (`episode/aggregation.py`), and a
genuinely sudden change in evidence (e.g. a new independent signal group
deviating hard on a single day) can legitimately jump a score directly from
`WATCH`-band to `ESCALATE`-band in one step. Forcing every transition
through `INVESTIGATING` as an artificial intermediate stop would mean
logging a state change that doesn't correspond to any real change in
confidence at that point — which directly conflicts with task brief step
20's explainability requirement ("this must come from structured data, not
hardcoded text"). A transition log entry should always be backed by an
actual computed confidence value; inventing a synthetic intermediate hop
would not be.

`NORMAL` (no episode at all) isn't a state `RiskEpisode` itself occupies —
an episode only exists once something has been flagged, so "no episode" is
represented by the absence of a `RiskEpisode`, not a first state within one.

## Transition record

Every transition (`episode/model.py::StateTransition`) carries:
`day`, `old_state`, `new_state`, `reason`, `confidence`, `evidence_keys`
(the `(signal_group, evidence_type)` pairs that changed since the last
transition), `actor` (always `"state_machine"` in this phase — this field
exists so a future agentic override, e.g. a human analyst manually
escalating, has somewhere to record itself distinctly).

`reason` is built by `episode/state_machine.py::explain_transition` FROM
the confidence breakdown's own components and the changed evidence keys —
never a canned per-state-pair sentence. Example, real output:

```
WATCH -> ESCALATE: score 0.73; new/changed evidence in: dispute, refund, volume; breadth=0.80; persistence=0.12; balance=0.83; novelty=0.00
```

## Determinism (invariant 5)

`transition()` is a pure function of `(day, old_state, confidence,
new_evidence_keys, force_resolve)` — given identical inputs it always
returns an identical `StateTransition`. Since `confidence` is itself
computed deterministically from the scored history (no randomness anywhere
in `episode/aggregation.py` or `agents/confidence.py`), re-running the
entire episode builder on the same scored history always produces an
identical transition log, confidence trajectory, and resolution. Verified
directly in `tests/test_episode_invariants.py`.
