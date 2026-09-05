# Drift Watch

**Autonomous merchant risk-drift detection & investigation agent — a buildathon prototype inspired by publicly documented Razorpay engineering/product challenges. Not affiliated with, endorsed by, or built using any non-public Razorpay data or systems.**

## Problem

Merchant risk review at payment platforms happens almost entirely at onboarding. Razorpay's own engineering blog describes their internal onboarding-risk system (Bumblebee) handling 10,000-12,000 manual-equivalent reviews a month — but once a merchant is approved, there's no publicly documented system that continuously re-evaluates behavior afterward. Risk is not static: a legitimate merchant can be compromised, pivot into riskier activity, or begin laundering through a previously clean account, and none of that surfaces until damage has already accumulated.

## Solution

Drift Watch continuously monitors already-approved merchants against **their own historical baseline** (not a single global threshold), detects correlated behavioral drift across transaction, refund/dispute, geography, and category-mix signals, groups flags into stateful risk episodes, investigates each episode with an evidence-seeking agent, weighs competing hypotheses (risk drift vs. legitimate growth vs. seasonal pattern), and produces a grounded, fully-cited case — with a recommendation that **always** requires human approval.

**Why behavioral drift matters:** a bare anomaly score can't distinguish a Diwali sale from account compromise, and onboarding review can't see post-onboarding pivots. Drift is the observable signature of both; the hard part is explaining it — which requires evidence, competing hypotheses, and a human.

## Architecture

```
Detection (Phase 1)          merchant-specific rolling baseline + z-scores,
                             independent signal-domain correlation
        ↓
Risk Episode (Phase 3)       grouping, state machine, confidence trajectory
        ↓
Agentic Investigation (P4)   evidence-seeking planner → typed tools →
                             bounded loop with hard budget
        ↓
Evidence                     stable EVID-xxx registry, traceable to source tool
        ↓
Competing Hypotheses         RISK_DRIFT / LEGITIMATE_GROWTH / SEASONAL_PATTERN
                             / INSUFFICIENT_EVIDENCE (Phase 2 confidence math)
        ↓
Grounded Synthesis           every claim cites registered evidence; unsupported
                             citations are rejected, not kept
        ↓
Recommendation               MONITOR / REQUEST_MORE_EVIDENCE / ESCALATE —
                             computed by deterministic rules, never by an LLM
        ↓
Human Approval               every ESCALATE starts PENDING_HUMAN_REVIEW;
                             record_human_decision is the only transition
        ↓
Audit Trail                  ordered, persisted events for every step
```

The Phase 5 product layer (FastAPI backend + SQLite + React dashboard) **calls this existing engine** and duplicates none of its logic. Phase 5 also adds a pluggable LLM adapter behind the planner/synthesis interfaces — the deterministic implementations remain the default and the fallback (see "Real LLM adapter" below).

## Repository layout

```
drift-watch/
├── data/              synthetic generator + generated events (24 merchants, 240 days)
├── detection/         statistical drift layer (Phase 1)
├── agents/            investigators, confidence model, case builder (Phases 1-2)
├── episode/           grouping, state machine, aggregation, builder (Phase 3)
├── agent/             agentic investigation layer (Phase 4)
├── backend/           Phase 5: FastAPI app, engine adapter, SQLite, LLM adapter
├── frontend/          Phase 5: React + Vite Risk Ops dashboard
├── evaluation/        evaluation harness + real multi-seed results (CSVs)
├── research/          competitive/product research
├── docs/              design docs (confidence model, evidence model, state
│                      machine, temporal windows, Phase 4 architecture)
├── tests/             102 tests (Phases 1-4 regression + Phase 5 API/persistence/LLM/security)
├── scripts/           Phase 1 demo script
├── PHASE_1..5_*.md    per-phase reports (historical, unedited)
├── PROJECT_STATE.md   current state, honest self-assessment
└── DECISIONS.md       decision log D1-D11
```

## Quickstart

```bash
# 1. Backend (Python 3.11+)
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
# → http://127.0.0.1:8000  serves the API AND the built dashboard

# 2. Frontend (only if you want to rebuild it or develop on it; Node 18+)
cd frontend && npm install && npm run build   # build → served by the backend
cd frontend && npm run dev                    # or: dev server on :5173, API proxied to :8000

# 3. Use it
open http://127.0.0.1:8000            # Risk Ops dashboard
open http://127.0.0.1:8000/docs       # OpenAPI / Swagger
```

The SQLite database is created automatically (`backend/drift_watch.db`, override with `DRIFT_WATCH_DB`). No other infrastructure is required.

## Backend API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness + counts + configured LLM provider |
| GET | `/merchants` | monitored merchants + dashboard summary metrics |
| GET | `/merchants/{id}` | identity, episodes, daily behavioral timeline |
| GET | `/merchants/{id}/episodes` | episodes + latest investigation per episode |
| GET | `/episodes/{id}` | episode detail + latest investigation + decisions |
| POST | `/episodes/{id}/investigate` | runs the existing Phase 4 investigation loop, persists evidence + audit |
| POST | `/episodes/{id}/approve` | records a human APPROVE decision (requires reviewer reason) |
| POST | `/episodes/{id}/override` | records a human OVERRIDE decision |
| POST | `/episodes/{id}/request-evidence` | records a REQUEST_MORE_EVIDENCE decision |
| GET | `/episodes/{id}/audit` | persisted audit trail (investigation events + human decisions) |

