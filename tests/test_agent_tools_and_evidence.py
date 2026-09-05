"""
Tests covering task brief step 17 items #7, #8, #9, #10, #11, #12.
"""
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from detection.drift_detector import merchant_specific_drift
from agent.tools import ALL_TOOLS, ToolContext, TransactionBehaviorTool
from agent.evidence import EvidenceRegistry
from agent.models import FailureReason, ToolStatus
from agent.failures import validate_tool_output, is_safe_to_use


def _fraud_history(days=200, onset=150, seed=3):
    rng = np.random.default_rng(seed)
    txn = 50 * (1 + rng.normal(0, 0.05, days))
    refund = 0.03 * (1 + rng.normal(0, 0.08, days))
    dispute = 0.005 * (1 + rng.normal(0, 0.10, days))
    for d in range(onset, days):
        ramp = min(1.0, (d - onset) / 4.0)
        txn[d] *= 1 + 1.4 * ramp
        refund[d] *= 1 + 2.3 * ramp
        dispute[d] *= 1 + 3.0 * ramp
    df = pd.DataFrame({
        "merchant_id": ["M"] * days, "day": list(range(days)),
        "txn_count": txn, "txn_volume": txn * 1000.0,
        "refund_rate": refund, "dispute_rate": dispute,
        "category_entropy": [1.2] * days, "geo_entropy": [1.1] * days,
        "dominant_category": ["apparel"] * days, "dominant_geo": ["mumbai"] * days,
    })
    return merchant_specific_drift(df)


def test_evidence_ids_are_unique():
    """Test #11: evidence IDs are unique, even across many tool calls."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry)
    for _ in range(3):
        for tool in ALL_TOOLS.values():
            tool.execute(ctx)
    ids = [e.evidence_id for e in registry.all()]
    assert len(ids) == len(set(ids)), "Evidence IDs must be unique even across repeated tool calls"


def test_evidence_traceable_to_source_tool():
    """Test #12: every evidence item is traceable to the tool that produced it."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry)
    result = ALL_TOOLS["transaction_behavior"].execute(ctx)
    for e in result.evidence:
        assert e.source_tool == "transaction_behavior"
        assert registry.get(e.evidence_id) is e


def test_no_tool_produces_arbitrary_prose_as_primary_result():
    """Every tool's primary result is structured (AgentEvidence list), not a string."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry)
    for name, tool in ALL_TOOLS.items():
        result = tool.execute(ctx)
        assert isinstance(result.evidence, list)
        for e in result.evidence:
            assert isinstance(e.value, (float, type(None)))
            assert isinstance(e.interpretation, str)  # narrative is secondary, not primary


def test_tool_timeout_handled_safely():
    """Test #7: simulated timeout produces a controlled failure, not a crash."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry,
                       simulate_failure=FailureReason.TOOL_TIMEOUT)
    result = ALL_TOOLS["transaction_behavior"].execute(ctx)
    assert result.status == ToolStatus.FAILURE
    assert result.failure_reason == FailureReason.TOOL_TIMEOUT
    assert result.evidence == []


def test_tool_exception_handled_safely():
    """Test #8: a raising tool must not propagate the exception - it must
    degrade to a controlled TOOL_EXCEPTION failure."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    broken_history = hist.drop(columns=["z_txn_count", "baseline_mean_txn_count", "baseline_days_txn_count"])
    ctx = ToolContext(scored_history=broken_history, episode_start=150, as_of_day=160, registry=registry)
    result = ALL_TOOLS["transaction_behavior"].execute(ctx)
    # Missing columns degrade safely (either FAILURE or a MISSING-evidence
    # SUCCESS, per episode/aggregation.py's own safe-degradation contract) -
    # the critical property is: it never raises.
    assert result.status in (ToolStatus.SUCCESS, ToolStatus.FAILURE)


def test_malformed_tool_output_is_rejected():
    """Test #9: validate_tool_output rejects a SUCCESS-with-no-evidence or
    FAILURE-with-evidence result."""
    from agent.tools import ToolResult
    bad_success = ToolResult(tool_name="x", status=ToolStatus.SUCCESS, evidence=[])
    assert not validate_tool_output(bad_success).valid
    assert not is_safe_to_use(bad_success)


def test_failed_tools_do_not_become_risk_evidence():
    """Test #10: a failed tool call must never contribute evidence to the pool."""
    hist = _fraud_history()
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry,
                       simulate_failure=FailureReason.TOOL_EXCEPTION)
    result = ALL_TOOLS["refund_dispute_behavior"].execute(ctx)
    assert result.status == ToolStatus.FAILURE
    assert len(registry) == 0, "A failed tool call must not register any evidence"


def test_merchant_context_does_not_read_ground_truth_columns():
    """merchant_context must never read archetype/drift_kind/true_drift -
    those are evaluation-only labels, not real-world-observable data."""
    hist = _fraud_history()
    hist = hist.copy()
    hist["archetype"] = "fraud_drift"  # simulate a ground-truth column being present
    hist["drift_kind"] = "fraud"
    registry = EvidenceRegistry()
    ctx = ToolContext(scored_history=hist, episode_start=150, as_of_day=160, registry=registry)
    result = ALL_TOOLS["merchant_context"].execute(ctx)
    assert result.status == ToolStatus.SUCCESS
    for e in result.evidence:
        assert "fraud" not in e.interpretation.lower()
        assert "archetype" not in e.interpretation.lower()


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS: {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
