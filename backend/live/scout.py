"""News scout (docs/IMPLEMENTATION_GUIDE_v2.md B 4.2 scout / classify_signal, B 6.2 External Evidence Radar).

run(keys) searches Google News RSS with 3-5 aliases per project (distinctive name tokens, the object and the state)
and reads the PIB press-release feed once; batch() picks up to MAX_PROJECTS projects: watchlists first, then Critical
and High, least recently scouted first, so the High / Critical set rotates through the daily runs. Every item is
  - skipped when its title is mostly in a non-Latin script (the linker and the taxonomy read English only),
  - deduped by URL hash and by title + text hash,
  - entity-linked to the current portfolio. A project's place words are its name words (4+ letters, not STOP, not
    its state's words) that occur in at most DF_MAX current project names. score = 0.5 x min(1, place words found
    / 2) + 0.5 if a context anchor is found too: its NH number, its object (bypass, airport ...; not a plain road)
    or its agency's short name (NHAI, AAI ...). So two place words link, or one with an anchor; one place word
    alone (a city's general news) does not. score >= LINK_MIN links unless a second project is within LINK_MARGIN
    (ambiguous, e.g. two packages of one corridor): an ambiguous item is stored with no project (the unlinked
    pool), a weaker one is dropped,
  - classified with the report-remark taxonomy of pipeline/external.py (first category that matches) and a severity:
    3 court order / termination / NGT, 2 a negative verb (stalled, halted, protest, stay, ban ...), else 1 (a mention).
A linked item of severity >= 2 raises a 'signal' alert. Each searched project gets a scouted row, so an empty result
reads "searched, nothing found" only for projects that were searched ("unknown is not clear").
"""
import hashlib
import html
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from backend import db, serving
from pipeline.external import TAXONOMY, category_regex

GOOGLE_NEWS = "https://news.google.com/rss/search"
PIB_RSS = os.environ.get("PIB_RSS", "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3")
USER_AGENT = "PAIMANA-early-warning/2.0 (MoSPI IPMD project monitoring prototype; news scout)"
TIMEOUT_S, REQ_GAP_S = 10, 1.0
MAX_PROJECTS = 50
DF_MAX = 8
LINK_MIN, LINK_MARGIN = 0.5, 0.1
NON_LATIN_MAX = 0.3
HEAT_DAYS = 90
CATEGORY_RX = {c: re.compile(category_regex(c), re.I) for c in TAXONOMY}
SEVERE = re.compile(r"\b(?:high|supreme|apex)\s+court\b|\bcourt\s+(?:order\w*|direct\w*|stay\w*|quash\w*|halt\w*)"
                    r"|terminat\w*|(?-i:\bNGT\b)|green\s+tribunal|blacklist\w*"
                    r"|cancel\w*\s+(?:the\s+)?(?:contract|tender|project|work)", re.I)
NEGATIVE = re.compile(r"\bstall\w*|\bhalt\w*|protest\w*|\bstay(?:s|ed)?\b|\bstopp\w*|\bstops?\b|suspend\w*|delay\w*"
                      r"|agitat\w*|blockade|dharna|obstruct\w*|\bstuck\b|abandon\w*|\bscrap\w*|standstill"
                      r"|deadline\w*\s+(?:missed|extended)|miss\w*\s+(?:the\s+)?deadline|shortage|dispute\w*"
                      r"|encroach\w*|collaps\w*|\bban(?:s|ned)?\b", re.I)
OBJECTS = ["expressway", "ring road", "bypass", "flyover", "tunnel", "bridge", "airport", "terminal", "metro", "port",
           "railway line", "new line", "doubling", "dam", "canal", "hydro", "power project", "transmission",
           "pipeline", "refinery", "hospital", "aiims", "medical college", "highway", "road"]
# generic words that can still be rare in one portfolio (DF_MAX catches the common ones)
STOP = {"outer", "inner", "left", "over", "flexible", "rigid", "bypasses", "additional", "structures", "balance",
        "existing", "configuration", "village", "villages", "border", "town", "city", "district", "junction",
        "stretch", "design", "chainage", "length", "total", "near", "including", "remaining", "missing", "link",
        "spur", "greenfield", "brownfield", "strengthenlng", "widenning", "upgradtion", "hybrid", "annuity"}
