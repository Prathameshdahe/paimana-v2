"""Public-portal refresh jobs. Evidence and display only: the 2026-09 research found no backtest lift from either
source, so nothing here feeds the model.

parivesh_snapshot archives the 'State-wise Status of FC Proposals' table (proposals by state and level) of the
PARIVESH 2.0 FC Authority Dashboard to raw/external/parivesh2_snapshots/<date>.csv, in the layout of
raw/external/parivesh2_fc_state_levels_2026-09-27.csv. The dashboard keeps no history, so these files are its only
point-in-time record. A date already archived is not fetched again: the scheduler can tick every few hours and a
failed fetch is retried the same day.

bhoomi_rashi_pull pulls the Bhoomi Rashi whole-state Highway Register of every state in the RepState dropdown (or
the ones given), parses and aggregates each export to NH stretches (pipeline/bhoomi_rashi.py) and writes them to
raw/external/bhoomi_rashi_pulls/<date>.csv; pipeline/external.py load_land then reads each state from the newest
pull that has it. A raw export (0.7-74 MB, about 731 MB for all states) lives only in a temporary folder while it
is parsed. An export shorter than its Content-Length, cut off mid-transfer or without a closing </table> is
truncated (the Haryana export was once cut at 15.9 of 51.0 MB and still parsed): it is retried once, then that state
is skipped and the run is 'partial'. Off unless BHOOMI_PULL=1 (backend/live/scheduler.py).

Both read public pages with no login or captcha, send the User-Agent of pipeline/parivesh.py, make at most one
request per second, run one at a time each and write a job_runs row whenever they fetched. Nothing that looks like
an e-mail address is archived.
"""
import html
import io
import re
import tempfile
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

from backend import db
from pipeline.bhoomi_rashi import STRETCH_COLS, aggregate_stretches, parse_bhoomi_rashi
from pipeline.external import read_land
from pipeline.parivesh import EMAIL, EXTERNAL, MIN_GAP_S, USER_AGENT

DASHBOARD_URL = "https://parivesh.nic.in/fc-dashboard/FCDashboard.aspx"
DASHBOARD_TABLE = {"State Name", "Total Submitted Proposals"}
SNAPSHOTS = EXTERNAL / "parivesh2_snapshots"
BHOOMI = "https://bhoomirashi.gov.in/auth/revamp"
PULLS = EXTERNAL / "bhoomi_rashi_pulls"
PULL_EVERY_D = 91
EXPORT_GAP_S = 3.0        # between two state exports; never below MIN_GAP_S
TIMEOUT_S, EXPORT_TIMEOUT_S = 60, 900
TAIL = 64 << 10           # the bytes at the end of an export searched for </table>
_snapshot_lock, _pull_lock = threading.Lock(), threading.Lock()


