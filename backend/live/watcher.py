"""Report inbox watcher (docs/IMPLEMENTATION_GUIDE_v2.md B 4.2 ingest_report, B 7 monthly run).

watch_once() takes every file in dataset/raw/inbox/ that this pipeline version has not ingested (by sha256), oldest
first, one pipeline run per file:
  1. classify: a portal Projects_Report.csv export (pipeline/extract/portal_csv.py --projects, which replaces
     clean/portal/portal_projects.csv) or a PAIMANA flash report PDF (pipeline/extract/proj_flash_2025_27.py; a
     copy goes into its source folder in the Dataset drive folder, the folder the extractor rebuilds the family
     from and records source_file, hence source_doc_id, relative to).
  2. the extractor, pipeline/build_clean_projects.py, then python -m pipeline.run silver (which resolves identity
     first), external, gold, score and profile. train is the monthly run and is started by hand.
  3. success: the inbox file moves to dataset/raw/<csv|pdf>/<fiscal year>/, the old and new predictions are diffed
     into tier_up / tier_down / new_project alerts, and prediction_log rows whose t + 2q is now labelled get their
     realised outcome (a slip_realised alert when they were High / Critical and slipped).
     failure: the predictions pointer and file, the prediction log and the clean input the run replaced are put
     back, serving stays on the version it had (pinned), the file stays in the inbox and a pipeline_error alert is
     raised. The source row keeps status error, so the file is retried only under a new pipeline version.
Idempotent on (sha256, pipeline_version); pipeline_version hashes the pipeline and model code.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from backend import db, serving
from pipeline.extract.common import fiscal_year

ROOT = serving.ROOT
RAW = ROOT / "dataset" / "raw"
INBOX = RAW / "inbox"
CLEAN = ROOT / "dataset" / "clean"
POINTER = serving.POINTER
LOG, LABELS = serving.GOLD / "prediction_log.parquet", serving.GOLD / "labels_h2.parquet"
PIPELINE = ["silver", "external", "gold", "score", "profile"]
PORTAL_HEADER = ["Sr. No.", "Sector Name", "Line Ministry", "Implementing Agency", "Project Code", "Project Name"]
UPLOAD_SUFFIXES = (".csv", ".pdf")
MAX_UPLOAD = 100 << 20
SETTLE_S = 5              # a file changed this recently may still be copying in
STEP_TIMEOUT_S = 3600
OUTPUT_TAIL = 2000        # characters of a failing step's output kept in the error
WATCH_TIERS = ("Critical", "High")
TIER_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}   # untiered ranks below Low
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def pipeline_version() -> str:
    """Hash of the pipeline and model code: a file is ingested again when the code that turns it into scores changes."""
    files = sorted([*(ROOT / "pipeline").rglob("*.py"), *(ROOT / "ml").glob("*.py")])
    return hashlib.sha256(b"".join(p.read_bytes() for p in files)).hexdigest()[:12]


def pending() -> list[tuple[Path, str]]:
    """Inbox files this pipeline version has not ingested yet, oldest first, as (path, sha256); of two copies of the
    same bytes only the first (the other is skipped once that one is recorded)."""
    if not INBOX.is_dir():
        return []
    now, pv = time.time(), pipeline_version()
    files = sorted((p for p in INBOX.iterdir() if p.is_file() and p.name != "README.md" and not p.name.startswith(".")
                    and now - p.stat().st_mtime >= SETTLE_S), key=lambda p: (p.stat().st_mtime, p.name))
    first = {}
    for p in files:
        first.setdefault(sha256(p), p)
    return [(p, h) for h, p in first.items() if not db.source_seen(h, pv)]


def busy() -> bool:
    return _lock.locked()


def _flash():
    from pipeline.extract import proj_flash_2025_27  # PyMuPDF, only when a PDF comes in
    return proj_flash_2025_27


def classify(path: Path) -> tuple[str | None, str | None]:
    """(kind, period YYYY-MM) of an inbox file: 'portal_csv' (period None: the export prints no date) or
    'flash_pdf' (period from the file name, as the extractor reads it); kind None when it is neither."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            head = [str(c).strip() for c in pd.read_csv(path, skiprows=2, nrows=0).columns[:6]]
        except (ValueError, UnicodeDecodeError):  # pandas parser errors are ValueErrors
            return None, None
        return ("portal_csv", None) if head == PORTAL_HEADER else (None, None)
    if suffix == ".pdf":
        import fitz
        try:
            with fitz.open(path) as doc:
                text = " ".join(doc[i].get_text() for i in range(min(2, doc.page_count)))
        except Exception:  # PyMuPDF raises its own error types for a damaged or non-PDF file
            return None, None
        period = _flash().period_from_name(path.name)
        if period and re.search(r"PAIMANA portal|_FR_", text) and "QPISR" not in text:
            return "flash_pdf", period
    return None, None


