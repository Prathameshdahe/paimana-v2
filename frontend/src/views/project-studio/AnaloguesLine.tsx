import { Link } from 'react-router-dom'
import { analogueChips, analogueSentence, OUTCOME_TONE } from '@/lib/forecast'
import { cn } from '@/lib/formatters'
import type { Forecast } from '@/contracts/project'

const OUTCOME_WORD = { slipped: 'slipped', held: 'held', unknown: 'not known' } as const

/**
 * Similar past projects in one sentence — "Of 10 similar past projects at this stage, 7 slipped within a year and 3
 * held" — and a chip per project (name, sector, how long ago, what happened). Counts of what happened, no distance,
 * slip or rate; the developer's Model detail keeps the table.
 */
export function AnaloguesLine({ forecast, error, className }: { forecast: Forecast | undefined; error?: unknown; className?: string }) {
  const sentence = analogueSentence(forecast)
  const chips = analogueChips(forecast)
  return (
    <section className={cn('rounded-xl border border-border-subtle bg-surface-panel p-5 shadow-card', className)}>
      <h3 className="text-base font-semibold text-fg-base">What happened to projects like it</h3>
      {!forecast ? (
        error ? (
          <p className="mt-2 text-sm text-fg-muted">No comparison: the project is not in the current scored portfolio.</p>
        ) : (
          <div className="mt-3 space-y-2" aria-busy="true">
            <div className="h-5 w-5/6 animate-pulse rounded bg-surface-input/70" />
            <div className="h-5 w-2/3 animate-pulse rounded bg-surface-input/70" />
          </div>
        )
      ) : !sentence ? (
        <p className="mt-2 text-sm text-fg-muted">No similar past project at this stage to compare with.</p>
      ) : (
        <>
          <p className="mt-2 text-base leading-relaxed text-fg-base">{sentence}</p>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {chips.map((c, i) => {
              const body = (
                <>
                  <span className="max-w-[220px] truncate text-fg-base">{c.name}</span>
                  <span className="text-fg-dimmed">
                    {[c.sector, c.yearsAgo !== null ? (c.yearsAgo === 0 ? 'this year' : `${c.yearsAgo} year${c.yearsAgo === 1 ? '' : 's'} ago`) : null].filter(Boolean).join(' · ')}
                  </span>
                  <span className={cn('font-medium', OUTCOME_TONE[c.outcome])}>{OUTCOME_WORD[c.outcome]}</span>
                </>
              )
              const cls = 'inline-flex items-center gap-1.5 rounded-full bg-surface-elevated px-2.5 py-1 text-xs ring-1 ring-inset ring-border-subtle'
              return (
                <li key={`${c.key ?? c.name}-${i}`}>
                  {c.key ? (
                    <Link to={`/projects/${c.key}`} className={cn(cls, 'hover:ring-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent')}>{body}</Link>
                  ) : (
                    <span className={cls}>{body}</span>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </section>
  )
}
