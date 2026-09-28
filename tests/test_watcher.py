import io
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import db, serving  # noqa: E402
from backend.live import watcher  # noqa: E402
from backend.main import app  # noqa: E402
from viewers import as_role  # noqa: E402 - tests/viewers.py

PORTAL_CSV = ('"Projects Details"\n\n"Sr. No.","Sector Name","Line Ministry","Implementing Agency","Project Code",'
              '"Project Name","Original Cost\n(in cr.)","Revised Cost\n(in cr.)","Expenditure\n(in cr.)",'
              '"Physical Progress\n(in %)","Original\nDate of Commissioning","Revised\nDate of Commissioning",'
              '"Sanction Date"\n"1","Railways","Ministry of Railways","RVNL","700001","New line X-Y","100","0","10",'
              '"5","01/01/2027","31/12/2027","01/01/2020"\n')
ASOF = pd.Timestamp("2026-07-01")


def preds(rows, mv="mv-new"):
    """Synthetic predictions: (key, tier, p_any_2q)."""
    return pd.DataFrame([{"project_key": k, "asof": ASOF, "model_version": mv, "tier": t, "project_name": f"name {k}",
                          "p_any_2q": p} for k, t, p in rows])


OLD = preds([("A", "Low", .1), ("B", "High", .6), ("C", "Critical", .9), ("D", "Medium", .3), ("E", None, None)], "mv-old")
NEW = preds([("A", "Critical", .95), ("B", "Low", .1), ("C", "Critical", .9), ("D", "Low", .2), ("E", "High", .7),
             ("F", "High", .65), ("G", "Low", .05)])


def log_frame(rows):
    """Prediction-log rows: (key, asof, model_version, tier, p_any_2q, realised y_any or None)."""
    d = pd.DataFrame([{"project_key": k, "asof": pd.Timestamp(a), "model_version": mv, "p_any_2q": p,
                       "p_date_push_2q": p, "p_cost_rev_2q": p, "tier": t} for k, a, mv, t, p, _ in rows])
    y = pd.array([r[5] for r in rows], dtype="Int8")
    return d.assign(y_any_2q=y, y_date_push_2q=y, y_cost_rev_2q=pd.array([None] * len(rows), dtype="Int8"),
                    realised_period=pd.Series([pd.Timestamp("2026-01-01") if r[5] is not None else pd.NaT
                                               for r in rows], dtype="datetime64[us]"))


LOG = log_frame([("A", "2026-01-01", "mv1", "High", .7, None), ("A", "2026-01-01", "mv2", "Critical", .8, None),
                 ("B", "2026-01-01", "mv1", "Low", .1, None), ("C", "2026-07-01", "mv1", "High", .6, None),
                 ("D", "2025-07-01", "mv1", "High", .6, 0)])
LABELS = pd.DataFrame({"project_key": ["A", "B", "D"], "period": pd.to_datetime(["2026-01-01"] * 2 + ["2025-07-01"]),
                       "target_period": pd.to_datetime(["2026-07-01"] * 2 + ["2026-01-01"]),
                       "y_date_push": pd.array([1, 0, 1], dtype="Int8"), "y_cost_rev": pd.array([0, 0, 1], dtype="Int8"),
                       "y_any": pd.array([1, 0, 1], dtype="Int8")})


def test_diff_alerts_only_for_high_and_critical_moves():
    got = {(a["project_key"], a["kind"], a["severity"]) for a in watcher.diff_alerts(OLD, NEW, "t")}
    assert got == {("A", "tier_up", 3), ("B", "tier_down", 1), ("E", "tier_up", 2), ("F", "new_project", 2),
                   ("G", "new_project", 1)}


def test_fill_realised_is_idempotent_and_alerts_flagged_slips():
    log, filled = watcher.fill_realised(LOG, LABELS)
    assert sorted(filled["project_key"]) == ["A", "A", "B"]
    assert log.loc[log.project_key.eq("D"), "y_any_2q"].tolist() == [0]  # filled before: kept as it was
    assert log["y_any_2q"].dtype == "Int8" and log.loc[log.project_key.eq("C"), "realised_period"].isna().all()
    alerts = watcher.realised_alerts(filled, {"A": "Road A"}, "t")
    assert [(a["project_key"], a["kind"], a["model_version"]) for a in alerts] == [("A", "slip_realised", "mv2")]
    assert "completion date pushed" in alerts[0]["detail"] and "cost revised" not in alerts[0]["detail"]
    assert watcher.accuracy(filled) == {"realised": 2, "slipped": 1, "flagged": 1, "flagged_and_slipped": 1}
    again, none = watcher.fill_realised(log, LABELS)
    assert none.empty and again.equals(log)


