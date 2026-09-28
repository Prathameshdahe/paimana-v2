"""Project brief (docs/IMPLEMENTATION_GUIDE_v2.md B 5.3, B 8 row 8): two short paragraphs from the local LLM, built
only from the numbers /api/projects/{key} already serves.

payload() collects the facts (prediction, intervals, top drivers, flagged checklist rows, open report events, linked
news of severity >= 2); the LLM gets the payload as JSON and a prompt to cite only payload facts. validate() extracts
every number from the text (integers, decimals, '.99', percents, Rs amounts written 'Rs.999' or 'INR999', month counts,
digits after letters as in 'p99') and every date (ISO, 'March 2026', '1 Mar 2026', 'Dec-2026', 'DD.MM.YYYY',
'MM/YYYY') and rejects the brief if one is not in the payload: a date matches a payload date to the day or month it is
written to; a number matches a payload number rounded to the decimals written, a fraction written as a percent
(0.87 -> 87%) or a percent written as a fraction (18 -> 0.18), and a number marked '%' or 'per cent' must be a percent
(0.8% is not 0.80); signs are ignored. A number in words ('seventy-one', 'three', 'twice'; not 'one of') is rejected
unless the same word is in the payload (a project named 'Four Laning of ...'). Cached briefs are checked again.
A rejected draft is retried once with the offending numbers named; a second rejection returns the reasons. Accepted
briefs are cached per (project, asof, model_version) in the app database; LM Studio down is 'llm_unavailable'
(connect timeout llm.client.CONNECT_TIMEOUT; Windows retries a refused connection, so about 5 s), remembered through
the client's shared circuit breaker (client.mark_down / down_recently, client.DOWN_S seconds) with the chat and the
second opinion, so a page that asks again does not wait again and a refusal any of them found spares the others. A
slow answer (LLMTimeoutError) or an HTTP error is 'llm_unavailable' too but does not trip the breaker: LM Studio is
up.
"""
import json
import math
import re
from datetime import date, datetime, timezone

from llm import client

from . import db, serving

BUSY_WAIT_S = 120  # a chat answer takes about a minute at most on the laptop

_MONTH = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?"
          r"|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_DAY, _YEAR = r"(\d{1,2})(?:st|nd|rd|th)?", r"((?:19|20)\d{2})"
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DATES = (  # pattern, match -> (year, month, day or None); applied in this order, each date blanked once read
    (re.compile(r"\b(\d{4})-(\d{2})(?:-(\d{2}))?\b"), lambda m: (m[1], m[2], m[3])),
    (re.compile(rf"\b(?:{_DAY}\s+)?{_MONTH}\.?,?\s*(?:{_DAY},?\s*)?[-']?\s*{_YEAR}\b", re.I),
     lambda m: (m[4], MONTHS[m[2][:3].lower()], m[1] or m[3])),
    (re.compile(rf"\b(?:(\d{{1,2}})[/.-])?(\d{{1,2}})[/.-]{_YEAR}\b"), lambda m: (m[3], m[2], m[1])),
)
# not after a digit or a digit-period (inside a number or a dotted date); a bare '.99' not after a word or period
NUMBER = re.compile(r"(?<!\d)(?<!\d\.)(?:(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?|(?<![\w.])(\.\d+))"
                    r"(\s*(?:%|per\s?cent\b|percent\b))?", re.I)
NUMBER_WORD = re.compile(r"\b(?:zero|one(?!\s+of\b)|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
                         r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty"
                         r"|sixty|seventy|eighty|ninety|hundred|thousand|half|twice|thrice|double|triple|dozen)\b",
                         re.I)
SYSTEM = (
    "You write a brief on one infrastructure project for a government monitoring officer: exactly two short "
    "paragraphs of plain text, no headings, no lists, at most 110 words each. Use only facts in the JSON payload. "
    "Every number you write must appear in the payload, in digits; you may round it or write a probability such as "
    "0.71 as 71%. "
    "Do not compute new numbers (no sums, differences or ratios) and do not add dates. Do not give advice and do not "
    "say what would fix or speed up the project. Paragraph 1: the model's tier, its probabilities, the expected slip "
    "and its 90% range, and the top drivers. Paragraph 2: the flagged checklist rows, the open report events and the "
    "news, naming their source or date as given. Say 'unknown' where the payload says unknown.")
STRICT = ("Your previous draft was rejected because these numbers are not in the payload: {bad}. Rewrite both "
          "paragraphs. Copy every number and date exactly as it appears in the payload, in digits, or leave it "
          "out.")


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

