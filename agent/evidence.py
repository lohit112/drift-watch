"""
Agent evidence model (Phase 4) — task brief step 4.

Deliberately NOT a new evidence architecture. Every AgentEvidence wraps an
existing `agents.evidence.Evidence` object (the same typed evidence model
used by the deterministic investigators and episode aggregation since
Phase 2/3) and adds exactly what's new for the agent layer: a stable
unique ID and an EvidenceRegistry that makes traceability a structural
guarantee rather than a convention.

Every factual claim the synthesis layer (agent/synthesis.py) makes MUST
cite an evidence_id from this registry - see synthesis.py's grounding
check. If a claim can't be traced to a registered evidence_id, it is
rejected before it reaches the final case, not merely flagged.
"""
from dataclasses import dataclass
from typing import Optional

from agents.evidence import Evidence as CoreEvidence


@dataclass
class AgentEvidence:
    evidence_id: str                # "EVID-001", "EVID-002", ... - stable, unique, sequential
    source_tool: str                # e.g. "refund_dispute_behavior"
    signal_group: str
    metric: str                     # the underlying feature name, e.g. "refund_rate"
    value: Optional[float]          # same as core.observation
    baseline: Optional[float]
    deviation: Optional[float]      # z-score / deviation magnitude, same as core.deviation - NEEDED for
                                     # agents.confidence.compute_confidence's anomaly_strength component
                                     # (a Phase 4 bug found via testing: omitting this field silently
                                     # zeroed out anomaly_strength for every reconstructed hypothesis
                                     # score - see agent/hypotheses.py::_to_core_evidence)
    time_window: str
    evidence_type: str              # trigger / contextual / historical / contradicting / missing
    interpretation: str             # human-readable, == core.summary (never re-authored/embellished)
    reliability: float              # == core.confidence (the evidence item's own reliability)
    status: str                     # "verified" - always, since it's built from computed evidence,
                                     # never from unvalidated tool output (see agent/failures.py)
    supports_hypothesis: Optional[str]     # "A"/"B"/None, from the underlying core evidence
    contradicts_hypothesis: Optional[str]

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class EvidenceRegistry:
    """Assigns stable, sequential, unique evidence IDs and is the single
    source of truth an investigation can check a claim against. One
    registry per investigation (not global/shared state - see
    agent/loop.py, a fresh registry is created per InvestigationLoop run)."""

    def __init__(self):
        self._next_id = 1
        self._by_id: dict[str, AgentEvidence] = {}

    def register(self, core_evidence: CoreEvidence, source_tool: str) -> AgentEvidence:
        evidence_id = f"EVID-{self._next_id:03d}"
        self._next_id += 1
        metric = _infer_metric(core_evidence)
        wrapped = AgentEvidence(
            evidence_id=evidence_id, source_tool=source_tool,
            signal_group=core_evidence.signal_group, metric=metric,
            value=core_evidence.observation, baseline=core_evidence.baseline,
            deviation=core_evidence.deviation,
            time_window=core_evidence.time_window, evidence_type=core_evidence.evidence_type,
            interpretation=core_evidence.summary, reliability=core_evidence.confidence,
            status="verified",
            supports_hypothesis=core_evidence.supports_hypothesis,
            contradicts_hypothesis=core_evidence.contradicts_hypothesis,
        )
        self._by_id[evidence_id] = wrapped
        return wrapped

    def get(self, evidence_id: str) -> Optional[AgentEvidence]:
        return self._by_id.get(evidence_id)

    def contains(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def all(self) -> list[AgentEvidence]:
        return list(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)


def _infer_metric(core_evidence: CoreEvidence) -> str:
    """The core Evidence model doesn't carry a raw feature-name field
    (it's implicit in how investigators.py/aggregation.py built it) - this
    maps signal_group back to the underlying metric name for display,
    matching detection/signal_taxonomy.py's SIGNAL_GROUPS -> primary feature
    convention used throughout agents/investigators.py."""
    mapping = {
        "volume": "txn_count", "refund": "refund_rate", "dispute": "dispute_rate",
        "category_mix": "category_entropy", "geo_mix": "geo_entropy",
    }
    return mapping.get(core_evidence.signal_group, core_evidence.signal_group)
