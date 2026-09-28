"""Pydantic models: API responses + LLM structured-output schemas."""
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


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
Tier = Literal["Critical", "High", "Medium", "Low", "Watch"]
Flag = Literal["land", "forest", "litigation", "contractor", "early_notice"]
Sort = Literal["risk", "cost", "slip", "name", "progress"]


class Meta(CamelModel):
    asof: date
    model_version: str
    gold_version: str
    silver_version: str
    n_current: int
    n_watch: int
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
    override: bool | None = None  # the stagnation badge


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
    # PARIVESH link, remark-named proposals, remark status (as-of quarters), measured hidden-delay priors that apply;
    # empty on the public page
    portal: Record | None = None
    proposals: list[Record] = []
    remark_status: Record | None = None
    hidden_delay: list[Record] = []


class Provenance(CamelModel):
    """model, data versions and source document are None on the public page (backend/access.py)."""
    asof: date
    model_version: str | None
    gold_version: str | None
    silver_version: str | None
    source_doc_id: str | None
    source_page: int | None
    period: date | None
    period_type: str | None


class ReviewBadge(CamelModel):
    n_rows: int
    first_period: date | None
    last_period: date | None
    note: str


class ResearchFact(CamelModel):
    """A cited web fact (backend/serving.py research). origin 'sweep': found by a research agent and checked by a
    second one (verified keep | fix; it re-opened the source of an article fact); 'agent': a news item the in-app research agent judged
    relevant with the local LLM (signal_id, judged_at). live: negative, not resolved, within 4 quarters of asof.
    headline is the citation label; the public gets no match_reason, and no headline on agent facts (a raw news feed
    title): label those by summary and source. basis: 'article' when the researcher read the source, 'headline' when
    only a news-feed headline and its feed summary were judged (every agent fact, and the sweep's second pass)."""
    fact_id: str
    category: str
    taxonomy: str
    direction: Literal["negative", "positive", "neutral"]
    severity: int
    event_date: date | None
    date_precision: Literal["day", "month", "year"] | None
    published_date: date | None
    status: str
    summary: str
    headline: str | None
    source: str | None
    url: str
    domain: str | None
    match: str | None
    match_reason: str | None = None
    verified: str | None = None
    basis: Literal["article", "headline"] | None = None
    origin: Literal["sweep", "agent"]
    researched_on: date | None
    live: bool
    signal_id: int | None = None
    judged_at: str | None = None


class LandShare(CamelModel):
    value: float | None
    as_of: str | None


class ForestStage(CamelModel):
    stage: str | None
    as_of: str | None


class CourtCase(CamelModel):
    court: str | None
    status: str | None
    as_of: str | None


class ContractorState(CamelModel):
    company: str | None
    status: str | None
    as_of: str | None


class NewTarget(CamelModel):
    date: str | None  # 'YYYY-MM' as the source gives it
    as_of: str | None


class CostRevision(CamelModel):
    new_cost_cr: float | None
    as_of: str | None


class ResearchExternal(CamelModel):
    """The latest figure the researched sources give, each as of its own date; None when no source gives it."""
    land_acquired_pct: LandShare | None
    forest_clearance: ForestStage | None
    court_case: CourtCase | None
    contractor: ContractorState | None
    new_target: NewTarget | None
    cost_revision: CostRevision | None


class ResearchBrief(CamelModel):
    """The project page's research block. searched False: not researched yet; searched with n_facts 0: searched,
    nothing found (not 'clear'). top: up to 3 facts, live blockers first."""
    researched_on: date | None
    searched: bool
    agent_researched_at: str | None
    latest_status: str | None
    n_facts: int
    n_negative_live: int
    top: list[ResearchFact]


class ProjectResearch(CamelModel):
    """GET /api/projects/{key}/research: every research fact of one project (sweep and agent), newest first."""
    key: str
    researched_on: date | None
    searched: bool
    agent_researched_at: str | None
    latest_status: str | None
    external: ResearchExternal
    n_facts: int
    n_negative_live: int
    facts: list[ResearchFact]


