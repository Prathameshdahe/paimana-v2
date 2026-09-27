"""
Bottleneck clusters across projects (docs/IMPLEMENTATION_GUIDE_v2.md B 6.1).

Run from repo root after score (part of the profile step):  python -m pipeline.run profile

Inputs   gold/project_events.parquet, gold/predictions_latest.json (and the file it names: the current portfolio),
         optionally the app database (database/paimana.db or PAIMANA_DB): linked news signals of severity >= 2
Outputs  gold/bottlenecks.parquet (one row per cluster), gold/bottleneck_members.parquet (cluster x project x
         evidence line), gold/bottlenecks_summary.json

Members are the open report events of current projects, plus linked news signals of severity >= SEVERITY_MIN with a
taxonomy category (a signal takes the authority of the project's open event of that category, else 'unspecified').
They are grouped by (category, authority, state); a group becomes a bottleneck when it holds >= MIN_PROJECTS distinct
projects. Where most of a (category, state) group's projects name no authority, a coarser rollup over every authority
is added too (level 'state'), unless it holds exactly the projects of its 'unspecified' cluster.
The headline states what the data supports, 'Blocking N projects worth Rs X Cr': the projects that would be affected
while the issue stays open. It is a grouping of shared open issues, not a causal claim about resolving it.
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.silver import ROOT  # noqa: E402

GOLD = ROOT / "dataset" / "gold"
DB = ROOT / "database" / "paimana.db"
MIN_PROJECTS, SEVERITY_MIN, N_EVIDENCE = 3, 2, 3
UNSPECIFIED = "unspecified"
WATCH = ("Critical", "High")
NOTE = ("Projects that would be affected while this issue stays open: they share an open issue of this category and "
        "place in their report remarks or linked news. This is a grouping, not a causal claim about what resolving "
        "it would change.")
CUR_COLS = ["project_key", "project_name", "state", "tier", "p_any_2q", "months_p50", "anticipated_cost_cr"]
COLS = ["bottleneck_id", "level", "category", "authority", "state", "n_projects", "member_keys", "capital_exposed_cr",
        "mean_p_any_2q", "mean_months_p50", "n_critical_high", "earliest_first_seen", "last_seen", "n_signals",
        "evidence", "headline", "note"]
MEMBER_COLS = ["bottleneck_id", "project_key", "kind", "authority", "first_seen", "last_seen", "evidence",
               "source_doc_id", "source_page", "url"]


def load_signals(path=None) -> pd.DataFrame:
    """Linked signals (project_key, category, severity, title, source, published_at, url) of severity >=
    SEVERITY_MIN with a category; empty when the database is missing (the pipeline never needs it)."""
    path = Path(path or os.environ.get("PAIMANA_DB") or DB)
    cols = ["project_key", "category", "severity", "title", "source", "published_at", "url"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as con:
        return pd.read_sql_query(f"""SELECT sp.project_key, s.category, s.severity, s.title, s.source, s.published_at,
            s.url FROM signal_projects sp JOIN signals s ON s.id = sp.signal_id
            WHERE s.severity >= {SEVERITY_MIN} AND s.category IS NOT NULL""", con)


def members(events: pd.DataFrame, cur: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """Member rows (project_key, category, authority, state, kind, first_seen, last_seen, evidence, source_doc_id,
    source_page, url): open events and qualifying signals of current projects, the state from the portfolio."""
    ev = events[events["status"].eq("open") & events["project_key"].isin(cur["project_key"])]
    ev = ev.assign(kind="event", authority=ev["authority"].fillna(UNSPECIFIED), url=None)
    sig = signals[signals["project_key"].isin(cur["project_key"])]
    if len(sig):
        auth = ev.drop_duplicates(["project_key", "category"])[["project_key", "category", "authority"]]
        date = pd.to_datetime(sig["published_at"].str[:10], errors="coerce").astype("datetime64[us]")
        sig = sig.assign(kind="signal", first_seen=date, last_seen=date, source_doc_id=sig["source"],
                         source_page=pd.NA, evidence="news: " + sig["title"].fillna("") + " ("
                         + sig["source"].fillna("") + ", " + sig["published_at"].fillna("").str[:10] + ")")
        sig = sig.merge(auth, on=["project_key", "category"], how="left").fillna({"authority": UNSPECIFIED})
    cols = ["project_key", "category", "authority", "kind", "first_seen", "last_seen", "evidence", "source_doc_id",
            "source_page", "url"]
    m = pd.concat([ev[cols], sig[cols]] if len(sig) else [ev[cols]], ignore_index=True)
    return m.merge(cur[["project_key", "state"]], on="project_key", how="left").fillna({"state": "unknown"})


def bottleneck_id(level, category, authority, state) -> str:
    return "BN-" + hashlib.sha1(f"{level}|{category}|{authority}|{state}".encode()).hexdigest()[:10]


def _describe(level, key, g: pd.DataFrame, cur: pd.DataFrame) -> dict:
    category, authority, state = key
    p = cur[cur["project_key"].isin(g["project_key"])].sort_values(["p_any_2q", "project_key"],
                                                                     ascending=[False, True], na_position="last")
    cap = float(p["anticipated_cost_cr"].sum())
    names = cur.set_index("project_key")["project_name"]
    lines = g.sort_values(["last_seen", "kind"], ascending=[False, True]).drop_duplicates("project_key")
    return {
        "bottleneck_id": bottleneck_id(level, category, authority, state), "level": level, "category": category,
        "authority": authority, "state": state, "n_projects": len(p), "member_keys": p["project_key"].tolist(),
        "capital_exposed_cr": round(cap, 2), "mean_p_any_2q": p["p_any_2q"].mean(),
        "mean_months_p50": p["months_p50"].mean(), "n_critical_high": int(p["tier"].isin(WATCH).sum()),
        "earliest_first_seen": g["first_seen"].min(), "last_seen": g["last_seen"].max(),
        "n_signals": int(g["kind"].eq("signal").sum()),
        "evidence": [f"{str(names.get(k, k))[:70]} ({k}): {e}" for k, e in
                     zip(lines["project_key"].head(N_EVIDENCE), lines["evidence"].head(N_EVIDENCE))],
        "headline": f"Blocking {len(p)} projects worth Rs {cap:,.0f} Cr", "note": NOTE,
    }


def cluster(m: pd.DataFrame, cur: pd.DataFrame, min_projects=MIN_PROJECTS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(bottlenecks, members) from member rows (see members())."""
    rows, parts = [], []
    fine = {}
    for key, g in m.groupby(["category", "authority", "state"], sort=True):
        if g["project_key"].nunique() >= min_projects:
            rows.append(_describe("authority", key, g, cur))
            parts.append(g.assign(bottleneck_id=rows[-1]["bottleneck_id"]))
        if key[1] == UNSPECIFIED:
            fine[key[0], key[2]] = set(g["project_key"])
    for (category, state), g in m.groupby(["category", "state"], sort=True):
        keys = set(g["project_key"])
        unspecified = set(g.loc[g["authority"].eq(UNSPECIFIED), "project_key"])
        if len(keys) >= min_projects and len(unspecified) * 2 >= len(keys) and keys != fine.get((category, state)):
            rows.append(_describe("state", (category, None, state), g, cur))
            parts.append(g.assign(bottleneck_id=rows[-1]["bottleneck_id"]))
    b = pd.DataFrame(rows, columns=COLS)
    b = b.sort_values(["capital_exposed_cr", "bottleneck_id"], ascending=[False, True], ignore_index=True)
    mem = pd.concat(parts, ignore_index=True) if parts else m.iloc[:0].assign(bottleneck_id=None)
    return b, mem[MEMBER_COLS].sort_values(["bottleneck_id", "project_key", "last_seen"], ignore_index=True)


