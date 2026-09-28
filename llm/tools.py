"""The chat assistant's tools (docs/AI_ASSISTANT.md): read-only functions over the served data that the router or the
planner (llm/router.py, llm/agent.py) call for one question.

Each tool is `fn(viewer, **args) -> ToolResult` with a pydantic args model (extra fields are an error; sector, state,
ministry and agency are matched to the portfolio's own values, a project key to its canonical PRJ key), a one-line
description for the planner's catalogue, a label for the progress list, and `public`: whether the public may use it;
the others need a feature of backend/access.py POLICY (explain_prediction and second_opinion 'insights',
agency_scorecard 'agencies', bottlenecks 'bottlenecks'). The Viewer always comes from the server: no tool takes a
scope argument, every project row is cut to viewer.scope, and a project outside it is "not found", worded exactly
like an unknown key, so an answer never reveals that it exists. Who counts as an official follows the routes:
viewer.can('insights'); anyone else gets the public outputs, built from serving.public_project / public_page /
public_external / public_research / public_research_summary (no drivers, intervals, rank, evidence lines, PARIVESH
details, provenance, match reasons or agent headlines).

A ToolResult has
  summary  one plain line with only numbers from its facts (the progress list and the deterministic answer),
  cards    the SPEC 4 card dicts, camelCase, sent to the browser as they are,
  facts    the compact JSON the writer may use and the answer is checked against (backend/brief.validate): percents
           as whole numbers ('slip_chance_2q_pct': 69), money in Rs crore, dates as 'June 2028', small lists capped;
           a dict item with "cite": i points at the i-th of the result's own sources (1-based; the agent renumbers),
           the whole block at its first source unless it says otherwise,
  sources  what the answer may cite, {kind, title, source, url, date, projectKey},
  keys     the projects the result is about (follow-up questions, the second planning round),
  found    False when there is nothing to show (unknown or out-of-scope project, no match).
Outside text (report remarks, headlines, research notes and status lines, PARIVESH and register lines, search hits that
are not PAIMANA's own words) goes through quote(): one line, no prompt markers, code fences or tags, capped; the agent
puts every fact inside one delimited data block that the prompt calls quoted material.
"""
from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from backend import db, labels, serving
from llm import rag

TOP_FACTS = 8            # list items the writer gets (a card may show more)
NEWS_N, RESEARCH_N = 4, 6
PASSAGE_CHARS = 700      # a trusted search hit (help, doc, glossary, project card) is cut here, an outside one at 500
HORIZONS = [2, 4]        # the model's horizons in quarters, so "within 2 quarters" is a number the facts contain
FLAG_WORDS = {"land": "land acquisition", "forest": "forest clearance", "litigation": "court case",
              "contractor": "contractor problems", "early_notice": "early notice"}
FACTOR_FLAG = {"land": "land", "forest_clearance": "forest", "litigation": "litigation", "contractor": "contractor"}
BOTTLENECK_CATEGORY = {"forest": "forest_env", "forest_clearance": "forest_env", "environment": "forest_env",
                       "court": "litigation", "funds": "funding"}
MARKERS = re.compile(r"<<<|>>>|```|<\|[^<>]*\|>|</?[A-Za-z][^<>]{0,40}>")
SPACE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")
KEY_RX = re.compile(r"^PRJ[-\s]?(\d{1,6})$", re.I)
Tier = Literal["Critical", "High", "Medium", "Low", "Watch"]
Flag = Literal["land", "forest", "litigation", "contractor", "early_notice"]
Factor = Literal["land", "forest_clearance", "litigation", "contractor", "utility_shifting", "inter_agency"]


@dataclass
class ToolResult:
    summary: str
    cards: list[dict] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    found: bool = True


@dataclass(frozen=True)
class Tool:
    name: str
    label: str
    description: str
    args: type[BaseModel]
    fn: Callable[..., ToolResult]
    public: bool
    feature: str | None = None   # what an official needs (POLICY) when the tool is not public

    def allowed(self, viewer) -> bool:
        return self.public or (self.feature is not None and viewer.can(self.feature))


class ToolError(ValueError):
    """A call the viewer may not make, or a tool that does not exist."""


TOOLS: dict[str, Tool] = {}


def tool(name: str, label: str, description: str, args: type[BaseModel], public: bool, feature: str | None = None):
    def register(fn):
        TOOLS[name] = Tool(name, label, description, args, fn, public, feature)
        return fn
    return register


def available(viewer) -> list[Tool]:
    """The tools this viewer may call, in catalogue order."""
    return [t for t in TOOLS.values() if t.allowed(viewer)]


def validate_args(viewer, name: str, args: dict | None) -> dict:
    """The call's arguments checked by the tool's model (pydantic ValidationError, a ValueError, when wrong);
    ToolError for a tool that does not exist or that the viewer may not use."""
    t = TOOLS.get(name)
    if t is None or not t.allowed(viewer):
        raise ToolError(f"no tool {name!r} for this viewer")
    return t.args.model_validate(args or {}).model_dump()


def run(viewer, name: str, args: dict | None = None) -> ToolResult:
    """Validate and run one call."""
    return TOOLS[name].fn(viewer, **validate_args(viewer, name, args))


def catalogue(viewer) -> str:
    """One line per tool the viewer may use, 'name(arg, optional?, choice: a|b): description' (the planner)."""
    out = []
    for t in available(viewer):
        parts = []
        for n, f in t.args.model_fields.items():
            lit = _literal_args(f.annotation)
            parts.append(f"{n}{'' if f.is_required() else '?'}" + (f": {'|'.join(map(str, lit))}" if lit else ""))
        out.append(f"{t.name}({', '.join(parts)}): {t.description}")
    return "\n".join(out)


def _literal_args(ann) -> list:
    """The choices of a Literal annotation (also inside Optional / Annotated), else []."""
    args = getattr(ann, "__args__", ())
    if getattr(ann, "__origin__", None) is Literal:
        return list(args)
    for a in args:
        if getattr(a, "__origin__", None) is Literal:
            return list(a.__args__)
    return []


# ------------------------------------------------------------------ small helpers

def quote(s, n: int = 300) -> str | None:
    """Outside text for a prompt: one line, no prompt markers, code fences or tags, at most n characters."""
    if s is None:
        return None
    s = SPACE.sub(" ", MARKERS.sub(" ", str(s))).strip().replace('"', "'")
    return (s[: n - 3].rstrip() + "...") if len(s) > n else s or None


def _pct(p) -> int | None:
    return None if p is None else round(100 * float(p))


def _r(v, nd: int = 1):
    if v is None:
        return None
    v = round(float(v), nd)
    return int(v) if nd == 0 else v


def _month(d) -> str | None:
    """'June 2028' for a date or an ISO string, None for none."""
    if d is None or d == "":
        return None
    if isinstance(d, str):
        try:
            d = date.fromisoformat(d[:10])
        except ValueError:
            return None
    return f"{d:%B %Y}"


def _iso(d) -> str | None:
    return None if d is None else str(d)[:10]


def _short(name: str | None, n: int = 14) -> str | None:
    w = (name or "").split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "") if w else name


def _compact(d: dict) -> dict:
    """d without None values and empty lists or dicts (fewer prompt tokens)."""
    return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}


