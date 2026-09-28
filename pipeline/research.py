"""
Web research evidence (dataset/raw/external/research/README.md): what the public web said about each current
project, one cited fact per row, each checked by a second agent (basis 'article': the source was read and
re-opened; 'headline': a news-feed headline and its feed summary were judged).

Run from repo root after the external step:  python -m pipeline.run research

Inputs   raw/external/research/research_sweep_*.jsonl (one line per project; for a project in more than one file the
         line with the latest researched_on wins), silver/project_master.parquet (the known keys and their state),
         silver/observations.parquet (asof: its latest period, the gold asof)
Outputs  gold/research_facts.parquet (one row per fact), gold/research_projects.parquet (one row per searched
         project: coverage, latest status and the flattened external block), gold/research_summary.json (coverage,
         facts by category x direction, live blockers by category and state, the top recent ones, validation counts)

Every line is validated (validate_line): its shape, the enums (category, direction, severity 1-3, match, verdict),
http(s) URLs, dates that parse ('YYYY-MM-DD', 'YYYY-MM' or 'YYYY'), a summary of at most MAX_WORDS words, and a
privacy floor (private_names): an honorific followed by a capitalised word ('Shri Ramesh ...', 'Mr. Singh',
'Mr.Singh') is rejected unless the capitalised words after it, up to the first of / the / and, end in a word naming
an organisation or a place ('Dr. Ram Manohar Lohia Hospital', 'Dr B R Ambedkar Institute of Technology', 'Sri
Lanka'; not 'Shri Ramesh Kumar of the Municipal Corporation', and a surname-like place word such as Nagar or Sagar
only after another one); named officials are rejected too (officials by office only). The floor catches honorific +
name only: a name with no honorific relies on the researchers' rule. A bad fact is dropped with its reason, a
bad latest_status or external entry is blanked, and a bad line or an unknown project key drops the project; the
counts go to the summary. A status outside ongoing / resolved / unknown reads as unknown. The fact's category maps
to the report-remark TAXONOMY of pipeline/external.py (funds -> funding, natural_event -> weather; approvals_other,
design_scope, progress and other have no taxonomy row and keep their name).

A fact is live when it is negative, not resolved and dated (event date, else publish date) after asof minus LIVE_Q
calendar quarters, the window of the report-remark flags (pipeline/hidden_delay.py); a month or year date counts
from its first day, so a coarse date errs toward not live. The risk profile (ml/risk_profile.py) recomputes it at
its own asof with live().

Not model features: a sweep run in 2026 knows 2026 (hindsight for any earlier quarter), large troubled projects get
far more coverage than quiet ones (notoriety bias: news measures fame as much as risk, and no news is not no
problem), and one search per project is a snapshot with no point-in-time history for the backtest to replay. The
facts are evidence only: the project page, External Factors, the risk profile's land / forest / litigation /
contractor rows and the assistant.
"""
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.hidden_delay import LIVE_Q  # noqa: E402
from pipeline.silver import ROOT, SILVER  # noqa: E402

GOLD = ROOT / "dataset" / "gold"
RESEARCH = ROOT / "dataset" / "raw" / "external" / "research"
FACTS, PROJECTS, SUMMARY = (GOLD / "research_facts.parquet", GOLD / "research_projects.parquet",
                            GOLD / "research_summary.json")
# research category -> pipeline/external.py TAXONOMY name (the last four have no taxonomy row)
TAXONOMY_OF = {"land": "land", "forest_env": "forest_env", "litigation": "litigation", "contractor": "contractor",
               "funds": "funding", "utility_shifting": "utility_shifting", "inter_agency": "inter_agency",
               "law_order": "law_order", "natural_event": "weather", "approvals_other": "approvals_other",
               "design_scope": "design_scope", "progress": "progress", "other": "other"}
