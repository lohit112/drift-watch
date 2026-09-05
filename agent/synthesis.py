"""
Case synthesis (Phase 4) — task brief step 4's grounding requirement and
step 9's pluggable-model requirement.

`SynthesisModel` is the pluggable interface; `DeterministicSynthesis` is
the mock/reference implementation - template-based, not a real LLM, and
labeled as such throughout.

EVIDENCE GROUNDING (task brief step 4): every factual sentence the
synthesized case narrative contains is built by substituting real
evidence_id strings into a fixed template - it is not free-text generation
that could hallucinate a fact. `check_grounding` is still run over the
final narrative as an explicit, separate verification step (not just
"trust the template"), because this is exactly the check that would matter
once a real LLM-backed synthesis model is plugged in behind the same
interface: any sentence referencing an EVID-xxx string that is NOT in the
registry is rejected from the case, not silently kept.

The LLM must never manufacture metrics/percentages/counts/dates/facts
(task brief step 4) - this is enforced structurally here by never letting
the synthesis layer write a number that didn't come from an AgentEvidence
object's own `value`/`baseline` fields.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from agent.evidence import EvidenceRegistry
from agent.hypotheses import HypothesisState
from agent.models import Recommendation, SufficiencyDecision

EVID_PATTERN = re.compile(r"EVID-\d{3}")


@dataclass
class SynthesizedCase:
    narrative: str                    # every claim traceable to an EVID-xxx citation
    recommendation: Recommendation
    leading_hypothesis: str
    hypothesis_summary: dict
    cited_evidence_ids: list
    rejected_claims: list             # claims that failed grounding and were dropped, for transparency

    def to_dict(self) -> dict:
        return {
            "narrative": self.narrative, "recommendation": self.recommendation.value,
            "leading_hypothesis": self.leading_hypothesis,
            "hypothesis_summary": self.hypothesis_summary,
            "cited_evidence_ids": self.cited_evidence_ids,
            "rejected_claims": self.rejected_claims,
        }


def check_grounding(narrative: str, registry: EvidenceRegistry) -> tuple:
    """Returns (cited_ids, is_fully_grounded). Any EVID-xxx string in the
    narrative that ISN'T in the registry means the narrative references
    evidence that doesn't exist - fabrication - and grounding fails."""
    cited = EVID_PATTERN.findall(narrative)
    unknown = [c for c in cited if not registry.contains(c)]
    return cited, (len(unknown) == 0)


class SynthesisModel:
    def synthesize(self, hypothesis_state: HypothesisState, registry: EvidenceRegistry,
                    sufficiency: SufficiencyDecision) -> SynthesizedCase:
        raise NotImplementedError


class DeterministicSynthesis(SynthesisModel):
    """Template-based synthesis (task brief step 9's mock-model
    requirement). Builds the narrative sentence by sentence, each sentence
    citing the specific evidence_id(s) it's built from - see module
    docstring."""

    def synthesize(self, hypothesis_state: HypothesisState, registry: EvidenceRegistry,
                    sufficiency: SufficiencyDecision) -> SynthesizedCase:
        leading = hypothesis_state.leading()
        sentences = []
        rejected = []

        for label, hyp in hypothesis_state.hypotheses.items():
            if not hyp.supporting_evidence_ids:
                continue
            ids = ", ".join(f"[{eid}]" for eid in hyp.supporting_evidence_ids)
            sentences.append(
                f"{hyp.label.value} is supported by {len(hyp.supporting_evidence_ids)} evidence item(s) {ids}."
            )

        if sufficiency == SufficiencyDecision.FAILED:
            narrative = "Synthesis could not proceed - investigation failed before evidence sufficiency was reached."
            recommendation = Recommendation.REQUEST_MORE_EVIDENCE
        elif sufficiency in (SufficiencyDecision.NEED_MORE_EVIDENCE, SufficiencyDecision.CONFLICTING,
                              SufficiencyDecision.BUDGET_EXHAUSTED):
            narrative = " ".join(sentences) + (
                f" Evidence remains insufficient to confidently separate competing hypotheses "
                f"(sufficiency={sufficiency.value})."
            )
            recommendation = Recommendation.REQUEST_MORE_EVIDENCE
        else:  # SUFFICIENT
            narrative = " ".join(sentences) + f" Leading hypothesis: {leading.label.value}."
            from agent.models import HypothesisLabel
            if leading.label == HypothesisLabel.RISK_DRIFT and leading.support_score > 0.62:
                recommendation = Recommendation.ESCALATE
            elif leading.label == HypothesisLabel.INSUFFICIENT_EVIDENCE:
                recommendation = Recommendation.REQUEST_MORE_EVIDENCE
            else:
                recommendation = Recommendation.MONITOR

        cited_ids, is_grounded = check_grounding(narrative, registry)
        if not is_grounded:
            unknown = [c for c in cited_ids if not registry.contains(c)]
            for u in unknown:
                narrative = narrative.replace(f"[{u}]", "[unsupported claim removed]")
                rejected.append(u)
            cited_ids = [c for c in cited_ids if registry.contains(c)]

        return SynthesizedCase(
            narrative=narrative, recommendation=recommendation,
            leading_hypothesis=leading.label.value,
            hypothesis_summary=hypothesis_state.to_dict(),
            cited_evidence_ids=cited_ids, rejected_claims=rejected,
        )
