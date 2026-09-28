"""App state in SQLite: alerts, watchlist, signals, job runs, ingested sources, briefs, research facts, second
opinions, audit log.

database/paimana.db, or the path in PAIMANA_DB. One short connection per call
(single backend process); the analytics side stays in backend/serving.py.
Every write that comes from a person also writes an audit_log row in the same
transaction.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import serving

DEFAULT_PATH = serving.ROOT / "database" / "paimana.db"
# a viewer's project keys (backend/access.py) as one JSON parameter: json.dumps(sorted(keys))
IN_KEYS = "project_key IN (SELECT value FROM json_each(?))"
ALERT_KINDS = ("tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice", "pipeline_error")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sources (
    sha256 TEXT NOT NULL, pipeline_version TEXT NOT NULL, filename TEXT, kind TEXT, period TEXT, rows INTEGER,
    ingested_at TEXT, status TEXT, error TEXT, archived_as TEXT, PRIMARY KEY (sha256, pipeline_version));
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, started_at TEXT, finished_at TEXT, status TEXT,
    summary_json TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, project_key TEXT,
    kind TEXT NOT NULL CHECK (kind IN {ALERT_KINDS}), severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 3),
    title TEXT, detail TEXT, asof TEXT, model_version TEXT, source TEXT, acked_by TEXT, acked_at TEXT);
CREATE INDEX IF NOT EXISTS alerts_created ON alerts (created_at);
CREATE INDEX IF NOT EXISTS alerts_project ON alerts (project_key);
CREATE TABLE IF NOT EXISTS watchlist (
    role TEXT NOT NULL, project_key TEXT NOT NULL, added_at TEXT, PRIMARY KEY (role, project_key));
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, url_hash TEXT, title TEXT, source TEXT,
    published_at TEXT, fetched_at TEXT, summary TEXT, category TEXT, severity INTEGER, text_hash TEXT);
CREATE INDEX IF NOT EXISTS signals_text ON signals (text_hash);
CREATE INDEX IF NOT EXISTS signals_published ON signals (published_at);
CREATE TABLE IF NOT EXISTS signal_projects (
    signal_id INTEGER NOT NULL REFERENCES signals (id), project_key TEXT NOT NULL, link_score REAL, method TEXT,
    PRIMARY KEY (signal_id, project_key));
CREATE INDEX IF NOT EXISTS signal_projects_key ON signal_projects (project_key);
CREATE TABLE IF NOT EXISTS scouted (project_key TEXT PRIMARY KEY, scouted_at TEXT NOT NULL, n_items INTEGER);
CREATE TABLE IF NOT EXISTS audit_log (at TEXT NOT NULL, role TEXT, action TEXT NOT NULL, target TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS briefs (
    project_key TEXT NOT NULL, asof TEXT NOT NULL, model_version TEXT NOT NULL, generated_at TEXT, text TEXT,
    n_numbers_checked INTEGER, attempts INTEGER, PRIMARY KEY (project_key, asof, model_version));
-- the in-app research agent (backend/live/research.py): its facts (the gold research_facts columns, origin 'agent',
-- dates as text) and when it last researched each project (its rotation)
CREATE TABLE IF NOT EXISTS research_facts (
    fact_id TEXT PRIMARY KEY, project_key TEXT NOT NULL, category TEXT, taxonomy TEXT, direction TEXT,
    severity INTEGER, event_date TEXT, date_precision TEXT, published_date TEXT, status TEXT, summary TEXT,
    headline TEXT, source TEXT, url TEXT, domain TEXT, match TEXT, match_reason TEXT, origin TEXT NOT NULL DEFAULT
    'agent', researched_on TEXT, live INTEGER, signal_id INTEGER REFERENCES signals (id), model TEXT,
    prompt_version TEXT, judged_at TEXT);
CREATE INDEX IF NOT EXISTS research_facts_key ON research_facts (project_key);
CREATE TABLE IF NOT EXISTS researched (
    project_key TEXT PRIMARY KEY, researched_at TEXT NOT NULL, n_candidates INTEGER, n_relevant INTEGER);
-- every verdict of the research agent on a news item for a project (relevant NULL: the verdict was rejected)
CREATE TABLE IF NOT EXISTS signal_judgements (
    signal_id INTEGER NOT NULL REFERENCES signals (id), project_key TEXT NOT NULL, relevant INTEGER,
    verdict_json TEXT, model TEXT, prompt_version TEXT, judged_at TEXT, PRIMARY KEY (signal_id, project_key));
-- the LLM second opinion (llm/second_opinion.py) per evidence version: json holds the status (ok | rejected), the
-- opinion or the reasons, the tier and model version it was set against and the evidence items it read, and on an
-- accepted one last_rejected when a newer prompt's reply for the same evidence was rejected
CREATE TABLE IF NOT EXISTS second_opinions (
    project_key TEXT NOT NULL, evidence_hash TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT, asof TEXT,
    generated_at TEXT, json TEXT, PRIMARY KEY (project_key, evidence_hash, model));
"""
SECOND_OPINION_COLS = ("project_key", "evidence_hash", "model", "prompt_version", "asof", "generated_at")
RESEARCH_FACT_COLS = ("fact_id", "project_key", "category", "taxonomy", "direction", "severity", "event_date",
                      "date_precision", "published_date", "status", "summary", "headline", "source", "url", "domain",
                      "match", "match_reason", "origin", "researched_on", "live", "signal_id", "model",
                      "prompt_version", "judged_at")


