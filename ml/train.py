"""
PAIMANA Radar slip-prediction pipeline.
One script: load -> label -> features (Tier1+Tier2) -> split -> baselines -> LightGBM -> SHAP -> latest scoring.

Kept as a single file on purpose: the two gold CSVs and the files in model/ are the
deliverable. Split into modules if this grows a second entrypoint.

Run from the repo root:  python ml/train.py
"""
import json
import os
import warnings
from datetime import date

import numpy as np
import pandas as pd
import lightgbm as lgb
import shap
from sklearn.linear_model import LogisticRegression
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SILVER = f"{ROOT}/dataset/silver"
GOLD = f"{ROOT}/dataset/gold"
MODEL_DIR = f"{ROOT}/model"

TIER1_NUM = ["cost_original", "cost_revised", "cost_anticipated", "cost_overrun_pct",
             "delay_months", "physical_progress", "cumulative_expenditure"]
TIER1_CAT = ["sector", "state", "project_type", "agency"]
TIER2_ENGINEERED = ["pct_time_elapsed", "optimism_gap", "progress_velocity", "disparity_index",
                     "spend_velocity", "n_prior_revisions", "months_since_last_revision",
                     "staleness_flag", "size_band", "agency_past_slip_rate"]
TIER1_FEATURES = TIER1_NUM + TIER1_CAT
TIER2_FEATURES = TIER1_FEATURES + TIER2_ENGINEERED
CAT_FEATURES = TIER1_CAT + ["size_band"]


def month_num(ts):
    return None if pd.isna(ts) else ts.year * 12 + ts.month


def not_equal(a, b):
    a_na, b_na = pd.isna(a), pd.isna(b)
    if a_na and b_na:
        return False
    if a_na != b_na:
        return True
    return a != b


def load_data():
    frames = []
    for f in ["project_monitoring_2024-25_clean.csv", "project_monitoring_2025-26_clean.csv"]:
        d = pd.read_csv(f"{SILVER}/{f}")
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["report_date"] = pd.to_datetime(df["report_date"], format="%Y-%m")
    for c in ["doc_original", "doc_revised", "doc_anticipated"]:
        df[c] = pd.to_datetime(df[c], format="%Y-%m", errors="coerce")
    df = df.sort_values(["project_id", "report_date"]).reset_index(drop=True)
    return df


def build_labels(df):
    """label for row i uses ONLY row i and its chronological 'next' row of the SAME project.
    LEAKAGE BOUNDARY: this is the one place next.* is read at all; features (featurize_project)
    never touch it. dropped_pairs counts (row,next) pairs where neither the date nor cost
    component was computable."""
    rows = []
    dropped = 0
    for pid, g in df.groupby("project_id", sort=False):
        g = g.sort_values("report_date").reset_index()
        for i in range(len(g) - 1):
            cur, nxt = g.iloc[i], g.iloc[i + 1]
            date_usable = pd.notna(cur["doc_anticipated"])
            nxt_date = nxt["doc_anticipated"] if pd.notna(nxt["doc_anticipated"]) else nxt["doc_revised"]
            date_usable = date_usable and pd.notna(nxt_date)
            date_slip = False
            if date_usable:
                date_slip = (month_num(nxt_date) - month_num(cur["doc_anticipated"])) >= 3

            cost_usable = pd.notna(cur["cost_anticipated"]) and cur["cost_anticipated"] not in (0, 0.0) \
                and pd.notna(nxt["cost_anticipated"])
            cost_slip = False
            if cost_usable:
                cost_slip = ((nxt["cost_anticipated"] - cur["cost_anticipated"]) / cur["cost_anticipated"]) >= 0.05

            if not date_usable and not cost_usable:
                dropped += 1
                continue
            label = 1 if (date_slip or cost_slip) else 0
            rows.append({"project_id": pid, "report_date": cur["report_date"],
                         "next_report_date": nxt["report_date"], "label": label})
    return pd.DataFrame(rows), dropped