class Truncated(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


# ------------------------------------------------------------ PARIVESH 2.0 dashboard

def snapshot_path(today: date | None = None) -> Path:
    return SNAPSHOTS / f"{today or date.today()}.csv"


def parse_dashboard(page: str, retrieved) -> pd.DataFrame:
    """The dashboard's state x level table with source (the dashboard's own last-updated time) and retrieved
    columns. ValueError when the page has no such table (a changed layout, an error page)."""
    try:
        tables = pd.read_html(io.StringIO(page), flavor="lxml")
    except ValueError:
        tables = []
    t = next((t for t in tables if DASHBOARD_TABLE <= set(map(str, t.columns))), None)
    if t is None:
        raise ValueError("no 'State-wise Status of FC Proposals' table on the dashboard page")
    t = t.loc[:, ~t.columns.astype("str").str.contains("mail", case=False)].replace(EMAIL, "", regex=True)
    m = re.search(r"Last Updated On:\s*([^<]+?)\s*<", page)
    updated = pd.to_datetime(m.group(1), format="%d-%b-%y %I:%M %p", errors="coerce") if m else pd.NaT
    note = f"last updated {updated:%d-%b-%Y %H:%M}" if pd.notna(updated) else "no last-updated time on the page"
    return t.assign(source=f"{DASHBOARD_URL} (State-wise Status of FC Proposals, {note})", retrieved=str(retrieved))


def snapshot_once(today: date | None = None) -> dict:
    """Archive the dashboard table for today unless that date is archived already."""
    if not _snapshot_lock.acquire(blocking=False):
        return {"busy": True}
    today = today or date.today()
    path, started, t0 = snapshot_path(today), _now(), time.time()
    try:
        if path.exists():
            return {"skipped": True, "file": f"{SNAPSHOTS.name}/{path.name}"}
        try:
            with _client() as c:
                r = c.get(DASHBOARD_URL)
                r.raise_for_status()
            t = parse_dashboard(r.text, today)
        except (httpx.HTTPError, ValueError) as e:
            out = {"error": f"{type(e).__name__}: {e}"[:500]}
            db.record_job("parivesh_snapshot", started, "error", out)
            return out
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")          # a crash never leaves a half file that blocks the day
        t.to_csv(part, index=False)
        part.replace(path)
        total = t["State Name"].astype("str").str.strip().str.upper().eq("TOTAL")
        out = {"file": f"{SNAPSHOTS.name}/{path.name}", "states": int((~total).sum()),
               "total_proposals": int(t.loc[total, "Total Submitted Proposals"].iloc[0]) if total.any() else None,
               "source": t["source"].iloc[0], "seconds": round(time.time() - t0, 1)}
        db.record_job("parivesh_snapshot", started, "ok", out)
        return out
    finally:
        _snapshot_lock.release()


def snapshot_busy() -> bool:
    return _snapshot_lock.locked()


# ------------------------------------------------------------ Bhoomi Rashi whole-state register

def register_form(page: str) -> tuple[str, list[str]]:
    """(EncHid, state names in the dropdown) from the RepState page. EncHid is sent as the page gives it, like a
    browser would: the page carried a value on 2026-09-27 and none on 2026-09-28."""
    field = re.search(r'<input[^>]*name="EncHid"[^>]*>', page, re.I)
    select = re.search(r'<select[^>]*name="highway_id".*?</select>', page, re.I | re.S)
    if not field or not select:
        raise ValueError("RepState page without the EncHid field or the state dropdown")
    enc = re.search(r'value="([^"]*)"', field.group(0), re.I)
    states = [html.unescape(v) for v in re.findall(r'<option[^>]*value="([^"]*)"', select.group(0), re.I)]
    return enc.group(1) if enc else "", [s for s in states if s and s != "-1"]


def export(client: httpx.Client, enc: str, state: str, path: Path) -> int:
    """Stream one state's export to path and return its size; Truncated when the body is shorter than its
    Content-Length, the transfer broke off or there is no closing </table>."""
    fields = {"EncHid": enc, "act": "1", "type": "2", "highway_id": state}
    got = 0
    try:    # identity encoding: the bytes on the wire are the body, so they compare with Content-Length
        with client.stream("POST", f"{BHOOMI}/state_register1.cshtml", data=fields, files=[("but", (None, "Submit"))],
                           headers={"Referer": f"{BHOOMI}/RepState.cshtml", "Accept-Encoding": "identity"},
                           timeout=EXPORT_TIMEOUT_S) as r:
            r.raise_for_status()
            want = r.headers.get("content-length")
            with open(path, "wb") as f:
                for chunk in r.iter_raw():
                    f.write(chunk)
                    got += len(chunk)
    except (httpx.RemoteProtocolError, httpx.ReadError, httpx.ReadTimeout) as e:
        raise Truncated(f"transfer broke off: {type(e).__name__}") from e
    if want is not None and got != int(want):
        raise Truncated(f"{got:,} of {int(want):,} bytes")
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - TAIL))
        if b"</table>" not in f.read().lower():
            raise Truncated(f"no closing </table> in {got:,} bytes")
    return path.stat().st_size


