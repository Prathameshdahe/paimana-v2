"""The app-state helpers (schema app): the public API of `backend.db` (see the package docstring).

Rows go out as dicts through _out(): timestamptz -> ISO-8601 to the second in UTC, date -> YYYY-MM-DD, the 0/1 flags
(research_facts.live, signal_judgements.relevant) -> int, numeric -> float; parameters go in through _in(): ISO
strings of the *_at columns -> aware datetimes (a bare date is midnight UTC), of the date columns -> dates, dicts and
lists of the json columns -> jsonb text, NUL bytes out of every string (outside text can carry them; text columns
refuse them). A viewer's project keys (backend/access.py) are one array parameter:
`project_key = ANY(:keys)`. Every write that comes from a person also writes an audit_log row in the same
transaction, with the actor ({user_id, email, ip} of the signed-in person, backend/access.py Viewer.actor; ip None
when it is not an address) next to the role. The reads that serving and the pipeline make before the schema exists
(serving used from a script) return nothing rather than fail (_rows_or_none).
"""
from __future__ import annotations

import ipaddress
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from backend import serving

from . import migrate
from .engine import connect, now, read

__all__ = ["ALERT_KINDS", "SECOND_OPINION_COLS", "RESEARCH_FACT_COLS", "init", "seed", "add_alerts", "alerts",
           "max_alert_id", "alerts_after", "ack", "watchlist", "watch", "unwatch", "watched_keys", "latest_jobs",
           "record_job", "source_seen", "record_source", "source_documents", "load_runs", "project_signals",
           "signals", "save_signals",
           "known_signal_hashes", "signal_links", "scouted_at", "mark_scouted", "signal_feed", "severe_links",
           "radar_counts", "news_for_index", "linked_signals", "index_marks", "research_facts", "researched",
           "researched_rows", "research_candidates", "save_research", "mark_researched", "add_alerts_once",
           "signal_verdicts", "signal_judgements", "second_opinion", "second_opinions", "second_opinion_times",
           "save_second_opinion", "cached_brief", "save_brief", "audit", "audit_rows", "inet"]

ALERT_KINDS = ("tier_up", "tier_down", "new_project", "slip_realised", "signal", "early_notice", "pipeline_error")
SECOND_OPINION_COLS = ("project_key", "evidence_hash", "model", "prompt_version", "asof", "generated_at")
RESEARCH_FACT_COLS = ("fact_id", "project_key", "category", "taxonomy", "direction", "severity", "event_date",
                      "date_precision", "published_date", "status", "summary", "headline", "source", "url", "domain",
                      "match", "match_reason", "origin", "researched_on", "live", "signal_id", "model",
                      "prompt_version", "judged_at")
SIGNAL_COLS = ("url", "url_hash", "title", "source", "published_at", "fetched_at", "summary", "category", "severity",
               "text_hash")
JUDGEMENT_COLS = ("signal_id", "project_key", "relevant", "verdict_json", "model", "prompt_version", "judged_at")
TIMESTAMPS = {"created_at", "acked_at", "added_at", "started_at", "finished_at", "ingested_at", "published_at",
              "fetched_at", "scouted_at", "researched_at", "judged_at", "generated_at", "at", "since"}
DATES = {"asof", "event_date", "published_date", "researched_on"}
FLAGS = {"live", "relevant"}
JSON = {"summary_json", "verdict_json", "json"}


# ---------------------------------------------------------------- values in and out

def _ts(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        d = v
    elif isinstance(v, date):
        d = datetime(v.year, v.month, v.day)
    else:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _day(v) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    return date.fromisoformat(s[:10] if len(s) >= 10 else s + "-01" if len(s) == 7 else s + "-01-01")


def _json_default(o):
    return o.isoformat() if isinstance(o, (date, datetime)) else str(o)


def _json(v) -> str | None:
    """jsonb text (dates and timestamps in ISO-8601); a NUL escape is dropped (jsonb refuses it)."""
    if v is None:
        return None
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=_json_default)
    return s.replace("\\u0000", "")


def _in(row: Mapping[str, Any]) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, str) and "\x00" in v:
            v = v.replace("\x00", "")     # a NUL in outside text (a feed title): text columns refuse it
        if k in TIMESTAMPS:
            v = _ts(v)
        elif k in DATES:
            v = _day(v)
        elif k in FLAGS:
            v = None if v is None else bool(v)
        elif k in JSON:
            v = _json(v)
        elif isinstance(v, (list, tuple)):
            v = list(v)
        out[k] = v
    return out


def _out(row: Mapping[str, Any]) -> dict:
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            v = v.astimezone(timezone.utc).isoformat(timespec="seconds")
        elif isinstance(v, date):
            v = v.isoformat()
        elif isinstance(v, bool) and k in FLAGS:
            v = int(v)
        elif isinstance(v, Decimal):
            v = float(v)
        elif isinstance(v, (ipaddress.IPv4Address, ipaddress.IPv6Address, ipaddress.IPv4Interface,
                            ipaddress.IPv6Interface)):
            v = str(getattr(v, "ip", v))
        out[k] = v
    return out


