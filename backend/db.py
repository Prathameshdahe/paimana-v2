"""App state in SQLite: alerts, watchlist, signals, job runs, ingested sources, audit log.

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
ALERT_KINDS = ("tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sources (
    sha256 TEXT PRIMARY KEY, filename TEXT, kind TEXT, period TEXT, rows INTEGER, ingested_at TEXT,
    status TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL, started_at TEXT, finished_at TEXT, status TEXT,
    summary_json TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, project_key TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN {ALERT_KINDS}), severity INTEGER NOT NULL CHECK (severity BETWEEN 1 AND 3),
    title TEXT, detail TEXT, asof TEXT, model_version TEXT, source TEXT, acked_by TEXT, acked_at TEXT);
CREATE INDEX IF NOT EXISTS alerts_created ON alerts (created_at);
CREATE INDEX IF NOT EXISTS alerts_project ON alerts (project_key);
CREATE TABLE IF NOT EXISTS watchlist (
    role TEXT NOT NULL, project_key TEXT NOT NULL, added_at TEXT, PRIMARY KEY (role, project_key));
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE, url_hash TEXT, title TEXT, source TEXT,
    published_at TEXT, fetched_at TEXT, summary TEXT, category TEXT, severity INTEGER, text_hash TEXT);
CREATE TABLE IF NOT EXISTS signal_projects (
    signal_id INTEGER NOT NULL REFERENCES signals (id), project_key TEXT NOT NULL, link_score REAL, method TEXT,
    PRIMARY KEY (signal_id, project_key));
CREATE INDEX IF NOT EXISTS signal_projects_key ON signal_projects (project_key);
CREATE TABLE IF NOT EXISTS audit_log (at TEXT NOT NULL, role TEXT, action TEXT NOT NULL, target TEXT, detail TEXT);
"""


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
        con.executescript(SCHEMA)
    return seed()


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


def alerts(since=None, kind=None, acked=None, page=1, size=50) -> dict:
    conds, params = [], []
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


def ack(alert_id: int, role: str) -> dict | None:
    """Mark an alert acknowledged by role (the first ack stands); None if there is no such alert."""
    with closing(connect()) as con, con:
        row = con.execute("SELECT * FROM alerts WHERE id = ?", [alert_id]).fetchone()
        if row is None:
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


def project_signals(project_key: str, limit=100) -> dict:
    """Linked signals for one project, newest first, and when the scout last ran (None: never searched)."""
    with closing(connect()) as con:
        items = [dict(r) for r in con.execute("""
            SELECT s.*, sp.link_score, sp.method FROM signal_projects sp JOIN signals s ON s.id = sp.signal_id
            WHERE sp.project_key = ? ORDER BY s.published_at DESC, s.id DESC LIMIT ?""", [project_key, limit])]
        last = con.execute("SELECT max(finished_at) FROM job_runs WHERE job = 'scout' AND status = 'ok'").fetchone()[0]
    return {"key": project_key, "last_scout_at": last, "items": items}


def audit(role, action, target, detail=None) -> None:
    with closing(connect()) as con, con:
        _audit(con, role, action, target, detail)
