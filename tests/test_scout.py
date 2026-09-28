import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db  # noqa: E402
from backend.live import scout  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import as_role  # noqa: E402 - tests/viewers.py

ROWS = [
    {"project_key": "PRJ-A", "project_name": "Upgradation and 4L of Haridwar Bypass from Km 0.000 Km 188.100 of NH-58 "
     "PKg-1", "state": "Uttarakhand", "agency": "NHAI", "tier": "Critical", "p_any_2q": .9},
    {"project_key": "PRJ-B", "project_name": "Outer Ring Road of Jabalpur Town from Barela to Manegaon Pkg-1",
     "state": "Madhya Pradesh", "agency": "NHAI", "tier": "High", "p_any_2q": .6},
    {"project_key": "PRJ-C", "project_name": "Outer Ring Road of Jabalpur Town from Barela to Kushner Pkg-3",
     "state": "Madhya Pradesh", "agency": "NHAI", "tier": "Low", "p_any_2q": .1},
    {"project_key": "PRJ-D", "project_name": "Construction of New Domestic Terminal Building at Rajahmundry Airport.",
     "state": "Andhra Pradesh", "agency": "Airport Authority of India [AAI]", "tier": "Medium", "p_any_2q": .3},
] + [  # generic names, so the generic words are frequent as in the real portfolio (DF_MAX)
    {"project_key": f"PRJ-F{i}", "project_name": "Construction and Upgradation of New Domestic Terminal Building, Ring "
     "Road, Bypass and Airport Works from Km 1 to Km 2 near Town", "state": "Bihar", "agency": "MoRTH", "tier": "Low",
     "p_any_2q": .05} for i in range(9)]


def item(title, link, desc=None, source="Times of India", date_="Mon, 02 Feb 2026 07:00:00 GMT"):
    desc = desc or f'&lt;a href="{link}"&gt;{title}&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;{source}&lt;/font&gt;'
    return (f"<item><title>{title} - {source}</title><link>{link}</link><pubDate>{date_}</pubDate>"
            f"<description>{desc}</description><source url=\"https://x\">{source}</source></item>")


RSS = ("<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>q</title>"
       + item("Work on Haridwar bypass stalled as farmers protest over land compensation", "https://n/1")
       + item("Work on Haridwar bypass stalled as farmers protest over land compensation", "https://n/2")  # same text
       + item("Some other story", "https://n/1")  # same URL
       + item("हरिद्वार बाईपास का काम रुका", "https://n/3")  # regional language
       + item("High Court stays tree felling for Jabalpur ring road near Barela", "https://n/4", source="Dainik")
       + item("Sensex closes higher on IT gains", "https://n/5")
       + item("Rajahmundry airport terminal works on track, says AAI", "https://n/6", source="The Hindu")
       + "</channel></rss>")


def test_parse_strips_source_tail_and_html():
    items = scout.parse_rss(RSS, "Google News")
    assert len(items) == 7
    first = items[0]
    assert first["title"] == "Work on Haridwar bypass stalled as farmers protest over land compensation"
    assert first["source"] == "Times of India" and first["summary"] == ""
    assert first["published_at"] == "2026-02-02T07:00:00+00:00"


def test_aliases_drop_boilerplate():
    idx = scout.build_index(ROWS)
    qs = scout.aliases(idx["projects"]["PRJ-A"])
    assert qs == ["Haridwar bypass", "NH 58 Haridwar", "NHAI Haridwar bypass"]  # never the city word alone
    assert not any(w in q.lower() for q in qs for w in ("km", "pkg", "upgradation", "0.000"))
    assert "AAI Rajahmundry" in " | ".join(scout.aliases(idx["projects"]["PRJ-D"]))


def test_link_and_classify():
    idx = scout.build_index(ROWS)
    assert scout.link("Work on Haridwar bypass stalled, Uttarakhand", idx)[::2] == ("PRJ-A", "linked")
    assert scout.link("Jabalpur ring road near Barela", idx)[::2] == (None, "ambiguous")  # two packages tie
    assert scout.link("Sensex closes higher", idx)[2] == "none"
    assert scout.link("Heavy rain in Haridwar, Uttarakhand", idx)[2] == "none"  # a city's general news
    assert scout.link("NHAI reviews works in Haridwar", idx)[::2] == ("PRJ-A", "linked")  # agency as the anchor
    assert scout.classify("farmers protest over land compensation") == ("land", 2)
    assert scout.classify("High Court stays tree felling") == ("forest_env", 3)
    assert scout.classify("terminal works on track") == (None, 1)


@pytest.fixture()
def tmp_db(fresh_db, monkeypatch):
    db.init()
    idx = scout.build_index(ROWS)
    monkeypatch.setattr(scout, "index", lambda: idx)
    return idx