def _rows(con, sql: str, params: Mapping | None = None) -> list[dict]:
    return [_out(r) for r in con.execute(sa.text(sql), params or {}).mappings()]


def _one(con, sql: str, params: Mapping | None = None) -> dict | None:
    rows = _rows(con, sql, params)
    return rows[0] if rows else None


def _rows_or_none(sql: str, params: Mapping | None = None) -> list[dict]:
    """Rows of a read that finds nothing, rather than failing, when the schema is not there yet (serving used from
    a script before db.init() migrated the database)."""
    try:
        with read() as con:
            return _rows(con, sql, params)
    except ProgrammingError as e:
        if "UndefinedTable" not in type(getattr(e, "orig", e)).__name__ and "does not exist" not in str(e):
            raise
        return []


def _keys(keys) -> list[str]:
    return sorted(keys)


def inet(v) -> str | None:
    """v when it is an IP address (the inet columns), else None: a test client's 'testclient', a missing peer."""
    try:
        return str(ipaddress.ip_address(str(v).strip())) if v else None
    except ValueError:
        return None


def _audit(con, role, action, target, detail=None, actor: Mapping | None = None) -> None:
    """One audit_log row. actor: {user_id, email, ip} of the person (None: the system or a script)."""
    a = actor or {}
    con.execute(sa.text('INSERT INTO app.audit_log ("at", role, action, target, detail, user_id, email, ip) VALUES '
                        "(:at, :role, :action, :target, :detail, :user_id, :email, CAST(:ip AS inet))"),
                {"at": now(), "role": role, "action": action, "target": target, "detail": detail,
                 "user_id": a.get("user_id"), "email": a.get("email"), "ip": inet(a.get("ip"))})


def init() -> int:
    """Bring the schema to the migration head (idempotent, logged) and seed the alert feed; returns the number of
    alerts seeded."""
    migrate.upgrade()
    return seed()


# ---------------------------------------------------------------- alerts

def seed() -> int:
    """Seed an empty alert feed from the current scores: one early_notice alert per early-notice project and
    one tier_up per Critical project, source 'seed:<asof>'. Does nothing once the feed has any alert."""
    m = serving.meta()
    asof, mv, source = str(m["asof"]), m["model_version"], f"seed:{m['asof']}"
    with connect() as con:
        con.execute(sa.text("LOCK TABLE app.alerts IN SHARE ROW EXCLUSIVE MODE"))  # check-then-insert, one seeder
        if con.execute(sa.text("SELECT 1 FROM app.alerts LIMIT 1")).first():
            return 0
        started, rows = now(), []
        for r in serving.early_notice():
            factors = [f for f in r["flags"] if f != "early_notice"] + [
                n for n in ("utility_shifting", "inter_agency") if r[f"ext_open_{n}"] == 1]
            detail = "; ".join(r["evidence"] or []) or "open " + " / ".join(factors) + " event in the report remarks"
            rows.append({"project_key": r["project_key"], "kind": "early_notice", "severity": 2,
                         "title": f"Early notice: {', '.join(factors)} on {r['project_name']}",
                         "detail": f"{detail}. CUF numbers show no slip yet (tier {r['tier'] or 'untiered'})."})
        for r in serving.in_tier("Critical"):
            rows.append({"project_key": r["project_key"], "kind": "tier_up", "severity": 3,
                         "title": f"Critical: {r['project_name']}",
                         "detail": f"entered Critical at asof {asof}; P(date push or cost revision, 2q) = "
                                   f"{r['p_any_2q']:.2f}"})
        if rows:
            con.execute(sa.text("""INSERT INTO app.alerts (created_at, project_key, kind, severity, title, detail, asof,
                model_version, source) VALUES (:created_at, :project_key, :kind, :severity, :title, :detail, :asof,
                :model_version, :source)"""), [_in({**r, "created_at": started, "asof": asof, "model_version": mv,
                                                   "source": source}) for r in rows])
        con.execute(sa.text("""INSERT INTO app.job_runs (job, started_at, finished_at, status, summary_json)
            VALUES ('seed_alerts', :started, :finished, 'ok', CAST(:summary AS jsonb))"""),
                    {"started": started, "finished": now(),
                     "summary": _json({"asof": asof, "model_version": mv, "alerts": len(rows)})})
    return len(rows)


def add_alerts(rows: list[dict]) -> int:
    """Insert alerts (project_key, kind, severity, title, detail, asof, model_version, source); returns the count."""
    cols = ("project_key", "kind", "severity", "title", "detail", "asof", "model_version", "source")
    if not rows:
        return 0
    with connect() as con:
        con.execute(sa.text(f"INSERT INTO app.alerts (created_at, {', '.join(cols)}) VALUES (:created_at, "
                            f"{', '.join(':' + c for c in cols)})"),
                    [_in({"created_at": now(), **{c: r.get(c) for c in cols}}) for r in rows])
    return len(rows)


