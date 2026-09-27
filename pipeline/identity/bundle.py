"""Project bundle: one call returns everything for a project key.

Reads the Parquet layers with DuckDB. Optional layers (scores, events,
signals, sector context) are skipped when the file does not exist yet, so
this works on day one and grows as the layers appear.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from .identity_map import IdentityMap


@dataclass
class BundlePaths:
    observations: Path = Path("dataset/silver/observations.parquet")
    sector_context: Path = Path("dataset/silver/sector_context.parquet")
    sources: Path = Path("dataset/raw/sources.parquet")
    predictions_glob: str = "dataset/gold/predictions_*.parquet"
    events: Path = Path("dataset/gold/project_events.parquet")
    signals: Path = Path("dataset/gold/signals.parquet")
    extra: dict[str, Path] = field(default_factory=dict)  # name -> parquet keyed by project_key


def _exists(p: Path | str) -> bool:
    p = str(p)
    if any(ch in p for ch in "*?["):
        return any(Path().glob(p)) if not Path(p).is_absolute() else any(Path(p).parent.glob(Path(p).name))
    return Path(p).exists()


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_project_bundle(project_key: str, idmap: IdentityMap,
                       paths: BundlePaths | None = None,
                       asof: str | None = None) -> dict[str, Any]:
    """Return {master, aliases, observations, sector_context, scores,
    prediction_history, events, signals, provenance, extra}."""
    paths = paths or BundlePaths()
    key = idmap.canonical(project_key)
    master = idmap._projects.get(key)  # noqa: SLF001 - read-only access
    if master is None:
        raise KeyError(f"unknown project key {project_key}")
    con = duckdb.connect()
    bundle: dict[str, Any] = {
        "project_key": key,
        "requested_key": project_key,
        "master": dict(master),
        "aliases": [],
        "observations": [],
        "sector_context": [],
        "scores": None,
        "prediction_history": [],
        "events": [],
        "signals": [],
        "provenance": [],
        "extra": {},
    }
    adf = idmap.aliases_frame(canonical=True)
    bundle["aliases"] = adf[adf["project_key"] == key].to_dict("records")

    if _exists(paths.observations):
        obs = _rows(con, f"""
            SELECT * FROM read_parquet('{paths.observations}')
            WHERE project_key = ? ORDER BY period""", [key])
        bundle["observations"] = obs
        if obs and _exists(paths.sector_context):
            sector = obs[-1].get("sector")
            if sector:
                bundle["sector_context"] = _rows(con, f"""
                    SELECT * FROM read_parquet('{paths.sector_context}')
                    WHERE sector = ? ORDER BY period""", [sector])
        if obs and _exists(paths.sources):
            doc_ids = sorted({o.get("source_doc_id") for o in obs if o.get("source_doc_id")})
            if doc_ids:
                placeholders = ",".join("?" * len(doc_ids))
                bundle["provenance"] = _rows(con, f"""
                    SELECT * FROM read_parquet('{paths.sources}')
                    WHERE source_doc_id IN ({placeholders})""", doc_ids)

    if _exists(paths.predictions_glob):
        hist = _rows(con, f"""
            SELECT * FROM read_parquet('{paths.predictions_glob}')
            WHERE project_key = ? ORDER BY asof, model_version""", [key])
        bundle["prediction_history"] = hist
        if hist:
            if asof is not None:
                pick = [h for h in hist if str(h.get("asof")) <= asof]
                bundle["scores"] = pick[-1] if pick else None
            else:
                bundle["scores"] = hist[-1]

    for name, path in (("events", paths.events), ("signals", paths.signals)):
        if _exists(path):
            bundle[name] = _rows(con, f"""
                SELECT * FROM read_parquet('{path}')
                WHERE project_key = ? ORDER BY 1""", [key])

    for name, path in paths.extra.items():
        if _exists(path):
            bundle["extra"][name] = _rows(con, f"""
                SELECT * FROM read_parquet('{path}') WHERE project_key = ?""", [key])

    con.close()
    return bundle
