"""Search index of the assistant (docs/AI_ASSISTANT.md): every text the chat may quote, cut into chunks that carry a
visibility and a project, ranked by keywords and by meaning.

A chunk is {id, kind, project_key, visibility, title, text, source, url, date}; official_source, when set, replaces
source for signed-in officials, and mentions lists the other projects its text names (by PRJ key, and in a chunk bound
to no project also by a linked PARIVESH proposal number): a scoped official reads a chunk only when its project and
every project it mentions are in scope. Outside text (remarks, headlines, research notes, register and portal lines)
goes through _quote before it is spliced into a chunk: one line, no tags, code fences or double quotes, at most
QUOTE_MAX characters; hits of the kinds that carry it have trusted False. Kinds, and who may read them:
  help      docs/HELP.md, by section ............................................................. public
  doc       the maintained docs in DOCS (not docs/PROJECT_DOCUMENTATION.md, which is stale, nor the mock-data notes)
            .................................................................................... official
  project   one card per current project from the public project page's facts only: name, ministry, agency, sector,
            state, cost, progress, dates, tier, the chance of a slip as a percent, top risks in plain words, flags
            (no drivers, intervals, rank or evidence lines) ...................................... public
  event     one per report-remark event with its quote; officials also get its document and page ......... public
  research  web research facts (gold/research_facts.parquet from the sweep, the agent's SQLite research_facts,
            one per project and URL) and the latest status per project (gold/research_projects.parquet) ... public
  news      scout headlines linked to a project (the newest NEWS_PER_PROJECT per project): headline, publisher,
            date, category, never article text ..................................................... official
  external  land-register and forest-rulebook evidence per current project .......................... public;
            PARIVESH proposal evidence .............................................................. official
  glossary  tiers, the risk checks in plain words, delay categories, model feature labels, caveats ...... public;
            score field names and method notes .................................................... official
Markdown is cut at its headings; a section over MAX_WORDS is split at paragraphs (then lines, then words), and
consecutive pieces are merged while the chunk has fewer than MIN_WORDS, so chunks run about MIN_WORDS..MAX_WORDS.
Event, research, news and external chunks name their project as 'name (key, sector, state)', so a question about a
state or a sector finds them.

Ranking: TF-IDF (word 1-2 grams, sublinear tf, English stop words) over title and text; the same over the titles of
project cards, help, docs and glossary alone (TITLE_RANK: a name finds its project card before the shorter chunks
that also name it); and nomic embeddings ('search_document: ' before a chunk, 'search_query: ' before a question).
Each ranks only the chunks the viewer may read: visibility (the public reads public chunks), scope (Viewer.keys, for
the chunk's project and the projects it mentions), kinds and project are filtered before ranking, so a hidden chunk never takes a place. The
rankings (top POOL each) are fused by reciprocal rank, score = sum of 1 / (RRF_K + rank). Without embeddings (still
computing, LM Studio down or its embedding model not loaded, or RAG_EMBED=0) TF-IDF ranks alone: search() never
raises for an LLM outage.

Artifacts in dataset/rag/ (gitignored): chunks.parquet; embeddings.npz, the float16 vectors of the embedded chunks
with the content hash of each, so a vector is only ever paired with the chunk text it was computed from (the files
are replaced one by one, and the CLI and the backend may both write); meta.json with the input fingerprint: chunker
VERSION, a hash of this file and of the texts it copies from serving and the delay taxonomy (so an edit to them
rebuilds without a VERSION bump), embedding model, the served data state (its version, the external_summary.json
mtime, and its gold and model version and asof), the docs and research file mtimes, and the max signal id and link
and agent-fact counts of the app database. The data part is read from the same serving.state() the chunks are built
from, never from the files: while the report watcher pins the old version during an ingest, or a failed reload keeps
it, the files are newer than what is served, and an index built then carries the served version's fingerprint, so
it is rebuilt once the new version is served. ensure_index() serves the saved index and, when the fingerprint moved
(checked at most every CHECK_S seconds), rebuilds in a background thread: the new chunks are served on TF-IDF as soon
as they are built, then the chunks whose text changed are embedded (the rest keep their vectors, by content hash),
pausing while a chat request waits for the LLM (client.chat_active). A failed embedding run is retried after
EMBED_RETRY_S; a failed query embedding falls back to TF-IDF for QUERY_RETRY_S.
"""
import argparse
import dataclasses
import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import sys
import threading
import time
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from backend import db, serving
from llm import client
from pipeline.external import TAXONOMY

log = logging.getLogger(__name__)

ROOT, GOLD = serving.ROOT, serving.GOLD
RAG_DIR = ROOT / "dataset" / "rag"
HELP = "docs/HELP.md"
DOCS = ("README.md", "docs/ACCESS_CONTROL.md", "docs/AI_ASSISTANT.md", "docs/EXTERNAL_RESEARCH_2026-09.md",
        "docs/EXTERNAL_DATA_CROSSCHECK.md", "docs/IMPLEMENTATION_GUIDE_v2.md", "dataset/raw/external/README.md")
FEATURE_LABELS = "frontend/src/lib/featureLabels.ts"
RESEARCH_FACTS, RESEARCH_PROJECTS = GOLD / "research_facts.parquet", GOLD / "research_projects.parquet"
KINDS = ("help", "doc", "project", "event", "research", "news", "external", "glossary")
COLUMNS = ["id", "kind", "project_key", "visibility", "title", "text", "source", "official_source", "url", "date",
           "mentions"]
VERSION = 2                     # the chunks' schema (2: mentions); a change rebuilds every index, vectors are reused
PRJ_KEY = re.compile(r"\bPRJ-\d{6}\b")
PROPOSAL_NO = re.compile(r"\bFP/[A-Z]{2}/[A-Z0-9]+/\d+/\d{4}\b")
MIN_WORDS, MAX_WORDS = 180, 350
RRF_K, POOL = 60, 50
DOC_PREFIX, QUERY_PREFIX = "search_document: ", "search_query: "
EMBED_BATCH = 32
CHECK_S = 60.0                  # fingerprint checks at most this often
EMBED_RETRY_S = 300.0           # a failed build or embedding run waits this long before the next try
QUERY_RETRY_S = 30.0            # a failed query embedding: keywords only for this long
WAIT_S = 15.0                   # a search with no index yet waits this long for the first one
CHAT_PAUSE_S = 600.0            # the embedding run waits at most this long for a chat request to finish
DENSE_MIN_SHARE = 0.9           # rank by meaning only once this share of the chunks has a vector
TITLE_RANK = True               # a third ranking: TF-IDF over the titles alone (a name finds its project card)
TITLE_KINDS = {"project", "help", "doc", "glossary"}
EMBED = os.environ.get("RAG_EMBED", "1") != "0"  # 0: keywords only, the embedding model is never called
NEWS_PER_PROJECT = 30           # the newest linked headlines per project are indexed; older ones stay in the database

CATEGORY_WORDS = {
    "land": "land acquisition", "forest_env": "forest or environment clearance", "litigation": "court case or dispute",
    "contractor": "contractor", "funding": "funding", "funds": "funding", "utility_shifting": "utility shifting",
    "inter_agency": "approval from another agency", "law_order": "law and order or local resistance",
    "weather": "weather or force majeure", "natural_event": "weather or natural event",
    "approvals_other": "other approvals", "design_scope": "design or scope change", "progress": "progress",
    "other": "other"}
SUBTYPE_WORDS = {"rr": "resettlement and rehabilitation", "row": "right of way", "ngt": "National Green Tribunal",
                 "moefcc": "environment ministry (MoEFCC)", "crz": "coastal regulation zone",
                 "gad": "general arrangement drawing", "noc": "no-objection certificate",
                 "lwe": "left-wing extremism area"}