@pytest.fixture()
def live(fresh_db, tmp_path, monkeypatch):
    """The watcher's files in tmp_path; the real serving data stays loaded for asof / model_version."""
    db.init()
    gold, clean, inbox = tmp_path / "gold", tmp_path / "clean", tmp_path / "raw" / "inbox"
    for d in (gold, clean / "portal", inbox):
        d.mkdir(parents=True)
    OLD.to_parquet(gold / "predictions_old.parquet")
    (gold / "predictions_latest.json").write_text(json.dumps({"path": str(gold / "predictions_old.parquet")}))
    LOG.to_parquet(gold / "prediction_log.parquet")
    LABELS.to_parquet(gold / "labels_h2.parquet")
    (clean / "portal" / "portal_projects.csv").write_text("project_code\n1\n2\n")
    for name, value in {"POINTER": gold / "predictions_latest.json", "LOG": gold / "prediction_log.parquet",
                        "LABELS": gold / "labels_h2.parquet", "CLEAN": clean, "RAW": tmp_path / "raw",
                        "INBOX": inbox, "ROOT": tmp_path, "SETTLE_S": 0}.items():
        monkeypatch.setattr(watcher, name, value)
    yield tmp_path
    serving.pin(False)


def fake_pipeline(monkeypatch, fail_at=None):
    """Replace the subprocess steps: 'score' writes NEW as the new predictions, fail_at raises."""
    calls = []

    def run(cmd):
        step = cmd[-1] if cmd[3] == "-m" else Path(cmd[3]).stem
        calls.append(step)
        if step == "score":
            p = watcher.POINTER.parent / "predictions_new.parquet"
            NEW.to_parquet(p)
            watcher.POINTER.write_text(json.dumps({"path": str(p)}))
        if step == fail_at:
            raise RuntimeError(f"{step} broke")
        return 0.0
    monkeypatch.setattr(watcher, "run_step", run)
    return calls


def alerts_of(kind):
    """Alerts the watcher raised (not the seeded feed)."""
    return [a for a in db.alerts(kind=kind, size=100)["items"] if (a["source"] or "").startswith("ingest:")]