class ProjectDetail(CamelModel):
    key: str
    master: Record | None
    latest: Record | None
    scores: Scores | None
    flags: list[str]
    risk_profile: list[RiskRow]
    top_risks_plain: list[str]  # up to 3 flagged checklist rows in plain words
    external: External
    provenance: Provenance
    review: ReviewBadge | None
    research: ResearchBrief | None = None


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
    # remark flags live vs stale, PARIVESH-linked projects, land coverage and the measured hidden-delay priors
    remark_flags: dict[str, Any] | None = None
    portal: dict[str, Any] | None = None
    land_coverage: dict[str, Any] | None = None
    hidden_delay_priors: dict[str, Any] | None = None


class ResearchRange(CamelModel):
    first: date | None
    last: date | None


class ResearchCoverage(CamelModel):
    n_current: int
    n_searched: int
    n_with_facts: int
    n_facts: int
    n_negative_live: int
    n_projects_negative_live: int
    n_agent_facts: int
    n_agent_projects: int


class ResearchCategory(CamelModel):
    category: str
    taxonomy: str
    negative: int
    positive: int
    neutral: int
    n_live: int
    n_projects_live: int


class ResearchState(CamelModel):
    state: str | None
    n_current: int
    n_searched: int
    n_with_facts: int
    n_negative_live: int
    n_projects_negative_live: int


class ResearchBlocker(CamelModel):
    """A live negative fact of severity >= 2 with its project; the public gets the sweep's blockers only, as
    headline, url and dates. Show event_date by date_precision, else published_date (a live fact has one of them)."""
    headline: str
    url: str
    event_date: date | None
    date_precision: Literal["day", "month", "year"] | None
    published_date: date | None = None
    fact_id: str | None = None
    project_key: str | None = None
    project_name: str | None = None
    state: str | None = None
    tier: str | None = None
    category: str | None = None
    severity: int | None = None
    summary: str | None = None
    source: str | None = None
    origin: Literal["sweep", "agent"] | None = None


class ResearchSummary(CamelModel):
    """GET /api/research/summary: web research over the current projects in the viewer's scope."""
    asof: date
    live_window_quarters: int
    researched_on: ResearchRange
    coverage: ResearchCoverage
    by_category: list[ResearchCategory]
    by_state: list[ResearchState]
    top_recent_blockers: list[ResearchBlocker]
    agent_last_run: str | None
    note: str


class LiveAccuracy(CamelModel):
    """Realised outcomes of logged predictions; every metric is None until outcomes are realised (never faked)."""
    n_logged: int
    n_realised: int
    first_asof: date | None
    n_critical_high_realised: int
    precision_critical_high: float | None
    base_rate: float | None
    pr_auc: float | None
    note: str


class ModelsOut(CamelModel):
    """registry: one row per registered entry (pooled validation PR-AUC, ECE, test PR-AUC, champion now);
    decisions: champion / challenger decisions with their reasons (the last 100 of each)."""
    champions: dict[str, Any]
    run_id: str | None
    backtest: list[Record]
    ablation: list[Record]
    shap_summary: list[Record]
    calibration: list[Record]
    registry: list[Record]
    decisions: list[Record]
    live_accuracy: LiveAccuracy


class AgencyPoint(CamelModel):
    """One canonical agency (gold/agency_matrix.parquet). schedule_bias / cost_bias are shrunk toward the sector
    median when n < 10, the *_raw ones are not; CIs are bootstrap 90% intervals of the raw median."""
    agency: str
    names: str | None
    sector: str | None
    ministry: str | None
    n_projects: int
    n_open: int
    capital_cr: float
    schedule_bias: float | None
    schedule_bias_raw: float | None
    schedule_bias_q25: float | None
    schedule_bias_q75: float | None
    schedule_bias_ci_lo: float | None
    schedule_bias_ci_hi: float | None
    cost_bias: float | None
    cost_bias_raw: float | None
    cost_bias_q25: float | None
    cost_bias_q75: float | None
    cost_bias_ci_lo: float | None
    cost_bias_ci_hi: float | None
    n_cost: int
    sector_schedule_bias: float | None
    sector_cost_bias: float | None
    shrink_weight: float | None
    shrunk: bool
    hidden: bool
    trend: float | None
    n_recent: int
    is_self: bool = False  # the signed-in agency official's own agency


