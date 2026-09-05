"""
Hypothesis model (Phase 4) — task brief step 5.

Four explicit, non-binary hypotheses. Reuses `agents.confidence.compute_confidence`
UNCHANGED for the RISK_DRIFT score (it already computes exactly "how much
does the evidence pool support Hypothesis A" from a list of core Evidence
objects - no need to reinvent that math). LEGITIMATE_GROWTH and
SEASONAL_PATTERN scores are both derived from Hypothesis-B-supporting
evidence, split by WHICH KIND of B-evidence it is:

- "contradicting" evidence (a signal group that simply never deviated) is
  generic, time-independent evidence for LEGITIMATE_GROWTH - it just says
  "less is happening than a risk episode would need."
- "historical" evidence indicating an established, recurring pattern for
  THIS merchant is more specific evidence for SEASONAL_PATTERN - it
  positively suggests a repeating cycle, not just an absence of suspicion.

This is a real, documented simplification (see docs/PHASE_4_ARCHITECTURE.md
"Hypothesis Model" for the full rationale and its limits) - it is NOT a
symmetric, independently-calibrated model for all four hypotheses, since
only RISK_DRIFT's score has the same rigor as Phase 2's confidence model.

INSUFFICIENT_EVIDENCE is not a residual bucket computed by subtraction -
it becomes the leading hypothesis specifically when MISSING evidence
exists, or when RISK_DRIFT/LEGITIMATE_GROWTH/SEASONAL_PATTERN are all too
close together to separate (see `HypothesisState.leading()`).
"""
from dataclasses import dataclass, field
from typing import Optional

from agents.confidence import compute_confidence
from agents.evidence import Evidence as CoreEvidence
from agent.evidence import AgentEvidence
from agent.models import HypothesisLabel, HypothesisStatus

AMBIGUOUS_MARGIN = 0.12  # if the top two scores are within this margin, treat as unresolved


@dataclass
class Hypothesis:
    hypothesis_id: str
    label: HypothesisLabel
    supporting_evidence_ids: list = field(default_factory=list)
    contradicting_evidence_ids: list = field(default_factory=list)
    support_score: float = 0.0
    unresolved_questions: list = field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.ACTIVE

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id, "label": self.label.value,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "support_score": round(self.support_score, 3),
            "unresolved_questions": list(self.unresolved_questions),
            "status": self.status.value,
        }


def _to_core_evidence(ae: AgentEvidence) -> CoreEvidence:
    """Reconstructs a core Evidence object from an AgentEvidence so
    agents.confidence.compute_confidence (which operates on core Evidence)
    can be reused unchanged. Lossless for every field compute_confidence
    actually reads."""
    return CoreEvidence(
        source=ae.source_tool, signal_group=ae.signal_group, evidence_type=ae.evidence_type,
        observation=ae.value, baseline=ae.baseline, deviation=ae.deviation, time_window=ae.time_window,
        direction="n/a", strength="n/a", supports_hypothesis=ae.supports_hypothesis,
        contradicts_hypothesis=ae.contradicts_hypothesis, confidence=ae.reliability,
        summary=ae.interpretation,
    )


