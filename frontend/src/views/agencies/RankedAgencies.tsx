import { Badge } from '@/components/ui/Badge'
import { COST_TONE, SCHEDULE_ORDER, SCHEDULE_PHRASE, hasWords } from '@/lib/agencyWords'
import { cn, formatINRShort } from '@/lib/formatters'
import type { AgencyPoint, ScheduleWord } from '@/contracts/intel'

const INTRO: Record<ScheduleWord, string> = {
  'usually later': 'Their past projects mostly finished later than first planned.',
  'about on time': 'Their past projects mostly finished close to the first plan.',
  'usually earlier': 'Their past projects mostly finished before the first plan.',
  'too few projects': 'Fewer than five past projects: too few to see a pattern.',
}

/**
 * The agencies grouped by how their past projects usually finished (the backend's words, in its order), each with
 * its ministry and sector, past and open project counts, capital and a cost word. A row picks the agency. Without
 * words (a backend from before the numbers policy) it is one list by past projects.
 */
export function RankedAgencies({ points, selected, onPick }: {
  points: AgencyPoint[]
  selected: string | null
  onPick: (agency: string) => void
}) {
  const words = hasWords(points)
  const groups = words
    ? SCHEDULE_ORDER.map((w) => ({ w, rows: points.filter((a) => a.scheduleWord === w) })).filter((g) => g.rows.length > 0)
    : [{ w: null, rows: [...points].sort((a, b) => b.nProjects - a.nProjects) }]

  return (
    <div className="divide-y divide-border-subtle">
      {!words && (
        <p className="px-5 py-3 text-sm text-fg-muted">
          How each agency&rsquo;s projects usually finish is not available in words yet; the agencies are listed by past projects.
        </p>
      )}
      {groups.map(({ w, rows }) => (
        <section key={w ?? 'all'} aria-labelledby={w ? `ag-${w.replace(/\s/g, '-')}` : undefined}>
          {w && (
            <header className="bg-surface-elevated/70 px-5 py-2">
              <h3 id={`ag-${w.replace(/\s/g, '-')}`} className="text-sm font-semibold text-fg-base">
                {SCHEDULE_PHRASE[w]} <span className="font-normal text-fg-dimmed">· {rows.length}</span>
              </h3>
              <p className="text-xs text-fg-dimmed">{INTRO[w]}</p>
            </header>
          )}
          <ul className="divide-y divide-border-subtle/70">
            {rows.map((a) => (
              <li key={a.agency}>
                <button
                  type="button"
                  onClick={() => onPick(a.agency)}
                  aria-pressed={selected === a.agency}
                  className={cn(
                    'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-2.5 text-left transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent sm:grid-cols-[minmax(0,1fr)_9rem_7rem_auto]',
                    selected === a.agency && 'bg-accent/10 shadow-[inset_3px_0_0_hsl(var(--color-accent))]',
                    a.isSelf && 'font-semibold'
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm text-fg-base" title={a.names ?? undefined}>
                      {a.agency}{a.isSelf && <span className="ml-1.5 text-xs font-medium text-accent">your agency</span>}
                    </span>
                    <span className="block truncate text-xs font-normal text-fg-dimmed">{[a.ministry, a.sector].filter(Boolean).join(' · ') || 'ministry and sector unknown'}</span>
                  </span>
                  <span className="text-xs font-normal tabular-nums text-fg-muted">{a.nProjects} past · {a.nOpen} open</span>
                  <span className="hidden text-right text-xs font-normal tabular-nums text-fg-muted sm:block">{formatINRShort(a.capitalCr)}</span>
                  <span className="hidden justify-self-end sm:block">
                    {a.costWord && a.costWord !== 'too few projects' && (
                      <Badge variant={COST_TONE[a.costWord] === 'critical' ? 'critical' : COST_TONE[a.costWord] === 'stable' ? 'stable' : 'muted'}>
                        {a.costWord}
                      </Badge>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