class AgencyMatrix(CamelModel):
    asof: date
    n_agencies: int
    n_hidden: int
    method: str
    points: list[AgencyPoint]


class MemberBrief(CamelModel):
    key: str
    name: str | None
    tier: str | None
    p_any_2q: float | None
    anticipated_cost_cr: float | None


class Bottleneck(CamelModel):
    """A cluster of current projects sharing an open issue (category, authority, state); level 'state' is the
    rollup over every authority. headline + note: the projects that would be affected, not a causal claim."""
    bottleneck_id: str
    level: Literal["authority", "state"]
    category: str
    authority: str | None
    state: str | None
    n_projects: int
    capital_exposed_cr: float
    mean_p_any_2q: float | None
    mean_months_p50: float | None
    n_critical_high: int
    earliest_first_seen: date | None
    last_seen: date | None
    n_signals: int
    evidence: list[str]
    headline: str
    note: str
    top_members: list[MemberBrief]


class BottleneckPage(CamelModel):
    """summary: gold/bottlenecks_summary.json with the file's own keys."""
    asof: date
    total: int
    page: int
    size: int
    summary: dict[str, Any]
    items: list[Bottleneck]


class MemberEvidence(CamelModel):
    kind: Literal["event", "signal"]
    authority: str | None
    first_seen: date | None
    last_seen: date | None
    evidence: str | None
    source_doc_id: str | None
    source_page: int | None
    url: str | None


class BottleneckMember(CamelModel):
    key: str
    name: str | None
    sector: str | None
    state: str | None
    agency: str | None
    tier: str | None
    p_any_2q: float | None
    months_p50: float | None
    anticipated_cost_cr: float | None
    evidence: list[MemberEvidence]


class BottleneckDetail(CamelModel):
    asof: date
    bottleneck: Bottleneck
    total: int
    page: int
    size: int
    members: list[BottleneckMember]


class BriefOut(CamelModel):
    """A validated brief; payload is every fact the model was given (its own keys), the numbers it may cite."""
    status: Literal["ok"]
    key: str
    asof: str
    model_version: str
    text: str
    paragraphs: list[str]
    cached: bool
    generated_at: str | None
    n_numbers_checked: int | None
    attempts: int | None
    payload: dict[str, Any]


Concern = Literal["none", "watch", "concern"]


class OpinionEvidence(CamelModel):
    """One item of a second opinion's evidence pack (llm/second_opinion.py), cited as [E#]. direction context: the
    status line and the model, never grounds for a concern; stale: an old report remark, a resolved or old research
    fact, an old headline."""
    id: str
    kind: Literal["status", "model", "check", "parivesh", "land", "event", "research", "news"]
    date: str | None
    direction: Literal["context", "negative", "positive", "neutral"]
    severity: int | None
    stale: bool
    source: str
    text: str


class SecondOpinionOut(CamelModel):
    """An accepted LLM second opinion for the project's current evidence (evidence_hash). It never changes the tier:
    model_level is the tier's concern level (Critical and High 'concern', Medium and Watch 'watch', Low 'none') and
    vs_model compares the two. cited: the ids the narrative cites; evidence: every item the LLM read. model is the
    LLM, model_version PAIMANA's scoring model."""
    status: Literal["ok"]
    key: str
    name: str
    asof: str
    model_version: str | None
    tier: str | None
    model_level: Concern
    concern: Concern
    headline: str
    narrative: str
    key_evidence: list[str]
    vs_model: Literal["agrees", "higher", "lower"]
    gaps: list[str]
    cited: list[str]
    evidence: list[OpinionEvidence]
    evidence_hash: str
    model: str
    prompt_version: str | None
    generated_at: str | None
    cached: bool
    attempts: int | None = None
    n_numbers_checked: int | None = None
    llm_ms: int | None = None


