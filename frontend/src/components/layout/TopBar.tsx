import { Link, useNavigate } from 'react-router-dom'
import * as Popover from '@radix-ui/react-popover'
import { ChevronDown, LogOut } from 'lucide-react'
import { NavigationMenuWithActiveItem } from '@/components/ui/navigation-menu-05'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { useMeta, usePortfolio } from '@/lib/queries'
import { API_BASE, START_BACKEND, isOffline } from '@/lib/api'
import { formatDate } from '@/lib/formatters'
import { useAlertStream } from '@/lib/useAlertStream'
import { AlertBell } from './AlertBell'

const ROLE_LABELS: Record<string, string> = {
  ipmd_analyst: 'IPMD Analyst',
  ministry_official: 'Ministry Official',
  agency_official: 'Implementing Agency',
  public: 'Public',
}

/** 'Asha Rao' -> 'AR'; no name: the role's initials */
function initials(name: string, role: string): string {
  const words = (name.trim() || ROLE_LABELS[role] || '?').split(/\s+/)
  return words.slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('')
}

/**
 * Persistent top bar: logo, the pages the role may open, a compact data pill, the scope the
 * pages are cut to, the alert bell and the user menu. Model versions live on Models and the
 * project page's provenance line, not here.
 */
export function TopBar() {
  const meta = useMeta()
  const { data: p } = usePortfolio()
  const m = meta.data
  const { role, displayName, ministry, agency, status, signOut } = useSession()
  const scope = ministry ?? agency
  const navigate = useNavigate()
  const signedIn = !!role
  useAlertStream()

  return (
    <header data-no-print className="sticky top-0 z-40 w-full border-b border-border-subtle bg-surface-base/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4 sm:px-6">
        <Link to="/" className="flex shrink-0 items-baseline gap-1.5">
          <span className="text-base font-extrabold tracking-[0.18em] text-fg-base">PAIMANA</span>
          <span className="text-xs font-semibold tracking-widest text-fg-dimmed">RADAR</span>
        </Link>

        <NavigationMenuWithActiveItem />

        <div className="ml-auto flex min-w-0 items-center gap-2.5">
          {m && (
            // the data version and the viewer's project count (scoped portfolio)
            <span
              className="hidden xl:inline-flex items-center gap-1.5 whitespace-nowrap bg-surface-panel px-3 py-1 text-xs text-fg-muted ring-1 ring-inset ring-border-subtle"
              title={`latest report: ${m.latestReportDoc ?? 'unknown'}`}
            >
              <span className="size-1.5 rounded-full bg-stable" />
              as of {formatDate(m.asof)} · {(p?.kpis.nProjects ?? m.nCurrent).toLocaleString()} projects
            </span>
          )}

          {scope && (
            // the scope every page is cut to (backend/access.py)
            <span
              title={`viewing as ${scope}`}
              className="hidden md:inline-block max-w-[200px] truncate bg-accent/10 px-3 py-1 text-xs font-medium text-fg-base ring-1 ring-inset ring-accent/25"
            >
              {scope}
            </span>
          )}

          {can(role, 'canSeeAlerts') && <AlertBell />}

          {signedIn ? (
            <Popover.Root>
              <Popover.Trigger
                aria-label="account"
                className="flex items-center gap-1 py-0.5 pl-0.5 pr-1.5 text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
              >
                <span className="flex size-8 items-center justify-center rounded-full bg-fg-base text-xs font-semibold text-fg-inverse">
                  {initials(displayName, role)}
                </span>
                <ChevronDown className="size-3.5" />
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  align="end"
                  sideOffset={8}
                  className="z-50 w-64 overflow-hidden rounded-xl border border-border-default bg-surface-panel shadow-pop"
                >
                  <div className="space-y-0.5 px-4 py-3">
                    <div className="truncate text-sm font-semibold text-fg-base">{displayName || ROLE_LABELS[role]}</div>
                    <div className="text-xs text-fg-muted">{ROLE_LABELS[role]}</div>
                    {scope && <div className="text-xs text-fg-dimmed">{scope}</div>}
                  </div>
                  <Popover.Close asChild>
                    <button
                      onClick={async () => {
                        await signOut()
                        navigate('/')
                      }}
                      className="flex w-full items-center gap-2 border-t border-border-subtle px-4 py-2.5 text-left text-sm text-fg-muted hover:bg-surface-elevated hover:text-fg-base"
                    >
                      <LogOut className="size-4" /> Sign out
                    </button>
                  </Popover.Close>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          ) : status === 'loading' ? null : (
            <Link
              to="/login"
              className="inline-flex h-8 items-center rounded-lg bg-fg-base px-3 text-xs font-medium text-fg-inverse shadow-sm hover:bg-fg-base/85"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>

      {isOffline(meta.error) && (
        <div className="border-t border-critical/30 bg-critical/5 px-4 py-1.5 text-center text-xs text-critical">
          backend not reachable at {API_BASE} — start uvicorn: <code className="font-mono">{START_BACKEND}</code>
        </div>
      )}
    </header>
  )
}