def _alert_where(since, kind, acked, keys) -> tuple[str, dict]:
    conds, params = [], {}
    if keys is not None:
        conds.append("project_key = ANY(:keys)")
        params["keys"] = _keys(keys)
    if since:
        conds.append("created_at >= :since")
        params["since"] = _ts(since)
    if kind:
        conds.append("kind = :kind")
        params["kind"] = kind
    if acked is not None:
        conds.append("acked_at IS NOT NULL" if acked else "acked_at IS NULL")
    return (" WHERE " + " AND ".join(conds)) if conds else "", params


def alerts(since=None, kind=None, acked=None, page=1, size=50, keys=None) -> dict:
    """keys: only alerts on these projects (None: every alert; project-less pipeline errors are in no scope)."""
    where, params = _alert_where(since, kind, acked, keys)
    with read() as con:
        total = con.execute(sa.text(f"SELECT count(*) FROM app.alerts{where}"), params).scalar()
        items = _rows(con, f"SELECT * FROM app.alerts{where} ORDER BY created_at DESC, severity DESC, id "
                           "LIMIT :limit OFFSET :offset", {**params, "limit": size, "offset": (page - 1) * size})
    return {"total": total, "page": page, "size": size, "items": items}


def max_alert_id() -> int:
    with read() as con:
        return con.execute(sa.text("SELECT coalesce(max(id), 0) FROM app.alerts")).scalar()


def alerts_after(alert_id: int, limit=100) -> list[dict]:
    """Alerts with an id above alert_id, oldest first (the live stream)."""
    with read() as con:
        return _rows(con, "SELECT * FROM app.alerts WHERE id > :id ORDER BY id LIMIT :limit",
                     {"id": alert_id, "limit": limit})


def ack(alert_id: int, role: str, keys=None, actor: Mapping | None = None) -> dict | None:
    """Mark an alert acknowledged by role (the first ack stands); None if there is no such alert (or it is not on
    one of keys, when given). actor: who, for the audit row."""
    with connect() as con:
        row = _one(con, "SELECT * FROM app.alerts WHERE id = :id FOR UPDATE", {"id": alert_id})
        if row is None or (keys is not None and row["project_key"] not in keys):
            return None
        if row["acked_at"] is None:
            con.execute(sa.text("UPDATE app.alerts SET acked_by = :role, acked_at = :at WHERE id = :id"),
                        {"role": role, "at": now(), "id": alert_id})
            _audit(con, role, "alert.ack", str(alert_id), actor=actor)
        else:
            _audit(con, role, "alert.ack", str(alert_id), f"already acked by {row['acked_by']}", actor=actor)
        return _one(con, "SELECT * FROM app.alerts WHERE id = :id", {"id": alert_id})


def add_alerts_once(rows: list[dict]) -> int:
    """add_alerts, skipping a row whose project already has an alert of that kind from that source (a URL)."""
    with read() as con:
        fresh = [r for r in rows if not con.execute(sa.text(
            "SELECT 1 FROM app.alerts WHERE project_key IS NOT DISTINCT FROM :k AND kind = :kind "
            "AND source IS NOT DISTINCT FROM :source"),
            {"k": r.get("project_key"), "kind": r["kind"], "source": r.get("source")}).first()]
    return add_alerts(fresh) if fresh else 0


# ---------------------------------------------------------------- watchlist

def watchlist(role: str, limit=100) -> dict:
    with read() as con:
        total = con.execute(sa.text("SELECT count(*) FROM app.watchlist WHERE role = :role"), {"role": role}).scalar()
        items = _rows(con, "SELECT * FROM app.watchlist WHERE role = :role ORDER BY added_at DESC, project_key "
                           "LIMIT :limit", {"role": role, "limit": limit})
    rows = {r["key"]: r for r in serving.rows_for_keys(tuple(i["project_key"] for i in items))}
    return {"total": total, "items": [{**i, "project": rows.get(i["project_key"])} for i in items]}


def watch(role: str, project_key: str, actor: Mapping | None = None) -> bool:
    """Add to role's watchlist; False if it was already there."""
    with connect() as con:
        added = con.execute(sa.text("INSERT INTO app.watchlist (role, project_key, added_at) VALUES (:role, :key, :at) "
                                    "ON CONFLICT DO NOTHING"),
                            {"role": role, "key": project_key, "at": now()}).rowcount == 1
        _audit(con, role, "watchlist.add", project_key, None if added else "already on the watchlist", actor)
    return added


def unwatch(role: str, project_key: str, actor: Mapping | None = None) -> bool:
    """Remove from role's watchlist; False if it was not there."""
    with connect() as con:
        removed = con.execute(sa.text("DELETE FROM app.watchlist WHERE role = :role AND project_key = :key"),
                              {"role": role, "key": project_key}).rowcount == 1
        _audit(con, role, "watchlist.remove", project_key, None if removed else "was not on the watchlist", actor)
    return removed


def watched_keys() -> list[str]:
    """Every watchlisted project (any role), first watched first."""
    with read() as con:
        return [r[0] for r in con.execute(sa.text(
            "SELECT project_key FROM app.watchlist GROUP BY 1 ORDER BY min(added_at), project_key"))]


# ---------------------------------------------------------------- jobs, sources

def latest_jobs() -> list[dict]:
    with read() as con:
        rows = _rows(con, "SELECT DISTINCT ON (job) * FROM app.job_runs ORDER BY job, id DESC")
    for r in rows:
        r["summary"] = r.pop("summary_json")
    return rows


