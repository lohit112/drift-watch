"""
Bounded investigation loop (Phase 4) — task brief step 7.

This is the ONLY place agentic decisions (planner tool selection) and
deterministic mechanics (tool execution, evidence registration, hypothesis
scoring, sufficiency evaluation) are wired together. The loop itself is
pure orchestration - it makes no risk judgments of its own; every actual
decision point is delegated to a named, testable component:

    "what to investigate next"     -> agent/planner.py (agentic)
    "did the tool actually work"   -> agent/failures.py (deterministic)
    "what does the evidence mean"  -> agent/hypotheses.py (deterministic,
                                       reuses agents.confidence unchanged)
    "do we have enough evidence"   -> evaluate_sufficiency() below (deterministic)
    "what's the final case"        -> agent/synthesis.py (agentic - but
                                       grounded, never fabricates)
    "was a human required"         -> agent/policy.py (deterministic, hard boundary)

THE LOOP ALWAYS TERMINATES: bounded by InvestigationBudget.max_iterations
AND max_tool_calls (task brief step 8), both hard caps checked every
iteration, independent of what the planner or hypotheses say. See
tests/test_agent_loop.py::test_loop_always_terminates for a planner that
never stops (broken planner) - still bounded by budget.
"""
from dataclasses import dataclass
from typing import Optional

from agent.audit import AuditTrail
from agent.evidence import EvidenceRegistry
from agent.failures import validate_tool_output
from agent.hypotheses import HypothesisState
from agent.models import (
    InvestigationBudget, SufficiencyDecision, FailureReason, ToolStatus,
    ApprovalStatus, ToolCallRecord,
)
from agent.planner import PlannerModel, PlannerContext, DeterministicPlanner, GROUP_TO_TOOL
from agent.policy import initial_approval_status
from agent.synthesis import SynthesisModel, DeterministicSynthesis
from agent.tools import ALL_TOOLS, ToolContext
from episode.model import RiskEpisode


@dataclass
class InvestigationResult:
    episode_id: str
    investigation_id: str
    hypothesis_state: HypothesisState
    registry: EvidenceRegistry
    audit_trail: AuditTrail
    tool_call_records: list
    sufficiency: SufficiencyDecision
    synthesized_case: object            # SynthesizedCase
    approval_status: ApprovalStatus
    budget: InvestigationBudget
    failure_reason: Optional[FailureReason] = None

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id, "investigation_id": self.investigation_id,
            "hypotheses": self.hypothesis_state.to_dict(),
            "evidence_count": len(self.registry),
            "tool_call_records": [
                {"sequence": t.sequence, "tool_name": t.tool_name, "question": t.question,
                 "status": t.status.value, "failure_reason": t.failure_reason.value if t.failure_reason else None,
                 "evidence_ids_produced": t.evidence_ids_produced}
                for t in self.tool_call_records
            ],
            "sufficiency": self.sufficiency.value,
            "case": self.synthesized_case.to_dict(),
            "approval_status": self.approval_status.value,
            "budget": self.budget.to_dict(),
            "failure_reason": self.failure_reason.value if self.failure_reason else None,
        }


def evaluate_sufficiency(hypothesis_state: HypothesisState, budget: InvestigationBudget,
                           planner_stopped: bool, any_tool_available: bool,
                           trigger_groups_covered: bool) -> SufficiencyDecision:
    """
    Deterministic sufficiency rule (task brief step 10 - explicitly NOT
    "N tools called = escalate"). Evaluated fresh after every tool call
    from the CURRENT hypothesis state, same "recompute rather than
    accumulate" principle used throughout this project (episode/aggregation.py,
    agent/hypotheses.py).

    - BUDGET_EXHAUSTED: the budget itself ran out, regardless of what the
      evidence shows - a hard cap, never overridden by confidence.
    - SUFFICIENT: hypotheses are no longer ambiguous AND the leading
      hypothesis isn't INSUFFICIENT_EVIDENCE itself AND every tool
      relevant to the episode's OWN triggering signal groups has actually
      been called (`trigger_groups_covered`). This last condition matters:
      without it, "not ambiguous" is trivially true the moment ANY evidence
      supports one hypothesis while the other two sit at their untouched
      default of 0.0 - that's an artifact of nothing having been checked
      yet, not genuine sufficiency (found and fixed during this phase's
      own testing - see docs/PHASE_4_ARCHITECTURE.md).
    - CONFLICTING: still ambiguous, but there is nothing left the planner
      could usefully investigate (planner voluntarily stopped due to
      exhausted relevant tools, not because it resolved anything).
    - NEED_MORE_EVIDENCE: still ambiguous, or trigger coverage is
      incomplete, and more relevant investigation is available and
      affordable.
    """
    if not budget.can_call_tool() or not budget.can_iterate():
        return SufficiencyDecision.BUDGET_EXHAUSTED

    leading = hypothesis_state.leading()
    from agent.models import HypothesisLabel
    if (trigger_groups_covered and not hypothesis_state.is_ambiguous()
            and leading.label != HypothesisLabel.INSUFFICIENT_EVIDENCE):
        return SufficiencyDecision.SUFFICIENT

    if planner_stopped and not any_tool_available:
        return SufficiencyDecision.CONFLICTING

    return SufficiencyDecision.NEED_MORE_EVIDENCE


