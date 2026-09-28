"""GET /api/projects/{key}/second-opinion with a fake LLM (client.chat): access, statuses, cache and regeneration."""
import json
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.main import app  # noqa: E402
from llm import client as llm_client  # noqa: E402
from llm import second_opinion as so  # noqa: E402

KEY = "PRJ-000698"      # Vishnugad Pipalkoti (THDC India Limited, Ministry of Power)
URL = "/api/projects/{}/second-opinion"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PAIMANA_DB", str(tmp_path_factory.mktemp("db") / "paimana.db"))
        with TestClient(app, headers={"X-Paimana-Role": "ipmd_analyst"}) as c:
            yield c
    llm_client._down_at = -1e9


def add_signal(key, url, title, published="2026-08-02T06:00:00+00:00"):
    """A severity-2 news item linked to key: a current hold-up in its evidence pack."""
    with closing(db.connect()) as con, con:
        sid = con.execute("""INSERT INTO signals (url, url_hash, title, source, published_at, fetched_at, summary,
            category, severity, text_hash) VALUES (?, ?, ?, 'PTI', ?, ?, '', 'law_order', 2, ?)""",
                          [url, url[-12:], title, published, published, url]).lastrowid
        con.execute("INSERT INTO signal_projects VALUES (?, ?, 0.75, 'places+context')", [sid, key])


def answer(narrative=None):
    """A fake client.chat: a reply that passes the checks for the pack in the prompt's project (or with narrative)."""
    calls = []

    def chat(messages, max_tokens=400, temperature=0.2, model=None):
        calls.append(messages)
        key = next(k for k in (KEY, "PRJ-002112", "PRJ-004326", "PRJ-001354") if so.pack(k)["name"] in
                   messages[1]["content"])
        p = so.pack(key)
        strong = next(it["id"] for it in p["items"] if it["direction"] == "negative" and not it["stale"]
                      and it["severity"] >= 2)
        return json.dumps({"concern": "concern", "headline": "Work on site is held up",
                           "narrative": narrative or f"Work was reported stopped after a protest [{strong}]. The "
                                                     "report shows much of the work done [E1].",
                           "key_evidence": [strong],
                           "gaps": ["No source says when work restarts"]})
    chat.calls = calls
    return chat


def test_public_is_403_and_an_agency_outside_its_scope_404(client):
    with TestClient(app) as public:
        assert public.get(URL.format(KEY)).status_code == 403
        assert public.get(URL.format(KEY), params={"cached": 1}).status_code == 403
    agencies = {a["name"] for a in client.get("/api/scopes").json()["agencies"]}
    own = serving.rows_for_keys((KEY,))[0]["agency"]
    mine = serving.state()["con"].execute("SELECT canonical FROM amap WHERE raw = ?", [own]).fetchone()[0]
    assert mine in agencies and "NHAI" in agencies and KEY not in serving.scope_keys(("agency", "NHAI"))
    h = {"X-Paimana-Role": "agency_official", "X-Paimana-Agency": quote("NHAI")}
    assert client.get(URL.format(KEY), headers=h, params={"cached": 1}).status_code == 404
    assert client.get(URL.format(KEY), headers=h).status_code == 404
    h = {"X-Paimana-Role": "agency_official", "X-Paimana-Agency": quote(mine)}
    assert client.get(URL.format(KEY), headers=h, params={"cached": 1}).json()["status"] == "none"
    assert client.get(URL.format("PRJ-999999")).status_code == 404


