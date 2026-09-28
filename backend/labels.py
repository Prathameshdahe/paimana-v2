"""Plain labels for what the model and the checklist call things: gold feature names (the SHAP drivers), the 13 risk
dimensions of ml/risk_profile.py, the six external factors and the checklist rows' sources, in the words an officer
reads.

FEATURE_LABELS mirrors frontend/src/lib/featureLabels.ts and feature_label() its featureLabel(): the same map and the
same fallback for ext_open_<category> / ext_ever_<category> and for any other name (underscores to spaces, first
letter up). DIMENSION_LABELS and FACTOR_LABELS mirror RISK_DIMENSION and EXTERNAL_FACTORS in
frontend/src/lib/riskPalette.ts; SOURCE_LABELS mirrors SOURCE_LABEL in views/project-studio/RiskChecklist.tsx (every
`source` ml/risk_profile.py writes: the frontend map must hold the same keys and words, so a row never shows its raw
token). The maps are kept by hand on both sides; tests/test_labels.py checks the keys match. The chat (llm/tools.py)
uses them so a driver or a flagged check reads the same in an answer as on the page.
"""
import re

# gold feature name (pipeline/gold.py) -> the label an officer reads
FEATURE_LABELS = {
    "months_to_anticipated_completion": "Months to anticipated completion",
    "months_to_scheduled_completion": "Months to original scheduled completion",
    "months_since_last_obs": "Months since the last report",
    "months_since_last_revision": "Months since the last revision",
    "elapsed_ratio": "Schedule elapsed (share of sanctioned span)",
    "physical_progress_pct": "Physical progress %",
    "expected_progress_scurve": "Expected progress on the sector S-curve",
    "scurve_deviation": "Progress vs sector S-curve (pp)",
    "progress_velocity_2q": "Progress velocity, last 2 quarters",
    "progress_velocity_4q": "Progress velocity, last 4 quarters",
    "velocity_vs_sector_median": "Velocity vs sector median",
    "acceleration": "Progress acceleration",
    "stagnation_quarters": "Quarters without progress",
    "spend_velocity_2q": "Spend velocity, last 2 quarters",
    "expenditure_ratio": "Spent / anticipated cost",
    "burn_gap": "Spend vs build gap (pp)",
    "spi": "Schedule performance index",
    "cost_variation_pct": "Cost variation so far %",
    "slip_to_date_months": "Slip so far (months)",
    "revisions_so_far": "Revisions so far",
    "slipped_last_period": "Slipped in the last report",
    "log_cost": "Project size (log cost)",
    "cost_band": "Cost band",
    "agency": "Implementing agency",
    "agency_n": "Agency portfolio size (projects)",
    "agency_slip_rate": "Agency 2-quarter slip rate",
    "agency_cost_optimism": "Agency cost optimism",
    "agency_slip_4q": "Agency slip rate, last 4 quarters",
    "sector_slip_4q": "Sector slip rate, last 4 quarters",
    "ministry": "Ministry",
    "sector": "Sector",
    "state": "State",
    "sector_actual_target_ratio": "Sector output vs target",
    "sector_yoy_growth": "Sector output growth (year on year)",
    "sector_trend_4q": "Sector output trend, 4 quarters",
    "obs_count_in_quarter": "Reports in the quarter",
    "dq_score": "Data quality score",
    "period_type": "Report type",
    "ext_open_total": "Open issues in report remarks",
    "ext_remark_quarters": "Quarters with free-text remarks",
    "ext_months_since_first_land": "Months since a land issue was first reported",
    "ext_months_since_first_forest_env": "Months since a forest/environment issue was first reported",
    "fc_expected_complexity": "Forest clearance: expected complexity",
    "fc_worst_complexity": "Forest clearance: worst-case complexity",
    "fc_max_authority_level": "Forest clearance: highest approving level",
    "la_linked": "Land records linked",
    "la_complexity_max_by_t": "Land acquisition complexity",
    "la_parcels_by_t": "Land parcels notified",
    "la_notif_span_by_t": "Land notification span (days)",
}
_EXT = re.compile(r"^ext_(open|ever)_(.+)$")

# the 13 risk-profile dimensions (ml/risk_profile.py DIMENSIONS), as the checklist on the project page names them
DIMENSION_LABELS = {
    "schedule_slip": "Schedule slip",
    "cost_escalation": "Cost escalation",
    "execution_stagnation": "Execution stagnation",
    "expenditure_lag": "Expenditure lag",
    "repeated_revisions": "Repeated revisions",
    "sector_headwind": "Sector headwind",
    "agency_optimism": "Agency optimism",
    "land_acquisition": "Land acquisition",
    "forest_clearance": "Environment / forest clearance",
    "litigation": "Litigation",
    "contractor_stress": "Contractor stress",
    "data_staleness": "Data staleness",
    "external_composite": "External factor score",
}

# the six external factors of gold/external_summary.json
FACTOR_LABELS = {
    "land": "Land acquisition",
    "forest_clearance": "Forest clearance",
    "litigation": "Litigation",
    "contractor": "Contractor stress",
    "utility_shifting": "Utility shifting",
    "inter_agency": "Inter-agency",
}

# the `source` of a risk-profile row (ml/risk_profile.py: what flagged or cleared it), as the checklist names it
SOURCE_LABELS = {
    "model": "model",
    "silver": "reports",
    "report": "report remarks",
    "sector_context": "sector output data",
    "agency_stats": "agency history",
    "bhoomi_rashi": "Bhoomi Rashi land records",
    "parivesh_rules": "Parivesh FC rules",
    "parivesh_portal": "PARIVESH portal",
    "external_composite": "land + forest composite",
    "news_research": "web research",
}


def feature_label(feature: str) -> str:
    """The plain label of a gold feature name (featureLabel() in featureLabels.ts)."""
    if feature in FEATURE_LABELS:
        return FEATURE_LABELS[feature]
    m = _EXT.match(feature)
    words = (m[2] if m else feature).replace("_", " ")
    if m:
        return f"Open {words} issue in remarks" if m[1] == "open" else f"{words} issue ever reported"
    return words[:1].upper() + words[1:]


def dimension_label(dimension: str) -> str:
    """The checklist label of a risk dimension; an unknown one in words."""
    return DIMENSION_LABELS.get(dimension) or dimension.replace("_", " ").capitalize()


def source_label(source: str | None) -> str:
    """The checklist's words for a risk-profile row's source; an unknown one in words, None 'source unknown'."""
    if not source:
        return "source unknown"
    return SOURCE_LABELS.get(source) or source.replace("_", " ")


def direction(contribution: float | None) -> str:
    """What a SHAP contribution does to the chance of a slip, in words (the drivers explain p_any_2q in log-odds:
    above 0 pushes it up)."""
    if contribution is None or contribution == 0:
        return "no effect"
    return "raises the risk" if contribution > 0 else "lowers the risk"