def test_ingest_runs_once_per_sha256(live, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    (watcher.INBOX / "Projects_Report.csv").write_text(PORTAL_CSV, encoding="utf-8")
    out = watcher.watch_once()
    assert [f["status"] for f in out["files"]] == ["ok"], out
    assert calls == ["portal_csv", "build_clean_projects", "silver", "external", "research", "gold", "score",
                     "profile", "serve"]
    row = out["files"][0]
    assert row["kind"] == "portal_csv" and row["rows"] == 2
    assert (live / row["archived_as"]).exists() and row["archived_as"].startswith("raw/csv/")
    assert not (watcher.INBOX / "Projects_Report.csv").exists()
    assert {a["project_key"] for a in alerts_of("tier_up")} == {"A", "E"}
    assert [a["project_key"] for a in alerts_of("slip_realised")] == ["A"]
    assert pd.read_parquet(watcher.LOG)["realised_period"].notna().sum() == 4
    # the same bytes again: nothing to do
    (watcher.INBOX / "copy.csv").write_text(PORTAL_CSV, encoding="utf-8")
    assert watcher.pending() == [] and watcher.watch_once()["files"] == []
    assert len(calls) == 9
    # the accepted report and its run are registered for the lineage (ingest.source_documents / load_runs)
    (doc,) = db.source_documents(row["sha256"])
    assert (doc["file_type"], doc["report_type"], doc["source_path"]) == ("csv", "portal_csv", row["archived_as"])
    (run,) = db.load_runs("INGEST")
    assert (run["status"], run["rows_loaded"], run["source_document_id"]) == ("SUCCESS", 2, doc["source_document_id"])
    assert run["model_version"] == "mv-new" and db.latest_jobs()[0]["summary"]["serve_error"] is None
    # a new pipeline version ingests it again
    monkeypatch.setattr(watcher, "pipeline_version", lambda: "next")
    assert [p.name for p, _ in watcher.pending()] == ["copy.csv"]


def test_failed_step_keeps_the_old_predictions(live, monkeypatch):
    fake_pipeline(monkeypatch, fail_at="profile")
    ticks = [0]
    monkeypatch.setattr(serving, "_version", lambda: ("v", ticks[0]))
    before = serving.state()
    pointer, pred = watcher.POINTER.read_bytes(), (live / "gold" / "predictions_old.parquet").read_bytes()
    log = watcher.LOG.read_bytes()
    orig = watcher.run_step
    monkeypatch.setattr(watcher, "run_step", lambda cmd: (ticks.__setitem__(0, ticks[0] + 1), orig(cmd))[1])
    (watcher.INBOX / "Projects_Report.csv").write_text(PORTAL_CSV, encoding="utf-8")
    out = watcher.watch_once()["files"][0]
    assert out["status"] == "error" and "profile broke" in out["error"]
    assert watcher.POINTER.read_bytes() == pointer and watcher.LOG.read_bytes() == log
    assert (live / "gold" / "predictions_old.parquet").read_bytes() == pred
    assert (watcher.INBOX / "Projects_Report.csv").exists()  # stays for a retry under a new pipeline version
    assert serving.state() is before  # version files changed, but serving stays on what it had
    err = alerts_of("pipeline_error")
    assert len(err) == 1 and err[0]["project_key"] is None and "profile broke" in err[0]["detail"]
    assert watcher.pending() == []  # the failure is recorded, not retried every minute
    assert db.latest_jobs()[0]["status"] == "error"


def test_failed_serve_step_does_not_fail_the_ingest(live, monkeypatch):
    """The serving tables are best effort: the report is ingested and served, the failure is a severity-2 alert."""
    calls = fake_pipeline(monkeypatch, fail_at="serve")
    (watcher.INBOX / "Projects_Report.csv").write_text(PORTAL_CSV, encoding="utf-8")
    row = watcher.watch_once()["files"][0]
    assert row["status"] == "ok" and calls[-1] == "serve" and not (watcher.INBOX / "Projects_Report.csv").exists()
    assert "serve broke" in db.latest_jobs()[0]["summary"]["serve_error"]
    (err,) = alerts_of("pipeline_error") or [None]
    assert err is None
    (err,) = [a for a in db.alerts(kind="pipeline_error")["items"] if a["source"] == "serve:Projects_Report.csv"]
    assert err["severity"] == 2 and "serve broke" in err["detail"] and "python -m pipeline.run serve" in err["detail"]
    assert [r["status"] for r in db.load_runs("INGEST")] == ["SUCCESS"]


def test_unknown_file_is_an_error_not_a_run(live, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    (watcher.INBOX / "notes.csv").write_text("a,b\n1,2\n")
    assert watcher.watch_once()["files"][0]["error"].startswith("not a portal")
    assert calls == [] and len(alerts_of("pipeline_error")) == 1


def test_upload_endpoint(live, monkeypatch):
    with TestClient(app) as c:
        c.headers.update(as_role(c, "developer"))
        r = c.post("/api/jobs/ingest", files={"file": ("../../Projects_Report.csv", io.BytesIO(PORTAL_CSV.encode()))})
        assert r.status_code == 200 and r.json()["kind"] == "portal_csv", r.text
        assert r.json()["savedAs"].endswith("inbox/Projects_Report.csv")
        assert (watcher.INBOX / "Projects_Report.csv").read_text(encoding="utf-8") == PORTAL_CSV
        again = c.post("/api/jobs/ingest", files={"file": ("x.csv", io.BytesIO(PORTAL_CSV.encode()))}).json()
        assert again["savedAs"].endswith("inbox/x.csv")  # not ingested yet, so a second copy is kept
        assert c.post("/api/jobs/ingest", files={"file": ("a.exe", io.BytesIO(b"MZ"))}).status_code == 422
        fake_pipeline(monkeypatch)
        w = c.post("/api/jobs/watch").json()
        assert w["started"] and w["pending"] == 1  # two copies of the same bytes: one run
        dup = c.post("/api/jobs/ingest", files={"file": ("y.csv", io.BytesIO(PORTAL_CSV.encode()))}).json()
        assert dup["alreadyIngested"] and dup["savedAs"] is None
