"""
SQLite persistence (Phase 5) — P0.

Simple, stdlib-only (sqlite3) persistence. No ORM, no migrations framework —
the schema is small and created idempotently at startup. This layer stores
and retrieves ONLY; every value it persists is produced by the existing
Phase 1-4 engine (detection → episodes → agent loop). No business logic
lives here.

Tables:
  merchants              - one row per monitored merchant (identity only:
                           NO ground-truth columns like archetype/drift_kind
                           ever leave the engine — see agent/tools.py)
  episodes               - one row per RiskEpisode
  investigations         - one row per POST .../investigate run
  investigation_evidence - the registry's AgentEvidence rows per investigation
  human_decisions        - explicit human decisions (the ONLY approval record)
  audit_events           - the per-investigation audit trail, plus explicit
                           human_decision events appended on approve/override
"""
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id       TEXT PRIMARY KEY,
    dominant_category TEXT NOT NULL,
    dominant_geo      TEXT NOT NULL,
    first_day         INTEGER NOT NULL,
    last_day          INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    episode_id        TEXT PRIMARY KEY,
    merchant_id       TEXT NOT NULL REFERENCES merchants(merchant_id),
    start_day         INTEGER NOT NULL,
    current_day       INTEGER NOT NULL,
    end_day           INTEGER,
    status            TEXT NOT NULL,
    peak_day          INTEGER,
    peak_score        REAL,
    signal_groups     TEXT NOT NULL,          -- JSON array
    hypothesis_a      TEXT NOT NULL,
    hypothesis_b      TEXT NOT NULL,
    recommended_action TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_merchant ON episodes(merchant_id);
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    episode_id       TEXT NOT NULL REFERENCES episodes(episode_id),
    created_at       TEXT NOT NULL,
    planner_mode     TEXT NOT NULL,            -- "deterministic" | "llm"
    sufficiency      TEXT NOT NULL,
    recommendation   TEXT NOT NULL,
    approval_status  TEXT NOT NULL,
    leading_hypothesis TEXT NOT NULL,
    narrative        TEXT NOT NULL,
    hypotheses       TEXT NOT NULL,            -- JSON
    tool_calls       TEXT NOT NULL,            -- JSON
    budget           TEXT NOT NULL,            -- JSON
    failure_reason   TEXT
);
CREATE INDEX IF NOT EXISTS idx_investigations_episode ON investigations(episode_id);
CREATE TABLE IF NOT EXISTS investigation_evidence (
    investigation_id TEXT NOT NULL REFERENCES investigations(investigation_id),
    evidence_id      TEXT NOT NULL,
    source_tool      TEXT NOT NULL,
    signal_group     TEXT NOT NULL,
    metric           TEXT NOT NULL,
    value            REAL,
    baseline         REAL,
    deviation        REAL,
    time_window      TEXT NOT NULL,
    evidence_type    TEXT NOT NULL,
    interpretation   TEXT NOT NULL,
    reliability      REAL NOT NULL,
    status           TEXT NOT NULL,
    supports_hypothesis     TEXT,
    contradicts_hypothesis  TEXT,
    PRIMARY KEY (investigation_id, evidence_id)
);
CREATE TABLE IF NOT EXISTS human_decisions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id        TEXT NOT NULL REFERENCES investigations(investigation_id),
    episode_id              TEXT NOT NULL,
    decision                TEXT NOT NULL,     -- APPROVE | OVERRIDE | REQUEST_MORE_EVIDENCE
    reviewer_reason         TEXT NOT NULL,
    original_recommendation TEXT NOT NULL,
    decided_at              TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL,
    episode_id       TEXT NOT NULL,
    sequence         INTEGER NOT NULL,
    event_type       TEXT NOT NULL,
    detail           TEXT NOT NULL,            -- JSON
    timestamp        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_episode ON audit_events(episode_id);
