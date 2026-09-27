"""Pydantic models: API responses + LLM structured-output schemas."""
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _to_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(w.capitalize() for w in tail)


class CamelModel(BaseModel):
    """Base for models the frontend (TypeScript, camelCase) consumes directly."""
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


# ---------- serving (read side, backend/serving.py) ----------

def _camel_keys(d: dict) -> dict:
    return {_to_camel(k): v for k, v in d.items()}


# A Parquet row passed through as it is (master, observation, forest, land):
# its column names go out in camelCase like every other field.
Record = Annotated[dict[str, Any], AfterValidator(_camel_keys)]
Tier = Literal["Critical", "High", "Medium", "Low", "untiered"]
Flag = Literal["land", "forest", "litigation", "contractor", "early_notice"]
Sort = Literal["risk", "cost", "slip", "name"]


class Meta(CamelModel):
    asof: date
    model_version: str
    gold_version: str
    silver_version: str
    n_current: int
    n_untiered: int
    latest_report_period: date | None
    latest_report_doc: str | None
    models: dict[str, str]
    caveats: list[str]


class Kpis(CamelModel):
    n_projects: int
    original_cost_cr: float | None
    anticipated_cost_cr: float | None
    expenditure_cr: float | None
    overrun_cr: float | None
    overrun_pct: float | None
    avg_progress_pct: float | None


class TierCount(CamelModel):
    tier: str
    n: int
    capital_cr: float


class GroupStat(CamelModel):
    name: str | None
    n: int
    capital_cr: float | None
    n_critical: int
    n_high: int


class TopProject(CamelModel):
    key: str
    name: str | None
    sector: str | None
    state: str | None
    tier: str | None
    p_any_2q: float | None
    anticipated_cost_cr: float | None


class Portfolio(CamelModel):
    asof: date
    filters: dict[str, str | None]
    kpis: Kpis
    tiers: list[TierCount]
    by_state: list[GroupStat]
    by_sector: list[GroupStat]
    by_ministry: list[GroupStat]
    top: list[TopProject]


class ProjectRow(CamelModel):
    key: str
    name: str | None
    sector: str | None
    state: str | None
    agency: str | None
    ministry: str | None
    tier: str | None
    tier_rank_pct: float | None
    override: bool | None
    p_any_2q: float | None
    p_date_push_2q: float | None
    p_cost_rev_2q: float | None
    months_p50: float | None
    months_p95: float | None
    anticipated_cost_cr: float | None
    expenditure_cr: float | None
    physical_progress_pct: float | None
    anticipated_completion: date | None
    slip_to_date_months: float | None
    no_completion_date: bool | None
    flags: list[str]


class ProjectPage(CamelModel):
    total: int
    page: int
    size: int
    items: list[ProjectRow]


class ShapValue(CamelModel):
    feature: str
    value: Any = None
    contribution: float


class Scores(CamelModel):
    p_date_push_2q: float | None
    p_cost_rev_2q: float | None
    p_any_2q: float | None
    p_any_4q: float | None
    months_p05: float | None
    months_p50: float | None
    months_p95: float | None
    cost_pct_p05: float | None
    cost_pct_p50: float | None
    cost_pct_p95: float | None
    tier_rank_pct: float | None
    tier_by_rank: str | None
    tier: str | None
    stagnation_override: bool | None
    no_completion_date: bool | None
    stagnation_quarters: float | None
    elapsed_ratio: float | None
    shap_top5: list[ShapValue]


class RiskRow(CamelModel):
    dimension: str
    state: Literal["flagged", "clear", "unknown"]
    evidence: str | None
    source: str | None
    as_of_date: date | None


class EventRow(CamelModel):
    category: str
    event_no: int
    first_seen: date | None
    last_seen: date | None
    n_quarters: int | None
    n_mentions: int | None
    status: str | None
    resolved: bool | None
    subtype: str | None
    authority: str | None
    forest_area_ha: float | None
    violation: bool | None
    evidence: str | None
    source_doc_id: str | None
    source_page: int | None
    remarks_last_seen: date | None


class External(CamelModel):
    fc: Record | None
    land: Record | None
    land_pairs: list[Record]
    composite: Record | None
    events: list[EventRow]


class Provenance(CamelModel):
    asof: date
    model_version: str | None
    gold_version: str
    silver_version: str
    source_doc_id: str | None
    source_page: int | None
    period: date | None
    period_type: str | None


class ReviewBadge(CamelModel):
    n_rows: int
    first_period: date | None
    last_period: date | None
    note: str


class ProjectDetail(CamelModel):
    key: str
    master: Record | None
    latest: Record | None
    scores: Scores | None
    flags: list[str]
    risk_profile: list[RiskRow]
    external: External
    provenance: Provenance
    review: ReviewBadge | None


class TimelinePoint(CamelModel):
    period: date
    physical_progress_pct: float | None
    expenditure_cr: float | None
    anticipated_cost_cr: float | None
    anticipated_completion: date | None
    source_doc_id: str | None
    source_page: int | None
    period_type: str | None


class Timeline(CamelModel):
    key: str
    points: list[TimelinePoint]