def summary(b: pd.DataFrame, mem: pd.DataFrame, cur: pd.DataFrame, asof, n_signals: int, source) -> dict:
    keys = set(mem["project_key"])
    return {
        "as_of_date": str(pd.Timestamp(asof).date()), "min_projects": MIN_PROJECTS,
        "n_bottlenecks": int(b["level"].eq("authority").sum()), "n_rollups": int(b["level"].eq("state").sum()),
        "n_projects": len(keys),
        "capital_exposed_cr": round(float(cur.loc[cur["project_key"].isin(keys), "anticipated_cost_cr"].sum()), 1),
        "by_category": {c: int(n) for c, n in b["category"].value_counts().sort_index().items()},
        "signals_used": n_signals, "signals_source": source, "note": NOTE,
    }


def main(gold=GOLD, db=None):
    t0 = time.time()
    ptr = json.loads((gold / "predictions_latest.json").read_text(encoding="utf-8"))
    cur = pd.read_parquet(ROOT / ptr["path"], columns=CUR_COLS)
    events = pd.read_parquet(gold / "project_events.parquet")
    db = Path(db or os.environ.get("PAIMANA_DB") or DB)
    signals = load_signals(db)
    m = members(events, cur, signals)
    b, mem = cluster(m, cur)
    b.insert(1, "asof", pd.Timestamp(ptr["asof"]))
    b.to_parquet(gold / "bottlenecks.parquet", index=False)
    mem.to_parquet(gold / "bottleneck_members.parquet", index=False)
    s = summary(b, mem, cur, ptr["asof"], int(m["kind"].eq("signal").sum()),
                db.relative_to(ROOT).as_posix() if db.exists() and db.is_relative_to(ROOT) else None)
    (gold / "bottlenecks_summary.json").write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
    print(f"bottlenecks: {s['n_bottlenecks']} clusters + {s['n_rollups']} state rollups over {s['n_projects']} "
          f"projects (Rs {s['capital_exposed_cr']:,.0f} Cr), {s['signals_used']} signal rows, {time.time() - t0:.1f}s")
    with pd.option_context("display.width", 250, "display.max_colwidth", 60):
        print(b.head(10)[["level", "category", "authority", "state", "n_projects", "n_critical_high",
                          "headline"]].to_string(index=False))
    return b, mem, s


if __name__ == "__main__":
    main()
