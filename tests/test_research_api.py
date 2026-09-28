"""Web research in the API: sweep + agent facts per project, the scoped summary, public redaction, empty tables.
Expectations come from the committed gold research tables, so the tests hold for the pilot sample and the full
sweep alike."""
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.main import app  # noqa: E402
from pipeline.research import EXT_COLS  # noqa: E402

IPMD = {"X-Paimana-Role": "ipmd_analyst"}
AGENT_URL, AGENT_OLD_URL = "https://news.google.com/rss/articles/x1", "https://news.google.com/rss/articles/x0"
AGENT_SAME_URL = "https://news.google.com/rss/articles/x2"


def camel(name):
    head, *tail = name.split("_")
    return head + "".join(w.capitalize() for w in tail)


def ministry(name):
    return {"X-Paimana-Role": "ministry_official", "X-Paimana-Ministry": quote(name)}


def agency(name):
    return {"X-Paimana-Role": "agency_official", "X-Paimana-Agency": quote(name)}


def add_agent_fact(key, url, fact_id, **kw):
    row = {"fact_id": fact_id, "project_key": key, "category": "land", "taxonomy": "land", "direction": "negative",
           "severity": 2, "event_date": "2026-09-30", "date_precision": "day", "published_date": "2026-09-30",
           "status": "unknown", "summary": "Villagers stopped work on the approach road over compensation.",
           "headline": "Work on approach road stopped", "source": "PTI", "url": url, "domain": "news.google.com",
           "match": "medium", "match_reason": "LLM judge: names the project and its place", "origin": "agent",
           "researched_on": "2026-09-30", "live": 1, "signal_id": None, "model": "qwen", "prompt_version": "t",
           "judged_at": "2026-09-30T10:00:00+00:00", **kw}
    with closing(db.connect()) as con, con:
        con.execute(f"INSERT INTO research_facts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    list(row.values()))


@pytest.fixture(scope="module")
def sweep():
    """The committed sweep over the current projects, and the project with the most facts (key)."""
    s = serving.state()
    cur = {r["k"]: r for r in serving._rows(s, """SELECT c.project_key AS k, c.ministry, a.canonical AS agency
        FROM cur c LEFT JOIN amap a ON a.raw = c.agency""")}
    facts = pd.read_parquet(serving.RESEARCH_FACTS)
    projects = pd.read_parquet(serving.RESEARCH_PROJECTS)
    facts, projects = facts[facts["project_key"].isin(cur)], projects[projects["project_key"].isin(cur)]
    key = facts.groupby("project_key").size().sort_values(ascending=False, kind="stable").index[0]
    mine = facts[facts["project_key"].eq(key)]
    return SimpleNamespace(cur=cur, facts=facts, projects=projects, key=key, mine=mine, url=mine["url"].iloc[0],
                           headline=mine["headline"].iloc[0], source=mine["source"].iloc[0],
                           row=projects.set_index("project_key").loc[key])


@pytest.fixture(scope="module")
def client(tmp_path_factory, sweep):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))
        with TestClient(app) as c:
            add_agent_fact(sweep.key, AGENT_URL, "agentfact001")
            # the sweep cites this story already: the agent has it as a Google News link, its headline with the
            # feed's ' - Source' tail, other case and punctuation
            add_agent_fact(sweep.key, AGENT_SAME_URL, "agentfact002", source=sweep.source,
                           headline=f"{sweep.headline.upper().replace(':', ' -')}!  - {sweep.source}")
            add_agent_fact(sweep.key, AGENT_OLD_URL, "agentfact003", direction="positive", event_date=None,
                           published_date="2020-01-10", severity=1, live=0, headline="Approach road work resumes")
            # the same story as agentfact001 from a second feed: one fact
            add_agent_fact(sweep.key, AGENT_URL + "b", "agentfact004", source="The Tribune",
                           headline="Work on approach road stopped | The Tribune",
                           judged_at="2026-09-29T10:00:00+00:00")
            with closing(db.connect()) as con, con:
                con.execute("INSERT INTO researched VALUES (?, '2026-09-30T10:00:00+00:00', 5, 2)", [sweep.key])
            yield c


def test_project_research_merges_sweep_and_agent_facts(client, sweep):
    key = sweep.key
    d = client.get(f"/api/projects/{key}/research", headers=IPMD).json()
    facts = d["facts"]
    assert d["searched"] and d["researchedOn"] == str(sweep.row["researched_on"].date())
    assert d["agentResearchedAt"].startswith("2026-09-30")
    assert d["nFacts"] == len(facts) == len(sweep.mine) + 2
    assert d["nNegativeLive"] == int(sweep.mine["live"].sum()) + 1
    assert [f["factId"] for f in facts if f["origin"] == "agent"] == ["agentfact001", "agentfact003"]
    assert AGENT_SAME_URL not in {f["url"] for f in facts}                   # the agent's copy of a sweep story
    dates = [f["eventDate"] or f["publishedDate"] for f in facts]
    assert dates == sorted(dates, reverse=True) and facts[0]["factId"] == "agentfact001"    # newest first
    assert facts[0]["live"] and facts[0]["verified"] is None and facts[0]["matchReason"]
    assert all(f["verified"] in ("keep", "fix") and f["signalId"] is None for f in facts if f["origin"] == "sweep")
    for (entry, field), col in EXT_COLS.items():
        want = sweep.row[col]
        got = (d["external"][camel(entry)] or {}).get(camel(field))
        assert got == (None if pd.isna(want) else want), (entry, field)
    assert d["latestStatus"] == (None if pd.isna(sweep.row["latest_status"]) else sweep.row["latest_status"])

    pub = client.get(f"/api/projects/{key}/research").json()
    assert [f["factId"] for f in pub["facts"]] == [f["factId"] for f in facts]
    assert all(f["matchReason"] is None for f in pub["facts"])

    brief = client.get(f"/api/projects/{key}", headers=IPMD).json()["research"]
    top = brief["top"]
    assert brief["nFacts"] == d["nFacts"] and len(top) == min(3, d["nFacts"]) and top[0]["live"]
    assert [f["live"] for f in top] == sorted((f["live"] for f in top), reverse=True)   # live blockers first
    assert all(f["matchReason"] is None for f in client.get(f"/api/projects/{key}").json()["research"]["top"])


