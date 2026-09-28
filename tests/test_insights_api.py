"""Agency matrix, bottlenecks, radar summary, models page and the project brief (B 6, B 8 rows 7-9)."""
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import brief, serving  # noqa: E402
from backend.main import app  # noqa: E402
from llm import client as llm_client  # noqa: E402
from viewers import as_role  # noqa: E402 - tests/viewers.py

MAX_ROWS = 100


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        as_role(c, "developer")   # the models page and the model numbers are the developer's
        yield c


@pytest.fixture(scope="module")
def top_key(client):
    return client.get("/api/projects", params={"size": 1}).json()["items"][0]["key"]


# ------------------------------------------------------------------ agencies

def test_agency_matrix_hides_small_agencies_and_merges_names(client):
    m = client.get("/api/agencies/matrix").json()
    pts = m["points"]
    assert 0 < len(pts) <= 500 and m["nAgencies"] >= len(pts) and m["method"]
    assert all(p["nProjects"] >= 5 and not p["hidden"] for p in pts)
    assert all(p["scheduleBiasCiLo"] <= p["scheduleBiasRaw"] <= p["scheduleBiasCiHi"] for p in pts)
    assert all(p["scheduleBias"] == p["scheduleBiasRaw"] for p in pts if p["nProjects"] >= 10)
    nhai = next(p for p in pts if p["agency"] == "NHAI")
    assert "NATIONAL HIGHWAYS AUTHORITY OF INDIA" in nhai["names"] and nhai["nProjects"] > 1000
    every = client.get("/api/agencies/matrix", params={"include_hidden": True}).json()["points"]
    assert len(every) == m["nAgencies"] and any(p["hidden"] for p in every)
    roads = client.get("/api/agencies/matrix", params={"sector": "Roads & Highways"}).json()["points"]
    assert roads and all(p["sector"] == "Roads & Highways" for p in roads)


def test_agency_projects_page_through_every_printed_name(client):
    nhai = next(p for p in client.get("/api/agencies/matrix").json()["points"] if p["agency"] == "NHAI")
    page = client.get("/api/agencies/NHAI/projects", params={"size": 100}).json()
    assert page["total"] == nhai["nOpen"] and len(page["items"]) == 100
    assert {r["agency"] for r in page["items"]} <= {"NHAI", "National Highways Authority of India [NHAI]",
                                                     "NATIONAL HIGHWAYS AUTHORITY OF INDIA",
                                                     "NATIONAL HIGHWAYS DEVELOPMENT PROJECT"}
    probs = [r["pAny2q"] for r in page["items"] if r["pAny2q"] is not None]
    assert probs == sorted(probs, reverse=True)
    assert client.get("/api/agencies/nhai/projects", params={"size": 1}).json()["total"] == page["total"]
    assert client.get("/api/agencies/NO SUCH AGENCY/projects").status_code == 404
    assert client.get("/api/agencies/NHAI/projects", params={"size": 101}).status_code == 422


# ------------------------------------------------------------------ bottlenecks

def test_bottlenecks_list_and_detail(client):
    b = client.get("/api/bottlenecks").json()
    assert b["total"] == b["summary"]["n_bottlenecks"] + b["summary"]["n_rollups"] and b["items"]
    for it in b["items"]:
        assert it["nProjects"] >= 3 and len(it["topMembers"]) <= 5 and it["topMembers"]
        assert it["headline"].startswith(f"Blocking {it['nProjects']} projects worth Rs ")
        assert "speed" not in (it["headline"] + it["note"]).lower() and "not a causal claim" in it["note"]
    caps = [it["capitalExposedCr"] for it in b["items"]]
    assert caps == sorted(caps, reverse=True)
    first = b["items"][0]
    d = client.get(f"/api/bottlenecks/{first['bottleneckId']}").json()
    assert d["total"] == first["nProjects"] == len(d["members"])
    assert all(m["evidence"] and m["evidence"][0]["evidence"] for m in d["members"])
    assert d["bottleneck"]["topMembers"] == first["topMembers"]
    assert client.get(f"/api/bottlenecks/{first['bottleneckId']}", params={"page": 99}).json()["members"] == []
    assert client.get("/api/bottlenecks/BN-nope").status_code == 404
    big = client.get("/api/bottlenecks", params={"min_projects": first["nProjects"] + 1000}).json()
    assert big["total"] == 0 and big["items"] == []
    land = client.get("/api/bottlenecks", params={"category": "land", "level": "authority"}).json()["items"]
    assert all(it["category"] == "land" and it["level"] == "authority" for it in land)