def record_job(job: str, started_at: str, status: str, summary: dict) -> None:
    with connect() as con:
        con.execute(sa.text("""INSERT INTO app.job_runs (job, started_at, finished_at, status, summary_json)
            VALUES (:job, :started, :finished, :status, CAST(:summary AS jsonb))"""),
                    {"job": job, "started": _ts(started_at), "finished": now(), "status": status,
                     "summary": _json(json.dumps(summary, default=str))})


def source_seen(sha256: str, pipeline_version: str) -> bool:
    with read() as con:
        return con.execute(sa.text("SELECT 1 FROM app.sources WHERE sha256 = :sha AND pipeline_version = :pv"),
                           {"sha": sha256, "pv": pipeline_version}).first() is not None


def record_source(row: dict) -> None:
    """One ingested file (backend/live/watcher.py); a re-run under the same pipeline version replaces its app.sources
    row. A recognised report (kind set) is also registered in ingest.source_documents (its sha256, filename, period
    and type; the archived path once it has one) and its run in ingest.load_runs (run_type INGEST, the versions
    and row counts the row carries: started_at, rows_read, rows_loaded, rows_failed, silver_version, gold_version,
    model_version; status SUCCESS or FAILED), the lineage of secure.txt section 1."""
    cols = ("sha256", "pipeline_version", "filename", "kind", "period", "rows", "status", "error", "archived_as")
    with connect() as con:
        con.execute(sa.text(f"""INSERT INTO app.sources (ingested_at, {', '.join(cols)})
            VALUES (:ingested_at, {', '.join(':' + c for c in cols)})
            ON CONFLICT (sha256, pipeline_version) DO UPDATE SET
            {', '.join(f'{c} = EXCLUDED.{c}' for c in cols[2:])}, ingested_at = EXCLUDED.ingested_at"""),
                    {"ingested_at": now(), **{c: row.get(c) for c in cols}})
        if not row.get("kind"):
            return
        period = _day(row["period"]) if row.get("period") else None
        doc_id = con.execute(sa.text("""INSERT INTO ingest.source_documents (filename, file_type, sha256, report_period,
                report_type, source_path)
            VALUES (:filename, :file_type, :sha256, :period, :kind, :path)
            ON CONFLICT (sha256) DO UPDATE SET filename = EXCLUDED.filename, report_period = EXCLUDED.report_period,
                report_type = EXCLUDED.report_type, source_path = coalesce(EXCLUDED.source_path,
                ingest.source_documents.source_path)
            RETURNING source_document_id"""),
                             {"filename": row.get("filename"),
                              "file_type": "csv" if row["kind"] == "portal_csv" else "pdf", "sha256": row["sha256"],
                              "period": period, "kind": row["kind"], "path": row.get("archived_as")}).scalar()
        con.execute(sa.text("""INSERT INTO ingest.load_runs (run_type, source_document_id, report_period,
                pipeline_version, silver_version, gold_version, model_version, started_at, finished_at, status,
                rows_read, rows_loaded, rows_failed)
            VALUES ('INGEST', :doc, :period, :pv, :silver, :gold, :model, :started, :finished, :status, :read, :loaded,
                :failed)"""),
                    {"doc": doc_id, "period": period, "pv": row["pipeline_version"],
                     "silver": row.get("silver_version"), "gold": row.get("gold_version"),
                     "model": row.get("model_version"),
                     "started": _ts(row.get("started_at")) or now(), "finished": now(),
                     "status": "SUCCESS" if row.get("status") == "ok" else "FAILED",
                     "read": row.get("rows_read", row.get("rows")), "loaded": row.get("rows_loaded", row.get("rows")),
                     "failed": row.get("rows_failed")})


def source_documents(sha256: str | None = None) -> list[dict]:
    """The registered source documents (ingest.source_documents), or the one with that sha256."""
    with read() as con:
        return _rows(con, "SELECT * FROM ingest.source_documents" + (" WHERE sha256 = :sha" if sha256 else "")
                     + " ORDER BY source_document_id", {"sha": sha256})


def load_runs(run_type: str | None = None, limit: int = 50) -> list[dict]:
    """The newest load runs (ingest.load_runs), of one run_type (INGEST, SERVING) or any."""
    with read() as con:
        return _rows(con, "SELECT * FROM ingest.load_runs" + (" WHERE run_type = :t" if run_type else "")
                     + " ORDER BY load_run_id DESC LIMIT :limit", {"t": run_type, "limit": limit})


# ---------------------------------------------------------------- signals

def project_signals(project_key: str, limit=100) -> dict:
    """Linked signals for one project, newest first, and when the scout last searched it (None: never)."""
    with read() as con:
        items = _rows(con, """SELECT s.*, sp.link_score, sp.method FROM app.signal_projects sp
            JOIN app.signals s ON s.id = sp.signal_id WHERE sp.project_key = :key
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC LIMIT :limit""", {"key": project_key, "limit": limit})
        last = _one(con, "SELECT scouted_at FROM app.scouted WHERE project_key = :key", {"key": project_key})
    return {"key": project_key, "last_scout_at": last and last["scouted_at"], "items": items}


