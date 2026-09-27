"""Fixed-sequence AI worker cell: 5 plain Python functions called in order.

No agent framework — 5 sequential calls don't need a graph library, a for-loop
does the job. Orchestrated by run_worker_cycle() at the bottom.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend import serving, store
from backend.schemas import (
    AnalystOutput,
    AuditorQuery,
    DispatcherOutput,
    DispatchDraft,
    EvidenceItem,
    ScoutOutput,
)

from .client import LLM_MODEL, call_llm

TOP_N = 10  # Scout only runs on the top-priority projects
STALE_MONTHS, DQ_MIN = 3, 0.7  # same thresholds as the data-staleness row in ml/risk_profile.py


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 1. Auditor ----------

def auditor(project_row: dict) -> tuple[list[str], float, AuditorQuery | None]:
    """Plain-Python detection, no LLM. Only phrases the result via LLM if issues exist."""
    issues: list[str] = []

    months_since = project_row.get("months_since_last_obs")
    if months_since is not None and months_since > STALE_MONTHS:
        issues.append(f"no new figures for {months_since:.0f} months")
    dq = project_row.get("dq_score")
    if dq is not None and dq < DQ_MIN:
        issues.append(f"data-quality score {dq:.2f} is below {DQ_MIN}")

    # simple proxy: no physical progress but cost has already overrun
    physical_progress = project_row.get("physical_progress_pct")
    cost_overrun_pct = project_row.get("cost_variation_pct")
    if physical_progress is not None and cost_overrun_pct is not None:
        if physical_progress == 0 and cost_overrun_pct > 0:
            issues.append(
                f"physical progress is 0% while cost has already overrun by {cost_overrun_pct:.1f}%"
            )

    # Naive heuristic, not a calibrated confidence score. Replace once real
    # reporting QA rules exist to check against.
    data_confidence = max(0.0, 1.0 - 0.3 * len(issues))

    query: AuditorQuery | None = None
    if issues:
        system = "You are a compliance auditor for a government project monitoring system."
        user = (
            "Phrase the following ALREADY-DETECTED data-quality issues into ONE plain-language "
            "query sentence to send back to the reporting agency. Do not invent any new issue, "
            f"only phrase what is listed.\nProject: {project_row.get('project_name')}\n"
            f"Issues: {'; '.join(issues)}"
        )
        query = call_llm(system, user, AuditorQuery)

    return issues, data_confidence, query


# ---------- 2. Forecaster ----------

def forecaster(project_key: str) -> dict:
    """Pure lookup of the current scores, NEVER calls the LLM. Keep call_llm out of this function."""
    bundle = serving.project(project_key)
    scores = bundle["scores"] or {}
    return {
        "project_key": project_key,
        "tier": scores.get("tier"),
        "p_any_2q": scores.get("p_any_2q"),
        "p_date_push_2q": scores.get("p_date_push_2q"),
        "p_cost_rev_2q": scores.get("p_cost_rev_2q"),
        "months_p50": scores.get("months_p50"),
        "anticipated_cost_cr": (bundle["latest"] or {}).get("anticipated_cost_cr"),
        "model_version": bundle["provenance"]["model_version"],
        "shap_top5": scores.get("shap_top5", []),
    }


# ---------- 3. Scout ----------

def scout(project_row: dict) -> ScoutOutput:
    """LLM call. Extracts cause tags from the project's last free-text report remark.

    Note: this is the project's own reported remarks text (free text only in
    reports up to 2023), not a live news fetch. RSS ingestion isn't built yet.
    """
    key = project_row["project_key"]
    remark = serving.last_remarks(key) or {}
    events = serving.project(key)["external"]["events"]
    open_events = sorted({e["category"] for e in events if e["status"] == "open"})
    system = (
        "You are extracting delay-cause tags from a government project status note. "
        "Only use categories: land, clearance, litigation, contractor, funds, utility_shifting."
    )
    user = (
        f"Project: {project_row.get('project_name', '')}\n"
        f"Sector: {project_row.get('sector', '')}\n"
        f"Open delay events in reports: {', '.join(open_events) or 'none recorded'}\n"
        f"Remarks ({remark.get('period', 'none')}): {remark.get('remarks', '')}\n"
        "Extract 1-3 cause tags with a confidence (0-1) and a short source_note quoting the remark."
    )
    return call_llm(system, user, ScoutOutput)


# ---------- 4. Analyst ----------

def analyst(forecaster_output: dict, scout_output: ScoutOutput) -> AnalystOutput:
    """LLM call. Drafts from already-computed facts only, never asked to invent numbers."""
    system = (
        "You are a project-risk analyst. Write a short summary and recommended action using ONLY "
        "the facts given below. Do not invent numbers."
    )
    user = (
        f"Risk tier (by rank): {forecaster_output.get('tier')}\n"
        f"P(date push or cost revision within 2 quarters): {forecaster_output.get('p_any_2q')}\n"
        f"P(date push, 2q): {forecaster_output.get('p_date_push_2q')}\n"
        f"P(cost revision, 2q): {forecaster_output.get('p_cost_rev_2q')}\n"
        f"Expected slip over 2 quarters (months, median): {forecaster_output.get('months_p50')}\n"
        f"Anticipated cost (Cr): {forecaster_output.get('anticipated_cost_cr')}\n"
        f"SHAP top drivers: {forecaster_output.get('shap_top5')}\n"
        f"Scout cause tags: {[t.model_dump() for t in scout_output.tags]}\n"
    )
    return call_llm(system, user, AnalystOutput)


# ---------- 5. Dispatcher ----------

def dispatcher(analyst_output: AnalystOutput, project_row: dict) -> DispatchDraft:
    """LLM call. Never auto-sends, just drafts, stored via store.py with status=pending."""
    system = (
        "You draft an internal escalation memo for a government project monitoring dashboard. "
        "Pick the single most appropriate recipient role."
    )
    user = (
        f"Project: {project_row.get('project_name')} ({project_row.get('project_key')})\n"
        f"Summary: {analyst_output.summary}\n"
        f"Bottlenecks: {analyst_output.bottlenecks}\n"
        f"Recommended action: {analyst_output.recommended_action}\n"
    )
    out = call_llm(system, user, DispatcherOutput)
    return DispatchDraft(
        id=str(uuid.uuid4()),
        project_id=str(project_row.get("project_key")),
        project_name=str(project_row.get("project_name") or "Unknown project"),
        draft_memo=out.draft_memo,
        recommended_recipient_role=out.recommended_recipient_role,
        status="pending",
        created_at=_now(),
    )


# ---------- orchestrator ----------

def run_worker_cycle() -> dict:
    """Auditor -> Forecaster -> Scout -> Analyst -> Dispatcher over the top-N priority projects.

    Capped to TOP_N by p_any_2q per trigger run: running a local 14B
    model over hundreds of projects synchronously isn't viable for a demo
    button, and Scout was only ever meant for the top-priority projects.
    """
    top = serving.top_projects(TOP_N)
    meta = serving.meta()
    dataset_label = f"{Path(serving.state()['pointer']['path']).name} (top {TOP_N} by p_any_2q)"

    alerts_raised = 0
    new_drafts: list[DispatchDraft] = []
    processed = 0

    for project_row in top:
        issues, _confidence, _query = auditor(project_row)
        if issues:
            alerts_raised += 1

        fc = forecaster(project_row["project_key"])
        sc = scout(project_row)
        an = analyst(fc, sc)
        draft = dispatcher(an, project_row)
        draft.evidence = [
            EvidenceItem(tag=t.category, source_url=None, note=t.source_note) for t in sc.tags
        ]
        new_drafts.append(draft)
        processed += 1

    ts = _now()
    model_version = meta["model_version"]
    new_runs = [
        {
            "id": str(uuid.uuid4()), "worker": "auditor", "timestamp": ts,
            "model_version": f"rules-v1 + {LLM_MODEL} (query phrasing only)", "dataset": dataset_label,
            "projects_processed": processed, "alerts_raised": alerts_raised,
            "summary": f"Checked {processed} top-priority projects for stale/inconsistent figures; {alerts_raised} flagged.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "forecaster", "timestamp": ts,
            "model_version": model_version, "dataset": dataset_label,
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Looked up tier and slip/cost-revision probabilities for {processed} projects from the champion scores at {meta['asof']}.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "scout", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": "silver report remarks, free text up to 2023 (no live news fetch yet)",
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Extracted delay-cause tags for {processed} projects from their last report remarks (no live news fetch yet).",
        },
        {
            "id": str(uuid.uuid4()), "worker": "analyst", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": dataset_label,
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Drafted risk summaries and recommended actions for {processed} projects.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "dispatcher", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": dataset_label,
            "projects_processed": processed, "alerts_raised": len(new_drafts),
            "summary": f"Drafted {len(new_drafts)} escalation memos, all pending human approval.",
        },
    ]

    store.append_worker_runs(new_runs)
    store.append_dispatch_drafts([d.model_dump() for d in new_drafts])

    return {"worker_runs": new_runs, "dispatch_drafts": [d.model_dump() for d in new_drafts]}
