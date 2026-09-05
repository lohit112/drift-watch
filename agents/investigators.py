"""
Investigator sub-agents (Bumblebee-style Fetchers).

Each investigator owns ONE evidence domain and returns a structured finding.
They do not decide risk themselves - that's the Evidence Correlator / Case
Builder's job. This separation is deliberate: investigators are deterministic
and auditable; only the planner/case-builder layer does open-ended reasoning.
"""
from dataclasses import dataclass, field
from typing import Any
import pandas as pd


@dataclass
class Finding:
    investigator: str
    summary: str
    detail: dict
    supports_risk: bool  # does this finding lean toward the risk hypothesis?


def _baseline_window(history: pd.DataFrame, flagged_day: int, recent_span: int = 5, min_baseline_days: int = 15):
    """
    Baseline = everything from day 0 up to (flagged_day - recent_span),
    capped at 60 days back. Falls back gracefully for merchants flagged
    early (before a full 60-day baseline exists) instead of returning an
    empty/undefined baseline - avoids the "compared against nothing"
    bug found during testing (see DECISIONS.md).
    """
    baseline_end = flagged_day - recent_span
    baseline_start = max(0, baseline_end - 60)
    baseline = history[(history["day"] >= baseline_start) & (history["day"] < baseline_end)]
    recent = history[(history["day"] > baseline_end) & (history["day"] <= flagged_day)]
    return baseline, recent, len(baseline) >= min_baseline_days


def transaction_investigator(history: pd.DataFrame, flagged_day: int) -> Finding:
    baseline, recent, has_baseline = _baseline_window(history, flagged_day)
    if not has_baseline:
        return Finding(
            investigator="Transaction Investigator",
            summary="Insufficient baseline history (<15 days) before this event to assess transaction pattern change with confidence.",
            detail={"baseline_days_available": len(baseline)},
            supports_risk=False,
        )
    base_count = baseline["txn_count"].mean() if len(baseline) else recent["txn_count"].mean()
    recent_count = recent["txn_count"].mean()
    pct_change = (recent_count - base_count) / base_count * 100 if base_count else 0

    return Finding(
        investigator="Transaction Investigator",
        summary=f"Transaction volume changed {pct_change:+.0f}% vs. 60-day baseline "
                 f"({base_count:.0f} -> {recent_count:.0f} txns/day, avg over trailing 5 days).",
        detail={"baseline_txn_count": round(base_count, 1), "recent_txn_count": round(recent_count, 1),
                "pct_change": round(pct_change, 1)},
        supports_risk=bool(abs(pct_change) > 40),
    )


def dispute_investigator(history: pd.DataFrame, flagged_day: int) -> Finding:
    baseline, recent, has_baseline = _baseline_window(history, flagged_day)
    if not has_baseline:
        return Finding(
            investigator="Dispute Investigator",
            summary="Insufficient baseline history (<15 days) before this event to assess dispute pattern change with confidence.",
            detail={"baseline_days_available": len(baseline)},
            supports_risk=False,
        )
    base_rate = baseline["dispute_rate"].mean()
    recent_rate = recent["dispute_rate"].mean()
    ratio = (recent_rate / base_rate) if base_rate > 1e-6 else float("inf")

    return Finding(
        investigator="Dispute Investigator",
        summary=f"Dispute rate is {ratio:.1f}x baseline ({base_rate:.3f} -> {recent_rate:.3f}), "
                 f"averaged over the 5 days around the flagged event.",
        detail={"baseline_dispute_rate": round(base_rate, 4), "recent_dispute_rate": round(recent_rate, 4),
                "ratio": round(ratio, 2) if ratio != float("inf") else None},
        supports_risk=bool(ratio > 1.8),
    )


def geography_investigator(history: pd.DataFrame, flagged_day: int) -> Finding:
    baseline, recent, has_baseline = _baseline_window(history, flagged_day)
    if not has_baseline:
        return Finding(
            investigator="Geography Investigator",
            summary="Insufficient baseline history (<15 days) before this event to assess geographic shift with confidence.",
            detail={"baseline_days_available": len(baseline)},
            supports_risk=False,
        )
    base_geo = baseline["dominant_geo"].mode().iloc[0]
    now_geo = recent["dominant_geo"].mode().iloc[0]
    shifted = base_geo != now_geo

    return Finding(
        investigator="Geography Investigator",
        summary=(f"Dominant transaction geography shifted from '{base_geo}' to '{now_geo}'."
                  if shifted else f"Dominant geography unchanged ('{base_geo}')."),
        detail={"baseline_dominant_geo": base_geo, "recent_dominant_geo": now_geo, "shifted": shifted},
        supports_risk=bool(shifted and now_geo == "unknown_intl"),
    )


def merchant_profile_investigator(history: pd.DataFrame, flagged_day: int) -> Finding:
    baseline, recent, has_baseline = _baseline_window(history, flagged_day)
    if not has_baseline:
        return Finding(
            investigator="Merchant Profile Investigator",
            summary="Insufficient baseline history (<15 days) before this event to assess category shift with confidence.",
            detail={"baseline_days_available": len(baseline)},
            supports_risk=False,
        )
    base_cat = baseline["dominant_category"].mode().iloc[0]
    now_cat = recent["dominant_category"].mode().iloc[0]
    shifted = base_cat != now_cat

    return Finding(
        investigator="Merchant Profile Investigator",
        summary=(f"Dominant product category shifted from '{base_cat}' to '{now_cat}'."
                  if shifted else f"Dominant category unchanged ('{base_cat}')."),
        detail={"baseline_dominant_category": base_cat, "recent_dominant_category": now_cat, "shifted": shifted},
        supports_risk=bool(shifted and now_cat == "digital_goods"),
    )


def run_all_investigators(history: pd.DataFrame, flagged_day: int) -> list[Finding]:
    return [
        transaction_investigator(history, flagged_day),
        dispute_investigator(history, flagged_day),
        geography_investigator(history, flagged_day),
        merchant_profile_investigator(history, flagged_day),
    ]