def test_not_researched_is_not_searched(client, sweep):
    s = serving.state()
    key = next(r["k"] for r in serving._rows(s, "SELECT project_key AS k FROM master ORDER BY project_key")
               if r["k"] not in set(sweep.projects["project_key"]))
    d = client.get(f"/api/projects/{key}/research", headers=IPMD).json()
    assert d["searched"] is False and d["facts"] == [] and d["researchedOn"] is None
    assert all(v is None for v in d["external"].values())
    empty = sweep.projects[sweep.projects["n_facts"].eq(0) & sweep.projects["searched"]]
    if len(empty):   # searched, nothing found
        got = client.get(f"/api/projects/{empty['project_key'].iloc[0]}/research").json()
        assert got["searched"] is True and got["nFacts"] == 0


def test_research_is_scoped(client, sweep):
    key, own = sweep.key, sweep.cur[sweep.key]
    other_m = next(r["ministry"] for r in sweep.cur.values() if r["ministry"] != own["ministry"])
    assert client.get(f"/api/projects/{key}/research", headers=ministry(own["ministry"])).status_code == 200
    assert client.get(f"/api/projects/{key}/research", headers=ministry(other_m)).status_code == 404
    other_a = next(sweep.cur[k]["agency"] for k in sweep.projects["project_key"]
                   if sweep.cur[k]["agency"] not in (None, own["agency"]))
    assert client.get(f"/api/projects/{key}/research", headers=agency(own["agency"])).status_code == 200
    assert client.get(f"/api/projects/{key}/research", headers=agency(other_a)).status_code == 404
    got = client.get("/api/research/summary", headers=agency(other_a)).json()
    keys = serving.scope_keys(("agency", other_a))
    assert got["coverage"]["nSearched"] >= 1 and all(b["projectKey"] in keys for b in got["topRecentBlockers"])


def test_summary_counts_add_up_across_ministries(client, sweep):
    full = client.get("/api/research/summary", headers=IPMD).json()
    cov = full["coverage"]
    assert cov["nSearched"] == int(sweep.projects["searched"].sum()) and cov["nCurrent"] == len(sweep.cur)
    assert cov["nFacts"] == len(sweep.facts) + 2 and cov["nAgentFacts"] == 2 and cov["nAgentProjects"] == 1
    assert cov["nCurrent"] == sum(s["nCurrent"] for s in full["byState"])
    names = [m["name"] for m in client.get("/api/scopes").json()["ministries"]]
    parts = [client.get("/api/research/summary", headers=ministry(m)).json() for m in names]
    for f in ("nCurrent", "nSearched", "nWithFacts", "nFacts", "nNegativeLive", "nProjectsNegativeLive"):
        assert sum(p["coverage"][f] for p in parts) == cov[f], f
    assert sum(c["nLive"] for c in full["byCategory"]) == cov["nNegativeLive"]
    blockers = full["topRecentBlockers"]
    assert blockers[0]["factId"] == "agentfact001" and all(b["projectName"] and b["tier"] for b in blockers)
    assert len({(b["projectKey"], b["url"]) for b in blockers}) == len(blockers)   # one row per project and page
    assert all(b["severity"] >= 2 for b in blockers)


def test_public_summary_is_counts_and_citations(client):
    full = client.get("/api/research/summary", headers=IPMD).json()
    pub = client.get("/api/research/summary").json()
    assert pub["coverage"] == full["coverage"] and pub["byCategory"] == full["byCategory"]
    assert [b["url"] for b in pub["topRecentBlockers"]] == [b["url"] for b in full["topRecentBlockers"]]
    for b in pub["topRecentBlockers"]:
        assert b["headline"] and b["url"] and b["eventDate"]
        assert all(b[k] is None for k in ("factId", "projectKey", "projectName", "summary", "source", "tier"))


def test_empty_research_tables_keep_their_columns(tmp_path, monkeypatch):
    real = duckdb.connect()
    serving._load_research(real)
    monkeypatch.setattr(serving, "RESEARCH_DDL", {n: (tmp_path / "missing.parquet", ddl)
                                                  for n, (_, ddl) in serving.RESEARCH_DDL.items()})
    empty = duckdb.connect()
    serving._load_research(empty)
    for name in serving.RESEARCH_DDL:
        cols = [(r[0], r[1]) for r in real.execute(f"DESCRIBE {name}").fetchall()]
        assert [(r[0], r[1]) for r in empty.execute(f"DESCRIBE {name}").fetchall()] == cols, name
        assert empty.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 0
