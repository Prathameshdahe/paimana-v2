import { useMemo } from 'react'
import { useAlerts, useMeta, usePortfolio, useProjectMap } from '@/lib/queries'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { lastMonday, weekBrief } from '@/lib/headline'
import { outlookOf } from '@/lib/outlook'
import { cn } from '@/lib/formatters'
import { PortfolioLine } from './KPIRibbon'
import type { AlertKind } from '@/contracts/portfolio'

const COUNTED: AlertKind[] = ['tier_up', 'slip_realised', 'early_notice', 'signal']

/** alert counts since last Monday per kind (four one-row pages: the totals, not a sample) */
function useWeekAlerts(enabled: boolean): Partial<Record<AlertKind, number>> | null {
  const since = useMemo(() => lastMonday(), [])
  const tierUp = useAlerts({ since, kind: 'tier_up', size: 1 }, enabled)
  const slip = useAlerts({ since, kind: 'slip_realised', size: 1 }, enabled)
  const notice = useAlerts({ since, kind: 'early_notice', size: 1 }, enabled)
  const signal = useAlerts({ since, kind: 'signal', size: 1 }, enabled)
  const all = [tierUp, slip, notice, signal]
  if (!enabled || all.some((q) => !q.data)) return null
  return Object.fromEntries(COUNTED.map((k, i) => [k, all[i]?.data?.total ?? 0]))
}

/**
 * The page's opening: what needs attention this week in at most three sentences (lib/headline weekBrief, no LLM),
 * then the portfolio line. Officials read what is due soon and likely to slip, early notices among them and the
 * week's changes; the public reads where the Critical and High projects are, under its own title. Everything is
 * already cut to the viewer's scope.
 */
export function WeekBrief({ title, className }: { title?: string; className?: string }) {
  const { role } = useSession()
  const official = can(role, 'canSeeAlerts')
  const numbers = can(role, 'canSeeNumbers')
  const meta = useMeta()
  const portfolio = usePortfolio()
  const map = useProjectMap({}, official)
  const alerts = useWeekAlerts(official)
  const asof = portfolio.data?.asof ?? meta.data?.asof ?? null

  const sentences = official
    ? map.rows && asof
      ? weekBrief({ asof, rows: map.rows, outlookOf: (r) => outlookOf(r, numbers), partial: map.partial, alerts })
      : null
    : portfolio.data
      ? weekBrief({
          asof, rows: null, outlookOf: () => null, kpis: portfolio.data.kpis,
          bySector: portfolio.data.bySector, byState: portfolio.data.byState,
        })
      : null
  const heading = title ?? (official ? 'What needs attention this week' : 'Where the projects stand')

  return (
    <section className={cn('space-y-4 rounded-xl border border-border-subtle bg-surface-panel p-6 shadow-card animate-card-in', className)}>
      <div className="space-y-2">
        <h2 className="text-sm font-medium text-fg-muted">{heading}</h2>
        {sentences ? (
          <p className="max-w-4xl text-lg leading-relaxed text-fg-base">{sentences.join(' ')}</p>
        ) : map.error && official ? (
          <p className="text-sm text-fg-muted">The week&rsquo;s summary is not available right now; the figures below still are.</p>
        ) : (
          <div className="space-y-2" aria-busy="true" aria-label="Loading the summary">
            <div className="h-5 w-11/12 animate-pulse rounded bg-surface-input/80" />
            <div className="h-5 w-3/4 animate-pulse rounded bg-surface-input/80" />
          </div>
        )}
      </div>
      <PortfolioLine />
    </section>
  )
}
