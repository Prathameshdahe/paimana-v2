import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import * as Popover from '@radix-ui/react-popover'
import { ChevronDown, KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { NavigationMenuWithActiveItem } from '@/components/ui/navigation-menu-05'
import { useSession } from '@/lib/auth/SessionContext'
import { can, canAdmin } from '@/lib/auth/access'
import { useDemo } from '@/lib/auth/demo'
import { DemoRoleList } from '@/components/common/DemoRoleList'
import { useMeta, usePortfolio } from '@/lib/queries'
import { API_BASE, START_BACKEND, isOffline } from '@/lib/api'
import { formatDate } from '@/lib/formatters'
import { useAlertStream } from '@/lib/useAlertStream'
import { useBeaconStatus } from '@/lib/useBeaconStatus'
import { ParakhMark } from '@/components/brand/ParakhMark'
import { AlertBell } from './AlertBell'
import { ChangePasswordDialog } from './ChangePasswordDialog'

/** the officials' roles in words; the developer has none (hidden: only a small tag inside the account menu) */
const ROLE_LABELS: Record<string, string> = {
  ipmd_analyst: 'IPMD Analyst',
  ministry_official: 'Ministry Official',
  agency_official: 'Implementing Agency',
}

/** 'Asha Rao' -> 'AR'; no name: the role's initials */
function initials(name: string, role: string): string {
  const words = (name.trim() || ROLE_LABELS[role] || '?').split(/\s+/)
  return words.slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('')
}

const ITEM = 'flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-fg-muted hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:bg-surface-elevated focus-visible:text-fg-base'

/**
 * Persistent top bar: the PARAKH mark (its beacon follows the alert bell: lib/useBeaconStatus.ts), the pages the role may open, a compact data pill, the scope the pages are cut to, the
 * alert bell and the account menu (name, email, role and scope; change password, administration for admins, sign
 * out). The public gets a Sign in link; nothing shows in that slot until the session is known. A session that
 * expired mid-way says so under the bar. Model versions live on Models and the project page's provenance line.
 */
export function TopBar() {
  const meta = useMeta()
  const { data: p } = usePortfolio()
  const m = meta.data
  const session = useSession()
  const { role, displayName, email, ministry, agency, isAdmin, status, expired, signOut } = session
  const scope = ministry ?? agency
  const navigate = useNavigate()
  const [changing, setChanging] = useState(false)
  const demo = useDemo()
  const [menuOpen, setMenuOpen] = useState(false)
  useAlertStream()
  const beacon = useBeaconStatus()

  return (
    <header data-no-print className="sticky top-0 z-40 w-full border-b border-border-subtle bg-surface-base/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-[1440px] items-center gap-4 px-4 sm:px-6">
        <Link
          to="/"
          title={beacon.label ? `PARAKH · ${beacon.label}` : 'PARAKH'}
          className="flex shrink-0 items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          <ParakhMark size={30} status={beacon.status} />
          <span className="text-base font-extrabold tracking-[0.18em] text-fg-base">PARAKH</span>
        </Link>

        <NavigationMenuWithActiveItem />

        <div className="ml-auto flex min-w-0 items-center gap-2.5">
          {m && (
            // the data version and the viewer's project count (scoped portfolio)
            <span
              className="hidden xl:inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-panel px-3 py-1 text-xs text-fg-muted ring-1 ring-inset ring-border-subtle"
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
              className="hidden md:inline-block max-w-[200px] truncate rounded-full bg-accent/10 px-3 py-1 text-xs font-medium text-fg-base ring-1 ring-inset ring-accent/25"
            >
              {scope}
            </span>
          )}

          {can(role, 'canSeeAlerts') && <AlertBell />}

          {role ? (
            <Popover.Root open={menuOpen} onOpenChange={setMenuOpen}>
              <Popover.Trigger
                aria-label="account"
                className="flex items-center gap-1 rounded-full py-0.5 pl-0.5 pr-1.5 text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
              >
                <span className="flex size-8 items-center justify-center rounded-full bg-fg-base text-xs font-semibold text-fg-inverse">
                  {initials(displayName, role)}
                </span>
                <ChevronDown className="size-3.5" aria-hidden="true" />
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  align="end"
                  sideOffset={8}
                  className="z-50 w-72 overflow-hidden rounded-xl border border-border-default bg-surface-panel shadow-pop"
                >
                  <div className="space-y-0.5 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 truncate text-sm font-semibold text-fg-base">{displayName || ROLE_LABELS[role]}</span>
                      {role === 'developer' && (
                        <span className="shrink-0 rounded-md bg-fg-base/5 px-1.5 py-px text-xs font-medium text-fg-muted ring-1 ring-inset ring-border-default">
                          Developer
                        </span>
                      )}
                    </div>
                    {email && <div className="truncate text-xs text-fg-muted" title={email}>{email}</div>}
                    {role !== 'developer' && (
                      <div className="truncate text-xs text-fg-dimmed">
                        {ROLE_LABELS[role]}{scope && ` · ${scope}`}{isAdmin && ' · administrator'}
                      </div>
                    )}
                  </div>
                  {demo.data?.enabled && (
                    // prototype mode (backend DEMO_LOGIN): one click opens another role, ministry or agency
                    <div className="border-t border-border-subtle py-1">
                      <div className="px-4 pb-1 pt-1.5 text-xs font-medium text-fg-dimmed">Switch role (demo)</div>
                      <DemoRoleList variant="menu" onPicked={() => setMenuOpen(false)} />
                    </div>
                  )}
                  <div className="border-t border-border-subtle py-1">
                    <Popover.Close asChild>
                      <button type="button" onClick={() => setChanging(true)} className={ITEM}>
                        <KeyRound className="size-4" aria-hidden="true" /> Change password
                      </button>
                    </Popover.Close>
                    {canAdmin(session) && (
                      <Popover.Close asChild>
                        <Link to="/admin" className={ITEM}>
                          <ShieldCheck className="size-4" aria-hidden="true" /> Administration
                        </Link>
                      </Popover.Close>
                    )}
                    <Popover.Close asChild>
                      <button
                        type="button"
                        onClick={async () => {
                          await signOut()
                          navigate('/')
                        }}
                        className={ITEM}
                      >
                        <LogOut className="size-4" aria-hidden="true" /> Sign out
                      </button>
                    </Popover.Close>
                  </div>
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          ) : status === 'loading' ? null : (
            <Link
              to="/login"
              className="inline-flex h-8 items-center rounded-lg bg-fg-base px-3 text-xs font-medium text-fg-inverse shadow-sm hover:bg-fg-base/85 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            >
              Sign in
            </Link>
          )}
        </div>
      </div>

      {expired && (
        <div className="border-t border-warning/30 bg-warning/5 px-4 py-1.5 text-center text-xs text-warning">
          Your session expired.{' '}
          <Link to="/login" className="font-medium underline underline-offset-2">Sign in again</Link>
        </div>
      )}

      {isOffline(meta.error) && (
        <div className="border-t border-critical/30 bg-critical/5 px-4 py-1.5 text-center text-xs text-critical">
          The data service is not answering at {API_BASE || 'this address'}. On the server, start it with <code className="font-mono">{START_BACKEND}</code>
        </div>
      )}

      <ChangePasswordDialog open={changing} onOpenChange={setChanging} email={email} />
    </header>
  )
}