def _dates(s: str) -> tuple[str, list[tuple[str, str]]]:
    """(s with its dates blanked, [(date as written, 'YYYY-MM' or 'YYYY-MM-DD')]); a match that is no real month or
    day ('2025-26') stays text, so its numbers are checked as numbers."""
    found = []
    for rx, parts in DATES:
        def blank(m, parts=parts):
            y, mo, d = parts(m)
            mo, d = int(mo), int(d) if d else None
            if not 1 <= mo <= 12 or (d is not None and not 1 <= d <= 31):
                return m.group(0)
            found.append((m.group(0).strip(), f"{y}-{mo:02d}" + (f"-{d:02d}" if d else "")))
            return " "
        s = rx.sub(blank, s)
    return s, found


def _number(m) -> tuple[float, int, bool]:
    """(value, decimals written, marked as a percent) of one NUMBER match."""
    frac = m.group(2) or m.group(3) or ""
    return float((m.group(1) or "0").replace(",", "") + frac), max(len(frac) - 1, 0), bool(m.group(4))


def _numbers_in(v, out: list, dates: set):
    """Every number in a payload: numeric leaves and the numbers inside its strings (evidence lines). A date counts
    as a whole date (added to dates to its month and, when written, its day) plus its year."""
    if isinstance(v, bool) or v is None:
        return out
    if isinstance(v, (int, float)):
        if math.isfinite(v):
            out.append(abs(float(v)))
    elif isinstance(v, (date, datetime)):
        _numbers_in(v.isoformat(), out, dates)
    elif isinstance(v, str):
        rest, found = _dates(v)
        for _, k in found:
            dates.update({k[:7], k})
            out.append(float(k[:4]))
        out += [_number(m)[0] for m in NUMBER.finditer(rest)]
    elif isinstance(v, dict):
        for x in v.values():
            _numbers_in(x, out, dates)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _numbers_in(x, out, dates)
    return out


def _matches(t: float, d: int, pct: bool, values: list[float]) -> bool:
    """t written with d decimals is some payload value rounded to d decimals: as is, or a fraction written as a
    percent when t is marked as one, or a percent written as a fraction when it is not."""
    unit = 10 ** d
    for v in values:
        for s in ((1, 100 if v <= 1.5 else None) if pct else (1, 0.01 if 1 < v <= 100 else None)):
            if s is not None and abs(t * unit - math.floor(v * s * unit + 0.5 + 1e-9)) < 1e-6:
                return True
    return False


def validate(text: str, facts: dict) -> tuple[bool, list[str], int]:
    """(accepted, reasons, numbers checked): every number and date in text must be in facts (module docstring)."""
    dates: set = set()
    values = _numbers_in(facts, [], dates)
    words = {w.lower() for w in NUMBER_WORD.findall(json.dumps(facts, ensure_ascii=False, default=str))}
    rest, found = _dates(text)
    reasons, n = [f"'{raw}' is not in the payload" for raw, k in found if k not in dates], len(found)
    for m in NUMBER.finditer(rest):
        n += 1
        if not _matches(*_number(m), values):
            reasons.append(f"'{m.group(0).strip()}' is not in the payload")
    for m in NUMBER_WORD.finditer(rest):
        n += 1
        if m.group(0).lower() not in words:
            reasons.append(f"'{m.group(0)}' is a number in words; write payload numbers in digits")
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
    if hit and validate(hit["text"], facts)[0]:   # a brief cached under an older, looser validator is redone
        return {**hit, "paragraphs": paragraphs(hit["text"]), "status": "ok", "cached": True, "payload": facts}
    down = {"status": "llm_unavailable", "detail": f"LM Studio was unreachable in the last {client.DOWN_S} s"}
    if client.down_recently():
        return down
    reasons, attempts = [], 0
    try:
        # one generation at a time on the local model (llm/client.py LLM_GATE); chat answers go first
        with client.gate(BUSY_WAIT_S) as free:
            if not free:
                return {"status": "llm_unavailable", "detail": f"the local LLM stayed busy for {BUSY_WAIT_S} s"}
            if client.down_recently():   # the request that held the gate found LM Studio down
                return down
            for attempt in range(2):
                attempts = attempt + 1
                text = _ask(facts, re.findall(r"'([^']*)'", " ".join(reasons)) if attempt else None)
                ok, reasons, n = validate(text, facts)
                if ok:
                    break
    except client.LLMConnectionError as e:
        if e.down:   # refused: shared with the chat and the second opinion; a timeout or HTTP error is not
            client.mark_down()
        return {"status": "llm_unavailable", "detail": str(e)[:300]}
    if not ok:
        return {"status": "rejected", "reasons": reasons, "attempts": attempts}
    out = {"key": key, "asof": asof, "model_version": mv, "text": text,
           "paragraphs": paragraphs(text),
           "n_numbers_checked": n, "attempts": attempts,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    db.save_brief(out)
    return {**out, "status": "ok", "cached": False, "payload": facts}