def _asof() -> str:
    return _month(serving.state()["asof"])


def _official(viewer) -> bool:
    return viewer.can("insights")


def _src(kind: str, title: str, source: str, url: str | None = None, when=None, key: str | None = None) -> dict:
    return {"kind": kind, "title": title, "source": source, "url": url, "date": _iso(when), "projectKey": key}


def _resolve(viewer, key: str | None) -> str | None:
    """The canonical key when the project exists and is in the viewer's scope, else None (the same for both)."""
    if not key:
        return None
    k = serving.canonical(key)
    return k if k is not None and viewer.sees(k) else None


def _not_found(key) -> ToolResult:
    shown = re.sub(r"[^A-Za-z0-9-]", "", str(key or ""))[:32] or "that project"
    return ToolResult(summary=f"Project {shown} was not found.", facts={"not_found": shown}, found=False)


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else f"{n} {word}s"


# ------------------------------------------------------------------ argument types

def _norm_key(v: str) -> str:
    v = v.strip()
    m = KEY_RX.match(v)
    return f"PRJ-{int(m[1]):06d}" if m else v.upper()


@serving.cached
def _chat_values(s) -> dict[str, dict[str, str]]:
    """Lower-cased value -> the portfolio's own spelling, per filter (current projects)."""
    out = {}
    for col in ("sector", "state", "ministry"):
        out[col] = {r["v"].lower(): r["v"] for r in serving._rows(
            s, f"SELECT DISTINCT {col} AS v FROM cur WHERE {col} IS NOT NULL")}
    out["agency"] = {a["name"].lower(): a["name"] for a in serving.scopes()["agencies"]}
    return out


def values(kind: str) -> dict[str, str]:
    return _chat_values()[kind]


def _known(kind: str):
    def check(v: str) -> str:
        known = values(kind)
        low = " ".join(v.lower().replace(" and ", " & ").split())
        if low in known:
            return known[low]
        if kind == "ministry":  # 'coal' or 'Coal ministry' -> 'Ministry of Coal' when only one ministry has the word
            word = re.sub(r"\b(?:ministry|of|the|department)\b", " ", low).strip()
            hits = [m for k, m in known.items() if word and re.search(rf"\b{re.escape(word)}\b", k)]
            if len(hits) == 1:
                return hits[0]
        raise ValueError(f"unknown {kind} {v!r}")
    return check


Key = Annotated[str, Field(min_length=3, max_length=32), AfterValidator(_norm_key)]
Sector = Annotated[str, Field(max_length=60), AfterValidator(_known("sector"))]
State = Annotated[str, Field(max_length=60), AfterValidator(_known("state"))]
Ministry = Annotated[str, Field(max_length=100), AfterValidator(_known("ministry"))]
Agency = Annotated[str, Field(max_length=100), AfterValidator(_known("agency"))]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SearchArgs(Args):
    q: str | None = Field(None, max_length=100)
    tier: Tier | None = None
    sector: Sector | None = None
    state: State | None = None
    ministry: Ministry | None = None
    agency: Agency | None = None
    flag: Flag | None = None
    near_complete: bool = False
    sort: Literal["risk", "cost", "slip", "progress", "name"] = "risk"
    order: Literal["asc", "desc"] | None = None
    limit: int = Field(10, ge=1, le=20)


class StatsArgs(Args):
    group_by: Literal["state", "sector", "ministry", "tier"] = "state"
    rank_by: Literal["capital", "projects"] = "capital"
    tier: Tier | None = None
    sector: Sector | None = None
    state: State | None = None
    ministry: Ministry | None = None


class KeyArgs(Args):
    key: Key


class CompareArgs(Args):
    keys: list[Key] = Field(min_length=2, max_length=4)


class ResearchArgs(Args):
    key: Key | None = None


class ExternalArgs(Args):
    key: Key | None = None
    factor: Factor | None = None
    state: State | None = None
    limit: int = Field(5, ge=1, le=20)


class KnowledgeArgs(Args):
    q: str = Field(min_length=2, max_length=300)
    k: int = Field(5, ge=1, le=8)


class AgencyArgs(Args):
    agency: Agency | None = None
    sort: Literal["capital", "schedule_overrun", "cost_overrun"] = "capital"
    limit: int = Field(8, ge=1, le=15)


class BottleneckArgs(Args):
    category: str | None = Field(None, max_length=40)
    state: State | None = None
    limit: int = Field(5, ge=1, le=10)


# ------------------------------------------------------------------ shared builders

def _row_item(r: dict) -> dict:
    """A list row (serving ROW_SQL) as a 'projects' card item."""
    return {"key": r["key"], "name": r["name"], "sector": r["sector"], "state": r["state"],
            "ministry": r["ministry"], "agency": r["agency"], "tier": r["tier"], "pAny2q": r["p_any_2q"],
            "anticipatedCostCr": r["anticipated_cost_cr"], "physicalProgressPct": r["physical_progress_pct"],
            "anticipatedCompletion": _iso(r["anticipated_completion"]), "flags": r["flags"] or []}


def _row_fact(r: dict) -> dict:
    return _compact({"key": r["key"], "name": _short(r["name"]), "state": r["state"], "tier": r["tier"],
                     "slip_chance_2q_pct": _pct(r["p_any_2q"]), "cost_cr": _r(r["anticipated_cost_cr"]),
                     "progress_pct": _r(r["physical_progress_pct"]),
                     "completion": _month(r["anticipated_completion"]),
                     "flags": [FLAG_WORDS.get(f, f) for f in r["flags"] or []]})


def _rows(viewer, **kw) -> dict:
    page = serving.projects(**kw, scope=viewer.scope)
    return page if _official(viewer) else serving.public_page(page)


def _bundle(viewer, key: str) -> tuple[dict, dict | None]:
    """(the project page, redacted for the public; its current list row or None for a past project)."""
    d = serving.project(key)
    rows = serving.rows_for_keys((key,))
    row = rows[0] if rows else None
    if not _official(viewer):
        d = serving.public_project(d)
        row = row and serving.public_page({"items": [row]})["items"][0]
    return d, row


def _name(d: dict, row: dict | None) -> str:
    return (row and row["name"]) or (d["master"] or {}).get("project_name") or d["key"]


def _project_card(d: dict, row: dict | None) -> dict:
    sc, latest = d["scores"] or {}, d["latest"] or {}
    return {"type": "project", "key": d["key"], "name": _name(d, row), "tier": sc.get("tier"),
            "pAny2q": sc.get("p_any_2q"), "pDatePush2q": sc.get("p_date_push_2q"),
            "pCostRev2q": sc.get("p_cost_rev_2q"), "monthsP50": sc.get("months_p50"),
            "progressPct": row["physical_progress_pct"] if row else latest.get("physical_progress_pct"),
            "costCr": row["anticipated_cost_cr"] if row else latest.get("anticipated_cost_cr"),
            "anticipatedCompletion": _iso(row["anticipated_completion"] if row
                                          else latest.get("anticipated_completion")),
            "topRisksPlain": d["top_risks_plain"], "flags": d["flags"]}


