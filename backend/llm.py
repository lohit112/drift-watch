"""
Real-LLM adapter (Phase 5) — P1.

Pluggable LLM-backed implementations of the EXISTING Phase 4 interfaces
(`agent.planner.PlannerModel`, `agent.synthesis.SynthesisModel`). The
deterministic implementations REMAIN the default and the fallback: when no
provider is configured, when credentials are missing, on network failure,
on malformed model output, on schema violations, or on tool-allowlist
violations, the deterministic planner/synthesis is used instead. The
product is fully runnable with zero external API access.

TRUST MODEL (extends Phase 4's security model — see docs/PHASE_4_ARCHITECTURE.md
"Security"):
  - LLM output is UNTRUSTED until validated. The planner may only select a
    tool from the context's explicit allowlist (`PlannerContext.available_tools`);
    anything else - including invented tool names - falls back to deterministic.
    The loop still enforces the budget; the adapter executes nothing itself.
  - The synthesis model may ONLY write prose that cites EVID-xxx ids from the
    registry it was given. The grounding check runs over its output exactly as
    over the deterministic template's, and unsupported citations are rejected.
  - The recommendation is NEVER model-generated: it is computed by the same
    deterministic `agent.synthesis.recommendation_for` rule used by the
    deterministic implementation (DECISIONS.md D4: the model never touches
    decision math).
  - Merchant-controlled text (e.g. dominant_category inside evidence
    summaries) is passed through `agent.policy.sanitize_merchant_text` and
    framed as quoted data before entering any prompt - untrusted
    merchant-derived text must never become trusted system instructions.
  - Credentials come ONLY from environment variables (or a git-ignored .env
    file; see .env.example). No keys are hardcoded anywhere.

HONEST STATUS: this adapter is production-shaped and fully exercised by
tests against a FAKE transport. No live provider call was made during
development (no API credentials available in this environment), so no real
LLM integration is claimed. With DRIFT_WATCH_LLM_PROVIDER unset (the
default) the system runs 100% deterministically.
"""
import json
import os
import re
from pathlib import Path
from urllib import request as _urlrequest
from urllib.error import URLError, HTTPError

from agent.models import Recommendation, SufficiencyDecision
from agent.planner import PlannerModel, DeterministicPlanner, InvestigationPlan
from agent.policy import sanitize_merchant_text
from agent.synthesis import (SynthesisModel, DeterministicSynthesis, SynthesizedCase,
                             check_grounding, recommendation_for)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT_SECONDS = 20
MAX_NARRATIVE_CHARS = 4000
MAX_REASON_CHARS = 500

_PLAN_EXAMPLE = '{"selected_tool": "<one of the allowlisted tool names, or null to stop>", "reason": "...", "question": "..."}'
_SYNTH_EXAMPLE = '{"narrative": "..."}'


def _load_dotenv(path=REPO_ROOT / ".env"):
    """Minimal .env loader (KEY=VALUE lines) so a demo can run without
    exporting variables. .env is git-ignored; only .env.example is committed."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_llm_config():
    _load_dotenv()
    provider = os.environ.get("DRIFT_WATCH_LLM_PROVIDER", "none").strip().lower()
    return {
        "provider": provider,
        "model": os.environ.get("DRIFT_WATCH_LLM_MODEL", ""),
        "api_key": os.environ.get("DRIFT_WATCH_LLM_API_KEY", ""),
        "base_url": os.environ.get("DRIFT_WATCH_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "timeout": float(os.environ.get("DRIFT_WATCH_LLM_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))),
    }


def http_post_json(url, headers, payload, timeout):
    """Default transport: OpenAI-compatible POST /chat/completions via
    stdlib urllib (no extra dependency). Injectable in tests."""
    req = _urlrequest.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", **headers})
    with _urlrequest.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _chat(config, transport, messages):
    """Calls the provider and returns the raw text content. Raises on any
    transport-level failure (network, HTTP, timeout, malformed envelope)."""
    content = transport(
        f"{config['base_url']}/chat/completions",
        {"Authorization": f"Bearer {config['api_key']}"},
        {"model": config["model"], "messages": messages, "temperature": 0},
        config["timeout"],
    )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Provider returned an empty/non-text completion")
    return content


def _parse_json_object(text):
    """Strict JSON extraction. Model output is untrusted: reject anything
    that is not a single JSON object (no prose wrapping tolerated beyond a
    single fenced block, which is stripped defensively)."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    obj = json.loads(cleaned)  # raises on malformed output
    if not isinstance(obj, dict):
        raise ValueError("Model output is not a JSON object")
    return obj


