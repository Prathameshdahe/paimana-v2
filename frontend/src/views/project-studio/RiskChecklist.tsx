import { Card } from '@/components/ui/Card'
import { formatDate, cn } from '@/lib/formatters'
import { RISK_DIMENSION, RISK_STATE_CHIP } from '@/lib/riskPalette'
import type { RiskRow, RiskState } from '@/contracts/project'

/** ml/risk_profile.py's source words for a row, as an officer reads them (backend/labels.py keeps the same) */
const SOURCE_LABEL: Record<string, string> = {
  model: 'model',
  silver: 'reports',
  report: 'report remarks',
  sector_context: 'sector output data',
  agency_stats: 'agency history',
  bhoomi_rashi: 'Bhoomi Rashi land records',
  parivesh_rules: 'Parivesh FC rules',
  parivesh_portal: 'PARIVESH portal',
  external_composite: 'land + forest composite',
  news_research: 'web research',
}

const CHIP_TEXT: Record<RiskState, string> = { flagged: 'Flagged', clear: 'Clear', unknown: 'Unknown ?' }

/** Risk profile checklist (guide §5.2): one row per dimension with state, evidence, source and date. */
export function RiskChecklist({ rows }: { rows: RiskRow[] }) {
  const count = (s: RiskState) => rows.filter((r) => r.state === s).length

  return (
    <Card
      title={`Risk profile · ${rows.length} dimensions`}
      info="Unknown means there is no data for that dimension here — it is not the same as clear."
      titleRight={
        <span className="text-xs text-fg-dimmed">
          <span className="text-critical font-semibold">{count('flagged')} flagged</span> ·{' '}
          <span className="text-stable">{count('clear')} clear</span> · {count('unknown')} unknown
        </span>
      }
      className="h-full"
    >
      {rows.length === 0 ? (
        <div className="px-5 py-6 text-center text-xs text-fg-dimmed">
          no risk profile for this project at this asof (not in the current portfolio)
        </div>
      ) : (
        <div className="divide-y divide-border-subtle/60">
          {rows.map((r) => (
            <div key={r.dimension} className="grid grid-cols-[170px_96px_1fr] gap-3 px-4 py-2.5 items-start">
              <span className="text-xs font-medium text-fg-base">{RISK_DIMENSION[r.dimension]?.label ?? r.dimension}</span>
              <span className={cn('justify-self-start rounded-full px-2 py-0.5 text-xs font-medium', RISK_STATE_CHIP[r.state])}>
                {CHIP_TEXT[r.state]}
              </span>
              <div className="min-w-0">
                <div className={cn('text-xs leading-relaxed', r.state === 'unknown' ? 'text-fg-dimmed italic' : 'text-fg-base')}>
                  {r.evidence ?? 'no evidence line'}
                </div>
                <div className="text-xs text-fg-dimmed mt-0.5">
                  {r.source ? (SOURCE_LABEL[r.source] ?? r.source) : 'source unknown'}
                  {r.asOfDate && ` · ${formatDate(r.asOfDate)}`}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
