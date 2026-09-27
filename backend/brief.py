"""Project brief (docs/IMPLEMENTATION_GUIDE_v2.md B 5.3, B 8 row 8): two short paragraphs from the local LLM, built
only from the numbers /api/projects/{key} already serves.

payload() collects the facts (prediction, intervals, top drivers, flagged checklist rows, open report events, linked
news of severity >= 2); the LLM gets the payload as JSON and a prompt to cite only payload facts. validate() extracts
every number from the text (integers, decimals, percents, Rs amounts, month counts) and rejects the brief if one is not
in the payload: a text number matches a payload number written to its precision (rounded or truncated), a fraction
written as a percent (0.87 -> 87%) or a percent written as a fraction (18 -> 0.18); signs are ignored. A rejected
draft is retried once with the offending numbers named; a second rejection returns the reasons. Accepted briefs are
cached per (project, asof, model_version) in the app database; LM Studio down is 'llm_unavailable' (connect timeout
llm.client.CONNECT_TIMEOUT).
"""
import json
import math
import re
from datetime import date, datetime, timezone

from llm import client

from . import db, serving

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b")
NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?(\s*%)?")
SYSTEM = (
    "You write a brief on one infrastructure project for a government monitoring officer: exactly two short "
    "paragraphs of plain text, no headings, no lists, at most 110 words each. Use only facts in the JSON payload. "
    "Every number you write must appear in the payload; you may round it or write a probability such as 0.71 as 71%. "
    "Do not compute new numbers (no sums, differences or ratios) and do not add dates. Do not give advice and do not "
    "say what would fix or speed up the project. Paragraph 1: the model's tier, its probabilities, the expected slip "
    "and its 90% range, and the top drivers. Paragraph 2: the flagged checklist rows, the open report events and the "
    "news, naming their source or date as given. Say 'unknown' where the payload says unknown.")
STRICT = ("Your previous draft was rejected because these numbers are not in the payload: {bad}. Rewrite both "
          "paragraphs. Copy every number exactly as it appears in the payload, or leave it out.")


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def payload(key: str) -> dict | None:
    """The facts the brief may use for one current project; None when it is not in the scored portfolio."""
    d = serving.project(key)
    sc = d["scores"]
    rows = serving.rows_for_keys((key,))
    if sc is None or not rows:
        return None
    row = rows[0]
    sig = [s for s in db.project_signals(key, limit=50)["items"] if (s["severity"] or 0) >= 2][:5]
    return {
        "project": {"key": key, "name": row["name"], "sector": row["sector"], "state": row["state"],
                    "agency": row["agency"], "ministry": row["ministry"]},
        "asof": str(d["provenance"]["asof"]), "model_version": d["provenance"]["model_version"],
        "status": {"physical_progress_pct": _r(row["physical_progress_pct"], 1),
                   "anticipated_cost_cr": _r(row["anticipated_cost_cr"], 1),
                   "expenditure_cr": _r(row["expenditure_cr"], 1),
                   "anticipated_completion": str(row["anticipated_completion"] or "unknown"),
                   "slip_to_date_months": _r(row["slip_to_date_months"], 0)},
        "prediction": {"tier": sc["tier"] or "untiered", "horizons_quarters": [2, 4], "interval_pct": 90,
                       "p_date_push_2q": _r(sc["p_date_push_2q"]), "p_cost_revision_2q": _r(sc["p_cost_rev_2q"]),
                       "p_any_2q": _r(sc["p_any_2q"]), "p_any_4q": _r(sc["p_any_4q"]),
                       "slip_months_p05": _r(sc["months_p05"], 1), "slip_months_p50": _r(sc["months_p50"], 1),
                       "slip_months_p95": _r(sc["months_p95"], 1), "cost_change_pct_p05": _r(sc["cost_pct_p05"], 1),
                       "cost_change_pct_p50": _r(sc["cost_pct_p50"], 1),
                       "cost_change_pct_p95": _r(sc["cost_pct_p95"], 1)},
        "top_drivers": [{"feature": v["feature"], "value": v["value"] if not isinstance(v["value"], float)
                         else _r(v["value"]), "contribution": _r(v["contribution"])} for v in sc["shap_top5"]],
        "checklist_flagged": [{"dimension": r["dimension"], "evidence": r["evidence"], "source": r["source"],
                               "as_of_date": str(r["as_of_date"]) if r["as_of_date"] else None}
                              for r in d["risk_profile"] if r["state"] == "flagged"],
        "open_events": [{"category": e["category"], "subtype": e["subtype"], "authority": e["authority"],
                         "first_seen": str(e["first_seen"]), "last_seen": str(e["last_seen"]),
                         "evidence": e["evidence"]} for e in d["external"]["events"] if e["status"] == "open"],
        "news": [{"title": s["title"], "source": s["source"], "published_at": (s["published_at"] or "")[:10],
                  "category": s["category"] or "unclassified", "severity": s["severity"]} for s in sig],
    }


