"""
Drift Watch Risk Ops backend (Phase 5) — P0.

FastAPI application over the EXISTING Phase 1-4 engine. This module defines
HTTP routing, status codes, and persistence glue ONLY:

    detection → Risk Episode → Agentic Investigation → Evidence →
    Competing Hypotheses → Grounded Synthesis → Recommendation →
    Human Approval → Audit Trail

Every step above is the existing engine (detection/, episode/, agent/).
The backend never duplicates their logic and NEVER executes a risk action:
approve/override/request-evidence only RECORD a human decision via the
existing Phase 4 policy (`agent.policy.record_human_decision`). There is
no endpoint — and no code path — that executes a consequential account
action. ESCALATE is a recommendation for human review, nothing more.

Run:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000
"""
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.db import Database
from backend.engine import DriftWatchEngine, NotFoundError, ConflictError, REPO_ROOT
from backend.llm import build_models, load_llm_config
from backend import schemas

DEFAULT_DB_PATH = REPO_ROOT / "backend" / "drift_watch.db"


def create_app(db_path=None, data_path=None) -> FastAPI:
    """App factory. Tests build isolated instances with their own SQLite
    file; `python -m uvicorn backend.main:app` uses the module-level app."""
    db = Database(db_path or os.environ.get("DRIFT_WATCH_DB", DEFAULT_DB_PATH))
    engine = DriftWatchEngine(data_path=data_path)
    llm_config = load_llm_config()
    planner, synthesis, planner_mode = build_models(llm_config)

    # Seed the product surface from the engine (identity + episodes only).
    for m in engine.list_merchants():
        db.upsert_merchant(m["merchant_id"], m["dominant_category"], m["dominant_geo"],
                           m["first_day"], m["last_day"])
    for ep in engine._episodes.values():
        db.upsert_episode(ep.to_dict())

    app = FastAPI(
        title="Drift Watch — Risk Ops",
        description=("Post-onboarding merchant risk-drift detection, agentic investigation, "
                     "and human-in-the-loop review. Recommendations only — no autonomous "
                     "account actions, ever."),
        version="5.0.0",
    )

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": f"{exc.kind} not found: {exc.identifier}"})

    @app.exception_handler(ConflictError)
    async def _conflict(_: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": exc.message})

    def _persist_investigation(result, record):
        db.insert_investigation(record)
        for ev in result.registry.all():
            db.insert_evidence(record["investigation_id"], ev.to_dict())
        for event in result.audit_trail.events():
            db.insert_audit_event(record["investigation_id"], record["episode_id"], event.to_dict())

    def _investigation_response(record):
        return {
            "investigation": record,
            "evidence": db.evidence_for(record["investigation_id"]),
            "audit_events": [e for e in db.audit_for_episode(record["episode_id"])
                             if e["investigation_id"] == record["investigation_id"]],
        }

    # ---------------- health ----------------

    @app.get("/health", response_model=schemas.HealthResponse)
    def health():
        n_inv = db.query_one("SELECT COUNT(*) AS c FROM investigations")["c"]
        return {"status": "ok", "merchants": len(engine.merchants),
                "episodes": len(engine._episodes), "llm_provider": llm_config["provider"] or "none",
                "database": db.path, "investigations": n_inv}

    # ---------------- merchants ----------------

    @app.get("/merchants", response_model=schemas.MerchantsResponse)
    def merchants():
        rows = db.query("SELECT * FROM investigations ORDER BY created_at")
        decisions = db.query("SELECT decision FROM human_decisions")
        summary = {
            "merchants_monitored": len(engine.merchants),
            "episodes_detected": len(engine._episodes),
            "investigations_run": len(rows),
            "pending_human_review": sum(1 for r in rows if r["approval_status"] == "PENDING_HUMAN_REVIEW"),
            "escalations_recommended": sum(1 for r in rows if r["recommendation"] == "ESCALATE"),
            "approved": sum(1 for d in decisions if d["decision"] == "APPROVE"),
            "overridden": sum(1 for d in decisions if d["decision"] == "OVERRIDE"),
        }
        return {"summary": summary, "merchants": engine.list_merchants()}

    @app.get("/merchants/{merchant_id}", response_model=schemas.MerchantDetailResponse)
    def merchant_detail(merchant_id: str):
        try:
            return engine.merchant_detail(merchant_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/merchants/{merchant_id}/episodes", response_model=schemas.EpisodesResponse)
    def merchant_episodes(merchant_id: str):
        try:
            eps = engine.list_episodes(merchant_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        latest = {e["episode_id"]: db.latest_investigation(e["episode_id"]) for e in eps}
        return {"merchant_id": merchant_id, "episodes": eps, "latest_investigations": latest}

    # ---------------- episodes ----------------

    @app.get("/episodes/{episode_id}", response_model=schemas.EpisodeDetailResponse)
    def episode_detail(episode_id: str):
        try:
            ep = engine.episode_detail(episode_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"episode": ep, "latest_investigation": db.latest_investigation(episode_id),
                "human_decisions": db.decisions_for(episode_id)}

    @app.post("/episodes/{episode_id}/investigate", response_model=schemas.InvestigateResponse)
    def investigate(episode_id: str):
        try:
            result, record = engine.investigate(episode_id, planner, synthesis, planner_mode)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        # The Phase 4 loop names an investigation INV-<episode_id>; keep that
        # stable for the first run and suffix re-investigations so each run
        # is a distinct, auditable record.
        prior_runs = db.query_one(
            "SELECT COUNT(*) AS c FROM investigations WHERE episode_id=?", (episode_id,))["c"]
        if prior_runs:
            record["investigation_id"] = f"{record['investigation_id']}-R{prior_runs + 1}"
        _persist_investigation(result, record)
        db.upsert_episode(engine.episode_detail(episode_id))
        return _investigation_response(record)

    def _record_decision(episode_id: str, decision: str, reviewer_reason: str):
        try:
            engine.episode(episode_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        investigation = db.latest_investigation(episode_id)
        if investigation is None:
            raise ConflictError("No investigation exists for this episode yet - run investigate first.")
        if db.decision_exists(investigation["investigation_id"]):
            raise ConflictError("A human decision has already been recorded for investigation "
                                f"{investigation['investigation_id']} - decisions are final and "
                                "cannot be changed or bypassed.")
        recorded = engine.human_decision(decision, reviewer_reason,
                                         _recommendation_enum(investigation["recommendation"]))
        decision_row = {
            "investigation_id": investigation["investigation_id"], "episode_id": episode_id,
            "decision": recorded.decision, "reviewer_reason": recorded.reviewer_reason,
            "original_recommendation": recorded.original_recommendation.value,
            "decided_at": engine.now_iso(),
        }
        db.insert_human_decision(decision_row)
        approval_status = {"APPROVE": "APPROVED", "OVERRIDE": "OVERRIDDEN",
                           "REQUEST_MORE_EVIDENCE": "REQUEST_MORE_EVIDENCE"}[decision]
        db.update_investigation_approval(investigation["investigation_id"], approval_status)
        db.append_audit_event(episode_id, investigation["investigation_id"], "human_decision",
                              {"decision": decision_row["decision"],
                               "reviewer_reason": decision_row["reviewer_reason"],
                               "original_recommendation": decision_row["original_recommendation"],
                               "note": ("Recorded human decision. The system does not execute "
                                        "account actions - an ESCALATE recommendation and even an "
                                        "APPROVE decision only update the review record; any "
                                        "account action is taken by humans outside this system.")},
                              decision_row["decided_at"])
        investigation = db.investigation(investigation["investigation_id"])
        return {
            "investigation": investigation,
            "decision": decision_row,
            "audit_events": [e for e in db.audit_for_episode(episode_id)
                             if e["investigation_id"] == investigation["investigation_id"]],
        }

    @app.post("/episodes/{episode_id}/approve", response_model=schemas.HumanDecisionResponse)
    def approve(episode_id: str, body: schemas.HumanDecisionRequest):
        return _record_decision(episode_id, "APPROVE", body.reviewer_reason)

    @app.post("/episodes/{episode_id}/override", response_model=schemas.HumanDecisionResponse)
    def override(episode_id: str, body: schemas.HumanDecisionRequest):
        return _record_decision(episode_id, "OVERRIDE", body.reviewer_reason)

    @app.post("/episodes/{episode_id}/request-evidence", response_model=schemas.HumanDecisionResponse)
    def request_evidence(episode_id: str, body: schemas.HumanDecisionRequest):
        return _record_decision(episode_id, "REQUEST_MORE_EVIDENCE", body.reviewer_reason)

    @app.get("/episodes/{episode_id}/audit", response_model=schemas.AuditResponse)
    def episode_audit(episode_id: str):
        try:
            engine.episode(episode_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"episode_id": episode_id, "events": db.audit_for_episode(episode_id),
                "human_decisions": db.decisions_for(episode_id)}

    # ---------------- frontend (built React app, if present) ----------------
    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


def _recommendation_enum(value: str):
    from agent.models import Recommendation
    return Recommendation(value)


def __getattr__(name):
    """Lazily build the module-level app (engine load + DB seed take a few
    seconds and create the SQLite file) so that `uvicorn backend.main:app`
    works while importing `backend.main` for tests stays side-effect free."""
    if name == "app":
        return create_app()
    raise AttributeError(name)
