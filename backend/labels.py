"""Plain labels for what the model and the checklist call things: gold feature names (the SHAP drivers), the 13 risk
dimensions of ml/risk_profile.py, the six external factors and the checklist rows' sources, in the words an officer
reads.

FEATURE_LABELS mirrors frontend/src/lib/featureLabels.ts and feature_label() its featureLabel(): the same map and the
same fallback for ext_open_<category> / ext_ever_<category> and for any other name (underscores to spaces, first
letter up). DIMENSION_LABELS, FACTOR_LABELS and SOURCE_LABELS mirror RISK_DIMENSION, EXTERNAL_FACTORS
and SOURCE_LABEL in frontend/src/lib/riskPalette.ts (SOURCE_LABELS: every
`source` ml/risk_profile.py writes: the frontend map must hold the same keys and words, so a row never shows its raw
token). The maps are kept by hand on both sides; tests/test_labels.py checks the keys match. The chat (llm/tools.py)
uses them so a driver or a flagged check reads the same in an answer as on the page.

DRIVER_LABELS are the plainer words of the numbers policy (docs/ACCESS_CONTROL.md, the `numbers` feature): what
serving.drivers_plain() calls each driver for a viewer who reads words, not model numbers. They hold no digit, unit
or statistic (no '%', 'pp', 'log', '2-quarter'), so a brief or a chat answer built from them cannot carry a number
from a label; the backend sends them, so the frontend keeps no copy. They cover every gold feature (pipeline/gold.py
FEATURES, the ext_open_* / ext_ever_* ones from EXT_ISSUES); driver_label() falls back to feature_label() with the
units and digits taken out for any other name.
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

# gold feature name -> the words of drivers_plain (module docstring): no digits, units or statistics
DRIVER_LABELS = {
    "months_to_anticipated_completion": "Time left to the expected completion",
    "months_to_scheduled_completion": "Time left to the original deadline",
    "months_since_last_obs": "Time since the last progress report",
    "months_since_last_revision": "Time since the last revision",
    "elapsed_ratio": "Share of the planned time used up",
    "physical_progress_pct": "Work done so far",
    "expected_progress_scurve": "Where similar projects usually are at this stage",
    "scurve_deviation": "Progress compared with similar projects",
    "progress_velocity_2q": "Pace of work in the last half year",
    "progress_velocity_4q": "Pace of work in the last year",
    "velocity_vs_sector_median": "Pace of work compared with the sector",
    "acceleration": "Work speeding up or slowing down",
    "stagnation_quarters": "Quarters with no progress",
    "spend_velocity_2q": "Pace of spending in the last half year",
    "expenditure_ratio": "Share of the cost already spent",
    "burn_gap": "Spending compared with work done",
    "spi": "Work done against the schedule",
    "cost_variation_pct": "Cost change so far",
    "slip_to_date_months": "Delay so far",
    "revisions_so_far": "Earlier revisions of cost or date",
    "slipped_last_period": "A slip in the last report",
    "log_cost": "Project size",
    "cost_band": "Project size",
    "agency": "Implementing agency",
    "agency_n": "Size of the agency's portfolio",
    "agency_slip_rate": "The agency's record of delays",
    "agency_cost_optimism": "The agency's record on cost",
    "agency_slip_4q": "The agency's recent delays",
    "sector_slip_4q": "Recent delays in the sector",
    "ministry": "Ministry",
    "sector": "Sector",
    "state": "State",
    "sector_actual_target_ratio": "Sector output against its target",
    "sector_yoy_growth": "Sector output growth",
    "sector_trend_4q": "Sector output trend",
    "obs_count_in_quarter": "Reports in the quarter",
    "dq_score": "Quality of the reported figures",
    "period_type": "Report type",
    "ext_open_total": "Open issues in the report remarks",
    "ext_remark_quarters": "Quarters with written remarks",
    "ext_months_since_first_land": "Time since a land issue was first reported",
    "ext_months_since_first_forest_env": "Time since a forest issue was first reported",
    "fc_expected_complexity": "Expected difficulty of the forest clearance",
    "fc_worst_complexity": "Worst-case difficulty of the forest clearance",
    "fc_max_authority_level": "Level that must approve the forest clearance",
    "la_linked": "Land records linked",
    "la_complexity_max_by_t": "Difficulty of the land acquisition",
    "la_parcels_by_t": "Land parcels notified",
    "la_notif_span_by_t": "Time over which land was notified",
}
# the remark categories of the ext_open_<category> / ext_ever_<category> features (pipeline/external.py TAXONOMY,
# every one of them a feature of the served champions), as the issue an officer reads
EXT_ISSUES = {
    "land": "land issue",
    "forest_env": "forest or environment issue",
    "litigation": "court case",
    "contractor": "contractor problem",
    "funding": "funding problem",
    "utility_shifting": "utility shifting issue",
    "inter_agency": "wait for another agency's approval",
    "law_order": "law and order problem",
    "weather": "weather problem",
}
DRIVER_LABELS |= {f"ext_open_{c}": f"Open {w} in the report remarks" for c, w in EXT_ISSUES.items()}
DRIVER_LABELS |= {f"ext_ever_{c}": f"A {w} reported before" for c, w in EXT_ISSUES.items()}
_UNITS =re.compile(r"\([^)]*\)|%|\S*\d\S*")   # a unit in brackets, a percent sign, a token with a digit

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


def driver_label(feature: str) -> str:
    """The drivers_plain words of a gold feature name (DRIVER_LABELS; module docstring): never a digit or a unit."""
    if feature in DRIVER_LABELS:
        return DRIVER_LABELS[feature]
    m = _EXT.match(feature)
    if m:
        words = _UNITS.sub(" ", m[2].replace("_", " "))
        words = " ".join(words.split()) or "an"
        return (f"Open {words} issue in the report remarks" if m[1] == "open"
                else f"A {words} issue reported before")
    return " ".join(_UNITS.sub(" ", feature_label(feature)).split()).rstrip(",;:") or "Another input"


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