# ------------------------------------------------------------------ validator

def _numbers_in(v, out: list, dates: set):
    """Every number in a payload: numeric leaves and the numbers inside its strings (evidence lines). An ISO date
    counts as a whole date (added to dates, month and day are not numbers of their own) plus its year."""
    if isinstance(v, bool) or v is None:
        return out
    if isinstance(v, (int, float)):
        if math.isfinite(v):
            out.append(abs(float(v)))
    elif isinstance(v, (date, datetime)):
        _numbers_in(v.isoformat(), out, dates)
    elif isinstance(v, str):
        for m in ISO_DATE.finditer(v):
            dates.update({m.group(0)[:7], m.group(0)[:10]})
            out.append(float(m.group(1)))
        out += [abs(float(m.group(1).replace(",", "") + (m.group(2) or "")))
                for m in NUMBER.finditer(ISO_DATE.sub(" ", v))]
    elif isinstance(v, dict):
        for x in v.values():
            _numbers_in(x, out, dates)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _numbers_in(x, out, dates)
    return out


def _matches(t: float, d: int, values: list[float]) -> bool:
    """t written with d decimals is some payload value (or its percent / fraction form) rounded or truncated."""
    unit = 10 ** d
    for v in values:
        for s in (1, 100 if v <= 1.5 else None, 0.01 if 1 < v <= 100 else None):
            if s is None:
                continue
            x = v * s * unit
            if abs(t * unit - math.floor(x + 0.5 + 1e-9)) < 1e-6 or abs(t * unit - math.floor(x + 1e-9)) < 1e-6:
                return True
    return False


def validate(text: str, facts: dict) -> tuple[bool, list[str], int]:
    """(accepted, reasons, numbers checked): every number and ISO date in text must be in facts (module docstring)."""
    dates: set = set()
    values = _numbers_in(facts, [], dates)
    reasons, n = [], 0
    for m in ISO_DATE.finditer(text):
        n += 1
        if m.group(0)[:10] not in dates:
            reasons.append(f"'{m.group(0)}' is not in the payload")
    for m in NUMBER.finditer(ISO_DATE.sub(" ", text)):
        n += 1
        t = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        d = len(m.group(2)) - 1 if m.group(2) else 0
        if not _matches(t, d, values):
            reasons.append(f"'{m.group(0).strip()}' is not in the payload")
    if not text.strip():
        reasons.append("empty text")
    return not reasons, reasons, n


# ------------------------------------------------------------------ generate

def _ask(facts: dict, bad: list[str] | None = None) -> str:
    user = "Payload:\n" + json.dumps(facts, ensure_ascii=False, default=str)
    if bad:
        user += "\n\n" + STRICT.format(bad=", ".join(bad))
    return client.complete(SYSTEM, user).strip()


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def generate(key: str) -> dict:
    """{'status': 'ok' | 'rejected' | 'llm_unavailable' | 'not_scored', ...} for one canonical key."""
    facts = payload(key)
    if facts is None:
        return {"status": "not_scored", "detail": f"project {key} is not in the current scored portfolio"}
    asof, mv = facts["asof"], facts["model_version"]
    hit = db.cached_brief(key, asof, mv)
    if hit:
        return {**hit, "paragraphs": paragraphs(hit["text"]), "status": "ok", "cached": True, "payload": facts}
    reasons, attempts = [], 0
    try:
        for attempt in range(2):
            attempts = attempt + 1
            text = _ask(facts, re.findall(r"'([^']*)'", " ".join(reasons)) if attempt else None)
            ok, reasons, n = validate(text, facts)
            if ok:
                break
    except client.LLMConnectionError as e:
        return {"status": "llm_unavailable", "detail": str(e)[:300]}
    if not ok:
        return {"status": "rejected", "reasons": reasons, "attempts": attempts}
    out = {"key": key, "asof": asof, "model_version": mv, "text": text,
           "paragraphs": paragraphs(text),
           "n_numbers_checked": n, "attempts": attempts,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    db.save_brief(out)
    return {**out, "status": "ok", "cached": False, "payload": facts}