class LLMPlanner(PlannerModel):
    """LLM-backed planner. Selects ONLY from the context's allowlist;
    falls back to DeterministicPlanner on every failure mode. The loop's
    budget and failure handling are untouched - this class executes
    nothing."""

    def __init__(self, config=None, transport=http_post_json, fallback=None):
        self.config = config or load_llm_config()
        self.transport = transport
        self.fallback = fallback or DeterministicPlanner()
        self.last_fallback_reason = None

    def plan(self, context):
        try:
            if self.config["provider"] == "none":
                raise ValueError("LLM provider not configured")
            if not self.config["api_key"] or not self.config["model"]:
                raise ValueError("LLM credentials/model missing")
            episode_context = {
                "episode_id": context.episode.episode_id,
                "trigger_signal_groups": sorted(context.episode.signal_groups),
                "start_day": context.episode.start_day,
                "current_day": context.episode.current_day,
            }
            user_payload = {
                "task": ("Choose the next investigation tool, or stop. You are planning an "
                         "evidence-gathering investigation; never select a tool outside the "
                         "allowlist; never try to confirm risk - gather what would discriminate "
                         "between the hypotheses."),
                "episode": episode_context,
                "tools_called": list(context.tools_called),
                "tool_allowlist": list(context.available_tools),
                "budget": context.budget.to_dict(),
                "hypotheses": context.hypothesis_state.to_dict(),
                "respond_with_json": _PLAN_EXAMPLE,
            }
            messages = [
                {"role": "system", "content": (
                    "You are the planner of a merchant risk investigation system. "
                    "Output STRICT JSON only, matching: " + _PLAN_EXAMPLE +
                    " `selected_tool` MUST be either null or a name copied verbatim from "
                    "`tool_allowlist`. Never invent tool names, evidence, metrics, or dates.")},
                {"role": "user", "content": json.dumps(user_payload)},
            ]
            obj = _parse_json_object(_chat(self.config, self.transport, messages))
            selected = obj.get("selected_tool")
            reason = sanitize_merchant_text(str(obj.get("reason", "")))[:MAX_REASON_CHARS]
            question = sanitize_merchant_text(str(obj.get("question", "")))[:MAX_REASON_CHARS]
            if selected is None:
                return InvestigationPlan(reason=reason or "LLM planner chose to stop.",
                                         selected_tool=None, question=question, stop=True)
            # ALLOWLIST ENFORCEMENT: the model's only executable choice is a
            # tool name, and only a name the loop already permits.
            if selected not in context.available_tools:
                raise ValueError(f"Model selected a non-allowlisted tool: {selected!r}")
            return InvestigationPlan(reason=reason or "LLM planner selection.",
                                     selected_tool=selected, question=question)
        except Exception as exc:  # noqa: BLE001 - ANY failure falls back deterministically
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            return self.fallback.plan(context)


