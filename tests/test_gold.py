import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import gold  # noqa: E402

QUARTERS = pd.date_range("2014-01-01", "2019-10-01", freq="QS").astype("datetime64[us]")


def panel(n_keys=40, seed=7):
    """Synthetic silver observations: gappy quarterly rows, rising progress and spend, occasional cost
    revisions and completion pushes, three agencies, two sectors; some keys complete."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_keys):
        start = int(rng.integers(0, 8))
        periods = [p for p in QUARTERS[start:start + int(rng.integers(6, 18))] if rng.random() > 0.15]
        cost, prog, spend = float(rng.uniform(200, 8000)), 0.0, 0.0
        sanction = QUARTERS[start] - pd.DateOffset(months=int(rng.integers(0, 24)))
        sched = sanction + pd.DateOffset(months=int(rng.integers(24, 60)))
        ant = sched
        for i, p in enumerate(periods):
            prog = min(100.0, prog + float(rng.choice([0, 0.2, 5, 12, 25])))
            spend = min(1.2, spend + float(rng.uniform(0, 0.12)))
            if rng.random() < 0.2:
                cost *= 1.1
            if rng.random() < 0.25:
                ant = ant + pd.DateOffset(months=int(rng.integers(3, 12)))
            done = prog >= 100
            rows.append({
                "project_key": f"PRJ-{k:06d}", "period": p, "period_type": "quarterly",
                "original_cost_cr": 1000.0 if k % 5 else None, "anticipated_cost_cr": cost,
                "expenditure_cr": spend * cost, "physical_progress_pct": None if rng.random() < 0.1 else prog,
                "sanction_date": sanction, "scheduled_completion": sched,
                "anticipated_completion": None if rng.random() < 0.1 else ant, "is_completed": done,
                "cost_basis": "anticipated", "completion_basis": "anticipated",
                "agency": ["NHAI", "Rail Vikas [RVNL]", None][k % 3], "ministry": None,
                "sector": ["Roads & Highways", "Railways"][k % 2], "state": "Goa", "delay_months": None,
                "obs_count_in_quarter": 1, "months_since_last_obs": 3, "dq_score": 1.0})
            if done:
                break
    d = pd.DataFrame(rows)
    for c in ("period", "sanction_date", "scheduled_completion", "anticipated_completion"):
        d[c] = pd.to_datetime(d[c]).astype("datetime64[us]")
    d["months_since_last_obs"] = d["months_since_last_obs"].astype("Int64")
    return d


def sectors():
    return pd.DataFrame({"sector": "Railways", "period": QUARTERS, "actual_target_ratio": 0.9,
                         "yoy_growth_pct": 4.0, "trend_4q": 3.5})


def external(mentions=(), stretches=(), fc_keys=()):
    """Gold's external inputs: mentions as (key, quarter index, category or None, resolved), land stretches as
    (key, parcels, complexity, first notification, last notification); fc_keys get a forest-clearance prior."""
    m = pd.DataFrame(list(mentions), columns=["project_key", "q", "category", "resolved"])
    s = pd.DataFrame(list(stretches), columns=["project_key", "num_parcels", "acquisition_complexity_score",
                                               "first_notif_date", "last_notif_date"])
    s = s.assign(project_key=s["project_key"].astype("str"), stretch_id=np.arange(len(s)),
                 first_notif_date=pd.to_datetime(s["first_notif_date"]).astype("datetime64[us]"),
                 last_notif_date=pd.to_datetime(s["last_notif_date"]).astype("datetime64[us]"))
    return {"mentions": pd.DataFrame({"project_key": m["project_key"].astype("str"),
                                      "period": QUARTERS[m["q"].to_numpy(dtype=int)],
                                      "category": m["category"].astype("str"),
                                      "resolved": m["resolved"].astype("boolean")}),
            "fc": pd.DataFrame({"project_key": pd.Series(list(fc_keys), dtype="str"),
                                "fc_prior_expected_complexity": 3.0, "fc_prior_worst_complexity": 7,
                                "fc_prior_max_authority_level": 4}),
            "land_pairs": s}


def panel_external(full, seed=11):
    """Random remark quarters and land stretches for half the panel's keys."""
    rng = np.random.default_rng(seed)
    keys = sorted(full["project_key"].unique())
    mentions, stretches = [], []
    for k in keys[::2]:
        for q in sorted(rng.choice(len(QUARTERS), 8, replace=False)):
            cats = {c for c in rng.choice(gold.EXT_CATS[:3] + [None] * 3, 2) if c} or {None}
            mentions += [(k, q, c, None if c is None else bool(rng.random() < 0.3)) for c in cats]
    for k in keys[:6]:
        for _ in range(2):
            first = QUARTERS[int(rng.integers(0, len(QUARTERS)))] + pd.Timedelta(days=int(rng.integers(0, 80)))
            last = first + pd.Timedelta(days=int(rng.integers(0, 900)))
            stretches.append((k, int(rng.integers(10, 500)), int(rng.integers(0, 6)), first, last))
    return external(mentions, stretches, keys[::3])


