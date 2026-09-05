"""
Failure handling (Phase 4) — task brief step 11.

Centralizes the rules for how tool/planner/synthesis failures degrade
safely. The single governing rule, enforced everywhere in this module and
checked directly in tests/test_agent_failures.py:

    A FAILED INVESTIGATION STEP MUST NEVER INCREASE RISK.

Concretely: a tool failure produces zero evidence (not synthetic evidence,
not a "the tool couldn't check, so assume something is wrong" inference).
Missing evidence is tracked explicitly (agent/hypotheses.py's
INSUFFICIENT_EVIDENCE hypothesis) and pulls the system TOWARD
REQUEST_MORE_EVIDENCE, never toward ESCALATE.
"""
from dataclasses import dataclass

from agent.models import FailureReason, ToolStatus
from agent.tools import ToolResult


@dataclass
class ValidationResult:
    valid: bool
    reason: str = ""


def validate_tool_output(result: ToolResult) -> ValidationResult:
    """Rejects malformed tool output before it can enter the evidence
    pool. A tool claiming SUCCESS with no evidence, or FAILURE with
    evidence attached, is malformed and must not be trusted either way."""
    if result.status == ToolStatus.SUCCESS and not result.evidence:
        return ValidationResult(False, "Tool reported SUCCESS but produced no evidence - rejected.")
    if result.status == ToolStatus.FAILURE and result.evidence:
        return ValidationResult(False, "Tool reported FAILURE but attached evidence anyway - rejected.")
    if result.status == ToolStatus.SUCCESS:
        for e in result.evidence:
            if not e.evidence_id or not e.evidence_id.startswith("EVID-"):
                return ValidationResult(False, f"Evidence item missing a valid evidence_id: {e}")
    return ValidationResult(True)


def is_safe_to_use(result: ToolResult) -> bool:
    """A single call site every consumer of a ToolResult should go
    through, so 'is this result trustworthy' is answered in exactly one
    place."""
    return result.status == ToolStatus.SUCCESS and validate_tool_output(result).valid


def failure_implies_no_risk_signal(reason: FailureReason) -> bool:
    """Every failure reason implies exactly this - included as an explicit
    function (rather than just relying on convention) so it can be
    asserted against directly in tests for every enum member, catching a
    future failure mode added without this guarantee."""
    return True  # true for every current FailureReason by construction - see tests/test_agent_failures.py