def featurize_project(g):
    """Point-in-time Tier1+Tier2(minus agency_past_slip_rate, size_band) features for EVERY row
    of one project's history, in chronological order. Row k's output uses ONLY rows 0..k of
    this same slice -- never a later row. Reused verbatim for (a) every labeled row of the
    training panel and (b) each project's single latest row: both are just different
    row-selections over this same per-row output, so the logic lives in exactly one place."""
    g = g.sort_values("report_date").reset_index(drop=True)
    prev = None
    n_revisions = 0
    last_revision_date = None
    out = []
    for _, r in g.iterrows():
        feat = {c: r[c] for c in TIER1_NUM + TIER1_CAT}

        pte = np.nan
        if pd.notna(r["doc_original"]) and pd.notna(r["doc_anticipated"]):
            denom = month_num(r["doc_anticipated"]) - month_num(r["doc_original"])
            if denom > 0:
                pte = (month_num(r["report_date"]) - month_num(r["doc_original"])) / denom
                pte = min(max(pte, 0), 2)
        feat["pct_time_elapsed"] = pte
        feat["optimism_gap"] = pte - r["physical_progress"] / 100 if pd.notna(pte) and pd.notna(r["physical_progress"]) else np.nan

        if pd.notna(r["cumulative_expenditure"]) and pd.notna(r["cost_anticipated"]) and r["cost_anticipated"] != 0:
            feat["disparity_index"] = (r["cumulative_expenditure"] / r["cost_anticipated"] * 100) - r["physical_progress"]
        else:
            feat["disparity_index"] = np.nan

        if prev is not None:
            mb = month_num(r["report_date"]) - month_num(prev["report_date"])
            feat["progress_velocity"] = (r["physical_progress"] - prev["physical_progress"]) / mb \
                if mb and pd.notna(r["physical_progress"]) and pd.notna(prev["physical_progress"]) else np.nan
            feat["spend_velocity"] = (r["cumulative_expenditure"] - prev["cumulative_expenditure"]) / mb \
                if mb and pd.notna(r["cumulative_expenditure"]) and pd.notna(prev["cumulative_expenditure"]) else np.nan
            feat["staleness_flag"] = 1 if (r["physical_progress"] == prev["physical_progress"] and
                                            r["cumulative_expenditure"] == prev["cumulative_expenditure"]) else 0
            revised_here = not_equal(r["doc_revised"], prev["doc_revised"]) or not_equal(r["cost_revised"], prev["cost_revised"])
        else:
            feat["progress_velocity"] = np.nan
            feat["spend_velocity"] = np.nan
            feat["staleness_flag"] = 0
            revised_here = False

        feat["n_prior_revisions"] = n_revisions
        feat["months_since_last_revision"] = month_num(r["report_date"]) - month_num(last_revision_date) \
            if last_revision_date is not None else np.nan

        feat["project_id"] = r["project_id"]
        feat["report_date"] = r["report_date"]
        feat["project_name"] = r["project_name"]
        feat["doc_anticipated"] = r["doc_anticipated"]  # row i's own field, kept for earned-schedule baseline only
        out.append(feat)

        if revised_here:
            n_revisions += 1
            last_revision_date = r["report_date"]
        prev = r
    return pd.DataFrame(out)


def add_agency_past_slip_rate(target, labels):
    """expanding, leakage-safe by construction: mean label of the agency's rows with
    report_date strictly < this row's report_date (0.5 default). Built once off ALL known
    labels and merge_asof'd (strict, backward) into panel rows and into latest rows alike --
    same lookup table, same rule, both call sites."""
    target = target.copy()
    target["agency"] = target["agency"].astype(str)
    lv = labels.merge(target[["project_id", "agency"]].drop_duplicates(), on="project_id", how="left")
    dl = (lv.groupby(["agency", "report_date"])["label"].agg(["sum", "count"]).reset_index()
          .sort_values(["agency", "report_date"]))
    dl["cum_sum_before"] = dl.groupby("agency")["sum"].cumsum() - dl["sum"]
    dl["cum_cnt_before"] = dl.groupby("agency")["count"].cumsum() - dl["count"]
    dl["agency_past_slip_rate"] = np.where(dl["cum_cnt_before"] > 0, dl["cum_sum_before"] / dl["cum_cnt_before"], 0.5)
    dl = dl[["agency", "report_date", "agency_past_slip_rate"]].sort_values("report_date")

    target = target.sort_values("report_date")
    merged = pd.merge_asof(target, dl, on="report_date", by="agency", direction="backward", allow_exact_matches=False)
    merged["agency_past_slip_rate"] = merged["agency_past_slip_rate"].fillna(0.5)
    return merged


