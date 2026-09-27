/** Gold feature names in the words an officer reads (project SHAP drivers, the Models SHAP summary). */

// gold feature name (pipeline/gold.py) -> the label an officer reads
const FEATURE_LABELS: Record<string, string> = {
  months_to_anticipated_completion: 'Months to anticipated completion',
  months_to_scheduled_completion: 'Months to original scheduled completion',
  months_since_last_obs: 'Months since the last report',
  months_since_last_revision: 'Months since the last revision',
  elapsed_ratio: 'Schedule elapsed (share of sanctioned span)',
  physical_progress_pct: 'Physical progress %',
  expected_progress_scurve: 'Expected progress on the sector S-curve',
  scurve_deviation: 'Progress vs sector S-curve (pp)',
  progress_velocity_2q: 'Progress velocity, last 2 quarters',
  progress_velocity_4q: 'Progress velocity, last 4 quarters',
  velocity_vs_sector_median: 'Velocity vs sector median',
  acceleration: 'Progress acceleration',
  stagnation_quarters: 'Quarters without progress',
  spend_velocity_2q: 'Spend velocity, last 2 quarters',
  expenditure_ratio: 'Spent / anticipated cost',
  burn_gap: 'Spend vs build gap (pp)',
  spi: 'Schedule performance index',
  cost_variation_pct: 'Cost variation so far %',
  slip_to_date_months: 'Slip so far (months)',
  revisions_so_far: 'Revisions so far',
  slipped_last_period: 'Slipped in the last report',
  log_cost: 'Project size (log cost)',
  cost_band: 'Cost band',
  agency: 'Implementing agency',
  agency_n: 'Agency portfolio size (projects)',
  agency_slip_rate: 'Agency 2-quarter slip rate',
  agency_cost_optimism: 'Agency cost optimism',
  agency_slip_4q: 'Agency slip rate, last 4 quarters',
  sector_slip_4q: 'Sector slip rate, last 4 quarters',
  ministry: 'Ministry',
  sector: 'Sector',
  state: 'State',
  sector_actual_target_ratio: 'Sector output vs target',
  sector_yoy_growth: 'Sector output growth (year on year)',
  sector_trend_4q: 'Sector output trend, 4 quarters',
  obs_count_in_quarter: 'Reports in the quarter',
  dq_score: 'Data quality score',
  period_type: 'Report type',
  ext_open_total: 'Open issues in report remarks',
  ext_remark_quarters: 'Quarters with free-text remarks',
  ext_months_since_first_land: 'Months since a land issue was first reported',
  ext_months_since_first_forest_env: 'Months since a forest/environment issue was first reported',
  fc_expected_complexity: 'Forest clearance: expected complexity',
  fc_worst_complexity: 'Forest clearance: worst-case complexity',
  fc_max_authority_level: 'Forest clearance: highest approving level',
  la_linked: 'Land records linked',
  la_complexity_max_by_t: 'Land acquisition complexity',
  la_parcels_by_t: 'Land parcels notified',
  la_notif_span_by_t: 'Land notification span (days)',
}

export function featureLabel(feature: string): string {
  const known = FEATURE_LABELS[feature]
  if (known) return known
  const m = feature.match(/^ext_(open|ever)_(.+)$/)
  const words = (m ? m[2] : feature)?.replace(/_/g, ' ') ?? feature
  if (m) return m[1] === 'open' ? `Open ${words} issue in remarks` : `${words} issue ever reported`
  return words.charAt(0).toUpperCase() + words.slice(1)
}