def _project_facts(viewer, d: dict, row: dict | None, brief: bool = False) -> dict:
    """The facts of one project page; brief: the compare subset."""
    sc, latest, m = d["scores"] or {}, d["latest"] or {}, d["master"] or {}
    tier = sc.get("tier")
    f = {"key": d["key"], "name": _short(_name(d, row), 25), "state": m.get("state") or latest.get("state"),
         "tier": tier, "slip_chance_2q_pct": _pct(sc.get("p_any_2q")),
         "progress_pct": _r(latest.get("physical_progress_pct")),
         "anticipated_cost_cr": _r(latest.get("anticipated_cost_cr")),
         "anticipated_completion": _month(latest.get("anticipated_completion")),
         "slip_so_far_months": _r(row and row["slip_to_date_months"], 0), "top_risks": d["top_risks_plain"]}
    if brief:
        return _compact(f)
    f.update({"sector": m.get("sector"), "ministry": m.get("ministry"), "agency": m.get("agency"),
              "horizon_quarters": HORIZONS, "as_of": _month(d["provenance"]["asof"]),
              "latest_report": _month(latest.get("period")), "stalled": bool(sc.get("stagnation_override")) or None,
              "date_push_chance_2q_pct": _pct(sc.get("p_date_push_2q")),
              "cost_revision_chance_2q_pct": _pct(sc.get("p_cost_rev_2q")),
              "slip_chance_4q_pct": _pct(sc.get("p_any_4q")), "likely_slip_months_2q": _r(sc.get("months_p50")),
              "original_cost_cr": _r(latest.get("original_cost_cr")), "spent_cr": _r(latest.get("expenditure_cr")),
              "sanctioned": _month(m.get("sanction_date")),
              "original_completion": _month(latest.get("scheduled_completion")),
              "flags": [FLAG_WORDS.get(x, x) for x in d["flags"]]})
    if tier == serving.WATCH:
        f["tier_note"] = ("Watch: the reports give no anticipated completion date, so the project is not ranked by "
                          "the chance of a slip")
    if not d["scores"]:
        f["status_note"] = "not in the current scored portfolio (completed, dropped or not in the latest report)"
    if _official(viewer) and sc.get("months_p05") is not None:
        f["slip_months_90pct_range"] = [_r(sc["months_p05"]), _r(sc["months_p95"])]
    if _official(viewer):
        f["flagged_checks"] = [labels.dimension_label(r["dimension"]) for r in d["risk_profile"]
                               if r["state"] == "flagged"]
    rs = d.get("research") or {}
    if rs.get("searched"):
        f["web_research"] = {"facts": rs["n_facts"], "live_blockers": rs["n_negative_live"]}
    return _compact(f)


def _project_source(d: dict, row: dict | None, what: str = "PAIMANA project page") -> dict:
    return _src("project", _short(_name(d, row), 20), what, when=d["provenance"]["asof"], key=d["key"])


def _tier_words(tier: str | None, pct: int | None) -> str:
    if tier is None:
        return "is not in the current scored portfolio"
    if tier == serving.WATCH or pct is None:
        return f"is in the {tier} tier"
    return f"is in the {tier} tier, with a {pct}% chance of a schedule or cost slip within 2 quarters"


def _filters_words(f: dict) -> str:
    bits = [f.get("tier") and f"{f['tier']}", f.get("sector"), f.get("ministry"), f.get("agency"),
            f.get("flag") and f"flagged for {FLAG_WORDS.get(f['flag'], f['flag'])}",
            f.get("state") and f"in {f['state']}", f.get("q") and f"matching '{quote(f['q'], 40)}'",
            f.get("near_complete") and "near completion"]
    return ", ".join(b for b in bits if b)


# ------------------------------------------------------------------ public tools

@tool("search_projects", "Searching projects",
      "find current projects by name words (q) or filters, riskiest first; near_complete: 80-99% done",
      SearchArgs, public=True)
def search_projects(viewer, q=None, tier=None, sector=None, state=None, ministry=None, agency=None, flag=None,
                    near_complete=False, sort="risk", order=None, limit=10) -> ToolResult:
    if near_complete and sort == "risk" and order is None:
        sort, order = "progress", "desc"
    page = _rows(viewer, q=q, tier=tier, sector=sector, state_=state, ministry=ministry, agency=agency, flag=flag,
                 near_complete=near_complete, sort=sort, order=order, size=limit)
    filters = _compact({"q": q, "tier": tier, "sector": sector, "state": state, "ministry": ministry,
                        "agency": agency, "flag": flag, "near_complete": near_complete or None})
    items, total, what = page["items"], page["total"], _filters_words(filters)
    title = f"Projects{': ' + what if what else ''}"
    facts = {"filters": filters, "total_matching": total, "shown": len(items), "sorted_by": sort,
             "projects": [_row_fact(r) for r in items[:TOP_FACTS]]}
    if not items:
        return ToolResult(summary=f"No current project matches ({what or 'no filter'}).", facts=facts,
                          sources=[_src("portfolio", title, "PAIMANA project list", when=serving.state()["asof"])],
                          found=False)
    first = items[0]
    summary = (f"{_plural(total, 'current project')} match{'es' if total == 1 else ''}"
               f"{' (' + what + ')' if what else ''}; first by {sort}: {_short(first['name'], 10)} ({first['key']}, "
               f"{first['tier'] or 'no tier'}).")
    return ToolResult(summary=summary, facts=facts,
                      cards=[{"type": "projects", "title": title, "total": total,
                              "items": [_row_item(r) for r in items]}],
                      sources=[_src("portfolio", title, "PAIMANA project list", when=serving.state()["asof"])],
                      keys=[r["key"] for r in items])


@tool("portfolio_stats", "Counting the portfolio",
      "counts, capital and tier counts of the current projects, grouped by state, sector, ministry or tier",
      StatsArgs, public=True)
def portfolio_stats(viewer, group_by="state", rank_by="capital", tier=None, sector=None, state=None,
                    ministry=None) -> ToolResult:
    p = serving.portfolio(ministry, sector, state, tier, scope=viewer.scope)
    k = p["kpis"]
    if group_by == "tier":
        rows = [{"name": t["tier"], "n": t["n"], "capital_cr": t["capital_cr"],
                 "n_critical": t["n"] if t["tier"] == "Critical" else 0,
                 "n_high": t["n"] if t["tier"] == "High" else 0} for t in p["tiers"]]
    else:  # serving orders by capital; 'which state has the most ...' ranks by the number of projects
        rows = p[f"by_{group_by}"]
        if rank_by == "projects":
            rows = sorted(rows, key=lambda r: -r["n"])
    filters = _compact({"tier": tier, "sector": sector, "state": state, "ministry": ministry})
    what = _filters_words(filters)
    title = f"Current projects by {group_by}" + (f" ({what})" if what else "")
    facts = {"filters": filters, "as_of": _asof(), "projects": k["n_projects"],
             "anticipated_cost_cr": _r(k["anticipated_cost_cr"], 0), "spent_cr": _r(k["expenditure_cr"], 0),
             "cost_overrun_pct": _r(k["overrun_pct"]), "average_progress_pct": _r(k["avg_progress_pct"]),
             "tiers": {t["tier"]: t["n"] for t in p["tiers"]}, "group_by": group_by,
             "groups_ranked_by": "number of projects" if rank_by == "projects" else "capital",
             "groups": [_compact({"name": r["name"], "projects": r["n"], "capital_cr": _r(r["capital_cr"], 0),
                                  "critical": r["n_critical"], "high": r["n_high"]}) for r in rows[:10]],
             "groups_total": len(rows)}
    top = rows[0] if rows else None
    summary = (f"{_plural(k['n_projects'], 'current project')}{' (' + what + ')' if what else ''}"
               + (f" with an anticipated cost of Rs {k['anticipated_cost_cr']:,.0f} crore"
                  if k["anticipated_cost_cr"] is not None else "")
               + (f"; the {group_by} with the most is {top['name']} with {_plural(top['n'], 'project')}"
                  if top and group_by != "tier" and rank_by == "projects" else
                  f"; the largest {group_by} by capital is {top['name']} with {_plural(top['n'], 'project')}"
                  if top and group_by != "tier" else "") + ".")
    return ToolResult(summary=summary, facts=_compact(facts),
                      cards=[{"type": "stats", "title": title, "groupBy": group_by,
                              "rows": [{"name": r["name"], "n": r["n"], "capitalCr": r["capital_cr"],
                                        "nCritical": r["n_critical"], "nHigh": r["n_high"]} for r in rows[:40]]}],
                      sources=[_src("portfolio", title, "PAIMANA portfolio", when=p["asof"])],
                      found=k["n_projects"] > 0)


