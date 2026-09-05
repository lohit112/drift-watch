"""
Investigation planner (Phase 4) — task brief step 6.

`PlannerModel` is the pluggable interface (task brief step 9): a real LLM
planner could implement this later without any other agent-layer code
changing. `DeterministicPlanner` is the mock/reference implementation used
throughout this phase - explicitly labeled as deterministic/mock per the
task brief's instruction not to fake an LLM.

DESIGN PRINCIPLE (task brief's explicit warning): this planner is
EVIDENCE-SEEKING, not RISK-CONFIRMING. It never selects a tool because
that tool is likely to produce risk-supporting evidence. Its actual
priority order:

1. Investigate whichever of the episode's OWN deviant signal groups
   (`RiskEpisode.signal_groups`, from Phase 3) haven't been looked at yet -
   this is "what triggered the alert," which must be understood before
   anything else, regardless of which hypothesis it might end up
   supporting.
2. Once every deviant group has a tool result, disambiguate RISK_DRIFT vs.
   SEASONAL_PATTERN specifically by calling historical_context - this is
   the single most useful question once "what's happening now" is known
   ("has this happened before"), and it does NOT run before step 1's
   questions are resolved (unlike a fixed pipeline that always runs every
   investigator).
3. merchant_context is lowest priority - it never resolves a hypothesis by
   itself (see agent/tools.py's documented limitation: no real onboarding
   data exists), so it is only selected once everything else has been
   exhausted and the budget allows.
4. Stop as soon as either (a) the hypotheses are no longer ambiguous, or
   (b) there is nothing left to investigate. (The loop's own sufficiency
   rule, agent/loop.py::evaluate_sufficiency, independently refuses to
   declare SUFFICIENT while any signal group still lacks episode-window
   evidence - the planner's stop and the loop's sufficiency are
   deliberately separate checks.)

This priority order NEVER depends on which hypothesis is currently
leading, or on whether RISK_DRIFT's score is high or low - only on which
signal groups are relevant and which questions remain open. That is what
makes it evidence-seeking rather than risk-confirming, and it's checked
directly in tests/test_agent_planner_and_loop.py. An earlier version
gated the historical_context call behind the current partial-pool
hypothesis scores (escalating-score -> skip); that was found to be a
genuine bug during this phase's own testing and removed - see the
historical_context branch below and PHASE_4_FINAL.md.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from agent.hypotheses import HypothesisState
from agent.models import InvestigationBudget
from episode.model import RiskEpisode

# Which tool addresses which of the episode's own deviant signal groups.
# volume -> transaction_behavior, refund/dispute -> refund_dispute_behavior,
# category_mix/geo_mix -> mix_behavior. Order matters: it's the fixed,
# documented priority a deterministic planner uses when multiple groups are
# simultaneously relevant, chosen to match the signal_taxonomy.py group
# ordering already used throughout the project (no separate ordering
# invented for this phase).
GROUP_TO_TOOL = {
    "volume": "transaction_behavior",
    "refund": "refund_dispute_behavior",
    "dispute": "refund_dispute_behavior",
    "category_mix": "mix_behavior",
    "geo_mix": "mix_behavior",
}


@dataclass
class PlannerContext:
    episode: RiskEpisode
    hypothesis_state: HypothesisState
    tools_called: list          # tool names already executed this investigation
    available_tools: list       # tool names the planner is permitted to select from
    budget: InvestigationBudget


@dataclass
class InvestigationPlan:
    reason: str
    selected_tool: Optional[str]     # None means "stop, no further investigation needed"
    question: str
    stop: bool = False

    def to_dict(self) -> dict:
        return {"reason": self.reason, "selected_tool": self.selected_tool,
                "question": self.question, "stop": self.stop}


class PlannerModel(ABC):
    """Pluggable interface - task brief step 9. A real LLM-backed planner
    would implement `plan()` and could be swapped in without touching
    agent/loop.py."""

    @abstractmethod
    def plan(self, context: PlannerContext) -> InvestigationPlan:
        raise NotImplementedError


class DeterministicPlanner(PlannerModel):
    """Deterministic/mock planner (task brief step 9's explicit
    requirement to label mock implementations clearly). Rule-based, not an
    LLM - see module docstring for the exact priority order and why it's
    evidence-seeking rather than risk-confirming."""

    def plan(self, context: PlannerContext) -> InvestigationPlan:
        deviant_groups = sorted(context.episode.signal_groups)
        relevant_tools_for_trigger = []
        for group in deviant_groups:
            tool = GROUP_TO_TOOL.get(group)
            if tool and tool not in relevant_tools_for_trigger:
                relevant_tools_for_trigger.append(tool)
        # Fixed, documented order (not hypothesis-dependent):
        ordered_trigger_tools = [t for t in ("transaction_behavior", "refund_dispute_behavior", "mix_behavior")
                                  if t in relevant_tools_for_trigger]

        for tool in ordered_trigger_tools:
            if tool in context.available_tools and tool not in context.tools_called:
                group_names = [g for g in deviant_groups if GROUP_TO_TOOL.get(g) == tool]
                return InvestigationPlan(
                    reason=(f"Signal group(s) {group_names} triggered this episode and haven't been "
                            f"investigated yet - understanding the trigger comes before anything else."),
                    selected_tool=tool,
                    question=f"What does {tool} show for the triggering signal group(s) {group_names}?",
                )

        if "historical_context" in context.available_tools and "historical_context" not in context.tools_called:
            return InvestigationPlan(
                reason=("All triggering signal groups have been investigated - historical context is "
                        "the single most useful next question: it tells a fresh risk signal from a "
                        "recurring pattern, and gives the competing hypotheses (SEASONAL_PATTERN, and "
                        "RISK_DRIFT's novelty component) their evidence before any conclusion is drawn. "
                        "It is asked BEFORE looking at the current hypothesis scores: a score computed "
                        "over a pool where the competing hypotheses were never given any evidence is "
                        "not a basis for skipping the one question that could change it (found and "
                        "fixed during this phase's own testing - the earlier score-gated version let a "
                        "partial-pool RISK_DRIFT lead of 0.708 skip this question entirely and escalate "
                        "a genuinely conflicting refund-up/dispute-down episode that the deterministic "
                        "layer, with all 5 groups investigated, correctly held at REQUEST_MORE_EVIDENCE)."),
                selected_tool="historical_context",
                question="Has this merchant shown this deviation pattern before?",
            )

        if ("merchant_context" in context.available_tools
                and "merchant_context" not in context.tools_called
                and context.hypothesis_state.is_ambiguous()
                and context.budget.can_call_tool()):
            return InvestigationPlan(
                reason="Still ambiguous after historical context - checking observable merchant profile as a last resort.",
                selected_tool="merchant_context",
                question="What is this merchant's observable behavioral profile?",
            )

        if not context.hypothesis_state.is_ambiguous():
            return InvestigationPlan(
                reason=(f"Hypotheses are no longer ambiguous - {context.hypothesis_state.leading().label.value} "
                        f"leads with sufficient separation."),
                selected_tool=None, question="", stop=True,
            )

        return InvestigationPlan(
            reason="No further relevant tools remain to investigate, despite residual ambiguity.",
            selected_tool=None, question="", stop=True,
        )