def assign_size_band(df, edges):
    return pd.cut(df["cost_anticipated"], bins=[-np.inf] + list(edges) + [np.inf],
                  labels=["Q1", "Q2", "Q3", "Q4"])


def choose_split(panel):
    dates = np.sort(panel["report_date"].unique())
    n = len(panel)
    train_end = dates[np.searchsorted(np.cumsum(panel["report_date"].value_counts().sort_index().reindex(dates, fill_value=0)), 0.6 * n)]
    train_end = pd.Timestamp(train_end)
    for buffer_months in range(6, -1, -1):
        test_start = train_end + pd.DateOffset(months=buffer_months + 1)
        test_frac = (panel["report_date"] >= test_start).mean()
        if test_frac >= 0.15 or buffer_months == 0:
            break
    return train_end, test_start, buffer_months


def metrics_for(y_true, y_score, report_dates, next_dates):
    y_true = np.asarray(y_true)
    y_score = np.asarray(y_score, dtype=float)
    pr_auc = float(average_precision_score(y_true, y_score)) if y_true.sum() > 0 else 0.0
    k = min(50, len(y_score))
    top_idx = np.argsort(-y_score, kind="stable")[:k]
    recall_50 = float(y_true[top_idx].sum() / y_true.sum()) if y_true.sum() > 0 else 0.0
    tp_mask = np.zeros(len(y_true), dtype=bool)
    tp_mask[top_idx] = True
    tp_mask &= (y_true == 1)
    if tp_mask.sum() > 0:
        rd, nd = np.asarray(report_dates)[tp_mask], np.asarray(next_dates)[tp_mask]
        lead = [( (pd.Timestamp(b).year * 12 + pd.Timestamp(b).month) - (pd.Timestamp(a).year * 12 + pd.Timestamp(a).month))
                for a, b in zip(rd, nd)]
        lead_time = float(np.mean(lead))
    else:
        lead_time = None
    return {"pr_auc": round(pr_auc, 4), "recall_at_50": round(recall_50, 4),
            "lead_time_months": round(lead_time, 2) if lead_time is not None else None,
            "n_test": int(len(y_true)), "n_positive": int(y_true.sum())}