class InvestigationLoop:
    def __init__(self, planner: PlannerModel = None, synthesis: SynthesisModel = None,
                  tools: dict = None, budget: InvestigationBudget = None):
        self.planner = planner or DeterministicPlanner()
        self.synthesis = synthesis or DeterministicSynthesis()
        self.tools = tools if tools is not None else ALL_TOOLS
        self.budget = budget or InvestigationBudget()

    def run(self, episode: RiskEpisode, scored_history) -> InvestigationResult:
        investigation_id = f"INV-{episode.episode_id}"
        audit = AuditTrail(episode_id=episode.episode_id, investigation_id=investigation_id)
        registry = EvidenceRegistry()
        hypothesis_state = HypothesisState()
        tool_call_records: list = []
        tools_called: list = []

        audit.record("investigation_started", {"episode_id": episode.episode_id,
                                                  "start_day": episode.start_day, "current_day": episode.current_day})

        # Step 3: load only the MISSING-evidence gaps already known from the
        # episode's own deterministic tracking (Phase 3) - genuine carried-
        # over knowledge that shouldn't need rediscovering. Deliberately
        # NOT pre-loading episode.supporting_evidence/contradicting_evidence:
        # those already reflect Phase 3's own FULL investigation of every
        # signal group as of the episode's current day, and pre-loading them
        # would make the agent's own tool calls redundant - there would be
        # nothing left to investigate, defeating the actual purpose of this
        # phase (see docs/PHASE_4_ARCHITECTURE.md "Why the loop doesn't
        # pre-load full episode evidence" for the concrete bug this fixes).
        # The planner instead uses episode.signal_groups directly (see
        # agent/planner.py) to know WHAT triggered, without already knowing
        # everything the deeper investigation would find.
        for core_ev in episode.missing_evidence:
            registry.register(core_ev, source_tool="episode_baseline")
        audit.record("loaded_episode_baseline_evidence", {
            "evidence_count": len(registry), "trigger_signal_groups": sorted(episode.signal_groups),
            "note": "only known missing-evidence gaps are pre-loaded; all other evidence is gathered by tool calls",
        })
        hypothesis_state.update(registry.all())

        failure_reason = None
        sufficiency = SufficiencyDecision.NEED_MORE_EVIDENCE

        def relevant_trigger_tools() -> set:
            return {GROUP_TO_TOOL[g] for g in episode.signal_groups if g in GROUP_TO_TOOL}

        def trigger_groups_covered() -> bool:
            return relevant_trigger_tools().issubset(set(tools_called))

        while True:
            if not self.budget.can_iterate():
                sufficiency = SufficiencyDecision.BUDGET_EXHAUSTED
                audit.record("budget_exhausted", {"reason": "max_iterations reached", **self.budget.to_dict()})
                break
            self.budget.record_iteration()

            available_tools = [name for name in self.tools if name not in tools_called]
            plan = self.planner.plan(PlannerContext(
                episode=episode, hypothesis_state=hypothesis_state, tools_called=tools_called,
                available_tools=list(self.tools.keys()), budget=self.budget,
            ))
            audit.record("planner_decision", plan.to_dict())

            if plan.stop or plan.selected_tool is None:
                sufficiency = evaluate_sufficiency(hypothesis_state, self.budget, planner_stopped=True,
                                                     any_tool_available=bool(available_tools),
                                                     trigger_groups_covered=trigger_groups_covered())
                break

            if plan.selected_tool not in self.tools:
                failure_reason = FailureReason.INVALID_TOOL_SELECTION
                sufficiency = SufficiencyDecision.FAILED
                audit.record("planner_failure", {"reason": "selected an unavailable tool",
                                                   "selected_tool": plan.selected_tool})
                break

            if not self.budget.can_call_tool():
                sufficiency = SufficiencyDecision.BUDGET_EXHAUSTED
                audit.record("budget_exhausted", {"reason": "max_tool_calls reached", **self.budget.to_dict()})
                break

            tool = self.tools[plan.selected_tool]
            context = ToolContext(scored_history=scored_history, episode_start=episode.start_day,
                                    as_of_day=episode.current_day, registry=registry)
            result = tool.execute(context)
            self.budget.record_tool_call(tool.name)
            tools_called.append(tool.name)

            valid = validate_tool_output(result)
            if result.status == ToolStatus.SUCCESS and valid.valid:
                evidence_ids = [e.evidence_id for e in result.evidence]
                audit.record("tool_call", {"tool": tool.name, "question": plan.question,
                                             "status": "SUCCESS", "evidence_ids": evidence_ids})
                tool_call_records.append(ToolCallRecord(
                    sequence=len(tool_call_records) + 1, tool_name=tool.name, question=plan.question,
                    status=ToolStatus.SUCCESS, failure_reason=None, evidence_ids_produced=evidence_ids,
                ))
                before = {l.value: h.support_score for l, h in hypothesis_state.hypotheses.items()}
                hypothesis_state.update(registry.all())
                after = {l.value: h.support_score for l, h in hypothesis_state.hypotheses.items()}
                audit.record("hypothesis_update", {"before": before, "after": after})
            else:
                reason = result.failure_reason or FailureReason.INVALID_OUTPUT
                audit.record("tool_call", {"tool": tool.name, "question": plan.question,
                                             "status": "FAILURE", "failure_reason": reason.value,
                                             "detail": result.detail or valid.reason})
                tool_call_records.append(ToolCallRecord(
                    sequence=len(tool_call_records) + 1, tool_name=tool.name, question=plan.question,
                    status=ToolStatus.FAILURE, failure_reason=reason, evidence_ids_produced=[],
                ))
                # RULE (task brief step 11): a failed tool call NEVER
                # becomes risk evidence and NEVER re-scores hypotheses -
                # deliberately no hypothesis_state.update() call here.

            available_tools = [name for name in self.tools if name not in tools_called]
            sufficiency = evaluate_sufficiency(hypothesis_state, self.budget, planner_stopped=False,
                                                 any_tool_available=bool(available_tools),
                                                 trigger_groups_covered=trigger_groups_covered())
            if sufficiency in (SufficiencyDecision.SUFFICIENT, SufficiencyDecision.CONFLICTING,
                                SufficiencyDecision.BUDGET_EXHAUSTED, SufficiencyDecision.FAILED):
                break

        try:
            case = self.synthesis.synthesize(hypothesis_state, registry, sufficiency)
        except Exception as exc:  # noqa: BLE001 - synthesis failure must not crash or fabricate
            failure_reason = FailureReason.SYNTHESIS_FAILURE
            sufficiency = SufficiencyDecision.FAILED
            from agent.synthesis import SynthesizedCase
            from agent.models import Recommendation
            case = SynthesizedCase(
                narrative=f"Synthesis failed ({type(exc).__name__}) - defaulting to REQUEST_MORE_EVIDENCE.",
                recommendation=Recommendation.REQUEST_MORE_EVIDENCE,
                leading_hypothesis="UNKNOWN", hypothesis_summary=hypothesis_state.to_dict(),
                cited_evidence_ids=[], rejected_claims=[],
            )
            audit.record("synthesis_failure", {"error": str(exc)})

        approval_status = initial_approval_status(case.recommendation)
        audit.record("recommendation", {"recommendation": case.recommendation.value, "sufficiency": sufficiency.value})
        audit.record("approval_required", {"approval_status": approval_status.value})

        return InvestigationResult(
            episode_id=episode.episode_id, investigation_id=investigation_id,
            hypothesis_state=hypothesis_state, registry=registry, audit_trail=audit,
            tool_call_records=tool_call_records, sufficiency=sufficiency, synthesized_case=case,
            approval_status=approval_status, budget=self.budget, failure_reason=failure_reason,
        )