def test_new_endpoints_never_return_more_than_100_project_rows(client, top_key):
    bid = client.get("/api/bottlenecks").json()["items"][0]["bottleneckId"]
    for path in ("/api/agencies/matrix", "/api/agencies/matrix?include_hidden=true", "/api/agencies/NHAI/projects",
                 "/api/agencies/NHAI/projects?size=100", "/api/bottlenecks", "/api/bottlenecks?size=100",
                 f"/api/bottlenecks/{bid}?size=100", "/api/radar/summary", "/api/models"):
        r = client.get(path)
        assert r.status_code == 200, path

        def lists(v):
            if isinstance(v, dict):
                return [x for w in v.values() for x in lists(w)]
            if isinstance(v, list):
                own = [v] if v and all(isinstance(x, dict) and "key" in x for x in v) else []
                return own + [x for w in v for x in lists(w)]
            return []
        assert all(len(rows) <= MAX_ROWS for rows in lists(r.json())), path


# ------------------------------------------------------------------ radar, models

def test_radar_summary_on_an_empty_database(client):
    r = client.get("/api/radar/summary").json()
    assert r["windowDays"] == 90 and r["nSignalsTotal"] == 0 and r["nLinked"] + r["nUnlinked"] == r["nWindow"]
    assert r["leadTime"]["nLinkedPairs"] == 0 and r["leadTime"]["medianLeadDays"] is None


def test_models_page_has_registry_calibration_shap_and_honest_live_accuracy(client):
    m = client.get("/api/models").json()
    assert 0 < len(m["shapSummary"]) <= 20 and "meanAbsShap" in m["shapSummary"][0]
    shap = [r["meanAbsShap"] for r in m["shapSummary"]]
    assert shap == sorted(shap, reverse=True)
    assert m["calibration"] and {"bin", "meanPred", "obsRate"} <= set(m["calibration"][0])
    assert any(r["champion"] for r in m["registry"]) and all("reason" in d for d in m["decisions"])
    live = m["liveAccuracy"]
    assert live["nLogged"] > 0 and live["note"]
    if live["nRealised"] == 0:   # today: nothing realised, so no metric at all
        assert live["precisionCriticalHigh"] is None and live["prAuc"] is None and live["baseRate"] is None
    assert serving.average_precision([1, 0, 1, 0], [.9, .8, .7, .1]) == pytest.approx((1 + 2 / 3) / 2)


# ------------------------------------------------------------------ brief

def test_validator_accepts_payload_numbers_and_their_formats():
    facts = {"p": 0.8712, "months": 6.34, "cost_cr": 12345.6, "asof": "2026-07-01", "pct": 18.0,
             "evidence": "NH-161: 1,699 parcels, notifications over 5 years", "name": "Four Laning of NH-161",
             "fc": "FC got on 28.10.2021"}
    for text in ("P = 0.87, or 87%; 87.1% if you like.", "Slip 6.3 months (6 months).", "Rs 12,345.6 Cr, Rs 12,346 Cr",
                 "As of 2026-07-01, in 2026.", "Cost variation 18%, or 0.18.", "1,699 parcels on NH-161 over 5 years.",
                 "Rs.12,346 Cr, INR12,346 crore", "As of July 2026 (1 Jul 2026, 01/07/2026, Jul-2026, 07/2026).",
                 "Four Laning of NH-161: one of the drivers is at 87 per cent.", "FC got on 28.10.2021."):
        ok, reasons, n = brief.validate(text, facts)
        assert ok and n > 0, (text, reasons)


def test_validator_rejects_invented_numbers():
    facts = {"p": 0.8712, "months": 6.34, "cost_cr": 12345.6, "asof": "2026-07-01"}
    for text, bad in (("P = 0.91.", "0.91"), ("Slip 9 months.", "9"), ("Rs 13,000 Cr.", "13,000"),
                      ("Due 2026-09-01.", "2026-09-01"), ("Over 7 quarters.", "7"), ("A 45% chance.", "45%"),
                      # after a letter or a lone period, a bare decimal, digits after letters
                      ("Cost Rs.999 Cr.", "999"), ("Cost Rs999 Cr.", "999"), ("Cost INR999 crore.", "999"),
                      ("Probability .99 of slipping.", ".99"), ("The p99 slip.", "99"), ("0.87,0.91", "0.91"),
                      # words, month-name and dotted dates, a fraction marked as a percent, truncation
                      ("A seventy-one percent chance.", "seventy"), ("About three years late.", "three"),
                      ("Due March 2026.", "March 2026"), ("Due Dec-2026.", "Dec-2026"), ("Due 09/2026.", "09/2026"),
                      ("Done on 28.10.2099.", "28.10.2099"), ("P is 0.8 per cent.", "0.8 per cent"),
                      ("P = 0.8.", "0.8"), ("Rs 12,345 Cr.", "12,345")):
        ok, reasons, _ = brief.validate(text, facts)
        assert not ok and any(bad in r for r in reasons), (text, reasons)
    assert not brief.validate("   ", facts)[0]


