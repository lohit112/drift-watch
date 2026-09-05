# Phase 5 — Final Report (Productization + Demo + Optional Real-LLM Adapter)

_Date: Sep 5, 2026. Starting point: the completed Phase 1-4 codebase (102-test
baseline: 70 Phase 1-4 + Phase 5 additions). Phases 1-4 engine code is
unchanged and remains the source of truth._

## Completion status: **COMPLETE**

Phase 5 turns the existing investigation engine into a runnable Risk Ops
product: a FastAPI backend over the real engine, SQLite persistence, a React
Risk Ops dashboard, a production-shaped LLM adapter with a fully functional
deterministic fallback, security tests, and an end-to-end M0021 demo with
human approval and a persisted audit trail.

## What Phase 5 added

### Backend (P0) — `backend/`
- `main.py` — FastAPI app (factory for testability; lazy module-level app for
  uvicorn). All required endpoints implemented:
  `GET /health`, `GET /merchants`, `GET /merchants/{id}`,
  `GET /merchants/{id}/episodes`, `GET /episodes/{id}`,
  `POST /episodes/{id}/investigate`, `POST /episodes/{id}/approve`,
  `POST /episodes/{id}/override`, `GET /episodes/{id}/audit`, plus
  `POST /episodes/{id}/request-evidence` (the frontend's third review button).
  Typed pydantic response models (`schemas.py`); 404/409/422 error semantics;
  no business logic — the endpoints call the existing engine.
- `engine.py` — thin adapter: loads the dataset through the existing
  `merchant_specific_drift` → `build_episodes_for_merchant` pipeline once,
  indexes episodes, and runs the existing `InvestigationLoop` on demand.
  Ground-truth columns are dropped before any data reaches the product layer.
- **Approval boundary preserved and strengthened:** approve/override/
  request-evidence call the existing `agent.policy.record_human_decision`
  and only RECORD a decision (final and immutable — a second decision on the
  same investigation is a 409). There is no endpoint and no code path that
  executes an account action; a test asserts no such route can exist.

### Persistence (P0) — `backend/db.py`
Simple stdlib-SQLite schema: merchants, episodes, investigations,
investigation_evidence, human_decisions, audit_events. Seeded from the engine
at startup; investigations/evidence/audit events persisted per POST;
human decisions appended as explicit `human_decision` audit events. Tests
verify durability across a fresh connection. No Redis/Kafka/ORM — by design.

### Frontend (P0) — `frontend/` (React + Vite, Razorpay-flavored UI)
- Dashboard: summary metrics (merchants, episodes, investigations,
  escalations, pending review, approved/overridden) + merchant table.
- Merchant detail: identity, behavioral timeline (SVG, per-series normalized,
  detector-flagged days marked, selected episode highlighted), episode list
  with latest recommendation.
- Investigation view: episode summary, planner/tool activity (with budget +
  sufficiency), competing hypotheses with score bars, evidence grouped into
  supporting / contradicting / missing / contextual, grounded synthesis
  narrative, recommendation banner, approval status.
- Human review: Approve / Override / Request-more-evidence with a recorded
  reviewer reason; recorded decisions are displayed and audited.
- **ESCALATE ≠ automatic action is made visually explicit**: a persistent
  topbar note and an autonomy explainer directly under the recommendation
  banner ("the system has no code path to execute an account action").
- Built with zero UI dependencies (react, react-dom only); light fintech
  theme using Razorpay's Blade-style palette (navy #0C2451, brand blue
  #2B84EB). `npm run build` output is served by the backend at `/`;
  `npm run dev` proxies the API for development.

### Real-LLM adapter (P1) — `backend/llm.py`
- `LLMPlanner` / `LLMSynthesis` behind the existing `PlannerModel` /
  `SynthesisModel` interfaces; OpenAI-compatible chat-completions transport
  via stdlib urllib (no new dependency).
- Structured output required (strict JSON); tool selection restricted to the
  context's allowlist; narrative output must cite registry evidence IDs and
  passes the same grounding check as the deterministic template; the
  recommendation is ALWAYS the shared deterministic rule
  (`agent.synthesis.recommendation_for`, extracted verbatim from the
  Phase 4 implementation — its behavior is unchanged and all 70 Phase 1-4
  tests still pass).
- Credentials only via environment variables / git-ignored `.env`
  (`.env.example` provided); no hardcoded keys.
- Deterministic fallback on EVERY failure mode (provider unconfigured,
  network error, timeout, malformed JSON, allowlist violation, empty
  output), with the fallback reason recorded.
- **Honest status:** production-shaped and fully tested against a fake
  transport; no live provider call was made (no credentials in this
  environment), so no real LLM integration is claimed. Default configuration
  is 100% deterministic.

### Security (P1) — extends the Phase 4 model
- Untrusted merchant-derived text is sanitized before entering any LLM
  prompt (tested end-to-end: injected `dominant_category` text never reaches
  a prompt unsanitized and cannot change tool selection, narrative, or
  recommendation).
- Model output is untrusted until validated: malformed JSON, invented tool
  names, and invented evidence citations are all rejected with deterministic
  fallback (each has a dedicated test).
- Human approval cannot be bypassed: invalid decision values raise, decisions
  before an investigation exist → 409, double decisions → 409, and no
  executable-action route exists (tested).
- Failed tools never increase risk (Phase 4 tests) and provider failures
  never change the investigation's safety posture (new test).

### Demo (P1)
The exact 17-step demo flow works end to end against the real engine and is
deterministic (deterministic planner/synthesis by default). Verified live:
backend → dashboard → M0021 → healthy history → drift → episode
DW-M0021-0178 → investigate → planner/tool activity → evidence → hypotheses
→ grounded synthesis → ESCALATE → PENDING_HUMAN_REVIEW → approve/override →
recorded decision → audit trail.

## Tests
- Full suite: **102 passed, 0 failed** (70 Phase 1-4 — all preserved — plus 32 new).
- New: `tests/test_backend_api.py` (14 — endpoints, investigation flow,
  approval/override, audit persistence, no-executable-action routes),
  `tests/test_persistence.py` (4 — schema, durability across reopen),
  `tests/test_llm_adapter.py` (13 — fallback on malformed/network/allowlist
  failures, grounding rejection, deterministic recommendation rule, prompt
  sanitization, approval boundary), plus API-level budget/sufficiency checks.

## Final validation performed
1. `python -m pytest tests/ -q` → 102 passed.
2. Live backend started (uvicorn) and endpoint smoke tests run (health,
   merchants, episode detail, investigate, approve, override, 409/404/422
   paths, audit).
3. Frontend built (`npm run build`) and served by the backend.
4. Complete M0021 demo flow executed via the API and UI.
5. Approve/override verified (final, immutable, audited).
6. Deterministic fallback verified (provider "none" → deterministic stack;
   fake-transport failures → identical-to-deterministic results).
7. Secrets/paths check: no API keys in the repo; no absolute machine-specific
   paths in shipped code (engine resolves repo root relatively; DB path
   overridable via env).

## Files added/changed in Phase 5
- Added: `backend/__init__.py`, `backend/main.py`, `backend/engine.py`,
  `backend/db.py`, `backend/llm.py`, `backend/schemas.py`,
  `frontend/package.json`, `frontend/vite.config.js`, `frontend/index.html`,
  `frontend/src/{main.jsx,App.jsx,api.js,styles.css}`,
  `tests/test_backend_api.py`, `tests/test_persistence.py`,
  `tests/test_llm_adapter.py`, `.env.example`, `.gitignore`,
  `PHASE_5_FINAL.md` (this file).
- Changed: `README.md` (rewritten for the final system), `PROJECT_STATE.md`,
  `requirements.txt` (+fastapi/uvicorn/httpx), `agent/synthesis.py`
  (recommendation rule extracted verbatim into `recommendation_for` — shared
  by deterministic and LLM synthesis; behavior identical, all prior tests
  pass).
- NOT changed: every Phase 1-4 report, the detector, episode engine, agent
  loop, tools, planner, confidence model, evaluation scripts, and data.

## Known limitations
- All data synthetic; no production integration claimed.
- LLM adapter unexercised against a live provider (documented, tested
  against fakes only); deterministic stack is the shipped behavior.
- Single-process uvicorn + SQLite: demo-grade persistence, not production.
- Agent-layer conservatism on narrow episodes and the D10 seasonal
  over-escalation (deterministic layer) carry over from Phase 4 — documented,
  not hidden.
- Frontend is functional/minimal: no auth (single-operator demo), no i18n, no
  automated UI tests (API-level coverage instead).

## Future work (not started, per scope rules)
- Real LLM provider bake-off + adversarial injection suite against the live
  model (the checklist is in docs/PHASE_4_ARCHITECTURE.md "Security").
- Postgres + authn/authz for multi-operator use; WebSocket/poll updates.
- Middle-ground alert queue (INVESTIGATING episodes as low-priority items)
  surfaced in the dashboard.
- Adaptive gap tolerance and seasonal-recurrence specificity (Phase 3
  remaining items).
