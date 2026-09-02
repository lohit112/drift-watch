"""
Investigator sub-agents (Bumblebee-style Fetchers) — Phase 2 rewrite.

One investigator per independent signal group (see detection/signal_taxonomy.py):
Volume, Refund, Dispute, Category, Geography. Each investigator builds a list
of typed Evidence objects (agents/evidence.py) for its own signal group:

  TRIGGER      - the detector's own flagged-day observation vs its own
                 baseline_mean/std (never recomputed independently - this is
                 the Phase 1 §9 fix: trigger evidence is now, by
                 construction, the same number the detector flagged on).
  CONTEXTUAL   - 3-day and 7-day trailing windows ending on the flagged day,
                 compared to the same baseline, so a reviewer can see
                 whether the trigger was a one-day blip or is persisting.
  HISTORICAL   - how many times this specific feature has deviated this
                 much before, anywhere earlier in this merchant's own
                 history (not the population).
  CONTRADICTING - emitted for this group when it did NOT deviate at all
                 (weak evidence against Hypothesis A for that dimension).
  MISSING      - emitted instead of all of the above when the merchant
                 does not yet have enough baseline history for this
                 feature to be assessed with any confidence.

Investigators consume the DETECTOR'S OWN SCORED OUTPUT (the per-merchant
dataframe from detection.drift_detector.merchant_specific_drift, which
carries z_<feature>, baseline_mean_<feature>, baseline_std_<feature>,
baseline_days_<feature> columns) rather than raw unscored history - this is
what guarantees trigger evidence can never disagree with the detector about
what happened on the flagged day.
"""
from typing import Optional
import pandas as pd

from detection.drift_detector import FEATURES, Z_THRESHOLD, BASELINE_WINDOW
from detection.signal_taxonomy import SIGNAL_GROUPS
from agents.evidence import Evidence, strength_from_z, direction_from_delta

MIN_BASELINE_DAYS = 15  # below this, a feature's evidence is MISSING, not "no deviation"

INVESTIGATOR_NAMES = {
    "volume": "Volume Investigator",
    "refund": "Refund Investigator",
    "dispute": "Dispute Investigator",
    "category_mix": "Category Investigator",
    "geo_mix": "Geography Investigator",
}

# Which signal group a coordinated risk episode ("Hypothesis A") would
# typically ALSO move, used to decide whether a non-deviant group counts as
# meaningful contradicting evidence. All 5 groups qualify - a real account
# compromise / fraud drift plausibly touches any of them (see the "fraud"
# archetype in data/synthetic_generator.py, which moves all 5 at once).
RISK_RELEVANT_GROUPS = set(SIGNAL_GROUPS.keys())


def _primary_feature(group_key: str) -> str:
    """The single feature used for z-score/baseline lookups for a signal
    group. txn_count is used to represent 'volume' (txn_volume moves with
    it almost by construction - see signal_taxonomy.py)."""
    feats = SIGNAL_GROUPS[group_key].features
    return "txn_count" if group_key == "volume" else feats[0]


def _row_at(scored_history: pd.DataFrame, day: int) -> Optional[pd.Series]:
    match = scored_history[scored_history["day"] == day]
    return match.iloc[0] if not match.empty else None