def main():
    os.makedirs(GOLD, exist_ok=True)
    os.makedirs(MODEL_DIR, exist_ok=True)

    print("loading + labeling...")
    df = load_data()
    label_df, dropped_pairs = build_labels(df)
    print(f"rows={len(df)} unique_projects={df.project_id.nunique()} labeled_pairs={len(label_df)} dropped_pairs={dropped_pairs}")

    print("featurizing (point-in-time, per project)...")
    feat_parts = [featurize_project(g) for _, g in df.groupby("project_id", sort=False)]
    feat_all = pd.concat(feat_parts, ignore_index=True)

    panel = label_df.merge(feat_all, on=["project_id", "report_date"], how="left")
    latest = feat_all.loc[feat_all.groupby("project_id")["report_date"].idxmax()].reset_index(drop=True)

    train_end, test_start, buffer_months = choose_split(panel)
    panel["split"] = np.select(
        [panel["report_date"] <= train_end, panel["report_date"] >= test_start],
        ["train", "test"], default="buffer")
    split_counts = panel["split"].value_counts().to_dict()
    print(f"train_end={train_end.date()} test_start={test_start.date()} buffer_months={buffer_months} split_counts={split_counts}")

    # size_band: quartile edges from TRAIN split's cost_anticipated only, applied to everyone
    edges = panel.loc[panel.split == "train", "cost_anticipated"].quantile([.25, .5, .75]).values
    panel["size_band"] = assign_size_band(panel, edges).astype(str)
    latest["size_band"] = assign_size_band(latest, edges).astype(str)

    panel = add_agency_past_slip_rate(panel, label_df)
    latest = add_agency_past_slip_rate(latest, label_df)

    for c in CAT_FEATURES:
        panel[c] = panel[c].astype("category")
        latest[c] = pd.Categorical(latest[c], categories=panel[c].cat.categories)

    gold_cols = ["project_id", "report_date"] + TIER2_FEATURES + ["label", "split"]
    panel[gold_cols].to_csv(f"{GOLD}/features_2024_25_2025_26.csv", index=False)
    print(f"wrote {GOLD}/features_2024_25_2025_26.csv rows={len(panel)}")

    train, test = panel[panel.split == "train"], panel[panel.split == "test"]

    # ---- baselines ----
    baselines = {}
    baselines["trust_reported_date"] = metrics_for(test.label, np.zeros(len(test)), test.report_date, test.next_report_date)

    # earned-schedule extrapolation
    pv = test["progress_velocity"]
    remaining = 100 - test["physical_progress"]
    months_to_finish = np.where((pv.notna()) & (pv > 0), remaining / pv.replace(0, np.nan), np.nan)
    months_to_finish = np.clip(months_to_finish, 0, 240)  # cap pace projection at 20y, avoids overflow on near-zero velocity
    implied_finish = test["report_date"].values + pd.to_timedelta(np.nan_to_num(months_to_finish, nan=0) * 30.44, unit="D")
    gap_months = np.array([month_num(pd.Timestamp(f)) - month_num(pd.Timestamp(a)) if pd.notna(a) else 6
                            for f, a in zip(implied_finish, test["doc_anticipated"])])
    gap_months = np.where(pd.isna(months_to_finish), 6, gap_months)  # undetermined pace treated as a 6mo gap (stalled = risky), not measured
    es_score = np.clip(gap_months / 12, 0, 1)
    baselines["earned_schedule"] = metrics_for(test.label, es_score, test.report_date, test.next_report_date)

    # reference-class forecasting: (sector, project_type, size_band) slip rate from TRAIN only
    ref = train.groupby(["sector", "project_type", "size_band"], observed=True)["label"].mean()
    base_rate = train["label"].mean()
    ref_key = list(zip(test.sector, test.project_type, test.size_band))
    ref_score = np.array([ref.get(k, base_rate) for k in ref_key])
    baselines["reference_class"] = metrics_for(test.label, ref_score, test.report_date, test.next_report_date)

    # logistic regression on Tier2
    num_cols = [c for c in TIER2_FEATURES if c not in CAT_FEATURES]
    pre = ColumnTransformer([
        ("num", SimpleImputer(strategy="median"), num_cols),
        ("cat", Pipeline([("imp", SimpleImputer(strategy="most_frequent")), ("oh", OneHotEncoder(handle_unknown="ignore"))]), CAT_FEATURES),
    ])
    logit = Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=1000))])
    train_x = train[TIER2_FEATURES].copy()
    for c in CAT_FEATURES:
        train_x[c] = train_x[c].astype(str)
    test_x = test[TIER2_FEATURES].copy()
    for c in CAT_FEATURES:
        test_x[c] = test_x[c].astype(str)
    logit.fit(train_x, train.label)
    logit_score = logit.predict_proba(test_x)[:, 1]
    baselines["logistic_regression_tier2"] = metrics_for(test.label, logit_score, test.report_date, test.next_report_date)

    # ---- LightGBM: Tier1 vs Tier2 ----
    def fit_lgbm(features):
        m = lgb.LGBMClassifier(n_estimators=200, num_leaves=15, min_child_samples=10,
                                random_state=42, verbosity=-1)
        m.fit(train[features], train.label, categorical_feature=[c for c in CAT_FEATURES if c in features])
        return m

    m_tier1 = fit_lgbm(TIER1_FEATURES)
    m_tier2 = fit_lgbm(TIER2_FEATURES)
    tier1_metrics = metrics_for(test.label, m_tier1.predict_proba(test[TIER1_FEATURES])[:, 1], test.report_date, test.next_report_date)
    tier2_metrics = metrics_for(test.label, m_tier2.predict_proba(test[TIER2_FEATURES])[:, 1], test.report_date, test.next_report_date)

    m_tier2.booster_.save_model(f"{MODEL_DIR}/lightgbm_model.txt")
    model_version = f"lgbm-v1-{date.today().isoformat()}"
    with open(f"{MODEL_DIR}/feature_schema.json", "w") as f:
        json.dump({"features": TIER2_FEATURES, "categorical_features": CAT_FEATURES, "model_version": model_version}, f, indent=2)

    all_scores = {**baselines, "lightgbm_tier1": tier1_metrics, "lightgbm_tier2": tier2_metrics}
    findings = []
    for name, m in all_scores.items():
        if name == "lightgbm_tier2":
            continue
        for metric in ("pr_auc", "recall_at_50"):
            if m[metric] is not None and m[metric] >= tier2_metrics[metric]:
                findings.append(f"{name} {metric}={m[metric]} ties/beats lightgbm_tier2 {metric}={tier2_metrics[metric]}")
    if not findings:
        findings.append("LightGBM Tier2 strictly beats every baseline and the Tier1 ablation on pr_auc and recall_at_50.")

    metrics_json = {
        "split": {"train_end": str(train_end.date()), "test_start": str(test_start.date()),
                  "buffer_months_used": buffer_months,
                  "note": "6-month buffer not fully achievable given data thinness" if buffer_months < 6 else "full 6-month buffer used",
                  "counts": {k: int(v) for k, v in split_counts.items()}},
        "dropped_pairs": int(dropped_pairs),
        "baselines": baselines,
        "lightgbm_tier1": tier1_metrics,
        "lightgbm_tier2": tier2_metrics,
        "findings": findings,
        "notes": [
            "Tier 3 (Scout external evidence) isn't built yet, so there are no Scout columns in the feature set.",
            "No separate labeled validation split was built: nothing downstream (baselines, logistic regression, LightGBM) needed one, so the buffer gap doubles as the unused middle slice; add a val slice if hyperparameter tuning/early stopping is introduced later.",
            "lead_time_months is the empirical gap to the next observed report for correctly-flagged true positives (top-50 by score) -- expect 1-3 months given quarterly/flash cadence, not multi-quarter numbers.",
        ],
    }
    with open(f"{MODEL_DIR}/metrics.json", "w") as f:
        json.dump(metrics_json, f, indent=2, default=str)
    print(json.dumps(metrics_json, indent=2, default=str))

    # ---- SHAP + latest scoring table ----
    explainer = shap.TreeExplainer(m_tier2.booster_)
    sv_test = explainer.shap_values(test[TIER2_FEATURES])
    if isinstance(sv_test, list):
        sv_test = sv_test[1]
    mean_abs = pd.Series(np.abs(sv_test).mean(axis=0), index=TIER2_FEATURES).sort_values(ascending=False)
    mean_abs.to_json(f"{MODEL_DIR}/shap_test_sanity.json", indent=2)

    latest_x = latest[TIER2_FEATURES]
    latest["slip_probability"] = m_tier2.predict_proba(latest_x)[:, 1]
    latest["risk_exposure_cr"] = latest["slip_probability"] * (latest["cost_anticipated"] - latest["cumulative_expenditure"]).clip(lower=0)
    latest["model_version"] = model_version

    sv_latest = explainer.shap_values(latest_x)
    if isinstance(sv_latest, list):
        sv_latest = sv_latest[1]

    def top5(row_idx):
        vals = sv_latest[row_idx]
        order = np.argsort(-np.abs(vals))[:5]
        return json.dumps([{"feature": TIER2_FEATURES[i], "contribution": round(float(vals[i]), 5),
                             "direction": "worsening" if vals[i] > 0 else "improving"} for i in order])

    latest["shap_top5_json"] = [top5(i) for i in range(len(latest))]

    out_cols = ["project_id", "project_name", "sector", "state", "agency", "project_type",
                "cost_anticipated", "cumulative_expenditure", "delay_months", "cost_overrun_pct",
                "physical_progress", "slip_probability", "risk_exposure_cr", "model_version", "shap_top5_json"]
    latest[out_cols].to_csv(f"{GOLD}/latest_features.csv", index=False)
    print(f"wrote {GOLD}/latest_features.csv rows={len(latest)}")


if __name__ == "__main__":
    main()
