import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { PredictionPanel } from '@/views/project-studio/PredictionPanel'
import { ShapWaterfall } from '@/views/project-studio/ShapWaterfall'
import { ProvenanceLine } from '@/views/project-studio/ProjectIdentityStrip'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { useProject } from '@/lib/queries'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import { PublicSummary } from '@/views/project-studio/PublicSummary'

interface ProjectDetailDrawerProps {
  /** null: closed */
  projectKey: string | null
  onClose: () => void
}

/** Slide-over with one project's prediction and drivers, from /api/projects/{key}. */
export function ProjectDetailDrawer({ projectKey, onClose }: ProjectDetailDrawerProps) {
  const { data: detail, error, isLoading } = useProject(projectKey)
  const { role } = useRole()
  const full = can(role, 'canSeeDrivers')
  const isOpen = projectKey !== null

  // ESC key listener to dismiss drawer
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const m = detail?.master

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-fg-base/40 backdrop-blur-xs transition-opacity duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over Drawer Panel */}
      <aside
        data-lenis-prevent
        className="relative z-50 flex h-full w-full max-w-[85vw] flex-col border-l border-border-default bg-surface-base shadow-2xl"
        role="dialog"
        aria-modal="true"
        aria-label={`Project diagnostics for ${projectKey}`}
      >
        {/* Drawer Header */}
        <div className="flex items-center justify-between border-b border-border-default bg-surface-panel px-5 py-3">
          <div className="min-w-0 flex-1 space-y-0.5">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm font-bold text-fg-base">{projectKey}</span>
              {detail && <Badge tier={detail.scores ? detail.scores.tier : undefined} />}
              {m && (
                <span className="text-xs text-fg-dimmed truncate">
                  {m.sector ?? 'sector unknown'} · {m.agency ?? 'agency unknown'} · {m.state ?? 'state unknown'}
                </span>
              )}
            </div>
            <h2 className="truncate font-sans text-xs text-fg-muted font-medium">{m?.projectName ?? ''}</h2>
            {detail && full && <ProvenanceLine detail={detail} />}
          </div>

          <div className="ml-4 flex items-center gap-2">
            <Link to={`/projects/${projectKey}`} onClick={onClose}>
              <Button variant="secondary" size="sm">
                Full page ↗
              </Button>
            </Link>
            <button
              onClick={onClose}
              className="rounded-xs border border-border-subtle p-1 text-xs text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base"
              aria-label="Close project drawer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 bg-surface-panel/30">
          {error ? (
            <ApiErrorNote error={error} />
          ) : isLoading || !detail ? (
            <div className="h-48 flex items-center justify-center text-xs text-fg-dimmed">
              fetching project...
            </div>
          ) : !full ? (
            <div className="max-w-xl">
              <PublicSummary detail={detail} />
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              <div className="lg:col-span-2">
                <PredictionPanel detail={detail} />
              </div>
              <div className="lg:col-span-3">
                <ShapWaterfall drivers={detail.scores?.shapTop5 ?? []} />
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
