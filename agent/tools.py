"""
Investigation tools (Phase 4) — task brief step 3.

Every tool wraps EXISTING deterministic investigation logic
(episode.aggregation.build_episode_signal_evidence, which has been
producing trigger/contextual/historical/contradicting/missing evidence
since Phase 3) rather than reimplementing it. Tools do not compute
anything new statistically - they select which already-defined signal
group(s) to look at and package the result with a stable evidence_id via
agent.evidence.EvidenceRegistry.

Each tool has a strict typed interface: name, description, an input
schema (ToolContext - just the context it needs), an output schema
(ToolResult - status + structured AgentEvidence list, never prose as the
primary result), and execute(). No tool returns arbitrary text as its
result; `ToolResult.evidence` is the only thing a caller should trust as
fact.

merchant_context is a deliberately thin tool: the synthetic dataset (see
data/synthetic_generator.py) has NO onboarding/KYC/business-registration
fields - only observable behavioral aggregates (dominant_category,
dominant_geo) and the detector's own derived columns. This tool surfaces
exactly that and nothing more. It deliberately does NOT read `archetype`
or `drift_kind` from scored_history - those are ground-truth labels used
only for evaluation and would be a direct leakage channel into the
"investigation" if a tool used them. Real onboarding-profile investigation
is out of scope until a real KYC dataset exists (task brief step 3's
explicit "document as future work instead of fabricating").
"""
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from episode.aggregation import build_episode_signal_evidence
from agents.evidence import Evidence as CoreEvidence
from agent.evidence import AgentEvidence, EvidenceRegistry
from agent.models import ToolStatus, FailureReason

# Columns that exist ONLY for evaluation/ground-truth purposes and must
# NEVER be read by any tool - reading them would be investigation-time
# label leakage, not a real signal a production system would have.
GROUND_TRUTH_ONLY_COLUMNS = {"archetype", "drift_kind", "true_drift", "true_drift_any"}


@dataclass
class ToolContext:
    """The ONLY input every tool receives - task brief step 3's "input
    schema." Deliberately narrow: a tool gets the scored history slice and
    the episode window, nothing else (no direct database/network access,
    no free-form text)."""
    scored_history: pd.DataFrame
    episode_start: int
    as_of_day: int
    registry: EvidenceRegistry
    simulate_failure: Optional[FailureReason] = None  # test-only hook, see agent/failures.py


@dataclass
class ToolResult:
    """The ONLY output every tool produces - task brief step 3's "output
    schema." status/failure_reason are always present; evidence is only
    populated on SUCCESS."""
    tool_name: str
    status: ToolStatus
    evidence: list = field(default_factory=list)   # list[AgentEvidence]
    failure_reason: Optional[FailureReason] = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name, "status": self.status.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
            "detail": self.detail,
        }


class InvestigationTool:
    name: str = "base_tool"
    description: str = ""
    signal_groups: tuple = ()

    def execute(self, context: ToolContext) -> ToolResult:
        if context.simulate_failure is not None:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=context.simulate_failure,
                               detail=f"Simulated failure for testing: {context.simulate_failure.value}")
        try:
            core_evidence = []
            for group in self.signal_groups:
                core_evidence.extend(build_episode_signal_evidence(
                    context.scored_history, context.episode_start, context.as_of_day, group))
        except Exception as exc:  # noqa: BLE001 - deliberately broad, this IS the safety boundary
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=FailureReason.TOOL_EXCEPTION,
                               detail=f"{type(exc).__name__}: {exc}")

        # BUGFIX (found via direct testing during this phase): build_episode_signal_evidence
        # always includes a "historical" entry alongside trigger/contextual/contradicting
        # for whatever group(s) it's asked about. If transaction_behavior/refund_dispute_
        # behavior/mix_behavior all kept their own historical entries AND
        # historical_context separately recomputed historical for every group, the SAME
        # historical fact would be counted twice when multiple tools run in one
        # investigation - directly inflating SEASONAL_PATTERN's score via duplicate
        # evidence (exactly the failure mode episode/aggregation.py was designed to avoid
        # at the deterministic layer - see docs/EPISODE_EVIDENCE.md). historical_context is
        # the SOLE source of "historical" evidence; every other tool strips it out.
        core_evidence = [ce for ce in core_evidence if ce.evidence_type != "historical"]

        if not core_evidence:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=FailureReason.NO_EVIDENCE,
                               detail="No evidence could be produced for this signal group.")

        wrapped = [context.registry.register(ce, source_tool=self.name) for ce in core_evidence]
        return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS, evidence=wrapped)