FLAG_WORDS = {"land": "land acquisition", "forest": "forest clearance", "litigation": "court case",
              "contractor": "contractor problems",
              "early_notice": "early notice (an outside factor is flagged before the reports show a slip)"}
LA_WORDS = {"flagged": "flagged: the Bhoomi Rashi register shows a hard acquisition on its stretch",
            "clear": "clear on the Bhoomi Rashi register", "possible": "a possible match only, not rated"}
SEVERITY_WORDS = {1: "a mention", 2: "a negative development",
                  3: "a severe development (court order, termination, ban)"}
# what each risk check tests, in plain words (ml/risk_profile.py build_rows)
CHECK_RULES = {
    "schedule_slip": "the chance of a completion-date push within 2 quarters is in the top 20% of current projects",
    "cost_escalation": "the chance of a cost revision within 2 quarters is in the top 20% of current projects",
    "execution_stagnation": "progress has not moved for 2 or more quarters after 30% of the planned time and is "
                            "below 95%, or progress is far behind the time used (schedule performance index below "
                            "0.1 after 30% of the planned time)",
    "expenditure_lag": "the share of cost spent runs more than 25 points ahead of, or 15 points behind, the share "
                       "of work done",
    "repeated_revisions": "the cost (up 5% or more) or the completion date (3 months or more) has been revised at "
                          "least twice",
    "sector_headwind": "the sector's output is below 95% of its target or falling over 4 quarters",
    "agency_optimism": "the agency's dated projects run more than 25% over their planned time (at least 5 projects)",
    "land_acquisition": "an open land issue in the report remarks, or a hard acquisition on its highway stretch in "
                        "the Bhoomi Rashi register",
    "forest_clearance": "an open forest or environment issue in the remarks, a PARIVESH proposal past its rule "
                        "limit, or a linear project with a known forest area on a hard clearance route",
    "litigation": "an open court case or dispute in the report remarks",
    "contractor_stress": "an open contractor issue (termination, re-tender, insolvency, poor performance) in the "
                         "report remarks",
    "data_staleness": "more than 3 months between the latest report and the one before, or a data-quality score "
                      "below 0.7",
    "external_composite": "the combined land and forest score is 0.6 or more, rated only where land records are "
                          "linked",
}

_index = None                   # the Index served now (module state; ensure_index)
_ready = threading.Event()      # set once an index is served
_building = threading.Event()   # a refresh was started and has not finished
_build_lock = threading.Lock()
_checked_at = -1e9
_build_failed_at = -1e9
_embed_failed_at = -1e9
_query_failed_at = -1e9


# ------------------------------------------------------------------ small helpers

