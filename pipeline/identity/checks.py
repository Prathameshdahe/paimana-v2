"""Invariants to run at the end of `make silver`. Each returns a dict of
counts and raises IdentityCheckError when the invariant is violated, so the
build fails loudly instead of shipping a broken panel."""
from __future__ import annotations

import pandas as pd

from .identity_map import IdentityMap


class IdentityCheckError(AssertionError):
    pass


def check_unique_observations(obs: pd.DataFrame) -> dict:
    dup = obs.duplicated(["project_key", "period"], keep=False)
    n = int(dup.sum())
    if n:
        sample = obs.loc[dup, ["project_key", "period"]].head(10).to_dict("records")
        raise IdentityCheckError(f"{n} duplicate (project_key, period) rows, e.g. {sample}")
    return {"observations": len(obs), "duplicate_key_period": 0}


def check_keys_exist(idmap: IdentityMap, *frames: pd.DataFrame) -> dict:
    known = set(idmap.keys(active_only=False))
    missing = set()
    for df in frames:
        if "project_key" in df.columns:
            missing |= set(df["project_key"].dropna().unique()) - known
    if missing:
        raise IdentityCheckError(f"{len(missing)} project_keys not in identity map, e.g. {sorted(missing)[:10]}")
    return {"known_keys": len(known), "missing": 0}


def check_no_merged_keys_in_use(idmap: IdentityMap, *frames: pd.DataFrame) -> dict:
    merged = {k for k in idmap.keys(active_only=False) if idmap.canonical(k) != k}
    used = set()
    for df in frames:
        if "project_key" in df.columns:
            used |= set(df["project_key"].dropna().unique()) & merged
    if used:
        raise IdentityCheckError(f"merged keys still used downstream: {sorted(used)[:10]}; map through canonical()")
    return {"merged_keys": len(merged), "in_use": 0}


def check_portal_one_to_one(resolved_portal: pd.DataFrame) -> dict:
    """Current portal rows (one per live project) must map 1:1 to accepted keys."""
    acc = resolved_portal[resolved_portal["review_status"] == "accepted"]
    n_review = int((resolved_portal["review_status"] != "accepted").sum())
    collisions = acc["project_key"].value_counts()
    collisions = collisions[collisions > 1]
    if len(collisions):
        raise IdentityCheckError(f"{len(collisions)} keys receive >1 portal row: {collisions.head(10).to_dict()}")
    return {"portal_rows": len(resolved_portal), "accepted": len(acc), "review": n_review}


def run_all(idmap: IdentityMap, obs: pd.DataFrame, resolved_portal: pd.DataFrame | None = None,
            *other_frames: pd.DataFrame) -> dict:
    report = {}
    report["unique_observations"] = check_unique_observations(obs)
    report["keys_exist"] = check_keys_exist(idmap, obs, *other_frames)
    report["no_merged_keys"] = check_no_merged_keys_in_use(idmap, obs, *other_frames)
    if resolved_portal is not None:
        report["portal_one_to_one"] = check_portal_one_to_one(resolved_portal)
    return report
