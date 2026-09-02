# Episode Model — Task Brief Step 2

## What a Risk Episode is

A `RiskEpisode` (`episode/model.py`) represents a continuous/related period
of behavioral drift for one merchant — the primary object of this phase,
replacing independent day-level `RiskCase`s as the thing a human reviewer
actually looks at.

## Fields

| Field | Meaning |
|---|---|
| `episode_id` | `DW-<merchant_id>-<start_day>`, deterministic and unique. |
| `merchant_id`, `start_day`, `current_day`, `end_day` | `end_day` is `None` until the episode is `RESOLVED`, at which point it's the day the episode formally closed (not the last flagged day — see below). |
| `status` | One of `WATCH` / `INVESTIGATING` / `ESCALATE` / `RESOLVED` — see `docs/STATE_MACHINE.md`. |
| `trigger_events` | The detector's own flagged days that fall within this episode span — the raw material the episode was built from. |
| `signal_groups` | Every independent signal group (`detection/signal_taxonomy.py`) that has EVER shown `trigger` evidence anywhere in this episode — accumulates monotonically, never shrinks. |
| `peak_day` / `peak_score` | The day and value of the highest confidence score ever reached in this episode's trajectory. |
| `confidence_history` | Append-only `[(day, score, status), ...]` — the full trajectory, never overwritten. |
| `evidence_timeline` | Append-only list of **changes** (new evidence, a duty-cycle crossing "sustained," contradicting evidence appearing/resolving) — deliberately NOT one entry per day per signal group (see task brief step 7 / `docs/EPISODE_EVIDENCE.md`). |
| `supporting_evidence` / `contradicting_evidence` / `missing_evidence` | The CURRENT (latest-day) snapshot of evidence for each category — what a reviewer would see if they opened the case today. |
| `hypothesis_a` / `hypothesis_b` | Same fixed text used by the single-day case builder (`agents/case_builder.py::HYPOTHESIS_A_TEXT/B_TEXT`) — kept identical so day-level and episode-level cases describe the same two explanations. |
| `recommended_action` | The action text from `agents.confidence.decide_action` at the episode's current confidence. |
| `transition_log` | Every state change, with old/new state, day, a reason built from structured data, confidence, and the evidence keys that drove it (task brief step 20). |
| `resolution` | `{"day", "outcome", "reason"}` — set only once `RESOLVED`; `outcome` is the last non-`RESOLVED` status the episode reached (e.g. an episode that peaked at `ESCALATE` and then quieted down still resolves with `outcome="ESCALATE"`, not "WATCH", preserving what actually happened). |

## Start, peak, and resolution (task brief step 9)

- **START**: the first day in the episode's flagged-day cluster (`episode/grouping.py::group_into_episodes`'s `start_day`).
- **PEAK**: the day with the highest confidence score anywhere in `confidence_history` — tracked as a running max while the episode is built, so it reflects the true peak even if confidence later declines.
- **RESOLUTION**: NOT the last flagged day. An episode formally resolves `GAP_TOLERANCE_DAYS + 1` days after its last flagged day (or at the end of the merchant's available history, whichever comes first) — i.e. once enough quiet days have passed that a new flagged day, if one occurred, would start a genuinely new episode rather than extend this one (see `episode/grouping.py`'s gap-tolerance rationale). This means an episode's `end_day` is always a few days later than its last `trigger_event`, by design — the system needs to see the quiet period actually hold before calling something resolved.

## Relationship to the existing (Phase 1/2) day-level system

Nothing about `detection/drift_detector.py`, `agents/evidence.py`, or
`agents/confidence.py` changed in this phase. `RiskEpisode` is built by
`episode/builder.py`, which calls the SAME `compute_confidence` function
used by single-day cases — only what evidence gets fed into it differs
(episode-aggregated, via `episode/aggregation.py`, vs. single-day, via
`agents/investigators.py`). Single-day `agents/case_builder.py::build_case`
still exists and is still correct for what it does; episodes are the
better lens for anything spanning more than one day, which is most real
risk activity.
