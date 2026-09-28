"""backend/live/portals.py on canned pages (no network): the PARIVESH dashboard snapshot, the Bhoomi Rashi pull with
its truncation guard, their job_runs rows, the scheduler switches and the IPMD-only trigger endpoints."""
import asyncio
import re
import sys
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db  # noqa: E402
from backend.live import portals, scheduler, scout, watcher  # noqa: E402
from backend.main import app  # noqa: E402

DAY = date(2026, 9, 28)
EXPORT_HEADER = ["State", "Highway Name", "Chainage", "District", "Sub District", "Village", "Survey No", "Area",
                 "Publish Date"]
EXPORT_ROWS = [["STATE", "48", "10.000 - 30.000", "SURAT", "Olpad", "Kim", "12/A", "1.5", "15/01/2019"],
               ["", "", "", "", "", "", "13", "2.25", "20/03/2020"],
               ["", "48", "30.000 - 32.000", "BHARUCH", "Ankleshwar", "Kosamba", "8", "0.5", "05/05/2021"]]
LEVELS = ["Sr. No.", "State Name", "User Agency", "Divisional Forest Officer (DFO)", "Pending Email", "Remarks",
          "Total Submitted Proposals"]
STATE_ROWS = [["1", "GOA", "3", "1", "dfo.goa@example.gov.in", "nodal: nodal.fc@example.gov.in", "12"],
              ["2", "KERALA", "5", "2", "", "", "40"], ["", "TOTAL", "8", "3", "", "", "52"]]


def table(header, rows, th=True):
    tr = lambda cells, td="td": "<tr>" + "".join(f"<{td}>{c}</{td}>" for c in cells) + "</tr>"   # noqa: E731
    return "<table>" + tr(header, "th" if th else "td") + "".join(tr(r) for r in rows) + "</table>"


DASHBOARD = ("<html><body><span id='lblDate'>Last Updated On: 27-Sep-26 02:15 AM</span>"
             + table(["Region", "Pending Count"], [["RO Bhopal", "7"]]) + table(LEVELS, STATE_ROWS) + "</body></html>")
REPSTATE = ('<form action="state_register1.cshtml" method="post"><INPUT TYPE="HIDDEN" NAME="EncHid" id="EncHid" '
            'VALUE="881552512"><select name="highway_id" id="highway_id"><option value="-1">Select State</option>'
            '<option value="ANDAMAN &amp; NICOBAR ISLANDS">ANDAMAN &amp; NICOBAR ISLANDS</option>'
            '<option value="GOA">GOA</option><option value="HARYANA">HARYANA</option>'
            '<option value="KERALA">KERALA</option></select></form>')


def export_page(state, rows=EXPORT_ROWS):
    rows = [[state if c == "STATE" else c for c in r] for r in rows]
    return "<html><body>" + table(EXPORT_HEADER, rows, th=False) + "</body></html>"


def streamed(body: bytes, length: int | None = None) -> httpx.Response:
    """A response read off the wire (not preloaded), with a Content-Length header when given."""
    return httpx.Response(200, stream=httpx.ByteStream(body),
                          headers={"Content-Length": str(length)} if length is not None else None)