def _iso(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return None if pd.isna(v) else v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _month(v) -> str | None:
    """'March 2027' for a date, None for a missing one."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or pd.isna(v):
        return None
    return f"{pd.Timestamp(v):%B %Y}"


def _num(v, nd=1) -> str | None:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return f"{float(v):,.{nd}f}"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _short(name: str | None, n: int = 20) -> str | None:
    """A project name cut to n words (some names are a whole scope of work) for the chunks that only cite it."""
    w = (name or "").split()
    return " ".join(w[:n]) + (" ..." if len(w) > n else "") if w else name


def _a(word: str) -> str:
    return ("an " if word[:1].lower() in "aeiou" else "a ") + word


def _words(s: str) -> int:
    return len(s.split())


def _chunk(id_, kind, visibility, title, text, source, *, project_key=None, official_source=None, url=None,
           date_=None) -> dict:
    return {"id": id_, "kind": kind, "project_key": project_key, "visibility": visibility, "title": title[:200],
            "text": text.strip(), "source": source, "official_source": official_source, "url": url,
            "date": _iso(date_), "mentions": None}


QUOTE_MAX = 500                 # characters of one outside text (the longest remark, headline or portal line is less)
TRUSTED_KINDS = frozenset({"help", "doc", "glossary", "project"})  # PAIMANA's own words; the others quote outside text
_TAG = re.compile(r"<\|[^<>]*\|>|</?[A-Za-z][^<>]*>")
_SPACE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")  # \s covers U+2028, U+2029 and U+0085 too


def _quote(s, n: int = QUOTE_MAX) -> str | None:
    """Outside text (a remark, a headline, a research note, a register or portal line) made safe to splice into
    PAIMANA's own sentences: no <tags> or <|special tokens|>, no backticks (no code fences), double quotes turned
    single (the chunk quotes it in double quotes), every run of whitespace, line or paragraph separator and control
    characters one space, at most n characters. The words stay: the chat still fences such hits as quoted data
    (Hit trusted False)."""
    if s is None:
        return None
    s = _TAG.sub(" ", str(s)).replace("`", "'").replace('"', "'")
    s = _SPACE.sub(" ", s).strip()
    return s if len(s) <= n else s[:n - 3].rstrip() + "..."


def _sentences(*parts) -> str:
    return " ".join(p for p in parts if p)


def _ro_db() -> sqlite3.Connection | None:
    """A read-only connection to the app database, None when it does not exist (never creates it)."""
    p = db.path()
    if not p.exists():
        return None
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ------------------------------------------------------------------ markdown

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _clean_md(s: str) -> str:
    """Links to their text, no emphasis marks, backticks, table rules or HTML comments."""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = LINK.sub(r"\1", s)
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*$", "", s, flags=re.M)
    s = re.sub(r"[ \t]+", " ", s)
    # hard-wrapped lines of one paragraph or list item become one line; lists, tables and headings keep theirs
    s = re.sub(r"(?<=\S)[ \t]*\n[ \t]*(?![-*+] |\d+[.)] |\||#)(?=\S)", " ", s)
    return re.sub(r"\n\s*\n(\s*\n)+", "\n\n", s).strip()


def _sections(md: str) -> tuple[str | None, list[tuple[str, str]]]:
    """(the first H1, [(heading path below it, section text starting with its heading)]); a heading with nothing
    under it is no section of its own (it stays in the path of its sub-headings); '#' lines in code fences are
    text."""
    title, out, path, body = None, [], [], []
    fence = False

    def flush():
        text = "\n".join(body).strip()
        if text:
            head = path[-1][1] if path else None
            out.append((" > ".join(t for _, t in path), f"{head}\n\n{text}" if head else text))
        body.clear()

    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if not m:
            body.append(line)
            continue
        flush()
        level, text = len(m[1]), _clean_md(m[2])
        if level == 1 and title is None:
            title, path = text, []
            continue
        path = [(lv, t) for lv, t in path if lv < level] + [(level, text)]
    flush()
    return title, out


def _split_long(text: str, max_words: int) -> list[str]:
    """text cut at paragraphs, then lines, then words, into pieces of at most max_words words."""
    if _words(text) <= max_words:
        return [text]
    for sep in ("\n\n", "\n"):
        parts = [p for p in text.split(sep) if p.strip()]
        if len(parts) > 1:
            out, cur, n = [], [], 0
            for part in parts:
                for piece in _split_long(part, max_words):
                    k = _words(piece)
                    if cur and n + k > max_words:
                        out.append(sep.join(cur))
                        cur, n = [], 0
                    cur.append(piece)
                    n += k
            if cur:
                out.append(sep.join(cur))
            return out
    w = text.split()
    size = math.ceil(len(w) / math.ceil(len(w) / max_words))  # equal windows, not full ones and a stub
    return [" ".join(w[i:i + size]) for i in range(0, len(w), size)]


def md_chunks(md: str, min_words: int = MIN_WORDS, max_words: int = MAX_WORDS) -> tuple[str | None,
                                                                                        list[tuple[str, str]]]:
    """(document title, [(chunk title, chunk text)]): sections cut at headings, long ones split, consecutive small
    pieces merged while the chunk has fewer than min_words and stays within max_words."""
    title, sections = _sections(md)
    pieces = [(t, p) for t, body in sections for p in _split_long(_clean_md(body), max_words)]
    out, titles, cur, n = [], [], [], 0

    def flush():
        out.append(("; ".join(titles)[:160], "\n\n".join(cur)))

    for t, p in pieces:
        k = _words(p)
        if cur and (n >= min_words or n + k > max_words):
            flush()
            titles, cur, n = [], [], 0
        cur.append(p)
        n += k
        if t and t not in titles:
            titles.append(t)
    if cur:
        flush()
    return title, out


# ------------------------------------------------------------------ chunk builders

def help_chunks() -> list[dict]:
    p = ROOT / HELP
    if not p.exists():
        return []
    title, parts = md_chunks(p.read_text(encoding="utf-8"))
    return [_chunk(f"help:{i}", "help", "public", f"Help: {t}" if t else (title or "PAIMANA help"), text,
                   "PAIMANA help") for i, (t, text) in enumerate(parts)]


def doc_chunks() -> list[dict]:
    out = []
    for rel in DOCS:
        p = ROOT / rel
        if not p.exists():
            continue
        title, parts = md_chunks(p.read_text(encoding="utf-8"))
        name = title or rel
        out += [_chunk(f"doc:{rel}:{i}", "doc", "official", f"{name}: {t}" if t else name, text, rel)
                for i, (t, text) in enumerate(parts)]
    return out


def project_card(r: dict, top_risks: list[str]) -> str:
    """The public facts of one current project as a few plain sentences (serving ROW_SQL columns and more)."""
    where = _sentences(r.get("sector") and _a(f"{r['sector']} project"), r.get("state") and f"in {r['state']}")
    head = f"{r['name']} ({r['key']})" + (f" is {where}" if where else "")
    head += "".join(x for x in (r.get("ministry") and f", under the {r['ministry']}",
                                r.get("agency") and f", implemented by {r['agency']}") if x) + "."
    tier = r.get("tier")
    if tier == serving.WATCH:
        tier_s = ("Risk tier: Watch (the reports give no anticipated completion date, so it is not ranked by the "
                  "chance of a slip).")
    elif tier:
        pct = r.get("p_any_2q")
        tier_s = f"Risk tier: {tier}." + (f" Chance of a schedule or cost slip within 2 quarters: {round(pct * 100)}%."
                                          if pct is not None else "")
    else:
        tier_s = "Not scored."
    stalled = "Stalled: no progress for 2 or more quarters (a badge; the tier stays by rank)." if r.get("stalled") \
        else None
    prog = _num(r.get("physical_progress_pct"))
    period = _month(r.get("obs_period"))
    prog_s = prog and f"Physical progress {prog}%" + (f" in the {period} report." if period else ".")
    costs = [f"{label} Rs {v} crore" for label, v in (
        ("original cost", _num(r.get("original_cost_cr"))), ("anticipated cost", _num(r.get("anticipated_cost_cr"))),
        ("spent so far", _num(r.get("expenditure_cr")))) if v]
    cost_s = (_cap("; ".join(costs)) + ".") if costs else "Cost not reported."
    dates = [f"{label} {v}" for label, v in (
        ("sanctioned", _month(r.get("sanction_date"))),
        ("original scheduled completion", _month(r.get("scheduled_completion"))),
        ("anticipated completion", _month(r.get("anticipated_completion")))) if v]
    date_s = (_cap("; ".join(dates)) + ".") if dates else None
    slip = r.get("slip_to_date_months")
    slip_s = None
    if slip is not None and not pd.isna(slip):
        slip_s = f"Slip so far: {round(slip)} months" + (" (ahead of the original schedule)." if slip < 0 else ".")
    risks = ("Top risks: " + " ".join(top_risks)) if top_risks else "No risk check is flagged."
    flags = [FLAG_WORDS.get(f, f) for f in (r.get("flags") or [])]
    flag_s = ("Flags: " + ", ".join(flags) + ".") if flags else None
    return _sentences(head, tier_s, stalled, prog_s, cost_s, date_s, slip_s, risks, flag_s)


def project_chunks(s: dict) -> list[dict]:
    rows = serving._rows(s, """SELECT c.project_key AS "key", c.project_name AS name, c.sector, c.state, c.agency,
            c.ministry, c.tier, c.stagnation_override AS stalled, c.p_any_2q, c.anticipated_cost_cr,
            c.original_cost_cr, c.expenditure_cr, c.physical_progress_pct, c.anticipated_completion,
            c.scheduled_completion, c.slip_to_date_months, c.obs_period, c.flags, m.sanction_date
        FROM cur c LEFT JOIN master m USING (project_key) ORDER BY c.project_key""")
    flagged = {r["k"]: set(r["dims"]) for r in serving._rows(
        s, "SELECT project_key AS k, list(dimension) AS dims FROM rp WHERE state = 'flagged' GROUP BY 1")}
    out = []
    for r in rows:
        top = [text for dim, text in serving.PLAIN_RISK.items() if dim in flagged.get(r["key"], ())][:3]
        out.append(_chunk(f"project:{r['key']}", "project", "public", r["name"] or r["key"], project_card(r, top),
                          "PAIMANA project page", project_key=r["key"], date_=s["asof"]))
    return out


def _names(s: dict) -> dict[str, tuple[str, str]]:
    """Project key -> (its name cut to 20 words, 'name (key, sector, state)'): the current row for a current
    project, else the master row. The sector and state let a place or sector question find the project's chunks."""
    names = {}
    for table in ("master", "cur"):
        for r in serving._rows(s, f"SELECT project_key AS k, project_name AS n, sector, state FROM {table}"):
            name = _short(r["n"]) or r["k"]
            names[r["k"]] = (name, f"{name} ({', '.join(x for x in (r['k'], r['sector'], r['state']) if x)})")
    return names


def _ref(names: dict, key: str) -> tuple[str, str]:
    return names.get(key) or (key, key)


def event_chunks(s: dict, names: dict) -> list[dict]:
    out = []
    for e in serving._rows(s, "SELECT * FROM events ORDER BY project_key, category, event_no"):
        key, cat = e["project_key"], e["category"]
        name, ref = _ref(names, key)
        what = CATEGORY_WORDS.get(cat, cat.replace("_", " "))
        sub = e.get("subtype")
        sub = sub and SUBTYPE_WORDS.get(sub, sub.replace("_", " "))
        if e["status"] == "open":
            state = "open at the last free-text remark" + (f" ({_month(e['remarks_last_seen'])})"
                                                           if _month(e.get("remarks_last_seen")) else "")
        else:
            state = "reported done" if e.get("resolved") else "no longer mentioned"
        area = e.get("forest_area_ha")
        text = _sentences(
            f"{ref}: {what} issue in the report remarks" + (f" ({sub})" if sub else "") + f", {state}.",
            f"First reported {_month(e['first_seen'])}, last reported {_month(e['last_seen'])} "
            f"({e['n_quarters']} {'quarter' if e['n_quarters'] == 1 else 'quarters'} with a mention).",
            e.get("authority") and f"Authority: {_quote(e['authority'])}.",
            area is not None and not pd.isna(area) and f"Forest area {area:g} ha.",
            e.get("violation") and "A violation is reported.",
            e.get("evidence") and f"Remark: \"{_quote(e['evidence'])}\"")
        doc = e.get("source_doc_id")
        out.append(_chunk(f"event:{key}:{cat}:{e['event_no']}", "event", "public",
                          f"{name}: {what} issue ({'open' if e['status'] == 'open' else 'closed'})", text,
                          "Project report remarks", project_key=key,
                          official_source=doc and f"Project report remarks, {doc} p. {e.get('source_page')}",
                          date_=e["last_seen"]))
    return out


def _research_rows() -> pd.DataFrame:
    """Research facts: the sweep's gold file and the agent's SQLite table, one per project and URL (sweep first)."""
    frames = []
    if RESEARCH_FACTS.exists():
        frames.append(pd.read_parquet(RESEARCH_FACTS).assign(origin="sweep"))
    con = _ro_db()
    if con is not None:
        with closing(con):
            if "research_facts" in _tables(con):
                frames.append(pd.read_sql_query("SELECT * FROM research_facts", con).assign(origin="agent"))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "url" in df:
        df = df.drop_duplicates(["project_key", "url"], keep="first")
    return _no_nan(df)


def _no_nan(df: pd.DataFrame) -> pd.DataFrame:
    return df.astype(object).where(df.notna(), None)


def _fact_date(r: dict) -> str | None:
    d = _iso(r.get("event_date"))
    prec = r.get("date_precision")
    return d and (d[:4] if prec == "year" else d[:7] if prec == "month" else d)


def research_chunks(names: dict) -> list[dict]:
    out = []
    df = _research_rows()
    for r in df.to_dict("records") if len(df) else []:
        key = r.get("project_key")
        if not key or not r.get("summary"):
            continue
        (name, ref), when = _ref(names, key), _fact_date(r)
        cat = CATEGORY_WORDS.get(r.get("category"), _quote(r.get("category"), 40) or "other")
        sev = r.get("severity")
        kind = ", ".join(x for x in (cat, _quote(r.get("direction"), 40),
                                     sev is not None and not pd.isna(sev) and f"severity {int(sev)} of 3",
                                     r.get("status") and f"status {_quote(r['status'], 40)}",
                                     r.get("live") in (True, 1) and "a live blocker") if x)
        pub = _iso(r.get("published_date"))
        summary, headline, source = _quote(r["summary"], 800), _quote(r.get("headline")), _quote(r.get("source"), 100)
        text = _sentences(f"{ref}, web research: {summary}",
                          f"({kind}" + (f"; event date {when})." if when else ")."),
                          source and f"Source: {source}" + (f", {pub}" if pub else "")
                          + (f": \"{headline}\"" if headline else "") + ".")
        fid = r.get("fact_id") or hashlib.sha256(f"{key}|{r.get('url')}".encode()).hexdigest()[:12]
        out.append(_chunk(f"research:{fid}", "research", "public", headline or summary[:100], text,
                          source or "web research", project_key=key, url=r.get("url"), date_=when or pub))
    if RESEARCH_PROJECTS.exists():
        for r in _no_nan(pd.read_parquet(RESEARCH_PROJECTS)).to_dict("records"):
            key, status = r.get("project_key"), r.get("latest_status")
            if key and isinstance(status, str) and status.strip():
                on, (name, ref) = _iso(r.get("researched_on")), _ref(names, key)
                out.append(_chunk(f"research:{key}:status", "research", "public", f"{name}: latest status",
                                  f"{ref}, latest status from web research"
                                  + (f" on {on}" if on else "") + f": {_quote(status, 800)}", "web research",
                                  project_key=key, date_=on))
    return out


def news_chunks(names: dict) -> list[dict]:
    con = _ro_db()
    if con is None:
        return []
    with closing(con):
        if not {"signals", "signal_projects"} <= _tables(con):
            return []
        rows = [dict(r) for r in con.execute("""SELECT id, title, source, published_at, category, severity, url,
                project_key FROM (
                SELECT s.id, s.title, s.source, s.published_at, s.category, s.severity, s.url, sp.project_key,
                    row_number() OVER (PARTITION BY sp.project_key ORDER BY s.published_at DESC, s.id DESC) AS n
                FROM signal_projects sp JOIN signals s ON s.id = sp.signal_id WHERE coalesce(s.title, '') != '')
            WHERE n <= ? ORDER BY id, project_key""", [NEWS_PER_PROJECT])]
    out = []
    for r in rows:
        title, source = _quote(r["title"]), _quote(r["source"], 100)
        if not title:
            continue
        key, day = r["project_key"], (r["published_at"] or "")[:10] or None
        sev = SEVERITY_WORDS.get(r["severity"])
        text = _sentences(f"News linked to {_ref(names, key)[1]}: \"{title}\"",
                          f"({source or 'unknown publisher'}" + (f", {day})." if day else ")."),
                          f"Category: {CATEGORY_WORDS.get(r['category'], _quote(r['category'], 40) or 'unclassified')}"
                          + (f"; {sev}." if sev else "."),
                          "Linked automatically by place names; a headline is a lead, not a confirmed fact.")
        out.append(_chunk(f"news:{r['id']}:{key}", "news", "official", title, text,
                          source or "news", project_key=key, url=r["url"], date_=day))
    return out


def external_chunks(s: dict, names: dict) -> list[dict]:
    out = []
    for r in serving._rows(s, """SELECT c.project_key AS "key", l.la_state, l.la_evidence,
            f.fc_evidence, f.fc_mentioned, f.fc_pending, co.coverage, co.ext_score_evidence
        FROM cur c LEFT JOIN land l USING (project_key) LEFT JOIN fc f USING (project_key)
            LEFT JOIN composite co USING (project_key)
        WHERE l.la_state IN ('flagged', 'clear', 'possible') OR f.fc_mentioned OR f.fc_pending
        ORDER BY c.project_key"""):
        la, (name, ref) = r["la_state"] if r["la_state"] in LA_WORDS else None, _ref(names, r["key"])
        la_ev, fc_ev, score_ev = _quote(r["la_evidence"]), _quote(r["fc_evidence"]), _quote(r["ext_score_evidence"])
        text = _sentences(
            f"{ref}, outside factors.",
            la and f"Land acquisition ({LA_WORDS[la]})" + (f": {la_ev}." if la_ev else "."),
            fc_ev and f"Forest clearance route by the rulebook: {fc_ev}.",
            r["fc_mentioned"] and "A forest clearance is mentioned in the report remarks.",
            r["fc_pending"] and "A forest clearance is reported pending.",
            r["coverage"] == "fc+la" and score_ev and f"Land and forest score: {score_ev}.")
        out.append(_chunk(f"external:{r['key']}", "external", "public", f"{name}: land and forest evidence", text,
                          "Bhoomi Rashi land register; PARIVESH rulebook", project_key=r["key"]))
    lines: dict[str, list[str]] = {}
    for r in serving._rows(s, """SELECT project_key AS k, evidence FROM fcprop WHERE evidence IS NOT NULL
                                 ORDER BY project_key, received"""):
        lines.setdefault(r["k"], []).append(r["evidence"])
    portal = {r["project_key"]: r for r in serving._rows(s, "SELECT * FROM portal ORDER BY project_key")}
    for key in sorted(set(portal) | set(lines)):
        p, (name, ref) = portal.get(key), _ref(names, key)
        head = f"{ref}, PARIVESH forest clearance proposals."
        if p:
            head += " " + _sentences(
                f"{p['n_proposals']} linked ({p['link_source']}), {p['n_open']} open, {p['n_overdue']} past the rule "
                "limit.", p.get("stage_at_asof") and f"Stage at the as-of date: {p['stage_at_asof']}"
                + (f" for {p['months_in_stage']:g} months." if p.get("months_in_stage") is not None else "."))
        items = ((p or {}).get("evidence") or "").split(" | ") + lines.get(key, [])
        items = [_quote(i) for i in items if i and not re.fullmatch(r"and \d+ more", i.strip())]
        items = [i for i in items if i]
        for i, part in enumerate(_split_long("\n".join(items), MAX_WORDS - _words(head)) if items else [""]):
            out.append(_chunk(f"parivesh:{key}:{i}", "external", "official", f"{name}: PARIVESH proposals",
                              f"{head}\n{part}".strip(), "PARIVESH forest clearance portal", project_key=key))
    return out


def _feature_labels() -> list[str]:
    p = ROOT / FEATURE_LABELS
    if not p.exists():
        return []
    return [f"{m[1]}: {m[2]}" for m in re.finditer(r"^\s*(\w+):\s*'([^']*)',?\s*$", p.read_text(encoding="utf-8"),
                                                    re.M)]


def glossary_chunks() -> list[dict]:
    tiers = (
        "Risk tiers. PAIMANA ranks every current project that has an anticipated completion date by its chance of a "
        "slip: the anticipated completion date pushed out by 3 months or more, or the anticipated cost up by 5% or "
        "more, within the next 2 quarters. Critical is the riskiest 5% of scored projects, High the next 15% "
        "(together the top 20%), Medium the next 30% and Low the remaining 50%. Tiers are relative to the current "
        "portfolio, and the chances rank projects against each other; they are not calibrated frequencies. "
        "Watch: the reports give no anticipated completion date, so there is no date-based score and the project "
        "is not ranked; Watch projects are listed by flagged risk checks, then by the chance of a cost revision, an "
        "order no backtest has checked. Stalled: a badge for no progress in 2 or more quarters after 30% of the "
        "planned time, below 95% progress; it does not change the tier, because stalled projects slipped no more "
        "often in the backtest. Other estimates on the project page: the chance of a date push and of a cost "
        "revision within 2 quarters, the chance of either within 4 quarters, and the likely slip in months. Early "
        "notice: a flagged outside factor (land, forest, court case, contractor, utility shifting, another "
        "agency's approval) on a project whose reports show no slip so far or whose tier is Low or Medium.")
    checks = "Risk checks. Each is flagged, clear or unknown; unknown is never clear. " + " ".join(
        f"{_cap(dim.replace('_', ' '))}: flagged when {rule}. In plain words: \"{serving.PLAIN_RISK[dim]}\""
        for dim, rule in CHECK_RULES.items() if dim in serving.PLAIN_RISK)
    cats = "Delay categories read from the report remarks. " + " ".join(
        f"{CATEGORY_WORDS.get(c, c)} ({c}): " + ", ".join(SUBTYPE_WORDS.get(t, t.replace("_", " ")) for t in subs)
        + "." for c, subs in TAXONOMY.items())
    feats = _feature_labels()
    public = [("tiers", "Glossary: risk tiers, Watch, Stalled, early notice", tiers),
              ("checks", "Glossary: risk checks", checks),
              ("categories", "Glossary: delay categories", cats),
              ("caveats", "Glossary: caveats of the data and the model", "Caveats. " + " ".join(serving.CAVEATS))]
    if feats:
        public.append(("features", "Glossary: model features in plain words",
                       "Model features (the inputs of the slip model) and the labels an officer reads. Open <category> "
                       "issue in remarks and <category> issue ever reported come from the report remarks. "
                       + "; ".join(feats) + "."))
    official = [("scores", "Glossary: score fields",
                 "Score fields. p_any_2q: chance of a schedule or cost slip within 2 quarters (tiers rank on it). "
                 "p_date_push_2q: chance of a completion-date push of 3 months or more within 2 quarters. "
                 "p_cost_rev_2q: chance of a cost revision of 5% or more within 2 quarters. p_any_4q: chance of "
                 "either within 4 quarters. months_p05, months_p50, months_p95: 5th, 50th and 95th percentile of the "
                 "predicted slip in months over 2 quarters; cost_pct_*: the same for the cost change in percent. "
                 "tier_rank_pct: rank share among scored projects. shap_top5: the five features that moved the "
                 "p_any_2q score most for this project (SHAP contributions in log-odds)."),
                ("methods", "Glossary: method notes", " ".join([serving.BAND_METHOD, serving.AGENCY_METHOD,
                                                                serving.LIVE_NOTE]))]
    out = []
    for vis, items in (("public", public), ("official", official)):
        for slug, title, text in items:
            for i, part in enumerate(_split_long(text, MAX_WORDS)):
                out.append(_chunk(f"glossary:{slug}:{i}", "glossary", vis, title, part, "PAIMANA glossary"))
    return out


def _proposal_keys(s: dict) -> dict[str, set[str]]:
    """PARIVESH proposal number -> the projects it is linked to (the remark-named proposals and the portal links)."""
    out: dict[str, set[str]] = {}
    for r in serving._rows(s, "SELECT project_key AS k, proposal_no AS p FROM fcprop WHERE proposal_no IS NOT NULL"):
        out.setdefault(r["p"].strip(), set()).add(r["k"])
    for r in serving._rows(s, "SELECT project_key AS k, proposals AS ps FROM portal WHERE proposals IS NOT NULL"):
        for p in r["ps"].split(";"):
            if p.strip():
                out.setdefault(p.strip(), set()).add(r["k"])
    return out


def bind_mentions(chunks: list[dict], proposals: dict[str, set[str]]) -> None:
    """Set each chunk's mentions: the projects other than its own that its title or text names by PRJ key and, in a
    chunk bound to no project (a doc, help or glossary text), by a linked PARIVESH proposal number; space-separated,
    None when there are none. The docs name projects (docs/EXTERNAL_DATA_CROSSCHECK.md gives the PARIVESH status of
    PRJ-001354): a scoped official must not read that about a project outside the scope."""
    for c in chunks:
        text = f"{c['title']}\n{c['text']}"
        named = set(PRJ_KEY.findall(text))
        if not c["project_key"]:
            named |= {k for p in PROPOSAL_NO.findall(text) for k in proposals.get(p, ())}
        named.discard(c["project_key"])
        c["mentions"] = " ".join(sorted(named)) or None


def build_chunks(s: dict | None = None) -> list[dict]:
    """Every chunk of the current inputs (module docstring), ids unique; s is the served data state (serving.state()
    by default)."""
    s = serving.state() if s is None else s
    names = _names(s)
    out = (help_chunks() + doc_chunks() + project_chunks(s) + event_chunks(s, names) + research_chunks(names)
           + news_chunks(names) + external_chunks(s, names) + glossary_chunks())
    out = [c for c in out if c["text"]]
    dup = [k for k, n in Counter(c["id"] for c in out).items() if n > 1]
    if dup:
        raise ValueError(f"duplicate chunk ids: {dup[:5]}")
    bind_mentions(out, _proposal_keys(s))
    return out


# ------------------------------------------------------------------ fingerprint

def _mtime(p: Path) -> int | None:
    try:
        return p.stat().st_mtime_ns
    except OSError:
        return None


def _app_marks() -> dict:
    try:
        con = _ro_db()
        if con is None:
            return {}
        with closing(con):
            t, out = _tables(con), {}
            if "signals" in t:
                out["signals"] = con.execute("SELECT max(id) FROM signals").fetchone()[0]
            if "signal_projects" in t:
                out["links"] = con.execute("SELECT count(*) FROM signal_projects").fetchone()[0]
            if "research_facts" in t:
                out["research"] = list(con.execute("SELECT count(*), max(rowid) FROM research_facts").fetchone())
            return out
    except sqlite3.Error as e:
        return {"error": str(e)}


def _code_mark() -> str:
    """Hash of the chunker's code (this file: CHECK_RULES, the word tables, the glossary text) and of the texts it
    copies from elsewhere (serving's plain risks, caveats and method notes, the delay taxonomy)."""
    texts = json.dumps([serving.PLAIN_RISK, serving.CAVEATS, serving.BAND_METHOD, serving.AGENCY_METHOD,
                        serving.LIVE_NOTE, serving.WATCH, TAXONOMY], sort_keys=True, default=str)
    return hashlib.sha256(Path(__file__).read_bytes() + texts.encode()).hexdigest()[:16]


def fingerprint(s: dict | None = None) -> str:
    """Hash of everything the chunks are built from (module docstring); a change means the index is stale. The data
    part comes from s, the served data state (serving.state() by default) that build_chunks(s) reads, not from the
    files on disk, which run ahead of it while serving is pinned or a reload failed."""
    s = serving.state() if s is None else s
    parts = {"version": VERSION, "code": _code_mark(), "embed_model": client.LLM_EMBED_MODEL,
             "data": [s.get("version"), s.get("gold_version"), s.get("model_version"), s.get("asof")],
             "files": {f: _mtime(ROOT / f) for f in (HELP, *DOCS, FEATURE_LABELS)},
             "research": [_mtime(RESEARCH_FACTS), _mtime(RESEARCH_PROJECTS)], "app": _app_marks()}
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ index

def rrf(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal rank fusion: an item scores the sum of 1 / (k + rank) over the rankings it is in (rank 1 first);
    ties keep the order in which items first appear."""
    score, first = {}, {}
    for ranking in rankings:
        for rank, i in enumerate(ranking, 1):
            score[i] = score.get(i, 0.0) + 1.0 / (k + rank)
            first.setdefault(i, len(first))
    return sorted(score.items(), key=lambda t: (-t[1], first[t[0]]))


def _role(viewer) -> str:
    return getattr(viewer, "role", None) or "public"


def _embed_text(r: dict) -> str:
    return f"{DOC_PREFIX}{r['title']}\n{r['text']}"


def _hash(r: dict) -> str:
    return hashlib.sha1(f"{client.LLM_EMBED_MODEL}\n{_embed_text(r)}".encode()).hexdigest()[:16]


class Lexical:
    """TF-IDF over each chunk's title and text, and over the titles of TITLE_KINDS alone (a project's name, a help
    or doc heading; the templated titles of the other kinds, 'name: land acquisition issue', would tie by the
    thousand); each ranks the candidates that share a term with the query, best first."""

    def __init__(self, rows: list[dict]):
        def fit(docs):
            vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, stop_words="english",
                                  dtype=np.float32)
            return vec, vec.fit_transform(docs if any(docs) else ["paimana"]).tocsr()
        self.body, self.X = fit([f"{r['title']}\n{r['text']}" for r in rows])
        self.head, self.T = fit([(r["title"] or "") if r["kind"] in TITLE_KINDS else "" for r in rows])

    @property
    def n_terms(self) -> int:
        return len(self.body.vocabulary_)

    @staticmethod
    def _rank(vec, M, q: str, cand: np.ndarray) -> list[int]:
        qv = vec.transform([q])
        if not qv.nnz or not cand.size:
            return []
        s = (M @ qv.T).toarray().ravel()[cand]
        keep = np.flatnonzero(s > 0)
        return cand[keep[np.lexsort((cand[keep], -s[keep]))][:POOL]].tolist()

    def rank(self, q: str, cand: np.ndarray) -> list[list[int]]:
        out = [self._rank(self.body, self.X, q, cand)]
        return out + [self._rank(self.head, self.T, q, cand)] if TITLE_RANK else out


@dataclasses.dataclass
class Index:
    rows: list[dict]
    fingerprint: str
    lex: Lexical
    emb: np.ndarray | None          # (n, dim) float16
    has_emb: np.ndarray             # (n,) bool
    meta: dict = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        self.kind = np.array([r["kind"] for r in self.rows], dtype=object)
        self.public = np.array([r["visibility"] == "public" for r in self.rows], dtype=bool)
        self.pkey = np.array([r["project_key"] or "" for r in self.rows], dtype=object)
        self.named = {i: frozenset(r["mentions"].split()) for i, r in enumerate(self.rows) if r.get("mentions")}
        self._emb32 = None  # a float32 copy of emb, made at the first dense ranking

    @property
    def dense_ready(self) -> bool:
        return self.emb is not None and len(self.rows) > 0 and self.has_emb.mean() >= DENSE_MIN_SHARE

    def candidates(self, viewer, kinds=None, project_key=None) -> np.ndarray:
        """Indices of the chunks this viewer may read that pass the filters: visibility, scope (the chunk's project
        and every project it mentions), kinds, project."""
        mask = np.ones(len(self.rows), dtype=bool)
        if _role(viewer) == "public":
            mask &= self.public
        if kinds:
            mask &= np.isin(self.kind, list(kinds))
        if project_key:
            mask &= self.pkey == project_key
        keys = getattr(viewer, "keys", None)
        if keys is not None:
            keys = keys if isinstance(keys, (set, frozenset)) else set(keys)
            mask &= (self.pkey == "") | np.isin(self.pkey, list(keys))
            for i, named in self.named.items():
                if mask[i] and not named <= keys:
                    mask[i] = False
        return np.flatnonzero(mask)

    def dense(self, qv: np.ndarray, cand: np.ndarray) -> list[int]:
        ok = cand[self.has_emb[cand]]
        if not ok.size:
            return []
        if self._emb32 is None:
            # one float32 copy per index (float16 has no BLAS matmul): scoring every row and then picking the
            # candidates allocates one score vector per query, where copying the candidates' rows took about 26 MB
            # of temporaries per query at 5.7k chunks
            self._emb32 = self.emb.astype(np.float32)
        s = (self._emb32 @ qv)[ok]
        return ok[np.argsort(-s, kind="stable")[:POOL]].tolist()

    def hit(self, i: int, score: float, official: bool) -> dict:
        r = self.rows[i]
        return {"id": r["id"], "kind": r["kind"], "title": r["title"], "text": r["text"],
                "source": (r.get("official_source") or r["source"]) if official else r["source"],
                "url": r["url"], "date": r["date"], "project_key": r["project_key"], "score": round(float(score), 6),
                "trusted": r["kind"] in TRUSTED_KINDS}

    def search(self, q: str, viewer, k: int = 6, kinds=None, project_key=None) -> list[dict]:
        cand = self.candidates(viewer, kinds, project_key)
        if not cand.size:
            return []
        ranked = self.lex.rank(q, cand)
        if EMBED and self.dense_ready:
            qv = _query_vector(q, self.emb.shape[1])
            if qv is not None:
                ranked.append(self.dense(qv, cand))
        official = _role(viewer) != "public"
        return [self.hit(i, s, official) for i, s in rrf(ranked)[:k]]


def _query_vector(q: str, dim: int) -> np.ndarray | None:
    """The query's embedding, or None (keywords only) while LM Studio is down or the last try failed."""
    global _query_failed_at
    if client.down_recently() or time.monotonic() - _query_failed_at < QUERY_RETRY_S:
        return None
    try:
        v = np.asarray(client.embed([QUERY_PREFIX + q]), dtype=np.float32)
    except Exception as e:  # noqa: BLE001 - any embedder failure means keywords only, never a failed search
        _query_failed_at = time.monotonic()
        log.warning("rag: query embedding failed, keywords only for %.0f s: %s", QUERY_RETRY_S, e)
        return None
    return v[0] if v.shape == (1, dim) else None


def build_index(rows: list[dict], fp: str, previous: "Index | None" = None) -> Index:
    """The TF-IDF index of rows, with the vectors of previous for the chunks whose text did not change."""
    rows = [{**{c: r.get(c) for c in COLUMNS}, "hash": r.get("hash") or _hash(r)} for r in rows]
    emb, has = None, np.zeros(len(rows), dtype=bool)
    if previous is not None and previous.emb is not None:
        old = {r["hash"]: i for i, r in enumerate(previous.rows) if previous.has_emb[i]}
        hit = [(i, old[r["hash"]]) for i, r in enumerate(rows) if r["hash"] in old]
        if hit:
            emb = np.zeros((len(rows), previous.emb.shape[1]), dtype=np.float16)
            new_i, old_i = map(list, zip(*hit))
            emb[new_i] = previous.emb[old_i]
            has[new_i] = True
    return Index(rows, fp, Lexical(rows), emb, has, {"fingerprint": fp})


def embed_missing(idx: Index) -> Index:
    """idx with the chunks that have no vector embedded, in batches, pausing while a chat request is active; stops
    at the first failure (the rest stay keyword-only and are retried after EMBED_RETRY_S)."""
    global _embed_failed_at
    todo = np.flatnonzero(~idx.has_emb)
    if not todo.size:
        return idx
    emb = None if idx.emb is None else idx.emb.copy()
    has = idx.has_emb.copy()
    for start in range(0, todo.size, EMBED_BATCH):
        if client.chat_active():
            client.wait_chat_idle(CHAT_PAUSE_S)
        part = todo[start:start + EMBED_BATCH]
        try:
            v = np.asarray(client.embed([_embed_text(idx.rows[i]) for i in part]), dtype=np.float32)
            if emb is None:
                emb = np.zeros((len(idx.rows), v.shape[1]), dtype=np.float16)
            if v.shape != (part.size, emb.shape[1]):
                raise ValueError(f"embedding shape {v.shape}, expected ({part.size}, {emb.shape[1]})")
        except Exception as e:  # noqa: BLE001 - LM Studio down or a bad reply: keep what we have
            _embed_failed_at = time.monotonic()
            log.warning("rag: embedding stopped after %d of %d chunks: %s", start, todo.size, e)
            break
        emb[part] = v.astype(np.float16)
        has[part] = True
    return dataclasses.replace(idx, emb=emb, has_emb=has, meta=dict(idx.meta))


# ------------------------------------------------------------------ storage

def _tmp(d: Path, name: str) -> Path:
    """A temporary file name no other writer uses: the CLI build and the backend's refresh may save at once."""
    return d / f".{name}.{os.getpid()}.{threading.get_ident()}.{time.monotonic_ns()}.tmp"


def save(idx: Index, where: Path | None = None) -> None:
    """Write idx to where (RAG_DIR): chunks.parquet, embeddings.npz (the vectors of the embedded chunks with their
    content hashes, so load() pairs a vector only with the chunk it was computed from, whatever state the other
    files are in) and meta.json, each written to a temporary file of its own and moved into place."""
    d = where or RAG_DIR
    d.mkdir(parents=True, exist_ok=True)
    tmps = []

    def put(name: str, write) -> None:
        t = _tmp(d, name)
        tmps.append(t)
        write(t)
        os.replace(t, d / name)

    try:
        put("chunks.parquet", lambda t: pd.DataFrame(idx.rows, columns=COLUMNS + ["hash"]).to_parquet(t, index=False))
        if idx.emb is not None and idx.has_emb.any():
            on = np.flatnonzero(idx.has_emb)
            hashes = np.array([idx.rows[i]["hash"] for i in on], dtype=str)

            def vectors(t):
                with open(t, "wb") as f:
                    np.savez(f, emb=idx.emb[on].astype(np.float16), hash=hashes)
            put("embeddings.npz", vectors)
        else:
            (d / "embeddings.npz").unlink(missing_ok=True)
        (d / "embeddings.npy").unlink(missing_ok=True)  # the format before the hashes were saved with the vectors
        counts = Counter(f"{r['kind']}/{r['visibility']}" for r in idx.rows)
        meta = {**idx.meta, "fingerprint": idx.fingerprint, "version": VERSION, "n_chunks": len(idx.rows),
                "n_embedded": int(idx.has_emb.sum()), "embed_model": client.LLM_EMBED_MODEL,
                "dim": None if idx.emb is None else int(idx.emb.shape[1]), "counts": dict(sorted(counts.items())),
                "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        put("meta.json", lambda t: t.write_text(json.dumps(meta, indent=1), encoding="utf-8"))
    finally:
        for t in tmps:
            t.unlink(missing_ok=True)
    idx.meta = meta


def _saved_vectors(d: Path, df: pd.DataFrame, rows: list[dict]) -> tuple[np.ndarray, np.ndarray] | None:
    """(emb, has) for rows: from embeddings.npz, each vector matched to its chunk by content hash; from the older
    embeddings.npy (row i for chunk i, the parquet's embedded column) only when that is all there is."""
    try:
        if (d / "embeddings.npz").exists():
            with np.load(d / "embeddings.npz") as z:
                e, at = z["emb"], {h: i for i, h in enumerate(z["hash"].tolist())}
            pairs = [(i, at[r["hash"]]) for i, r in enumerate(rows) if r["hash"] in at]
        elif (d / "embeddings.npy").exists() and "embedded" in df:
            e = np.load(d / "embeddings.npy")
            if len(e) != len(rows):
                return None
            pairs = [(i, i) for i in np.flatnonzero(df["embedded"].to_numpy(dtype=bool))]
        else:
            return None
    except (OSError, ValueError, KeyError) as err:
        log.warning("rag: cannot read the saved vectors in %s: %s", d, err)
        return None
    if e.ndim != 2 or not pairs:
        return None
    emb, has = np.zeros((len(rows), e.shape[1]), dtype=np.float16), np.zeros(len(rows), dtype=bool)
    new, old = map(list, zip(*pairs))
    emb[new], has[new] = e[old], True
    return emb, has


def load(where: Path | None = None, *, any_version: bool = False) -> Index | None:
    """The saved index, or None when there is none or it cannot be read. any_version also reads an index of another
    chunk VERSION, only to reuse its vectors (they are matched to chunks by content hash, not by schema)."""
    d = where or RAG_DIR
    try:
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        df = pd.read_parquet(d / "chunks.parquet")
    except (OSError, ValueError) as e:
        if not isinstance(e, FileNotFoundError):
            log.warning("rag: cannot read the saved index in %s: %s", d, e)
        return None
    if meta.get("version") != VERSION and not any_version:
        return None
    rows = [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()}
            for r in df.drop(columns="embedded", errors="ignore").to_dict("records")]
    for r in rows:
        r["hash"] = _hash(r)  # from the text itself, not trusted from the file
    vec = _saved_vectors(d, df, rows) if meta.get("embed_model") == client.LLM_EMBED_MODEL else None
    emb, has = vec if vec is not None else (None, np.zeros(len(rows), dtype=bool))
    return Index(rows, meta["fingerprint"], Lexical(rows), emb, has, meta)


# ------------------------------------------------------------------ the served index

def current() -> Index | None:
    """The index served now, without checking the inputs."""
    return _index


def _publish(idx: Index) -> None:
    global _index
    _index = idx
    _ready.set()


def _stale(idx: Index | None, fp: str) -> bool:
    now = time.monotonic()
    if idx is None or idx.fingerprint != fp:
        return now - _build_failed_at >= EMBED_RETRY_S
    return (EMBED and not idx.has_emb.all() and now - _embed_failed_at >= EMBED_RETRY_S
            and not client.down_recently())


def rebuild(embed: bool = True, previous: Index | None = None, s: dict | None = None) -> Index:
    """Build from the current inputs now, reusing the vectors of unchanged chunks, then serve and save it. s is the
    served data state both the chunks and the fingerprint are taken from (serving.state() by default). Waits for a
    background refresh of this process to finish first (one build at a time)."""
    with _build_lock:
        return _rebuild(embed, previous, s)


def _rebuild(embed: bool, previous: Index | None, s: dict | None) -> Index:
    t0 = time.monotonic()
    s = serving.state() if s is None else s
    fp = fingerprint(s)
    previous = previous or _index or load(any_version=True)
    rows = build_chunks(s)
    t1 = time.monotonic()
    idx = build_index(rows, fp, previous)
    t2 = time.monotonic()
    _publish(idx)
    n_before = int(idx.has_emb.sum())
    if embed and EMBED:
        idx = embed_missing(idx)
    t3 = time.monotonic()
    idx.meta.update({"chunk_s": round(t1 - t0, 2), "lexical_s": round(t2 - t1, 2), "embed_s": round(t3 - t2, 2),
                     "n_embedded_now": int(idx.has_emb.sum()) - n_before, "built_at": datetime.now(
                         timezone.utc).isoformat(timespec="seconds")})
    _publish(idx)
    save(idx)
    return idx


def _refresh(raise_errors: bool = False) -> None:
    """Serve the saved index if none is served yet; rebuild or finish its embeddings when stale."""
    global _build_failed_at
    if not _build_lock.acquire(blocking=False):
        return
    _building.set()
    try:
        idx = _index
        if idx is None:
            idx = load()
            if idx is not None:
                _publish(idx)
        s = serving.state()            # once: the fingerprint and the chunks describe the same data version
        fp = fingerprint(s)
        if not _stale(idx, fp):
            return
        if idx is not None and idx.fingerprint == fp:
            idx = embed_missing(idx)   # same chunks, only vectors missing
            _publish(idx)
            save(idx)
        else:
            _rebuild(True, idx, s)   # this thread holds the build lock
    except Exception:
        _build_failed_at = time.monotonic()
        log.exception("rag: index build failed")
        if raise_errors:
            raise
    finally:
        _building.clear()
        _build_lock.release()


def ensure_index(background: bool = True) -> Index | None:
    """The served index (None until the first one exists). At most every CHECK_S seconds it checks the inputs'
    fingerprint and rebuilds a stale index, in a background thread unless background is False; meanwhile the old
    index (or the new one without vectors) keeps serving. Call it once at startup to load early."""
    global _checked_at
    now = time.monotonic()
    if _index is not None and now - _checked_at < CHECK_S:
        return _index
    _checked_at = now
    if not background:
        _refresh(raise_errors=True)
    elif not _build_lock.locked():
        _building.set()  # before the thread starts, so a search that finds no index knows one is coming
        threading.Thread(target=_refresh, name="rag-index", daemon=True).start()
    return _index


def search(query: str, viewer, k: int = 6, kinds: set[str] | None = None,
           project_key: str | None = None) -> list[dict]:
    """The k best chunks for query that viewer may read (backend.access.Viewer: role, keys), as Hits {id, kind,
    title, text, source, url, date, project_key, score, trusted}; kinds and project_key narrow the candidates before
    ranking. trusted is False for the kinds that quote outside text (event, research, news, external): the chat
    passes their text as quoted data, never as instructions.
    [] when there is no index yet (after waiting up to WAIT_S while the first one is being built)."""
    q = (query or "").strip()[:1000]
    if not q or k <= 0:
        return []
    idx = ensure_index(background=True)
    deadline = time.monotonic() + WAIT_S
    while idx is None and _building.is_set() and time.monotonic() < deadline:
        _ready.wait(0.1)
        idx = _index
    return idx.search(q, viewer, k, kinds, project_key) if idx is not None else []


def reset() -> None:
    """Forget the served index and every retry timer (tests); a background refresh still running (a search starts
    one) is waited for first, so it cannot publish into the next test."""
    global _index, _checked_at, _build_failed_at, _embed_failed_at, _query_failed_at
    with _build_lock:
        pass
    _index = None
    _ready.clear()
    _building.clear()
    _checked_at = _build_failed_at = _embed_failed_at = _query_failed_at = -1e9


# ------------------------------------------------------------------ CLI

def _counts(idx: Index) -> str:
    c = Counter((r["kind"], r["visibility"]) for r in idx.rows)
    return "\n".join(f"  {k:<9} {v:<8} {n:>6}" for (k, v), n in sorted(c.items()))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m llm.rag", description="The assistant's search index.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the index now (embeddings of unchanged chunks are reused)")
    b.add_argument("--no-embed", action="store_true", help="TF-IDF only, no LM Studio calls")
    q = sub.add_parser("search", help="search as a role")
    q.add_argument("query")
    q.add_argument("--role", default="public", choices=["public", "agency_official", "ministry_official",
                                                        "ipmd_analyst"])
    q.add_argument("--ministry")
    q.add_argument("--agency")
    q.add_argument("-k", type=int, default=6)
    q.add_argument("--kinds", help="comma-separated, of " + ", ".join(KINDS))
    q.add_argument("--project", help="a PRJ key")
    sub.add_parser("stats", help="what the saved index holds")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per embedding request otherwise

    if args.cmd == "build":
        t0 = time.monotonic()
        idx = rebuild(embed=not args.no_embed)
        m = idx.meta
        print(f"{len(idx.rows)} chunks in {time.monotonic() - t0:.1f} s (chunks {m['chunk_s']} s, TF-IDF "
              f"{m['lexical_s']} s, embeddings {m['embed_s']} s for {m['n_embedded_now']} new); "
              f"{int(idx.has_emb.sum())} with a vector, {idx.lex.n_terms:,} TF-IDF terms\n"
              f"{_counts(idx)}")
        return 0
    if args.cmd == "stats":
        idx = load()
        if idx is None:
            print("no saved index; run python -m llm.rag build")
            return 1
        print(f"{len(idx.rows)} chunks, {int(idx.has_emb.sum())} with a vector, fingerprint {idx.fingerprint} "
              f"(current {fingerprint()})\n{_counts(idx)}")
        return 0
    from backend.access import make_viewer  # noqa: PLC0415 - the CLI's only use of the API layer
    v = make_viewer(args.role, args.ministry, args.agency)
    kinds = set(args.kinds.split(",")) if args.kinds else None
    idx = load() or rebuild(embed=False)
    if idx.fingerprint != fingerprint():
        print("(the saved index is stale; python -m llm.rag build refreshes it)")
    t0 = time.monotonic()
    hits = idx.search(args.query, v, k=args.k, kinds=kinds, project_key=args.project)
    print(f"{len(hits)} hits in {1000 * (time.monotonic() - t0):.0f} ms "
          f"({'hybrid' if idx.dense_ready and _query_failed_at < 0 else 'keywords only'})")
    for h in hits:
        print(f"{h['score']:.4f} {h['kind']:<9} {h['id']:<34} {h['title'][:70]}\n"
              f"         {h['text'][:200].replace(chr(10), ' ')}\n         source: {h['source']}"
              + (f" | {h['url']}" if h["url"] else "") + (f" | {h['date']}" if h["date"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