def signals(url: str | None = None) -> list[dict]:
    """Every stored signal (or the one with that URL), oldest first."""
    with read() as con:
        return _rows(con, "SELECT * FROM app.signals" + (" WHERE url = :url" if url else "") + " ORDER BY id",
                     {"url": url})


def known_signal_hashes(url_hashes: Iterable[str], text_hashes: Iterable[str]) -> tuple[set[str], set[str]]:
    """(the url hashes, the text hashes) of every stored signal that has one of those given: what a batch of new
    items is deduplicated against."""
    with read() as con:
        rows = con.execute(sa.text("SELECT url_hash, text_hash FROM app.signals WHERE url_hash = ANY(:u) "
                                   "OR text_hash = ANY(:t)"), {"u": list(url_hashes), "t": list(text_hashes)}).all()
    return {r[0] for r in rows}, {r[1] for r in rows}


def save_signals(rows: list[dict]) -> list[int]:
    """Store signals (SIGNAL_COLS) in one transaction, each with its links: row['links'] = [(project_key, link_score,
    method)]; returns their ids in order."""
    ids = []
    with connect() as con:
        for r in rows:
            sid = con.execute(sa.text(f"INSERT INTO app.signals ({', '.join(SIGNAL_COLS)}) VALUES "
                                      f"({', '.join(':' + c for c in SIGNAL_COLS)}) RETURNING id"),
                              _in({c: r.get(c) for c in SIGNAL_COLS})).scalar()
            for key, score, method in r.get("links") or ():
                con.execute(sa.text("INSERT INTO app.signal_projects (signal_id, project_key, link_score, method) "
                                    "VALUES (:sid, :key, :score, :method) ON CONFLICT DO NOTHING"),
                            {"sid": sid, "key": key, "score": score, "method": method})
            ids.append(sid)
    return ids


def signal_links(signal_id: int | None = None) -> list[dict]:
    """The signal_projects rows (of one signal, or every one)."""
    with read() as con:
        return _rows(con, "SELECT * FROM app.signal_projects" + (" WHERE signal_id = :sid" if signal_id else "")
                     + " ORDER BY signal_id, project_key", {"sid": signal_id})


def scouted_at() -> dict[str, str]:
    """project_key -> when the scout last searched it."""
    with read() as con:
        return {r["project_key"]: r["scouted_at"]
                for r in _rows(con, "SELECT project_key, scouted_at FROM app.scouted")}


def mark_scouted(done: list[tuple[str, int]]) -> None:
    """(project_key, n_items) of the projects a scout run searched, now."""
    if not done:
        return
    with connect() as con:
        con.execute(sa.text("""INSERT INTO app.scouted (project_key, scouted_at, n_items) VALUES (:key, :at, :n)
            ON CONFLICT (project_key) DO UPDATE SET scouted_at = EXCLUDED.scouted_at, n_items = EXCLUDED.n_items"""),
                    [{"key": k, "at": now(), "n": n} for k, n in done])


LINKED_TO_KEYS = "s.id IN (SELECT signal_id FROM app.signal_projects WHERE project_key = ANY(:keys))"


def signal_feed(since=None, category=None, severity=None, linked=None, state_keys=None, page=1, size=50,
                keys=None) -> tuple[int, list[dict], dict[int, list[dict]]]:
    """One page of signals, newest first: (total, the rows, {signal id: its signal_projects rows}). keys: only
    signals linked to one of them; state_keys: only signals linked to one of these (an empty list: none)."""
    conds, params = [], {}
    if keys is not None:
        conds.append(LINKED_TO_KEYS)
        params["keys"] = _keys(keys)
    for sql, name, v in (("s.published_at >= :since", "since", _ts(since)),
                         ("s.category = :category", "category", category),
                         ("s.severity >= :severity", "severity", severity)):
        if v is not None:
            conds.append(sql)
            params[name] = v
    if state_keys is not None:
        conds.append("s.id IN (SELECT signal_id FROM app.signal_projects WHERE project_key = ANY(:state_keys))")
        params["state_keys"] = list(state_keys)
    if linked is not None:
        conds.append(("" if linked else "NOT ")
                     + "EXISTS (SELECT 1 FROM app.signal_projects sp WHERE sp.signal_id = s.id)")
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with read() as con:
        total = con.execute(sa.text(f"SELECT count(*) FROM app.signals s{where}"), params).scalar()
        rows = _rows(con, f"""SELECT s.* FROM app.signals s{where}
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC LIMIT :limit OFFSET :offset""",
                     {**params, "limit": size, "offset": (page - 1) * size})
        links: dict[int, list[dict]] = {}
        for ln in _rows(con, "SELECT * FROM app.signal_projects WHERE signal_id = ANY(:ids) ORDER BY project_key",
                        {"ids": [r["id"] for r in rows]}):
            links.setdefault(ln["signal_id"], []).append(ln)
    return total, rows, links