def steps(kind: str, path: Path) -> list[list[str]]:
    py = [sys.executable, "-X", "utf8"]
    extract = (["pipeline/extract/portal_csv.py", "--projects", str(path)] if kind == "portal_csv"
               else ["pipeline/extract/proj_flash_2025_27.py"])
    return [py + extract, py + ["pipeline/build_clean_projects.py"]] + [py + ["-m", "pipeline.run", s] for s in PIPELINE]


def run_step(cmd: list[str]) -> float:
    """Run one pipeline command from the repo root; returns its seconds, raises RuntimeError with the output tail."""
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=STEP_TIMEOUT_S, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd[3:])} exited {r.returncode}: {(r.stdout + r.stderr)[-OUTPUT_TAIL:]}")
    return round(time.time() - t0, 1)


# ------------------------------------------------------------------ diffs

def _rank(tier) -> int:
    return TIER_RANK.get(tier, len(TIER_RANK))


def _tier(v):
    return v if isinstance(v, str) else None


def diff_alerts(old: pd.DataFrame, new: pd.DataFrame, source: str) -> list[dict]:
    """Alerts for old -> new predictions (one row per project_key each): tier_up when a project moves up into High or
    Critical (severity 3 into Critical, else 2), tier_down when it moves down out of them (1), new_project for a key
    scored now and not before (2 if it comes in High or Critical, else 1). Moves among Medium, Low and untiered raise
    nothing; a project no longer scored (completed, dropped from the report) raises nothing either."""
    m = new.merge(old[["project_key", "tier"]], on="project_key", how="left", suffixes=("", "_old"), indicator="seen")
    out = []
    for r in m.to_dict("records"):
        tier, was, asof = _tier(r["tier"]), _tier(r["tier_old"]), str(pd.Timestamp(r["asof"]).date())
        p = f"P(date push or cost revision, 2q) = {r['p_any_2q']:.2f}" if pd.notna(r["p_any_2q"]) else "not scored"
        base = {"project_key": r["project_key"], "asof": asof, "model_version": r["model_version"], "source": source}
        if r["seen"] == "left_only":
            out.append({**base, "kind": "new_project", "severity": 2 if tier in WATCH_TIERS else 1,
                        "title": f"New project: {r['project_name']}",
                        "detail": f"first scored at asof {asof}: tier {tier or 'untiered'}; {p}"})
        elif _rank(tier) < _rank(was) and tier in WATCH_TIERS:
            out.append({**base, "kind": "tier_up", "severity": 3 if tier == "Critical" else 2,
                        "title": f"{tier}: {r['project_name']}",
                        "detail": f"{was or 'untiered'} -> {tier} at asof {asof}; {p}"})
        elif _rank(tier) > _rank(was) and was in WATCH_TIERS:
            out.append({**base, "kind": "tier_down", "severity": 1, "title": f"Down from {was}: {r['project_name']}",
                        "detail": f"{was} -> {tier or 'untiered'} at asof {asof}; {p}"})
    return out


