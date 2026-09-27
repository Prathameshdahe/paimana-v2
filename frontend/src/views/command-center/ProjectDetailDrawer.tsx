import { Link } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { ExternalLink, X } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { ApiError } from '@/lib/api'
import { useProject, useSignals, useTimeline } from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import {
  ExternalChips, MoneyBar, ProgressTrend, ProjectChips, RiskGrid, RiskRingCard, TimelineStrip, TimeVsWork, TopDrivers,
  VisualsSkeleton,
} from '@/views/project-studio/ProjectVisuals'

/**
 * The project side panel: a visual summary of one project (/api/projects/{key} + /timeline), opened from any
 * list through useProjectPanel (?project=KEY) and mounted once in App. Radix Dialog gives ESC, backdrop close,
 * focus trap and labels; motion slides it (not under reduced motion). The public gets the redacted blocks.
 */
export function ProjectDetailDrawer() {
  const { key, close } = useProjectPanel()
  return (
    <MotionConfig reducedMotion="user">
      <Dialog.Root open={key !== null} onOpenChange={(o) => { if (!o) close() }}>
        <AnimatePresence>
          {key !== null && (
            <Dialog.Portal forceMount>
              <Dialog.Overlay asChild forceMount>
                <motion.div className="fixed inset-0 z-50 bg-fg-base/30 backdrop-blur-[2px]"
                  initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
              </Dialog.Overlay>
              <Dialog.Content asChild forceMount aria-describedby={undefined}>
                <motion.aside
                  data-lenis-prevent
                  className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[680px] flex-col border-l border-border-default bg-surface-base shadow-2xl focus:outline-none"
                  initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
                  transition={{ type: 'tween', duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
                >
                  <PanelBody projectKey={key} />
                </motion.aside>
              </Dialog.Content>
            </Dialog.Portal>
          )}
        </AnimatePresence>
      </Dialog.Root>
    </MotionConfig>
  )
}

function PanelBody({ projectKey }: { projectKey: string }) {
  const { role } = useRole()
  const full = can(role, 'canSeeDrivers')
  const { data: detail, error } = useProject(projectKey)
  // the canonical key: an old or merged key resolves to the project it now belongs to
  const k = detail?.key ?? null
  const timeline = useTimeline(k)
  const signals = useSignals(can(role, 'canSeeNews') ? k : null)

  return (
    <>
      <header className="flex items-start gap-3 border-b border-border-subtle bg-surface-panel px-5 py-4">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-fg-dimmed">{k ?? projectKey}</span>
            {detail?.scores && <Badge tier={detail.scores.tier} />}
          </div>
          <Dialog.Title className="line-clamp-2 text-lg font-semibold leading-snug text-fg-base">
            {detail?.master?.projectName ?? projectKey}
          </Dialog.Title>
          {detail && <ProjectChips detail={detail} />}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!error && <Link
            to={`/projects/${k ?? projectKey}`}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-default bg-surface-panel px-3 text-xs font-medium text-fg-base shadow-sm transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          >
            Open full page <ExternalLink className="size-3.5" />
          </Link>}
          <Dialog.Close
            className="inline-flex size-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
            aria-label="Close project panel"
          >
            <X className="size-4" />
          </Dialog.Close>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {error ? (
          error instanceof ApiError && error.status === 404 ? (
            <div className="py-12 text-center text-sm text-fg-muted">Project not found, or not in your view.</div>
          ) : (
            <ApiErrorNote error={error} />
          )
        ) : !detail ? (
          <VisualsSkeleton />
        ) : (
          <>
            <RiskRingCard detail={detail} full={full} />
            <div className="grid gap-4 sm:grid-cols-2">
              <TimeVsWork detail={detail} />
              <MoneyBar detail={detail} />
            </div>
            <ProgressTrend timeline={timeline.data} error={timeline.error} />
            <TimelineStrip detail={detail} />
            <RiskGrid detail={detail} plain={!full} />
            <div className={full ? 'grid gap-4 sm:grid-cols-2' : ''}>
              {full && <TopDrivers drivers={detail.scores?.shapTop5 ?? []} />}
              <ExternalChips
                events={detail.external.events}
                news={signals.data && { n: signals.data.items.length, scouted: !!signals.data.lastScoutAt }}
              />
            </div>
          </>
        )}
      </div>
    </>
  )
}
