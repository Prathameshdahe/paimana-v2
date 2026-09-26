import { Tooltip } from '@/components/ui/Tooltip'
import type { Project } from '@/contracts/project'

const LABELS: Record<string, string> = {
  pdf_reparse: 'Re-extracted from source PDF (word-position parse)',
  cross_period_vote: 'Inferred from majority value across this project\'s reporting periods',
  name_keyword_rule: 'Inferred from project name keywords',
  original_extraction: 'From original CSV extraction — not independently verified',
}

const DOT: Record<string, string> = {
  pdf_reparse: 'bg-stable',
  cross_period_vote: 'bg-stable',
  name_keyword_rule: 'bg-warning',
  original_extraction: 'bg-fg-dimmed',
}

/** Small provenance indicator for sector/state — honest about data quality. */
export function DataConfidenceBadge({ project }: { project: Project }) {
  const dc = project.dataConfidence
  if (!dc) return null

  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-fg-dimmed">
      <Tooltip content={`Sector: ${LABELS[dc.sectorSource]}`}>
        <span className="inline-flex items-center gap-1 cursor-help">
          <span className={`h-1.5 w-1.5 rounded-full ${DOT[dc.sectorSource]}`} />
          sector
        </span>
      </Tooltip>
      <Tooltip content={`State: ${LABELS[dc.stateSource]}`}>
        <span className="inline-flex items-center gap-1 cursor-help">
          <span className={`h-1.5 w-1.5 rounded-full ${DOT[dc.stateSource]}`} />
          state
        </span>
      </Tooltip>
    </span>
  )
}