def path() -> Path:
    return Path(os.environ.get("PAIMANA_DB") or DEFAULT_PATH)


def connect() -> sqlite3.Connection:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _audit(con, role, action, target, detail=None):
    con.execute("INSERT INTO audit_log (at, role, action, target, detail) VALUES (?, ?, ?, ?, ?)",
                [_now(), role, action, target, detail])


def init() -> int:
    """Create the tables if missing and seed the alert feed; returns the number of alerts seeded."""
    with closing(connect()) as con:
        _migrate(con)
        con.executescript(SCHEMA)
    return seed()


def _migrate(con) -> None:
    """Bring a database made before the report watcher up to SCHEMA. sources gains pipeline_version (nothing wrote
    it before, so it is recreated); alerts gains the pipeline_error kind and project-less alerts (a CHECK and a NOT
    NULL cannot be altered in SQLite, so the table is rebuilt with its rows)."""
    if "pipeline_version" not in {r[1] for r in con.execute("PRAGMA table_info(sources)")}:
        con.execute("DROP TABLE IF EXISTS sources")
    old = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'alerts'").fetchone()
    if old and "pipeline_error" not in old[0]:
        con.executescript("BEGIN; ALTER TABLE alerts RENAME TO alerts_old; DROP INDEX IF EXISTS alerts_created; "
                          "DROP INDEX IF EXISTS alerts_project;" + SCHEMA
                          + "INSERT INTO alerts SELECT * FROM alerts_old; DROP TABLE alerts_old; COMMIT;")


# ---------------------------------------------------------------- alerts

