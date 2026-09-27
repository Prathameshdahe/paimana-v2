"""
Resolve every clean project row (and the portal snapshot) to a stable PRJ-xxxxxx key.

Run from repo root after build_clean_projects.py:  python pipeline/build_identity.py

Inputs   clean/projects/projects_monthly.csv, projects_quarterly.csv, portal/portal_projects.csv,
         projects/project_master.csv (portal code -> clean key), reference/sector_map.csv
Outputs  silver/identity/projects.parquet, aliases.parquet, audit.jsonl   (resolver state, append-only)
         silver/identity/resolved_rows.parquet, review_queue.csv, identity_manifest.json, manual_links.csv

The resolver works on entities, not rows: one entity per clean project_key (the clean layer already
linked rows by printed code, vetted crosswalk and exact name), plus one per portal code with no clean
key. That is ~8.5k resolutions instead of ~167k and the resolver's job is what the clean layer cannot
do: link name-only keys (NAME:*) across eras to the code keys, and keep PRJ keys stable. Every row then
takes its entity's key. The map on disk is read first and only never-seen entities mint, so a re-run
is an alias-cache hit.
Code evidence for an entity is its clean project_key when that key is code-anchored (key_source
printed_code or crosswalk). name_chain / name_link_to_code keys came from name matching and are not
passed as codes. Two different codes never link (identity_map._score).
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.identity import IdentityCheckError, IdentityConfig, IdentityMap  # noqa: E402
from pipeline.identity.checks import (check_keys_exist, check_no_merged_keys_in_use,  # noqa: E402
                                      check_portal_one_to_one)

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "dataset" / "clean"
OUT = ROOT / "dataset" / "silver" / "identity"

# The portal export is a snapshot from about Jul 2026 (clean/README.md), the month of the latest
# PAIMANA flash report. It is a constant, not max(paimana_flash period), so adding a newer flash
# report later does not move the portal rows to a new alias key.
PORTAL_PERIOD = "2026-07-01"
PORTAL_FILE = "portal/portal_projects.csv"
CODE_KEY_SOURCES = ("printed_code", "crosswalk")
KEY_COLS = ["source_report_type", "source_period", "source_row_id"]
MANUAL_COLS = KEY_COLS + ["project_key", "note"]
CONTRACT = ["project_name", "project_code", "sector", "state", "agency", "ministry",
            "original_cost_cr", "sanction_year"]
CONTEXT = ["source_file", "page", "list_type", "printed_code", "clean_project_key"]
ENTITY_TYPE = "clean_key"  # source_report_type of entity rows in the alias table
OUT_COLS = KEY_COLS + ["source_file", "page", "list_type", "project_code", "clean_project_key",
                       "project_key", "match_score", "match_method", "review_status"]


def _name(s):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(s).lower()).split())


def row_ids(df):
    """sha1 of (source_file, page, list_type, printed code, name, original cost), 16 hex, plus '#n'
    for the n-th exact duplicate inside one report. Printed content, not row position, so the id
    survives re-extraction. The name normalisation is local on purpose: tuning normalize.ABBREV must
    not change row ids."""
    txt = lambda c: df[c].map(lambda v: "" if pd.isna(v) else str(v))  # noqa: E731
    page = df["page"].map(lambda v: "" if pd.isna(v) else str(int(v)))
    cost = df["original_cost_cr"].map(lambda v: "" if pd.isna(v) else f"{float(v):.2f}")
    basis = (txt("source_file") + "|" + page + "|" + txt("list_type") + "|" + txt("printed_code") + "|"
             + df["project_name"].fillna("").map(_name) + "|" + cost)
    h = basis.map(lambda s: hashlib.sha1(s.encode("utf-8")).hexdigest()[:16])
    n = h.groupby([df["source_report_type"], df["source_period"], h]).cumcount()
    ids = h.where(n == 0, h + "#" + (n + 1).astype(str))
    dup = pd.DataFrame({"t": df["source_report_type"], "p": df["source_period"], "i": ids}).duplicated()
    assert not dup.any(), f"{int(dup.sum())} source_row_id collisions"
    return ids


def adapt_clean(df):
    """projects_monthly / projects_quarterly rows -> resolver contract."""
    return pd.DataFrame({
        "source_report_type": df["report_type"],
        "source_period": df["report_period"] + "-01",
        "source_file": df["source_file"],
        "page": df["page"],
        "list_type": df["list_type"],
        "printed_code": df["project_code"],
        "clean_project_key": df["project_key"],
        "project_name": df["project_name"],
        "project_code": df["project_key"].where(df["key_source"].isin(CODE_KEY_SOURCES)),
        "sector": df["sector"],
        "state": df["state"],
        "agency": df["agency"],
        "ministry": df["ministry"],
        "original_cost_cr": df["cost_original_cr"],
        "sanction_year": pd.to_numeric(df["doa_original"].str[:4], errors="coerce"),
    })


def adapt_portal(portal, master, sector_map):
    """Portal rows -> resolver contract. The printed PAIMANA code becomes 'PAIMANA:<code>' (the clean
    layer's format) and is then looked up in project_master.project_codes: about half of the PAIMANA
    codes were crosswalked onto an OCMS key, and the code evidence must be that same key or the
    portal row would contradict its own project's flash rows. Sector goes through the HML era of
    sector_map (portal prints the HML label + ministry); the portal has no state column."""
    codes = master.assign(code=master["project_codes"].str.split(";")).explode("code")
    code2key = codes.dropna(subset=["code"]).set_index("code")["project_key"]
    assert code2key.index.is_unique
    pcode = portal["project_code"].astype(str).str.strip()
    hml = sector_map[sector_map["era"].eq("hml")].dropna(subset=["sector_raw", "ministry"])
    sec = portal.merge(hml[["sector_raw", "ministry", "sector"]].drop_duplicates(["sector_raw", "ministry"]),
                       left_on=["sector", "ministry"], right_on=["sector_raw", "ministry"], how="left")
    clean_key = ("PAIMANA:" + pcode).map(code2key)
    return pd.DataFrame({
        "source_report_type": "portal",
        "source_period": PORTAL_PERIOD,
        "source_file": PORTAL_FILE,
        "page": None,
        "list_type": None,
        "printed_code": pcode,
        "clean_project_key": clean_key,
        "project_name": portal["project_name"],
        "project_code": clean_key.fillna("PAIMANA:" + pcode),
        "sector": sec["sector_y"].where(sec["sector_y"].ne("Unknown")).values,
        "state": None,
        "agency": portal["agency"],
        "ministry": portal["ministry"],
        "original_cost_cr": portal["cost_original_cr"].astype(float),
        "sanction_year": pd.to_numeric(portal["sanction_date"].str[:4], errors="coerce"),
    })


def _latest(s):
    s = s.dropna()
    return s.iloc[-1] if len(s) else None


def _first(s):
    s = s.dropna()
    return s.iloc[0] if len(s) else None


def _mode_name(s):
    """Most frequent printed name, ties to the latest. The long-running OCMS spelling usually wins over
    a short recent PAIMANA label, which is what name-only keys from older reports have to match."""
    s = s.dropna()
    if not len(s):
        return None
    counts = s.value_counts(sort=False)
    top = counts[counts.eq(counts.max())].index
    return s[s.isin(top)].iloc[-1]


def entities(rows):
    """One resolver row per entity. Input rows must be sorted by period."""
    ent = rows["clean_project_key"].fillna(rows["project_code"])
    g = rows.assign(entity=ent).groupby("entity", sort=False)
    out = pd.DataFrame({
        "source_period": g["source_period"].min(),
        "project_name": g["project_name"].agg(_mode_name),
        "project_code": g["project_code"].agg(_first),
        "sector": g["sector"].agg(_latest),
        "state": g["state"].agg(_latest),
        "agency": g["agency"].agg(_latest),
        "ministry": g["ministry"].agg(_latest),
        "original_cost_cr": g["original_cost_cr"].agg(_first),
        "sanction_year": g["sanction_year"].agg(_first),
    }).rename_axis("source_row_id").reset_index()
    out.insert(0, "source_report_type", ENTITY_TYPE)
    return out.sort_values(KEY_COLS, kind="mergesort", ignore_index=True), ent


def load_rows(clean):
    proj = pd.concat([pd.read_csv(clean / "projects" / f, low_memory=False)
                      for f in ("projects_monthly.csv", "projects_quarterly.csv")], ignore_index=True)
    portal = pd.read_csv(clean / "portal" / "portal_projects.csv")
    master = pd.read_csv(clean / "projects" / "project_master.csv", low_memory=False)
    sector_map = pd.read_csv(clean / "reference" / "sector_map.csv")
    rows = pd.concat([adapt_clean(proj), adapt_portal(portal, master, sector_map)], ignore_index=True)
    rows["source_row_id"] = row_ids(rows)
    # deterministic minting order (the resolver sorts the same way; sorting here orders the outputs)
    return rows.sort_values(KEY_COLS, kind="mergesort", ignore_index=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", type=Path, default=CLEAN)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args(argv)
    t0 = time.time()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    rows = load_rows(args.clean)
    manual_path = out / "manual_links.csv"
    if not manual_path.exists():
        pd.DataFrame(columns=MANUAL_COLS).to_csv(manual_path, index=False, lineterminator="\n")
    manual = pd.read_csv(manual_path, dtype=str, keep_default_na=False)
    prev_path = out / "resolved_rows.parquet"
    prev = pd.read_parquet(prev_path, columns=KEY_COLS + ["project_key"]) if prev_path.exists() else None

    idmap = IdentityMap(IdentityConfig(root=out), run_id=args.run_id)
    n_before = len(list(idmap.keys(active_only=False)))
    ent, row_entity = entities(rows)
    eres = idmap.resolve_batch(ent, manual=manual)
    idmap.save()
    minted = len(list(idmap.keys(active_only=False))) - n_before
    this_run = eres["match_method"].value_counts().to_dict()
    # cached entities come back as alias_cache; the published method is the one of first resolution
    first = idmap.aliases_frame()[KEY_COLS + ["match_method"]]
    eres = (eres.drop(columns=["match_method"]).merge(first, on=KEY_COLS, how="left", validate="1:1")
            .set_index("source_row_id"))
    res = rows.drop(columns=["project_code"]).rename(columns={"printed_code": "project_code"})
    for c in ("project_key", "match_score", "match_method", "review_status"):
        res[c] = row_entity.map(eres[c]).values
    assert res["project_key"].notna().all()
    res[OUT_COLS].to_parquet(out / "resolved_rows.parquet", index=False)

    # one line per entity to confirm; confirm by copying its KEY_COLS into manual_links.csv
    names = idmap.projects_frame()[["project_key", "canonical_name"]].rename(columns={"canonical_name": "linked_name"})
    n_rows = row_entity.value_counts().rename("n_rows")
    queue = (eres[eres["review_status"].eq("review")].join(n_rows).reset_index()
             .merge(names, on="project_key", how="left")
             .sort_values(["match_score", "source_row_id"], kind="mergesort"))
    queue[KEY_COLS + ["project_name", "project_code", "n_rows", "project_key", "linked_name", "match_score",
                      "match_method"]].to_csv(out / "review_queue.csv", index=False, lineterminator="\n")

    checks = {}
    portal = res[res["source_report_type"].eq("portal")]
    for name, fn in (("keys_exist", lambda: check_keys_exist(idmap, res)),
                     ("no_merged_keys", lambda: check_no_merged_keys_in_use(idmap, res)),
                     ("portal_one_to_one", lambda: check_portal_one_to_one(portal))):
        try:
            checks[name] = fn()
        except IdentityCheckError as e:
            checks[name] = {"failed": str(e)}

    clean = res[res["source_report_type"].ne("portal")]
    rerun = {"minted_this_run": minted, "method_this_run": this_run}
    if prev is not None:
        j = prev.merge(res[KEY_COLS + ["project_key"]], on=KEY_COLS, suffixes=("_prev", ""))
        rerun.update(rows_in_previous_run=len(j), keys_changed_vs_previous=int(j["project_key_prev"].ne(j["project_key"]).sum()))
    summary = {
        "run_id": idmap.run_id,
        "runtime_seconds": round(time.time() - t0, 1),
        "rows": len(res),
        "entities": len(ent),
        "entity_status": eres["review_status"].value_counts().to_dict(),
        "rows_by_report_type": res["source_report_type"].value_counts().to_dict(),
        "keys": len(list(idmap.keys())),
        "clean_keys": int(clean["clean_project_key"].nunique()),
        "clean_keys_split_across_prj_keys": int((clean.groupby("clean_project_key")["project_key"].nunique() > 1).sum()),
        "prj_keys_holding_several_clean_keys": int((clean.groupby("project_key")["clean_project_key"].nunique() > 1).sum()),
        "status": res["review_status"].value_counts().to_dict(),
        "review_share": round(float(res["review_status"].eq("review").mean()), 4),
        "method": res["match_method"].value_counts().to_dict(),
        "rerun": rerun,
        "checks": checks,
    }
    (out / "identity_manifest.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    failed = [k for k, v in checks.items() if "failed" in v]
    if failed:
        raise SystemExit(f"identity checks failed: {failed}")


if __name__ == "__main__":
    main()