DIRECTIONS, STATUSES = ("negative", "positive", "neutral"), ("ongoing", "resolved", "unknown")
MATCHES, VERDICTS = ("high", "medium", "low"), ("keep", "fix")
# how deep the researcher read: 'article' opened the source, 'headline' judged a news-feed headline and its feed
# summary only (the pass that took over when the web-search budget ran out); a line without it is 'article'
BASES = ("article", "headline")
# the brief's copyright rule is a paraphrase of 30 words or fewer, and the agents were asked for 30; the floor is
# 40 so a verified paraphrase a word or two over (the pilot has one of 31) is not dropped. It is our own wording,
# never quoted article text (dataset/raw/external/research/README.md records the same deviation)
MAX_WORDS = 40
TOP_BLOCKERS = 20
DATE_RX = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
PRECISION = {1: "year", 2: "month", 3: "day"}
# an honorific ('Mr', 'Mr.', 'Mr.Singh'), then its run of capitalised words (initials and 'of' / 'the' / 'and' inside
# the run)
# not after a number: '12 Km Corridor' or '4.94-Km stretch' is a length, not Kumari
HONORIFIC = re.compile(r"(?<!\d)(?<!\d[ -])\b(?:Mr|Mrs|Ms|Mx|Shri|Shrimati|Smt|Sri|Sh|Dr|Kumari|Km|Prof|MR|MRS|SHRI|SMT"
                       r"|SRI|DR)\b"
                       r"(?:\.\s*|\s+)([A-Z][\w'.-]*(?:\s+(?:[A-Z][\w'.-]*|of|the|and|&))*)")
# the head of a run is its words before the first of / the / and / & ('Ramesh Kumar' of 'Ramesh Kumar of the
# Municipal Corporation'); the run names a thing, not a person, only when its head ENDS in one of these words: an
# institution, a company, a place or a work ('Dr. Ram Manohar Lohia Hospital', 'Dr B R Ambedkar Institute of
# Technology', 'Sri Lanka')
ORG_WORDS = re.compile(
    r"\b(?:hospital|university|college|institute|school|academy|board|trust|foundation|society|samiti|sansthan"
    r"|nagar|marg|road|path|chowk|setu|bridge|flyover|station|airport|stadium|port|terminal|dam|canal|sagar"
    r"|projects?|pariyojana|yojana|scheme|mission|memorial|park|temple|mandir|shrine|complex|bhawan|bhavan|hall"
    r"|cent(?:re|er)|library|museum|market|corporation|limited|ltd|authority|council|commission|department"
    r"|ministry|district|municipal|medical|garden|expressway|highway|lanka|city|ganganagar|sahib|kalahasti"
    r"|navami|jayanti|puja|mela|utsav|mahotsav"
    r"|nellore|puttaparthi|constructions?|contractors?|builders|developers|engineers|engineering|enterprises?"
    r"|industries|infra|infrastructure|infratech|associates|company|pvt|private|group|laboratories)\b", re.I)
# place words that are also surnames ('Mr. Ramesh Nagar', 'Dr. Anil Sagar'): they end a thing's name only after
# another of ORG_WORDS ('Sri City Industrial Park')
SURNAME_WORDS = {"sagar", "nagar", "park"}
CONNECTOR = re.compile(r"\s+(?:of|the|and|&)(?=\s|$)")
EXT_KEYS = {"land_acquired_pct": ("value", "as_of"), "forest_clearance": ("stage", "as_of"),
            "court_case": ("court", "status", "as_of"), "contractor": ("company", "status", "as_of"),
            "new_target": ("date", "as_of"), "cost_revision": ("new_cost_cr", "as_of")}
# flattened external block: (entry, field) -> column of research_projects
EXT_COLS = {("land_acquired_pct", "value"): "land_acquired_pct", ("land_acquired_pct", "as_of"): "land_as_of",
            ("forest_clearance", "stage"): "fc_stage", ("forest_clearance", "as_of"): "fc_as_of",
            ("court_case", "court"): "court", ("court_case", "status"): "court_status",
            ("court_case", "as_of"): "court_as_of", ("contractor", "company"): "contractor",
            ("contractor", "status"): "contractor_status", ("contractor", "as_of"): "contractor_as_of",
            ("new_target", "date"): "new_target", ("new_target", "as_of"): "new_target_as_of",
            ("cost_revision", "new_cost_cr"): "cost_revision_cr", ("cost_revision", "as_of"): "cost_revision_as_of"}
FACT_COLS = ["fact_id", "project_key", "category", "taxonomy", "direction", "severity", "event_date",
             "date_precision", "published_date", "status", "summary", "headline", "source", "url", "domain", "match",
             "match_reason", "verified", "basis", "origin", "researched_on", "live"]