def test_brief_is_503_quickly_when_the_llm_is_down(client, top_key, monkeypatch):
    monkeypatch.setattr(llm_client, "LLM_BASE_URL", "http://127.0.0.1:9/v1")   # nothing listens there
    t0 = time.time()
    r = client.get(f"/api/projects/{top_key}/brief")
    assert r.status_code == 503 and r.json()["status"] == "llm_unavailable"
    assert time.time() - t0 < 10
    t0 = time.time()                                   # remembered: the next ask does not wait again
    assert client.get(f"/api/projects/{top_key}/brief").status_code == 503 and time.time() - t0 < 1
    assert llm_client.down_recently()                  # through the client's breaker, shared with the chat
    llm_client._down_at = -1e9                         # forget the outage for the next tests


def test_brief_shares_the_clients_breaker_and_a_timeout_does_not_trip_it(client, top_key, monkeypatch):
    calls = []

    def slow(system, user):
        calls.append(user)
        raise llm_client.LLMTimeoutError("LM Studio did not answer in time (ReadTimeout)")
    monkeypatch.setattr(llm_client, "complete", slow)
    monkeypatch.setattr(llm_client, "_down_at", -1e9)
    r = client.get(f"/api/projects/{top_key}/brief")
    assert r.status_code == 503 and "did not answer in time" in r.json()["detail"]
    assert not llm_client.down_recently()              # LM Studio is up, only slow: not marked down
    assert client.get(f"/api/projects/{top_key}/brief").status_code == 503 and len(calls) == 2   # asked again
    llm_client.mark_down()                             # the chat found the connection refused just now
    assert client.get(f"/api/projects/{top_key}/brief").status_code == 503 and len(calls) == 2   # not asked
    assert "unreachable in the last" in client.get(f"/api/projects/{top_key}/brief").json()["detail"]
    monkeypatch.setattr(llm_client, "_down_at", -1e9)
    with llm_client.gate(1) as ok:                     # the request ahead holds the LLM and finds it down
        assert ok
        seen = []
        t = threading.Thread(target=lambda: seen.append(client.get(f"/api/projects/{top_key}/brief").json()))
        t.start()
        time.sleep(0.2)
        llm_client.mark_down()
    t.join(5)
    assert seen[0]["status"] == "llm_unavailable" and "unreachable" in seen[0]["detail"] and len(calls) == 2
    monkeypatch.setattr(llm_client, "_down_at", -1e9)


def test_brief_waits_for_the_llm_gate_and_says_busy(client, top_key, monkeypatch):
    other = client.get("/api/projects", params={"size": 1, "page": 3}).json()["items"][0]["key"]
    calls = []
    monkeypatch.setattr(llm_client, "complete", lambda system, user: calls.append(user) or "x")
    monkeypatch.setattr(brief, "BUSY_WAIT_S", 0.2)
    assert llm_client.LLM_GATE.acquire(timeout=1)       # a chat answer is generating
    try:
        r = client.get(f"/api/projects/{other}/brief")
    finally:
        llm_client.LLM_GATE.release()
    assert r.status_code == 503 and "busy" in r.json()["detail"] and calls == []


def test_brief_accepts_caches_and_rejects(client, top_key, monkeypatch):
    facts = brief.payload(top_key)
    p = facts["prediction"]
    good = (f"The model rates this project {p['tier']}: P(any slip, 2 quarters) = {p['p_any_2q']}.\n\n"
            f"The expected slip is {p['slip_months_p50']} months.")
    calls = []
    monkeypatch.setattr(llm_client, "complete", lambda system, user: calls.append(user) or good)
    r = client.get(f"/api/projects/{top_key}/brief")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ok" and not out["cached"] and len(out["paragraphs"]) == 2 and out["payload"]
    again = client.get(f"/api/projects/{top_key}/brief").json()
    assert again["cached"] and again["text"] == good and len(calls) == 1

    other = client.get("/api/projects", params={"size": 1, "page": 2}).json()["items"][0]["key"]
    calls.clear()
    monkeypatch.setattr(llm_client, "complete", lambda system, user: calls.append(user) or "It will slip 97.5 months.")
    r = client.get(f"/api/projects/{other}/brief")
    assert r.status_code == 422 and r.json()["status"] == "rejected"
    assert any("97.5" in x for x in r.json()["reasons"]) and len(calls) == 2
    assert "97.5" in calls[1] and "rejected" in calls[1]            # the retry names the offending number
    assert client.get("/api/projects/PRJ-999999/brief").status_code == 404
