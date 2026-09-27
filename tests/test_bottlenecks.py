import sqlite3
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import bottlenecks as bn  # noqa: E402

T = pd.Timestamp


def cur_frame():
    rows = [("P1", "Maharashtra", "Critical", .9, 100.0), ("P2", "Maharashtra", "High", .7, 200.0),
            ("P3", "Maharashtra", "Low", .1, 300.0), ("P4", "Maharashtra", None, None, 50.0),
            ("P5", "Odisha", "Medium", .4, 10.0), ("P6", "Odisha", "Low", .2, 20.0), ("P7", "Odisha", "Low", .2, 30.0)]
    return pd.DataFrame([{"project_key": k, "project_name": f"Project {k}", "state": s, "tier": t, "p_any_2q": p,
                          "months_p50": 3.0 if p else None, "anticipated_cost_cr": c} for k, s, t, p, c in rows])


def event(key, category="land", authority=None, status="open", first="2019-01-01", last="2023-01-01"):
    return {"project_key": key, "category": category, "authority": authority, "status": status,
            "first_seen": T(first), "last_seen": T(last), "evidence": f"{category} issue at {key}",
            "source_doc_id": "doc", "source_page": 1}


def test_three_projects_make_a_bottleneck_with_capital_and_tiers():
    ev = pd.DataFrame([event("P1"), event("P2"), event("P3", first="2017-04-01"), event("P4", status="closed"),
                       event("P5"), event("P6", category="forest_env"), event("GONE")])   # GONE: not current
    b, mem = bn.cluster(bn.members(ev, cur_frame(), bn.load_signals("nowhere.db")), cur_frame())
    assert len(b) == 1
    r = b.iloc[0]
    assert (r["category"], r["authority"], r["state"], r["level"]) == ("land", "unspecified", "Maharashtra",
                                                                       "authority")
    assert r["n_projects"] == 3 and r["member_keys"] == ["P1", "P2", "P3"]            # riskiest first
    assert r["capital_exposed_cr"] == 600.0 and r["n_critical_high"] == 2
    assert abs(r["mean_p_any_2q"] - (.9 + .7 + .1) / 3) < 1e-9
    assert r["earliest_first_seen"] == T("2017-04-01") and len(r["evidence"]) == 3
    assert r["headline"] == "Blocking 3 projects worth Rs 600 Cr"
    assert "not a causal claim" in r["note"] and "speed" not in (r["headline"] + r["note"]).lower()
    assert set(mem["project_key"]) == {"P1", "P2", "P3"} and set(mem["bottleneck_id"]) == {r["bottleneck_id"]}


def test_ids_are_stable_and_authorities_split_clusters():
    ev = pd.DataFrame([event("P1", authority="State Govt"), event("P2", authority="State Govt"),
                       event("P3", authority="High Court"), event("P5"), event("P6"), event("P7")])
    b1, _ = bn.cluster(bn.members(ev, cur_frame(), bn.load_signals("nowhere.db")), cur_frame())
    b2, _ = bn.cluster(bn.members(ev.iloc[::-1], cur_frame(), bn.load_signals("nowhere.db")), cur_frame())
    # Maharashtra: 2 + 1 named, no cluster of 3 and mostly named, so no rollup; Odisha: 3 unspecified
    assert b1[["bottleneck_id", "state", "n_projects"]].values.tolist() == [
        [bn.bottleneck_id("authority", "land", "unspecified", "Odisha"), "Odisha", 3]]
    assert b1["bottleneck_id"].tolist() == b2["bottleneck_id"].tolist()


def test_state_rollup_when_authority_is_mostly_unspecified():
    ev = pd.DataFrame([event("P1"), event("P2"), event("P3", authority="State Govt")])
    b, _ = bn.cluster(bn.members(ev, cur_frame(), bn.load_signals("nowhere.db")), cur_frame())
    assert b[["level", "authority", "n_projects"]].values.tolist() == [["state", None, 3]]
    # no rollup that repeats the unspecified cluster's projects
    ev = pd.DataFrame([event("P1"), event("P2"), event("P3")])
    b, _ = bn.cluster(bn.members(ev, cur_frame(), bn.load_signals("nowhere.db")), cur_frame())
    assert b["level"].tolist() == ["authority"]


def test_signals_add_members_and_evidence_from_the_database(tmp_path):
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as con:
        con.executescript("""CREATE TABLE signals (id INTEGER PRIMARY KEY, url TEXT, title TEXT, source TEXT,
            published_at TEXT, category TEXT, severity INTEGER);
            CREATE TABLE signal_projects (signal_id INTEGER, project_key TEXT);""")
        con.executemany("INSERT INTO signals VALUES (?, ?, ?, ?, ?, ?, ?)", [
            (1, "u1", "Farmers stall land handover", "Daily", "2026-08-01T00:00:00+00:00", "land", 2),
            (2, "u2", "Mention only", "Daily", "2026-08-02T00:00:00+00:00", "land", 1),        # severity 1
            (3, "u3", "Protest", "Daily", "2026-08-03T00:00:00+00:00", None, 3),               # no category
            (4, "u4", "Land row at P1", "Daily", "2026-08-04T00:00:00+00:00", "land", 3)])
        con.executemany("INSERT INTO signal_projects VALUES (?, ?)", [(1, "P3"), (2, "P4"), (3, "P4"), (4, "P1")])
    sig = bn.load_signals(db)
    assert sorted(sig["project_key"]) == ["P1", "P3"]
    ev = pd.DataFrame([event("P1", authority="State Govt"), event("P2")])
    b, mem = bn.cluster(bn.members(ev, cur_frame(), sig), cur_frame())
    # P3 joins through its signal (unspecified); P1's signal takes its event's authority: 2 + 1, rollup only
    assert b[["level", "n_projects", "n_signals"]].values.tolist() == [["state", 3, 2]]
    assert b.iloc[0]["last_seen"] == T("2026-08-04")
    assert mem.loc[mem["kind"].eq("signal"), "authority"].tolist() == ["State Govt", "unspecified"]


def test_multi_state_needs_a_named_authority_and_cleared_events_are_left_out():
    cur = pd.DataFrame([{"project_key": k, "project_name": k, "state": "Multi-State", "tier": "Low", "p_any_2q": .2,
                         "months_p50": 1.0, "anticipated_cost_cr": 10.0} for k in ("M1", "M2", "M3", "M4")])
    ev = pd.DataFrame([event(k, category="forest_env") for k in ("M1", "M2", "M3")])
    b, _ = bn.cluster(bn.members(ev, cur, bn.load_signals("nowhere.db")), cur)
    assert b.empty                                   # no shared place, no shared authority, no rollup
    ev = pd.DataFrame([event(k, category="forest_env", authority="MoEFCC") for k in ("M1", "M2", "M3", "M4")])
    ev.loc[3, "evidence"] = "Forest clearance got on 28.10.2021 and work started"
    b, mem = bn.cluster(bn.members(ev, cur, bn.load_signals("nowhere.db")), cur)
    assert b[["authority", "state", "n_projects"]].values.tolist() == [["MoEFCC", "Multi-State", 3]]
    assert "M4" not in set(mem["project_key"])
    ev.loc[3, "evidence"] = "Forest clearance obtained but land not yet handed over"   # a hold-up: still open
    assert bn.cluster(bn.members(ev, cur, bn.load_signals("nowhere.db")), cur)[0].iloc[0]["n_projects"] == 4