@tool("get_project", "Reading the project page",
      "one project's tier, chance of a slip, progress, cost, dates and top risks (key: PRJ-######)", KeyArgs,
      public=True)
def get_project(viewer, key) -> ToolResult:
    k = _resolve(viewer, key)
    if k is None:
        return _not_found(key)
    d, row = _bundle(viewer, k)
    facts = _project_facts(viewer, d, row)
    progress, when = facts.get("progress_pct"), facts.get("anticipated_completion")
    summary = (f"{_short(_name(d, row), 12)} ({k}) {_tier_words(facts.get('tier'), facts.get('slip_chance_2q_pct'))}"
               + (f"; progress {progress:g}%" if progress is not None else "")
               + (f", anticipated completion {when}" if when else "") + ".")
    return ToolResult(summary=summary, facts=facts, cards=[_project_card(d, row)],
                      sources=[_project_source(d, row)], keys=[k])


def _changes(points: list[dict]) -> list[str]:
    """What moved between the last reports: progress over the window, each completion-date and cost revision."""
    if len(points) < 2:
        return []
    out, a, b = [], points[0], points[-1]
    pa, pb = a["physical_progress_pct"], b["physical_progress_pct"]
    ma, mb = _month(a["period"]), _month(b["period"])
    if pa is not None and pb is not None:
        delta = round(pb - pa, 1)
        out.append(f"Progress stayed at {pb:g}% from the {ma} report to the {mb} report." if delta == 0 else
                   f"Progress {'rose' if delta > 0 else 'fell'} {abs(delta):g} points, from {pa:g}% in the {ma} "
                   f"report to {pb:g}% in the {mb} report.")
    for col, what, fmt in (("anticipated_completion", "Anticipated completion", _month),
                           ("anticipated_cost_cr", "Anticipated cost", lambda v: f"Rs {v:,.2f} crore")):
        moves = [(p, q) for p, q in zip(points, points[1:]) if p[col] is not None and q[col] is not None
                 and p[col] != q[col]]
        for p, q in moves[-3:]:
            out.append(f"{what} moved from {fmt(p[col])} to {fmt(q[col])} in the {_month(q['period'])} report.")
        if not moves and b[col] is not None:
            out.append(f"{what} unchanged at {fmt(b[col])} since the {ma} report.")
    return out


@serving.cached
def _chat_prediction_log(s, key):
    """The project's logged predictions, the latest model per asof (serving.live_accuracy's deduplication)."""
    path = serving._posix(serving.GOLD / "prediction_log.parquet")
    return serving._rows(s, f"""SELECT "asof", tier, p_any_2q FROM read_parquet('{path}') WHERE project_key = ?
        QUALIFY row_number() OVER (PARTITION BY project_key, "asof" ORDER BY model_version DESC) = 1
        ORDER BY "asof" """, [key])


@tool("project_history", "Reading the report history",
      "one project's progress, cost and completion date over its reports and what changed lately (key)", KeyArgs,
      public=True)
def project_history(viewer, key) -> ToolResult:
    k = _resolve(viewer, key)
    if k is None:
        return _not_found(key)
    d, row = _bundle(viewer, k)
    pts, name = serving.timeline(k), _name(d, row)
    window = pts[-5:]
    facts = {"key": k, "name": _short(name, 25), "reports_total": len(pts),
             "reports": [_compact({"period": _month(p["period"]), "progress_pct": _r(p["physical_progress_pct"]),
                                   "anticipated_cost_cr": _r(p["anticipated_cost_cr"], 2),
                                   "anticipated_completion": _month(p["anticipated_completion"])}) for p in window],
             "changes": _changes(window)}
    sources = [_project_source(d, row, "PAIMANA progress history (project reports)")]
    if _official(viewer):
        alerts = [a for a in db.alerts(keys={k}, size=50)["items"] if a["kind"] in ("tier_up", "tier_down")][:5]
        facts["tier_alerts"] = [{"date": _month(a["created_at"]), "title": quote(a["title"], 120),
                                 "detail": quote(a["detail"], 160)} for a in alerts]
        log = _chat_prediction_log(k)
        if len(log) > 1:
            facts["predictions"] = [_compact({"as_of": _month(r["asof"]), "tier": r["tier"],
                                              "slip_chance_2q_pct": _pct(r["p_any_2q"])}) for r in log[-6:]]
    if not pts:
        return ToolResult(summary=f"No report history for {_short(name, 12)} ({k}).", facts=_compact(facts),
                          sources=sources, keys=[k], found=False)
    summary = " ".join([f"{_short(name, 12)} ({k}) has {_plural(len(pts), 'report')}."] + facts["changes"][:2])
    card = {"type": "history", "key": k, "name": name,
            "points": [{"period": _iso(p["period"]), "progressPct": p["physical_progress_pct"],
                        "costCr": p["anticipated_cost_cr"], "anticipatedCompletion": _iso(p["anticipated_completion"])}
                       for p in pts[-24:]], "changes": facts["changes"]}
    return ToolResult(summary=summary, facts=_compact(facts), cards=[card], sources=sources, keys=[k])


@tool("compare_projects", "Comparing projects",
      "two to four projects side by side: tier, chance of a slip, progress, cost, completion (keys)", CompareArgs,
      public=True)
def compare_projects(viewer, keys) -> ToolResult:
    seen, cards, facts, sources, missing = [], [], [], [], []
    for key in keys:
        k = _resolve(viewer, key)
        if k is None:
            missing.append(re.sub(r"[^A-Za-z0-9-]", "", key)[:32])
            continue
        if k in seen:
            continue
        seen.append(k)
        d, row = _bundle(viewer, k)
        cards.append(_project_card(d, row))
        facts.append({**_project_facts(viewer, d, row, brief=True), "cite": len(sources) + 1})
        sources.append(_project_source(d, row))
    out = _compact({"horizon_quarters": HORIZONS, "projects": facts, "not_found": missing})
    if not cards:
        return ToolResult(summary="None of those projects was found.", facts=out, found=False)
    parts = [f"{_short(c['name'], 8)} ({c['key']}): {c['tier'] or 'no tier'}" for c in cards]
    return ToolResult(summary="Compared " + "; ".join(parts) + "." + (
        f" Not found: {', '.join(missing)}." if missing else ""), facts=out,
        cards=[{"type": "compare", "items": cards}], sources=sources, keys=seen)