class HypothesisState:
    """Tracks all 4 hypotheses across an investigation, updated as new
    AgentEvidence arrives. One instance per investigation (not shared
    state across episodes)."""

    def __init__(self):
        self.hypotheses: dict = {
            label: Hypothesis(hypothesis_id=f"HYP-{label.value}", label=label)
            for label in HypothesisLabel
        }

    def update(self, all_evidence: list) -> None:
        """Recomputes every hypothesis's score from the FULL evidence pool
        collected so far (not incrementally) - same "recompute fresh"
        design principle used by episode/aggregation.py, for the same
        reason: it guarantees two runs with identical evidence produce
        identical scores (determinism), and confidence can genuinely rise
        or fall as new evidence arrives without special-cased undo logic."""
        core_evidence = [_to_core_evidence(e) for e in all_evidence]
        n_missing = sum(1 for e in all_evidence if e.evidence_type == "missing")

        risk_conf = compute_confidence(core_evidence)
        self.hypotheses[HypothesisLabel.RISK_DRIFT].support_score = risk_conf.final_score
        self.hypotheses[HypothesisLabel.RISK_DRIFT].supporting_evidence_ids = [
            e.evidence_id for e in all_evidence if e.supports_hypothesis == "A"
        ]
        self.hypotheses[HypothesisLabel.RISK_DRIFT].contradicting_evidence_ids = [
            e.evidence_id for e in all_evidence if e.supports_hypothesis == "B"
        ]

        contradicting_b = [e for e in all_evidence if e.evidence_type == "contradicting" and e.supports_hypothesis == "B"]
        historical_b = [e for e in all_evidence if e.evidence_type == "historical" and e.supports_hypothesis == "B"]
        # Fixed denominator (5 = total independent signal groups, matching
        # detection/signal_taxonomy.py), NOT a dynamic count of however much
        # B-capable evidence happens to exist so far. A dynamic denominator
        # was tried first and found, via direct testing, to badly distort
        # early-investigation scores: before historical_context has been
        # called, a single quiet ("contradicting") signal group out of one
        # possible B-capable item would score LEGITIMATE_GROWTH at a full
        # 1.0 - the same small-sample distortion agents/confidence.py's
        # signal_breadth component was fixed to avoid in Phase 2, using the
        # identical fix (a fixed total, not a count of what's been
        # investigated so far).
        legit_score = len(contradicting_b) / 5

        # SEASONAL_PATTERN breadth discount: "this recurred before" is much
        # weaker evidence for a genuine seasonal pattern when EVERY signal
        # group is deviating simultaneously (breadth=1.0) than when only 1-2
        # groups move (breadth=0.2-0.4), because a real seasonal sales bump
        # (see data/synthetic_generator.py's "seasonal"/"seasonal_promo"
        # archetypes) typically moves volume+refund only, while a
        # coordinated multi-signal deviation is what a fraud episode looks
        # like (see the "fraud" archetype, which moves all 5 groups). This
        # matters in practice: a merchant can accumulate 3+ historical
        # z-threshold crossings on an UNRELATED feature purely by chance
        # over 100+ days (the exact mechanism documented in DECISIONS.md
        # D10, where a similar signal was tried as a standalone confidence
        # discount at the deterministic layer and reverted for breaking
        # real fraud detection). Requiring LOW breadth alongside historical
        # recurrence, rather than treating recurrence alone as sufficient,
        # is what keeps this hypothesis-layer signal from repeating that
        # mistake - a coordinated 5-group deviation with a few incidental
        # historical crossings should NOT out-score a fresh, high-breadth
        # risk signal.
        deviant_groups = {e.signal_group for e in all_evidence if e.evidence_type == "trigger"}
        breadth_ratio = len(deviant_groups) / 5
        seasonal_score = (len(historical_b) / 5) * (1 - breadth_ratio)

        self.hypotheses[HypothesisLabel.LEGITIMATE_GROWTH].support_score = legit_score
        self.hypotheses[HypothesisLabel.LEGITIMATE_GROWTH].supporting_evidence_ids = [e.evidence_id for e in contradicting_b]
        self.hypotheses[HypothesisLabel.SEASONAL_PATTERN].support_score = seasonal_score
        self.hypotheses[HypothesisLabel.SEASONAL_PATTERN].supporting_evidence_ids = [e.evidence_id for e in historical_b]

        # INSUFFICIENT_EVIDENCE score: proportional to how much of the
        # evidence pool is MISSING, and to how close the other three scores
        # are to each other (a genuinely ambiguous case IS evidence that
        # more investigation is warranted, not that any one hypothesis won).
        scores = [self.hypotheses[l].support_score for l in
                  (HypothesisLabel.RISK_DRIFT, HypothesisLabel.LEGITIMATE_GROWTH, HypothesisLabel.SEASONAL_PATTERN)]
        spread = max(scores) - sorted(scores)[-2] if len(scores) >= 2 else 1.0
        missing_ratio = n_missing / max(1, len(all_evidence))
        insufficient_score = max(missing_ratio, (AMBIGUOUS_MARGIN - spread) / AMBIGUOUS_MARGIN if spread < AMBIGUOUS_MARGIN else 0.0)
        self.hypotheses[HypothesisLabel.INSUFFICIENT_EVIDENCE].support_score = max(0.0, min(1.0, insufficient_score))
        self.hypotheses[HypothesisLabel.INSUFFICIENT_EVIDENCE].supporting_evidence_ids = [
            e.evidence_id for e in all_evidence if e.evidence_type == "missing"
        ]

        for h in self.hypotheses.values():
            h.status = HypothesisStatus.ACTIVE
        self.leading().status = HypothesisStatus.LEADING

    def leading(self) -> Hypothesis:
        return max(self.hypotheses.values(), key=lambda h: h.support_score)

    def is_ambiguous(self) -> bool:
        """True when the top two REAL hypotheses (excluding
        INSUFFICIENT_EVIDENCE, which is a symptom, not a competitor) are
        too close to call."""
        real = [self.hypotheses[l] for l in
                (HypothesisLabel.RISK_DRIFT, HypothesisLabel.LEGITIMATE_GROWTH, HypothesisLabel.SEASONAL_PATTERN)]
        scores = sorted((h.support_score for h in real), reverse=True)
        return (scores[0] - scores[1]) < AMBIGUOUS_MARGIN

    def to_dict(self) -> dict:
        return {label.value: h.to_dict() for label, h in self.hypotheses.items()}