OBJECT_RX = {o: re.compile(rf"\b{o}s?\b", re.I) for o in OBJECTS}
GENERIC_OBJECTS = {"road", "highway"}   # searched for, but too common in news to count as link context
NH_RX = re.compile(r"\bNH[\s-]*(\d{1,3}[A-Z]{0,2})\b", re.I)
WORD_RX = re.compile(r"[a-z]{4,}")
NO_STATE = {None, "", "Multi-State", "PAN India", "Offshore"}
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def tokens(text: str) -> set[str]:
    """Lower-case words of 4+ letters and NH numbers ('nh58') of a name or a news text."""
    return set(WORD_RX.findall(text.lower())) | {f"nh{m.lower()}" for m in NH_RX.findall(text)}


# ------------------------------------------------------------ portfolio index

def build_index(rows: list[dict]) -> dict:
    """Project rows (project_key, project_name, state, agency, tier, p_any_2q) -> per key the row with its place
    words, NH numbers, object and agency short name, and the keys per place word."""
    df = Counter(t for r in rows for t in tokens(r["project_name"] or ""))
    projects, by_token = {}, {}
    for r in rows:
        name, agency = r["project_name"] or "", r.get("agency") or ""
        state_words = set(WORD_RX.findall((r["state"] or "").lower()))
        distinct = {t for t in tokens(name) if df[t] <= DF_MAX} - state_words - STOP
        short = re.search(r"\[(\w+)\]", agency)
        projects[r["project_key"]] = {
            **r, "places": {t for t in distinct if not NH_RX.fullmatch(t)},
            "nh": {t for t in tokens(name) if NH_RX.fullmatch(t)},
            "object": next((o for o, rx in OBJECT_RX.items() if rx.search(name)), None),
            "agency_short": short.group(1) if short else agency if re.fullmatch(r"[A-Za-z]{2,8}", agency) else None}
        for t in projects[r["project_key"]]["places"]:
            by_token.setdefault(t, []).append(r["project_key"])
    return {"projects": projects, "by_token": by_token}


@serving.cached
def index(s) -> dict:
    """build_index over the current portfolio."""
    return build_index(serving._rows(s, """SELECT project_key, project_name, state, agency, sector, tier, p_any_2q
        FROM cur ORDER BY project_key"""))


def aliases(p: dict) -> list[str]:
    """3-5 search strings for one build_index project: its place words in name order (so no km ranges, package
    numbers or 'construction of'), each time with a second anchor: the object (bypass, airport ...), the NH number,
    the agency's short name, or the state when there are two place words (one city word and the state alone
    fetch the city's general news)."""
    name, obj, agency = p["project_name"] or "", p["object"], p["agency_short"]
    places = [w.title() for w in dict.fromkeys(WORD_RX.findall(name.lower())) if w in p["places"]][:3]
    nh = next((f"NH {m.upper()}" for m in NH_RX.findall(name)), None)
    state = p.get("state") if p.get("state") not in NO_STATE else None
    head = " ".join(places[:2])
    qs = [f"{head} {obj}" if obj else None, f"{' '.join(places)} {state}" if state and len(places) > 1 else None,
          f"{nh} {places[0]}" if nh and places else None,
          f"{agency} {head} {obj if obj and obj not in GENERIC_OBJECTS else ''}" if agency else None]
    if len(places) > 2:
        qs.append(f"{places[0]} {places[2]} {obj or ''}")
    qs = [re.sub(r"\s+", " ", q).strip() for q in qs if q and head]
    if len(set(qs)) < 3:  # few place words: the cleaned name start is a better query than nothing
        clean = re.sub(r"\([^)]*\)|\b(?:km|ch)\b[\s.]*[\d./,]+|\d[\d.,/]*|\b(?:pkg|package|phase)\b[\s-]*\w*", " ",
                       name, flags=re.I)
        qs += [" ".join(clean.split()[:6]), f"{' '.join(clean.split()[:4])} {state or ''}".strip()]
    return list(dict.fromkeys(q for q in qs if len(q) > 3))[:5]


def link(text: str, idx: dict) -> tuple[str | None, float, str]:
    """(project_key or None, best score, 'linked' | 'ambiguous' | 'none') for one news text, and whether the
    context anchor was found (see the module docstring)."""
    t = tokens(text)
    scores = []
    for key in {k for w in t for k in idx["by_token"].get(w, ())}:
        p = idx["projects"][key]
        scores.append((0.5 * min(1.0, len(p["places"] & t) / 2) + 0.5 * _context(p, text, t), key))
    scores.sort(reverse=True)
    if not scores or scores[0][0] < LINK_MIN:
        return None, scores[0][0] if scores else 0.0, "none"
    best, key = scores[0]
    if len(scores) > 1 and scores[1][0] >= best - LINK_MARGIN:
        return None, best, "ambiguous"
    return key, best, "linked"


