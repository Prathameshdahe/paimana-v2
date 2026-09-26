import { useNavigate } from 'react-router-dom'
import { usePortfolioSummary } from '@/mocks'
import { NavigationMenuWithActiveItem } from '@/components/ui/navigation-menu-05'
import { useRole } from '@/lib/auth/RoleContext'

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
  const { data: s } = usePortfolioSummary()
  const { role, displayName, clearRole } = useRole()
  const navigate = useNavigate()

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

        {/* Center: Live Portfolio Metrics — monospace ticker */}
        {s && (
          <div className="hidden lg:flex items-center gap-4 font-sans text-[12px] text-fg-muted">
            <span className="bg-surface-elevated text-fg-base px-2.5 py-1 rounded-sm border border-border-default font-semibold flex items-center gap-1.5 shadow-sm">
              <span className="font-mono tabular-nums">{s.totalProjects.toLocaleString()}</span>
              <span className="font-sans text-[10px] uppercase tracking-wider text-fg-dimmed">projects</span>
            </span>
          </div>
        )}

        {/* Right: Navigation Segments + role identity */}
        <nav className="flex items-center gap-4">
          <NavigationMenuWithActiveItem />

          <span className="text-border-strong/40">│</span>

          {role ? (
            <div className="flex items-center gap-2 font-mono text-[11px]">
              <span className="text-fg-muted">
                {displayName} <span className="text-fg-dimmed">· {ROLE_LABELS[role]}</span>
              </span>
              <button
                onClick={() => {
                  clearRole()
                  navigate('/login')
                }}
                className="text-fg-dimmed underline-offset-2 hover:text-fg-base hover:underline"
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
    </header>
  )
}
