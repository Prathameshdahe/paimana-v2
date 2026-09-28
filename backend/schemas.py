"""Pydantic models: API responses + LLM structured-output schemas.

The numbers policy (SPEC9_ui section 6, docs/ACCESS_CONTROL.md): the model's own numbers (probabilities, quantiles,
SHAP values, rank, agency bias statistics, analogue distances and outcomes, composite scores, measured hidden-delay
months, backtest lifts, the news linker's match score) are sent only to a viewer with the `numbers` feature (the
developer). For everyone else the backend sets them to null (the key stays; a list of SHAP values is empty) and the
responses carry words instead: Outlook, PlainDriver, top_reason, the agency words, extra_months_word, the analogue
outcome and the completion band. The words are sent to every viewer, the developer too, so the UI reads one field
whoever is signed in. Each model below says which of its fields are hidden numbers.
"""
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
Chance = Literal["very likely", "likely", "possible", "unlikely"]
SlipBand = Literal["under 6 months", "6 to 12 months", "1 to 2 years", "over 2 years"]


class Outlook(CamelModel):
    """The model's 2-quarter outlook in words (backend/serving.py outlook), on project scores, list rows, the
    portfolio's top list, bottleneck members, external-factor cards and chat cards, for every viewer.
    delay: the chance of a completion-date push (p_date_push_2q) within the horizon, by fixed bands: >= 0.75 'very
    likely', >= 0.5 'likely', >= 0.25 'possible', else 'unlikely'; cost: the same bands over the chance of a cost
    revision (p_cost_rev_2q); slip: the median further slip (months_p50): under 6 months, 6 to 12 months, 1 to 2
    years (to 24 months), over 2 years. A field is null where the model gives no number: the Watch tier (no
    anticipated completion date) has no delay and no slip. horizon is always 'next two quarters'."""
    delay: Chance | None
    cost: Chance | None
    slip: SlipBand | None
    horizon: Literal["next two quarters"]


class PlainDriver(CamelModel):
    """One SHAP driver in words (serving.drivers_plain), largest first: label (backend/labels.py DRIVER_LABELS: no
    digits or units), direction (what it does to the chance of a slip), strength (its tercile by |contribution|
    among the project's own five: two strong, two moderate, one slight). Viewers with `insights` get them; the
    public gets an empty list."""
    label: str
    direction: Literal["raises", "lowers"]
    strength: Literal["strong", "moderate", "slight"]


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
    """The portfolio's 20 riskiest; p_any_2q is a hidden number (null without `numbers`); outlook and top_reason
    as on ProjectRow."""
    key: str
    name: str | None
    sector: str | None
    state: str | None
    tier: str | None
    p_any_2q: float | None
    anticipated_cost_cr: float | None
    override: bool | None = None  # the stagnation badge
    outlook: Outlook | None = None
    top_reason: str | None = None


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
    """A current project in a list (projects, agency projects, watchlist, chat cards). Hidden numbers (null without
    `numbers`): tier_rank_pct, p_any_2q, p_date_push_2q, p_cost_rev_2q, months_p50, months_p95. Words for every
    viewer: outlook; drivers_plain (empty for the public); top_reason: the label of the first driver that raises
    the chance of a slip, else of the first flagged check (land, forest, court case, contractor, stagnation ...;
    the model's own schedule and cost checks left out), the public always the flagged check; null when neither."""
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
    outlook: Outlook | None = None
    drivers_plain: list[PlainDriver] = []
    top_reason: str | None = None


class ProjectPage(CamelModel):
    total: int
    page: int
    size: int
    items: list[ProjectRow]


class MapRow(CamelModel):
    """One dot of the command centre's risk map (GET /api/projects/map): the same row for every viewer, with no model
    number at all; top_reason as on ProjectRow (the public's from the flagged checks)."""
    key: str
    name: str | None
    sector: str | None
    state: str | None
    tier: str | None
    override: bool | None
    anticipated_completion: date | None
    anticipated_cost_cr: float | None
    physical_progress_pct: float | None
    no_completion_date: bool | None
    flags: list[str]
    outlook: Outlook | None
    top_reason: str | None


class MapPage(CamelModel):
    """GET /api/projects/map: every matching current project in scope (at most 5,000; total counts them all), by
    tier (Critical, High, Medium, Low, Watch) and key."""
    total: int
    items: list[MapRow]


