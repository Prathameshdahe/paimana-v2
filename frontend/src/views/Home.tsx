import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { Page, PageHeader } from '@/components/layout/Page'
import { WeekBrief } from '@/views/command-center/WeekBrief'
import { IndiaMap } from '@/views/home/IndiaMap'
import { EarlyWarningInbox } from '@/views/home/EarlyWarningInbox'
import { LiveStatus } from '@/views/home/LiveStatus'
import { AgencyHome, LinkButton, MinistryHome, PublicHome } from '@/views/home/RoleHomes'
import { useSession } from '@/lib/auth/SessionContext'
import { canOpen } from '@/lib/auth/access'

/**
 * Landing page, one per role on the same route: the public's transparency view, a ministry's dashboard, an
 * agency's scorecard (views/home/RoleHomes), and the IPMD (and developer) portfolio overview below. Deep triage
 * lives in Command Center (/command).
 */
export function Home() {
  const { role, ministry, agency } = useSession()
  if (role === 'ministry_official' && ministry) return <MinistryHome ministry={ministry} />
  if (role === 'agency_official' && agency) return <AgencyHome agency={agency} />
  if (role === 'ipmd_analyst' || role === 'developer') return <AnalystHome />
  return <PublicHome />
}

const QUICK_LINKS: Array<{ to: string; label: string; hint: string }> = [
  { to: '/external', label: 'External factors', hint: 'land, forest, courts' },
  { to: '/bottlenecks', label: 'Bottlenecks', hint: 'shared blockers' },
  { to: '/radar', label: 'Radar', hint: 'linked news' },
  // the developer's only (canOpen filters it): model statistics are not for the four roles
  { to: '/models', label: 'Models', hint: 'accuracy checks' },
]

/**
 * IPMD: the week over the whole portfolio, the live jobs, one line of links to the analysis pages (the Command Center
 * is the header's button), the map and the alerts.
 */
function AnalystHome() {
  const { role } = useSession()
  return (
    <Page>
      <PageHeader
        title="Portfolio overview"
        actions={<LinkButton to="/command">Open Command Center <ArrowRight className="size-4" aria-hidden="true" /></LinkButton>}
      />

      <WeekBrief />
      <LiveStatus />

      <nav className="flex flex-wrap items-baseline gap-x-6 gap-y-2 text-sm" aria-label="Analysis pages">
        <span className="text-fg-muted">Look closer:</span>
        {QUICK_LINKS.filter((l) => canOpen(role, l.to)).map(({ to, label, hint }) => (
          <Link key={to} to={to}
            className="rounded font-medium text-fg-base underline decoration-border-strong underline-offset-4 hover:decoration-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
            {label}<span className="font-normal text-fg-dimmed"> · {hint}</span>
          </Link>
        ))}
      </nav>

      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
        <IndiaMap />
        <EarlyWarningInbox />
      </div>
    </Page>
  )
}