PROJECT_COLS = (["project_key", "researched_on", "searched", "n_queries", "n_facts", "n_negative_live",
                 "latest_status"] + list(EXT_COLS.values()))


def parse_date(s) -> tuple[pd.Timestamp | None, str | None]:
    """'YYYY-MM-DD' | 'YYYY-MM' | 'YYYY' -> (the first day it covers, 'day' | 'month' | 'year'); None -> (None,
    None); anything else raises ValueError."""
    if s is None:
        return None, None
    m = DATE_RX.match(str(s).strip())
    if not m:
        raise ValueError(f"date {s!r} is not YYYY-MM-DD, YYYY-MM or YYYY")
    parts = [p for p in m.groups() if p]
    t = pd.Timestamp(year=int(parts[0]), month=int(parts[1]) if len(parts) > 1 else 1,
                     day=int(parts[2]) if len(parts) > 2 else 1)
    if not 1990 <= t.year <= 2100:
        raise ValueError(f"date {s!r} is out of range")
    return t, PRECISION[len(parts)]


def show_date(t, precision) -> str:
    """A parsed date back as written: 2026-08-13, 2026-08 or 2026 ('n/a' when missing)."""
    if t is None or pd.isna(t):
        return "n/a"
    return pd.Timestamp(t).strftime({"year": "%Y", "month": "%Y-%m"}.get(precision, "%Y-%m-%d"))


def _names_thing(run: str) -> bool:
    """The run after an honorific names an organisation or a place: its head (the words before of / the / and / &)
    ends in one of ORG_WORDS, a surname-like one (SURNAME_WORDS) only after another."""
    words = CONNECTOR.split(run, maxsplit=1)[0].split()
    found = [m.group(0).lower() for m in map(ORG_WORDS.search, words) if m]
    last = ORG_WORDS.search(words[-1]) if words else None
    if last is None:
        return False
    return last.group(0).lower() not in SURNAME_WORDS or any(w not in SURNAME_WORDS for w in found[:-1])


def private_names(text) -> list[str]:
    """Honorific + capitalised-name runs in text that do not name an organisation or place (see the docstring).
    Anything but a string has none (the validators reject a field of the wrong type themselves)."""
    if not isinstance(text, str):
        return []
    return [m.group(0) for m in HONORIFIC.finditer(text) if not _names_thing(m.group(1))]


def fact_id(key: str, url: str, category: str, event_date) -> str:
    """sha256[:12] of key|url|category|event_date (the date as written; '' when unknown)."""
    return hashlib.sha256(f"{key}|{url}|{category}|{event_date or ''}".encode("utf-8")).hexdigest()[:12]


def domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def live_since(asof) -> pd.Timestamp:
    """Facts dated after this are recent enough to be live (LIVE_Q calendar quarters before asof)."""
    return pd.Timestamp(asof) - pd.DateOffset(months=3 * LIVE_Q)


def is_live(direction, status, event_date, published_date, asof) -> bool:
    """One fact: negative, not resolved, dated (event, else publish) after live_since(asof)."""
    t = event_date if event_date is not None and not pd.isna(event_date) else published_date
    return (direction == "negative" and status != "resolved" and t is not None and not pd.isna(t)
            and pd.Timestamp(t) > live_since(asof))


def live(df: pd.DataFrame, asof) -> pd.Series:
    """is_live over a facts frame (direction, status, event_date, published_date)."""
    t = pd.to_datetime(df["event_date"]).fillna(pd.to_datetime(df["published_date"]))
    return df["direction"].eq("negative") & df["status"].ne("resolved") & t.gt(live_since(asof)).fillna(False)


def _text(v, what) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{what} is missing")
    return v.strip()


