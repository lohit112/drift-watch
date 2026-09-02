# Audit Report — Session 2, Aug 21 2026

Independent re-verification of session-1 claims before extending the system. All numbers below were reproduced by actually rerunning the scripts, not copied from PROJECT_STATE.md.

## 1. Current architecture (as built)
`synthetic_generator.py` → `drift_detector.py` (merchant-specific z-score baseline, static-threshold comparator) → `investigators.py` (4 deterministic evidence functions) → `case_builder.py` (rule-based correlation + hypothesis generation) → printed JSON case. No backend, no frontend, no persistence, no real LLM call.

## 2. What actually works (reproduced)
- Data generation is deterministic (seeded RNG) — reran, byte-identical merchant counts per archetype.
- Detection reruns produce the same 81/5760 flagged merchant-days, same precision/recall/F1 table as claimed in PROJECT_STATE.md. **Confirmed, not fabricated.**
- End-to-end demo case script runs without errors and produces a structured case for both a fraud-drift and a seasonal merchant.

## 3. What does not work / is missing
- No frontend, backend, or database — CLI/JSON only.
- Case builder is not agentic in the "genuine planning" sense — it runs all four investigators unconditionally every time, rather than deciding which evidence to gather based on the drift signal type. This directly contradicts the "don't fake agents" requirement — right now it's closer to a fixed pipeline than a planner.
- No real LLM integration exists anywhere in the pipeline.
- No automated tests exist (`tests/` is empty).

## 4. Bugs found this audit
1. **Confidence formula is arbitrary.** `confidence_risk = min(0.95, 0.15 + 0.22 * n_risk_signals)` has no defensible derivation — the constants 0.15 and 0.22 were picked to "look reasonable," not fit to anything. This is a legitimate criticism a Razorpay ML engineer would raise immediately. **Fixed this session — see below.**
2. **Evaluation is day-level, not event-level**, which the original methodology doc even flagged as a simplification. Precision/recall/F1 are computed by treating every drifted day as an independent labeled example, which double-penalizes (or double-rewards) detectors within a single multi-day drift event. A merchant with one 20-day fraud episode contributes 20 "positive" rows even though it's one event. **Partially fixed this session — added true event-level recall/latency, see below. Day-level metrics kept alongside for comparison, both now clearly labeled.**
3. **Planner doesn't actually plan.** All 4 investigators always run, regardless of which signal group triggered the flag (e.g. a pure "refund" trigger still runs the Geography Investigator). This is real technical debt against the "genuine agentic decision-making" requirement, not fixed this session — flagged as the top priority for next iteration (see below).

## 5. Evaluation weaknesses
- Day-level recall (15.4%) looked worse than it actually is because of bug #2. Event-level recall (below) is the number that should headline the README and pitch, not the day-level one.
- No cross-validation against multiple random seeds — one synthetic dataset instance. A judge could reasonably ask "did you get lucky with this seed?" Not resolved this session; flagged for next.

## 6. Security weaknesses
Unchanged from session 1 — no real LLM integration exists yet, so prompt-injection testing is still not meaningful. See SECURITY.md.

## 7. Product weaknesses
No UI means the "case as a reviewable artifact" pitch can't actually be shown to a judge yet — this is the single highest-leverage missing piece for demo impact specifically (as opposed to technical credibility, where the planner issue is highest-leverage).

## 8. Agentic-AI weaknesses
This is the most important finding of this audit: **the system currently behaves like a fixed pipeline dressed up as agents, not a planner making genuine tool-selection decisions.** This was flagged as a known limitation in session 1 (PROJECT_STATE.md open issue #2, re: rule-based case builder) but this audit is making it explicit and prioritized correctly — it's a P0 correctness-of-claims issue, not a P1/P2 nice-to-have. If this ships to a judge unfixed, "agentic" would be an overstatement of what the code does.

## 9. UX / 10. Deployment weaknesses
Both zero — nothing built yet in either area. Unchanged from session 1, correctly tracked there.

## 11. Biggest competitive weaknesses (ranked)
1. Case builder isn't a real planner (agentic-depth claim currently overstated)
2. No UI (demo impact)
3. Confidence formula was arbitrary (fixed this session)
4. Day-level-only evaluation understated real performance (partially fixed this session)
5. No real LLM in the loop at all yet

## 12. Highest-value next improvements (this session's priority order)
1. Fix the confidence formula (defensible components, documented) — **done below**
2. Add true event-level evaluation metrics alongside day-level — **done below**
3. Make the planner actually plan — selectively skip investigators when the triggering signal group makes them clearly irrelevant — **deferred to next session, documented in PROJECT_STATE.md as the new #1 priority, replacing the recall item since event-level recall reframes that as less urgent than believed**
