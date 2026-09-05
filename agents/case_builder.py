"""
Evidence Correlator + Case Builder.

Takes structured findings from the investigators and produces a reviewable
case: competing hypotheses, supporting evidence, confidence, recommended
action, and audit trail.

NOTE ON LLM USE (see docs/PRODUCT_SPEC.md and DECISIONS.md): this reference
implementation uses deterministic rules to combine investigator findings so
the core loop is testable end-to-end without an API key. In the full build,
this is exactly the seam where a Claude Agent SDK call belongs: the
investigators' structured findings are passed in as grounded evidence, and
the LLM is prompted to (a) write the natural-language case narrative and
(b) propose additional hypotheses a rule table might miss - while the
deterministic correlation logic below still decides confidence and severity,
so a prompt-injected finding can change wording but not the actual decision.
"""
import datetime
from dataclasses import dataclass, field
from typing import Any
import pandas as pd

from agents.investigators import Finding, run_all_investigators


@dataclass
class RiskCase:
    merchant_id: str
    flagged_day: int
    deviant_signal_groups: list
    findings: list
    hypothesis_a: str          # risk explanation
    hypothesis_b: str          # legitimate explanation
    evidence_for_a: list
    evidence_for_b: list
    confidence_risk: float     # 0-1, how much evidence leans toward A
    recommended_action: str
    severity: str
    audit_log: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "merchant_id": self.merchant_id,
            "flagged_day": self.flagged_day,
            "deviant_signal_groups": self.deviant_signal_groups,
            "findings": [f.__dict__ for f in self.findings],
            "hypothesis_a_risk": self.hypothesis_a,
            "hypothesis_b_legitimate": self.hypothesis_b,
            "evidence_for_a": self.evidence_for_a,
            "evidence_for_b": self.evidence_for_b,
            "confidence_risk": round(self.confidence_risk, 2),
            "recommended_action": self.recommended_action,
            "severity": self.severity,
            "audit_log": self.audit_log,
        }


ACTIONS_BY_SEVERITY = {
    "low": "Monitor - no action needed, continue tracking",
    "medium": "Increase monitoring frequency; request merchant verification of recent changes",
    "high": "Escalate for human risk-analyst review before any account action",
}


def build_case(history: pd.DataFrame, flagged_day: int, deviant_signal_groups: list) -> RiskCase:
    log = []

    def note(msg: str):
        log.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "detail": msg})

    note(f"Sentinel flagged day {flagged_day} with deviant signal groups: {deviant_signal_groups}")
    findings = run_all_investigators(history, flagged_day)
    for f in findings:
        note(f"{f.investigator} activated -> {f.summary}")

    risk_supporting = [f for f in findings if f.supports_risk]
    n_risk_signals = len(risk_supporting)
    note(f"Evidence Correlator: {n_risk_signals}/{len(findings)} investigators support the risk hypothesis.")

    confidence_risk = min(0.95, 0.15 + 0.22 * n_risk_signals)

    # Legitimate-explanation heuristics: a pure volume spike with no
    # dispute/geo/category shift looks like a sale or seasonal spike, not fraud.
    only_volume = deviant_signal_groups == ["volume"]
    hypothesis_b_strength = "high" if only_volume else ("medium" if n_risk_signals <= 1 else "low")

    hyp_a = ("Correlated shift across multiple independent risk signals "
             "(transaction pattern, dispute rate, and/or geography/category) "
             "consistent with account compromise or a change to riskier "
             "business activity.")
    hyp_b = ("Legitimate business change (e.g. a sale, seasonal promotion, "
             "or planned product/geo expansion) that happens to move one or "
             "more of the same surface metrics without genuine risk increase.")

    evidence_for_a = [f.summary for f in findings if f.supports_risk]
    evidence_for_b = [f.summary for f in findings if not f.supports_risk]
    if only_volume:
        evidence_for_b.append("Only the transaction-volume signal group deviated; "
                               "no corresponding shift in disputes, geography, or category mix - "
                               "the single-signal pattern typical of a sale or promotion, not fraud.")

    if confidence_risk >= 0.7:
        severity = "high"
    elif confidence_risk >= 0.4:
        severity = "medium"
    else:
        severity = "low"

    note(f"Case Builder: confidence_risk={confidence_risk:.2f}, severity={severity}, "
         f"hypothesis_b_strength={hypothesis_b_strength}")
    note(f"Recommended action: {ACTIONS_BY_SEVERITY[severity]}")
    note("Routed to human approval gate - no autonomous account action taken.")

    return RiskCase(
        merchant_id=history["merchant_id"].iloc[0],
        flagged_day=flagged_day,
        deviant_signal_groups=deviant_signal_groups,
        findings=findings,
        hypothesis_a=hyp_a,
        hypothesis_b=hyp_b,
        evidence_for_a=evidence_for_a,
        evidence_for_b=evidence_for_b,
        confidence_risk=confidence_risk,
        recommended_action=ACTIONS_BY_SEVERITY[severity],
        severity=severity,
        audit_log=log,
    )