def _newest(f: dict) -> date:
    d = f.get("event_date") or f.get("published_date")
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10]) if d else date.min


def _fact_date(f: dict) -> str | None:
    d, prec = f.get("event_date"), f.get("date_precision")
    if d is None:
        return _month(f.get("published_date"))
    return str(d)[:4] if prec == "year" else _month(d) if prec == "month" else str(d)[:10]


def _research_one(viewer, k: str) -> ToolResult:
    d, row = _bundle(viewer, k)
    name = _name(d, row)
    r = serving.research(k)
    if not _official(viewer):
        r = serving.public_research(r)
    ranked = sorted(r["facts"], key=_newest, reverse=True)  # live blockers first, most severe, then newest
    ranked = sorted(ranked, key=lambda f: (not f["live"], -(f["severity"] or 0)))[:RESEARCH_N]
    sources = [_project_source(d, row, "PAIMANA web research")]
    items = []
    for f in ranked:
        sources.append(_src("research", quote(f["headline"], 160) or quote(f["summary"], 90) or f["source"],
                            quote(f["source"], 80) or "web research", f["url"], f["event_date"] or f["published_date"],
                            k))
        items.append(_compact({"cite": len(sources), "date": _fact_date(f),
                               "category": rag.CATEGORY_WORDS.get(f["category"], f["category"]),
                               "direction": f["direction"], "severity": f["severity"], "status": quote(f["status"], 40),
                               "live_blocker": f["live"] or None, "summary": quote(f["summary"], 240),
                               "source": quote(f["source"], 80)}))
    news = []
    if _official(viewer):
        sig = db.project_signals(k, limit=40)["items"]  # newest first; the most severe of them first
        sig = sorted(sig, key=lambda s: -(s["severity"] or 0))[:NEWS_N]
        for s in sig:
            sources.append(_src("news", quote(s["title"], 160) or "news item", quote(s["source"], 80) or "news",
                                s["url"], (s["published_at"] or "")[:10] or None, k))
            news.append(_compact({"cite": len(sources), "date": _month(s["published_at"]),
                                  "source": quote(s["source"], 80), "headline": quote(s["title"], 200),
                                  "category": rag.CATEGORY_WORDS.get(s["category"], s["category"]),
                                  "severity": s["severity"]}))
    ext = {n: {f: quote(v, 120) if isinstance(v, str) else v for f, v in e.items()}
           for n, e in (r["external"] or {}).items() if e}
    facts = _compact({"key": k, "name": _short(name, 25), "searched": r["searched"],
                      "researched_on": _month(r["researched_on"] or r["agent_researched_at"]),
                      "latest_status": quote(r["latest_status"], 300), "outside_status": ext,
                      "facts_total": r["n_facts"], "live_blockers": r["n_negative_live"], "facts": items,
                      "news": news, "news_shown": len(news) or None,
                      "note": "A live blocker is negative, not resolved and dated within the last 4 quarters."})
    if not r["searched"]:
        summary = f"{_short(name, 12)} ({k}) has not been researched on the web yet."
    elif not r["facts"]:
        summary = f"Web research on {_short(name, 12)} ({k}) found nothing."
    else:
        summary = (f"Web research on {_short(name, 12)} ({k}): {_plural(r['n_facts'], 'fact')}, "
                   f"{_plural(r['n_negative_live'], 'live blocker')}.")
    if news:
        summary += f" {_plural(len(news), 'linked news item')} shown."
    return ToolResult(summary=summary, facts=facts, sources=sources, keys=[k],
                      found=bool(r["facts"] or news or r["latest_status"]))


def _research_all(viewer) -> ToolResult:
    r = serving.research_summary(scope=viewer.scope)
    official = _official(viewer)
    if not official:
        r = serving.public_research_summary(r)
    cov = r["coverage"]
    sources = [_src("research", "Web research summary", "PAIMANA web research", when=r["asof"])]
    blockers = []
    for b in r["top_recent_blockers"][:5]:
        sources.append(_src("research", quote(b["headline"], 160) or quote(b.get("summary"), 90) or "web research",
                            quote(b.get("source"), 80) or "web research", b["url"],
                            b["event_date"] or b["published_date"], b.get("project_key") if official else None))
        blockers.append(_compact({"cite": len(sources), "date": _fact_date(b), "headline": quote(b["headline"], 160),
                                  **({"project": _short(b["project_name"], 10), "key": b["project_key"],
                                      "tier": b["tier"], "category": rag.CATEGORY_WORDS.get(b["category"]),
                                      "summary": quote(b["summary"], 200)} if official else {})}))
    cats = sorted(r["by_category"], key=lambda c: -c["n_live"])[:6]
    facts = _compact({"projects_current": cov["n_current"], "projects_searched": cov["n_searched"],
                      "projects_with_facts": cov["n_with_facts"], "facts_total": cov["n_facts"],
                      "live_blockers": cov["n_negative_live"],
                      "projects_with_live_blockers": cov["n_projects_negative_live"],
                      "researched_between": [_month(r["researched_on"]["first"]), _month(r["researched_on"]["last"])],
                      "live_by_category": [{"category": rag.CATEGORY_WORDS.get(c["category"], c["category"]),
                                            "live": c["n_live"], "negative": c["negative"]} for c in cats
                                           if c["n_live"] or c["negative"]],
                      "recent_blockers": blockers, "note": quote(r["note"], 400)})
    keys = [b["project_key"] for b in r["top_recent_blockers"] if b.get("project_key")] if official else []
    cards = []
    if keys:
        rows = serving.rows_for_keys(tuple(dict.fromkeys(keys))[:20])
        cards.append({"type": "projects", "title": "Projects with recent live blockers in web research",
                      "total": len(rows), "items": [_row_item(x) for x in rows]})
    summary = (f"Web research covers {_plural(cov['n_searched'], 'searched project')} of {cov['n_current']}; "
               f"{_plural(cov['n_negative_live'], 'live blocker')} on "
               f"{_plural(cov['n_projects_negative_live'], 'project')}.")
    return ToolResult(summary=summary, facts=facts, cards=cards, sources=sources, keys=list(dict.fromkeys(keys)),
                      found=cov["n_searched"] > 0)


@tool("project_research", "Reading web research and news",
      "web research facts (and, for officials, linked news) of one project (key), or the latest blockers across "
      "the portfolio (no key)", ResearchArgs, public=True)
def project_research(viewer, key=None) -> ToolResult:
    if key is None:
        return _research_all(viewer)
    k = _resolve(viewer, key)
    return _not_found(key) if k is None else _research_one(viewer, k)


EXTERNAL_DIMS = ("land_acquisition", "forest_clearance", "litigation", "contractor_stress", "external_composite")


