"""
Episode model — task brief step 2.

A RiskEpisode is the primary object of Phase 2 (episode intelligence): a
continuous/related period of behavioral drift for one merchant, tracked
over time rather than re-assessed independently on every flagged day.

Design choices, stated up front so they can be checked against the code:

- confidence_history is APPEND-ONLY: every day the episode is updated, a
  new (day, score, status) point is appended. Nothing is ever overwritten
  or deleted (invariant 3: future observations cannot affect earlier
  state - see tests/test_episode_invariants.py).
- evidence_timeline is also APPEND-ONLY, but deliberately NOT one entry per
  day per signal group (that would just be daily evidence spam and defeats
  the deduplication requirement in task brief step 7). An entry is added
  only when something actually CHANGES: a signal group's evidence newly
  appears, a persistence duty-cycle crosses the "sustained" threshold, or
  contradicting evidence appears/disappears. See episode/aggregation.py
  for the diffing logic that decides what counts as a change.
- transition_log is the authoritative explainability record (task brief
  step 20): every state change carries old_state, new_state, day, reason,
  confidence, and the evidence keys that drove it.
"""
from dataclasses import dataclass, field
from typing import Optional

# Episode states - task brief step 4's suggested machine, kept as-is because
# it matched the data well once implemented (see docs/STATE_MACHINE.md for
# why each transition is defined the way it is).
STATES = ("WATCH", "INVESTIGATING", "ESCALATE", "RESOLVED")


@dataclass
class StateTransition:
    day: int
    old_state: Optional[str]
    new_state: str
    reason: str
    confidence: float
    evidence_keys: list          # (signal_group, evidence_type) keys that drove this transition
    actor: str = "state_machine"


@dataclass
class RiskEpisode:
    episode_id: str
    merchant_id: str
    start_day: int
    current_day: int
    end_day: Optional[int]              # set only once RESOLVED
    status: str                          # one of STATES
    trigger_events: list                 # days where the detector first flagged something
    signal_groups: set                   # every independent group that has EVER deviated in this episode
    peak_day: Optional[int]
    peak_score: float
    confidence_history: list             # append-only [(day, score, status), ...]
    evidence_timeline: list              # append-only [{day, signal_group, evidence_type, change, summary}, ...]
    supporting_evidence: list            # current (latest) Evidence objects supporting Hypothesis A
    contradicting_evidence: list         # current Evidence objects supporting Hypothesis B
    missing_evidence: list               # current Evidence objects of type "missing"
    hypothesis_a: str
    hypothesis_b: str
    recommended_action: str
    transition_log: list = field(default_factory=list)
    resolution: Optional[dict] = None    # {"day": int, "outcome": str, "reason": str} once RESOLVED

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "merchant_id": self.merchant_id,
            "start_day": self.start_day,
            "current_day": self.current_day,
            "end_day": self.end_day,
            "status": self.status,
            "trigger_events": self.trigger_events,
            "signal_groups": sorted(self.signal_groups),
            "peak_day": self.peak_day,
            "peak_score": round(self.peak_score, 3) if self.peak_score is not None else None,
            "confidence_history": [(d, round(s, 3), st) for d, s, st in self.confidence_history],
            "evidence_timeline": self.evidence_timeline,
            "supporting_evidence": [e.summary for e in self.supporting_evidence],
            "contradicting_evidence": [e.summary for e in self.contradicting_evidence],
            "missing_evidence": [e.summary for e in self.missing_evidence],
            "hypothesis_a": self.hypothesis_a,
            "hypothesis_b": self.hypothesis_b,
            "recommended_action": self.recommended_action,
            "transition_log": [t.__dict__ for t in self.transition_log],
            "resolution": self.resolution,
        }