def _context(p: dict, text: str, t: set) -> bool:
    """The text names the project's NH number, its object (not a plain road / highway) or its agency."""
    obj, agency = p["object"], p["agency_short"]
    return bool(p["nh"] & t or (obj and obj not in GENERIC_OBJECTS and OBJECT_RX[obj].search(text))
                or (agency and re.search(rf"\b{re.escape(agency)}\b", text)))


def classify(text: str) -> tuple[str | None, int]:
    """(taxonomy category or None, severity 1-3)."""
    category = next((c for c, rx in CATEGORY_RX.items() if rx.search(text)), None)
    return category, 3 if SEVERE.search(text) else 2 if NEGATIVE.search(text) else 1


# ------------------------------------------------------------ fetch, parse

def _date(s: str | None) -> str | None:
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc).isoformat(timespec="seconds") if s else None
    except (TypeError, ValueError):
        return None


def _non_latin(s: str) -> float:
    letters = [ch for ch in s if ch.isalpha()]
    return sum(ord(ch) > 0x24F for ch in letters) / max(len(letters), 1)


def parse_rss(xml: str, feed: str) -> list[dict]:
    """RSS 2.0 items -> {url, title, summary, source, published_at}; the ' - Source' tail Google News adds to a
    title is cut (it is in source)."""
    out = []
    for it in ET.fromstring(xml).iter("item"):
        title, url = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
        if not title or not url:
            continue
        source = (it.findtext("source") or "").strip() or feed
        if title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        summary = html.unescape(re.sub(r"<[^>]+>", " ", it.findtext("description") or ""))
        summary = " ".join(summary.split())
        if summary.endswith(source):  # Google News repeats title and source in the description
            summary = summary[: -len(source)].strip()
        out.append({"url": url, "title": title, "summary": "" if summary == title else summary[:1000],
                    "source": source, "published_at": _date(it.findtext("pubDate"))})
    return out


def _getter(client: httpx.Client):
    """client.get at most once per REQ_GAP_S seconds."""
    last = [0.0]

    def get(url, params=None) -> str:
        time.sleep(max(0.0, REQ_GAP_S - (time.monotonic() - last[0])))
        last[0] = time.monotonic()
        r = client.get(url, params=params)
        r.raise_for_status()
        return r.text
    return get


def google_news(get, query: str) -> list[dict]:
    return parse_rss(get(GOOGLE_NEWS, {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}), "Google News")


# ------------------------------------------------------------ store

