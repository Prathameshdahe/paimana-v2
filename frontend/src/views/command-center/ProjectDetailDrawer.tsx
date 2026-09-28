import { useState } from 'react'
import { Link } from 'react-router-dom'
import * as Dialog from '@radix-ui/react-dialog'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { ChevronDown, ExternalLink, FlaskConical, X } from 'lucide-react'
import { Badge, StalledBadge } from '@/components/ui/Badge'
import { ApiErrorNote } from '@/components/common/ApiErrorNote'
import { ApiError } from '@/lib/api'
import { useProject, useSignals, useTimeline } from '@/lib/queries'
import { restoreOpener, useProjectPanel } from '@/lib/useProjectPanel'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { detailHeadline } from '@/lib/headline'
import { driversOf, outlookOf } from '@/lib/outlook'
import { cn } from '@/lib/formatters'
import {
  ExternalChips, MoneyBar, ProgressTrend, ProjectChips, RiskGrid, TimelineStrip, TimeVsWork, VisualsSkeleton,
} from '@/views/project-studio/ProjectVisuals'
import { OutlookTiles } from '@/views/project-studio/Outlook'
import { WhyBlock } from '@/views/project-studio/WhyBlock'
import { BriefCard } from '@/views/project-studio/BriefCard'
import { ResearchNews } from '@/views/project-studio/ResearchNews'
import { SecondOpinionCard } from '@/views/project-studio/SecondOpinionCard'

const HEAD_LINK = 'inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-default bg-surface-panel px-3 text-xs font-medium text-fg-base shadow-sm transition-colors hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent'

/**
 * The project side panel: one project in the order an officer reads it — the sentence, the outlook tiles, why it is
 * happening and what the checks found, the AI brief on request and the second opinion (officials), then the report
 * facts, the outside issues and research. Opened from any list through useProjectPanel (?project=KEY) and mounted
 * once in App. Radix Dialog gives Escape, backdrop close, focus trap and labels; closing gives focus back to what opened
 * it (the map lane, the table row: useProjectPanel remembers it; the panel has no Dialog.Trigger). motion slides it
 * (not under reduced motion). The API already cuts what the viewer may not see; the developer gets a link into the Model detail tab.
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
              <Dialog.Content asChild forceMount aria-describedby={undefined}
                onCloseAutoFocus={(e) => { e.preventDefault(); restoreOpener() }}>
                <motion.aside
                  data-lenis-prevent
                  className="fixed inset-y-0 right-0 z-50 flex w-[calc(100%-64px)] max-w-[680px] flex-col border-l border-border-default bg-surface-base shadow-2xl focus:outline-none max-sm:w-full"
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

/** "Read the AI brief": folded until asked, then written (and cached for the next open) */
function FoldedBrief({ projectKey }: { projectKey: string }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="rounded-xl border border-border-subtle bg-surface-panel shadow-card">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 rounded-xl px-4 py-3 text-left text-sm font-semibold text-fg-base hover:bg-surface-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent">
        Read the AI brief
        <ChevronDown className={cn('size-4 text-fg-muted transition-transform', open && 'rotate-180')} aria-hidden="true" />
      </button>
      {open && <div className="px-3 pb-3"><BriefCard projectKey={projectKey} autoRequest className="shadow-none" /></div>}
    </section>
  )
}

function PanelBody({ projectKey }: { projectKey: string }) {
  const { role } = useSession()
  const insights = can(role, 'canSeeDrivers')
  const numbers = can(role, 'canSeeNumbers')
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
            {detail?.scores?.stagnationOverride && <StalledBadge quarters={detail.scores.stagnationQuarters} />}
          </div>
          <Dialog.Title className="line-clamp-2 text-lg font-semibold leading-snug text-fg-base">
            {detail?.master?.projectName ?? projectKey}
          </Dialog.Title>
          {detail && <ProjectChips detail={detail} />}
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {!error && <Link to={`/projects/${k ?? projectKey}`} className={HEAD_LINK}>Open full page <ExternalLink className="size-3.5" aria-hidden="true" /></Link>}
          {!error && numbers && (
            <Link to={`/projects/${k ?? projectKey}?tab=model`} className={HEAD_LINK}>
              <FlaskConical className="size-3.5" aria-hidden="true" /> Model detail
            </Link>
          )}
          <Dialog.Close
            className="inline-flex size-8 items-center justify-center rounded-lg text-fg-muted transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
            aria-label="Close project panel"
          >
            <X className="size-4" />
          </Dialog.Close>
        </div>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {error ? (
          error instanceof ApiError && error.status === 404 ? (
            <div className="py-12 text-center text-sm text-fg-muted">This project was not found, or it is not in your view.</div>
          ) : (
            <ApiErrorNote error={error} />
          )
        ) : !detail ? (
          <VisualsSkeleton />
        ) : (
          <>
            <p className="text-base leading-relaxed text-fg-base">{detailHeadline(detail, numbers)}</p>
            <OutlookTiles outlook={outlookOf(detail.scores, numbers)} tier={detail.scores?.tier ?? null} />
            <WhyBlock drivers={driversOf(detail.scores, numbers)} checks={detail.riskProfile} numbers={numbers} compact />
            {k && insights && <FoldedBrief key={`b-${k}`} projectKey={k} />}
            {k && can(role, 'canSeeSecondOpinion') && (
              <SecondOpinionCard key={k} projectKey={k} variant="panel" tier={detail.scores?.tier} />
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <TimeVsWork detail={detail} />
              <MoneyBar detail={detail} />
            </div>
            <ProgressTrend timeline={timeline.data} error={timeline.error} />
            <TimelineStrip detail={detail} />
            <ExternalChips
              detail={detail}
              news={signals.data && { n: signals.data.items.length, scouted: !!signals.data.lastScoutAt }}
              research={detail.research}
            />
            <RiskGrid detail={detail} plain={!insights} numbers={numbers} />
            <ResearchNews projectKey={k} variant="panel" />
          </>
        )}
      </div>
    </>
  )
}