def test_run_stores_dedupes_links_and_alerts(tmp_db, monkeypatch):
    calls = []

    def get(url, params=None):  # canned feed, no network
        calls.append((url, params and params["q"]))
        return RSS
    out = scout.run(["PRJ-A"], pib=False, get=get)
    assert [c[1] for c in calls] == scout.aliases(tmp_db["projects"]["PRJ-A"])
    assert out["regional_skipped"] == len(calls) and out["stored"] == 3 and out["linked"] == 2
    assert out["ambiguous"] == 1 and out["alerts"] == 1
    signals = {r["url"]: r for r in db.signals()}
    links = {ln["signal_id"]: ln["project_key"] for ln in db.signal_links()}
    scouted = list(db.scouted_at())
    assert set(signals) == {"https://n/1", "https://n/4", "https://n/6"}
    assert links == {signals["https://n/1"]["id"]: "PRJ-A", signals["https://n/6"]["id"]: "PRJ-D"}
    assert (signals["https://n/1"]["category"], signals["https://n/1"]["severity"]) == ("land", 2)
    assert signals["https://n/4"]["severity"] == 3  # stored in the unlinked pool, no alert
    alerts = db.alerts(kind="signal")["items"]
    assert [(a["project_key"], a["severity"]) for a in alerts] == [("PRJ-A", 2)]
    assert scouted == ["PRJ-A"]
    again = scout.run(["PRJ-A"], pib=False, get=get)
    assert again.get("stored", 0) == 0 and again["duplicate"] > 0 and db.alerts(kind="signal")["total"] == 1


def test_feed_lead_time_and_heat(tmp_db, monkeypatch):
    scout.run(["PRJ-A"], pib=False, get=lambda url, params=None: RSS)
    monkeypatch.setattr(scout, "cuf_changes", lambda key: [date(2025, 10, 1), date(2026, 4, 1)] if key == "PRJ-A" else [])
    monkeypatch.setattr(scout, "heat", lambda days=90, keys=None: [{"state": "Uttarakhand", "n": 1}])  # published dates are old
    f = scout.feed()
    assert f["total"] == 3 and len(f["items"]) == 3
    a = next(i for i in f["items"] if i["url"] == "https://n/1")
    assert a["projects"][0]["key"] == "PRJ-A"
    assert a["projects"][0]["cuf_change_period"] == date(2026, 4, 1) and a["projects"][0]["lead_days"] == 58
    d = next(i for i in f["items"] if i["url"] == "https://n/6")["projects"][0]
    assert d["cuf_change_period"] is None and d["lead_days"] is None  # no change since: unknown, not zero
    assert [i["url"] for i in scout.feed(linked=False)["items"]] == ["https://n/4"]
    assert scout.feed(severity=2)["total"] == 2 and scout.feed(state="Uttarakhand")["total"] == 1
    assert scout.feed(category="land")["total"] == 1


def test_heat_counts_recent_severe_signals(tmp_db):
    now = scout._now().strftime("%a, %d %b %Y %H:%M:%S GMT")
    rss = RSS.replace("Mon, 02 Feb 2026 07:00:00 GMT", now)
    scout.run(["PRJ-A"], pib=False, get=lambda url, params=None: rss)
    assert scout.heat() == [{"state": "Uttarakhand", "n": 1}]


def test_cuf_changes_on_real_panel():
    from backend import serving
    key = serving.projects(sort="slip", size=1)["items"][0]["key"]
    changes = scout.cuf_changes(key)
    assert changes and all(isinstance(p, date) for p in changes) and changes == sorted(changes)


def test_feed_endpoint_bounds(tmp_db):
    with TestClient(app) as c:
        c.headers.update(as_role(c, "developer"))
        assert c.get("/api/signals/feed", params={"size": 101}).status_code == 422
        assert c.get("/api/signals/feed", params={"severity": 4}).status_code == 422
        body = c.get("/api/signals/feed").json()
        assert body == {"total": 0, "page": 1, "size": 50, "items": [], "stateHeat": []}
        assert c.post("/api/jobs/scout", params={"project_key": "PRJ-999999"}).status_code == 404


def test_worker_scout_reads_only_recorded_evidence(tmp_db, monkeypatch):
    from backend import serving
    from llm import worker
    prompts = []
    monkeypatch.setattr(worker, "call_llm", lambda system, user, schema: prompts.append(user) or schema(tags=[]))
    s = serving.state()
    with_events = serving._rows(s, "SELECT project_key FROM cur WHERE project_key IN (SELECT project_key FROM events)"
                                   " ORDER BY project_key LIMIT 1")[0]["project_key"]
    bare = serving._rows(s, "SELECT project_key FROM cur WHERE project_key NOT IN (SELECT project_key FROM events)"
                            " ORDER BY project_key LIMIT 1")[0]["project_key"]
    assert worker.scout({"project_key": bare}) == (worker.ScoutOutput(tags=[]), []) and prompts == []  # no evidence
    tags, signals = worker.scout({"project_key": with_events})
    assert "report remark" in prompts[0] and " p." in prompts[0] and signals == []
    db.save_signals([{"url": "https://n/9", "title": "Work halted", "source": "PTI", "published_at": "2026-08-01",
                      "severity": 2, "links": [(bare, None, None)]}])
    _, signals = worker.scout({"project_key": bare})
    assert [x["url"] for x in signals] == ["https://n/9"] and "news, 2026-08-01, PTI" in prompts[1]
