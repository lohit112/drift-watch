"""
Typed request/response models (Phase 5) — P0.

Pure pydantic schemas for the HTTP surface. Every value returned by the API
originates from the existing Phase 1-4 engine; these models only shape the
JSON.
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    merchants: int
    episodes: int
    llm_provider: str
    database: str


class DashboardSummary(BaseModel):
    merchants_monitored: int
    episodes_detected: int
    investigations_run: int
    pending_human_review: int
    escalations_recommended: int
    approved: int
    overridden: int


class MerchantSummary(BaseModel):
    merchant_id: str
    dominant_category: str
    dominant_geo: str
    first_day: int
    last_day: int
    episode_count: int
    latest_episode_status: Optional[str] = None
    latest_episode_id: Optional[str] = None


class MerchantsResponse(BaseModel):
    summary: DashboardSummary
    merchants: List[MerchantSummary]


class TimelinePoint(BaseModel):
    day: int
    txn_count: float
    txn_volume: float
    refund_rate: float
    dispute_rate: float
    category_entropy: float
    geo_entropy: float
    predicted_drift_ms: int


class EpisodeSummary(BaseModel):
    episode_id: str
    merchant_id: str
    start_day: int
    current_day: int
    end_day: Optional[int]
    status: str
    peak_day: Optional[int]
    peak_score: Optional[float]
    signal_groups: List[str]
    recommended_action: str


class MerchantDetailResponse(BaseModel):
    merchant_id: str
    dominant_category: str
    dominant_geo: str
    first_day: int
    last_day: int
    episodes: List[Dict[str, Any]]
    behavioral_timeline: List[TimelinePoint]


class EpisodesResponse(BaseModel):
    merchant_id: str
    episodes: List[Dict[str, Any]]
    latest_investigations: Dict[str, Optional[Dict[str, Any]]]


class ToolCallRecord(BaseModel):
    sequence: int
    tool_name: str
    question: str
    status: str
    failure_reason: Optional[str] = None
    evidence_ids_produced: List[str]


class EvidenceRecord(BaseModel):
    evidence_id: str
    source_tool: str
    signal_group: str
    metric: str
    value: Optional[float]
    baseline: Optional[float]
    deviation: Optional[float]
    time_window: str
    evidence_type: str
    interpretation: str
    reliability: float
    status: str
    supports_hypothesis: Optional[str] = None
    contradicts_hypothesis: Optional[str] = None


class InvestigationRecord(BaseModel):
    investigation_id: str
    episode_id: str
    created_at: str
    planner_mode: str
    sufficiency: str
    recommendation: str
    approval_status: str
    leading_hypothesis: str
    narrative: str
    hypotheses: Dict[str, Any]
    tool_calls: List[ToolCallRecord]
    budget: Dict[str, Any]
    failure_reason: Optional[str] = None


class EpisodeDetailResponse(BaseModel):
    episode: Dict[str, Any]
    latest_investigation: Optional[InvestigationRecord] = None
    human_decisions: List[Dict[str, Any]] = []


class AuditEventRecord(BaseModel):
    id: int
    investigation_id: str
    episode_id: str
    sequence: int
    event_type: str
    detail: Dict[str, Any]
    timestamp: str


class AuditResponse(BaseModel):
    episode_id: str
    events: List[AuditEventRecord]
    human_decisions: List[Dict[str, Any]]


class InvestigateResponse(BaseModel):
    investigation: InvestigationRecord
    evidence: List[EvidenceRecord]
    audit_events: List[AuditEventRecord]


class HumanDecisionRequest(BaseModel):
    reviewer_reason: str = Field(min_length=1, max_length=500,
                                 description="The human reviewer's recorded justification")


class HumanDecisionResponse(BaseModel):
    investigation: InvestigationRecord
    decision: Dict[str, Any]
    audit_events: List[AuditEventRecord]
