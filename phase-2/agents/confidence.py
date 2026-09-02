"""
Risk Confidence Score — Phase 2, task brief step 12.

Replaces the Phase 1 heuristic `min(0.95, 0.15 + 0.22 * n_risk_signals)`,
which had no documented justification for its constants (see
PHASE_1_REPORT.md / AUDIT_REPORT.md - a prior session incorrectly claimed
this had already been fixed; it had not).

This is explicitly called a "Risk Confidence Score", NOT a probability -
it is not calibrated against observed outcome frequencies (see
docs/CONFIDENCE_MODEL.md "Limitations"). It is a documented, weighted
combination of five components computed from the structured Evidence list
(agents/evidence.py), each normalized to [0, 1]:

  1. anomaly_strength     - how extreme is the trigger deviation itself?
  2. signal_breadth       - how many INDEPENDENT signal groups deviated?
  3. temporal_persistence - does the deviation hold up in the 3-day/7-day
                             contextual windows, or was it a one-day blip?
  4. evidence_balance     - fraction of all evidence supporting Hypothesis A
                             minus fraction supporting Hypothesis B
  5. novelty              - has this merchant shown this before (historical
                             evidence), or is it unprecedented for them?

A missing-evidence penalty is applied afterward, separately from the five
weighted components (see docs/CONFIDENCE_MODEL.md), because missing
evidence should always cap confidence rather than being averaged into it -
an investigator that can't assess a dimension should never quietly count as
"neutral" evidence.
"""
from dataclasses import dataclass

from agents.evidence import Evidence

# Weights sum to 1.0 - see docs/CONFIDENCE_MODEL.md "Weight rationale" for
# why anomaly_strength and evidence_balance get the largest share (they are
# the most directly diagnostic), and novelty the smallest (weakest standalone
# signal - many legitimate first-time events also look "novel").
WEIGHTS = {
    "anomaly_strength": 0.30,
    "signal_breadth": 0.20,
    "temporal_persistence": 0.20,
    "evidence_balance": 0.20,
    "novelty": 0.10,
}
MISSING_EVIDENCE_PENALTY_PER_GROUP = 0.12   # multiplicative cap reduction per missing signal group
MAX_CONFIDENCE_WITH_ANY_MISSING = 0.75      # hard ceiling if ANY group's evidence is missing


@dataclass
class ConfidenceBreakdown:
    anomaly_strength: float
    signal_breadth: float
    temporal_persistence: float
    evidence_balance: float
    novelty: float
    raw_score: float               # weighted sum before missing-evidence penalty
    missing_groups: int
    final_score: float             # after missing-evidence penalty/cap
    n_support_a: int
    n_support_b: int
    n_missing: int

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