def _opt_text(v, what) -> str | None:
    """An optional text field: None or '' -> None; anything but a string is a ValueError."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"{what} is not text")
    return v.strip() or None


def validate_fact(key: str, f: dict) -> tuple[dict | None, str | None]:
    """One raw fact -> (a FACT_COLS row without live / researched_on / origin, None) or (None, reason). A field of
    the wrong type is a reason like any other, never an exception: one bad line must not stop the step (and with it
    the report watcher's ingest)."""
    try:
        if not isinstance(f, dict):
            raise ValueError("fact is not an object")
        cat, direction, match = f.get("category"), f.get("direction"), f.get("match")
        if not isinstance(cat, str) or cat not in TAXONOMY_OF:
            raise ValueError(f"category {cat!r}")
        if direction not in DIRECTIONS:
            raise ValueError(f"direction {direction!r}")
        if match not in MATCHES:
            raise ValueError(f"match {match!r}")
        sev = f.get("severity")
        if isinstance(sev, bool) or not isinstance(sev, int) or not 1 <= sev <= 3:
            raise ValueError(f"severity {sev!r}")
        if f.get("verified") not in VERDICTS:
            raise ValueError(f"verified {f.get('verified')!r}")
        basis = f.get("basis", "article")
        if basis not in BASES:
            raise ValueError(f"basis {basis!r}")
        url = _text(f.get("url"), "url")
        if urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname:
            raise ValueError("url is not http(s)")
        summary, headline = _text(f.get("summary"), "summary"), _text(f.get("headline"), "headline")
        if len(summary.split()) > MAX_WORDS:
            raise ValueError(f"summary over {MAX_WORDS} words")
        source, reason = _opt_text(f.get("source"), "source"), _opt_text(f.get("match_reason"), "match_reason")
        event_date, published_date = (_opt_text(f.get(c), c) for c in ("event_date", "published_date"))
        ev, precision = parse_date(event_date)
        pub, _ = parse_date(published_date)
        if any(private_names(t) for t in (summary, headline, source, reason)):
            raise ValueError("privacy: names a person")   # the name itself never goes into the summary
        status = f.get("status")
        status = status.strip().lower() if isinstance(status, str) else ""
    except (ValueError, TypeError, AttributeError) as e:
        return None, str(e) if isinstance(e, ValueError) else f"malformed fact ({type(e).__name__})"
    return {"fact_id": fact_id(key, url, cat, event_date), "project_key": key, "category": cat,
            "taxonomy": TAXONOMY_OF[cat], "direction": direction, "severity": sev, "event_date": ev,
            "date_precision": precision, "published_date": pub,
            "status": status if status in STATUSES else "unknown", "summary": summary, "headline": headline,
            "source": source or domain(url), "url": url, "domain": domain(url), "match": match,
            "match_reason": reason, "verified": f["verified"], "basis": basis}, None


def validate_external(ext) -> tuple[dict, list[tuple[str, str]]]:
    """The external block -> (flattened EXT_COLS values, (where, reason) of the entries blanked)."""
    out, issues = dict.fromkeys(EXT_COLS.values()), []
    if ext is None:
        return out, issues
    if not isinstance(ext, dict):
        return out, [("external", "not an object")]
    for entry, fields in EXT_KEYS.items():
        v = ext.get(entry)
        if v is None:
            continue
        try:
            if not isinstance(v, dict):
                raise ValueError("not an object")
            vals = {f: v.get(f) for f in fields}
            num = {"land_acquired_pct": "value", "cost_revision": "new_cost_cr"}.get(entry)
            for f in fields:
                if f != num and vals[f] is not None and not isinstance(vals[f], str):
                    raise ValueError(f"{f} is not text")
            parse_date(vals["as_of"])
            if entry == "new_target":
                parse_date(vals["date"])
            if num:
                x = vals[num]
                if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0 or (
                        entry == "land_acquired_pct" and x > 100):
                    raise ValueError(f"{num} {x!r}")
                vals[num] = float(x)
            if any(private_names(x) for x in vals.values() if isinstance(x, str)):
                raise ValueError("privacy: names a person")
        except (ValueError, TypeError, AttributeError) as e:
            issues.append((f"external.{entry}", str(e) if isinstance(e, ValueError) else type(e).__name__))
            continue
        for f, x in vals.items():
            out[EXT_COLS[(entry, f)]] = x
    return out, issues


def validate_line(obj, known) -> tuple[dict | None, list[dict], list[tuple[str, str]]]:
    """One JSON line -> (research_projects row or None, fact rows, issues as (where, reason)). known: the project
    keys."""
    if not isinstance(obj, dict):
        return None, [], [("line", "not an object")]
    key = obj.get("project_key")
    if not isinstance(key, str) or key not in known:
        return None, [], [("line", "unknown project key")]
    try:
        researched, _ = parse_date(_opt_text(obj.get("researched_on"), "researched_on"))
        if researched is None:
            raise ValueError("researched_on is missing")
        if not isinstance(obj.get("facts", []), list):
            raise ValueError("facts is not a list")
        if not isinstance(obj.get("searched", True), bool):   # 'false' as a string would read as True
            raise ValueError("searched is not true or false")
    except ValueError as e:
        return None, [], [("line", str(e))]
    issues, facts, seen = [], [], set()
    for f in obj.get("facts") or []:
        row, why = validate_fact(key, f)
        if row is None:
            issues.append(("fact", why))
        elif row["fact_id"] not in seen:
            seen.add(row["fact_id"])
            facts.append({**row, "researched_on": researched, "origin": "sweep"})
    ext, ext_issues = validate_external(obj.get("external"))
    status = obj.get("latest_status") if isinstance(obj.get("latest_status"), str) else None
    if status and private_names(status):
        issues.append(("latest_status", "privacy: names a person"))
        status = None
    queries = obj.get("queries") if isinstance(obj.get("queries"), list) else []
    return ({"project_key": key, "researched_on": researched, "searched": obj.get("searched", True),
             "n_queries": len(queries), "latest_status": (status or "").strip() or None, **ext},
            facts, issues + ext_issues)


def load(paths=None, known=None) -> tuple[list[tuple[dict, list[dict]]], dict]:
    """Every sweep line, validated; for a project in more than one line the latest researched_on wins (the later
    file on a tie). Returns ([(project row, fact rows)], validation counts)."""
    paths = sorted(RESEARCH.glob("research_sweep_*.jsonl")) if paths is None else paths
    best, reasons, n_lines, n_bad = {}, Counter(), 0, 0
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            reasons[f"file: {Path(path).name} is not UTF-8"] += 1
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            n_lines += 1
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, RecursionError):
                n_bad += 1
                reasons[f"line: {Path(path).name}:{i} is not JSON"] += 1
                continue
            try:
                proj, facts, issues = validate_line(obj, known)
            except (ValueError, TypeError, AttributeError, KeyError) as e:   # a shape no check foresaw: drop it
                proj, facts, issues = None, [], [("line", f"{Path(path).name}:{i} malformed ({type(e).__name__})")]
            reasons.update(f"{where}: {why}" for where, why in issues)
            if proj is None:
                n_bad += 1
                continue
            k = proj["project_key"]
            if k not in best or proj["researched_on"] >= best[k][0]["researched_on"]:
                best[k] = (proj, facts, issues)
    kept = list(best.values())
    counts = {"files": [Path(p).name for p in paths], "lines_read": n_lines, "lines_dropped": n_bad,
              "facts_dropped": sum(1 for _, _, iss in kept for where, _ in iss if where == "fact"),
              "privacy_rejected": sum(1 for _, _, iss in kept for _, why in iss if why.startswith("privacy")),
              "reasons": dict(reasons.most_common(20))}
    return [(p, f) for p, f, _ in kept], counts