EXT = panel_external(panel())


def build(d, cutoff=None, ext=EXT):
    return gold.build_features(d, cutoff=cutoff, sectors=sectors(), external=ext)


def at(f, t):
    return f[f["period"] == t].sort_values("project_key", ignore_index=True)


def test_key_features_ignore_its_later_rows():
    full = panel()
    key = full["project_key"].value_counts().index[0]
    rows = full[full["project_key"] == key]
    t = rows["period"].iloc[len(rows) // 2]
    cut = full[(full["project_key"] != key) | (full["period"] <= t)]
    a = build(cut)
    b = build(full)
    a, b = (f[(f["project_key"] == key)].reset_index(drop=True) for f in (a, b))
    pd.testing.assert_frame_equal(a, b.iloc[:len(a)])
    assert len(b) > len(a)


def test_velocity_and_stagnation():
    d = panel(1).iloc[:0]
    base = {c: None for c in d.columns}
    prog = [10, 20, 20.2, 20.4, 40]
    rows = [base | {"project_key": "PRJ-000001", "period": QUARTERS[i], "physical_progress_pct": p,
                    "anticipated_cost_cr": 100.0, "is_completed": False, "sector": "Railways",
                    "period_type": "quarterly", "obs_count_in_quarter": 1, "dq_score": 1.0}
            for i, p in enumerate(prog)]
    d = pd.DataFrame(rows).astype({"period": "datetime64[us]", "sanction_date": "datetime64[us]",
                                   "scheduled_completion": "datetime64[us]",
                                   "anticipated_completion": "datetime64[us]"})
    f = build(d)
    assert f["progress_velocity_2q"].tolist()[2:] == pytest.approx([5.1, 0.2, 9.9])
    assert f["stagnation_quarters"].tolist() == [0, 0, 1, 2, 0]


def obs_rows(key, rows, agency="NHAI"):
    """Minimal observations for one key: rows are (quarter index, cost, anticipated completion, completed)."""
    d = pd.DataFrame([{"project_key": key, "period": QUARTERS[q], "anticipated_cost_cr": c,
                       "anticipated_completion": a, "is_completed": done} for q, c, a, done in rows])
    d["anticipated_completion"] = pd.to_datetime(d["anticipated_completion"]).astype("datetime64[us]")
    template = panel(1).iloc[:0]
    d = pd.concat([template, d], ignore_index=True).assign(
        agency=agency, sector="Railways", period_type="quarterly", obs_count_in_quarter=1, dq_score=1.0,
        cost_basis="anticipated", completion_basis="anticipated",
        original_cost_cr=d["anticipated_cost_cr"], physical_progress_pct=50.0)
    return d.astype(template.dtypes.to_dict())


def test_labels_exact_horizon_and_null_inputs():
    d = pd.concat([obs_rows("PRJ-000001", [(0, 100.0, "2020-01", False), (1, 100.0, "2020-01", False),
                                           (2, 104.0, None, False), (3, 110.0, "2020-06", False),
                                           (4, 110.0, "2020-06", True)]),
                   obs_rows("PRJ-000002", [(0, 100.0, "2020-01", False), (1, 100.0, "2020-01", False),
                                           (3, 100.0, "2020-01", False)])], ignore_index=True)
    lab = gold.build_labels(d, 2).set_index(["project_key", "period"])
    assert list(lab.index) == [("PRJ-000001", QUARTERS[q]) for q in (0, 1, 2)] + [("PRJ-000002", QUARTERS[1])]
    rows = lab[["y_date_push", "y_cost_rev", "y_any"]].astype("float64").to_numpy().tolist()
    nan = float("nan")
    assert np.array_equal(rows, [[nan, 0, nan], [1, 1, 1], [nan, 1, nan], [0, 0, 0]], equal_nan=True)
    assert lab["y_months"].tolist()[1] == 5 and lab["y_cost_pct"].iloc[0] == pytest.approx(4.0)
    assert (lab["target_period"] == [QUARTERS[q] for q in (2, 3, 4, 3)]).all()


def test_labels_null_across_a_basis_change():
    rows = [(0, 100.0, "2020-01", False), (2, 150.0, "2020-09", False)]
    same = gold.build_labels(obs_rows("PRJ-000001", rows), 2)
    assert same[["y_date_push", "y_cost_rev", "y_any"]].iloc[0].tolist() == [1, 1, 1]
    d = obs_rows("PRJ-000001", rows)
    d.loc[1, "cost_basis"] = "revised"              # t + h prints revised cost, t printed anticipated
    lab = gold.build_labels(d, 2).iloc[0]
    assert pd.isna(lab["y_cost_rev"]) and pd.isna(lab["y_cost_pct"]) and pd.isna(lab["y_any"])
    assert lab["y_date_push"] == 1 and lab["y_months"] == 8
    d.loc[1, "completion_basis"] = "revised"
    lab = gold.build_labels(d, 2).iloc[0]
    assert pd.isna(lab["y_date_push"]) and pd.isna(lab["y_months"])


def test_cutoff_bounds_feature_frame():
    c = QUARTERS[12]
    f = build(panel(), cutoff=c)
    assert f["period"].max() == c


def test_features_at_t_same_on_truncated_panel():
    full = panel()
    b = build(full)
    for t in QUARTERS[3::2]:
        a = build(full[full["period"] <= t])
        pd.testing.assert_frame_equal(at(a, t), at(b, t))
        pd.testing.assert_frame_equal(at(build(full, cutoff=t), t), at(b, t))


def test_agency_stats_count_only_realised_labels():
    # key 1 slips between q0 and q2; that outcome is known at q2, not at q1
    d = pd.concat([obs_rows("PRJ-000001", [(0, 100.0, "2020-01", False), (2, 100.0, "2020-09", False)]),
                   obs_rows("PRJ-000002", [(1, 100.0, "2021-01", False), (2, 100.0, "2021-01", False),
                                           (3, 100.0, "2021-01", False)])], ignore_index=True)
    f = build(d).set_index(["project_key", "period"])
    k2 = f.loc["PRJ-000002"]
    assert k2["agency_n"].tolist() == [0, 1, 2]
    assert k2["agency_slip_rate"].iloc[1] > k2["agency_slip_rate"].iloc[0] or pd.isna(k2["agency_slip_rate"].iloc[0])


def test_agency_n_matches_brute_force():
    full = panel()
    f = build(full)
    lab = gold.build_labels(gold.base(full), gold.AGENCY_H).merge(f[["project_key", "period", "agency"]],
                                                                  on=["project_key", "period"])
    pairs = f[["project_key", "period", "agency"]].merge(lab.loc[lab["agency"].notna(), ["agency", "target_period"]],
                                                          on="agency")
    want = (pairs[pairs["target_period"] <= pairs["period"]].groupby(["project_key", "period"]).size()
            .reindex(pd.MultiIndex.from_frame(f[["project_key", "period"]]), fill_value=0))
    assert (f["agency_n"].to_numpy() == want.to_numpy()).all()
    assert f.loc[f["agency"].isna(), "agency_n"].eq(0).all()


def test_recent_slip_rates_match_brute_force_and_ignore_later_outcomes():
    full = panel(60)
    f = build(full)
    lab = gold.build_labels(gold.base(full), gold.AGENCY_H).merge(f[["project_key", "period", "agency", "sector"]],
                                                                  on=["project_key", "period"])
    lab = lab[lab["y_date_push"].notna()]
    k = gold.SHRINK_K
    for _, r in f.sample(40, random_state=0).iterrows():
        win = lab[(lab["target_period"] <= r["period"])
                  & (lab["target_period"] > r["period"] - pd.DateOffset(months=3 * gold.RECENT_Q))]
        if win.empty:
            assert pd.isna(r["sector_slip_4q"]) and pd.isna(r["agency_slip_4q"])
            continue
        sec, ag = win[win["sector"] == r["sector"]], win[win["agency"] == r["agency"]]
        want_sec = (sec["y_date_push"].sum() + k * win["y_date_push"].mean()) / (len(sec) + k)
        want_ag = (ag["y_date_push"].sum() + k * want_sec) / (len(ag) + k)
        assert r["sector_slip_4q"] == pytest.approx(want_sec) and r["agency_slip_4q"] == pytest.approx(want_ag)
    # every label realised after t changes: the rates at t do not
    flip = full.assign(anticipated_completion=full["anticipated_completion"] + pd.DateOffset(months=9))
    t = QUARTERS[12]
    keep = full["period"] <= t
    g = build(pd.concat([full[keep], flip[~keep]], ignore_index=True))
    cols = ["agency_slip_4q", "sector_slip_4q"]
    pd.testing.assert_frame_equal(at(g, t)[cols], at(f, t)[cols])
    assert {"agency_slip_4q", "sector_slip_4q"} <= set(gold.FEATURE_GROUPS["context"])


def test_external_open_at_t_follows_the_last_two_remark_quarters():
    k = "PRJ-000001"
    d = obs_rows(k, [(q, 100.0, "2020-01", False) for q in range(7)])
    ext = external([(k, 0, "land", False), (k, 1, None, None), (k, 2, None, None), (k, 3, "land", True),
                    (k, 5, "forest_env", False)])
    f = build(d, ext=ext)
    assert f["ext_open_land"].tolist() == [1, 1, 0, 0, 0, 0, 0]          # q2: q0 is no longer in the last 2
    assert f["ext_ever_land"].tolist() == [1] * 7                         # q3 reports it done: closed, not unseen
    assert f["ext_open_forest_env"].tolist() == [0, 0, 0, 0, 0, 1, 1]     # q6 has no remarks: q5 is still recent
    assert f["ext_remark_quarters"].tolist() == [1, 2, 3, 4, 4, 5, 5]
    assert f["ext_months_since_first_land"].tolist() == [0, 3, 6, 9, 12, 15, 18]
    assert f["ext_months_since_first_forest_env"].isna().tolist() == [True] * 5 + [False] * 2
    assert f["ext_open_total"].tolist() == [1, 1, 0, 0, 0, 1, 1]
    assert f["ext_open_age_q"].fillna(-1).tolist() == [0, 1, -1, -1, -1, 0, 1]   # null when nothing is open
    assert f["fc_expected_complexity"].isna().all() and f["la_linked"].eq(0).all()
    assert f["la_parcels_by_t"].isna().all()                              # unlinked: unknown, not 0


def test_open_flags_expire_four_calendar_quarters_after_the_last_mention():
    # land mentioned at q0 only, and no remarks after it: still open by the remark rule, stale by the calendar
    k = "PRJ-000001"
    d = obs_rows(k, [(q, 100.0, "2020-01", False) for q in range(7)])
    f = build(d, ext=external([(k, 0, "land", False)]))
    assert f["ext_open_land"].tolist() == [1, 1, 1, 1, 0, 0, 0]
    assert f["ext_open_age_q"].tolist() == [0, 1, 2, 3, 4, 5, 6]          # the age keeps counting once expired
    assert f["ext_open_total"].tolist() == [1, 1, 1, 1, 0, 0, 0]
    assert f["ext_ever_land"].eq(1).all()
    assert not {"ministry", "fc_worst_complexity", "fc_max_authority_level"} & set(gold.FEATURES)


def test_land_features_count_only_stretches_notified_by_t():
    k = "PRJ-000001"
    d = obs_rows(k, [(q, 100.0, "2020-01", False) for q in range(8)])
    ext = external(stretches=[(k, 100, 4, QUARTERS[4], QUARTERS[7]), (k, 50, 1, QUARTERS[6], QUARTERS[6])],
                   fc_keys=[k])
    f = build(d, ext=ext).set_index("period")
    assert f.loc[QUARTERS[3], ["la_parcels_by_t", "la_complexity_max_by_t"]].isna().all()   # unknown, not 0
    assert f["la_linked"].tolist() == [0] * 4 + [1] * 4
    # still being notified at t: linked with its span so far (cut at t), parcels and complexity not known yet
    assert f.loc[QUARTERS[5], ["la_notif_span_by_t"]].tolist() == [(QUARTERS[5] - QUARTERS[4]).days]
    assert f.loc[QUARTERS[5], ["la_parcels_by_t", "la_complexity_max_by_t"]].isna().all()
    assert f.loc[QUARTERS[6], ["la_parcels_by_t", "la_complexity_max_by_t"]].tolist() == [50, 1]
    assert f.loc[QUARTERS[7], ["la_parcels_by_t", "la_complexity_max_by_t"]].tolist() == [150, 4]
    assert f["fc_expected_complexity"].eq(3).all()


def test_land_totals_notified_after_t_do_not_reach_t():
    k = "PRJ-000001"
    d = obs_rows(k, [(q, 100.0, "2020-01", False) for q in range(8)])
    small, big = (build(d, ext=external(stretches=[(k, n, c, QUARTERS[2], QUARTERS[6])])) for n, c in [(10, 0), (900, 5)])
    cols = ["la_linked", "la_parcels_by_t", "la_complexity_max_by_t", "la_notif_span_by_t"]
    pd.testing.assert_frame_equal(small.loc[small["period"] < QUARTERS[6], cols],
                                  big.loc[big["period"] < QUARTERS[6], cols])
    assert small["la_linked"].tolist() == [0, 0] + [1] * 6
    assert big.loc[big["period"] >= QUARTERS[6], "la_parcels_by_t"].eq(900).all()
    cut = gold.external_until(external(stretches=[(k, 900, 5, QUARTERS[2], QUARTERS[6])]), QUARTERS[4])["land_pairs"]
    assert cut[["num_parcels", "acquisition_complexity_score", "last_notif_date"]].isna().all(axis=None)


def test_external_features_at_t_ignore_later_remarks_and_stretches():
    full = panel()
    b = build(full)
    keys = sorted(full["project_key"].unique())
    for t in QUARTERS[3:-1:4]:
        later = QUARTERS.get_loc(t) + 1
        extra = external([(k, q, "land", False) for k in keys for q in range(later, len(QUARTERS), 3)],
                         [(k, 999, 5, QUARTERS[later], QUARTERS[-1]) for k in keys[:10]])
        more = {n: pd.concat([EXT[n], extra[n]], ignore_index=True) for n in ("mentions", "land_pairs")}
        a = build(full, ext={**EXT, **more})
        cut = build(full, ext=gold.external_until({**EXT, **more}, t))
        for f in (a, cut):
            pd.testing.assert_frame_equal(f[f["period"] <= t].reset_index(drop=True),
                                          b[b["period"] <= t].reset_index(drop=True))
        assert not a[a["period"] > t].equals(b[b["period"] > t])        # the appended rows do reach later t
