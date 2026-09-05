"""
Synthetic merchant transaction generator for Drift Watch.

Generates daily aggregated behavioral features for a population of merchants
across several archetypes, with ground-truth drift labels for evaluation.

All data produced by this script is synthetic and is NOT derived from any
real Razorpay data.

Phase 2 extension: the original 6-archetype population (`build_population`)
is kept unchanged for backward compatibility with Phase 1 docs/tests. A new
`build_richer_population` adds 13 additional drift_kind regimes spanning
legitimate, suspicious, and ambiguous behavior (see docs/EVIDENCE_MODEL.md
and PHASE_2_REPORT.md §"Signal Grouping"/"Multi-Seed Results" for how these
are used). Both functions now take an explicit `seed` so the multi-seed
benchmark (evaluation/MULTI_SEED_EVALUATION.md) can generate independent,
reproducible populations rather than sharing module-global RNG state.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

CATEGORIES = ["apparel", "electronics", "digital_goods", "groceries", "home_decor", "beauty", "subscriptions"]
GEOGRAPHIES = ["mumbai", "delhi", "bengaluru", "chennai", "hyderabad", "pune", "kolkata", "jaipur", "surat", "unknown_intl"]
PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]

# Ground-truth categorization of drift_kind values used across both the
# original and richer populations. Anything NOT in RISK_KINDS is treated as
# a legitimate business change (or no change) for evaluation purposes, even
# though several LEGIT_KINDS move the same surface metrics a risk episode
# would (that's the point - they're the Hypothesis-B test cases).
RISK_KINDS = {
    "fraud", "slow_fraud", "refund_abuse", "dispute_escalation", "geo_anomaly",
    "category_anomaly", "volume_dispute_combo", "refund_geo_combo",
    "two_weak_signals", "seasonal_suspicious", "contradictory_evidence",
    "missing_evidence_case", "temporary_anomaly",
}
LEGIT_KINDS = {"launch", "geo_expansion", "marketing_campaign", "seasonal_promo"}


@dataclass
class MerchantArchetype:
    merchant_id: str
    archetype: str
    home_category: str
    home_geo: str
    base_txn_count: float
    base_refund_rate: float
    base_dispute_rate: float
    base_avg_value: float
    days: int = 240
    drift_start_day: Optional[int] = None   # day index where drift begins, if any
    drift_end_day: Optional[int] = None      # day index where drift ends (exclusive); None = persists
    drift_kind: Optional[str] = None         # see RISK_KINDS / LEGIT_KINDS above


def _entropy(counts: dict) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    probs = np.array([c / total for c in counts.values() if c > 0])
    return float(-(probs * np.log(probs + 1e-12)).sum())


def generate_merchant_days(m: MerchantArchetype, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    cat_weights = {c: (5.0 if c == m.home_category else 0.5) for c in CATEGORIES}
    geo_weights = {g: (5.0 if g == m.home_geo else 0.3) for g in GEOGRAPHIES}

    for day in range(m.days):
        started = m.drift_start_day is not None and day >= m.drift_start_day
        ended = m.drift_end_day is not None and day >= m.drift_end_day
        drifted = started and not ended
        days_into_drift = (day - m.drift_start_day) if drifted else 0

        txn_count = m.base_txn_count * (1 + rng.normal(0, 0.08))
        refund_rate = m.base_refund_rate * (1 + rng.normal(0, 0.12))
        dispute_rate = m.base_dispute_rate * (1 + rng.normal(0, 0.15))
        avg_value = m.base_avg_value * (1 + rng.normal(0, 0.06))
        local_cat_weights = dict(cat_weights)
        local_geo_weights = dict(geo_weights)

        if m.archetype == "growing":
            txn_count *= 1 + 0.004 * day

        if m.archetype == "seasonal" and (day % 90) in range(40, 46):
            txn_count *= 2.2
            refund_rate *= 1.3

        if drifted:
            if m.drift_kind in ("fraud", "temporary_anomaly", "missing_evidence_case"):
                ramp_days = 3.0 if m.drift_kind in ("temporary_anomaly", "missing_evidence_case") else 4.0
                ramp = min(1.0, days_into_drift / ramp_days)
                txn_count *= 1 + 1.4 * ramp
                refund_rate *= 1 + 2.3 * ramp
                dispute_rate *= 1 + 3.0 * ramp
                local_cat_weights = {c: (5.0 if c == "digital_goods" else 0.3) for c in CATEGORIES}
                if m.drift_kind != "missing_evidence_case":
                    local_geo_weights = {g: (5.0 if g == "unknown_intl" else 0.2) for g in GEOGRAPHIES}
            elif m.drift_kind == "slow_fraud":
                ramp = min(1.0, days_into_drift / 30.0)
                txn_count *= 1 + 1.4 * ramp
                refund_rate *= 1 + 2.3 * ramp
                dispute_rate *= 1 + 3.0 * ramp
                local_cat_weights = {c: (5.0 if c == "digital_goods" else 0.3) for c in CATEGORIES}
                local_geo_weights = {g: (5.0 if g == "unknown_intl" else 0.2) for g in GEOGRAPHIES}
            elif m.drift_kind == "launch":
                new_cat = "electronics" if m.home_category != "electronics" else "home_decor"
                local_cat_weights[new_cat] = 4.0
                txn_count *= 1 + 0.3 * min(1.0, days_into_drift / 10.0)
            elif m.drift_kind == "geo_expansion":
                new_geo = "pune" if m.home_geo != "pune" else "jaipur"
                local_geo_weights[new_geo] = 4.0
                txn_count *= 1 + 0.2 * min(1.0, days_into_drift / 10.0)
            elif m.drift_kind == "seasonal_promo":
                txn_count *= 1.9
                refund_rate *= 1.4
            elif m.drift_kind == "marketing_campaign":
                # Legitimate, temporary volume spike (paired with drift_end_day) -
                # unlike "fraud", nothing else about the merchant's mix changes.
                txn_count *= 1.8
                refund_rate *= 1.2
            elif m.drift_kind == "refund_abuse":
                ramp = min(1.0, days_into_drift / 5.0)
                refund_rate *= 1 + 3.0 * ramp
            elif m.drift_kind == "dispute_escalation":
                ramp = min(1.0, days_into_drift / 5.0)
                dispute_rate *= 1 + 4.0 * ramp
            elif m.drift_kind == "geo_anomaly":
                local_geo_weights = {g: (5.0 if g == "unknown_intl" else 0.2) for g in GEOGRAPHIES}
            elif m.drift_kind == "category_anomaly":
                local_cat_weights = {c: (5.0 if c == "digital_goods" else 0.3) for c in CATEGORIES}
            elif m.drift_kind == "volume_dispute_combo":
                ramp = min(1.0, days_into_drift / 6.0)
                txn_count *= 1 + 1.2 * ramp
                dispute_rate *= 1 + 3.0 * ramp
            elif m.drift_kind == "refund_geo_combo":
                ramp = min(1.0, days_into_drift / 6.0)
                refund_rate *= 1 + 2.5 * ramp
                local_geo_weights = {g: (5.0 if g == "unknown_intl" else 0.2) for g in GEOGRAPHIES}
            elif m.drift_kind == "two_weak_signals":
                ramp = min(1.0, days_into_drift / 10.0)
                refund_rate *= 1 + 0.8 * ramp
                dispute_rate *= 1 + 1.0 * ramp
            elif m.drift_kind == "seasonal_suspicious":
                # Looks like a legitimate seasonal bump (volume+refund) but
                # carries a real dispute/geo shift hidden inside it.
                txn_count *= 1.9
                refund_rate *= 1.3
                dispute_rate *= 1 + 2.0 * min(1.0, days_into_drift / 8.0)
                local_geo_weights = {g: (4.0 if g == "unknown_intl" else 0.5) for g in GEOGRAPHIES}
            elif m.drift_kind == "contradictory_evidence":
                ramp = min(1.0, days_into_drift / 6.0)
                refund_rate *= 1 + 2.0 * ramp
                dispute_rate *= max(0.3, 1 - 0.5 * ramp)  # dispute rate falls while refund rises

        txn_count = max(1, int(round(txn_count)))
        cats = rng.choice(list(local_cat_weights.keys()), size=txn_count,
                           p=np.array(list(local_cat_weights.values())) / sum(local_cat_weights.values()))
        geos = rng.choice(list(local_geo_weights.keys()), size=txn_count,
                           p=np.array(list(local_geo_weights.values())) / sum(local_geo_weights.values()))
        cat_counts = pd.Series(cats).value_counts().to_dict()
        geo_counts = pd.Series(geos).value_counts().to_dict()

        rows.append({
            "merchant_id": m.merchant_id,
            "day": day,
            "txn_count": txn_count,
            "txn_volume": round(txn_count * avg_value, 2),
            "avg_txn_value": round(avg_value, 2),
            "refund_rate": max(0.0, refund_rate),
            "dispute_rate": max(0.0, dispute_rate),
            "category_entropy": round(_entropy(cat_counts), 4),
            "geo_entropy": round(_entropy(geo_counts), 4),
            "dominant_category": max(cat_counts, key=cat_counts.get),
            "dominant_geo": max(geo_counts, key=geo_counts.get),
            "true_drift": int(drifted and m.drift_kind in RISK_KINDS),
            "true_drift_any": int(drifted),
            "drift_kind": m.drift_kind if drifted else "none",
            "archetype": m.archetype,
        })
    return pd.DataFrame(rows)


def build_population(n_normal=8, n_seasonal=3, n_growing=3, n_launch=3,
                      n_geo=3, n_fraud=4, days=240, seed=42) -> pd.DataFrame:
    """Original Phase 1 population - unchanged behavior, kept for backward
    compatibility with existing docs/tests. Seed defaults to 42 to reproduce
    the exact Phase 1 dataset."""
    rng = np.random.default_rng(seed)
    merchants = []
    idx = 0

    def new_id():
        nonlocal idx
        idx += 1
        return f"M{idx:04d}"

    for _ in range(n_normal):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="normal",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(20, 200), base_refund_rate=rng.uniform(0.01, 0.08),
            base_dispute_rate=rng.uniform(0.001, 0.01), base_avg_value=rng.uniform(300, 3000),
            days=days,
        ))
    for _ in range(n_seasonal):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="seasonal",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(30, 150), base_refund_rate=rng.uniform(0.02, 0.09),
            base_dispute_rate=rng.uniform(0.002, 0.01), base_avg_value=rng.uniform(300, 2500),
            days=days,
        ))
    for _ in range(n_growing):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="growing",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(15, 60), base_refund_rate=rng.uniform(0.01, 0.06),
            base_dispute_rate=rng.uniform(0.001, 0.008), base_avg_value=rng.uniform(300, 2000),
            days=days,
        ))
    for _ in range(n_launch):
        start = int(rng.uniform(150, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="product_launch",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(25, 120), base_refund_rate=rng.uniform(0.01, 0.07),
            base_dispute_rate=rng.uniform(0.001, 0.008), base_avg_value=rng.uniform(300, 2500),
            days=days, drift_start_day=start, drift_kind="launch",
        ))
    for _ in range(n_geo):
        start = int(rng.uniform(150, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="geo_expansion",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(25, 120), base_refund_rate=rng.uniform(0.01, 0.07),
            base_dispute_rate=rng.uniform(0.001, 0.008), base_avg_value=rng.uniform(300, 2500),
            days=days, drift_start_day=start, drift_kind="geo_expansion",
        ))
    for _ in range(n_fraud):
        start = int(rng.uniform(160, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="fraud_drift",
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(20, 100), base_refund_rate=rng.uniform(0.01, 0.05),
            base_dispute_rate=rng.uniform(0.001, 0.006), base_avg_value=rng.uniform(300, 2000),
            days=days, drift_start_day=start, drift_kind="fraud",
        ))

    frames = [generate_merchant_days(m, rng) for m in merchants]
    return pd.concat(frames, ignore_index=True)


# Phase 2: richer population spanning legitimate / suspicious / ambiguous
# regimes (task brief step 6). n_per_kind controls how many merchants get
# each of the 13 new drift_kind regimes (2 by default -> 26 new merchants);
# the original 6 archetypes are still included at reduced counts so the
# population stays a reasonable evaluation size (~60 merchants).
RICHER_KIND_SPECS = {
    # legitimate
    "marketing_campaign": dict(category="legitimate", start_range=(100, 180), duration=12),
    # suspicious
    "slow_fraud": dict(category="suspicious", start_range=(60, 150), duration=None),
    "refund_abuse": dict(category="suspicious", start_range=(100, 200), duration=None),
    "dispute_escalation": dict(category="suspicious", start_range=(100, 200), duration=None),
    "geo_anomaly": dict(category="suspicious", start_range=(100, 200), duration=None),
    "category_anomaly": dict(category="suspicious", start_range=(100, 200), duration=None),
    "volume_dispute_combo": dict(category="suspicious", start_range=(100, 200), duration=None),
    "refund_geo_combo": dict(category="suspicious", start_range=(100, 200), duration=None),
    # ambiguous
    "two_weak_signals": dict(category="ambiguous", start_range=(100, 180), duration=None),
    "seasonal_suspicious": dict(category="ambiguous", start_range=(100, 180), duration=None),
    "contradictory_evidence": dict(category="ambiguous", start_range=(100, 180), duration=None),
    "missing_evidence_case": dict(category="ambiguous", start_range=(10, 25), duration=None),
    "temporary_anomaly": dict(category="ambiguous", start_range=(100, 180), duration=6),
}


def build_richer_population(seed=42, days=240, n_per_kind=2,
                             n_normal=6, n_seasonal=2, n_growing=2,
                             n_launch=2, n_geo=2, n_fraud=2) -> pd.DataFrame:
    """
    Phase 2 benchmark population: the original 6 archetypes (at reduced
    counts) plus 13 additional drift_kind regimes covering legitimate,
    suspicious, and ambiguous behavior (task brief step 6). Fully
    reproducible from `seed` alone - used by the multi-seed benchmark
    (evaluation/MULTI_SEED_EVALUATION.md) to generate 10 independent
    populations.
    """
    rng = np.random.default_rng(seed)
    merchants = []
    idx = 0

    def new_id():
        nonlocal idx
        idx += 1
        return f"R{idx:04d}"

    def base_kwargs():
        return dict(
            home_category=rng.choice(CATEGORIES), home_geo=rng.choice(GEOGRAPHIES),
            base_txn_count=rng.uniform(20, 150), base_refund_rate=rng.uniform(0.01, 0.06),
            base_dispute_rate=rng.uniform(0.001, 0.008), base_avg_value=rng.uniform(300, 2500),
            days=days,
        )

    for _ in range(n_normal):
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="normal", **base_kwargs()))
    for _ in range(n_seasonal):
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="seasonal", **base_kwargs()))
    for _ in range(n_growing):
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="growing", **base_kwargs()))
    for _ in range(n_launch):
        start = int(rng.uniform(150, 200))
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="product_launch",
                                            drift_start_day=start, drift_kind="launch", **base_kwargs()))
    for _ in range(n_geo):
        start = int(rng.uniform(150, 200))
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="geo_expansion",
                                            drift_start_day=start, drift_kind="geo_expansion", **base_kwargs()))
    for _ in range(n_fraud):
        start = int(rng.uniform(160, 200))
        merchants.append(MerchantArchetype(merchant_id=new_id(), archetype="fraud_drift",
                                            drift_start_day=start, drift_kind="fraud", **base_kwargs()))

    for kind, spec in RICHER_KIND_SPECS.items():
        for _ in range(n_per_kind):
            start = int(rng.uniform(*spec["start_range"]))
            end = start + spec["duration"] if spec["duration"] else None
            merchants.append(MerchantArchetype(
                merchant_id=new_id(), archetype=spec["category"],
                drift_start_day=start, drift_end_day=end, drift_kind=kind,
                **base_kwargs(),
            ))

    frames = [generate_merchant_days(m, rng) for m in merchants]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import os
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = build_population()
    out_path = os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv")
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} rows for {df['merchant_id'].nunique()} merchants -> {out_path}")
    print(df.groupby("archetype")["merchant_id"].nunique())

    richer = build_richer_population()
    richer_path = os.path.join(REPO_ROOT, "data", "synthetic_merchant_events_richer.csv")
    richer.to_csv(richer_path, index=False)
    print(f"\nGenerated {len(richer)} rows for {richer['merchant_id'].nunique()} merchants -> {richer_path}")
    print(richer.groupby(["archetype", "drift_kind"])["merchant_id"].nunique())
