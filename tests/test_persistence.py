"""
Phase 5 tests — SQLite persistence. Verifies that merchants, episodes,
investigations, evidence, human decisions, and audit events are durably
stored and readable back from a fresh connection (i.e. actually on disk,
not just in memory).
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("fastapi")

from backend.main import create_app  # noqa: E402
from backend.db import Database  # noqa: E402

FLAGSHIP = "DW-M0021-0178"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("phase5_persist") / "persistence_test.db"
    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c, db_path


def test_engine_seeds_merchants_and_episodes(client):
    c, db_path = client
    r = c.get("/health")
    assert r.status_code == 200
    db = Database(db_path)
    assert db.query_one("SELECT COUNT(*) AS c FROM merchants")["c"] == r.json()["merchants"]
    assert db.query_one("SELECT COUNT(*) AS c FROM episodes")["c"] == r.json()["episodes"]
    ep = db.query_one("SELECT * FROM episodes WHERE episode_id=?", (FLAGSHIP,))
    assert ep is not None and ep["status"] in ("WATCH", "INVESTIGATING", "ESCALATE", "RESOLVED")


def test_investigation_and_evidence_persisted(client):
    c, db_path = client
    assert c.post(f"/episodes/{FLAGSHIP}/investigate").status_code == 200
    db = Database(db_path)
    inv = db.latest_investigation(FLAGSHIP)
    assert inv is not None
    assert inv["recommendation"] in ("MONITOR", "REQUEST_MORE_EVIDENCE", "ESCALATE")
    assert inv["approval_status"] == "PENDING_HUMAN_REVIEW"
    # hypotheses/tool_calls/budget come back as structured JSON, not strings
    assert isinstance(inv["hypotheses"], dict) and "RISK_DRIFT" in inv["hypotheses"]
    assert isinstance(inv["tool_calls"], list) and len(inv["tool_calls"]) > 0
    ev = db.evidence_for(inv["investigation_id"])
    assert len(ev) > 0
    e = ev[0]
    assert {"evidence_id", "source_tool", "signal_group", "evidence_type",
            "interpretation", "reliability"} <= set(e)
    n_tools = len({row["source_tool"] for row in ev})
    assert n_tools >= 1


def test_human_decision_and_audit_persisted(client):
    c, db_path = client
    r = c.post(f"/episodes/{FLAGSHIP}/approve", json={"reviewer_reason": "Persistence check."})
    assert r.status_code == 200
    db = Database(db_path)
    inv = db.latest_investigation(FLAGSHIP)
    decisions = db.decisions_for(FLAGSHIP)
    assert len(decisions) == 1
    d = decisions[0]
    assert d["decision"] == "APPROVE" and d["reviewer_reason"] == "Persistence check."
    assert db.investigation(inv["investigation_id"])["approval_status"] == "APPROVED"
    events = db.audit_for_episode(FLAGSHIP)
    assert any(e["event_type"] == "human_decision" for e in events)
    assert any(e["event_type"] == "planner_decision" for e in events)
    # every persisted event parses as JSON detail
    assert all(isinstance(e["detail"], dict) for e in events)


def test_data_is_durable_across_reopen(client):
    """The DB file on disk already contains the rows written through the
    API above; a fresh Database instance must see them."""
    c, db_path = client
    db = Database(db_path)
    assert db.query_one("SELECT COUNT(*) AS c FROM human_decisions")["c"] >= 1
    assert db.query_one("SELECT COUNT(*) AS c FROM investigations")["c"] >= 1