def seed() -> int:
    """Seed an empty alert feed from the current scores: one early_notice alert per early-notice project and
    one tier_up per Critical project, source 'seed:<asof>'. Does nothing once the feed has any alert."""
    m = serving.meta()
    asof, mv, source = str(m["asof"]), m["model_version"], f"seed:{m['asof']}"
    with closing(connect()) as con, con:
        con.execute("BEGIN IMMEDIATE")  # check-then-insert in one write lock, so two starts cannot both seed
        if con.execute("SELECT 1 FROM alerts LIMIT 1").fetchone():
            return 0
        started, rows = _now(), []
        for r in serving.early_notice():
            factors = [f for f in r["flags"] if f != "early_notice"] + [
                n for n in ("utility_shifting", "inter_agency") if r[f"ext_open_{n}"] == 1]
            detail = "; ".join(r["evidence"] or []) or "open " + " / ".join(factors) + " event in the report remarks"
            rows.append((started, r["project_key"], "early_notice", 2,
                         f"Early notice: {', '.join(factors)} on {r['project_name']}",
                         f"{detail}. CUF numbers show no slip yet (tier {r['tier'] or 'untiered'}).",
                         asof, mv, source))
        for r in serving.in_tier("Critical"):
            rows.append((started, r["project_key"], "tier_up", 3, f"Critical: {r['project_name']}",
                         f"entered Critical at asof {asof}; P(date push or cost revision, 2q) = {r['p_any_2q']:.2f}",
                         asof, mv, source))
        con.executemany("""INSERT INTO alerts (created_at, project_key, kind, severity, title, detail, asof,
            model_version, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
        con.execute("""INSERT INTO job_runs (job, started_at, finished_at, status, summary_json)
            VALUES ('seed_alerts', ?, ?, 'ok', ?)""",
                    [started, _now(), json.dumps({"asof": asof, "model_version": mv, "alerts": len(rows)})])
    return len(rows)


def add_alerts(rows: list[dict]) -> int:
    """Insert alerts (project_key, kind, severity, title, detail, asof, model_version, source); returns the count."""
    cols = ("project_key", "kind", "severity", "title", "detail", "asof", "model_version", "source")
    with closing(connect()) as con, con:
        con.executemany(f"INSERT INTO alerts (created_at, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
                        [[_now()] + [r.get(c) for c in cols] for r in rows])
    return len(rows)


def alerts(since=None, kind=None, acked=None, page=1, size=50, keys=None) -> dict:
    """keys: only alerts on these projects (None: every alert; project-less pipeline errors are in no scope)."""
    conds, params = [], []
    if keys is not None:
        conds.append(IN_KEYS)
        params.append(json.dumps(sorted(keys)))
    if since:
        conds.append("created_at >= ?")
        params.append(since)
    if kind:
        conds.append("kind = ?")
        params.append(kind)
    if acked is not None:
        conds.append("acked_at IS NOT NULL" if acked else "acked_at IS NULL")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with closing(connect()) as con:
        total = con.execute(f"SELECT count(*) FROM alerts{where}", params).fetchone()[0]
        items = [dict(r) for r in con.execute(
            f"SELECT * FROM alerts{where} ORDER BY created_at DESC, severity DESC, id LIMIT ? OFFSET ?",
            params + [size, (page - 1) * size])]
    return {"total": total, "page": page, "size": size, "items": items}


def max_alert_id() -> int:
    with closing(connect()) as con:
        return con.execute("SELECT coalesce(max(id), 0) FROM alerts").fetchone()[0]


def alerts_after(alert_id: int, limit=100) -> list[dict]:
    """Alerts with an id above alert_id, oldest first (the live stream)."""
    with closing(connect()) as con:
        return [dict(r) for r in con.execute("SELECT * FROM alerts WHERE id > ? ORDER BY id LIMIT ?", [alert_id, limit])]


def ack(alert_id: int, role: str, keys=None) -> dict | None:
    """Mark an alert acknowledged by role (the first ack stands); None if there is no such alert (or it is not on
    one of keys, when given)."""
    with closing(connect()) as con, con:
        row = con.execute("SELECT * FROM alerts WHERE id = ?", [alert_id]).fetchone()
        if row is None or (keys is not None and row["project_key"] not in keys):
            return None
        if row["acked_at"] is None:
            con.execute("UPDATE alerts SET acked_by = ?, acked_at = ? WHERE id = ?", [role, _now(), alert_id])
            _audit(con, role, "alert.ack", str(alert_id))
        else:
            _audit(con, role, "alert.ack", str(alert_id), f"already acked by {row['acked_by']}")
        return dict(con.execute("SELECT * FROM alerts WHERE id = ?", [alert_id]).fetchone())


# ------------------------------------------------------------- watchlist

def watchlist(role: str, limit=100) -> dict:
    with closing(connect()) as con:
        total = con.execute("SELECT count(*) FROM watchlist WHERE role = ?", [role]).fetchone()[0]
        items = [dict(r) for r in con.execute(
            "SELECT * FROM watchlist WHERE role = ? ORDER BY added_at DESC, project_key LIMIT ?", [role, limit])]
    rows = {r["key"]: r for r in serving.rows_for_keys(tuple(i["project_key"] for i in items))}
    return {"total": total, "items": [{**i, "project": rows.get(i["project_key"])} for i in items]}


def watch(role: str, project_key: str) -> bool:
    """Add to role's watchlist; False if it was already there."""
    with closing(connect()) as con, con:
        added = con.execute("INSERT OR IGNORE INTO watchlist (role, project_key, added_at) VALUES (?, ?, ?)",
                            [role, project_key, _now()]).rowcount == 1
        _audit(con, role, "watchlist.add", project_key, None if added else "already on the watchlist")
    return added


def unwatch(role: str, project_key: str) -> bool:
    """Remove from role's watchlist; False if it was not there."""
    with closing(connect()) as con, con:
        removed = con.execute("DELETE FROM watchlist WHERE role = ? AND project_key = ?",
                              [role, project_key]).rowcount == 1
        _audit(con, role, "watchlist.remove", project_key, None if removed else "was not on the watchlist")
    return removed


# ------------------------------------------------------- jobs, signals, log

def latest_jobs() -> list[dict]:
    with closing(connect()) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM job_runs WHERE id IN (SELECT max(id) FROM job_runs GROUP BY job) ORDER BY job")]
    for r in rows:
        r["summary"] = json.loads(r.pop("summary_json") or "null")
    return rows


def record_job(job: str, started_at: str, status: str, summary: dict) -> None:
    with closing(connect()) as con, con:
        con.execute("""INSERT INTO job_runs (job, started_at, finished_at, status, summary_json)
            VALUES (?, ?, ?, ?, ?)""", [job, started_at, _now(), status, json.dumps(summary, default=str)])


def source_seen(sha256: str, pipeline_version: str) -> bool:
    with closing(connect()) as con:
        return con.execute("SELECT 1 FROM sources WHERE sha256 = ? AND pipeline_version = ?",
                           [sha256, pipeline_version]).fetchone() is not None


def record_source(row: dict) -> None:
    """One ingested file (see backend/live/watcher.py); a re-run under the same pipeline version replaces it."""
    cols = ("sha256", "pipeline_version", "filename", "kind", "period", "rows", "status", "error", "archived_as")
    with closing(connect()) as con, con:
        con.execute(f"INSERT OR REPLACE INTO sources (ingested_at, {', '.join(cols)}) VALUES (?{', ?' * len(cols)})",
                    [_now()] + [row.get(c) for c in cols])


def project_signals(project_key: str, limit=100) -> dict:
    """Linked signals for one project, newest first, and when the scout last searched it (None: never)."""
    with closing(connect()) as con:
        items = [dict(r) for r in con.execute("""
            SELECT s.*, sp.link_score, sp.method FROM signal_projects sp JOIN signals s ON s.id = sp.signal_id
            WHERE sp.project_key = ? ORDER BY s.published_at DESC, s.id DESC LIMIT ?""", [project_key, limit])]
        last = con.execute("SELECT scouted_at FROM scouted WHERE project_key = ?", [project_key]).fetchone()
    return {"key": project_key, "last_scout_at": last and last[0], "items": items}


def _read(sql: str, params: list) -> list[sqlite3.Row]:
    """Rows of a read that finds nothing, rather than failing, when db.init() has not made the table yet (serving
    used from a script outside the backend)."""
    with closing(connect()) as con:
        try:
            return con.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            if "no such table" not in str(e):
                raise
            return []


def research_facts(project_key: str | None = None, keys=None) -> list[dict]:
    """The research agent's facts of one project, or of keys (None: every project), newest judged first."""
    conds, params = [], []
    if project_key is not None:
        conds.append("project_key = ?")
        params.append(project_key)
    if keys is not None:
        conds.append(IN_KEYS)
        params.append(json.dumps(sorted(keys)))
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return [dict(r) for r in _read(f"SELECT * FROM research_facts{where} ORDER BY judged_at DESC, fact_id", params)]


def researched(project_key: str | None = None) -> dict[str, str]:
    """project_key -> when the research agent last researched it (one project, or every one)."""
    sql, params = ("SELECT project_key, researched_at FROM researched", [])
    if project_key is not None:
        sql, params = sql + " WHERE project_key = ?", [project_key]
    return {r[0]: r[1] for r in _read(sql, params)}


def research_candidates(project_key: str, limit: int) -> tuple[list[dict], list[dict]]:
    """News items the research agent has not judged for this project: (up to limit linked to it, every one linked to
    no project, the unlinked pool), newest first."""
    unjudged = "NOT EXISTS (SELECT 1 FROM signal_judgements j WHERE j.signal_id = s.id AND j.project_key = ?)"
    with closing(connect()) as con:
        linked = [dict(r) for r in con.execute(f"""SELECT s.*, sp.method FROM signals s
            JOIN signal_projects sp ON sp.signal_id = s.id AND sp.project_key = ? WHERE {unjudged}
            ORDER BY s.published_at DESC, s.id DESC LIMIT ?""", [project_key, project_key, limit])]
        pool = [dict(r) for r in con.execute(f"""SELECT s.* FROM signals s
            WHERE NOT EXISTS (SELECT 1 FROM signal_projects sp WHERE sp.signal_id = s.id) AND {unjudged}
            ORDER BY s.published_at DESC, s.id DESC""", [project_key])]
    return linked, pool


def save_research(project_key: str, judgements: list[dict], facts: list[dict], links: list[int]) -> list[str]:
    """One batch of research verdicts in one transaction: every judgement, the relevant facts (a fact_id already
    stored is kept as it is) and a signal_projects row (method 'llm') for each newly linked pool item. Returns the
    fact_ids that are new."""
    jcols = ("signal_id", "project_key", "relevant", "verdict_json", "model", "prompt_version", "judged_at")
    with closing(connect()) as con, con:
        con.executemany(f"INSERT OR REPLACE INTO signal_judgements ({', '.join(jcols)}) VALUES "
                        f"({', '.join('?' * len(jcols))})", [[j.get(c) for c in jcols] for j in judgements])
        new = [f["fact_id"] for f in facts if con.execute(
            f"INSERT OR IGNORE INTO research_facts ({', '.join(RESEARCH_FACT_COLS)}) VALUES "
            f"({', '.join('?' * len(RESEARCH_FACT_COLS))})", [f.get(c) for c in RESEARCH_FACT_COLS]).rowcount]
        con.executemany("INSERT OR IGNORE INTO signal_projects (signal_id, project_key, link_score, method) "
                        "VALUES (?, ?, NULL, 'llm')", [(sid, project_key) for sid in links])
    return new


def mark_researched(project_key: str, n_candidates: int, n_relevant: int) -> None:
    with closing(connect()) as con, con:
        con.execute("INSERT OR REPLACE INTO researched (project_key, researched_at, n_candidates, n_relevant) "
                    "VALUES (?, ?, ?, ?)", [project_key, _now(), n_candidates, n_relevant])


def add_alerts_once(rows: list[dict]) -> int:
    """add_alerts, skipping a row whose project already has an alert of that kind from that source (a URL)."""
    with closing(connect()) as con:
        fresh = [r for r in rows if not con.execute(
            "SELECT 1 FROM alerts WHERE project_key IS ? AND kind = ? AND source = ?",
            [r.get("project_key"), r["kind"], r.get("source")]).fetchone()]
    return add_alerts(fresh) if fresh else 0


def signal_verdicts(project_key: str) -> dict[int, int | None]:
    """signal id -> the research agent's verdict on it for this project (1 relevant, 0 not, None rejected)."""
    return {r[0]: r[1] for r in _read("SELECT signal_id, relevant FROM signal_judgements WHERE project_key = ?",
                                      [project_key])}


def _opinion(r: sqlite3.Row) -> dict:
    return {**json.loads(r["json"] or "{}"), **{c: r[c] for c in SECOND_OPINION_COLS}}


def second_opinion(project_key: str, evidence_hash: str, model: str) -> dict | None:
    """The stored second opinion (accepted or rejected) for this evidence version and LLM model, or None."""
    rows = _read("SELECT * FROM second_opinions WHERE project_key = ? AND evidence_hash = ? AND model = ?",
                 [project_key, evidence_hash, model])
    return _opinion(rows[0]) if rows else None


def second_opinions(project_key: str | None = None) -> list[dict]:
    """Every stored second opinion of one project (None: every project), newest first: the prospective log."""
    sql, params = "SELECT * FROM second_opinions", []
    if project_key is not None:
        sql, params = sql + " WHERE project_key = ?", [project_key]
    return [_opinion(r) for r in _read(sql + " ORDER BY generated_at DESC, project_key", params)]


def second_opinion_times() -> dict[str, str]:
    """project_key -> when it was last asked for a second opinion: its newest one (any evidence version, accepted or
    rejected) or a newer rejection noted on an accepted one (json last_rejected.at)."""
    return {r[0]: r[1] for r in _read(
        "SELECT project_key, max(max(coalesce(generated_at, ''), coalesce(json_extract(json, '$.last_rejected.at'), "
        "''))) FROM second_opinions GROUP BY 1", [])}


def save_second_opinion(row: dict) -> None:
    """One second opinion (the SECOND_OPINION_COLS and everything else as json); replaces the one for the same
    project, evidence version and LLM model."""
    body = {k: v for k, v in row.items() if k not in SECOND_OPINION_COLS}
    with closing(connect()) as con, con:
        con.execute(f"INSERT OR REPLACE INTO second_opinions ({', '.join(SECOND_OPINION_COLS)}, json) VALUES "
                    f"({', '.join('?' * (len(SECOND_OPINION_COLS) + 1))})",
                    [row.get(c) for c in SECOND_OPINION_COLS] + [json.dumps(body, ensure_ascii=False, default=str)])


def cached_brief(project_key: str, asof: str, model_version: str) -> dict | None:
    """An accepted brief (backend/brief.py) for this data version, or None."""
    with closing(connect()) as con:
        row = con.execute("SELECT * FROM briefs WHERE project_key = ? AND asof = ? AND model_version = ?",
                          [project_key, asof, model_version]).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["key"] = out.pop("project_key")
    return out


def save_brief(b: dict) -> None:
    with closing(connect()) as con, con:
        con.execute("""INSERT OR REPLACE INTO briefs (project_key, asof, model_version, generated_at, text,
            n_numbers_checked, attempts) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    [b["key"], b["asof"], b["model_version"], b["generated_at"], b["text"], b["n_numbers_checked"],
                     b["attempts"]])


def audit(role, action, target, detail=None) -> None:
    with closing(connect()) as con, con:
        _audit(con, role, action, target, detail)