def test_cached_only_never_generates(client, monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("?cached=1 must not call the LLM")
    monkeypatch.setattr(llm_client, "chat", boom)
    r = client.get(URL.format(KEY), params={"cached": 1})
    assert r.status_code == 200 and r.json() == {"status": "none", "key": KEY,
                                                 "detail": "no second opinion for the current evidence yet"}
    s = serving.state()
    past = s["con"].execute("SELECT project_key FROM master WHERE project_key NOT IN (SELECT project_key FROM cur) "
                            "ORDER BY project_key LIMIT 1").fetchone()[0]
    assert client.get(URL.format(past), params={"cached": 1}).status_code == 404
    assert client.get(URL.format(past)).status_code == 404


def test_generates_caches_and_asks_again_when_the_evidence_changes(client, monkeypatch):
    add_signal(KEY, "https://n/stopped", "Work stopped at Vishnugad site after protest")
    chat = answer()
    monkeypatch.setattr(llm_client, "chat", chat)
    r = client.get(URL.format(KEY))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ok" and not out["cached"] and out["concern"] == "concern" and out["tier"] == "Medium"
    assert out["modelLevel"] == "watch" and out["vsModel"] == "higher" and out["keyEvidence"] and out["cited"]
    assert out["evidence"][0]["id"] == "E1" and {"kind", "direction", "stale", "source", "text", "url"} <= set(
        out["evidence"][0]) and len(out["evidenceHash"]) == 64 and out["promptVersion"] == so.PROMPT_VERSION
    # the count the card shows is what the LLM read; the news item links to its source, the status line to nothing
    read = [e for e in out["evidence"] if e["direction"] != "context"]
    assert out["nEvidenceRead"] == len(read) < len(out["evidence"])
    assert next(e["url"] for e in out["evidence"] if e["kind"] == "news") == "https://n/stopped"
    assert next(e["url"] for e in out["evidence"] if e["kind"] == "status") is None
    again = client.get(URL.format(KEY)).json()                      # same evidence: the stored opinion
    assert again["cached"] and again["narrative"] == out["narrative"] and len(chat.calls) == 1
    only = client.get(URL.format(KEY), params={"cached": 1}).json()
    assert only["status"] == "ok" and only["cached"] and only["evidenceHash"] == out["evidenceHash"]
    add_signal(KEY, "https://n/again", "Protest halts Vishnugad tunnel work again", "2026-08-09T06:00:00+00:00")
    assert client.get(URL.format(KEY), params={"cached": 1}).json()["status"] == "none"
    new = client.get(URL.format(KEY)).json()                        # new evidence: asked again
    assert new["status"] == "ok" and not new["cached"] and new["evidenceHash"] != out["evidenceHash"]
    assert len(chat.calls) == 2 and len(db.second_opinions(KEY)) == 2


def test_citations_that_do_not_exist_are_422(client, monkeypatch):
    key = "PRJ-002112"
    add_signal(key, "https://n/kumta", "Land dispute stops highway work near Kumta")
    chat = answer("Work stopped near Kumta over a land dispute [E77] and nothing says it restarted [E78].")
    monkeypatch.setattr(llm_client, "chat", chat)
    r = client.get(URL.format(key))
    assert r.status_code == 422 and r.json()["status"] == "rejected" and r.json()["attempts"] == 2
    assert any("not in the list" in x and "E77" in x for x in r.json()["reasons"]) and len(chat.calls) == 2
    assert client.get(URL.format(key), params={"cached": 1}).json()["status"] == "none"


def test_numbers_not_in_the_pack_are_422_and_the_retry_names_them(client, monkeypatch):
    key = "PRJ-004326"
    add_signal(key, "https://n/tower", "Tower relocation stalls Sriperumbudur expressway work")
    p = so.pack(key)
    strong = next(it["id"] for it in p["items"] if it["direction"] == "negative" and not it["stale"]
                  and it["severity"] >= 2)
    chat = answer(f"Work has been stalled for 97.5 days by a tower relocation [{strong}] on the stretch.")
    monkeypatch.setattr(llm_client, "chat", chat)
    r = client.get(URL.format(key))
    assert r.status_code == 422 and any("'97.5' is not in the evidence items" in x for x in r.json()["reasons"])
    assert "97.5" in chat.calls[1][1]["content"]


def test_llm_down_is_503_quickly_and_remembered(client, monkeypatch):
    key = "PRJ-001354"
    monkeypatch.setattr(llm_client, "LLM_BASE_URL", "http://127.0.0.1:9/v1")    # nothing listens there
    t0 = time.time()
    r = client.get(URL.format(key))
    assert r.status_code == 503 and r.json()["status"] == "llm_unavailable" and time.time() - t0 < 10
    assert r.json()["down"] is True and r.json()["busy"] is False       # refused: start LM Studio
    t0 = time.time()                                       # remembered: the next ask does not wait again
    r = client.get(URL.format(key))
    assert r.status_code == 503 and r.json()["down"] is True and time.time() - t0 < 1
    llm_client._down_at = -1e9                             # forget the outage for the next tests

    def slow(messages, **kw):
        raise llm_client.LLMTimeoutError("LM Studio did not answer in time (ReadTimeout)")
    monkeypatch.setattr(llm_client, "chat", slow)
    r = client.get(URL.format(key))                        # up, only slow: not 'down', so not 'start LM Studio'
    assert r.status_code == 503 and r.json()["down"] is False and r.json()["busy"] is False
    assert "did not answer in time" in r.json()["detail"]
