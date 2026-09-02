"""
Evidence Correlator + Case Builder — Phase 2 rewrite.

Takes structured Evidence (agents/evidence.py) from the investigators and
produces a reviewable case: competing hypotheses (each with its own
supporting/contradicting/missing evidence), a defensible Risk Confidence
Score (agents/confidence.py), a three-way decision
(ESCALATE / MONITOR / REQUEST_MORE_EVIDENCE), and a full audit trail.

NOTE ON LLM USE (see docs/PRODUCT_SPEC.md and DECISIONS.md): this reference
implementation uses deterministic rules to combine investigator findings so
the core loop is testable end-to-end without an API key. In the full build,
this is exactly the seam where a Claude Agent SDK call belongs: the
investigators' structured evidence is passed in as grounded evidence, and
the LLM is prompted to (a) write the natural-language case narrative and
(b) propose additional hypotheses a rule table might miss - while the
deterministic correlation logic below still decides confidence and severity,
so a prompt-injected finding can change wording but not the actual decision.
"""
import datetime
from dataclasses import dataclass, field
import pandas as pd

from agents.evidence import Evidence
from agents.investigators import run_all_investigators
from agents.confidence import compute_confidence, decide_action, ConfidenceBreakdown

HYPOTHESIS_A_TEXT = ("Correlated shift across multiple independent risk signals "
                      "(transaction pattern, dispute rate, and/or geography/category) "
                      "consistent with account compromise or a change to riskier "
                      "business activity.")
HYPOTHESIS_B_TEXT = ("Legitimate business change (e.g. a sale, seasonal promotion, "
                      "or planned product/geo expansion) that happens to move one or "
                      "more of the same surface metrics without genuine risk increase.")


@dataclass
class RiskCase:
    merchant_id: str
    flagged_day: int
    deviant_signal_groups: list
    evidence: list                       # flat list[Evidence] from all investigators
    hypothesis_a: str                    # risk explanation
    hypothesis_b: str                    # legitimate explanation
    evidence_for_a: list                 # Evidence items where supports_hypothesis == "A"
    evidence_for_b: list                 # Evidence items where supports_hypothesis == "B"
    evidence_missing: list                # Evidence items of type "missing"
    confidence: ConfidenceBreakdown       # Risk Confidence Score + component breakdown
    decision: str                         # ESCALATE / MONITOR / REQUEST_MORE_EVIDENCE
    recommended_action: str
    severity: str
    audit_log: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "merchant_id": self.merchant_id,
            "flagged_day": self.flagged_day,
            "deviant_signal_groups": self.deviant_signal_groups,
            "evidence": [e.to_dict() for e in self.evidence],
            "hypothesis_a_risk": self.hypothesis_a,
            "hypothesis_b_legitimate": self.hypothesis_b,
            "evidence_for_a": [e.summary for e in self.evidence_for_a],
            "evidence_for_b": [e.summary for e in self.evidence_for_b],
            "evidence_missing": [e.summary for e in self.evidence_missing],
            "risk_confidence_score": self.confidence.to_dict(),
            "decision": self.decision,
            "recommended_action": self.recommended_action,
            "severity": self.severity,
            "audit_log": self.audit_log,
        }


def build_case(scored_history: pd.DataFrame, flagged_day: int, deviant_signal_groups: list) -> RiskCase:
    """
    scored_history: the DETECTOR'S OWN scored output for one merchant (i.e.
    a slice of detection.drift_detector.merchant_specific_drift's return
    value for a single merchant_id) - NOT raw unscored history. This is what
    lets investigators build TRIGGER evidence from the exact numbers the
    detector flagged on (see agents/investigators.py module docstring and
    PHASE_1_REPORT.md §9).
    """
    log = []

    def note(msg: str):
        log.append({"timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "detail": msg})

    note(f"Sentinel flagged day {flagged_day} with deviant signal groups: {deviant_signal_groups}")
    evidence = run_all_investigators(scored_history, flagged_day)
    for e in evidence:
        note(f"{e.source} [{e.evidence_type}] -> {e.summary}")

    evidence_for_a = [e for e in evidence if e.supports_hypothesis == "A"]
    evidence_for_b = [e for e in evidence if e.supports_hypothesis == "B"]
    evidence_missing = [e for e in evidence if e.evidence_type == "missing"]
    note(f"Evidence Correlator: {len(evidence_for_a)} items support Hypothesis A, "
         f"{len(evidence_for_b)} support Hypothesis B, {len(evidence_missing)} missing.")

    confidence = compute_confidence(evidence)
    decision, severity, action = decide_action(confidence)

    hyp_a = HYPOTHESIS_A_TEXT
    hyp_b = HYPOTHESIS_B_TEXT

    note(f"Risk Confidence Score: {confidence.final_score:.2f} "
         f"(anomaly_strength={confidence.anomaly_strength:.2f}, signal_breadth={confidence.signal_breadth:.2f}, "
         f"temporal_persistence={confidence.temporal_persistence:.2f}, evidence_balance={confidence.evidence_balance:.2f}, "
         f"novelty={confidence.novelty:.2f}, missing_groups={confidence.missing_groups})")
    note(f"Decision: {decision}, severity={severity}")
    note(f"Recommended action: {action}")
    note("Routed to human approval gate - no autonomous account action taken.")

    return RiskCase(
        merchant_id=scored_history["merchant_id"].iloc[0],
        flagged_day=flagged_day,
        deviant_signal_groups=deviant_signal_groups,
        evidence=evidence,
        hypothesis_a=hyp_a,
        hypothesis_b=hyp_b,
        evidence_for_a=evidence_for_a,
        evidence_for_b=evidence_for_b,
        evidence_missing=evidence_missing,
        confidence=confidence,
        decision=decision,
        recommended_action=action,
        severity=severity,
        audit_log=log,
    )