@pytest.fixture
def portal(tmp_path, monkeypatch):
    """Canned portals behind an httpx MockTransport; every request is logged in calls."""
    monkeypatch.setenv("PAIMANA_DB", str(tmp_path / "paimana.db"))
    db.init()
    monkeypatch.setattr(portals, "SNAPSHOTS", tmp_path / "parivesh2_snapshots")
    monkeypatch.setattr(portals, "PULLS", tmp_path / "bhoomi_rashi_pulls")
    monkeypatch.setattr(portals, "EXPORT_GAP_S", 0.0)
    monkeypatch.setattr(portals, "MIN_GAP_S", 0.0)
    calls, tries = [], {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "parivesh.nic.in":
            calls.append("dashboard")
            return httpx.Response(200, text=DASHBOARD)
        if req.method == "GET":
            calls.append("RepState")
            return httpx.Response(200, text=REPSTATE)
        body = req.content.decode()
        assert all(f'name="{k}"\r\n\r\n{v}\r\n' in body
                   for k, v in {"EncHid": "881552512", "act": "1", "type": "2", "but": "Submit"}.items())
        state = re.search(r'name="highway_id"\r\n\r\n([^\r]*)', body).group(1)
        calls.append(state)
        tries[state] = tries.get(state, 0) + 1
        page = export_page(state).encode()
        if state == "ANDAMAN & NICOBAR ISLANDS":                      # the portal's empty table
            return streamed(export_page(state, rows=[]).encode())
        if state == "HARYANA" and tries[state] == 1:                   # cut off below its Content-Length, once
            return streamed(page[:60], len(page))
        if state == "KERALA":                                           # never closes its table
            return streamed(page[:-len("</table></body></html>")])
        return streamed(page, len(page))

    monkeypatch.setattr(portals, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return calls


def test_client_sends_the_research_user_agent():
    with portals._client() as c:
        assert c.headers["user-agent"] == portals.USER_AGENT and "@" not in portals.USER_AGENT


def test_snapshot_archives_the_state_table_once_per_date_without_emails(portal):
    out = portals.snapshot_once(DAY)
    assert out["file"] == "parivesh2_snapshots/2026-09-28.csv" and out["states"] == 2 and out["total_proposals"] == 52
    t = pd.read_csv(portals.SNAPSHOTS / "2026-09-28.csv")
    assert t["State Name"].tolist() == ["GOA", "KERALA", "TOTAL"] and "Pending Email" not in t
    assert not t.astype("str").apply(lambda c: c.str.contains("@")).any().any()
    assert t["source"].iloc[0].endswith("(State-wise Status of FC Proposals, last updated 27-Sep-2026 02:15)")
    assert t["retrieved"].iloc[0] == "2026-09-28"
    assert portals.snapshot_once(DAY) == {"skipped": True, "file": "parivesh2_snapshots/2026-09-28.csv"}
    assert portal == ["dashboard"]                                     # the second call did not fetch
    assert [r["status"] for r in db.latest_jobs() if r["job"] == "parivesh_snapshot"] == ["ok"]


def test_snapshot_of_a_changed_page_is_an_error_row_and_no_file(portal, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "DASHBOARD", "<html><body>Service unavailable</body></html>")
    out = portals.snapshot_once(DAY)
    assert out["error"].startswith("ValueError: no 'State-wise Status") and not portals.SNAPSHOTS.exists()
    assert [r["status"] for r in db.latest_jobs() if r["job"] == "parivesh_snapshot"] == ["error"]


def test_bhoomi_pull_retries_a_truncated_export_and_keeps_only_stretches(portal):
    out = portals.bhoomi_pull(today=DAY)
    by = {r["state"]: r for r in out["states"]}
    assert by["GOA"]["status"] == "ok" and by["GOA"]["retried"] is False and by["GOA"]["stretches"] == 2
    assert by["HARYANA"]["status"] == "ok" and by["HARYANA"]["retried"] is True        # guard caught the cut copy
    assert by["ANDAMAN & NICOBAR ISLANDS"]["status"] == "empty"
    assert by["KERALA"]["status"] == "truncated" and "</table>" in by["KERALA"]["error"]
    assert out["failed"] == ["KERALA"] and (out["n_ok"], out["n_empty"], out["stretches"]) == (2, 1, 4)
    assert portal.count("KERALA") == 2 and portal.count("HARYANA") == 2 and portal.count("GOA") == 1
    assert [p.name for p in portals.PULLS.iterdir()] == ["2026-09-28.csv"]            # no raw export kept
    st = pd.read_csv(portals.PULLS / "2026-09-28.csv")
    assert st["state"].tolist() == ["GOA", "GOA", "HARYANA", "HARYANA"] and "survey_no" not in st
    assert st.columns.tolist() == portals.STRETCH_COLS
    assert [r["status"] for r in db.latest_jobs() if r["job"] == "bhoomi_rashi_pull"] == ["partial"]
    # a second run the same day for one state keeps the other states of the day
    again = portals.bhoomi_pull(["GOA", "SIKKIM"], today=DAY)
    assert again["unknown_states"] == ["SIKKIM"] and [r["state"] for r in again["states"]] == ["GOA"]
    assert pd.read_csv(portals.PULLS / "2026-09-28.csv")["state"].value_counts().to_dict() == {"GOA": 2, "HARYANA": 2}


def test_register_form_reads_the_states_and_an_empty_enchid():
    assert portals.register_form(REPSTATE) == ("881552512", ["ANDAMAN & NICOBAR ISLANDS", "GOA", "HARYANA", "KERALA"])
    assert portals.register_form(REPSTATE.replace(' VALUE="881552512"', ""))[0] == ""
    with pytest.raises(ValueError, match="state dropdown"):
        portals.register_form("<html>Error</html>")


def test_bhoomi_pull_only_when_due(portal):
    portals.PULLS.mkdir()
    (portals.PULLS / "2026-08-01.csv").write_text(",".join(portals.STRETCH_COLS) + "\n")
    assert portals.pull_if_due(91, today=DAY) == {"skipped": True, "last_pull": "2026-08-01"} and portal == []
    assert portals.pull_if_due(30, today=DAY)["n_ok"] == 2


def test_scheduler_switches(monkeypatch):
    ran = []
    monkeypatch.setenv("LIVE_JOBS", "1")
    monkeypatch.setattr(scheduler, "STATUS", {j: dict(v) for j, v in scheduler.STATUS.items()})
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    monkeypatch.delenv("PARIVESH_SNAPSHOT", raising=False)
    monkeypatch.setattr(scheduler, "PORTALS_FIRST_DELAY_S", 0.05)
    monkeypatch.setattr(scheduler, "SCOUT_FIRST_DELAY_S", 60)
    monkeypatch.setattr(watcher, "watch_once", lambda: None)
    monkeypatch.setattr(scout, "batch", lambda: None)
    monkeypatch.setattr(portals, "snapshot_once", lambda: ran.append("snapshot"))
    monkeypatch.setattr(portals, "pull_if_due", lambda every_d: ran.append(f"pull {every_d}"))

    async def names():
        tasks = scheduler.start()
        await asyncio.sleep(0.3)
        await scheduler.stop(tasks)
        return [t.get_name() for t in tasks]
    assert asyncio.run(names()) == ["watch", "scout", "parivesh_snapshot"] and ran == ["snapshot"]
    monkeypatch.setenv("BHOOMI_PULL", "1")
    monkeypatch.setenv("BHOOMI_PULL_EVERY_D", "30")
    monkeypatch.setenv("PARIVESH_SNAPSHOT", "0")
    assert asyncio.run(names()) == ["watch", "scout", "bhoomi_rashi_pull"] and ran[-1] == "pull 30"


def test_trigger_endpoints_are_ipmd_only_and_bhoomi_is_off_by_default(portal, monkeypatch):
    monkeypatch.delenv("BHOOMI_PULL", raising=False)
    with TestClient(app, headers={"X-Paimana-Role": "public"}) as c:
        assert c.post("/api/jobs/parivesh-snapshot").status_code == 403
        assert c.post("/api/jobs/bhoomi-pull").status_code == 403
    with TestClient(app, headers={"X-Paimana-Role": "ipmd_analyst"}) as c:
        assert c.post("/api/jobs/parivesh-snapshot").json()["started"] is True
        assert portals.snapshot_path().exists() and portal == ["dashboard"]   # the background task ran
        s = c.post("/api/jobs/parivesh-snapshot").json()
        assert s["started"] is False and s["detail"].endswith("is already archived")
        s = c.post("/api/jobs/bhoomi-pull").json()
        assert s == {"started": False, "detail": "the Bhoomi Rashi pull is off (BHOOMI_PULL=0)", "pending": None,
                     "summary": None}
        live = c.get("/api/live/status").json()
        assert live["bhoomiPullEnabled"] is False and {"pariveshSnapshot", "bhoomiRashiPull"} <= set(live)
        monkeypatch.setenv("BHOOMI_PULL", "1")
        assert c.post("/api/jobs/bhoomi-pull", params={"state": "goa"}).json()["started"] is True
        assert portal[1:] == ["RepState", "GOA"]
        runs = {r["job"]: r for r in c.get("/api/jobs").json()}
        assert runs["bhoomi_rashi_pull"]["summary"]["n_ok"] == 1 and runs["parivesh_snapshot"]["status"] == "ok"