class ShapValue(CamelModel):
    feature: str
    value: Any = None
    contribution: float


class Scores(CamelModel):
    """The project page's model block. Hidden numbers (null without `numbers`; shap_top5 empty): the four
    probabilities, the six quantiles, tier_rank_pct, tier_by_rank, shap_top5. For every viewer: tier, the stagnation
    badge and its quarters, no_completion_date, elapsed_ratio (the share of the planned time used: a report fact),
    outlook, and drivers_plain (empty for the public)."""
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
    outlook: Outlook | None = None
    drivers_plain: list[PlainDriver] = []


class RiskRow(CamelModel):
    """A checklist row. evidence: None for the public; without `numbers` in words (serving.plain_text: the model
    checks' 'P = 0.87 (High-tier cut 0.85)' as 'a completion-date push is very likely within the next two quarters',
    the agency's timeline statistics as its schedule word, no composite score, a measured hidden delay as its band
    and project count); report facts in it stay as written."""
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


class HiddenDelayPrior(CamelModel):
    """A measured hidden-delay prior (pipeline/hidden_delay.py) that applies to the project: extra slip over the next
    year against matched projects. Hidden numbers (null without `numbers`): extra_months and its interval, extra_push
    and its interval, the Holm p-values. extra_months_word for every viewer: null when there are too few projects to
    measure (measurable False); 'no measurable extra delay' unless the interval lies above zero; else 'a few months'
    (under 4.5), 'about half a year' (under 9), 'about a year' (under 18) or 'over a year'. n_projects stays (a
    count). basis: what it was matched on; as_of: the remark quarter; current: whether it still describes the
    project at asof."""
    factor: str
    group: str
    label: str | None
    n_rows: int | None
    n_projects: int | None
    measurable: bool | None
    extra_months: float | None
    extra_months_lo: float | None
    extra_months_hi: float | None
    extra_push: float | None
    extra_push_lo: float | None
    extra_push_hi: float | None
    holm_months: float | None
    holm_push: float | None
    extra_months_word: Literal["no measurable extra delay", "a few months", "about half a year", "about a year",
                               "over a year"] | None = None
    basis: str | None = None
    as_of: Any = None
    current: bool | None = None


class External(CamelModel):
    """The project's outside factors. composite's external_factor_score, fc_component and la_component are hidden
    numbers (null without `numbers`; its coverage and ext_score_evidence ratings stay)."""
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
    hidden_delay: list[HiddenDelayPrior] = []


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
    """A similar past project at the same stage. Hidden numbers (null without `numbers`): distance and the outcome
    figures y_months, y_cost_pct, y_any, y_date_push, y_cost_rev. For every viewer: name (= analogue_name), sector,
    outcome ('slipped': its date was pushed or its cost revised within 4 quarters, 'held': neither, 'unknown': not
    known yet) and years_ago (whole years from the analogue's period, when it was at this stage, to the served asof;
    target_period is its outcome's period, 4 quarters on)."""
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
    name: str | None = None
    outcome: Literal["slipped", "held", "unknown"] = "unknown"
    years_ago: int | None = None


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
    """anticipated: the reports' anticipated completion (a fact); band: the likely further slip in words (Outlook
    .slip's bands), for every viewer. Hidden numbers (null without `numbers`): the slip quantiles months_p05/50/95 and
    the dates p05/p50/p95 derived from them."""
    anticipated: date | None
    band: SlipBand | None = None
    months_p05: float | None
    months_p50: float | None
    months_p95: float | None
    p05: date | None
    p50: date | None
    p95: date | None


