"""
Engine adapter (Phase 5) — P0.

The ONLY job of this module is to load the dataset through the EXISTING
Phase 1-4 pipeline and hand objects to the EXISTING Phase 4 investigation
loop. It contains zero detection / episode / investigation logic of its
own:

    detection.drift_detector.merchant_specific_drift   (Phase 1, unchanged)
    episode.builder.build_episodes_for_merchant        (Phase 3, unchanged)
    agent.loop.InvestigationLoop                       (Phase 4, unchanged)
    agent.policy.initial_approval_status / record_human_decision
                                                       (Phase 4, unchanged)

Ground-truth columns (archetype, drift_kind, true_drift, true_drift_any)
are dropped from every DataFrame this module hands out or serializes —
they are evaluation-only labels (see agent/tools.py GROUND_TRUTH_ONLY_COLUMNS)
and must never reach the product surface.
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

from detection.drift_detector import merchant_specific_drift
from episode.builder import build_episodes_for_merchant
from agent.loop import InvestigationLoop
from agent.policy import initial_approval_status, record_human_decision
from agent.models import ApprovalStatus

# Columns that exist only for evaluation/ground-truth purposes.
GROUND_TRUTH_ONLY_COLUMNS = ["true_drift", "true_drift_any", "drift_kind", "archetype"]

DEFAULT_DATA_PATH = REPO_ROOT / "data" / "synthetic_merchant_events.csv"


class NotFoundError(Exception):
    def __init__(self, kind, identifier):
        self.kind, self.identifier = kind, identifier
        super().__init__(f"{kind} not found: {identifier}")


class ConflictError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class DriftWatchEngine:
    """Loads the dataset once through the existing pipeline, indexes
    episodes per merchant, and runs the existing InvestigationLoop on
    demand. The scored frame is kept in memory (24 merchants x 240 days —
    trivial); durable state lives in backend.db.Database."""

    def __init__(self, data_path=None):
        data_path = Path(data_path) if data_path else DEFAULT_DATA_PATH
        raw = pd.read_csv(data_path)
        scored = merchant_specific_drift(raw)
        # Ground truth never crosses into the product layer.
        self.scored = scored.drop(columns=[c for c in GROUND_TRUTH_ONLY_COLUMNS
                                           if c in scored.columns])
        self.merchants = sorted(self.scored["merchant_id"].unique())
        self._history = {m: self.scored[self.scored["merchant_id"] == m].copy()
                         for m in self.merchants}
        self._episodes = {}          # episode_id -> RiskEpisode
        self._episodes_by_merchant = {}  # merchant_id -> [RiskEpisode]
        for m in self.merchants:
            eps = build_episodes_for_merchant(self._history[m])
            self._episodes_by_merchant[m] = eps
            for ep in eps:
                self._episodes[ep.episode_id] = ep

    # --- lookups ---

    def episode(self, episode_id):
        ep = self._episodes.get(episode_id)
        if ep is None:
            raise NotFoundError("Episode", episode_id)
        return ep

    def history_for(self, episode_id):
        ep = self.episode(episode_id)
        return self._history[ep.merchant_id]

    def require_merchant(self, merchant_id):
        if merchant_id not in self._history:
            raise NotFoundError("Merchant", merchant_id)

    # --- product-surface projections (serialization only, no logic) ---

    def list_merchants(self):
        out = []
        for m in self.merchants:
            hist = self._history[m]
            eps = self._episodes_by_merchant[m]
            last_row = hist.iloc[-1]
            out.append({
                "merchant_id": m,
                "dominant_category": str(last_row["dominant_category"]),
                "dominant_geo": str(last_row["dominant_geo"]),
                "first_day": int(hist["day"].min()),
                "last_day": int(hist["day"].max()),
                "episode_count": len(eps),
                "latest_episode_status": eps[-1].status if eps else None,
                "latest_episode_id": eps[-1].episode_id if eps else None,
            })
        return out

    def merchant_detail(self, merchant_id):
        self.require_merchant(merchant_id)
        hist = self._history[merchant_id]
        eps = self._episodes_by_merchant[merchant_id]
        timeline_cols = ["day", "txn_count", "txn_volume", "refund_rate", "dispute_rate",
                         "category_entropy", "geo_entropy", "predicted_drift_ms"]
        timeline = hist[timeline_cols].round(4).to_dict(orient="records")
        last_row = hist.iloc[-1]
        return {
            "merchant_id": merchant_id,
            "dominant_category": str(last_row["dominant_category"]),
            "dominant_geo": str(last_row["dominant_geo"]),
            "first_day": int(hist["day"].min()),
            "last_day": int(hist["day"].max()),
            "episodes": [e.to_dict() for e in eps],
            "behavioral_timeline": timeline,
        }

    def list_episodes(self, merchant_id):
        self.require_merchant(merchant_id)
        return [e.to_dict() for e in self._episodes_by_merchant[merchant_id]]

    def episode_detail(self, episode_id):
        return self.episode(episode_id).to_dict()

    # --- investigation (the existing Phase 4 loop, nothing reimplemented) ---

    def investigate(self, episode_id, planner, synthesis, planner_mode):
        ep = self.episode(episode_id)
        loop = InvestigationLoop(planner=planner, synthesis=synthesis)
        result = loop.run(ep, self.history_for(episode_id))
        case = result.synthesized_case
        record = {
            "investigation_id": result.investigation_id,
            "episode_id": episode_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "planner_mode": planner_mode,
            "sufficiency": result.sufficiency.value,
            "recommendation": case.recommendation.value,
            "approval_status": result.approval_status.value,
            "leading_hypothesis": case.leading_hypothesis,
            "narrative": case.narrative,
            "hypotheses": result.hypothesis_state.to_dict(),
            "tool_calls": [{"sequence": t.sequence, "tool_name": t.tool_name,
                            "question": t.question, "status": t.status.value,
                            "failure_reason": t.failure_reason.value if t.failure_reason else None,
                            "evidence_ids_produced": t.evidence_ids_produced}
                           for t in result.tool_call_records],
            "budget": result.budget.to_dict(),
            "failure_reason": result.failure_reason.value if result.failure_reason else None,
        }
        return result, record

    # --- human decisions (Phase 4 policy, unchanged) ---

    @staticmethod
    def initial_approval(recommendation):
        return initial_approval_status(recommendation)

    @staticmethod
    def human_decision(decision, reviewer_reason, original_recommendation):
        return record_human_decision(decision, reviewer_reason, original_recommendation)

    @staticmethod
    def now_iso():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