class TransactionBehaviorTool(InvestigationTool):
    name = "transaction_behavior"
    description = "Investigates transaction volume/count anomaly trajectory for the episode."
    signal_groups = ("volume",)


class RefundDisputeBehaviorTool(InvestigationTool):
    name = "refund_dispute_behavior"
    description = "Investigates refund rate and dispute rate behavior, including temporal persistence."
    signal_groups = ("refund", "dispute")


class MixBehaviorTool(InvestigationTool):
    name = "mix_behavior"
    description = "Investigates category-mix and geography-mix concentration/diversity shifts."
    signal_groups = ("category_mix", "geo_mix")


class HistoricalContextTool(InvestigationTool):
    """The SOLE source of 'historical' evidence type (see base
    InvestigationTool.execute's bugfix note) - reuses the same
    build_episode_signal_evidence call as the other tools, but keeps ONLY
    the historical entries rather than stripping them."""
    name = "historical_context"
    description = ("Investigates whether this merchant's own prior history shows this deviation "
                    "pattern before (novelty vs. an established, possibly seasonal, pattern).")
    signal_groups = ("volume", "refund", "dispute", "category_mix", "geo_mix")

    def execute(self, context: ToolContext) -> ToolResult:
        if context.simulate_failure is not None:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=context.simulate_failure,
                               detail=f"Simulated failure for testing: {context.simulate_failure.value}")
        try:
            core_evidence = []
            for group in self.signal_groups:
                core_evidence.extend(build_episode_signal_evidence(
                    context.scored_history, context.episode_start, context.as_of_day, group))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=FailureReason.TOOL_EXCEPTION,
                               detail=f"{type(exc).__name__}: {exc}")

        historical_only = [ce for ce in core_evidence if ce.evidence_type == "historical"]
        if not historical_only:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=FailureReason.NO_EVIDENCE,
                               detail="No historical evidence available (insufficient baseline).")
        wrapped = [context.registry.register(ce, source_tool=self.name) for ce in historical_only]
        return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS, evidence=wrapped)


class MerchantContextTool(InvestigationTool):
    """See module docstring: deliberately thin. Only reads
    dominant_category/dominant_geo (observable behavioral aggregates
    already computed by the detector), never archetype/drift_kind (ground
    truth labels - would be leakage)."""
    name = "merchant_context"
    description = ("Surfaces the merchant's observable behavioral profile (dominant category, "
                    "dominant geography) as context - NOT onboarding/KYC data, which does not "
                    "exist in this dataset (documented limitation, not fabricated).")
    signal_groups = ()

    def execute(self, context: ToolContext) -> ToolResult:
        if context.simulate_failure is not None:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=context.simulate_failure,
                               detail=f"Simulated failure for testing: {context.simulate_failure.value}")
        row = context.scored_history[context.scored_history["day"] == context.as_of_day]
        if row.empty:
            return ToolResult(tool_name=self.name, status=ToolStatus.FAILURE,
                               failure_reason=FailureReason.MISSING_DATA,
                               detail=f"No row for day {context.as_of_day}.")
        row = row.iloc[0]
        core = CoreEvidence(
            source="Merchant Context Tool", signal_group="profile", evidence_type="contextual",
            observation=None, baseline=None, deviation=None,
            time_window=f"as of day {context.as_of_day}", direction="n/a", strength="n/a",
            supports_hypothesis=None, contradicts_hypothesis=None, confidence=0.3,
            summary=(f"Merchant's dominant category is '{row['dominant_category']}' and dominant "
                     f"geography is '{row['dominant_geo']}' as of day {context.as_of_day}. "
                     f"No onboarding/KYC/business-registration data exists in this dataset - "
                     f"this is observable behavioral profile only, not verified business context."),
        )
        wrapped = context.registry.register(core, source_tool=self.name)
        return ToolResult(tool_name=self.name, status=ToolStatus.SUCCESS, evidence=[wrapped])


ALL_TOOLS: dict = {
    t.name: t for t in [
        TransactionBehaviorTool(), RefundDisputeBehaviorTool(), MixBehaviorTool(),
        HistoricalContextTool(), MerchantContextTool(),
    ]
}
