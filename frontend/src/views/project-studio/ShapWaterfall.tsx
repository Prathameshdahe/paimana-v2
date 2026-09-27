import { MonoFigure } from '@/components/ui/MonoFigure'
import { cn } from '@/lib/formatters'
import type { ShapValue } from '@/contracts/project'

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

function featureLabel(feature: string): string {
  const known = FEATURE_LABELS[feature]
  if (known) return known
  const m = feature.match(/^ext_(open|ever)_(.+)$/)
  const words = (m ? m[2] : feature)?.replace(/_/g, ' ') ?? feature
  if (m) return m[1] === 'open' ? `Open ${words} issue in remarks` : `${words} issue ever reported`
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return 'missing'
  if (typeof v === 'number') return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)
  return String(v)
}

/**
 * Top-5 TreeSHAP drivers of P(date push or cost revision, 2q) for one project,
 * as scored by the LightGBM champion. Contributions are in log-odds: red
 * pushes the probability up, green pulls it down.
 */
export function ShapWaterfall({ drivers }: { drivers: ShapValue[] }) {
  const sorted = [...drivers].sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
  const maxAbs = Math.max(...drivers.map((d) => Math.abs(d.contribution)), 0.0001)

  return (
    <div className="bg-surface-panel flex flex-col border border-border-subtle rounded-sm overflow-hidden h-full">
      <div className="border-b border-border-subtle px-4 py-3 flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-widest text-fg-muted">
          Why this score · top 5 drivers
        </span>
        {sorted[0] && (
          <span className="font-mono text-xs text-critical font-medium truncate ml-3">
            primary: {featureLabel(sorted[0].feature)}
          </span>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="px-4 py-6 text-center font-mono text-xs text-fg-dimmed">
          no drivers — they explain P(slip, 2q), which is not scored for this project
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60 flex-1">
          {sorted.map((d, i) => {
            const up = d.contribution > 0
            return (
              <div key={d.feature} className="flex items-center px-4 py-3 gap-4 hover:bg-surface-elevated/40 transition-colors">
                <span className="font-mono text-[11px] text-fg-muted w-5 shrink-0">{i + 1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-fg-base font-medium truncate mb-1" title={d.feature}>
                    {featureLabel(d.feature)}
                    <span className="font-mono text-fg-dimmed"> = {formatValue(d.value)}</span>
                  </div>
                  <div className="h-1.5 w-full bg-surface-input">
                    <div
                      className={cn('h-full', up ? 'bg-critical' : 'bg-stable')}
                      style={{ width: `${(Math.abs(d.contribution) / maxAbs) * 100}%` }}
                    />
                  </div>
                </div>
                <MonoFigure size="sm" sentiment={up ? 'critical' : 'stable'} className="shrink-0 w-16 text-right">
                  {up ? '+' : ''}
                  {d.contribution.toFixed(2)}
                </MonoFigure>
              </div>
            )
          })}
        </div>
      )}

      <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-fg-muted">
        TreeSHAP on the LightGBM P(slip, 2q) model, log-odds. Red raises the probability, green lowers it.
      </div>
    </div>
  )
}