class SecondOpinionNone(CamelModel):
    """?cached=1 and no accepted opinion for the current evidence: nothing was generated."""
    status: Literal["none"]
    key: str
    detail: str


class SecondOpinionRejected(CamelModel):
    """HTTP 422: both replies failed the checks (cited ids, numbers, concern level, lengths); reasons of the last."""
    status: Literal["rejected"]
    key: str
    reasons: list[str]
    attempts: int
    llm_ms: int | None = None


class SecondOpinionUnavailable(CamelModel):
    """HTTP 503: LM Studio is unreachable (remembered for a short while) or busy with other answers (busy)."""
    status: Literal["llm_unavailable"]
    detail: str
    busy: bool = False


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


class ScopeOption(CamelModel):
    name: str
    n: int  # current projects
    names: str | None = None  # agencies: every printed name
    ministry: str | None = None


class Scopes(CamelModel):
    """The sign-in picker: ministries and canonical agencies of the current portfolio."""
    ministries: list[ScopeOption]
    agencies: list[ScopeOption]


class RoleBody(CamelModel):
    """role: optional, and when sent it must be the signed-in one (X-Paimana-Role, backend/access.py)."""
    role: Role | None = None


class WatchRequest(CamelModel):
    role: Role | None = None
    project_key: str = Field(max_length=32)


CHAT_TEXT_MAX = 1000


class ChatMessage(CamelModel):
    """One turn. A question is 1-1000 characters; an earlier answer the client sends back may run longer (a streamed
    answer can pass 1000 characters) and only its first 1000 are read (backend/routes.py)."""
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4 * CHAT_TEXT_MAX)

    @model_validator(mode="after")
    def _question_length(self):
        if self.role == "user" and not 1 <= len(self.content.strip()) <= CHAT_TEXT_MAX:
            raise ValueError(f"a question is 1 to {CHAT_TEXT_MAX} characters")
        return self


class ChatRequest(CamelModel):
    """POST /api/chat: the conversation so far (1-12 turns, the last one the user's question) and the project open in
    the app (its key; it must be in the viewer's scope)."""
    messages: list[ChatMessage] = Field(min_length=1, max_length=12)
    project_key: str | None = Field(None, max_length=32)

    @model_validator(mode="after")
    def _ends_with_a_question(self):
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be the user's question")
        return self


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


class LiveJob(CamelModel):
    """One background loop: its in-memory tick state and its last recorded run (job_runs; None: never ran)."""
    interval_s: float | None
    running: bool
    last_tick: str | None
    next_due: str | None
    last_error: str | None
    last_run: JobRun | None


class LiveStatus(CamelModel):
    """enabled False: LIVE_JOBS=0, the loops are not running (jobs still start from the API, the Bhoomi Rashi pull
    only with BHOOMI_PULL=1). A job whose loop is off has interval_s None."""
    enabled: bool
    inbox_pending: int
    watch: LiveJob
    scout: LiveJob
    parivesh_snapshot: LiveJob | None = None
    bhoomi_rashi_pull: LiveJob | None = None
    research: LiveJob | None = None
    bhoomi_pull_enabled: bool = False


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


class CountRow(CamelModel):
    name: str | int | None
    n: int


class LeadTimeStats(CamelModel):
    n_linked_pairs: int
    n_with_later_change: int
    median_lead_days: int | None
    basis: str


class RadarSummary(CamelModel):
    """Counts over signals published in the last window_days; lead time over every linked signal."""
    window_days: int
    since: str
    n_signals_total: int
    n_window: int
    n_linked: int
    n_unlinked: int
    by_category: list[CountRow]
    by_severity: list[CountRow]
    by_source: list[CountRow]
    n_projects_scouted: int
    lead_time: LeadTimeStats


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
    role: Role | None = None


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