def tables(lines, asof) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(research_facts, research_projects) from load()'s lines at asof."""
    facts = pd.DataFrame([f for _, fs in lines for f in fs], columns=[c for c in FACT_COLS if c != "live"])
    facts = facts.astype({"severity": "int8"}) if len(facts) else facts
    for c in ("event_date", "published_date", "researched_on"):
        facts[c] = pd.to_datetime(facts[c]).astype("datetime64[us]")
    facts["live"] = live(facts, asof) if len(facts) else pd.Series(dtype=bool)
    facts = facts.sort_values(["project_key", "event_date", "fact_id"], ascending=[True, False, True],
                              na_position="last", ignore_index=True)[FACT_COLS]
    projects = pd.DataFrame([p for p, _ in lines], columns=[c for c in PROJECT_COLS if not c.startswith("n_f")
                                                             and c != "n_negative_live"])
    projects["researched_on"] = pd.to_datetime(projects["researched_on"]).astype("datetime64[us]")
    # typed even when a column is all null (the pilot sample), so the parquet schema does not depend on the data
    num = {"land_acquired_pct", "cost_revision_cr"}
    projects = projects.astype({c: "float64" if c in num else "str" for c in ["latest_status", *EXT_COLS.values()]})
    projects["n_facts"] = projects["project_key"].map(facts.groupby("project_key").size()).fillna(0).astype(int)
    projects["n_negative_live"] = projects["project_key"].map(
        facts[facts["live"]].groupby("project_key").size()).fillna(0).astype(int)
    return facts, projects.sort_values("project_key", ignore_index=True)[PROJECT_COLS]