Errors: 404 unknown merchant/episode, 409 conflict (no investigation yet, or a final human decision already recorded — decisions are final), 422 validation. There is deliberately **no** endpoint that executes an account action — approving an escalation updates the review record only.

## Environment configuration

Copy `.env.example` to `.env` (git-ignored) or export the variables:

```
DRIFT_WATCH_LLM_PROVIDER=none      # none (default, fully deterministic) | openai
DRIFT_WATCH_LLM_MODEL=             # model name for the provider
DRIFT_WATCH_LLM_API_KEY=           # credentials come ONLY from the environment
DRIFT_WATCH_LLM_BASE_URL=          # any OpenAI-compatible endpoint
DRIFT_WATCH_LLM_TIMEOUT=20
DRIFT_WATCH_DB=                    # optional SQLite path override
```

## Real LLM adapter (pluggable, safe by construction)

`backend/llm.py` implements `PlannerModel` and `SynthesisModel` behind the existing Phase 4 interfaces. Guarantees:

- **The deterministic implementations remain the default and the fallback** — on missing credentials, network failure, timeout, malformed JSON, schema violation, or a tool outside the planner's allowlist, the system silently falls back and records why. The product runs fully without any API access.
- The LLM planner may only select tools from the explicit allowlist; it executes nothing (the loop still enforces budgets and failure policy).
- The LLM synthesis model writes only narrative prose, may cite only registry evidence IDs, and its output passes the same grounding check as the deterministic template — invented citations are rejected from the case.
- **The recommendation is always computed by the shared deterministic rule** (`agent.synthesis.recommendation_for`); the model never touches decision math.
- Merchant-controlled text is sanitized before entering any prompt; untrusted merchant-derived text can never become trusted system instructions.

**Honest status:** the adapter is production-shaped and fully tested against a fake transport; no live provider call was made during development (no credentials available), so no real LLM integration is claimed. With `DRIFT_WATCH_LLM_PROVIDER=none` (default) the system is 100% deterministic.

## Demo flow (deterministic — safe for a live presentation)

1. Start the backend (`uvicorn backend.main:app --port 8000`), open `http://127.0.0.1:8000`
2. Dashboard → summary metrics + merchant table; select **M0021**
3. Merchant detail → healthy history, then the detected behavioral drift (flagged days marked); open episode **DW-M0021-0178**
4. Click **Investigate** → planner/tool activity appears (transaction → refund/dispute → mix)
5. Evidence registry: supporting / contradicting / missing, each cited by EVID-xxx
6. Competing hypotheses with scores; grounded synthesis narrative; **ESCALATE** recommendation
7. Approval shows **PENDING_HUMAN_REVIEW** — with the explainer that the system cannot act
8. Enter a reviewer reason → **Approve** (or Override / Request more evidence) → decision recorded
9. Audit trail shows every step, including the recorded human decision

Repeat investigations are deterministic; M0009 (seasonal merchant) demonstrates REQUEST_MORE_EVIDENCE, and overriding it demonstrates the review path.

## Test command

```bash
python -m pytest tests/ -q      # 102 tests: Phases 1-4 regression + Phase 5 API/persistence/LLM/security
```

## Safety model & human approval boundary

- No autonomous account action exists anywhere in the codebase — not as an endpoint, not as a code path. ESCALATE is a *recommendation for review*, surfaced with an explainer in the UI.
- Every recommendation starts `PENDING_HUMAN_REVIEW`. Only the explicit, externally-invoked `record_human_decision` changes an approval status; decisions are final and immutable once recorded.
- Failed tools never become risk evidence; missing evidence pulls toward REQUEST_MORE_EVIDENCE, never toward ESCALATE.
- The investigation loop is bounded by hard budgets (tool calls + iterations) that no planner output can exceed.
- Ground truth labels (`archetype`, `drift_kind`, `true_drift`) are structurally unreadable by tools and never leave the evaluation layer — the product cannot leak them.

## What is synthetic / what is real

- **Synthetic:** all merchant data (`data/synthetic_generator.py`, 24 merchants × 240 days, 6+ archetypes with ground-truth labels). No real Razorpay API, production data, or partnership is used or claimed anywhere.
- **Real:** the statistics, evaluation numbers, and multi-seed results in `evaluation/` are computed by the actual code on that data — see `evaluation/MULTI_SEED_EVALUATION.md` and `evaluation/EPISODE_EVALUATION.md` for honest numbers including where the system underperforms a static-threshold comparator.

## Current limitations

- All data is synthetic; no production integration exists or is claimed.
- The LLM adapter is unexercised against a live provider (no credentials during development); the deterministic fallback is the shipped behavior.
- The agent layer is deliberately conservative on narrow episodes (some deviant groups, quiet groups uninvestigated → REQUEST_MORE_EVIDENCE rather than ESCALATE) — see PHASE_4_FINAL.md.
- Seasonal-merchant false escalation persists at the deterministic episode layer (DECISIONS.md D10); the agent layer mitigates but does not fix it.
- SQLite + single-process uvicorn: a demo-grade persistence tier, not a production one.
- Day-level recall on the richer benchmark is genuinely weak and honestly reported (evaluation/MULTI_SEED_EVALUATION.md).
