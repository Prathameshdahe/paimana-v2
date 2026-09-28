import { ArrowDown, ArrowUp, ChevronDown } from 'lucide-react'
import { RISK_DIMENSION, SOURCE_LABEL } from '@/lib/riskPalette'
import { plainText, strengthDots } from '@/lib/outlook'
import { cn, formatDate } from '@/lib/formatters'
import type { PlainDriver, RiskRow } from '@/contracts/project'

/** three dots, `filled` of them dark: strong 3, moderate 2, slight 1 */
function Dots({ filled, label }: { filled: number; label: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-0.5" role="img" aria-label={label}>
      {[0, 1, 2].map((i) => (
        <span key={i} className={cn('size-1.5 rounded-full', i < filled ? 'bg-fg-base' : 'bg-fg-dimmed/30')} />
      ))}
    </span>
  )
}

const label = (dim: string) => RISK_DIMENSION[dim]?.label ?? dim.replace(/_/g, ' ')

/**
 * Why it is happening: up to five model drivers in words, ranked, each with the way it pushes (an arrow) and how hard
 * (dots, no bar lengths); then what the checks found — each flagged check as a sentence with its evidence, source and
 * date, the clear ones folded, and the ones without data named as such (not the same as clear). compact: the side
 * panel's tighter spacing. numbers: the developer reads the evidence as stored; the four roles read it without the
 * model's numbers an older backend writes into it (lib/outlook plainText).
 */
export function WhyBlock({ drivers, checks, numbers, compact, className }: {
  drivers: PlainDriver[]
  checks: RiskRow[]
  numbers: boolean
  compact?: boolean
  className?: string
}) {
  const flagged = checks.filter((r) => r.state === 'flagged')
  const clear = checks.filter((r) => r.state === 'clear')
  const unknown = checks.filter((r) => r.state === 'unknown')
  const top = drivers.slice(0, 5)
  // the page's second level under its h1; one level lower inside the side panel, whose title is the h2
  const H = compact ? 'h3' : 'h2'
  const Sub = compact ? 'h4' : 'h3'

  return (
    <section className={cn('rounded-xl border border-border-subtle bg-surface-panel shadow-card', compact ? 'p-4' : 'p-5', className)}>
      <H className="text-base font-semibold text-fg-base">Why it is happening</H>
      {top.length > 0 ? (
        <ol className={cn('mt-3 space-y-2', compact && 'mt-2')}>
          {top.map((d, i) => {
            const up = d.direction === 'raises'
            const Arrow = up ? ArrowUp : ArrowDown
            return (
              <li key={`${d.label}-${i}`} className="flex items-center gap-3 text-sm">
                <span className="w-4 shrink-0 text-right text-xs tabular-nums text-fg-dimmed">{i + 1}</span>
                <span className="min-w-0 flex-1 text-fg-base">{d.label}</span>
                <Arrow className={cn('size-4 shrink-0', up ? 'text-critical' : 'text-stable')} strokeWidth={2}
                  aria-label={up ? 'raises the risk' : 'lowers the risk'} role="img" />
                <Dots filled={strengthDots(d.strength)} label={`${d.strength} effect`} />
              </li>
            )
          })}
        </ol>
      ) : (
        <p className="mt-2 text-sm text-fg-muted">
          The model&rsquo;s reasons in words are not available for this project; the checks below still say what the reports show.
        </p>
      )}

      <div className={cn('border-t border-border-subtle', compact ? 'mt-3 pt-3' : 'mt-4 pt-4')}>
        <Sub className="text-sm font-semibold text-fg-base">What the checks found</Sub>
        {checks.length === 0 ? (
          <p className="mt-2 text-sm text-fg-muted">No checks: the project is not in the current portfolio.</p>
        ) : (
          <>
            {flagged.length === 0 ? (
              <p className="mt-2 text-sm text-fg-muted">No check is flagged on the latest reports.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {flagged.map((r) => {
                  const Icon = RISK_DIMENSION[r.dimension]?.icon
                  const evidence = plainText(r.evidence, numbers)
                  const meta = [r.source ? (SOURCE_LABEL[r.source] ?? r.source) : null, r.asOfDate ? formatDate(r.asOfDate) : null]
                    .filter(Boolean).join(', ')
                  return (
                    <li key={r.dimension} className="flex items-start gap-2.5 text-sm leading-snug">
                      {Icon && <Icon className="mt-0.5 size-4 shrink-0 text-critical" strokeWidth={2} aria-hidden="true" />}
                      <span className="text-fg-base">
                        <span className="font-medium">{label(r.dimension)}</span>: flagged
                        {evidence && <> — {evidence}</>}
                        {meta && <span className="text-fg-dimmed"> ({meta})</span>}
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
            {clear.length > 0 && (
              <details className="group mt-2 text-sm">
                <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-fg-muted hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
                  {clear.length} check{clear.length === 1 ? '' : 's'} clear
                  <ChevronDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
                </summary>
                <p className="mt-1 text-fg-muted">{clear.map((r) => label(r.dimension)).join(', ')}.</p>
              </details>
            )}
            {unknown.length > 0 && (
              <p className="mt-2 text-sm text-fg-muted">
                No data for: {unknown.map((r) => label(r.dimension)).join(', ')} — not the same as clear.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  )
}