"""


class Database:
    """Thin sqlite3 wrapper. One connection per Database instance; the
    FastAPI app creates exactly one at startup (sqlite3 connections are
    thread-constrained, and the app runs with a single worker for the
    demo). Row access returns plain dicts."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def execute(self, sql, params=()):
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur

    def query(self, sql, params=()):
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql, params=()):
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    # --- merchants / episodes (upserted from the engine at startup) ---

    def upsert_merchant(self, merchant_id, dominant_category, dominant_geo, first_day, last_day):
        self.execute(
            "INSERT INTO merchants (merchant_id, dominant_category, dominant_geo, first_day, last_day) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(merchant_id) DO UPDATE SET dominant_category=excluded.dominant_category, "
            "dominant_geo=excluded.dominant_geo, first_day=excluded.first_day, last_day=excluded.last_day",
            (merchant_id, dominant_category, dominant_geo, first_day, last_day))

    def upsert_episode(self, ep_dict):
        self.execute(
            "INSERT INTO episodes (episode_id, merchant_id, start_day, current_day, end_day, status, "
            "peak_day, peak_score, signal_groups, hypothesis_a, hypothesis_b, recommended_action) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(episode_id) DO UPDATE SET status=excluded.status, current_day=excluded.current_day, "
            "peak_score=excluded.peak_score, recommended_action=excluded.recommended_action",
            (ep_dict["episode_id"], ep_dict["merchant_id"], ep_dict["start_day"], ep_dict["current_day"],
             ep_dict["end_day"], ep_dict["status"], ep_dict["peak_day"], ep_dict["peak_score"],
             json.dumps(ep_dict["signal_groups"]), ep_dict["hypothesis_a"], ep_dict["hypothesis_b"],
             ep_dict["recommended_action"]))

    # --- investigations ---

    def insert_investigation(self, record):
        self.execute(
            "INSERT INTO investigations (investigation_id, episode_id, created_at, planner_mode, sufficiency, "
            "recommendation, approval_status, leading_hypothesis, narrative, hypotheses, tool_calls, budget, "
            "failure_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["investigation_id"], record["episode_id"], record["created_at"], record["planner_mode"],
             record["sufficiency"], record["recommendation"], record["approval_status"],
             record["leading_hypothesis"], record["narrative"], json.dumps(record["hypotheses"]),
             json.dumps(record["tool_calls"]), json.dumps(record["budget"]), record["failure_reason"]))

    def update_investigation_approval(self, investigation_id, approval_status):
        self.execute("UPDATE investigations SET approval_status=? WHERE investigation_id=?",
                     (approval_status, investigation_id))

    def insert_evidence(self, investigation_id, ev):
        self.execute(
            "INSERT OR REPLACE INTO investigation_evidence "
            "(investigation_id, evidence_id, source_tool, signal_group, metric, value, baseline, deviation, "
            "time_window, evidence_type, interpretation, reliability, status, supports_hypothesis, "
            "contradicts_hypothesis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (investigation_id, ev["evidence_id"], ev["source_tool"], ev["signal_group"], ev["metric"],
             ev["value"], ev["baseline"], ev["deviation"], ev["time_window"], ev["evidence_type"],
             ev["interpretation"], ev["reliability"], ev["status"], ev["supports_hypothesis"],
             ev["contradicts_hypothesis"]))

    def evidence_for(self, investigation_id):
        return self.query(
            "SELECT * FROM investigation_evidence WHERE investigation_id=? ORDER BY evidence_id",
            (investigation_id,))

    def _decode_investigation(self, row):
        """JSON-typed columns come back from sqlite as strings — decode them
        so API responses are structured JSON, as stored."""
        if row is None:
            return None
        row = dict(row)
        for col in ("hypotheses", "tool_calls", "budget"):
            row[col] = json.loads(row[col])
        return row

    def latest_investigation(self, episode_id):
        return self._decode_investigation(self.query_one(
            "SELECT * FROM investigations WHERE episode_id=? ORDER BY created_at DESC, investigation_id DESC",
            (episode_id,)))

    def investigations_for(self, episode_id):
        return [self._decode_investigation(r) for r in self.query(
            "SELECT * FROM investigations WHERE episode_id=? ORDER BY created_at DESC, investigation_id DESC",
            (episode_id,))]

    def investigation(self, investigation_id):
        return self._decode_investigation(self.query_one(
            "SELECT * FROM investigations WHERE investigation_id=?", (investigation_id,)))

    # --- human decisions ---

    def insert_human_decision(self, record):
        self.execute(
            "INSERT INTO human_decisions (investigation_id, episode_id, decision, reviewer_reason, "
            "original_recommendation, decided_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record["investigation_id"], record["episode_id"], record["decision"], record["reviewer_reason"],
             record["original_recommendation"], record["decided_at"]))

    def decision_exists(self, investigation_id):
        return self.query_one(
            "SELECT id FROM human_decisions WHERE investigation_id=?", (investigation_id,)) is not None

    def decisions_for(self, episode_id):
        return self.query(
            "SELECT * FROM human_decisions WHERE episode_id=? ORDER BY decided_at DESC, id DESC",
            (episode_id,))

    # --- audit events ---

    def insert_audit_event(self, investigation_id, episode_id, event):
        self.execute(
            "INSERT INTO audit_events (investigation_id, episode_id, sequence, event_type, detail, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (investigation_id, episode_id, event["sequence"], event["event_type"],
             json.dumps(event["detail"]), event["timestamp"]))

    def append_audit_event(self, episode_id, investigation_id, event_type, detail, timestamp):
        """Explicit appended event (e.g. human_decision) — sequence continues
        after the investigation's own trail."""
        row = self.query_one(
            "SELECT COALESCE(MAX(sequence), 0) AS m FROM audit_events WHERE investigation_id=?",
            (investigation_id,))
        seq = (row["m"] if row else 0) + 1
        self.execute(
            "INSERT INTO audit_events (investigation_id, episode_id, sequence, event_type, detail, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (investigation_id, episode_id, seq, event_type, json.dumps(detail), timestamp))
        return seq

    def audit_for_episode(self, episode_id):
        events = self.query(
            "SELECT * FROM audit_events WHERE episode_id=? ORDER BY id", (episode_id,))
        for e in events:
            e["detail"] = json.loads(e["detail"])
        return events
