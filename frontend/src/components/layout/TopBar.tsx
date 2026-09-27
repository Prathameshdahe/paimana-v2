import { useNavigate } from 'react-router-dom'
import { NavigationMenuWithActiveItem } from '@/components/ui/navigation-menu-05'
import { useRole } from '@/lib/auth/RoleContext'
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

/**
 * TopBar — persistent telemetry rail.
 * Inspired by Bloomberg/Grafana: dense, monospace, structural.
 * Zero decorative icons. Information-first.
 */
export function TopBar() {
  const meta = useMeta()
  const { data: p } = usePortfolio()
  const m = meta.data
  const tierN = (t: string) => p?.tiers.find((x) => x.tier === t)?.n ?? 0
  const { role, displayName, clearRole } = useRole()
  const navigate = useNavigate()
  useAlertStream()

  return (
    <header data-no-print className="sticky top-0 z-40 w-full border-b border-border-default bg-surface-base/95 backdrop-blur-sm shadow-sm">
      <div className="mx-auto flex h-14 py-2 max-w-[1600px] items-center justify-between px-4">
        {/* Left: System Identifier */}
        <div className="flex items-center gap-3">
          <a href="/" className="flex items-baseline gap-1.5">
            <span className="font-sans text-base font-extrabold tracking-[0.2em] text-fg-base">
              PAIMANA
            </span>
            <span className="font-sans text-[11px] font-bold tracking-widest text-fg-dimmed">
              RADAR
            </span>
          </a>
        </div>

        {/* Center: Live Portfolio Metrics — monospace ticker (data version + tier counts) */}
        {m && (
          <div className="hidden lg:flex items-center gap-3 font-sans text-[12px] text-fg-muted">
            <span
              className="bg-surface-elevated text-fg-base px-2.5 py-1 rounded-sm border border-border-default font-semibold flex items-center gap-1.5 shadow-sm"
              title={`latest report: ${m.latestReportDoc ?? 'unknown'}`}
            >
              <span className="font-sans text-[10px] uppercase tracking-wider text-fg-dimmed">asof</span>
              <span className="font-mono tabular-nums whitespace-nowrap">{formatDate(m.asof)}</span>
              <span className="text-border-strong">·</span>
              <span className="font-mono tabular-nums">{m.nCurrent.toLocaleString()}</span>
              <span className="hidden xl:inline font-sans text-[10px] uppercase tracking-wider text-fg-dimmed">projects</span>
            </span>
            {p && (
              <span className="hidden xl:inline font-mono text-[11px] tabular-nums">
                <span className="text-critical font-semibold">{tierN('Critical')}</span> crit ·{' '}
                <span className="text-warning font-semibold">{tierN('High')}</span> high
              </span>
            )}
            <span className="hidden 2xl:inline font-mono text-[10px] text-fg-dimmed" title={Object.values(m.models).join(' · ')}>
              {m.modelVersion}
            </span>
          </div>
        )}

        {/* Right: Navigation Segments + role identity */}
        <nav className="flex items-center gap-3 xl:gap-4">
          <NavigationMenuWithActiveItem />

          <AlertBell />

          <span className="text-border-strong/40">│</span>

          {role ? (
            <div className="flex items-center gap-2 font-mono text-[11px]">
              {/* the role only from 2xl, the name always in the tooltip: six nav labels, the bell and this fit 1024px */}
              <span className="hidden 2xl:inline whitespace-nowrap text-fg-muted" title={displayName}>
                {ROLE_LABELS[role]}
              </span>
              <button
                title={`${displayName} · ${ROLE_LABELS[role]}`}
                onClick={() => {
                  clearRole()
                  navigate('/login')
                }}
                className="whitespace-nowrap text-fg-dimmed underline-offset-2 hover:text-fg-base hover:underline"
              >
                Switch role
              </button>
            </div>
          ) : (
            <a
              href="/login"
              className="font-mono text-[11px] text-fg-dimmed hover:text-fg-base hover:underline"
            >
              Sign in
            </a>
          )}
        </nav>
      </div>

      {isOffline(meta.error) && (
        <div className="border-t border-critical/30 bg-critical/5 px-4 py-1.5 text-center font-mono text-[11px] text-critical">
          backend not reachable at {API_BASE} — start uvicorn: <code>{START_BACKEND}</code>
        </div>
      )}
    </header>
  )
}
