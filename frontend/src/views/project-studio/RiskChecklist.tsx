import { Card } from '@/components/ui/Card'
import { formatDate, cn } from '@/lib/formatters'
import type { RiskRow, RiskState } from '@/contracts/project'

const DIMENSION_LABEL: Record<string, string> = {
  schedule_slip: 'Schedule slip',
  cost_escalation: 'Cost escalation',
  execution_stagnation: 'Execution stagnation',
  expenditure_lag: 'Expenditure lag',
  repeated_revisions: 'Repeated revisions',
  sector_headwind: 'Sector headwind',
  agency_optimism: 'Agency optimism',
  land_acquisition: 'Land acquisition',
  forest_clearance: 'Environment / forest clearance',
  litigation: 'Litigation',
  contractor_stress: 'Contractor stress',
  data_staleness: 'Data staleness',
  external_composite: 'External factor score',
}

const SOURCE_LABEL: Record<string, string> = {
  model: 'model',
  silver: 'reports',
  report: 'report remarks',
  sector_context: 'sector output data',
  agency_stats: 'agency history',
  bhoomi_rashi: 'Bhoomi Rashi land records',
  parivesh_rules: 'Parivesh FC rules',
  external_composite: 'land + forest composite',
}

// unknown gets its own look (dashed, grey, "?") so it never reads as clear
const CHIP: Record<RiskState, string> = {
  flagged: 'bg-critical text-fg-inverse border border-critical',
  clear: 'border border-stable text-stable',
  unknown: 'border border-dashed border-fg-dimmed text-fg-dimmed bg-surface-input',
}
const CHIP_TEXT: Record<RiskState, string> = { flagged: 'FLAGGED', clear: 'CLEAR', unknown: 'UNKNOWN ?' }

/** Risk profile checklist (guide §5.2): one row per dimension with state, evidence, source and date. */
export function RiskChecklist({ rows }: { rows: RiskRow[] }) {
  const count = (s: RiskState) => rows.filter((r) => r.state === s).length

  return (
    <Card
      title={`Risk Profile · ${rows.length} dimensions`}
      titleRight={
        <span className="font-mono text-[11px] text-fg-dimmed">
          <span className="text-critical font-semibold">{count('flagged')} flagged</span> ·{' '}
          <span className="text-stable">{count('clear')} clear</span> · {count('unknown')} unknown
        </span>
      }
      className="h-full"
    >
      {rows.length === 0 ? (
        <div className="px-5 py-6 text-center font-mono text-xs text-fg-dimmed">
          no risk profile for this project at this asof (not in the current portfolio)
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60">
          {rows.map((r) => (
            <div key={r.dimension} className="grid grid-cols-[170px_96px_1fr] gap-3 px-4 py-2.5 items-start">
              <span className="text-xs font-medium text-fg-base">{DIMENSION_LABEL[r.dimension] ?? r.dimension}</span>
              <span className={cn('justify-self-start px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider', CHIP[r.state])}>
                {CHIP_TEXT[r.state]}
              </span>
              <div className="min-w-0">
                <div className={cn('text-xs leading-relaxed', r.state === 'unknown' ? 'text-fg-dimmed italic' : 'text-fg-base')}>
                  {r.evidence ?? 'no evidence line'}
                </div>
                <div className="font-mono text-[10px] text-fg-dimmed mt-0.5">
                  {r.source ? (SOURCE_LABEL[r.source] ?? r.source) : 'source unknown'}
                  {r.asOfDate && ` · ${formatDate(r.asOfDate)}`}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="border-t border-border-subtle px-4 py-2 font-mono text-[10px] text-fg-dimmed">
        Unknown means there is no data for that dimension here — it is not the same as clear.
      </div>
    </Card>
  )
}
