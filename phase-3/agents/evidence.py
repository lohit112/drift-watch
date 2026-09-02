"""
Structured evidence model — Phase 2, task brief steps 2 and 13.

The core Phase 1 weakness this fixes: investigators used to recompute their
OWN baseline/recent windowing (a 5-day trailing average), independent of the
detector's own per-day z-score. That let a genuine detector flag (a single
day's statistically significant deviation) get diluted into "insufficient
evidence" purely because of a mismatched averaging window (see
PHASE_1_REPORT.md §9).

The fix here is not to force investigators to agree with the detector -
it's to make the relationship between what triggered the alert and what
supports/contradicts it explicit and separately visible, via five evidence
types:

- TRIGGER: the exact detector observation that caused the flag (same day,
  same baseline_mean/std the detector itself computed - see
  detection/drift_detector.py's baseline_mean_<feat>/baseline_std_<feat>
  columns). This is intentionally NOT recomputed by the investigator.
- CONTEXTUAL: short (3-day) and medium (7-day) trailing windows ending on
  the flagged day, compared against the SAME baseline the trigger used -
  answers "is this a one-day blip or does it persist?" without diluting
  the trigger's own evidence.
- HISTORICAL: how often this specific merchant has shown a deviation this
  large for this feature before, anywhere in its prior history.
- CONTRADICTING: signal groups that did NOT deviate, specifically ones a
  coordinated risk episode would typically also move (used to argue for
  Hypothesis B / against Hypothesis A).
- MISSING: evidence the system would like to have but couldn't obtain
  (usually: insufficient baseline history). Never silently treated as
  "no evidence of risk" - flagged explicitly so the case builder can
  reduce confidence and prefer "request more evidence" over a confident
  verdict either way.
"""
from dataclasses import dataclass
from typing import Optional

EVIDENCE_TYPES = ("trigger", "contextual", "historical", "contradicting", "missing")
STRENGTHS = ("weak", "moderate", "strong", "n/a")
DIRECTIONS = ("up", "down", "flat", "n/a")


@dataclass
class Evidence:
    source: str                          # e.g. "Refund Investigator"
    signal_group: str                    # e.g. "refund" - see detection/signal_taxonomy.py
    evidence_type: str                   # one of EVIDENCE_TYPES
    observation: Optional[float]         # the raw observed value, if any
    baseline: Optional[float]            # the value being compared against, if any
    deviation: Optional[float]           # z-score (trigger/contextual/historical) - signed
    time_window: str                     # human-readable description of the window used
    direction: str                       # one of DIRECTIONS
    strength: str                        # one of STRENGTHS
    supports_hypothesis: Optional[str]   # "A" (risk), "B" (legitimate), or None
    contradicts_hypothesis: Optional[str]
    confidence: float                    # 0-1, THIS evidence item's own reliability (not case confidence)
    summary: str                         # human-readable one-liner

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def strength_from_z(abs_z: Optional[float]) -> str:
    if abs_z is None:
        return "n/a"
    if abs_z >= 4.0:
        return "strong"
    if abs_z >= 2.5:
        return "moderate"
    return "weak"


def direction_from_delta(delta: Optional[float]) -> str:
    if delta is None:
        return "n/a"
    if delta > 1e-9:
        return "up"
    if delta < -1e-9:
        return "down"
    return "flat"
