# Drift Watch

**Continuous post-onboarding merchant risk-drift detection and evidence-based investigation.**

Drift Watch is a fintech risk-engineering prototype that monitors already-approved merchants for behavioral change, groups related anomalies into risk episodes, investigates suspicious episodes with a bounded evidence-seeking agent, and produces an evidence-grounded recommendation for human review.

The project uses synthetic merchant data. It is an independent prototype: it does not use private Razorpay data or systems and does not claim production deployment.

## Why this problem

A merchant can be legitimate at onboarding and become materially different months later because of account compromise, a business-model change, unusual refund/dispute behavior, geographic expansion, or seasonality. A single anomaly score does not explain which explanation is most plausible.

Drift Watch separates the problem into detection, episode formation, evidence gathering, competing-hypothesis reasoning, case synthesis, and human review.

## Architecture

```text
Merchant event stream
        |
        v
Merchant-specific drift detection
        |
        v
Risk episode grouping + state machine
        |
        v
Bounded agentic investigation
        +--> planner
        +--> typed investigation tools
        +--> evidence registry
        +--> competing hypotheses
        +--> sufficiency evaluation
        |
        v
Grounded case synthesis
        |
        v
Recommendation
        |
        v
Human review
        |
        v
Persisted audit trail
```

The Phase 5 product layer wraps this engine with FastAPI, SQLite, and a React/Vite Risk Ops dashboard. It calls the existing reasoning code rather than duplicating it.

## What is implemented

### Detection

The detector compares merchant behavior with the merchant's own historical baseline and keeps correlated features in explicit signal groups such as volume, refund/dispute, category mix, and geography. Historical calculations are constrained to past observations to avoid temporal leakage.

### Risk episodes

Flagged observations are grouped into persistent episodes with temporal boundaries, confidence trajectory, evidence aggregation, and state transitions. This addresses the failure mode where one persistent incident oscillates between day-level decisions.

### Agentic investigation

Phase 4 adds a bounded investigation loop. The planner starts from the episode trigger, selects explicit tools, records evidence with stable IDs, evaluates competing hypotheses, and stops when evidence is sufficient or the investigation budget is exhausted.

The hypothesis set is:

- `RISK_DRIFT`
- `LEGITIMATE_GROWTH`
- `SEASONAL_PATTERN`
- `INSUFFICIENT_EVIDENCE`

A failed tool call cannot increase risk, and unexplored hypotheses are not treated as evidence against themselves.

### Grounded synthesis

Evidence items carry stable `EVID-xxx` IDs and provenance. Narrative claims are checked against the registry; unsupported evidence references are rejected. Recommendation logic remains deterministic and outside free-form model generation.

### Human approval

`ESCALATE` is a recommendation for human review. The system does not expose an account-suspension or other executable merchant-action endpoint. Review actions are persisted and audited.

## Phase 5 product

The final product adds:

- FastAPI backend
- SQLite persistence
- React + Vite Risk Ops dashboard
- merchant and episode views
- investigation activity
- evidence and hypothesis views
- human review actions
- persisted audit trail
- pluggable LLM adapter with deterministic fallback

The default configuration is deterministic and does not require external API access.

## Evaluation

The repository contains event-level, multi-seed, episode-level, baseline, ablation, golden-case, failure-path, API, persistence, and LLM-adapter tests.

The current full automated suite is **102 passing tests**.

The benchmarks are intentionally reported with their tradeoffs. Drift Watch does not universally beat the static comparator: on the richer benchmark, it improves recall/false-alert behavior but has lower precision/F1 and slower average detection latency. Episode grouping also does not improve raw precision/F1. These results are preserved rather than optimized away.

## Development workflow

The project was developed iteratively against a real local repository. Python and pytest were used for the detection, episode, agent, API, persistence, and failure-path checks; the React/Vite frontend was built separately and then exercised through the FastAPI application. Claude Code and ZCode were used as coding-agent environments during implementation, but changes were kept reviewable in the repository and validated with deterministic tests and local runs.

The useful engineering record is the code, tests, evaluation artifacts, Git commits, decisions, and documented reversals—not an assumption that the first implementation was correct.

## Development evolution

