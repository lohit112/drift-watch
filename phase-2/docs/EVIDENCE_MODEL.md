# Evidence Model — Task Brief Step 2

## The problem this fixes

Phase 1 found (PHASE_1_REPORT.md §9) that the investigators recomputed
their own 5-day trailing-average baseline/recent windows, independent of
the detector's own per-day z-score. On the flagship demo merchant (M0021,
fraud-drift, day-1 onset flagged on day 178), this meant a genuine,
statistically significant detector flag got diluted into "no supporting
evidence" purely because the investigators' averaging window still
contained mostly pre-drift days. The system's own evidence contradicted
its own detector, and it wasn't visible *why* — the mismatch was implicit
in two different pieces of code computing two different numbers for "the
same thing."

**The fix is not to force the investigators to agree with the detector.**
It's to make explicit what kind of evidence each observation actually is,
so a reviewer (or the case builder) can see a genuine detector-strength
signal on day 1 that simply hasn't been corroborated by persistence yet —
which is a true, honest state of the world — rather than a single
undifferentiated "supports_risk: true/false" bit.

## The five evidence types

Implemented in `agents/evidence.py` (the `Evidence` dataclass) and produced
per signal group by `agents/investigators.py::build_signal_evidence`:

| Type | What it answers | Source |
|---|---|---|
| **TRIGGER** | What exactly caused the alert? | The detector's own flagged-day observation vs. its own `baseline_mean_<feat>`/`baseline_std_<feat>` (see `detection/drift_detector.py`) — **never recomputed independently**. This is the core fix: trigger evidence is now, by construction, the same z-score the detector flagged on. |
| **CONTEXTUAL** | Is this persisting, or was it a one-day blip? | 3-day and 7-day trailing averages ending on the flagged day, compared against the SAME baseline the trigger used (not a re-derived one). |
| **HISTORICAL** | Has this specific merchant shown this before? | Count of prior days (before the flagged day) where this same feature crossed the z-threshold, anywhere in this merchant's own history. |
| **CONTRADICTING** | What *didn't* move that plausibly should have? | Any signal group that did NOT deviate at the trigger day — a coordinated risk episode plausibly touches multiple dimensions, so a quiet dimension is itself evidence (for Hypothesis B). |
| **MISSING** | What couldn't be assessed at all? | Emitted instead of the above when a merchant has fewer than `MIN_BASELINE_DAYS=15` days of history for a feature. Never silently treated as "no risk" — always visible, and it caps confidence (`agents/confidence.py`) rather than being averaged away. |

Each `Evidence` object carries `source`, `signal_group`, `evidence_type`,
`observation`, `baseline`, `deviation`, `time_window`, `direction`,
`strength`, `supports_hypothesis` (`"A"`/`"B"`/`None`),
`contradicts_hypothesis`, `confidence` (the evidence item's own
reliability, distinct from the case's overall Risk Confidence Score), and
a human-readable `summary` — structured fields throughout, not vague
natural-language strings (task brief step 13).

## Why "what triggered" and "what supports" are kept distinct

A case's `to_dict()` output (see `agents/case_builder.py`) exposes
`deviant_signal_groups` (what triggered the Sentinel flag) and
`evidence_for_a`/`evidence_for_b` (what the investigation subsequently
found) as separate fields. This is deliberate: a merchant can trigger on
day 1 of a real drift with weak persistence evidence (correctly landing in
`REQUEST_MORE_EVIDENCE` — see the Confidence Model doc) and then, a few
days later on the same underlying episode, show strong contextual/temporal
persistence and correctly `ESCALATE`. Collapsing "triggered" and
"supports" into one bit would have hidden that this is a *timeline*, not a
single static fact.

## Multi-temporal windows (task brief step 3): why each window exists

| Window | Used for | Why this window |
|---|---|---|
| Trigger (single day) | All 5 signal groups | The detector's unit of decision is one day; evidence must start there. |
| Short-term (3-day) | All 5 signal groups, but most informative for fast-moving signals (volume, dispute) | Distinguishes a genuine step-change from a single noisy day; 3 days is short enough not to dilute a fast-ramping fraud onset (see the `fraud`/`temporary_anomaly` archetypes, which ramp over 3-4 days). |
| Medium-term (7-day) | All 5 signal groups, most informative for slower-moving signals (refund, category/geo mix) | Category and geography mix changes (a merchant genuinely pivoting product lines) are inherently noisier day-to-day than transaction counts; a week smooths that out without hiding a real pivot. |
| Historical (entire prior history) | Novelty scoring | Answers a different question than either window above: not "is this happening now" but "has this ever happened to this specific merchant before." A merchant with 3 prior refund spikes that all turned out to be nothing is different from one seeing this for the first time in 178 days. |

Windows deliberately differ per task brief step 3's instruction not to
blindly apply one window to every signal — but in this implementation both
3-day and 7-day windows are computed for every signal group (rather than
picking one window per group), so contextual evidence carries both a fast
and a slow read and the confidence model (`temporal_persistence`
component) can see whether a deviation shows up at either or both scales.

## Known limitations (not hidden)

- Contextual/historical windows are computed the same way for every signal
  group; the "choose windows appropriate to the signal" instruction is
  satisfied by presenting both a 3-day and 7-day view for every group
  rather than hand-picking a single bespoke window per group — a
  reasonable simplification, but a real one, not a fully bespoke design.
- CONTRADICTING evidence treats all 5 signal groups as equally
  "risk-relevant" (`RISK_RELEVANT_GROUPS` in `agents/investigators.py`) —
  in reality a pure refund-driven risk episode might not be expected to
  move geography at all, so a quiet geography reading isn't equally
  informative in every case. This is a real simplification, documented
  rather than silently assumed away.
- CUSTOMER_BEHAVIOR and SETTLEMENT/PAYMENT taxonomy dimensions have no
  evidence type implemented at all — see `detection/signal_taxonomy.py`'s
  `UNCOVERED_DIMENSIONS` and PHASE_2_REPORT.md.
