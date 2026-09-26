"""
Regenerate frontend/src/mocks/real_projects.json from the cleaned Silver
layer (dataset/silver/*_clean.csv). Replaces the old frontend
ingest_dataset.mjs script, which read a DATASET/ panel file that no longer
exists.

Keeps that script's Project contract shape and risk-score formula
(percentile-anchored composite score), but uses the cleaned sector/state
columns instead of the old raw/blank ones.

Note: shapDrivers/delayRemarks here are still heuristic, tied to each
project's own numbers rather than random. The dashboard overlays the real
LightGBM SHAP values from the backend when it is running.
"""
import pandas as pd
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "dataset" / "silver"
OUT = ROOT / "frontend" / "src" / "mocks" / "real_projects.json"

TOP_N = 300

DELAY_DRIVERS = [
    ("Land Acquisition Delay", lambda r: r["delay_months"] > 12),
    ("Forest Clearance Pending", lambda r: r["delay_months"] > 6),
    ("Contractor Cash Flow", lambda r: r["disparity"] > 15),
    ("Design Revision", lambda r: r["cost_overrun_pct"] > 20),
    ("Geological Surprises", lambda r: r["sector"] in ("RAILWAYS", "ROAD TRANSPORT AND HIGHWAYS")),
    ("Equipment Supply Delay", lambda r: r["cost_overrun_pct"] > 0),
]
IMPROVE_DRIVERS = [("Expedited Clearances", -2, 0.6), ("Favorable Weather", -1, 0.4)]


SECTOR_CANON = {
    "POWER": "Power",
    "ROAD TRANSPORT AND HIGHWAYS": "Road Transport and Highways",
    "ROAD TRANSPORT": "Road Transport and Highways",
    "PETROLEUM": "Petroleum",
    "RAILWAYS": "Railways",
    "COAL": "Coal",
    "URBAN DEVELOPMENT": "Urban Development",
    "URBAN DEVELOPME NT": "Urban Development",
    "HEALTH AND FAMILY WELFARE": "Health and Family Welfare",
    "WATER RESOURCES": "Water Resources",
    "CIVIL AVIATION": "Civil Aviation",
    "DEPARTMENT OF HIGHER EDUCATION": "Department of Higher Education",
    "TELECOMMUNICATIONS": "Telecommunications",
    "TELECOMMUNIC ATIONS": "Telecommunications",
    "TELECOMM UNICATIONS": "Telecommunications",
    "DPIIT": "DPIIT",
    "ATOMIC ENERGY": "Atomic Energy",
    "STEEL": "Steel",
    "MINES": "Mines",
    "SHIPPING AND PORTS": "Shipping and Ports",
}


def canon_sector(raw):
    s = re.sub(r"\s+", " ", str(raw).strip().upper())
    s = re.sub(r"^COAL\s+\d.*$", "COAL", s)  # strip stray suffix artifacts e.g. "COAL 1378NLCIL"
    return SECTOR_CANON.get(s, s.title() if s else "Unspecified")


def num(x, default=0.0):
    try:
        v = float(x)
        return v if v == v else default  # NaN check
    except (TypeError, ValueError):
        return default


def shap_for(row):
    """heuristic drivers tied to this project's own numbers — not random,
    still not real SHAP (no trained model yet)."""
    if row["delay_months"] <= 0 and row["cost_overrun_pct"] <= 0:
        return [{"feature": f, "weight": w, "impactMonths": im, "direction": "improving"}
                for f, im, w in IMPROVE_DRIVERS]
    applicable = [name for name, cond in DELAY_DRIVERS if cond(row)][:3] or ["Clearances Pending"]
    n = len(applicable)
    weights = [round(1.0 / n, 3)] * n
    weights[0] += round(1.0 - sum(weights), 3)
    drivers = []
    for name, w in zip(applicable, weights):
        drivers.append({
            "feature": name, "weight": w,
            "impactMonths": round(w * max(row["delay_months"], 1), 1),
            "direction": "worsening",
        })
    return sorted(drivers, key=lambda d: -d["weight"])