def fill_realised(log: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Realised 2-quarter outcomes for the open prediction_log rows whose (project_key, asof) now has an h=2 label
    (the t + 2q report came in). Returns the log and the rows filled by this call; rows filled before stay as they
    are, so a second call fills nothing."""
    lab = labels.dropna(subset=["y_any"]).rename(columns={"period": "asof"})
    open_rows = log.loc[log["realised_period"].isna(), ["project_key", "asof"]].reset_index()
    m = open_rows.merge(lab[["project_key", "asof", "target_period", "y_any", "y_date_push", "y_cost_rev"]],
                        on=["project_key", "asof"], validate="m:1")
    log = log.copy()
    for dst, src in (("y_any_2q", "y_any"), ("y_date_push_2q", "y_date_push"), ("y_cost_rev_2q", "y_cost_rev"),
                     ("realised_period", "target_period")):
        log.loc[m["index"], dst] = m[src].array
    return log, log.loc[m["index"]]


def _latest_model(rows: pd.DataFrame) -> pd.DataFrame:
    """One row per (project_key, asof): the latest model version (versions sort by their run timestamp)."""
    return rows.sort_values("model_version").drop_duplicates(["project_key", "asof"], keep="last")


def realised_alerts(filled: pd.DataFrame, names: dict, source: str) -> list[dict]:
    """slip_realised: a row realised now that was High / Critical at its asof and did slip."""
    rows = _latest_model(filled)
    hit = rows[rows["y_any_2q"].eq(1).fillna(False).astype(bool) & rows["tier"].isin(WATCH_TIERS)]
    out = []
    for r in hit.itertuples():
        what = " and ".join(w for w, y in (("completion date pushed", r.y_date_push_2q),
                                           ("cost revised", r.y_cost_rev_2q)) if y == 1)
        out.append({"project_key": r.project_key, "kind": "slip_realised", "severity": 2,
                    "title": f"Slip realised: {names.get(r.project_key, r.project_key)}",
                    "detail": f"flagged {r.tier} at asof {r.asof:%Y-%m-%d} (P = {r.p_any_2q:.2f}); by the "
                              f"{r.realised_period:%Y-%m} report: {what}",
                    "asof": f"{r.asof:%Y-%m-%d}", "model_version": r.model_version, "source": source})
    return out


def accuracy(filled: pd.DataFrame) -> dict:
    """Live accuracy of the rows realised now: how many slipped, and of those flagged High / Critical how many."""
    rows = _latest_model(filled)
    slipped = rows["y_any_2q"].eq(1).fillna(False).astype(bool)
    flagged = rows["tier"].isin(WATCH_TIERS)
    return {"realised": len(rows), "slipped": int(slipped.sum()), "flagged": int(flagged.sum()),
            "flagged_and_slipped": int((slipped & flagged).sum())}


# ------------------------------------------------------------------ ingest

def _flash_copy(path: Path, period: str) -> Path:
    """Copy a flash PDF into the extractor's source folder; refuses a period that folder already has a report for."""
    flash = _flash()
    if not flash.SRC_DIR.is_dir():
        raise RuntimeError(f"flash source folder {flash.SRC_DIR} is missing (Dataset drive folder not present)")
    for other in flash.SRC_DIR.glob("*.pdf"):
        if other.name not in flash.SKIP and flash.period_from_name(other.name) == period:
            raise RuntimeError(f"the flash source folder already has {other.name} for {period}; "
                               "replace it there by hand and rerun the pipeline")
    dest = flash.SRC_DIR / path.name
    shutil.copy2(path, dest)
    return dest


def _archive(path: Path, kind: str, period: str | None, sha: str) -> Path:
    """Move an ingested file to dataset/raw/<csv|pdf>/<fiscal year>/ (of the report period; of today for a portal
    export), with the sha256 prefix added to the name when a different file there already has it."""
    folder = RAW / ("csv" if kind == "portal_csv" else "pdf") / fiscal_year(period or f"{date.today():%Y-%m}")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / path.name
    if dest.exists() and sha256(dest) != sha:
        dest = folder / f"{path.stem}_{sha[:8]}{path.suffix}"
    return path.replace(dest)


def _rows(kind: str, copied: Path | None) -> int:
    if kind == "portal_csv":
        return len(pd.read_csv(CLEAN / "portal" / "portal_projects.csv", usecols=["project_code"]))
    src = _flash().rel(copied)
    parts = pd.read_csv(CLEAN / "_parts" / "proj_flash_2025_27" / "projects.csv", usecols=["source_file"])
    return int(parts["source_file"].eq(src).sum())


def _fail(row: dict, started: str, error: str, summary: dict) -> dict:
    s = serving.state()
    row.update(status="error", error=error)
    db.record_source(row)
    db.record_job("ingest", started, "error", {**summary, "file": row["filename"], "error": error})
    db.add_alerts([{"project_key": None, "kind": "pipeline_error", "severity": 3,
                    "title": f"Report ingest failed: {row['filename']}",
                    "detail": f"{error[:1500]} -- still serving asof {s['asof']} ({s['model_version']})",
                    "asof": str(s["asof"]), "model_version": s["model_version"], "source": f"ingest:{row['filename']}"}])
    return row


def ingest(path: Path, sha: str, pv: str) -> dict:
    """Run one inbox file through the pipeline (see the module docstring); returns its sources row."""
    started, t0 = _now(), time.time()
    kind, period = classify(path)
    row = {"sha256": sha, "pipeline_version": pv, "filename": path.name, "kind": kind, "period": period}
    if kind is None:
        return _fail(row, started, "not a portal Projects_Report.csv export or a PAIMANA flash report PDF", {})
    old_path = ROOT / json.loads(POINTER.read_text(encoding="utf-8"))["path"]
    old = pd.read_parquet(old_path)
    clean_input = ([CLEAN / "portal" / "portal_projects.csv"] if kind == "portal_csv"
                   else sorted((CLEAN / "_parts" / "proj_flash_2025_27").glob("*.csv")))
    saved = {p: p.read_bytes() for p in [POINTER, old_path, LOG, *clean_input] if p.exists()}
    version, copied, ran, timings = serving._version(), None, False, {}  # noqa: SLF001
    summary = {"file": path.name, "sha256": sha, "kind": kind, "period": period, "steps": timings}
    serving.pin(True)
    try:
        if kind == "flash_pdf":
            copied = _flash_copy(path, period)
        for cmd in steps(kind, path):
            timings[cmd[-1] if cmd[3] == "-m" else Path(cmd[3]).stem] = run_step(cmd)
        ran = True
        n_rows = _rows(kind, copied)
        new = pd.read_parquet(ROOT / json.loads(POINTER.read_text(encoding="utf-8"))["path"])
        archived = _archive(path, kind, period, sha)
        source = f"ingest:{path.name}"
        alerts = diff_alerts(old, new, source)
        log, filled = fill_realised(pd.read_parquet(LOG), pd.read_parquet(LABELS))
        log.to_parquet(LOG, index=False)
        alerts += realised_alerts(filled, dict(zip(new["project_key"], new["project_name"])), source)
        db.add_alerts(alerts)
    except Exception as e:  # any failing step: record it, put the served files back, keep serving what we had
        if not ran:
            for p, b in saved.items():
                if not p.exists() or p.read_bytes() != b:
                    p.write_bytes(b)
            if copied:
                copied.unlink(missing_ok=True)
        serving.pin(not ran and serving._version() != version)  # noqa: SLF001
        return _fail(row, started, f"{type(e).__name__}: {e}", {**summary, "seconds": round(time.time() - t0, 1)})
    serving.pin(False)
    row.update(status="ok", rows=n_rows, archived_as=archived.relative_to(ROOT).as_posix())
    db.record_source(row)
    db.record_job("ingest", started, "ok", {
        **summary, "rows": n_rows, "archived_as": row["archived_as"], "asof": str(new["asof"].max().date()),
        "model_version": new["model_version"].iloc[0], "alerts": dict(Counter(a["kind"] for a in alerts)),
        "realised": accuracy(filled), "seconds": round(time.time() - t0, 1)})
    return row


def watch_once() -> dict:
    """Ingest every pending inbox file. One run at a time: a call while one runs returns busy."""
    if not _lock.acquire(blocking=False):
        return {"busy": True, "files": []}
    try:
        pv = pipeline_version()
        return {"busy": False, "files": [ingest(p, h, pv) for p, h in pending()]}
    finally:
        _lock.release()


def save_upload(filename: str | None, fileobj) -> dict:
    """Save an uploaded report into the inbox under a safe, unused name; a file already ingested is not kept."""
    name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(filename or "").name).strip(" .")
    if Path(name).suffix.lower() not in UPLOAD_SUFFIXES:
        raise ValueError("only .csv and .pdf reports are accepted")
    INBOX.mkdir(parents=True, exist_ok=True)
    tmp, size, h = INBOX / f".upload-{uuid.uuid4().hex}", 0, hashlib.sha256()
    with open(tmp, "wb") as out:
        while chunk := fileobj.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                break
            h.update(chunk)
            out.write(chunk)
    sha = h.hexdigest()
    if size > MAX_UPLOAD or db.source_seen(sha, pipeline_version()):
        tmp.unlink()
        if size > MAX_UPLOAD:
            raise ValueError(f"file is larger than {MAX_UPLOAD >> 20} MB")
        return {"saved_as": None, "sha256": sha, "kind": None, "already_ingested": True}
    dest, n = INBOX / name, 1
    while dest.exists():
        dest, n = INBOX / f"{Path(name).stem} ({n}){Path(name).suffix}", n + 1
    tmp.replace(dest)
    return {"saved_as": dest.relative_to(ROOT).as_posix(), "sha256": sha, "kind": classify(dest)[0],
            "already_ingested": False}