def severe_links(since) -> list[tuple[int, str]]:
    """(signal id, project key) of every link of a signal of severity >= 2 published since."""
    with read() as con:
        return [tuple(r) for r in con.execute(sa.text("""SELECT DISTINCT sp.signal_id, sp.project_key
            FROM app.signal_projects sp JOIN app.signals s ON s.id = sp.signal_id
            WHERE s.severity >= 2 AND s.published_at >= :since"""), {"since": _ts(since)})]


def radar_counts(since, keys=None) -> dict:
    """The radar rollup's counts: signals in all (total) and published since (n_window, of them n_linked), the
    window's counts by category, severity and source, every link as (project_key, published_at) and the number of
    projects scouted; with keys only the signals linked to them, their links and their scouting."""
    signals_in, keys_in, params = "TRUE", "TRUE", {"since": _ts(since)}
    if keys is not None:
        signals_in, keys_in, params["keys"] = LINKED_TO_KEYS, "project_key = ANY(:keys)", _keys(keys)
    linked = "EXISTS (SELECT 1 FROM app.signal_projects sp WHERE sp.signal_id = s.id)"
    with read() as con:
        def counts(col, limit=20):
            return [{"name": r[0], "n": r[1]} for r in con.execute(sa.text(
                f"""SELECT {col}, count(*) FROM app.signals s WHERE s.published_at >= :since AND {signals_in}
                    GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {limit}"""), params)]
        total = con.execute(sa.text(f"SELECT count(*) FROM app.signals s WHERE {signals_in}"), params).scalar()
        n_window, n_linked = con.execute(sa.text(f"""SELECT count(*), count(*) FILTER (WHERE {linked})
            FROM app.signals s WHERE s.published_at >= :since AND {signals_in}"""), params).one()
        pairs = [(r["project_key"], r["published_at"]) for r in _rows(con, f"""SELECT project_key, s.published_at
            FROM app.signal_projects JOIN app.signals s ON s.id = signal_id WHERE {keys_in}""", params)]
        scouted = con.execute(sa.text(f"SELECT count(*) FROM app.scouted WHERE {keys_in}"), params).scalar()
        return {"total": total, "n_window": n_window, "n_linked": n_linked,
                "by_category": counts("coalesce(s.category, 'none')"), "by_severity": counts("s.severity"),
                "by_source": counts("s.source", 10), "pairs": pairs, "scouted": scouted}


def news_for_index(per_project: int) -> list[dict]:
    """The newest per_project titled signals linked to each project (id, title, source, published_at, category,
    severity, url, project_key), by id then key: the assistant's news chunks (llm/rag.py)."""
    return _rows_or_none("""SELECT id, title, source, published_at, category, severity, url, project_key FROM (
            SELECT s.id, s.title, s.source, s.published_at, s.category, s.severity, s.url, sp.project_key,
                row_number() OVER (PARTITION BY sp.project_key ORDER BY s.published_at DESC NULLS LAST, s.id DESC) AS n
            FROM app.signal_projects sp JOIN app.signals s ON s.id = sp.signal_id WHERE coalesce(s.title, '') != '') t
        WHERE n <= :n ORDER BY id, project_key""", {"n": per_project})


def linked_signals(min_severity: int = 2) -> list[dict]:
    """Linked signals of severity >= min_severity with a category (project_key, category, severity, title, source,
    published_at, url): the bottleneck clusters' news members (pipeline/bottlenecks.py)."""
    return _rows_or_none("""SELECT sp.project_key, s.category, s.severity, s.title, s.source, s.published_at, s.url
        FROM app.signal_projects sp JOIN app.signals s ON s.id = sp.signal_id
        WHERE s.severity >= :sev AND s.category IS NOT NULL ORDER BY s.id, sp.project_key""", {"sev": min_severity})


def index_marks() -> dict:
    """What the search index's fingerprint watches in the database: the newest signal id, the number of links and
    the research agent's facts (count, newest judged_at)."""
    with read() as con:
        r = con.execute(sa.text("""SELECT (SELECT max(id) FROM app.signals), (SELECT count(*) FROM app.signal_projects),
            (SELECT count(*) FROM app.research_facts), (SELECT max(judged_at) FROM app.research_facts)""")).one()
    return {"signals": r[0], "links": r[1], "research": [r[2], _out({"judged_at": r[3]})["judged_at"]]}


# ---------------------------------------------------------------- research agent

def research_facts(project_key: str | None = None, keys=None) -> list[dict]:
    """The research agent's facts of one project, or of keys (None: every project), newest judged first."""
    conds, params = [], {}
    if project_key is not None:
        conds.append("project_key = :key")
        params["key"] = project_key
    if keys is not None:
        conds.append("project_key = ANY(:keys)")
        params["keys"] = _keys(keys)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    return _rows_or_none(f"SELECT * FROM app.research_facts{where} ORDER BY judged_at DESC NULLS LAST, fact_id", params)


def researched(project_key: str | None = None) -> dict[str, str]:
    """project_key -> when the research agent last researched it (one project, or every one)."""
    sql, params = "SELECT project_key, researched_at FROM app.researched", {}
    if project_key is not None:
        sql, params = sql + " WHERE project_key = :key", {"key": project_key}
    return {r["project_key"]: r["researched_at"] for r in _rows_or_none(sql, params)}


