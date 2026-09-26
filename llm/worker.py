"""Fixed-sequence AI worker cell: 5 plain Python functions called in order.

No agent framework — 5 sequential calls don't need a graph library, a for-loop
does the job. Orchestrated by run_worker_cycle() at the bottom.
"""
import math
import uuid
from datetime import datetime, timezone

from backend import data_access, store
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
DATASET_LABEL = "dataset/gold/latest_features.csv (top 10 by slip_probability)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- 1. Auditor ----------

def auditor(project_row: dict) -> tuple[list[str], float, AuditorQuery | None]:
    """Plain-Python detection, no LLM. Only phrases the result via LLM if issues exist."""
    issues: list[str] = []
    project_id = project_row["project_id"]

    # best-effort staleness check against the full panel (latest row alone can't tell us this)
    panel = data_access.get_panel_rows(project_id)
    if not panel.empty:
        last = panel.iloc[-1]
        if "staleness_flag" in last and bool(last.get("staleness_flag")):
            n_rev = last.get("n_prior_revisions", "unknown")
            issues.append(f"panel data flags this project as stale (n_prior_revisions={n_rev})")
    else:
        issues.append("staleness check requires the full panel; no panel history found for this project")

    # simple proxy: no physical progress but cost has already overrun
    physical_progress = project_row.get("physical_progress")
    cost_overrun_pct = project_row.get("cost_overrun_pct")
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

def forecaster(project_id: str) -> dict:
    """Pure lookup, NEVER calls the LLM. Keep call_llm out of this function."""
    row = data_access.get_project_row(project_id)
    if row is None:
        return {"project_id": project_id, "slip_probability": None, "risk_exposure_cr": None}
    return {
        "project_id": project_id,
        "slip_probability": row["slip_probability"],
        "risk_exposure_cr": row["risk_exposure_cr"],
        "model_version": row.get("model_version"),
    }


# ---------- 3. Scout ----------

def scout(project_row: dict) -> ScoutOutput:
    """LLM call. Extracts cause tags from text already in real_projects.json.

    Note: this is the project's own reported remarks text, not a live news
    fetch. GDELT/RSS ingestion isn't built yet.
    """
    real = data_access.get_real_project(project_row["project_id"]) or {}
    system = (
        "You are extracting delay-cause tags from a government project status note. "
        "Only use categories: land, clearance, litigation, contractor, funds, utility_shifting."
    )
    user = (
        f"Project: {real.get('name', project_row.get('project_name', ''))}\n"
        f"Sector: {real.get('sector', project_row.get('sector', ''))}\n"
        f"Top bottleneck: {real.get('topBottleneck', '')}\n"
        f"Remarks: {real.get('delayRemarks', '')}\n"
        "Extract 1-3 cause tags with a confidence (0-1) and a short source_note quoting the remark."
    )
    return call_llm(system, user, ScoutOutput)


# ---------- 4. Analyst ----------

def analyst(forecaster_output: dict, scout_output: ScoutOutput, shap_top5: list[dict]) -> AnalystOutput:
    """LLM call. Drafts from already-computed facts only, never asked to invent numbers."""
    system = (
        "You are a project-risk analyst. Write a short summary and recommended action using ONLY "
        "the facts given below. Do not invent numbers."
    )
    user = (
        f"Slip probability: {forecaster_output.get('slip_probability')}\n"
        f"Risk exposure (Cr): {forecaster_output.get('risk_exposure_cr')}\n"
        f"SHAP top drivers: {shap_top5}\n"
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
        f"Project: {project_row.get('project_name')} ({project_row.get('project_id')})\n"
        f"Summary: {analyst_output.summary}\n"
        f"Bottlenecks: {analyst_output.bottlenecks}\n"
        f"Recommended action: {analyst_output.recommended_action}\n"
    )
    out = call_llm(system, user, DispatcherOutput)
    return DispatchDraft(
        id=str(uuid.uuid4()),
        project_id=str(project_row.get("project_id")),
        project_name=str(project_row.get("project_name") or "Unknown project"),
        draft_memo=out.draft_memo,
        recommended_recipient_role=out.recommended_recipient_role,
        status="pending",
        created_at=_now(),
    )


# ---------- orchestrator ----------

def run_worker_cycle() -> dict:
    """Auditor -> Forecaster -> Scout -> Analyst -> Dispatcher over the top-N priority projects.

    Capped to TOP_N by slip_probability per trigger run: running a local 14B
    model over hundreds of projects synchronously isn't viable for a demo
    button, and Scout was only ever meant for the top-priority projects.
    """
    df = data_access.load_latest_features()
    top = df.sort_values("slip_probability", ascending=False).head(TOP_N)

    alerts_raised = 0
    new_drafts: list[DispatchDraft] = []
    processed = 0

    for _, row in top.iterrows():
        project_row = row.to_dict()
        # NaN floats break JSON; None reads cleaner for a demo dashboard.
        project_row = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in project_row.items()}
        project_id = str(project_row["project_id"])

        issues, _confidence, _query = auditor(project_row)
        if issues:
            alerts_raised += 1

        fc = forecaster(project_id)

        import json as _json
        shap_top5 = _json.loads(project_row.get("shap_top5_json") or "[]")

        sc = scout(project_row)
        an = analyst(fc, sc, shap_top5)
        draft = dispatcher(an, project_row)
        draft.evidence = [
            EvidenceItem(tag=t.category, source_url=None, note=t.source_note) for t in sc.tags
        ]
        new_drafts.append(draft)
        processed += 1

    ts = _now()
    model_version = (top.iloc[0].get("model_version") if not top.empty else None) or "lgbm-v1"
    new_runs = [
        {
            "id": str(uuid.uuid4()), "worker": "auditor", "timestamp": ts,
            "model_version": f"rules-v1 + {LLM_MODEL} (query phrasing only)", "dataset": DATASET_LABEL,
            "projects_processed": processed, "alerts_raised": alerts_raised,
            "summary": f"Checked {processed} top-priority projects for stale/inconsistent figures; {alerts_raised} flagged.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "forecaster", "timestamp": ts,
            "model_version": model_version, "dataset": DATASET_LABEL,
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Looked up slip probability and risk exposure for {processed} projects from the trained model's latest scores.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "scout", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": "real_projects.json remarks (no live news fetch yet)",
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Extracted delay-cause tags for {processed} projects from existing status remarks (no live news fetch yet).",
        },
        {
            "id": str(uuid.uuid4()), "worker": "analyst", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": DATASET_LABEL,
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Drafted risk summaries and recommended actions for {processed} projects.",
        },
        {
            "id": str(uuid.uuid4()), "worker": "dispatcher", "timestamp": ts,
            "model_version": LLM_MODEL, "dataset": DATASET_LABEL,
            "projects_processed": processed, "alerts_raised": len(new_drafts),
            "summary": f"Drafted {len(new_drafts)} escalation memos, all pending human approval.",
        },
    ]

    store.append_worker_runs(new_runs)
    store.append_dispatch_drafts([d.model_dump() for d in new_drafts])

    return {"worker_runs": new_runs, "dispatch_drafts": [d.model_dump() for d in new_drafts]}