class Forecast(CamelModel):
    """GET /api/projects/{key}/forecast (needs `insights`), one shape in two variants.

    With `numbers` (the developer): everything as the pipeline wrote it, plus the words (completion.band, the
    analogues' name / outcome / years_ago).

    Without `numbers` (agency, ministry and IPMD officials), serving.plain_forecast:
      completion   {anticipated, band} (band: 'under 6 months' | '6 to 12 months' | '1 to 2 years' | 'over 2 years'
                   | null); months_p05/50/95 and p05/p50/p95 are null;
      analogues    [{rank, analogueKey, analogueName, name, sector, basis, analoguePeriod, targetPeriod, outcome:
                   'slipped' | 'held' | 'unknown', yearsAgo}], distance and the y_* outcome figures null;
      analogue_summary  counts only: '7 of the 10 most similar past projects at this stage slipped or had a cost
                   revision within 4 quarters.' (no median slip);
      scenarios, band, scurve   kept with their values: they are the curves the chart draws (a picture; SPEC9_ui
                   section 6 and the design brief: the UI's tooltip names the scenario and the month, never a value);
      band_method  a plain sentence instead of the quantile-model method.
    elapsed_ratio and physical_progress_pct are report facts in both."""
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
    """gold/external_summary.json; the nested blocks keep the file's own keys (snake_case). Every project card
    (factors.*.top, early_notice.top, portal.top_overdue and open_list) carries `outlook` (an Outlook dict) for every
    viewer. Hidden numbers (null without `numbers`, serving.plain_external): the cards' p_any_2q (their evidence lines
    in words), notice_backtest's lift, lift_within_sector_year and the slip_rate_with / slip_rate_without the lift is
    the ratio of (at any depth, by_sector too; n_with, n_without and projects_with stay), land_coverage.link_check's
    ci_lo / ci_hi (n and correct stay), external_composite's score distribution (mean, min, 25%, 50%, 75%, max per
    coverage) and the top_fc_la cards' external_factor_score / fc_component / la_component (n_projects and
    n_score_ge_high stay), and hidden_delay_priors.rows' extra_months / extra_push and their intervals, holm_* and
    garvit_band. Every prior row carries extra_months_word (as HiddenDelayPrior); without `numbers`
    hidden_delay_priors.note is a plain sentence."""
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
    median when n < 10, the *_raw ones are not; CIs are bootstrap 90% intervals of the raw median.
    Hidden numbers (null without `numbers`, serving.plain_agency_matrix): every schedule_bias* and cost_bias* field,
    sector_schedule_bias, sector_cost_bias, shrink_weight and trend. Words for every viewer: schedule_word ('usually
    later' / 'usually earlier' than planned when the shrunk median schedule bias is beyond +-10%, else 'about on
    time'; 'too few projects' when hidden) and cost_word ('usually costs more' / 'usually costs less' beyond +-5%,
    else 'about as planned'; 'too few projects' when hidden or with fewer than 5 projects with both costs). The
    counts, capital, shrunk, hidden and is_self stay."""
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
    schedule_word: Literal["usually later", "about on time", "usually earlier", "too few projects"] = \
        "too few projects"
    cost_word: Literal["usually costs more", "about as planned", "usually costs less", "too few projects"] = \
        "too few projects"


class AgencyMatrix(CamelModel):
    """method: without `numbers` a plain description of the words instead of the statistics."""
    asof: date
    n_agencies: int
    n_hidden: int
    method: str
    points: list[AgencyPoint]


class MemberBrief(CamelModel):
    """p_any_2q is a hidden number (null without `numbers`); outlook for every viewer."""
    key: str
    name: str | None
    tier: str | None
    p_any_2q: float | None
    anticipated_cost_cr: float | None
    outlook: Outlook | None = None


class Bottleneck(CamelModel):
    """A cluster of current projects sharing an open issue (category, authority, state); level 'state' is the
    rollup over every authority. headline + note: the projects that would be affected, not a causal claim.
    mean_p_any_2q and mean_months_p50 are hidden numbers (null without `numbers`); the counts, n_critical_high and
    the capital stay."""
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
    """p_any_2q and months_p50 are hidden numbers (null without `numbers`); outlook for every viewer."""
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
    outlook: Outlook | None = None


class BottleneckDetail(CamelModel):
    asof: date
    bottleneck: Bottleneck
    total: int
    page: int
    size: int
    members: list[BottleneckMember]


class BriefOut(CamelModel):
    """A validated brief; payload is every fact the model was given (its own keys, snake_case), the numbers it may
    cite. view 'numbers' (the developer): the payload's prediction holds the probabilities, intervals and SHAP
    top_drivers (backend/brief.py). view 'plain' (everyone else): prediction is {tier, horizon, delay, cost_rise,
    likely_slip} in the Outlook's words, drivers_plain replaces top_drivers, the checklist evidence is in words; the
    text is checked against that payload, so it cannot carry a model number. Each view is cached on its own."""
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
    view: Literal["numbers", "plain"] = "plain"


Concern = Literal["none", "watch", "concern"]


class OpinionEvidence(CamelModel):
    """One item of a second opinion's evidence pack (llm/second_opinion.py), cited as [E#], in the pack's order:
    current hold-ups, minor current issues, progress, old items, context. direction context: the status line, the
    model and the web research summary, for the officer and the evidence hash; left out of the LLM's prompt whenever
    the pack has any other item (so never cited, and their numbers are not the opinion's), shown with their ids only
    when the pack is nothing but context; never grounds for a concern. stale: an old report remark, a resolved or old
    research fact, progress dated before the last 4 quarters, an old headline. severity 2 or 3 (a current hold-up)
    is an observed item; a land complexity rating, the forest rulebook's estimate and a news headline the research
    agent has not judged about the project are at most 1. url: the research fact's or headline's link (None on the
    rest), for the officer; not part of the evidence hash."""
    id: str
    kind: Literal["status", "model", "check", "parivesh", "land", "event", "research", "news"]
    date: str | None
    direction: Literal["context", "negative", "positive", "neutral"]
    severity: int | None
    stale: bool
    source: str
    text: str
    url: str | None = None


class SecondOpinionOut(CamelModel):
    """An accepted LLM second opinion for the project's current evidence (evidence_hash). It never changes the tier:
    model_level is the tier's concern level (Critical and High 'concern', Medium and Watch 'watch', Low 'none') and
    vs_model compares the two. cited: the ids the narrative cites; evidence: every item of the pack, the context
    included, though the LLM read only the items whose direction is not context (all of them when there is nothing
    else: OpinionEvidence); n_evidence_read: how many of them it read (the count a card should show, not
    len(evidence)). model is the LLM, model_version PAIMANA's scoring model. view: the pack it was made from, 'plain'
    (every viewer without `numbers`: the model item states the tier and the outlook in words, the checklist items'
    evidence is in words) or 'numbers' (the developer: the probabilities); each view is stored under its own
    evidence_hash, so the two never mix."""
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
    n_evidence_read: int
    evidence_hash: str
    model: str
    prompt_version: str | None
    generated_at: str | None
    cached: bool
    attempts: int | None = None
    n_numbers_checked: int | None = None
    llm_ms: int | None = None
    view: Literal["numbers", "plain"] = "plain"


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
    """HTTP 503: LM Studio refused the connection (down: start it; remembered for a short while), or it is up but
    busy with other answers (busy), or up but slow or erring (neither: the detail says, e.g. no model loaded)."""
    status: Literal["llm_unavailable"]
    detail: str
    busy: bool = False
    down: bool = False


# ---------- app state (PostgreSQL, backend/db/) ----------

# a role a request may name (ack, watchlist, approvals: it must be the signed-in one, backend/access.py acting_as);
# the developer names its own like anyone else, and stays out of OfficialRole / RecipientRole
Role = Literal["ipmd_analyst", "ministry_official", "agency_official", "public", "developer"]
AlertKind = Literal["tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice",
                    "pipeline_error"]


class Alert(CamelModel):
    """project_key is None only for a pipeline_error alert. Without `numbers` the title and detail are rewritten in
    words (serving.plain_alert: a tier alert's 'P(date push or cost revision, 2q) = 0.91' reads 'a date push or cost
    revision is very likely within the next two quarters'), in the feed and on the live stream."""
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
    """role: optional, and when sent it must be the signed-in one (backend/access.py Viewer.acting_as)."""
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
    """A job's run; summary is the job's own JSON. Without `numbers` the ingest job's summary.realised (the live
    accuracy counts) is null (serving.plain_job)."""
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
    second_opinion: LiveJob | None = None
    bhoomi_pull_enabled: bool = False


class LeadTime(CamelModel):
    """The first report period after the signal date whose CUF row changed (completion pushed or cost revised) and
    the gap in days; None while no report has changed since."""
    cuf_change_period: date | None = None
    lead_days: int | None = None


class Signal(LeadTime):
    """A news item linked to the project; link_score (the linker's match score) is a hidden number (null without
    `numbers`); method (how it was linked) stays."""
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
    """link_score is a hidden number (null without `numbers`)."""
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


# ---------- sign-in, accounts and administration (backend/auth; frontend/src/contracts/auth.ts) ----------

OfficialRole = Literal["agency_official", "ministry_official", "ipmd_analyst"]
AccountStatus = Literal["active", "disabled"]
SignupStatus = Literal["pending", "approved", "rejected"]
EMAIL_MAX, NAME_LEN, NOTE_MAX, PASSWORD_MAX, SCOPE_MAX = 254, 120, 500, 256, 200


class StrictBody(CamelModel):
    """A request body: unknown fields are refused (422), not ignored."""
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True, extra="forbid")


class LoginRequest(StrictBody):
    email: str = Field(max_length=EMAIL_MAX)
    password: str = Field(max_length=PASSWORD_MAX)


class SignupIn(StrictBody):
    """POST /api/auth/signup: a request for an account an administrator approves; the password is the account's
    from the start (only its argon2 hash is kept)."""
    email: str = Field(min_length=3, max_length=EMAIL_MAX)
    display_name: str = Field(min_length=1, max_length=NAME_LEN)
    role: OfficialRole
    ministry: str | None = Field(None, max_length=SCOPE_MAX)
    agency: str | None = Field(None, max_length=SCOPE_MAX)
    justification: str = Field("", max_length=NOTE_MAX)
    password: str = Field(max_length=PASSWORD_MAX)


class SignupAccepted(CamelModel):
    id: int


class PasswordChange(StrictBody):
    current: str = Field(max_length=PASSWORD_MAX)
    new: str = Field(max_length=PASSWORD_MAX)


class PasswordReset(StrictBody):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=PASSWORD_MAX)


