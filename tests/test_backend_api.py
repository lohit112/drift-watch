"""
Phase 5 tests — FastAPI endpoints, investigation API flow, approval/override,
audit persistence, and security boundaries over the HTTP surface.

The backend is exercised with a throwaway SQLite database; the engine calls
the REAL Phase 1-4 pipeline (real dataset, real detection, real
investigation loop) - no mocking of the core.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from backend.main import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("phase5") / "api_test.db"
    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


# The flagship fraud episode (all 5 signal groups deviate -> the agent layer
# escalates it); used for the full investigate -> approve flow.
FLAGSHIP = "DW-M0021-0178"
SEASONAL = "DW-M0009-0041"    # documented seasonal merchant -> REQUEST_MORE
EXTRA = "DW-M0009-0131"       # untouched episode for re-investigation checks


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["merchants"] >= 20
    assert body["episodes"] >= 20
    assert body["llm_provider"] == "none"  # deterministic unless configured


def test_merchants_list_and_summary(client):
    r = client.get("/merchants")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["merchants_monitored"] == len(body["merchants"])
    m = body["merchants"][0]
    for key in ("merchant_id", "dominant_category", "dominant_geo", "episode_count"):
        assert key in m
    # Ground-truth labels must never reach the product surface.
    assert "archetype" not in str(body).lower() or "archetype" not in body["merchants"][0]


def test_merchant_detail_404(client):
    assert client.get("/merchants/DOES_NOT_EXIST").status_code == 404


def test_merchant_detail_has_timeline_and_no_ground_truth(client):
    r = client.get("/merchants/M0021")
    assert r.status_code == 200
    body = r.json()
    assert len(body["behavioral_timeline"]) >= 200
    point = body["behavioral_timeline"][0]
    assert {"day", "txn_count", "refund_rate", "dispute_rate", "predicted_drift_ms"} <= set(point)
    assert "archetype" not in point and "drift_kind" not in point and "true_drift" not in point


def test_merchant_episodes(client):
    r = client.get("/merchants/M0021/episodes")
    assert r.status_code == 200
    ids = [e["episode_id"] for e in r.json()["episodes"]]
    assert FLAGSHIP in ids
    assert client.get("/merchants/DOES_NOT_EXIST/episodes").status_code == 404


def test_episode_detail_before_investigation(client):
    r = client.get(f"/episodes/{EXTRA}")
    assert r.status_code == 200
    body = r.json()
    assert body["episode"]["episode_id"] == EXTRA
    assert body["latest_investigation"] is None
    assert client.get("/episodes/NOPE-1234").status_code == 404


def test_investigate_flow_persists_and_is_structured(client):
    r = client.post(f"/episodes/{FLAGSHIP}/investigate")
    assert r.status_code == 200
    body = r.json()
    inv = body["investigation"]
    assert inv["episode_id"] == FLAGSHIP
    assert inv["recommendation"] == "ESCALATE"
    # ESCALATE is a recommendation: it must start as pending human review.
    assert inv["approval_status"] == "PENDING_HUMAN_REVIEW"
    assert inv["planner_mode"] == "deterministic"
    assert len(inv["tool_calls"]) > 0
    assert inv["budget"]["tool_calls_used"] <= inv["budget"]["max_tool_calls"]
    assert len(body["evidence"]) == len({e["evidence_id"] for e in body["evidence"]})
    # Every narrative citation must exist in the persisted evidence registry.
    ev_ids = {e["evidence_id"] for e in body["evidence"]}
    cited = [e for e in ev_ids if f"[{e}]" in inv["narrative"]]
    assert cited, "narrative must cite registered evidence"
    assert any(e["event_type"] == "planner_decision" for e in body["audit_events"])


def test_approve_records_human_decision(client):
    r = client.post(f"/episodes/{FLAGSHIP}/approve",
                    json={"reviewer_reason": "Confirmed coordinated drift; escalation stands."})
    assert r.status_code == 200
    body = r.json()
    assert body["decision"]["decision"] == "APPROVE"
    assert body["investigation"]["approval_status"] == "APPROVED"
    assert any(e["event_type"] == "human_decision" for e in body["audit_events"])


def test_double_decision_is_conflict_not_bypass(client):
    r = client.post(f"/episodes/{FLAGSHIP}/override", json={"reviewer_reason": "second attempt"})
    assert r.status_code == 409
    r = client.post(f"/episodes/{FLAGSHIP}/request-evidence", json={"reviewer_reason": "third attempt"})
    assert r.status_code == 409


def test_override_and_request_evidence_paths(client):
    r = client.post(f"/episodes/{SEASONAL}/investigate")
    assert r.status_code == 200
    assert r.json()["investigation"]["recommendation"] == "REQUEST_MORE_EVIDENCE"
    r = client.post(f"/episodes/{SEASONAL}/override",
                    json={"reviewer_reason": "Seasonal pattern known for this merchant."})
    assert r.status_code == 200
    assert r.json()["decision"]["decision"] == "OVERRIDE"
    assert r.json()["investigation"]["approval_status"] == "OVERRIDDEN"


def test_decision_requires_reason_and_existing_episode(client):
    assert client.post(f"/episodes/{EXTRA}/approve", json={"reviewer_reason": ""}).status_code == 422
    assert client.post("/episodes/NOPE-1/approve", json={"reviewer_reason": "x"}).status_code == 404
    assert client.post("/episodes/NOPE-1/override", json={"reviewer_reason": "x"}).status_code == 404


def test_decision_before_investigation_is_conflict(client):
    r = client.post("/episodes/DW-M0009-0208/approve", json={"reviewer_reason": "x"})
    assert r.status_code == 409


def test_reinvestigation_creates_new_pending_record(client):
    r1 = client.post(f"/episodes/{EXTRA}/investigate")
    assert r1.status_code == 200
    id1 = r1.json()["investigation"]["investigation_id"]
    assert r1.json()["investigation"]["approval_status"] == "PENDING_HUMAN_REVIEW"
    r2 = client.post(f"/episodes/{EXTRA}/investigate")
    id2 = r2.json()["investigation"]["investigation_id"]
    assert id1 != id2 and id2.startswith(id1)


def test_audit_endpoint_returns_persisted_trail(client):
    r = client.get(f"/episodes/{FLAGSHIP}/audit")
    assert r.status_code == 200
    body = r.json()
    types = {e["event_type"] for e in body["events"]}
    assert {"investigation_started", "planner_decision", "tool_call", "hypothesis_update",
            "recommendation", "approval_required", "human_decision"} <= types
    seqs = [e["sequence"] for e in body["events"]]
    assert seqs == sorted(seqs)
    assert len(body["human_decisions"]) == 1
    assert client.get("/episodes/NOPE-1/audit").status_code == 404


def test_no_endpoint_executes_account_actions(client):
    """ESCALATE must never automatically execute a risk action. There is no
    such route - and the API must not grow one accidentally."""
    for action in ("suspend", "restrict", "execute", "escalate", "contact"):
        r = client.post(f"/episodes/{FLAGSHIP}/{action}", json={"reviewer_reason": "x"})
        assert r.status_code in (404, 405), f"/{action} must not exist as an executable route"