def researched_rows(project_key: str | None = None) -> list[dict]:
    """The researched rows (project_key, researched_at, n_candidates, n_relevant) of one project or every one."""
    with read() as con:
        return _rows(con, "SELECT * FROM app.researched" + (" WHERE project_key = :key" if project_key else "")
                     + " ORDER BY project_key", {"key": project_key})


def research_candidates(project_key: str, limit: int) -> tuple[list[dict], list[dict]]:
    """News items the research agent has not judged for this project: (up to limit linked to it, every one linked to
    no project, the unlinked pool), newest first."""
    unjudged = ("NOT EXISTS (SELECT 1 FROM app.signal_judgements j WHERE j.signal_id = s.id "
                "AND j.project_key = :key)")
    with read() as con:
        linked = _rows(con, f"""SELECT s.*, sp.method FROM app.signals s
            JOIN app.signal_projects sp ON sp.signal_id = s.id AND sp.project_key = :key WHERE {unjudged}
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC LIMIT :limit""", {"key": project_key, "limit": limit})
        pool = _rows(con, f"""SELECT s.* FROM app.signals s
            WHERE NOT EXISTS (SELECT 1 FROM app.signal_projects sp WHERE sp.signal_id = s.id) AND {unjudged}
            ORDER BY s.published_at DESC NULLS LAST, s.id DESC""", {"key": project_key})
    return linked, pool


def save_research(project_key: str, judgements: list[dict], facts: list[dict], links: list[int]) -> list[str]:
    """One batch of research verdicts in one transaction: every judgement (replacing an earlier one on the same
    item), the relevant facts (a fact_id already stored is kept as it is) and a signal_projects row (method 'llm')
    for each newly linked pool item. Returns the fact_ids that are new."""
    new = []
    with connect() as con:
        if judgements:
            con.execute(sa.text(f"""INSERT INTO app.signal_judgements ({', '.join(JUDGEMENT_COLS)})
                VALUES ({', '.join(':' + c for c in JUDGEMENT_COLS[:3])}, CAST(:verdict_json AS jsonb),
                :model, :prompt_version, :judged_at)
                ON CONFLICT (signal_id, project_key) DO UPDATE SET relevant = EXCLUDED.relevant,
                verdict_json = EXCLUDED.verdict_json, model = EXCLUDED.model, prompt_version = EXCLUDED.prompt_version,
                judged_at = EXCLUDED.judged_at"""), [_in({c: j.get(c) for c in JUDGEMENT_COLS}) for j in judgements])
        insert_fact = sa.text(f"INSERT INTO app.research_facts ({', '.join(RESEARCH_FACT_COLS)}) VALUES "
                              f"({', '.join(':' + c for c in RESEARCH_FACT_COLS)}) ON CONFLICT (fact_id) DO NOTHING")
        for f in facts:
            if con.execute(insert_fact, _in({**{c: f.get(c) for c in RESEARCH_FACT_COLS},
                                             "origin": f.get("origin") or "agent"})).rowcount:
                new.append(f["fact_id"])
        if links:
            con.execute(sa.text("INSERT INTO app.signal_projects (signal_id, project_key, link_score, method) "
                                "VALUES (:sid, :key, NULL, 'llm') ON CONFLICT DO NOTHING"),
                        [{"sid": sid, "key": project_key} for sid in links])
    return new


def mark_researched(project_key: str, n_candidates: int, n_relevant: int, researched_at=None) -> None:
    """The project was researched now (or at researched_at)."""
    with connect() as con:
        con.execute(sa.text("""INSERT INTO app.researched (project_key, researched_at, n_candidates, n_relevant)
            VALUES (:key, :at, :n, :r) ON CONFLICT (project_key) DO UPDATE SET researched_at = EXCLUDED.researched_at,
            n_candidates = EXCLUDED.n_candidates, n_relevant = EXCLUDED.n_relevant"""),
                    {"key": project_key, "at": _ts(researched_at) or now(), "n": n_candidates, "r": n_relevant})


def signal_verdicts(project_key: str) -> dict[int, int | None]:
    """signal id -> the research agent's verdict on it for this project (1 relevant, 0 not, None rejected)."""
    return {r["signal_id"]: r["relevant"] for r in _rows_or_none(
        "SELECT signal_id, relevant FROM app.signal_judgements WHERE project_key = :key", {"key": project_key})}


def signal_judgements(project_key: str | None = None, signal_id: int | None = None) -> list[dict]:
    """The judgement rows of a project and/or a signal, verdict_json as JSON text."""
    conds, params = [], {}
    if project_key is not None:
        conds.append("project_key = :key")
        params["key"] = project_key
    if signal_id is not None:
        conds.append("signal_id = :sid")
        params["sid"] = signal_id
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with read() as con:
        rows = _rows(con, f"SELECT * FROM app.signal_judgements{where} ORDER BY signal_id, project_key", params)
    for r in rows:
        r["verdict_json"] = None if r["verdict_json"] is None else json.dumps(r["verdict_json"], ensure_ascii=False)
    return rows


# ---------------------------------------------------------------- second opinions, briefs

