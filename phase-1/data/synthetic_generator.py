"""
Synthetic merchant transaction generator for Drift Watch.

Generates daily aggregated behavioral features for a population of merchants
across several archetypes, with ground-truth drift labels for evaluation.

All data produced by this script is synthetic and is NOT derived from any
real Razorpay data.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

RNG = np.random.default_rng(42)

CATEGORIES = ["apparel", "electronics", "digital_goods", "groceries", "home_decor", "beauty", "subscriptions"]
GEOGRAPHIES = ["mumbai", "delhi", "bengaluru", "chennai", "hyderabad", "pune", "kolkata", "jaipur", "surat", "unknown_intl"]
PAYMENT_METHODS = ["upi", "card", "netbanking", "wallet"]


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
    drift_start_day: Optional[int] = None  # day index where drift begins, if any
    drift_kind: Optional[str] = None        # "fraud", "seasonal", "launch", "geo_expansion", "growth", None


def _entropy(counts: dict) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    probs = np.array([c / total for c in counts.values() if c > 0])
    return float(-(probs * np.log(probs + 1e-12)).sum())


def generate_merchant_days(m: MerchantArchetype) -> pd.DataFrame:
    rows = []
    cat_weights = {c: (5.0 if c == m.home_category else 0.5) for c in CATEGORIES}
    geo_weights = {g: (5.0 if g == m.home_geo else 0.3) for g in GEOGRAPHIES}

    for day in range(m.days):
        drifted = m.drift_start_day is not None and day >= m.drift_start_day
        days_into_drift = (day - m.drift_start_day) if drifted else 0

        txn_count = m.base_txn_count * (1 + RNG.normal(0, 0.08))
        refund_rate = m.base_refund_rate * (1 + RNG.normal(0, 0.12))
        dispute_rate = m.base_dispute_rate * (1 + RNG.normal(0, 0.15))
        avg_value = m.base_avg_value * (1 + RNG.normal(0, 0.06))
        local_cat_weights = dict(cat_weights)
        local_geo_weights = dict(geo_weights)

        # gentle organic growth for the "growth" archetype (not labeled as drift-worthy in isolation)
        if m.archetype == "growing":
            txn_count *= 1 + 0.004 * day

        # seasonal spike (legitimate, still flagged as a candidate for investigation
        # but should resolve to Hypothesis B in the case builder)
        if m.archetype == "seasonal" and (day % 90) in range(40, 46):
            txn_count *= 2.2
            refund_rate *= 1.3

        if drifted:
            if m.drift_kind == "fraud":
                ramp = min(1.0, days_into_drift / 4.0)
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

        txn_count = max(1, int(round(txn_count)))
        cats = RNG.choice(list(local_cat_weights.keys()), size=txn_count,
                           p=np.array(list(local_cat_weights.values())) / sum(local_cat_weights.values()))
        geos = RNG.choice(list(local_geo_weights.keys()), size=txn_count,
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
            "true_drift": int(drifted and m.drift_kind == "fraud"),
            "true_drift_any": int(drifted),
            "drift_kind": m.drift_kind if drifted else "none",
            "archetype": m.archetype,
        })
    return pd.DataFrame(rows)


def build_population(n_normal=8, n_seasonal=3, n_growing=3, n_launch=3,
                      n_geo=3, n_fraud=4, days=240) -> pd.DataFrame:
    merchants = []
    idx = 0

    def new_id():
        nonlocal idx
        idx += 1
        return f"M{idx:04d}"

    for _ in range(n_normal):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="normal",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(20, 200), base_refund_rate=RNG.uniform(0.01, 0.08),
            base_dispute_rate=RNG.uniform(0.001, 0.01), base_avg_value=RNG.uniform(300, 3000),
            days=days,
        ))
    for _ in range(n_seasonal):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="seasonal",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(30, 150), base_refund_rate=RNG.uniform(0.02, 0.09),
            base_dispute_rate=RNG.uniform(0.002, 0.01), base_avg_value=RNG.uniform(300, 2500),
            days=days,
        ))
    for _ in range(n_growing):
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="growing",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(15, 60), base_refund_rate=RNG.uniform(0.01, 0.06),
            base_dispute_rate=RNG.uniform(0.001, 0.008), base_avg_value=RNG.uniform(300, 2000),
            days=days,
        ))
    for _ in range(n_launch):
        start = int(RNG.uniform(150, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="product_launch",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(25, 120), base_refund_rate=RNG.uniform(0.01, 0.07),
            base_dispute_rate=RNG.uniform(0.001, 0.008), base_avg_value=RNG.uniform(300, 2500),
            days=days, drift_start_day=start, drift_kind="launch",
        ))
    for _ in range(n_geo):
        start = int(RNG.uniform(150, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="geo_expansion",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(25, 120), base_refund_rate=RNG.uniform(0.01, 0.07),
            base_dispute_rate=RNG.uniform(0.001, 0.008), base_avg_value=RNG.uniform(300, 2500),
            days=days, drift_start_day=start, drift_kind="geo_expansion",
        ))
    for _ in range(n_fraud):
        start = int(RNG.uniform(160, 200))
        merchants.append(MerchantArchetype(
            merchant_id=new_id(), archetype="fraud_drift",
            home_category=RNG.choice(CATEGORIES), home_geo=RNG.choice(GEOGRAPHIES),
            base_txn_count=RNG.uniform(20, 100), base_refund_rate=RNG.uniform(0.01, 0.05),
            base_dispute_rate=RNG.uniform(0.001, 0.006), base_avg_value=RNG.uniform(300, 2000),
            days=days, drift_start_day=start, drift_kind="fraud",
        ))

    frames = [generate_merchant_days(m) for m in merchants]
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    import os
    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = build_population()
    out_path = os.path.join(REPO_ROOT, "data", "synthetic_merchant_events.csv")
    df.to_csv(out_path, index=False)
    print(f"Generated {len(df)} rows for {df['merchant_id'].nunique()} merchants -> {out_path}")
    print(df.groupby("archetype")["merchant_id"].nunique())
