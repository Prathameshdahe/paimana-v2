"""Tiny JSON-file store.

Stand-in for the Postgres layer planned later. Read-whole-file /
write-whole-file, no concurrency control, fine for a single-user demo.
When Postgres lands, swap these functions for real DB calls.
"""
import json
import os

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
WORKER_RUNS_PATH = os.path.join(DB_DIR, "worker_runs.json")
DISPATCH_DRAFTS_PATH = os.path.join(DB_DIR, "dispatch_drafts.json")


def _ensure_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def _read(path: str) -> list[dict]:
    _ensure_dir()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write(path: str, items: list[dict]) -> None:
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def load_worker_runs() -> list[dict]:
    return _read(WORKER_RUNS_PATH)


def append_worker_runs(new_runs: list[dict]) -> None:
    runs = load_worker_runs()
    runs.extend(new_runs)
    _write(WORKER_RUNS_PATH, runs)


def load_dispatch_drafts() -> list[dict]:
    return _read(DISPATCH_DRAFTS_PATH)


def append_dispatch_drafts(new_drafts: list[dict]) -> None:
    drafts = load_dispatch_drafts()
    drafts.extend(new_drafts)
    _write(DISPATCH_DRAFTS_PATH, drafts)


def update_dispatch_draft(draft_id: str, decision: str) -> dict | None:
    drafts = load_dispatch_drafts()
    for d in drafts:
        if d["id"] == draft_id:
            d["status"] = decision
            _write(DISPATCH_DRAFTS_PATH, drafts)
            return d
    return None
