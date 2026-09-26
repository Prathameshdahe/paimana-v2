"""Read-only access to the model outputs in dataset/gold/ and the dashboard dataset.

Everything here is loaded fresh per call (small files, single-user demo),
no in-process cache, no DB. If this ever gets real traffic, cache with
functools.lru_cache and invalidate on file mtime.
"""
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LATEST_FEATURES_PATH = os.path.join(ROOT, "dataset", "gold", "latest_features.csv")
PANEL_FEATURES_PATH = os.path.join(ROOT, "dataset", "gold", "features_2024_25_2025_26.csv")
REAL_PROJECTS_PATH = os.path.join(ROOT, "frontend", "src", "mocks", "real_projects.json")


def load_latest_features() -> pd.DataFrame:
    return pd.read_csv(LATEST_FEATURES_PATH, dtype={"project_id": str})


def get_project_row(project_id: str) -> dict | None:
    df = load_latest_features()
    match = df[df["project_id"] == project_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_panel_rows(project_id: str) -> pd.DataFrame:
    """All historical rows for one project from the labeled panel, oldest first."""
    df = pd.read_csv(PANEL_FEATURES_PATH, dtype={"project_id": str})
    rows = df[df["project_id"] == project_id]
    if "report_date" in rows.columns:
        rows = rows.sort_values("report_date")
    return rows


_real_projects_cache: list[dict] | None = None


def load_real_projects() -> list[dict]:
    global _real_projects_cache
    if _real_projects_cache is None:
        with open(REAL_PROJECTS_PATH, "r", encoding="utf-8") as f:
            _real_projects_cache = json.load(f)
    return _real_projects_cache


def get_real_project(project_id: str) -> dict | None:
    for p in load_real_projects():
        if p.get("id") == project_id or p.get("code") == project_id:
            return p
    return None
