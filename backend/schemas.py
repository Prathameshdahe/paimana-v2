"""Pydantic models: API responses + LLM structured-output schemas."""
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(w.capitalize() for w in tail)


class CamelModel(BaseModel):
    """Base for models the frontend (TypeScript, camelCase) consumes directly."""
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


# ---------- plain data lookups ----------

class ForecastOut(BaseModel):
    project_id: str
    slip_probability: float
    risk_exposure_cr: float
    model_version: str


class ShapItem(BaseModel):
    feature: str
    contribution: float
    direction: str


class ExplanationOut(BaseModel):
    project_id: str
    shap: list[ShapItem]


class ProjectScore(CamelModel):
    """Bulk per-project model output — lets the frontend overlay real
    slip_probability/SHAP onto every displayed project in one request
    instead of 300 individual /forecast calls."""
    project_id: str
    slip_probability: float
    model_version: str
    shap: list[ShapItem]


# ---------- worker cell persistence ----------

class WorkerRun(CamelModel):
    id: str
    worker: str  # auditor | forecaster | scout | analyst | dispatcher
    model_version: str
    dataset: str
    timestamp: str
    projects_processed: int
    alerts_raised: int
    summary: str


RecipientRole = Literal["ipmd_analyst", "ministry_official", "agency_official"]
Decision = Literal["approved", "edited", "rejected"]


class EvidenceItem(CamelModel):
    tag: str
    source_url: str | None = None
    note: str


class DispatchDraft(CamelModel):
    id: str
    project_id: str
    project_name: str
    draft_memo: str
    recommended_recipient_role: RecipientRole
    status: str = "pending"  # pending | approved | edited | rejected
    created_at: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ApprovalRequest(CamelModel):
    draft_id: str
    decision: Decision
    role: str


class TriggerResult(BaseModel):
    worker_runs: list[WorkerRun]
    dispatch_drafts: list[DispatchDraft]


# ---------- LLM structured-output schemas (one per worker LLM call) ----------

class AuditorQuery(BaseModel):
    """Auditor phrases an already-detected issue list into one query sentence."""
    query_text: str


CauseCategory = Literal[
    "land", "clearance", "litigation", "contractor", "funds", "utility_shifting"
]


class ScoutTag(BaseModel):
    category: CauseCategory
    confidence: float
    source_note: str


class ScoutOutput(BaseModel):
    tags: list[ScoutTag]


class AnalystOutput(BaseModel):
    summary: str
    bottlenecks: list[str]
    recommended_action: str


class DispatcherOutput(BaseModel):
    draft_memo: str
    recommended_recipient_role: RecipientRole