def _external_one(viewer, k: str) -> ToolResult:
    d, row = _bundle(viewer, k)
    name, ext, official = _name(d, row), d["external"], _official(viewer)
    land, fc, comp = ext["land"] or {}, ext["fc"] or {}, ext["composite"] or {}
    checks = [_compact({"check": labels.dimension_label(r["dimension"]), "state": r["state"],
                        "evidence": quote(r["evidence"], 200) if official else None})
              for r in d["risk_profile"] if r["dimension"] in EXTERNAL_DIMS]
    open_events = [e for e in ext["events"] if e["status"] == "open"]
    events = [_compact({"issue": rag.CATEGORY_WORDS.get(e["category"], e["category"]),
                        "first_reported": _month(e["first_seen"]), "last_reported": _month(e["last_seen"]),
                        "remark": quote(e["evidence"], 200)}) for e in open_events[:4]]
    facts = {"key": k, "name": _short(name, 25), "flags": [FLAG_WORDS.get(x, x) for x in d["flags"]],
             "checks": checks,
             "land_register": _compact({"state": land.get("la_state"),
                                        "evidence": quote(land.get("la_evidence"), 240)}),
             "forest": _compact({"mentioned_in_remarks": fc.get("fc_mentioned") or None,
                                 "pending_in_remarks": fc.get("fc_pending") or None,
                                 "route": quote(fc.get("fc_evidence"), 240)}),
             "land_and_forest_score": _compact({"score": _r(comp.get("external_factor_score"), 2),
                                                "coverage": comp.get("coverage"),
                                                "evidence": quote(comp.get("ext_score_evidence"), 200)}),
             "open_report_issues": events, "open_report_issues_total": len(open_events) or None,
             "note": "Report remarks are free text only through 2023; the land register rates road projects only."}
    if official and ext.get("portal"):
        p = ext["portal"]
        facts["parivesh"] = _compact({"proposals": p.get("n_proposals"), "open": p.get("n_open"),
                                      "past_rule_limit": p.get("n_overdue"), "stage": quote(p.get("stage_at_asof"), 60),
                                      "months_in_stage": _r(p.get("months_in_stage")),
                                      "rule_months": _r(p.get("norm_months"))})
    flagged = [c["check"] for c in checks if c.get("state") == "flagged"]
    summary = (f"Outside factors for {_short(name, 12)} ({k}): "
               + (f"flagged: {', '.join(flagged)}" if flagged else "no outside factor is flagged")
               + (f"; {_plural(len(open_events), 'open report issue')}" if open_events else "") + ".")
    sources = [_project_source(d, row, "PAIMANA outside factors (report remarks, land register, forest rules"
                                       + (", PARIVESH)" if official else ")"))]
    return ToolResult(summary=summary, facts=_compact(facts), cards=[_project_card(d, row)], sources=sources,
                      keys=[k])


@serving.cached
def _chat_factor_counts(s, scope):
    """Per external factor: current projects in scope flagged, their capital and how many are Critical / High."""
    sql, params = serving._scope_sql(scope)
    out = {}
    for n, (cond, _) in serving.EXT_FACTORS.items():
        out[n] = serving._one(s, f"""SELECT count(*) AS n, coalesce(sum(c.anticipated_cost_cr), 0) AS capital_cr,
                count(*) FILTER (WHERE c.tier = 'Critical') AS n_critical,
                count(*) FILTER (WHERE c.tier = 'High') AS n_high
            FROM cur c WHERE {cond} AND c.project_key IN (SELECT project_key FROM cur WHERE {sql})""", params)
    return out


@serving.cached
def _chat_factor_rows(s, scope, factor, state_, limit):
    """Current projects in scope flagged for a factor with no list flag (utility shifting, inter-agency)."""
    sql, params = serving._scope_sql(scope)
    cond = serving.EXT_FACTORS[factor][0]
    extra, more = ("AND c.state = ?", [state_]) if state_ else ("", [])
    keys = [r["k"] for r in serving._rows(s, f"""SELECT c.project_key AS k FROM cur c WHERE {cond} {extra}
        AND c.project_key IN (SELECT project_key FROM cur WHERE {sql})
        ORDER BY c.p_any_2q DESC NULLS LAST, c.project_key""", more + params)]
    return len(keys), serving.rows_for_keys(tuple(keys[:limit]))


def _external_all(viewer, factor=None, state=None, limit=5) -> ToolResult:
    counts = _chat_factor_counts(viewer.scope)
    ext = serving.external_summary(scope=viewer.scope)
    notice = ext["early_notice"]
    title = "Current projects flagged per outside factor"
    rows = [{"name": labels.FACTOR_LABELS[n], "n": c["n"], "capitalCr": round(c["capital_cr"], 1),
             "nCritical": c["n_critical"], "nHigh": c["n_high"]} for n, c in counts.items()]
    facts = {"as_of": _asof(), "factors": [{"factor": r["name"], "projects": r["n"],
                                            "capital_cr": _r(r["capitalCr"], 0), "critical": r["nCritical"],
                                            "high": r["nHigh"]} for r in rows],
             "early_notice": {"projects": notice["n_projects"], "capital_cr": _r(notice["capital_exposed_cr"], 0)},
             "note": "Report remarks are free text only through 2023, so remark-based flags describe the situation up "
                     "to 2023; unknown is not clear."}
    cards = [{"type": "stats", "title": title, "groupBy": "factor", "rows": rows}]
    sources = [_src("external", "Outside factors summary", "PAIMANA External Factors", when=serving.state()["asof"])]
    keys = []
    if factor:
        if factor in FACTOR_FLAG:
            page = _rows(viewer, flag=FACTOR_FLAG[factor], state_=state, size=limit)
            total, items = page["total"], page["items"]
        else:
            total, items = _chat_factor_rows(viewer.scope, factor, state, limit)
        label = labels.FACTOR_LABELS[factor]
        where = f" in {state}" if state else ""
        cards.insert(0, {"type": "projects", "title": f"Projects flagged for {label.lower()}{where}", "total": total,
                         "items": [_row_item(r) for r in items]})
        facts["flagged_projects"] = {"factor": label, "state": state, "total": total,
                                     "riskiest": [_row_fact(r) for r in items[:TOP_FACTS]]}
        keys = [r["key"] for r in items]
        if _official(viewer) and items:
            dim = serving.EXT_FACTORS[factor][1]
            ev = {r["project_key"]: r["evidence"] for r in serving._rows(
                serving.state(), f"""SELECT project_key, evidence FROM rp WHERE dimension = ? AND state = 'flagged'
                AND project_key IN ({','.join('?' * len(keys))})""", [dim, *keys])} if dim else {}
            for f in facts["flagged_projects"]["riskiest"]:
                if ev.get(f["key"]):
                    f["evidence"] = quote(ev[f["key"]], 200)
        summary = (f"{_plural(total, 'current project')} flagged for {label.lower()}{where}"
                   + (f"; the riskiest is {_short(items[0]['name'], 10)} ({items[0]['key']})" if items else "") + ".")
    else:
        top = max(rows, key=lambda r: r["n"])
        summary = (f"The most common outside factor is {top['name'].lower()} ({_plural(top['n'], 'project')}); "
                   f"{_plural(notice['n_projects'], 'project')} have an early notice.")
    return ToolResult(summary=summary, facts=_compact(facts), cards=cards, sources=sources, keys=keys)