class LLMSynthesis(SynthesisModel):
    """LLM-backed narrative synthesis. The model writes ONLY the narrative
    prose and may cite ONLY registry evidence ids; the grounding check
    rejects unsupported citations; the recommendation is always computed by
    the shared deterministic rule. Falls back to DeterministicSynthesis on
    any failure."""

    def __init__(self, config=None, transport=http_post_json, fallback=None):
        self.config = config or load_llm_config()
        self.transport = transport
        self.fallback = fallback or DeterministicSynthesis()
        self.last_fallback_reason = None

    def _narrative(self, hypothesis_state, registry, sufficiency):
        evidence_rows = []
        for ev in registry.all():
            evidence_rows.append({
                "evidence_id": ev.evidence_id,
                "evidence_type": ev.evidence_type,
                "signal_group": ev.signal_group,
                # interpretation may embed merchant-controlled values -> treat
                # as untrusted data, quoted, sanitized:
                "interpretation": sanitize_merchant_text(ev.interpretation),
            })
        payload = {
            "task": ("Write a 3-6 sentence factual case narrative for a human risk reviewer. "
                     "Cite evidence ONLY by the exact evidence_id values provided, in square "
                     "brackets, e.g. [EVID-001]. Use ONLY facts contained in the evidence below. "
                     "Do not invent numbers, dates, metrics, or evidence ids. Do not state a "
                     "recommendation or decision."),
            "sufficiency": sufficiency.value,
            "hypotheses": hypothesis_state.to_dict(),
            "evidence": evidence_rows,
            "respond_with_json": _SYNTH_EXAMPLE,
        }
        messages = [
            {"role": "system", "content": (
                "You write grounded case narratives for a risk operations system. "
                "Output STRICT JSON only, matching: " + _SYNTH_EXAMPLE +
                " Every evidence reference must be an evidence_id from the provided list. "
                "Never invent evidence, metrics, or dates.")},
            {"role": "user", "content": json.dumps(payload)},
        ]
        obj = _parse_json_object(_chat(self.config, self.transport, messages))
        narrative = str(obj.get("narrative", "")).strip()
        if not narrative:
            raise ValueError("Model returned an empty narrative")
        return narrative[:MAX_NARRATIVE_CHARS]

    def synthesize(self, hypothesis_state, registry, sufficiency):
        try:
            if self.config["provider"] == "none":
                raise ValueError("LLM provider not configured")
            if not self.config["api_key"] or not self.config["model"]:
                raise ValueError("LLM credentials/model missing")
            narrative = self._narrative(hypothesis_state, registry, sufficiency)
            # Grounding check over UNTRUSTED model output, exactly as over the
            # deterministic template: citations not in the registry are
            # rejected from the case, not silently kept.
            cited_ids, is_grounded = check_grounding(narrative, registry)
            rejected = []
            if not is_grounded:
                for u in [c for c in cited_ids if not registry.contains(c)]:
                    narrative = narrative.replace(f"[{u}]", "[unsupported claim removed]")
                    rejected.append(u)
                cited_ids = [c for c in cited_ids if registry.contains(c)]
            leading = hypothesis_state.leading()
            return SynthesizedCase(
                narrative=narrative,
                recommendation=recommendation_for(sufficiency, leading.label, leading.support_score),
                leading_hypothesis=leading.label.value,
                hypothesis_summary=hypothesis_state.to_dict(),
                cited_evidence_ids=cited_ids,
                rejected_claims=rejected,
            )
        except Exception as exc:  # noqa: BLE001 - ANY failure falls back deterministically
            self.last_fallback_reason = f"{type(exc).__name__}: {exc}"
            return self.fallback.synthesize(hypothesis_state, registry, sufficiency)


def build_models(config=None):
    """Returns (planner, synthesis, planner_mode) honoring configuration.
    With no provider configured (the default), this is the fully
    deterministic Phase 4 stack, unchanged."""
    cfg = config or load_llm_config()
    if cfg["provider"] in ("", "none"):
        return DeterministicPlanner(), DeterministicSynthesis(), "deterministic"
    if cfg["provider"] == "openai":  # any OpenAI-compatible endpoint
        return LLMPlanner(cfg), LLMSynthesis(cfg), "llm"
    # Unknown provider -> deterministic (fail safe, never fail open).
    return DeterministicPlanner(), DeterministicSynthesis(), "deterministic"


# Referenced so linters don't flag the re-exported names; these document the
# adapter's fallback posture in one place.
_DETERMINISTIC_FALLBACKS = (DeterministicPlanner, DeterministicSynthesis, Recommendation,
                            SufficiencyDecision)