```text
Phase 1  -> correctness audit + leakage prevention
Phase 2  -> structured evidence + confidence + evaluation
Phase 3  -> stateful risk episodes
Phase 4  -> bounded agentic investigation
Phase 5  -> backend + persistence + Risk Ops UI
```

The repository intentionally keeps the engineering record visible. Important failures and fixes are summarized in `CHANGELOG.md` and `DECISIONS.md`; the phase reports retain deeper evidence and historical measurements.

### What went wrong, and what changed

Examples from the actual build:

- The comparison baseline had temporal leakage. It was replaced with a history-only computation and the changed benchmark numbers were kept.
- The first demo could attach evidence from the wrong drift day. The event/evidence alignment was fixed and regression-tested.
- The original confidence formula was arbitrary. Phase 2 replaced it with a documented multi-component score.
- Persistent episodes could oscillate between decisions. Phase 3 introduced episode-level aggregation and stateful resolution.
- A seasonal merchant exposed an over-escalation edge case. An apparently useful confidence discount broke a real fraud scenario, so it was reverted and the limitation was documented.
- The Phase 4 agent initially double-counted historical evidence and could mistake unexplored hypotheses for negative evidence. Both issues were fixed with regression coverage.

## Security and safety

The system treats merchant-derived text as untrusted, constrains tool execution, validates model output before use, rejects unsupported evidence citations, bounds investigation iterations/tool calls, and requires an explicit human decision for escalation review.

The LLM adapter is pluggable and tested against fake transports. **No live provider call was made during development**, so the default implementation is deterministic and no live-LLM integration claim is made.

## Repository structure

```text
agent/          bounded agentic investigation
agents/          investigators, evidence, confidence, case building
detection/      statistical drift detection
episode/        risk episode grouping and state machine
evaluation/     benchmarks, ablations, and evaluation harnesses
backend/        FastAPI API, persistence, model adapter
frontend/       React/Vite Risk Ops dashboard
data/           synthetic data and generator
docs/           technical design documentation
research/       product and competitive research
scripts/        runnable utilities
tests/           regression and integration tests
```

## Quick start

### Requirements

- Python 3.11+
- Node.js 18+

### Backend

```bash
pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000` for the dashboard and `http://127.0.0.1:8000/docs` for the API.

### Frontend development

```bash
cd frontend
npm install
npm run build
```

For development with Vite:

```bash
npm run dev
```

The built frontend is served by the backend in the final demo path.

### Tests

```bash
python -m pytest tests/ -q
```

## Demo

The deterministic flagship path is:

```text
Dashboard
  -> M0021
  -> episode DW-M0021-0178
  -> Investigate
  -> planner/tool activity
  -> evidence
  -> competing hypotheses
  -> grounded synthesis
  -> ESCALATE
  -> PENDING_HUMAN_REVIEW
  -> Approve / Override / Request more evidence
  -> Audit trail
```

`python -m agent.demo --merchant M0021` runs the underlying investigation flow from the repository root.

## Documentation

- `PROJECT_STATE.md` — current architecture, evaluation, and limitations
- `DECISIONS.md` — major engineering decisions and reversals
- `CHANGELOG.md` — phase-by-phase improvements and debugging history
- `SECURITY.md` — safety and trust-boundary model
- `PHASE_1_REPORT.md` — correctness foundation and baseline
- `PHASE_2_REPORT.md` — evidence reasoning and evaluation
- `PHASE_3_FINAL.md` — episode intelligence and final cleanup
- `PHASE_4_FINAL.md` — bounded agentic investigation
- `PHASE_5_FINAL.md` — productization and integration

## Known limitations

- All merchant data is synthetic.
- The LLM adapter has not been exercised against a live provider.
- The default planner/synthesis path is deterministic.
- Narrow episodes are conservatively routed toward more evidence.
- Seasonal false escalation remains an open limitation at the deterministic episode layer.
- Episode fragmentation remains non-zero on slow-onset regimes.
- SQLite + single-process Uvicorn is demo-grade rather than production infrastructure.
- The frontend has no authentication or multi-operator authorization.

## Project status

**Phase 1–5 complete — submission candidate.**

This repository is a buildathon prototype and engineering demonstration, not a production fraud, compliance, or account-action system.
