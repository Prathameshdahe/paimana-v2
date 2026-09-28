import { Link } from 'react-router-dom'
import { ArrowRight, BrainCircuit, LayoutList, Network, Radar, Trees, type LucideIcon } from 'lucide-react'
import { Page, PageHeader } from '@/components/layout/Page'
import { IconChip } from '@/components/ui/Badge'
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

const QUICK_LINKS: Array<{ to: string; label: string; hint: string; icon: LucideIcon }> = [
  { to: '/command', label: 'Command Center', hint: 'Triage every project', icon: LayoutList },
  { to: '/external', label: 'External factors', hint: 'Land, forest, courts', icon: Trees },
  { to: '/bottlenecks', label: 'Bottlenecks', hint: 'Shared blockers', icon: Network },
  { to: '/radar', label: 'Radar', hint: 'Linked news', icon: Radar },
  // the developer's only (canOpen filters it): model statistics are not for the four roles
  { to: '/models', label: 'Models', hint: 'Accuracy checks', icon: BrainCircuit },
]

/** IPMD: the week over the whole portfolio, the live jobs, quick links to the analysis pages, the map and the alerts. */
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

      <nav className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-label="Analysis pages">
        {QUICK_LINKS.filter((l) => canOpen(role, l.to)).map(({ to, label, hint, icon }) => (
          <Link
            key={to}
            to={to}
            className="group flex items-center gap-3 rounded-xl border border-border-subtle bg-surface-panel px-4 py-3 shadow-card transition-all animate-card-in hover:-translate-y-0.5 hover:border-border-default hover:shadow-pop"
          >
            <IconChip icon={icon} variant="accent" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold text-fg-base">{label}</span>
              <span className="block truncate text-xs text-fg-dimmed">{hint}</span>
            </span>
            <ArrowRight className="size-4 shrink-0 text-fg-dimmed transition-transform group-hover:translate-x-0.5 group-hover:text-fg-base" />
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
