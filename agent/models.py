"""
Agent layer — core types (Phase 4).

This module holds only enums and small, dependency-free dataclasses shared
across the agent package, to avoid duplicate definitions scattered across
tools.py/planner.py/loop.py. Nothing here duplicates an existing Phase 1-3
abstraction: the underlying Evidence model, confidence formula, episode
model, and state machine are all REUSED from agents/ and episode/ (see
agent/evidence.py, agent/tools.py, agent/hypotheses.py for how).
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FailureReason(str, Enum):
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_EXCEPTION = "TOOL_EXCEPTION"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MISSING_DATA = "MISSING_DATA"
    NO_EVIDENCE = "NO_EVIDENCE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PLANNER_FAILURE = "PLANNER_FAILURE"
    SYNTHESIS_FAILURE = "SYNTHESIS_FAILURE"
    INVALID_TOOL_SELECTION = "INVALID_TOOL_SELECTION"


class ToolStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class SufficiencyDecision(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    NEED_MORE_EVIDENCE = "NEED_MORE_EVIDENCE"
    CONFLICTING = "CONFLICTING"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"


class Recommendation(str, Enum):
    MONITOR = "MONITOR"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    ESCALATE = "ESCALATE"


class ApprovalStatus(str, Enum):
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"
    APPROVED = "APPROVED"
    OVERRIDDEN = "OVERRIDDEN"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"


class HypothesisLabel(str, Enum):
    RISK_DRIFT = "RISK_DRIFT"
    LEGITIMATE_GROWTH = "LEGITIMATE_GROWTH"
    SEASONAL_PATTERN = "SEASONAL_PATTERN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class HypothesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    LEADING = "LEADING"


@dataclass
class InvestigationBudget:
    """Explicit limits (task brief step 8). No default is unlimited -
    every field here is a hard cap enforced by agent/loop.py."""
    max_iterations: int = 6
    max_tool_calls: int = 5
    tool_calls_used: int = 0
    iterations_used: int = 0
    per_tool_call_count: dict = field(default_factory=dict)

    def can_call_tool(self) -> bool:
        return self.tool_calls_used < self.max_tool_calls

    def can_iterate(self) -> bool:
        return self.iterations_used < self.max_iterations

    def record_tool_call(self, tool_name: str) -> None:
        self.tool_calls_used += 1
        self.per_tool_call_count[tool_name] = self.per_tool_call_count.get(tool_name, 0) + 1

    def record_iteration(self) -> None:
        self.iterations_used += 1

    def to_dict(self) -> dict:
        return {
            "max_iterations": self.max_iterations, "max_tool_calls": self.max_tool_calls,
            "tool_calls_used": self.tool_calls_used, "iterations_used": self.iterations_used,
            "per_tool_call_count": dict(self.per_tool_call_count),
        }


@dataclass
class InvestigationQuestion:
    """A single unresolved question the planner can choose to address.
    Deliberately plain data - the planner reasons over a list of these,
    it does not invent questions out of free text."""
    question_id: str
    text: str
    related_signal_group: Optional[str]
    related_hypothesis: Optional[str]
    resolved: bool = False


@dataclass
class ToolCallRecord:
    """One row of the audit trail's tool-call history - kept separately
    from the free-form audit event log (agent/audit.py) so tool-call
    efficiency metrics (task brief step 19) can be computed without
    re-parsing narrative text."""
    sequence: int
    tool_name: str
    question: str
    status: ToolStatus
    failure_reason: Optional[FailureReason]
    evidence_ids_produced: list
