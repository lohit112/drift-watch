"""
Episode state machine — task brief step 4.

States: WATCH, INVESTIGATING, ESCALATE, RESOLVED (task brief's suggested
machine, kept largely as-is - see docs/STATE_MACHINE.md for the one
deliberate deviation from the brief's exact transition list, and why).

Confidence-band -> state mapping reuses agents.confidence.decide_action
UNCHANGED (same thresholds: <0.38 WATCH-band / [0.38,0.62] INVESTIGATING-band
/ >0.62 ESCALATE-band via decide_action's REQUEST_MORE_EVIDENCE and ESCALATE
outcomes, plus its MONITOR outcome mapped to WATCH) so day-level and
episode-level cases stay consistent with each other - the same confidence
score means the same thing whether it came from a single day or an
episode-to-date aggregate.

RESOLVED is NOT driven by confidence at all - it is a structural event
(the episode's flagged run formally ends, per episode/grouping.py's gap
tolerance, or the merchant's history ends while the episode is still
open). Once RESOLVED, an episode is terminal and immutable - no further
transitions are permitted (this is directly tested as an invariant, see
tests/test_episode_invariants.py).
"""
from agents.confidence import ConfidenceBreakdown, decide_action
from episode.model import StateTransition

DECISION_TO_STATE = {
    "MONITOR": "WATCH",
    "REQUEST_MORE_EVIDENCE": "INVESTIGATING",
    "ESCALATE": "ESCALATE",
}


def status_for_confidence(confidence: ConfidenceBreakdown) -> str:
    decision, _, _ = decide_action(confidence)
    return DECISION_TO_STATE[decision]


def explain_transition(old_state: str, new_state: str, confidence: ConfidenceBreakdown,
                        new_evidence_keys: list) -> str:
    """Builds a reason string FROM STRUCTURED DATA (task brief step 20:
    'this must come from structured data, not hardcoded text') - it reads
    the confidence breakdown's own components and the evidence keys that
    changed since the last transition, rather than a canned sentence per
    state pair."""
    if old_state == new_state:
        return f"Confidence re-assessed at {confidence.final_score:.2f}; state unchanged ({new_state})."

    parts = [f"score {confidence.final_score:.2f}"]
    if new_evidence_keys:
        groups = sorted({g for g, _ in new_evidence_keys})
        parts.append(f"new/changed evidence in: {', '.join(groups)}")
    parts.append(f"breadth={confidence.signal_breadth:.2f}")
    parts.append(f"persistence={confidence.temporal_persistence:.2f}")
    parts.append(f"balance={confidence.evidence_balance:.2f}")
    if confidence.n_missing:
        parts.append(f"{confidence.n_missing} missing-evidence item(s)")
    return f"{old_state} -> {new_state}: " + "; ".join(parts)


def transition(day: int, old_state: str, confidence: ConfidenceBreakdown,
               new_evidence_keys: list, force_resolve: bool = False,
               resolve_reason: str = "") -> StateTransition:
    """Computes the next state and returns a fully-populated StateTransition
    (task brief step 4's required fields: old state, new state, triggering
    evidence, day, reason, confidence, actor).

    RESOLVED is terminal - once old_state == "RESOLVED", this always
    returns another RESOLVED transition with no change (never reopens an
    episode from confidence alone)."""
    if old_state == "RESOLVED":
        return StateTransition(day=day, old_state="RESOLVED", new_state="RESOLVED",
                                reason="Episode already resolved - immutable.",
                                confidence=confidence.final_score, evidence_keys=[])

    if force_resolve:
        new_state = "RESOLVED"
        reason = resolve_reason or f"Episode formally closed at day {day}."
        return StateTransition(day=day, old_state=old_state, new_state=new_state,
                                reason=reason, confidence=confidence.final_score,
                                evidence_keys=new_evidence_keys)

    new_state = status_for_confidence(confidence)
    reason = explain_transition(old_state, new_state, confidence, new_evidence_keys)
    return StateTransition(day=day, old_state=old_state, new_state=new_state,
                            reason=reason, confidence=confidence.final_score,
                            evidence_keys=new_evidence_keys)
