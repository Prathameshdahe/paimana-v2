import { cn, formatPct } from '@/lib/formatters'
import type { CUFFieldAuditRow } from '@/contracts/audit'

interface CUFAuditTableProps {
  rows: CUFFieldAuditRow[]
}

export function CUFAuditTable({ rows }: CUFAuditTableProps) {
  const currentFields = rows.filter((r) => r.currentlyCollected)
  const proposedFields = rows.filter((r) => !r.currentlyCollected)

  return (
    <div className="space-y-4">
      {/* Currently Collected Fields */}
      <div className="border border-border-subtle bg-surface-panel">
        <div className="border-b border-border-subtle px-4 py-3">
          <span className="text-xs font-mono uppercase tracking-widest text-fg-muted font-semibold">
            Clause (c) · Current CUF Field Utility
          </span>
        </div>
        <table className="w-full text-[13px] font-mono border-collapse">
          <thead>
            <tr className="border-b border-border-default text-fg-muted bg-surface-base">
              <th className="py-2 px-3 text-left font-medium w-1/4">Field</th>
              <th className="py-2 px-3 text-left font-medium w-1/3">Utility Rationale</th>
              <th className="py-2 px-3 text-right font-medium">Info Gain</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle/60">
            {currentFields.map((row) => (
              <tr key={row.fieldName} className="hover:bg-surface-elevated/30">
                <td className="py-3 px-4 align-top">
                  <div className="text-fg-base font-medium">{row.fieldName}</div>
                  <div className="text-xs text-fg-muted mt-1.5 line-clamp-2">
                    {row.description}
                  </div>
                </td>
                <td className="py-3 px-4 align-top">
                  <div className="text-fg-base whitespace-pre-wrap leading-relaxed text-xs">
                    {row.rationale}
                  </div>
                </td>
                <td className="py-3 px-4 align-top text-right">
                  <span className="text-stable font-medium">+{formatPct(row.infoGainPct)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Proposed Missing Variables */}
      <div className="border border-border-subtle bg-surface-panel">
        <div className="border-b border-border-subtle px-4 py-3">
          <span className="text-xs font-mono uppercase tracking-widest text-warning font-semibold">
            Clause (c) · Recommended Strategic Additions
          </span>
        </div>
        <table className="w-full text-[13px] font-mono border-collapse">
          <thead>
            <tr className="border-b border-border-default text-fg-muted bg-surface-base">
              <th className="py-3 px-4 text-left font-medium w-1/4">Proposed Field</th>
              <th className="py-3 px-4 text-left font-medium w-1/3">Strategic Rationale</th>
              <th className="py-3 px-4 text-left font-medium">Feasibility</th>
              <th className="py-3 px-4 text-right font-medium">Δ Accuracy</th>
              <th className="py-3 px-4 text-right font-medium">Lead Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle/60">
            {proposedFields.map((row) => (
              <tr key={row.fieldName} className="hover:bg-surface-elevated/30">
                <td className="py-3 px-4 align-top">
                  <div className="text-warning font-medium">{row.fieldName}</div>
                  <div className="text-xs text-fg-muted mt-1.5 line-clamp-2">
                    {row.description}
                  </div>
                </td>
                <td className="py-3 px-4 align-top">
                  <div className="text-fg-base whitespace-pre-wrap leading-relaxed text-xs">
                    {row.rationale}
                  </div>
                </td>
                <td className="py-3 px-4 align-top">
                  <span className={cn(
                    'text-xs uppercase tracking-wider font-semibold',
                    row.acquisitionFeasibility === 'immediate' ? 'text-stable' : 'text-accent'
                  )}>
                    {row.acquisitionFeasibility}
                  </span>
                </td>
                <td className="py-3 px-4 align-top text-right">
                  <span className="text-stable font-medium">+{formatPct(row.projectedAccuracyDeltaPct)}</span>
                </td>
                <td className="py-3 px-4 align-top text-right">
                  <span className="text-stable font-medium">+{row.earlyWarningLeadDays}d</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