def compute_confidence(evidence: list[Evidence], n_signal_groups_total: int = 5) -> ConfidenceBreakdown:
    trigger_ev = [e for e in evidence if e.evidence_type == "trigger"]
    contextual_ev = [e for e in evidence if e.evidence_type == "contextual"]
    historical_ev = [e for e in evidence if e.evidence_type == "historical"]
    missing_ev = [e for e in evidence if e.evidence_type == "missing"]

    # 1. anomaly_strength: average |z| across deviant trigger evidence, normalized.
    #    A z of 6 or more (the fraud archetype's day-1 onset routinely produces
    #    z in the 5-9 range for volume/refund/dispute - see PHASE_2_BASELINE.md)
    #    saturates the component at 1.0.
    deviant_triggers = [e for e in trigger_ev if e.supports_hypothesis == "A"]
    if deviant_triggers:
        avg_abs_z = sum(abs(e.deviation) for e in deviant_triggers if e.deviation is not None) / len(deviant_triggers)
        anomaly_strength = min(1.0, avg_abs_z / 6.0)
    else:
        anomaly_strength = 0.0

    # 2. signal_breadth: independent deviant groups / total independent groups
    #    being tracked by the taxonomy (fixed denominator - NOT the number of
    #    groups present in this particular evidence list, so this component
    #    behaves correctly even when called with a partial/synthetic evidence
    #    set, e.g. in unit tests - see tests/test_confidence_model.py).
    deviant_groups = {e.signal_group for e in deviant_triggers}
    signal_breadth = min(1.0, len(deviant_groups) / n_signal_groups_total)

    # 3. temporal_persistence: fraction of contextual (3d/7d) evidence that
    #    still supports A, among groups whose trigger fired. A trigger with no
    #    persisting contextual support (one-day blip) scores 0 here, not just
    #    a smaller trigger contribution - persistence is evaluated separately
    #    from anomaly_strength on purpose (see docs/EVIDENCE_MODEL.md).
    contextual_for_deviant_groups = [e for e in contextual_ev if e.signal_group in deviant_groups]
    if contextual_for_deviant_groups:
        temporal_persistence = sum(1 for e in contextual_for_deviant_groups if e.supports_hypothesis == "A") \
            / len(contextual_for_deviant_groups)
    else:
        temporal_persistence = 0.0

    # 4. evidence_balance: (support_A - support_B) / total_meaningful, over ALL
    #    evidence (trigger + contextual + historical + contradicting), rescaled
    #    from [-1, 1] to [0, 1].
    n_support_a = sum(1 for e in evidence if e.supports_hypothesis == "A")
    n_support_b = sum(1 for e in evidence if e.supports_hypothesis == "B")
    total_meaningful = n_support_a + n_support_b
    balance_raw = (n_support_a - n_support_b) / total_meaningful if total_meaningful else 0.0
    evidence_balance = (balance_raw + 1) / 2

    # 5. novelty: fraction of HISTORICAL evidence (for deviant groups) that
    #    reports this deviation has never happened before for this merchant.
    historical_for_deviant = [e for e in historical_ev if e.signal_group in deviant_groups]
    if historical_for_deviant:
        novelty = sum(1 for e in historical_for_deviant if e.supports_hypothesis == "A") \
            / len(historical_for_deviant)
    else:
        novelty = 0.0

    raw_score = (
        WEIGHTS["anomaly_strength"] * anomaly_strength +
        WEIGHTS["signal_breadth"] * signal_breadth +
        WEIGHTS["temporal_persistence"] * temporal_persistence +
        WEIGHTS["evidence_balance"] * evidence_balance +
        WEIGHTS["novelty"] * novelty
    )

    n_missing_groups = len({e.signal_group for e in missing_ev})
    if n_missing_groups > 0:
        penalty_factor = max(0.0, 1 - MISSING_EVIDENCE_PENALTY_PER_GROUP * n_missing_groups)
        final_score = min(raw_score * penalty_factor, MAX_CONFIDENCE_WITH_ANY_MISSING)
    else:
        final_score = raw_score

    final_score = max(0.0, min(1.0, final_score))

    return ConfidenceBreakdown(
        anomaly_strength=anomaly_strength, signal_breadth=signal_breadth,
        temporal_persistence=temporal_persistence, evidence_balance=evidence_balance,
        novelty=novelty, raw_score=raw_score, missing_groups=n_missing_groups,
        final_score=final_score, n_support_a=n_support_a, n_support_b=n_support_b,
        n_missing=len(missing_ev),
    )


def decide_action(confidence: ConfidenceBreakdown) -> tuple[str, str, str]:
    """Returns (decision, severity, action_text). Decision is one of
    ESCALATE / MONITOR / REQUEST_MORE_EVIDENCE (task brief step 14's three
    golden-case outcomes)."""
    score = confidence.final_score

    if confidence.n_missing > 0:
        return ("REQUEST_MORE_EVIDENCE", "unknown",
                "Request more evidence - insufficient baseline history exists for one or more "
                "signal groups to assess this merchant with confidence.")

    # Ambiguous zone: evidence doesn't clearly separate the two hypotheses.
    if 0.38 <= score <= 0.62:
        return ("REQUEST_MORE_EVIDENCE", "unknown",
                "Request more evidence - supporting and contradicting evidence are too close "
                "to confidently favor either hypothesis.")

    if score > 0.62:
        severity = "high" if score >= 0.75 else "medium"
        action = ("Escalate for human risk-analyst review before any account action"
                  if severity == "high" else
                  "Increase monitoring frequency; request merchant verification of recent changes")
        return ("ESCALATE", severity, action)

    return ("MONITOR", "low", "Monitor - evidence favors a legitimate explanation; continue tracking")