def build_signal_evidence(scored_history: pd.DataFrame, flagged_day: int, group_key: str) -> list[Evidence]:
    """Build the full evidence list (trigger/contextual/historical or
    missing/contradicting) for ONE signal group at ONE flagged day."""
    source = INVESTIGATOR_NAMES[group_key]
    feat = _primary_feature(group_key)
    trigger_row = _row_at(scored_history, flagged_day)

    if trigger_row is None:
        return [Evidence(
            source=source, signal_group=group_key, evidence_type="missing",
            observation=None, baseline=None, deviation=None,
            time_window=f"day {flagged_day}", direction="n/a", strength="n/a",
            supports_hypothesis=None, contradicts_hypothesis=None, confidence=0.0,
            summary=f"No data available for day {flagged_day} - cannot assess {group_key}.",
        )]

    baseline_days = trigger_row.get(f"baseline_days_{feat}", 0)
    if pd.isna(baseline_days) or baseline_days < MIN_BASELINE_DAYS:
        return [Evidence(
            source=source, signal_group=group_key, evidence_type="missing",
            observation=float(trigger_row[feat]), baseline=None, deviation=None,
            time_window=f"trailing {BASELINE_WINDOW}d ending day {flagged_day - 1}",
            direction="n/a", strength="n/a",
            supports_hypothesis=None, contradicts_hypothesis=None, confidence=0.0,
            summary=f"Insufficient baseline history ({int(baseline_days) if not pd.isna(baseline_days) else 0} "
                     f"of {MIN_BASELINE_DAYS} minimum days) to assess {group_key} with confidence.",
        )]

    base_mean = trigger_row[f"baseline_mean_{feat}"]
    base_std = trigger_row[f"baseline_std_{feat}"]
    trigger_z = trigger_row[f"z_{feat}"]
    trigger_val = trigger_row[feat]
    trigger_deviant = abs(trigger_z) >= Z_THRESHOLD if not pd.isna(trigger_z) else False

    evidence = []

    # --- TRIGGER: exactly the detector's own comparison, never recomputed ---
    if not pd.isna(trigger_z):
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="trigger",
            observation=round(float(trigger_val), 4), baseline=round(float(base_mean), 4),
            deviation=round(float(trigger_z), 2),
            time_window=f"day {flagged_day} vs. trailing {BASELINE_WINDOW}d baseline (the detector's own window)",
            direction=direction_from_delta(trigger_val - base_mean),
            strength=strength_from_z(abs(trigger_z)),
            supports_hypothesis="A" if trigger_deviant else None,
            contradicts_hypothesis="B" if trigger_deviant else None,
            confidence=min(1.0, abs(trigger_z) / 5.0) if trigger_deviant else 0.3,
            summary=(f"{group_key}: day-{flagged_day} value {trigger_val:.4g} vs. baseline "
                     f"{base_mean:.4g} (z={trigger_z:+.2f}) - "
                     f"{'a statistically significant deviation' if trigger_deviant else 'within normal range'}."),
        ))

    # --- CONTEXTUAL: 3-day and 7-day trailing windows ending on flagged_day ---
    # Short window suits fast-moving signals (volume, dispute); medium window
    # suits slower-moving ones (refund, category/geo mix) - see docs/EVIDENCE_MODEL.md
    # for why each window was chosen per signal.
    for span, label in ((3, "short-term (3-day)"), (7, "medium-term (7-day)")):
        window = scored_history[(scored_history["day"] > flagged_day - span) & (scored_history["day"] <= flagged_day)]
        if window.empty or pd.isna(base_std) or base_std == 0:
            continue
        recent_mean = window[feat].mean()
        z_equiv = (recent_mean - base_mean) / base_std
        deviant = abs(z_equiv) >= Z_THRESHOLD
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="contextual",
            observation=round(float(recent_mean), 4), baseline=round(float(base_mean), 4),
            deviation=round(float(z_equiv), 2),
            time_window=f"{label} trailing avg ending day {flagged_day}, vs. same detector baseline",
            direction=direction_from_delta(recent_mean - base_mean),
            strength=strength_from_z(abs(z_equiv)),
            supports_hypothesis="A" if deviant else None,
            contradicts_hypothesis="B" if deviant else None,
            confidence=0.6,  # contextual windows are corroborating, not primary - see CONFIDENCE_MODEL.md
            summary=(f"{group_key}: {label} average {recent_mean:.4g} vs. baseline {base_mean:.4g} "
                     f"(z={z_equiv:+.2f}) - {'persists beyond the single trigger day' if deviant else 'trend not sustained at deviation level'}."),
        ))

    # --- HISTORICAL: has this merchant shown a deviation this large before? ---
    prior = scored_history[scored_history["day"] < flagged_day]
    prior_z = prior[f"z_{feat}"].dropna()
    n_prior_extreme = int((prior_z.abs() >= Z_THRESHOLD).sum())
    evidence.append(Evidence(
        source=source, signal_group=group_key, evidence_type="historical",
        observation=float(n_prior_extreme), baseline=None, deviation=None,
        time_window=f"entire prior history (days 0-{flagged_day - 1})",
        direction="n/a",
        strength="strong" if n_prior_extreme == 0 else ("weak" if n_prior_extreme <= 2 else "n/a"),
        supports_hypothesis="A" if (n_prior_extreme == 0 and trigger_deviant) else None,
        contradicts_hypothesis="B" if (n_prior_extreme == 0 and trigger_deviant) else None,
        confidence=0.5,
        summary=(f"{group_key}: this merchant has shown a deviation of this magnitude "
                 f"{n_prior_extreme} time(s) before in its prior history "
                 f"({'never before - novel behavior' if n_prior_extreme == 0 else 'has happened before'})."),
    ))

    # --- CONTRADICTING: this group did NOT deviate ---
    if not trigger_deviant and group_key in RISK_RELEVANT_GROUPS:
        evidence.append(Evidence(
            source=source, signal_group=group_key, evidence_type="contradicting",
            observation=round(float(trigger_val), 4), baseline=round(float(base_mean), 4),
            deviation=round(float(trigger_z), 2) if not pd.isna(trigger_z) else None,
            time_window=f"day {flagged_day} vs. trailing {BASELINE_WINDOW}d baseline",
            direction=direction_from_delta(trigger_val - base_mean),
            strength="weak",
            supports_hypothesis="B", contradicts_hypothesis="A",
            confidence=0.4,
            summary=f"{group_key}: no deviation at the trigger day - a coordinated risk episode "
                     "would plausibly move this dimension too, and it didn't.",
        ))

    return evidence


def run_all_investigators(scored_history: pd.DataFrame, flagged_day: int) -> list[Evidence]:
    """Run all 5 signal-group investigators and return one flat, ordered
    list of structured Evidence for the flagged day."""
    all_evidence: list[Evidence] = []
    for group_key in SIGNAL_GROUPS:
        all_evidence.extend(build_signal_evidence(scored_history, flagged_day, group_key))
    return all_evidence
