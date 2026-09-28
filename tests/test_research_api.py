"""Web research in the API: sweep + agent facts per project, the scoped summary, public redaction, empty tables."""
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import duckdb
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.main import app  # noqa: E402

IPMD = {"X-Paimana-Role": "ipmd_analyst"}
KEY = "PRJ-000698"          # in the committed sweep: 4 facts, 2 live negative (Ministry of Power)
SWEEP_URL = "https://www.thdc.co.in/en/projects/hydro/vishnugad-pipalkoti-he-project"


def ministry(name):
    return {"X-Paimana-Role": "ministry_official", "X-Paimana-Ministry": quote(name)}


def agency(name):
    return {"X-Paimana-Role": "agency_official", "X-Paimana-Agency": quote(name)}


def add_agent_fact(key, url, fact_id, **kw):
    row = {"fact_id": fact_id, "project_key": key, "category": "land", "taxonomy": "land", "direction": "negative",
           "severity": 2, "event_date": "2026-09-01", "date_precision": "month", "published_date": "2026-09-03",
           "status": "unknown", "summary": "Villagers stopped work on the approach road over compensation.",
           "headline": "Work on approach road stopped", "source": "PTI", "url": url, "domain": "news.google.com",
           "match": "medium", "match_reason": "LLM judge: names the project and its place", "origin": "agent",
           "researched_on": "2026-09-28", "live": 1, "signal_id": None, "model": "qwen", "prompt_version": "t",
           "judged_at": "2026-09-28T10:00:00+00:00", **kw}
    with closing(db.connect()) as con, con:
        con.execute(f"INSERT INTO research_facts ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    list(row.values()))


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))
        with TestClient(app) as c:
            add_agent_fact(KEY, "https://news.google.com/rss/articles/x1", "agentfact001")
            add_agent_fact(KEY, SWEEP_URL, "agentfact002")                     # the sweep cites this page already
            add_agent_fact(KEY, "https://news.google.com/rss/articles/x0", "agentfact003", direction="positive",
                           event_date=None, published_date="2025-01-10", severity=1, live=0)
            with closing(db.connect()) as con, con:
                con.execute("INSERT INTO researched VALUES (?, '2026-09-28T10:00:00+00:00', 5, 2)", [KEY])
            yield c


def test_project_research_merges_sweep_and_agent_facts(client):
    d = client.get(f"/api/projects/{KEY}/research", headers=IPMD).json()
    facts = d["facts"]
    assert d["searched"] and d["researchedOn"] == "2026-09-28" and d["agentResearchedAt"].startswith("2026-09-28")
    assert d["nFacts"] == len(facts) == 6 and d["nNegativeLive"] == 3
    assert [f["factId"] for f in facts if f["origin"] == "agent"] == ["agentfact001", "agentfact003"]
    assert sum(f["url"] == SWEEP_URL for f in facts) == 1                  # the agent's copy of a sweep page is dropped
    dates = [f["eventDate"] or f["publishedDate"] for f in facts]
    assert dates == sorted(dates, reverse=True) and facts[0]["factId"] == "agentfact001"    # newest first
    assert facts[0]["live"] and facts[0]["verified"] is None and facts[0]["matchReason"]
    assert all(f["verified"] in ("keep", "fix") and f["signalId"] is None for f in facts if f["origin"] == "sweep")
    ext = d["external"]
    assert ext["contractor"]["company"] == "Hindustan Construction Company" and ext["newTarget"]["date"] == "2028-06"
    assert ext["landAcquiredPct"] is None and d["latestStatus"]

    pub = client.get(f"/api/projects/{KEY}/research").json()
    assert [f["factId"] for f in pub["facts"]] == [f["factId"] for f in facts]
    assert all(f["matchReason"] is None for f in pub["facts"])

    brief = client.get(f"/api/projects/{KEY}", headers=IPMD).json()["research"]
    assert brief["nFacts"] == 6 and len(brief["top"]) == 3 and all(f["live"] for f in brief["top"])
    assert brief["top"][0]["severity"] >= brief["top"][-1]["severity"]
    assert all(f["matchReason"] is None for f in client.get(f"/api/projects/{KEY}").json()["research"]["top"])


def test_not_researched_is_not_searched(client):
    key = next(r["key"] for r in client.get("/api/projects", headers=IPMD, params={"size": 50}).json()["items"]
               if r["key"] not in {p["project_key"] for p in serving._research_scope(None)[1]} and r["key"] != KEY)
    d = client.get(f"/api/projects/{key}/research", headers=IPMD).json()
    assert d["searched"] is False and d["facts"] == [] and d["researchedOn"] is None
    assert all(v is None for v in d["external"].values())
    empty = client.get("/api/projects/PRJ-006066/research").json()     # searched, nothing found
    assert empty["searched"] is True and empty["nFacts"] == 0


def test_research_is_scoped(client):
    power, coal = "Ministry of Power", "Ministry of Coal"
    assert client.get(f"/api/projects/{KEY}/research", headers=ministry(power)).status_code == 200
    assert client.get(f"/api/projects/{KEY}/research", headers=ministry(coal)).status_code == 404
    raw = client.get("/api/projects/PRJ-004326", headers=IPMD).json()["master"]["agency"]
    name = serving._one(serving.state(), "SELECT canonical FROM amap WHERE raw = ?", [raw])["canonical"]
    assert client.get("/api/projects/PRJ-004326/research", headers=agency(name)).status_code == 200
    assert client.get(f"/api/projects/{KEY}/research", headers=agency(name)).status_code == 404
    got = client.get("/api/research/summary", headers=agency(name)).json()
    keys = serving.scope_keys(("agency", name))
    assert got["topRecentBlockers"] and all(b["projectKey"] in keys for b in got["topRecentBlockers"])


def test_summary_counts_add_up_across_ministries(client):
    full = client.get("/api/research/summary", headers=IPMD).json()
    cov = full["coverage"]
    assert cov["nSearched"] == 14 and cov["nAgentFacts"] == 2 and cov["nAgentProjects"] == 1
    assert cov["nFacts"] == 45 and cov["nCurrent"] == sum(s["nCurrent"] for s in full["byState"])
    names = [m["name"] for m in client.get("/api/scopes").json()["ministries"]]
    parts = [client.get("/api/research/summary", headers=ministry(m)).json() for m in names]
    for f in ("nCurrent", "nSearched", "nWithFacts", "nFacts", "nNegativeLive", "nProjectsNegativeLive"):
        assert sum(p["coverage"][f] for p in parts) == cov[f], f
    assert sum(c["nLive"] for c in full["byCategory"]) == cov["nNegativeLive"]
    blockers = full["topRecentBlockers"]
    assert "agentfact001" in [b["factId"] for b in blockers] and all(b["projectName"] and b["tier"] for b in blockers)
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
