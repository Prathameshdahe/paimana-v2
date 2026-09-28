import type { ReactNode } from 'react'
import { cn } from '@/lib/formatters'

const BULLETS = [
  'Ranks every central sector project by its risk of a delay or a cost revision in the next two quarters',
  'Explains each ranking with the evidence behind it: the model’s drivers, report remarks, clearances and land',
  'Alerts the responsible officials when a project’s outlook changes',
]

/**
 * The account pages' frame (sign in, request access, reset): the product and the ministry on a dark left panel,
 * the form card on the right; stacked on a narrow screen. Formal and still: no animation, no gradient, nothing
 * behind the card.
 */
export function AccountLayout({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      <aside className="flex flex-col justify-between bg-fg-base px-6 py-10 text-fg-inverse sm:px-10 lg:w-[40%] lg:px-14 lg:py-14">
        <div>
          <p className="text-xl font-semibold tracking-[0.18em]">
            PAIMANA <span className="text-base font-normal tracking-widest text-fg-inverse/70">RADAR</span>
          </p>
          <h1 className="mt-8 max-w-md text-2xl font-semibold leading-snug lg:text-3xl">
            Early Warning Radar for Central Sector Projects
          </h1>
          <p className="mt-3 text-sm text-fg-inverse/80">Ministry of Statistics and Programme Implementation · IPMD</p>
          <ul className="mt-8 max-w-md space-y-3 text-sm leading-relaxed text-fg-inverse/90">
            {BULLETS.map((b) => (
              <li key={b} className="flex gap-3">
                <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-fg-inverse/60" aria-hidden="true" />
                {b}
              </li>
            ))}
          </ul>
        </div>
        <p className="mt-12 text-xs text-fg-inverse/70">Authorised use only. Activity is logged.</p>
      </aside>

      <main className="flex flex-1 items-start justify-center px-4 py-10 sm:px-6 lg:items-center">
        <div className={cn('w-full rounded-xl border border-border-default bg-surface-panel p-6 shadow-card sm:p-8', wide ? 'max-w-lg' : 'max-w-sm')}>
          {children}
        </div>
      </main>
    </div>
  )
}