def _opinion(r: dict) -> dict:
    return {**(r["json"] or {}), **{c: r[c] for c in SECOND_OPINION_COLS}}


def second_opinion(project_key: str, evidence_hash: str, model: str) -> dict | None:
    """The stored second opinion (accepted or rejected) for this evidence version and LLM model, or None."""
    rows = _rows_or_none("SELECT * FROM app.second_opinions WHERE project_key = :key AND evidence_hash = :h "
                         "AND model = :model", {"key": project_key, "h": evidence_hash, "model": model})
    return _opinion(rows[0]) if rows else None


def second_opinions(project_key: str | None = None) -> list[dict]:
    """Every stored second opinion of one project (None: every project), newest first: the prospective log."""
    sql, params = "SELECT * FROM app.second_opinions", {}
    if project_key is not None:
        sql, params = sql + " WHERE project_key = :key", {"key": project_key}
    return [_opinion(r) for r in _rows_or_none(sql + " ORDER BY generated_at DESC NULLS LAST, project_key", params)]


def second_opinion_times() -> dict[str, str]:
    """project_key -> when it was last asked for a second opinion: its newest one (any evidence version, accepted or
    rejected) or a newer rejection noted on an accepted one (json last_rejected.at)."""
    return {r["project_key"]: r["last"] for r in _rows_or_none("""SELECT project_key,
        max(greatest(generated_at, CAST("json" -> 'last_rejected' ->> 'at' AS timestamptz))) AS last
        FROM app.second_opinions GROUP BY 1""")}


def save_second_opinion(row: dict) -> None:
    """One second opinion (the SECOND_OPINION_COLS and everything else as json); replaces the one for the same
    project, evidence version and LLM model."""
    body = {k: v for k, v in row.items() if k not in SECOND_OPINION_COLS}
    with connect() as con:
        con.execute(sa.text(f"""INSERT INTO app.second_opinions ({', '.join(SECOND_OPINION_COLS)}, "json")
            VALUES ({', '.join(':' + c for c in SECOND_OPINION_COLS)}, CAST(:json AS jsonb))
            ON CONFLICT (project_key, evidence_hash, model) DO UPDATE SET prompt_version = EXCLUDED.prompt_version,
            asof = EXCLUDED.asof, generated_at = EXCLUDED.generated_at, "json" = EXCLUDED."json\""""),
                    _in({**{c: row.get(c) for c in SECOND_OPINION_COLS}, "json": body}))


def cached_brief(project_key: str, asof: str, model_version: str) -> dict | None:
    """An accepted brief (backend/brief.py) for this data version, or None."""
    with read() as con:
        row = _one(con, "SELECT * FROM app.briefs WHERE project_key = :key AND asof = :asof AND model_version = :mv",
                   {"key": project_key, "asof": _day(asof), "mv": model_version})
    if row is None:
        return None
    row["key"] = row.pop("project_key")
    return row


def save_brief(b: dict) -> None:
    with connect() as con:
        con.execute(sa.text("""INSERT INTO app.briefs (project_key, asof, model_version, generated_at, text,
                n_numbers_checked, attempts)
            VALUES (:key, :asof, :model_version, :generated_at, :text, :n_numbers_checked, :attempts)
            ON CONFLICT (project_key, asof, model_version) DO UPDATE SET generated_at = EXCLUDED.generated_at,
            text = EXCLUDED.text, n_numbers_checked = EXCLUDED.n_numbers_checked, attempts = EXCLUDED.attempts"""),
                    _in({k: b[k] for k in ("key", "asof", "model_version", "generated_at", "text",
                                           "n_numbers_checked", "attempts")}))


# ---------------------------------------------------------------- audit

def audit(role, action, target, detail=None, actor: Mapping | None = None) -> None:
    with connect() as con:
        _audit(con, role, action, target, detail, actor)


def audit_rows(since=None, user=None, action=None, page=1, size=50, hide_roles: Iterable[str] = ()) -> dict:
    """One page of the audit log, newest first. user: a user id (digits), an email or a role; action: exact;
    hide_roles: rows recorded under these roles are left out (the developer's, for anyone else)."""
    conds, params = [], {}
    if since:
        conds.append('"at" >= :since')
        params["since"] = _ts(since)
    if user:
        conds.append("(user_id = :uid OR role = :user OR email = :user)" if user.isdigit()
                     else "(role = :user OR email = :user)")
        params.update(user=user, uid=int(user) if user.isdigit() else None)
    if action:
        conds.append("action = :action")
        params["action"] = action
    if hide_roles:
        conds.append("(role IS NULL OR NOT role = ANY(:hide))")
        params["hide"] = list(hide_roles)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with read() as con:
        total = con.execute(sa.text(f"SELECT count(*) FROM app.audit_log{where}"), params).scalar()
        items = _rows(con, f"""SELECT id, "at", role, action, target, detail, user_id, email, host(ip) AS ip
            FROM app.audit_log{where} ORDER BY id DESC LIMIT :limit OFFSET :offset""",
                      {**params, "limit": size, "offset": (page - 1) * size})
    return {"total": total, "page": page, "size": size, "items": items}