@tool("external_factors", "Checking outside factors",
      "outside factors (land, forest, court cases, contractor ...) of one project (key), or counts across the "
      "portfolio and the projects flagged for one factor",
      ExternalArgs, public=True)
def external_factors(viewer, key=None, factor=None, state=None, limit=5) -> ToolResult:
    if key is not None:
        k = _resolve(viewer, key)
        return _not_found(key) if k is None else _external_one(viewer, k)
    return _external_all(viewer, factor, state, limit)


@tool("search_knowledge", "Searching help and data",
      "search PAIMANA's help pages, glossary, docs and the text of project records for a question (q)",
      KnowledgeArgs, public=True)
def search_knowledge(viewer, q, k=5) -> ToolResult:
    hits = rag.search(q, viewer, k=k)
    sources, passages = [], []
    for h in hits:
        sources.append(_src(h["kind"], quote(h["title"], 160) or h["kind"], quote(h["source"], 100) or "PAIMANA",
                            h["url"], h["date"], h["project_key"]))
        text = h["text"][:PASSAGE_CHARS] if h["trusted"] else quote(h["text"], 500)
        passages.append(_compact({"cite": len(sources), "title": quote(h["title"], 160), "text": quote(text, 800),
                                  "date": h["date"]}))
    if not hits:
        return ToolResult(summary="Nothing in PAIMANA's help or data matches that.", facts={"passages": []},
                          found=False)
    # the deterministic answer quotes the best hit when it is PAIMANA's own help or glossary text
    first = passages[0].get("text") if hits[0]["kind"] in ("help", "glossary", "doc") else None
    excerpt = " ".join(re.split(r"(?<=[.!?])\s+", first)[:2])[:400] if first else None
    summary = (f"From PAIMANA's {hits[0]['kind']} pages: {excerpt}" if excerpt else
               f"{_plural(len(hits), 'passage')} found in PAIMANA's help and data.")
    return ToolResult(summary=summary, facts={"found": len(hits), "passages": passages}, sources=sources,
                      keys=list(dict.fromkeys(h["project_key"] for h in hits if h["project_key"])))


# ------------------------------------------------------------------ officials only

def _value(v):
    return _r(v, 2) if isinstance(v, float) else v


@tool("explain_prediction", "Reading the risk drivers",
      "why a project has its tier: the five inputs that moved its score most (plain labels) and its flagged "
      "checks with their evidence (key)", KeyArgs, public=False, feature="insights")
def explain_prediction(viewer, key) -> ToolResult:
    k = _resolve(viewer, key)
    if k is None:
        return _not_found(key)
    d, row = _bundle(viewer, k)
    name, sc = _name(d, row), d["scores"] or {}
    shap = sc.get("shap_top5") or []
    flagged = [r for r in d["risk_profile"] if r["state"] == "flagged"]
    card = {"type": "explain", "key": k, "name": name, "tier": sc.get("tier"),
            "drivers": [{"feature": x["feature"], "label": labels.feature_label(x["feature"]), "value": x["value"],
                         "contribution": x["contribution"]} for x in shap],
            "flagged": [{"dimension": r["dimension"], "label": labels.dimension_label(r["dimension"]),
                         "evidence": r["evidence"]} for r in flagged]}
    facts = _compact({
        "key": k, "name": _short(name, 25), "tier": sc.get("tier"), "slip_chance_2q_pct": _pct(sc.get("p_any_2q")),
        "horizon_quarters": HORIZONS,
        "drivers": [{"input": labels.feature_label(x["feature"]), "value": _value(x["value"]),
                     "effect": labels.direction(x["contribution"])} for x in shap],
        "flagged_checks": [_compact({"check": labels.dimension_label(r["dimension"]),
                                     "meaning": serving.PLAIN_RISK.get(r["dimension"]),
                                     "evidence": quote(r["evidence"], 200)}) for r in flagged],
        "note": ("The drivers are the five inputs that moved this project's score most; they explain its rank "
                 "among projects, not the cause of a delay." if shap else
                 "No drivers: the project has no date-based score (Watch tier or not scored).")})
    up = [labels.feature_label(x["feature"]) for x in shap if x["contribution"] > 0][:3]
    summary = (f"{_short(name, 12)} ({k}) {_tier_words(sc.get('tier'), _pct(sc.get('p_any_2q')))}"
               + (f"; the inputs raising its risk most: {', '.join(up)}" if up else "")
               + (f"; flagged checks: {', '.join(labels.dimension_label(r['dimension']) for r in flagged)}"
                  if flagged else "") + ".")
    asof = d["provenance"]["asof"]
    return ToolResult(summary=summary, facts=facts, cards=[card], keys=[k], sources=[
        _src("model", f"Risk drivers of {_short(name, 12)}", "PAIMANA slip model (SHAP)", when=asof, key=k),
        _src("checklist", f"Risk checklist of {_short(name, 12)}", "PAIMANA risk checklist", when=asof, key=k)])


def _cached_opinion(key: str) -> dict | None:
    """llm.second_opinion.cached(key) when that module exists (unit B4), else None; never generates."""
    try:
        module = importlib.import_module("llm.second_opinion")
    except ImportError:
        return None
    fn = getattr(module, "cached", None)
    return fn(key) if fn else None


def _opinion_fields(o: dict) -> dict:
    """The opinion's own fields whether cached() returns them flat, under 'opinion' or as stored 'json'."""
    inner = o.get("opinion") if isinstance(o.get("opinion"), dict) else o.get("json")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except ValueError:
            inner = None
    return {**o, **(inner if isinstance(inner, dict) else {})}


@tool("second_opinion", "Reading the AI second opinion",
      "the cached AI second opinion on one project's evidence, if one was generated (key); never generates one",
      KeyArgs, public=False, feature="insights")
def second_opinion(viewer, key) -> ToolResult:
    k = _resolve(viewer, key)
    if k is None:
        return _not_found(key)
    d, row = _bundle(viewer, k)
    name = _name(d, row)
    o = _cached_opinion(k)
    if not o or o.get("status") in ("none", "not_scored", "rejected", "llm_unavailable"):
        return ToolResult(summary=f"No AI second opinion yet for {_short(name, 12)} ({k}).",
                          facts={"key": k, "name": _short(name, 25), "second_opinion": "none generated yet"},
                          sources=[_project_source(d, row)], keys=[k], found=False)
    o = _opinion_fields(o)
    when = o.get("generated_at") or o.get("generatedAt")
    card = {"type": "opinion", "key": k, "concern": o.get("concern"), "headline": o.get("headline"),
            "narrative": o.get("narrative"), "generatedAt": when}
    narrative = re.sub(r"\s*\[E\d+(?:\s*,\s*E?\d+)*\]", "", o.get("narrative") or "")
    facts = _compact({"key": k, "name": _short(name, 25), "concern": o.get("concern"),
                      "headline": quote(o.get("headline"), 160), "narrative": quote(narrative, 700),
                      "compared_with_the_model": o.get("vs_model"), "generated": _month(when),
                      "note": "An AI reading of the evidence; it never changes the tier."})
    return ToolResult(summary=f"AI second opinion on {_short(name, 12)} ({k}): {o.get('concern') or 'unknown'}.",
                      facts=facts, cards=[card], keys=[k],
                      sources=[_src("opinion", f"AI second opinion on {_short(name, 12)}", "PAIMANA second opinion",
                                    when=when, key=k)])