class ScenarioPoint(CamelModel):
    step: int
    quarter: date
    continue_: float | None  # own recent velocity; goes out as "continue"
    recover: float | None
    agency: float | None
    agency_basis: str | None


class Analogue(CamelModel):
    rank: int
    analogue_key: str
    analogue_name: str | None
    analogue_period: date | None
    target_period: date | None
    sector: str | None
    basis: str | None
    distance: float | None
    y_months: float | None
    y_cost_pct: float | None
    y_any: int | None
    y_date_push: int | None
    y_cost_rev: int | None


class ScurvePoint(CamelModel):
    elapsed_lo: float
    elapsed_hi: float
    expected_progress: float | None
    n_projects: int | None
    date: date | None  # bin middle on the project's sanction-to-scheduled span


class BandPoint(CamelModel):
    quarter: date
    lo: float
    mid: float
    hi: float


class CompletionBand(CamelModel):
    anticipated: date | None
    months_p05: float | None
    months_p50: float | None
    months_p95: float | None
    p05: date | None
    p50: date | None
    p95: date | None


class Forecast(CamelModel):
    key: str
    asof: date
    sector: str | None
    elapsed_ratio: float | None
    physical_progress_pct: float | None
    scenarios: list[ScenarioPoint]
    analogues: list[Analogue]
    analogue_summary: str
    scurve_fit_year: int | None
    scurve: list[ScurvePoint]
    band: list[BandPoint]
    completion: CompletionBand
    band_method: str


class ExternalSummary(CamelModel):
    """gold/external_summary.json; the nested blocks keep the file's own keys."""
    as_of_date: date
    n_projects: int
    model_version: str
    rule: str
    factors: dict[str, Any]
    early_notice: dict[str, Any]
    notice_backtest: dict[str, Any]
    external_composite: dict[str, Any]
    coverage: dict[str, Any]
    caveats: list[str]


class ModelsOut(CamelModel):
    champions: dict[str, Any]
    run_id: str | None
    backtest: list[Record]
    ablation: list[Record]


# ---------- app state (SQLite, backend/db.py) ----------

Role = Literal["ipmd_analyst", "ministry_official", "agency_official", "public"]
AlertKind = Literal["tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice",
                    "pipeline_error"]


class Alert(CamelModel):
    """project_key is None only for a pipeline_error alert."""
    id: int
    created_at: str
    project_key: str | None
    kind: AlertKind
    severity: int
    title: str | None
    detail: str | None
    asof: str | None
    model_version: str | None
    source: str | None
    acked_by: str | None
    acked_at: str | None


class AlertPage(CamelModel):
    total: int
    page: int
    size: int
    items: list[Alert]


class RoleBody(CamelModel):
    role: Role


class WatchRequest(CamelModel):
    role: Role
    project_key: str = Field(max_length=32)


class WatchItem(CamelModel):
    role: str
    project_key: str
    added_at: str | None
    project: ProjectRow | None


class Watchlist(CamelModel):
    total: int
    items: list[WatchItem]


class JobRun(CamelModel):
    id: int
    job: str
    started_at: str | None
    finished_at: str | None
    status: str | None
    summary: Any = None


class Ingested(CamelModel):
    """A file saved into dataset/raw/inbox/ for the watcher's next run; saved_as None when these bytes were
    already ingested by the current pipeline version (nothing is kept)."""
    saved_as: str | None
    sha256: str
    kind: str | None
    already_ingested: bool


class JobStarted(CamelModel):
    """summary: the run's counts when it ran inside the request (the scout on one project)."""
    started: bool
    detail: str
    pending: int | None = None
    summary: dict[str, Any] | None = None


class LeadTime(CamelModel):
    """The first report period after the signal date whose CUF row changed (completion pushed or cost revised) and
    the gap in days; None while no report has changed since."""
    cuf_change_period: date | None = None
    lead_days: int | None = None


class Signal(LeadTime):
    id: int
    url: str
    title: str | None
    source: str | None
    published_at: str | None
    fetched_at: str | None
    summary: str | None
    category: str | None
    severity: int | None
    link_score: float | None
    method: str | None


class ProjectSignals(CamelModel):
    """last_scout_at None means the scout never searched this project: no signals is then unknown, not clear."""
    key: str
    last_scout_at: str | None
    items: list[Signal]


class FeedProject(LeadTime):
    key: str
    name: str | None
    state: str | None
    tier: str | None
    link_score: float | None
    method: str | None


class FeedItem(CamelModel):
    """A stored signal; projects is empty for the unlinked pool (ambiguous or weak matches)."""
    id: int
    url: str
    title: str | None
    source: str | None
    published_at: str | None
    fetched_at: str | None
    summary: str | None
    category: str | None
    severity: int | None
    projects: list[FeedProject]


class StateHeat(CamelModel):
    state: str | None
    n: int


class SignalFeed(CamelModel):
    """state_heat: signals of severity >= 2 in the last 90 days per state of their linked projects."""
    total: int
    page: int
    size: int
    items: list[FeedItem]
    state_heat: list[StateHeat]


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
