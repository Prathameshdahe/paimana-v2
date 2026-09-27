import { Link } from 'react-router-dom'
import { KPIRibbon } from '@/views/command-center/KPIRibbon'
import { IndiaMap } from '@/views/home/IndiaMap'
import { EarlyWarningInbox } from '@/views/home/EarlyWarningInbox'
import { useRole } from '@/lib/auth/RoleContext'

/**
 * Landing page. Overview + geography + action inbox — the "what does the
 * portfolio look like right now, and what needs a decision" entry point.
 * Deep triage/sort/filter work lives in Command Center (/command).
 */
export function Home() {
  const { role } = useRole()
  const isInternal = !!role && role !== 'public'

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-fg-base">PAIMANA Radar</h1>
          <p className="text-xs font-mono text-fg-dimmed mt-1">
            National infrastructure project monitoring — early warning & predictive decision support
          </p>
        </div>
        <Link
          to="/command"
          className="border border-border-default px-3 py-1.5 text-xs font-mono text-fg-muted hover:text-fg-base hover:border-border-strong transition-colors"
        >
          Full Command Center &rarr;
        </Link>
      </div>

      <KPIRibbon />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
        <IndiaMap />
        <EarlyWarningInbox />
      </div>
    </div>
  )
}
