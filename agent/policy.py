"""
Policy / human approval boundary (Phase 4) — task brief steps 13 & 15.

HARD ARCHITECTURAL BOUNDARY: nothing in this codebase - not the planner,
not the synthesis layer, not the loop - has a function that executes a
consequential merchant action (suspend, restrict, contact, etc.). The
agent's only possible output is a `Recommendation` plus an `ApprovalStatus`
that always starts at `PENDING_HUMAN_REVIEW` for ESCALATE. There is no
code path, tested or untested, that transitions a recommendation directly
to an executed action - `record_human_decision` is the ONLY function that
changes approval status, and it requires an explicit external call
(standing in for a real human reviewer's action in a real system).

PROMPT-INJECTION TRUST BOUNDARY (task brief step 15): every merchant-
controlled field this system ever reads (dominant_category, dominant_geo)
comes from a FIXED, small categorical vocabulary defined in
data/synthetic_generator.py (CATEGORIES, GEOGRAPHIES) - there is no free-
text field anywhere in the pipeline for a merchant to inject instruction-
like text into. `sanitize_merchant_text` exists anyway, and is used by
MerchantContextTool, specifically so that IF a future real deployment adds
a free-text field (e.g. a merchant's self-reported business description),
the same defensive pattern is already in place: merchant-controlled text
is data to quote, never instructions to execute, and it plays no role in
tool selection or policy decisions regardless of its content.
HONESTLY STATED LIMITATION: this is not a claim of complete prompt-
injection immunity for a hypothetical future LLM-backed planner/synthesis
model - see docs/PHASE_4_ARCHITECTURE.md "Security" for what would still
need to be verified before a real LLM is plugged in.
"""
from dataclasses import dataclass

from agent.models import ApprovalStatus, Recommendation

MAX_SANITIZED_TEXT_LENGTH = 200


def sanitize_merchant_text(text: str) -> str:
    """Treats merchant-controlled text as inert DATA - truncates and
    strips it of anything that could be mistaken for a directive by a
    downstream template/LLM, and never returns it in a context where it
    could be interpreted as an instruction. Currently unused by any field
    that actually varies per-merchant with free text (see module
    docstring), but exercised directly by tests/test_agent_security.py to
    prove it neutralizes injection attempts if such a field existed."""
    import re
    if not isinstance(text, str):
        return ""
    truncated = text[:MAX_SANITIZED_TEXT_LENGTH]
    for marker in ("ignore previous instructions", "ignore all prior instructions",
                   "disregard the above", "system:", "you must", "override policy"):
        truncated = re.sub(re.escape(marker), "[redacted]", truncated, flags=re.IGNORECASE)
    return truncated


@dataclass
class HumanDecision:
    decision: str            # "APPROVE" | "OVERRIDE" | "REQUEST_MORE_EVIDENCE"
    reviewer_reason: str
    original_recommendation: Recommendation

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reviewer_reason": self.reviewer_reason,
                "original_recommendation": self.original_recommendation.value}


def initial_approval_status(recommendation: Recommendation) -> ApprovalStatus:
    """Every recommendation starts PENDING_HUMAN_REVIEW - ESCALATE always
    requires human review before any action, with no confidence threshold
    high enough to skip it. MONITOR/REQUEST_MORE_EVIDENCE don't block
    system operation on a human response, but remain visible for review
    at the audit-trail level (see docs/PHASE_4_ARCHITECTURE.md)."""
    return ApprovalStatus.PENDING_HUMAN_REVIEW


def record_human_decision(decision: str, reviewer_reason: str,
                            original_recommendation: Recommendation) -> HumanDecision:
    """The ONLY function in this codebase that can change an
    ApprovalStatus away from PENDING_HUMAN_REVIEW. No automated caller of
    this function exists anywhere in agent/loop.py or agent/demo.py - it
    exists to be called by a human reviewer (or, in tests, to simulate
    one)."""
    if decision not in ("APPROVE", "OVERRIDE", "REQUEST_MORE_EVIDENCE"):
        raise ValueError(f"Invalid human decision: {decision}")
    return HumanDecision(decision=decision, reviewer_reason=reviewer_reason,
                          original_recommendation=original_recommendation)
