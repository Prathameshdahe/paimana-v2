"""Fixed-sequence AI worker cell: 5 plain Python functions called in order.

No agent framework — 5 sequential calls don't need a graph library, a for-loop
does the job. Orchestrated by run_worker_cycle() at the bottom.

Every generation goes through _generate(), which takes the LLM gate (llm/client.py) for that one call: a project is
up to 4 calls of 20 to 120 s each (the auditor and scout only when they have something to phrase), and holding the
gate across all of them kept a chat answer waiting for minutes; taken per call, a chat request goes between them.
The forecaster and the data reads take no gate.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend import db, serving, store
from backend.schemas import (
    AnalystOutput,
    AuditorQuery,
    DispatcherOutput,
    DispatchDraft,
    EvidenceItem,
    ScoutOutput,
)

from .client import LLM_MODEL, call_llm, gate

TOP_N = 10  # Scout only runs on the top-priority projects
SCOUT_EVIDENCE = 10  # report events and news signals given to the scout, each
STALE_MONTHS, DQ_MIN = 3, 0.7  # same thresholds as the data-staleness row in ml/risk_profile.py


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate(system: str, user: str, response_model):
    """call_llm with the LLM gate held for this one generation only (module docstring); the gate is taken without
    a time limit: the cell runs on demand for an analyst, behind whatever chat answer is in flight."""
    with gate():
        return call_llm(system, user, response_model)


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
        query = _generate(system, user, AuditorQuery)

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
        "outlook": scores.get("outlook"),
        "drivers_plain": scores.get("drivers_plain", []),
    }


# ---------- 3. Scout ----------

def scout(project_row: dict) -> tuple[ScoutOutput, list[dict]]:
    """LLM call over the project's own evidence only: the delay events found in its report remarks
    (gold/project_events, with document and page) and the news signals the scout linked to it (SQLite).
    Returns the tags and those signals. With neither there is no LLM call and no tag: nothing is made up."""
    key = project_row["project_key"]
    events = sorted(serving.project(key)["external"]["events"], key=lambda e: e["status"] != "open")[:SCOUT_EVIDENCE]
    signals = db.project_signals(key, limit=SCOUT_EVIDENCE)["items"]
    if not events and not signals:
        return ScoutOutput(tags=[]), []
    lines = [f"- report remark, {e['category']} ({e['status']}, {e['first_seen']} to {e['last_seen']}): "
             f"\"{e['evidence']}\" [{e['source_doc_id']} p.{e['source_page']}]" for e in events]
    lines += [f"- news, {(s['published_at'] or 'undated')[:10]}, {s['source']}: \"{s['title']}\" "
              f"(category {s['category'] or 'none'}, severity {s['severity']})" for s in signals]
    system = (
        "You are extracting delay-cause tags from evidence about a government project. "
        "Only use categories: land, clearance, litigation, contractor, funds, utility_shifting. "
        "Use only the evidence lines given; if none supports a category, return no tags."
    )
    user = (
        f"Project: {project_row.get('project_name', '')}\n"
        f"Sector: {project_row.get('sector', '')}\n"
        "Evidence:\n" + "\n".join(lines) + "\n"
        "Extract 1-3 cause tags with a confidence (0-1) and a short source_note quoting one evidence line."
    )
    return _generate(system, user, ScoutOutput), signals


# ---------- 4. Analyst ----------

def analyst(forecaster_output: dict, scout_output: ScoutOutput) -> AnalystOutput:
    """LLM call. Drafts from already-computed facts only, never asked to invent numbers. Its summary becomes the memo
    an official reads (the dispatcher), so it gets the outlook and the drivers in words, never the model's
    probabilities or SHAP values (the numbers policy, docs/ACCESS_CONTROL.md)."""
    system = (
        "You are a project-risk analyst. Write a short summary and recommended action using ONLY "
        "the facts given below. Do not invent numbers, and never write a probability or a percentage chance."
    )
    o = forecaster_output.get("outlook") or {}
    drivers = [f"{d['label']} ({d['direction']} the risk, {d['strength']})"
               for d in forecaster_output.get("drivers_plain") or []]
    user = (
        f"Risk tier (by rank): {forecaster_output.get('tier')}\n"
        f"Outlook over the {o.get('horizon', 'next two quarters')}: a completion-date push is "
        f"{o.get('delay') or 'not rated'}, a cost revision is {o.get('cost') or 'not rated'}, likely further slip "
        f"{o.get('slip') or 'unknown'}\n"
        f"Anticipated cost (Cr): {forecaster_output.get('anticipated_cost_cr')}\n"
        f"Main reasons: {'; '.join(drivers) or 'none'}\n"
        f"Scout cause tags: {[t.model_dump() for t in scout_output.tags]}\n"
    )
    return _generate(system, user, AnalystOutput)


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
    out = _generate(system, user, DispatcherOutput)
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
        issues, _confidence, _query = auditor(project_row)   # each LLM call takes the gate on its own (_generate)
        if issues:
            alerts_raised += 1

        fc = forecaster(project_row["project_key"])
        sc, signals = scout(project_row)
        an = analyst(fc, sc)
        draft = dispatcher(an, project_row)
        draft.evidence = [
            EvidenceItem(tag=t.category, source_url=None, note=t.source_note) for t in sc.tags
        ] + [EvidenceItem(tag=s["category"] or "news", source_url=s["url"], note=s["title"]) for s in signals[:5]]
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
            "model_version": LLM_MODEL, "dataset": "gold/project_events (report remarks) + linked news signals (SQLite)",
            "projects_processed": processed, "alerts_raised": 0,
            "summary": f"Extracted delay-cause tags for {processed} projects from their report-remark events and linked news signals.",
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