class Me(CamelModel):
    """GET /api/auth/me and the answer of a sign-in. role: one of the official roles, or 'developer' (only ever
    to the developer). csrf_token goes back as X-CSRF-Token on every write; session_expires_at: when the session
    ends if left idle from now (never after its absolute end)."""
    user_id: int
    email: str
    display_name: str | None
    role: str
    ministry: str | None
    agency: str | None
    is_admin: bool
    csrf_token: str
    session_expires_at: str | None


class SignupRow(CamelModel):
    id: int
    email: str
    display_name: str | None
    role: str
    ministry: str | None
    agency: str | None
    justification: str | None
    status: SignupStatus
    created_at: str
    reviewed_by: int | None
    reviewed_at: str | None
    review_note: str | None
    ip: str | None


class ApproveSignup(StrictBody):
    """The role and scope may be corrected before the account is created; a field left out keeps the request's."""
    note: str | None = Field(None, max_length=NOTE_MAX)
    role: OfficialRole | None = None
    ministry: str | None = Field(None, max_length=SCOPE_MAX)
    agency: str | None = Field(None, max_length=SCOPE_MAX)


class RejectSignup(StrictBody):
    note: str = Field(min_length=1, max_length=NOTE_MAX)


class User(CamelModel):
    id: int
    email: str
    display_name: str | None
    role: str
    ministry: str | None
    agency: str | None
    is_admin: bool
    status: AccountStatus
    locked_until: str | None
    password_changed_at: str | None
    created_at: str | None
    last_login_at: str | None


class UserPage(CamelModel):
    total: int
    page: int
    size: int
    items: list[User]


class UserUpdate(StrictBody):
    """POST /api/admin/users/{id}: a field left out is left alone; an administrator cannot disable or demote their
    own account, and only an IPMD analyst can hold the admin flag."""
    status: AccountStatus | None = None
    role: OfficialRole | None = None
    ministry: str | None = Field(None, max_length=SCOPE_MAX)
    agency: str | None = Field(None, max_length=SCOPE_MAX)
    is_admin: bool | None = None


class ResetToken(CamelModel):
    """Shown once to the administrator who asked; only its sha256 is kept."""
    token: str
    expires_at: str | None


class AuditRow(CamelModel):
    id: int
    at: str
    user_id: int | None
    email: str | None
    role: str | None
    ip: str | None
    action: str
    target: str | None
    detail: str | None


class AuditPage(CamelModel):
    total: int
    page: int
    size: int
    items: list[AuditRow]


class Health(CamelModel):
    status: Literal["ok"]


class Ready(CamelModel):
    """GET /readyz: ready = the data version is loaded and the database answers; the local LLM is reported, not
    required (the app works without it)."""
    ready: bool
    data: str | None
    database: bool
    llm: Literal["reachable", "unreachable"]


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
