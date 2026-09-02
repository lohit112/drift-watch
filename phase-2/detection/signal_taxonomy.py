"""
Signal taxonomy — Phase 2, task brief step 5.

Groups the raw features Drift Watch computes into independent risk
dimensions. This is the same grouping principle already used by the
detector's SIGNAL_GROUPS (txn_count/txn_volume are correlated, not
independent - see DECISIONS.md D5), formalized here as a single shared
source of truth so the detector, investigators, and case builder all agree
on what counts as "one independent signal changing" vs "four features
moving."

Correlation notes (why groups are drawn this way):
- txn_count and txn_volume are algebraically related (volume ~ count *
  avg_value), so they are the same VOLUME dimension, not two.
- refund_rate and dispute_rate are NOT merged, even though real fraud often
  moves both together (see fraud/slow_fraud archetype construction in
  data/synthetic_generator.py) - they are measuring different things
  (customer-initiated reversal vs. bank-mediated reversal) and can move
  independently (see the "contradictory_evidence" archetype, where refund
  rises while dispute falls). Treating them as one group would hide that
  divergence, which is itself evidence.
- category_entropy and geo_entropy are each their own dimension for the
  same reason - a category shift and a geography shift are different
  underlying behaviors, even though both can appear together in a fraud
  episode (see "fraud" archetype construction, which moves both).
- avg_txn_value is deliberately NOT scored as its own signal in Phase 1/2:
  it's algebraically implied by txn_count and txn_volume together
  (avg = volume / count), so scoring it independently would be a third
  count of the same VOLUME dimension. It remains available for investigator
  narrative context only.
"""
from dataclasses import dataclass

FEATURES = ["txn_count", "txn_volume", "refund_rate", "dispute_rate",
            "category_entropy", "geo_entropy"]


@dataclass(frozen=True)
class SignalGroup:
    name: str
    features: tuple
    dimension: str   # one of the 7 taxonomy dimensions in the task brief
    description: str


SIGNAL_GROUPS = {
    "volume": SignalGroup(
        "volume", ("txn_count", "txn_volume"), "VOLUME",
        "Transaction count and transaction value together - algebraically "
        "correlated, counted as one independent signal.",
    ),
    "refund": SignalGroup(
        "refund", ("refund_rate",), "REFUND",
        "Customer-initiated return/refund rate.",
    ),
    "dispute": SignalGroup(
        "dispute", ("dispute_rate",), "DISPUTE",
        "Bank-mediated chargeback/dispute rate - distinct from refund_rate "
        "and can move in the opposite direction (see contradictory_evidence "
        "archetype).",
    ),
    "category_mix": SignalGroup(
        "category_mix", ("category_entropy",), "CATEGORY",
        "Product-category concentration/diversity.",
    ),
    "geo_mix": SignalGroup(
        "geo_mix", ("geo_entropy",), "GEOGRAPHY",
        "Transaction-geography concentration/diversity.",
    ),
}

# Two taxonomy dimensions from the task brief - CUSTOMER BEHAVIOR and
# SETTLEMENT/PAYMENT - have no corresponding feature in the current
# synthetic dataset (no per-customer repeat-purchase data, no payment-method
# breakdown feature is scored). Documented here rather than silently
# omitted: this is a real coverage gap, not an oversight. See
# PHASE_2_REPORT.md "Signal Grouping" and "Remaining Weaknesses".
UNCOVERED_DIMENSIONS = {
    "CUSTOMER_BEHAVIOR": "No per-customer/repeat-purchase signal exists in the "
                          "current feature set (only merchant-day aggregates).",
    "SETTLEMENT_PAYMENT": "payment_method distribution is generated "
                           "(PAYMENT_METHODS in synthetic_generator.py) but never "
                           "aggregated into a scored feature - not wired into "
                           "detection in Phase 1 or Phase 2.",
}


def independent_groups_deviant(deviant_features: list) -> list:
    """Given a list of deviant FEATURE names (not group names), return the
    independent SIGNAL_GROUPS names they belong to - collapsing correlated
    features (e.g. txn_count + txn_volume) into a single group."""
    hit = set()
    for group_key, group in SIGNAL_GROUPS.items():
        if any(f in deviant_features for f in group.features):
            hit.add(group_key)
    return sorted(hit)