@serving.cached
def _chat_agency_tiers(s, scope):
    """Canonical agency -> (Critical, High) current projects in scope."""
    sql, params = serving._scope_sql(scope)
    return {r["agency"]: (r["n_critical"], r["n_high"]) for r in serving._rows(s, f"""
        SELECT a.canonical AS agency, count(*) FILTER (WHERE c.tier = 'Critical') AS n_critical,
               count(*) FILTER (WHERE c.tier = 'High') AS n_high
        FROM cur c JOIN amap a ON a.raw = c.agency
        WHERE c.project_key IN (SELECT project_key FROM cur WHERE {sql}) GROUP BY 1""", params)}


def _agency_fact(p: dict) -> dict:
    return _compact({"agency": p["agency"], "ministry": p["ministry"], "sector": p["sector"],
                     "projects_with_history": p["n_projects"], "open_projects": p["n_open"],
                     "capital_cr": _r(p["capital_cr"], 0), "schedule_overrun_pct": _pct(p["schedule_bias"]),
                     "cost_overrun_pct": _pct(p["cost_bias"]),
                     "sector_schedule_overrun_pct": _pct(p["sector_schedule_bias"]),
                     "recent_trend_pct": _pct(p["trend"]), "shrunk_toward_sector": p["shrunk"] or None,
                     "hidden_small_sample": p["hidden"] or None})


@tool("agency_scorecard", "Reading the agency matrix",
      "implementing agencies' track record: how far their projects run over planned time and cost (agency?)",
      AgencyArgs, public=False, feature="agencies")
def agency_scorecard(viewer, agency=None, sort="capital", limit=8) -> ToolResult:
    m = serving.agency_matrix(scope=viewer.scope)
    pts = m["points"]
    if agency is None and viewer.scope and viewer.scope[0] == "agency" and sort == "capital":
        agency = viewer.scope[1]
    if agency:
        chosen = [p for p in pts if p["agency"] == agency]
    else:  # the matrix comes largest capital first; an overrun order ranks the shown (n >= 5) agencies by it
        col = {"schedule_overrun": "schedule_bias", "cost_overrun": "cost_bias"}.get(sort)
        shown = [p for p in pts if not p["hidden"] and (col is None or p[col] is not None)]
        chosen = (sorted(shown, key=lambda p: -p[col]) if col else shown)[:limit]
    if not chosen:
        return ToolResult(summary=f"No agency record for {quote(agency, 60)}.", facts={"agency": quote(agency, 60)},
                          found=False)
    tiers = _chat_agency_tiers(viewer.scope)
    rows = [{"name": p["agency"], "n": p["n_open"], "capitalCr": p["capital_cr"],
             "nCritical": tiers.get(p["agency"], (0, 0))[0], "nHigh": tiers.get(p["agency"], (0, 0))[1]}
            for p in chosen]
    facts = {"shown": len(chosen), "agencies": [_agency_fact(p) | {"critical_open": r["nCritical"],
                                                                    "high_open": r["nHigh"]}
                                                for p, r in zip(chosen, rows)],
             "note": "Schedule overrun: how much longer than planned the agency's median project runs (0% is on "
                     "time); cost overrun likewise; agencies with few projects are shrunk toward their sector."}
    p = chosen[0]
    if agency:
        summary = f"{p['agency']}: {_plural(p['n_open'], 'open project')}" + "".join(
            f", {what} {_pct(p[col])}%" for col, what in (("schedule_bias", "median schedule overrun"),
                                                          ("cost_bias", "cost overrun")) if p[col] is not None) + "."
    else:
        order = {"capital": "largest agency", "schedule_overrun": "agency", "cost_overrun": "agency"}[sort]
        by = {"capital": "by capital", "schedule_overrun": "with the largest schedule overrun",
              "cost_overrun": "with the largest cost overrun"}[sort]
        summary = (f"The {_plural(len(chosen), order)} {by}, led by {p['agency']} with "
                   f"{_plural(p['n_open'], 'open project')}.")
    title = f"Agency {p['agency']}" if agency else f"Agencies {by}"
    return ToolResult(summary=summary, facts=facts,
                      cards=[{"type": "stats", "title": title, "groupBy": "agency", "rows": rows}],
                      sources=[_src("agency", "Agency performance matrix", "PAIMANA agency matrix", when=m["asof"])])


@tool("bottlenecks", "Reading bottlenecks",
      "clusters of current projects held up by the same open issue and place: category (land|forest_env|...)?, "
      "state?", BottleneckArgs, public=False, feature="bottlenecks")
def bottlenecks(viewer, category=None, state=None, limit=5) -> ToolResult:
    cat = category and BOTTLENECK_CATEGORY.get(category.lower(), category.lower())
    page = serving.bottlenecks(cat, state, None, None, 1, limit, scope=viewer.scope)
    items = page["items"]
    rows, facts_items, sources = [], [], []
    for b in items:
        members = (serving.bottleneck(b["bottleneck_id"], 1, 100, scope=viewer.scope) or {}).get("members", [])
        what = rag.CATEGORY_WORDS.get(b["category"], b["category"])
        name = f"{what}: {b['authority'] or b['state'] or 'several places'}"
        rows.append({"name": name, "n": b["n_projects"], "capitalCr": b["capital_exposed_cr"],
                     "nCritical": sum(x["tier"] == "Critical" for x in members),
                     "nHigh": sum(x["tier"] == "High" for x in members)})
        sources.append(_src("bottleneck", quote(b["headline"], 120), "PAIMANA bottlenecks (report remarks and news)",
                            when=b["last_seen"]))
        facts_items.append(_compact({"cite": len(sources), "issue": what, "authority": quote(b["authority"], 80),
                                     "state": b["state"], "projects": b["n_projects"],
                                     "capital_cr": _r(b["capital_exposed_cr"], 0),
                                     "critical_or_high": b["n_critical_high"],
                                     "since": _month(b["earliest_first_seen"]),
                                     "last_seen": _month(b["last_seen"]),
                                     "evidence": [quote(e, 200) for e in b["evidence"][:2]]}))
    what = ", ".join(x for x in (cat and rag.CATEGORY_WORDS.get(cat, cat), state) if x)
    facts = _compact({"filters": what or None, "clusters_total": page["total"], "bottlenecks": facts_items,
                      "note": quote(page["summary"].get("note"), 300)})
    if not items:
        return ToolResult(summary=f"No bottleneck found{' (' + what + ')' if what else ''}.", facts=facts,
                          found=False)
    b = items[0]
    return ToolResult(summary=f"{_plural(page['total'], 'bottleneck')}{' (' + what + ')' if what else ''}; the largest "
                              f"blocks {_plural(b['n_projects'], 'project')} worth Rs "
                              f"{_r(b['capital_exposed_cr'], 0):,} crore.",
                      facts=facts, sources=sources,
                      cards=[{"type": "stats", "title": "Bottlenecks by capital exposed", "groupBy": "bottleneck",
                              "rows": rows}],
                      keys=[m["key"] for b in items for m in b["top_members"]])
