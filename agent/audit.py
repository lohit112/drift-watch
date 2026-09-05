"""
Audit trail (Phase 4) — task brief step 14.

Deterministic sequence numbers, not timestamps, are the primary ordering
key (task brief's explicit preference, "for tests") - this makes audit
trails directly comparable across runs for reproducibility tests
(tests/test_agent_reproducibility.py) without needing to mock the clock.
A wall-clock timestamp is still recorded for realism but is never load-
bearing for ordering or test assertions.
"""
import datetime
from dataclasses import dataclass, field


@dataclass
class AuditEvent:
    sequence: int
    episode_id: str
    investigation_id: str
    event_type: str          # e.g. "planner_decision", "tool_call", "hypothesis_update", "recommendation", "approval"
    detail: dict
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))

    def to_dict(self) -> dict:
        return {"sequence": self.sequence, "episode_id": self.episode_id,
                "investigation_id": self.investigation_id, "event_type": self.event_type,
                "detail": self.detail, "timestamp": self.timestamp}


class AuditTrail:
    """One instance per investigation. Answers, by construction, every
    question task brief step 14 lists: what did the AI do (event_type +
    detail per step), why (planner_decision events carry `reason`), what
    evidence did it see (tool_call events carry evidence_ids), what
    changed its mind (hypothesis_update events carry before/after scores),
    why it recommended what it did (recommendation event carries the
    sufficiency decision and hypothesis snapshot), was human approval
    required (approval events)."""

    def __init__(self, episode_id: str, investigation_id: str):
        self.episode_id = episode_id
        self.investigation_id = investigation_id
        self._events: list = []
        self._next_seq = 1

    def record(self, event_type: str, detail: dict) -> AuditEvent:
        event = AuditEvent(sequence=self._next_seq, episode_id=self.episode_id,
                            investigation_id=self.investigation_id, event_type=event_type, detail=detail)
        self._next_seq += 1
        self._events.append(event)
        return event

    def events(self) -> list:
        return list(self._events)

    def count_by_type(self, event_type: str) -> int:
        return sum(1 for e in self._events if e.event_type == event_type)

    def to_dict(self) -> dict:
        return {"episode_id": self.episode_id, "investigation_id": self.investigation_id,
                "events": [e.to_dict() for e in self._events]}