def build():
    d = pd.read_csv(SILVER / "project_monitoring_2024-25_clean.csv", dtype=str, keep_default_na=False)
    for c in ["cost_original", "cost_revised", "cost_anticipated", "cost_overrun_pct",
              "delay_months", "physical_progress", "cumulative_expenditure"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.sort_values("report_date")

    # pick top-N projects by latest anticipated cost (bundle size, same as before)
    latest = d.groupby("project_id").tail(1).set_index("project_id")
    top_ids = latest["cost_anticipated"].fillna(latest["cost_original"]).sort_values(ascending=False).head(TOP_N).index

    P95_OVERRUN, P95_DELAY = 81.4, 75.0  # from this dataset's own quantiles, not guessed
    out = []
    for pid in top_ids:
        panel = d[d["project_id"] == pid]
        last = panel.iloc[-1]

        cost_original = num(last["cost_original"])
        cost_anticipated = num(last["cost_anticipated"], cost_original) or cost_original
        cost_revised = num(last["cost_revised"]) or cost_anticipated or cost_original
        expenditure = num(last["cumulative_expenditure"])
        physical = num(last["physical_progress"])
        delay_months = max(0, num(last["delay_months"]))
        overrun_pct = max(0, num(last["cost_overrun_pct"]))
        overrun_cr = max(0, cost_anticipated - cost_revised)

        financial_pct = (expenditure / cost_anticipated * 100) if cost_anticipated > 0 else 0
        disparity = financial_pct - physical

        clamp = lambda v: min(100, max(0, v))
        cost_sub = clamp(overrun_pct / P95_OVERRUN * 100)
        delay_sub = clamp(delay_months / P95_DELAY * 100)
        gap_sub = clamp(100 - physical)
        spend_ratio = expenditure / cost_anticipated if cost_anticipated > 0 else 0
        spend_sub = clamp(spend_ratio / 1.5 * 100)
        risk = round(cost_sub * 0.30 + delay_sub * 0.30 + gap_sub * 0.25 + spend_sub * 0.15)
        tier = "CRITICAL" if risk >= 60 else "WARNING" if risk >= 30 else "NORMAL"
        runway = 0 if physical >= 100 else max(0, int(180 - risk * 2))

        sector_clean = canon_sector(last["sector"])
        row_ctx = {"delay_months": delay_months, "cost_overrun_pct": overrun_pct,
                   "disparity": disparity, "sector": sector_clean.upper()}
        drivers = shap_for(row_ctx)

        def pdate(v, fallback="2025-01-01"):
            v = str(v).strip()
            if not v or v == "nan":
                return fallback
            return f"{v}-01" if len(v) == 7 else v

        scurve = []
        planned_base = 0
        for _, q in panel.iterrows():
            planned_base += 120
            scurve.append({
                "quarter": q["report_date"],
                "plannedSpendCr": round(planned_base, 1),
                "actualSpendCr": round(num(q["cumulative_expenditure"]), 1),
                "physicalProgressPct": round(num(q["physical_progress"]), 1),
                "projectedSpendCr": round(num(q["cumulative_expenditure"]), 1),
            })

        out.append({
            "id": pid, "code": pid, "name": last["project_name"],
            "ministry": "MoSPI", "sector": sector_clean, "agency": last["agency"] or "Unknown",
            "state": (str(last["state"]).strip().title() or "Unspecified") if last["state"] else "Unspecified",
            "originalCostCr": round(cost_original, 2), "revisedCostCr": round(cost_revised, 2),
            "currentExpenditureCr": round(expenditure, 2), "disparityDeltaPct": round(disparity, 2),
            "overrunForecastCr": round(overrun_cr, 2),
            "sanctionedDoc": pdate(last["doc_original"]),
            "revisedDoc": pdate(last["doc_revised"], pdate(last["doc_original"])),
            "predictedDoc": pdate(last["doc_anticipated"], pdate(last["doc_original"])),
            "predictedDelayMonths": round(delay_months, 1),
            "delayCI": {"lowerMonths": round(max(0, delay_months - 2), 1), "upperMonths": round(delay_months + 4, 1)},
            "compositeRiskScore": risk, "actionableRunwayDays": runway,
            "floatDepletionVelocity": round(min(20, max(0.1, delay_months / 12 * 10)), 1),
            "riskTier": tier, "topBottleneck": drivers[0]["feature"], "shapDrivers": drivers,
            "delayRemarks": f"Nodal officer reported issues with {drivers[0]['feature']}. Action pending at {last['state'] or 'state'} level.",
            "sCurve": scurve, "projectType": last["project_type"],
            "dataConfidence": {
                "sectorSource": last["sector_source"],
                "stateSource": last["state_source"],
            },
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {len(out)} projects to {OUT}")
    tiers = pd.Series([p["riskTier"] for p in out]).value_counts().to_dict()
    print("risk tiers:", tiers)
    print("sectors:", pd.Series([p["sector"] for p in out]).value_counts().head(10).to_dict())
    print("states 'Unspecified':", sum(1 for p in out if p["state"] == "Unspecified"))


if __name__ == "__main__":
    build()