def _pull_state(client, enc, state, folder, gap) -> tuple[dict, pd.DataFrame | None]:
    path, row = folder / "export.html", {"state": state}
    for attempt in (1, 2):
        gap()
        try:
            row["bytes"], row["retried"] = export(client, enc, state, path), attempt > 1
            break
        except Truncated as e:
            row.update(status="truncated", error=str(e), attempts=attempt)
        except httpx.HTTPError as e:
            row.update(status="error", error=f"{type(e).__name__}: {e}"[:300])
            return row, None
    else:
        return row, None
    try:
        parcels = parse_bhoomi_rashi(path)
        st = aggregate_stretches(parcels) if len(parcels) else None
    except Exception as e:  # one malformed export must not stop the other states
        return row | {"status": "error", "error": f"parse: {type(e).__name__}: {e}"[:300]}, None
    finally:
        path.unlink(missing_ok=True)
    row = {k: v for k, v in row.items() if k not in ("error", "attempts")}
    return row | {"status": "ok" if st is not None else "empty", "parcels": len(parcels),
                  "stretches": 0 if st is None else len(st)}, st


def bhoomi_pull(states: list[str] | None = None, today: date | None = None) -> dict:
    """Pull, parse and aggregate these states (any case; default: every state in the dropdown) into today's pull
    file; a state pulled again the same day replaces its rows."""
    if not _pull_lock.acquire(blocking=False):
        return {"busy": True}
    today = today or date.today()
    started, t0, rows, parts = _now(), time.time(), [], []
    last = [0.0]

    def gap():
        time.sleep(max(0.0, max(EXPORT_GAP_S, MIN_GAP_S) - (time.monotonic() - last[0])))
        last[0] = time.monotonic()
    try:
        with _client() as client, tempfile.TemporaryDirectory(prefix="bhoomi_") as tmp:
            try:
                r = client.get(f"{BHOOMI}/RepState.cshtml")
                last[0] = time.monotonic()
                r.raise_for_status()
                enc, offered = register_form(r.text)
            except (httpx.HTTPError, ValueError) as e:
                out = {"error": f"RepState: {type(e).__name__}: {e}"[:500]}
                db.record_job("bhoomi_rashi_pull", started, "error", out)
                return out
            named = {o.upper(): o for o in offered}                     # the dropdown spells 'Ladakh'
            asked = [s.strip().upper() for s in states] if states else list(named)
            unknown = [s for s in asked if s not in named]
            for s in [named[s] for s in asked if s in named]:
                row, st = _pull_state(client, enc, s, Path(tmp), gap)
                rows.append(row)
                if st is not None:
                    parts.append(st)
        path = PULLS / f"{today}.csv"
        if parts:
            new = pd.concat(parts, ignore_index=True)[STRETCH_COLS]
            if path.exists():   # an earlier run today: keep its other states
                old = read_land(path)
                new = pd.concat([old[~old["state"].isin(new["state"])], new], ignore_index=True)
            PULLS.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(".part")
            new.sort_values(["state", "highway_name", "chainage_raw"]).to_csv(part, index=False)
            part.replace(path)
        failed = [r["state"] for r in rows if r["status"] in ("truncated", "error")] + unknown
        out = {"file": f"{PULLS.name}/{path.name}" if parts else None, "states": rows, "unknown_states": unknown,
               "n_ok": sum(r["status"] == "ok" for r in rows), "n_empty": sum(r["status"] == "empty" for r in rows),
               "failed": failed, "stretches": sum(len(p) for p in parts),
               "parcels": sum(r.get("parcels", 0) for r in rows), "seconds": round(time.time() - t0, 1)}
        db.record_job("bhoomi_rashi_pull", started, "error" if not parts else "partial" if failed else "ok", out)
        return out
    finally:
        _pull_lock.release()


def last_pull() -> date | None:
    days = sorted(p.stem for p in PULLS.glob("*.csv"))
    return date.fromisoformat(days[-1]) if days else None


def pull_if_due(every_d: int = PULL_EVERY_D, today: date | None = None) -> dict:
    """The scheduled run: pull when the newest pull file is every_d days old or there is none."""
    last, today = last_pull(), today or date.today()
    if last is not None and (today - last).days < every_d:
        return {"skipped": True, "last_pull": str(last)}
    return bhoomi_pull(today=today)


def pull_busy() -> bool:
    return _pull_lock.locked()
