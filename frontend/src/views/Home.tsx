import { Link } from 'react-router-dom'
import { Page, PageHeader } from '@/components/layout/Page'
import { KPIRibbon } from '@/views/command-center/KPIRibbon'
import { IndiaMap } from '@/views/home/IndiaMap'
import { EarlyWarningInbox } from '@/views/home/EarlyWarningInbox'
import { LiveStatus } from '@/views/home/LiveStatus'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'

/**
 * Landing page. Overview + geography + action inbox — the "what does the
 * portfolio look like right now, and what needs a decision" entry point.
 * Deep triage/sort/filter work lives in Command Center (/command). The public
 * gets the transparency view: KPIs, tier counts and the map, no alert inbox.
 */
export function Home() {
  const { role } = useRole()
  const alerts = can(role, 'canSeeAlerts')
  return (
    <Page>
      <PageHeader
        title="PAIMANA Radar"
        subtitle="Early warning for central-sector infrastructure projects"
        actions={
          <Link to="/command" className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border-default bg-surface-panel px-4 text-sm font-medium text-fg-base shadow-sm transition-colors hover:bg-surface-elevated">
            Open Command Center &rarr;
          </Link>
        }
      />

      <KPIRibbon />
      <LiveStatus />

      {/* without the inbox the map keeps a readable width instead of stretching across the page */}
      <div className={alerts ? 'grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch' : 'mx-auto max-w-[900px]'}>
        <IndiaMap />
        {alerts && <EarlyWarningInbox />}
      </div>
    </Page>
  )
}