def summary(facts, projects, asof, states, validation) -> dict:
    """gold/research_summary.json: coverage, facts by category x direction, live negative by category and by state,
    the top recent blockers (live negative, severity >= 2, newest first) and the validation counts."""
    neg = facts[facts["live"]]
    st = projects.assign(state=projects["project_key"].map(states).fillna("unknown"))
    fst = facts.assign(state=facts["project_key"].map(states).fillna("unknown"))
    by_state = []
    for s, g in st.groupby("state"):
        f = fst[fst["state"].eq(s)]
        by_state.append({"state": s, "n_searched": int(g["searched"].sum()), "n_with_facts": int(g["n_facts"].gt(0)
                                                                                               .sum()),
                         "n_facts": int(len(f)), "n_negative_live": int(f["live"].sum()),
                         "n_projects_negative_live": int(f.loc[f["live"], "project_key"].nunique())})
    top = neg[neg["severity"] >= 2].sort_values(["event_date", "severity", "fact_id"], ascending=[False, False, True],
                                                na_position="last")
    researched = projects["researched_on"]
    return {
        "asof": str(pd.Timestamp(asof).date()), "live_window_quarters": LIVE_Q,
        "researched_on": {"first": None if researched.empty else str(researched.min().date()),
                          "last": None if researched.empty else str(researched.max().date())},
        "coverage": {"n_projects_searched": int(projects["searched"].sum()),
                     "n_projects_with_facts": int(projects["n_facts"].gt(0).sum()), "n_facts": int(len(facts)),
                     "n_negative_live": int(len(neg)), "n_projects_negative_live": int(neg["project_key"].nunique())},
        "facts_by_category": {c: {d: int(n) for d, n in g["direction"].value_counts().items()}
                              for c, g in facts.groupby("category")},
        "live_negative_by_category": {c: {"n_facts": int(len(g)), "n_projects": int(g["project_key"].nunique())}
                                      for c, g in neg.groupby("category")},
        "by_state": sorted(by_state, key=lambda r: (-r["n_negative_live"], -r["n_searched"], r["state"])),
        "top_recent_blockers": top["fact_id"].head(TOP_BLOCKERS).tolist(),
        "validation": validation,
    }


def build(asof=None, paths=None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(research_facts, research_projects, summary) from the sweep files at asof (default: the latest silver
    period, the gold asof)."""
    master = pd.read_parquet(SILVER / "project_master.parquet", columns=["project_key", "state"])
    if asof is None:
        asof = pd.read_parquet(SILVER / "observations.parquet", columns=["period"])["period"].max()
    lines, validation = load(paths, set(master["project_key"]))
    facts, projects = tables(lines, asof)
    return facts, projects, summary(facts, projects, asof, master.set_index("project_key")["state"], validation)


def main(asof=None):
    t0 = time.time()
    facts, projects, s = build(asof)
    facts.to_parquet(FACTS, index=False)
    projects.to_parquet(PROJECTS, index=False)
    SUMMARY.write_text(json.dumps(s, indent=2, default=str) + "\n", encoding="utf-8")   # last: serving's version
    v, c = s["validation"], s["coverage"]
    print(f"research: {c['n_projects_searched']} projects searched ({c['n_projects_with_facts']} with facts), "
          f"{c['n_facts']} facts, {c['n_negative_live']} live negative on {c['n_projects_negative_live']} projects "
          f"at asof {s['asof']}; researched {s['researched_on']['first']} to {s['researched_on']['last']}")
    print(f"validation: {v['lines_read']} lines read, {v['lines_dropped']} dropped, {v['facts_dropped']} facts dropped "
          f"({v['privacy_rejected']} for privacy); {v['reasons'] or 'no issues'}")
    print(f"research: {time.time() - t0:.1f}s")
    return facts, projects, s


if __name__ == "__main__":
    main()