def store(items: list[dict], idx: dict) -> dict:
    """Dedupe, link, classify and store items; returns counts and raises 'signal' alerts."""
    counts, alerts, fetched_at = Counter(), [], _now().isoformat(timespec="seconds")
    with closing(db.connect()) as con, con:
        for it in items:
            if _non_latin(it["title"]) > NON_LATIN_MAX:
                counts["regional_skipped"] += 1
                continue
            text = f"{it['title']} {it['summary']}"
            url_hash, text_hash = _hash(it["url"]), _hash(" ".join(text.lower().split()))
            if con.execute("SELECT 1 FROM signals WHERE url_hash = ? OR text_hash = ?", [url_hash, text_hash]).fetchone():
                counts["duplicate"] += 1
                continue
            key, score, how = link(text, idx)
            counts[how] += 1
            if how == "none":
                continue
            category, severity = classify(text)
            sid = con.execute("""INSERT INTO signals (url, url_hash, title, source, published_at, fetched_at, summary,
                category, severity, text_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                              [it["url"], url_hash, it["title"], it["source"], it["published_at"], fetched_at,
                               it["summary"], category, severity, text_hash]).lastrowid
            counts["stored"] += 1
            if key is None:
                continue
            proj = idx["projects"][key]
            method = "places+context" if _context(proj, text, tokens(text)) else "places"
            con.execute("INSERT INTO signal_projects (signal_id, project_key, link_score, method) VALUES (?, ?, ?, ?)",
                        [sid, key, score, method])
            if severity >= 2:
                alerts.append({"project_key": key, "kind": "signal", "severity": severity,
                               "title": f"News ({category or 'mention'}): {proj['project_name']}",
                               "detail": f"{it['title']} ({it['source']}, {(it['published_at'] or '')[:10]})",
                               "asof": str(serving.state()["asof"]), "model_version": serving.state()["model_version"],
                               "source": it["url"]})
    db.add_alerts(alerts)
    return {**counts, "alerts": len(alerts)}


def run(keys: list[str], pib: bool = True, get=None) -> dict:
    """Scout these projects (and the PIB feed); one run at a time, a call while one runs returns busy."""
    if not _lock.acquire(blocking=False):
        return {"busy": True}
    started, t0 = _now().isoformat(timespec="seconds"), time.time()
    try:
        idx = index()
        counts, errors, items, done = Counter(), [], [], []
        with httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            get = get or _getter(client)
            if pib:
                try:
                    items += parse_rss(get(PIB_RSS), "PIB")
                    counts["pib_items"] = len(items)
                except (httpx.HTTPError, ET.ParseError) as e:
                    errors.append(f"PIB: {type(e).__name__}: {e}"[:300])
            for key in keys:
                p = idx["projects"].get(key)
                if p is None:
                    continue
                n, searched = 0, 0
                for q in aliases(p):
                    try:
                        got = google_news(get, q)
                    except (httpx.HTTPError, ET.ParseError) as e:
                        errors.append(f"{key} '{q}': {type(e).__name__}: {e}"[:300])
                        continue
                    counts["queries"] += 1
                    searched += 1
                    n += len(got)
                    items += got
                if searched:  # a project whose every query failed stays "not searched"
                    done.append((key, n))
        counts["items"] = len(items)
        out = {**counts, **store(items, idx), "projects": len(done), "errors": errors[:20],
               "seconds": round(time.time() - t0, 1)}
        with closing(db.connect()) as con, con:
            now = _now().isoformat(timespec="seconds")
            con.executemany("INSERT OR REPLACE INTO scouted (project_key, scouted_at, n_items) VALUES (?, ?, ?)",
                            [(k, now, n) for k, n in done])
        ok = counts["queries"] > 0 or (not keys and counts["pib_items"])
        db.record_job("scout", started, "ok" if ok else "error", out)
        return out
    finally:
        _lock.release()


def busy() -> bool:
    return _lock.locked()


def batch_keys(n: int = MAX_PROJECTS) -> list[str]:
    """Watchlisted projects first, then Critical and High, the least recently scouted (never first) and riskiest."""
    idx = index()["projects"]
    with closing(db.connect()) as con:
        watched = [r[0] for r in con.execute("SELECT project_key FROM watchlist GROUP BY 1 ORDER BY min(added_at)")]
        last = dict(con.execute("SELECT project_key, scouted_at FROM scouted").fetchall())
    risky = sorted((k for k, p in idx.items() if p["tier"] in ("Critical", "High")),
                   key=lambda k: (last.get(k) or "", -(idx[k]["p_any_2q"] or 0)))
    return list(dict.fromkeys(k for k in watched + risky if k in idx))[:n]


def batch() -> dict:
    return run(batch_keys())


# ------------------------------------------------------------ read side

@serving.cached
def cuf_changes(s, key: str) -> list[date]:
    """Periods at which the key's CUF row changed: anticipated completion pushed >= DATE_STEP months or anticipated
    cost up >= COST_STEP x against its previous observation on the same basis (the label rule of pipeline/gold.py)."""
    from pipeline.gold import COST_STEP, DATE_STEP
    return [r["period"] for r in serving._rows(s, f"""
        SELECT period FROM (
            SELECT period,
                   date_diff('month', lag(anticipated_completion) OVER w, anticipated_completion) >= {DATE_STEP}
                       AND completion_basis = lag(completion_basis) OVER w AS pushed,
                   anticipated_cost_cr >= {COST_STEP} * lag(anticipated_cost_cr) OVER w
                       AND cost_basis = lag(cost_basis) OVER w AS revised
            FROM obs WHERE project_key = ? WINDOW w AS (ORDER BY period))
        WHERE pushed OR revised ORDER BY period""", [key])]


def lead_time(key: str, published_at: str | None) -> dict:
    """The first report period after the signal date whose CUF row changed, and the gap in days (None: no change
    since, or no date). A positive gap is the lead time the news gave over the report."""
    pub = date.fromisoformat(published_at[:10]) if published_at else None
    change = next((p for p in cuf_changes(key) if pub and p > pub), None)
    return {"cuf_change_period": change, "lead_days": (change - pub).days if change else None}


def feed(since=None, category=None, state=None, severity=None, linked=None, page=1, size=50) -> dict:
    """One page of stored signals, newest first, each with its linked projects and their lead time."""
    idx = index()["projects"]
    conds, params = [], []
    for sql, v in (("s.published_at >= ?", since), ("s.category = ?", category), ("s.severity >= ?", severity)):
        if v is not None:
            conds.append(sql)
            params.append(v)
    if state:
        keys = [k for k, p in idx.items() if p["state"] == state]
        conds.append(f"s.id IN (SELECT signal_id FROM signal_projects WHERE project_key IN ({','.join('?' * len(keys))}))"
                     if keys else "0")
        params += keys
    if linked is not None:
        conds.append(("" if linked else "NOT ") + "EXISTS (SELECT 1 FROM signal_projects sp WHERE sp.signal_id = s.id)")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with closing(db.connect()) as con:
        total = con.execute(f"SELECT count(*) FROM signals s{where}", params).fetchone()[0]
        rows = [dict(r) for r in con.execute(f"""SELECT s.* FROM signals s{where}
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC LIMIT ? OFFSET ?""", params + [size, (page - 1) * size])]
        links = {}
        for r in con.execute(f"""SELECT * FROM signal_projects WHERE signal_id IN ({','.join('?' * len(rows))})""",
                             [r["id"] for r in rows]):
            links.setdefault(r["signal_id"], []).append(dict(r))
    for r in rows:
        r["projects"] = [{"key": ln["project_key"], "name": idx.get(ln["project_key"], {}).get("project_name"),
                          "state": idx.get(ln["project_key"], {}).get("state"),
                          "tier": idx.get(ln["project_key"], {}).get("tier"), "link_score": ln["link_score"],
                          "method": ln["method"], **lead_time(ln["project_key"], r["published_at"])}
                         for ln in links.get(r["id"], [])]
    return {"total": total, "page": page, "size": size, "items": rows, "state_heat": heat()}


def heat(days: int = HEAT_DAYS) -> list[dict]:
    """Signals of severity >= 2 in the last `days` days per state of their linked projects."""
    idx = index()["projects"]
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    with closing(db.connect()) as con:
        pairs = con.execute("""SELECT DISTINCT sp.signal_id, sp.project_key FROM signal_projects sp
            JOIN signals s ON s.id = sp.signal_id WHERE s.severity >= 2 AND s.published_at >= ?""", [since]).fetchall()
    n = Counter(st for _, st in {(sid, idx[k]["state"]) for sid, k in pairs if k in idx})
    return [{"state": s, "n": c} for s, c in n.most_common()]


def radar_summary(days: int = HEAT_DAYS) -> dict:
    """Radar rollup: stored signals published in the last `days` days by category, severity and source, linked vs
    unlinked; lead time over every linked signal (a positive gap: the news came before the CUF row changed)."""
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    linked_sql = "EXISTS (SELECT 1 FROM signal_projects sp WHERE sp.signal_id = s.id)"
    with closing(db.connect()) as con:
        def counts(col, limit=20):
            return [{"name": r[0], "n": r[1]} for r in con.execute(
                f"""SELECT {col}, count(*) FROM signals s WHERE s.published_at >= ? GROUP BY 1
                    ORDER BY 2 DESC, 1 LIMIT {limit}""", [since])]
        total = con.execute("SELECT count(*) FROM signals").fetchone()[0]
        n_window, n_linked = con.execute(f"""SELECT count(*), count(*) FILTER (WHERE {linked_sql}) FROM signals s
            WHERE s.published_at >= ?""", [since]).fetchone()
        by_category, by_severity, by_source = counts("coalesce(s.category, 'none')"), counts("s.severity"), counts(
            "s.source", 10)
        pairs = con.execute("""SELECT sp.project_key, s.published_at FROM signal_projects sp
            JOIN signals s ON s.id = sp.signal_id""").fetchall()
        scouted = con.execute("SELECT count(*) FROM scouted").fetchone()[0]
    gaps = [g for g in (lead_time(k, pub)["lead_days"] for k, pub in pairs) if g is not None]
    gaps.sort()
    return {"window_days": days, "since": since, "n_signals_total": total, "n_window": n_window,
            "n_linked": n_linked, "n_unlinked": n_window - n_linked, "by_category": by_category,
            "by_severity": by_severity, "by_source": by_source, "n_projects_scouted": scouted,
            "lead_time": {"n_linked_pairs": len(pairs), "n_with_later_change": len(gaps),
                          "median_lead_days": gaps[len(gaps) // 2] if gaps else None,
                          "basis": "every linked signal: the first report period after its date whose CUF row "
                                   "pushed completion or revised cost"}}
