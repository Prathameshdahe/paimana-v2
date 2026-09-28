import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { matchPath, useLocation } from 'react-router-dom'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { Bot, ChevronRight, Crosshair, Eraser, Send, ShieldCheck, Sparkles, Square, X } from 'lucide-react'
import { ApiError, isOffline, START_BACKEND } from '@/lib/api'
import { MAX_CHARS, StreamBroken, chatMessages, streamChat } from '@/lib/chatStream'
import { usePortfolio, useProject } from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { TIER_LABEL, tierKey } from '@/lib/riskPalette'
import { cn } from '@/lib/formatters'
import { useSession, useScopeKey, type Role } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { CiteChip, CitedText } from './CitedText'
import { ErrorBoundary } from './ErrorBoundary'
import { ChatCardView, SourcesList, ToolSteps } from './ChatCards'
import type {
  ChatCard, ChatDone, ChatEvent, ChatSource, ChatStage, ChatTool, ChatTurn,
} from '@/contracts/assistant'
import type { Portfolio } from '@/contracts/portfolio'

interface UserTurn {
  id: number
  role: 'user'
  text: string
}

/** why an answer has no (or only part of a) narrative */
interface Problem {
  kind: 'offline' | 'limit' | 'failed' | 'stopped' | 'cut'
  message: string
}

interface AssistantTurn {
  id: number
  role: 'assistant'
  /** the narrative: streamed tokens, then done.text */
  text: string
  stage: ChatStage | null
  stageDetail: string | null
  steps: ChatTool[]
  cards: ChatCard[]
  sources: ChatSource[]
  /** the reasons of each draft set aside (retry events) */
  retries: string[][]
  done: ChatDone | null
  streaming: boolean
  problem: Problem | null
}

type Turn = UserTurn | AssistantTurn

const MIN_W = 320
const maxW = () => Math.max(MIN_W, window.innerWidth * 0.75)
const clampW = (w: number) => Math.round(Math.min(maxW(), Math.max(MIN_W, w)))

/** one SSE event folded into the answer it belongs to */
function applyEvent(t: AssistantTurn, e: ChatEvent): AssistantTurn {
  switch (e.event) {
    case 'status':
      return { ...t, stage: e.data.stage, stageDetail: e.data.detail }
    case 'tool': {
      const i = t.steps.findIndex((s) => s.id === e.data.id)
      const steps = i < 0 ? [...t.steps, e.data] : t.steps.map((s, j) => (j === i ? { ...s, ...e.data } : s))
      return { ...t, steps }
    }
    case 'card':
      return e.data.type === 'sources' ? { ...t, sources: e.data.items } : { ...t, cards: [...t.cards, e.data] }
    case 'token':
      return { ...t, text: t.text + e.data.text }
    case 'retry':
      // the draft so far goes (it failed the check, or the local model stopped); its replacement streams in its place
      return { ...t, text: '', retries: [...t.retries, e.data.reasons] }
    case 'done':
      return { ...t, text: e.data.text, done: e.data, streaming: false }
    case 'error':
      return { ...t, streaming: false, problem: { kind: 'failed', message: e.data.message } }
  }
}

function problemOf(e: unknown): Problem {
  if (e instanceof StreamBroken) return { kind: 'cut', message: e.message }
  if (isOffline(e)) return { kind: 'offline', message: e instanceof Error ? e.message : String(e) }
  if (e instanceof ApiError && e.status === 429) return { kind: 'limit', message: e.message }
  return { kind: 'failed', message: e instanceof ApiError ? `${e.message} (error ${e.status})` : String(e) }
}

/** the earlier turns as the backend wants them: text only, without answers that failed or were stopped */
function history(turns: Turn[]): ChatTurn[] {
  return turns.flatMap((t): ChatTurn[] =>
    t.role === 'user' ? [{ role: 'user', content: t.text }]
      : t.text && !t.problem ? [{ role: 'assistant', content: t.text }] : []
  )
}

/** the first words of a long project name, brackets dropped: enough for the assistant's name match */
function shortName(name: string): string {
  const words = name.replace(/\([^)]*\)/g, ' ').replace(/\s+/g, ' ').trim().split(' ')
  return words.slice(0, 4).join(' ').replace(/[,;:-]+$/, '')
}

/**
 * Starter questions from the viewer's own portfolio and the open project (open: its tier once loaded), so a
 * ministry sees its own names. The public's are about plain facts and terms; officials' about causes and change.
 */
function starters(role: Role | null, portfolio: Portfolio | undefined, open: { tier: string | null } | null): string[] {
  const state = portfolio?.byState.map((s) => s.name).find((n): n is string => !!n && !/multi/i.test(n)) ?? 'Maharashtra'
  const ranked = open?.tier && open.tier !== 'Watch' ? open.tier : null
  if (!can(role, 'canSeeDrivers')) {
    return [
      open && 'latest news on this project',
      `projects near completion in ${state}`,
      `what does ${ranked ?? 'High'} risk mean`,
      !open && 'where does the data come from',
    ].filter((s): s is string => !!s)
  }
  const named = (portfolio?.top ?? []).filter((p) => p.name)
  const critical = named.find((p) => p.tier === 'Critical') ?? named[0]
  const [a, b] = named
  return [
    open ? `why is this project ${ranked ?? 'at risk'}`
      : critical?.name && `why is ${shortName(critical.name)} ${TIER_LABEL[tierKey(critical.tier)]}`,
    open ? 'what changed for this project' : a?.name && `what changed for ${shortName(a.name)}`,
    !open && a?.name && b?.name && `compare ${shortName(a.name)} and ${shortName(b.name)}`,
    open && 'latest news on this project',
    `top 5 land blockers in ${state}`,
  ].filter((s): s is string => !!s).slice(0, 4)
}

/**
 * The project assistant, open to every role: the backend decides per tool what the viewer may read (the public gets
 * public facts only; a ministry or agency official only their own projects). Questions stream back over
 * POST /api/chat (lib/chatStream): the tool steps as a compact progress list, the data as cards, then a narrative
 * whose [n] markers are chips that scroll to the numbered sources. The project open in the side panel (or last open
 * there, on this page) or on its page goes along as projectKey ("this project"). A full-height right drawer resized by its left edge (320px to
 * 75% of the window), a round launcher; the conversation resets when the viewer's role or scope changes.
 */
export function ChatWidget() {
  const { role } = useSession()
  const scope = useScopeKey()
  // an error in the chat itself (not one answer or card, which have their own) takes the chat away, not the app
  return can(role, 'canChat') ? (
    <ErrorBoundary key={scope} fallback={null}>
      <Chat />
    </ErrorBoundary>
  ) : null
}

function Chat() {
  const { role, ministry, agency } = useSession()
  const panel = useProjectPanel()
  const { pathname } = useLocation()
  const [open, setOpen] = useState(false)
  const [width, setWidth] = useState(() => clampW(440))
  const [dragging, setDragging] = useState(false)
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [flash, setFlash] = useState<string | null>(null)
  const [announce, setAnnounce] = useState('')
  // The side panel is a modal dialog above this drawer, so its project is remembered after it closes (until the
  // viewer goes to another page): the viewer closes the panel, then asks. Updated during render, not in an effect,
  // so the chip never flickers between the panel closing and the effect running.
  const [lastPanel, setLastPanel] = useState<{ key: string; path: string } | null>(null)
  if (panel.key) {
    if (lastPanel?.key !== panel.key || lastPanel.path !== pathname) setLastPanel({ key: panel.key, path: pathname })
  } else if (lastPanel && lastPanel.path !== pathname) {
    setLastPanel(null)
  }
  const remembered = lastPanel?.path === pathname ? lastPanel.key : null
  // the open project: the side panel's, else the project page's, else the panel's last; the viewer can stop asking
  const openKey = panel.key ?? matchPath('/projects/:key', pathname)?.params.key ?? remembered
  const [dropped, setDropped] = useState<string | null>(null)
  const askKey = openKey && openKey !== dropped ? openKey : null
  const { data: openDetail } = useProject(askKey)
  // sent and shown only once the project loaded for this viewer (an unknown key, or one outside the viewer's scope,
  // would fail every question with a 404), as the backend's canonical key
  const ctxKey = askKey && openDetail ? openDetail.key : null
  const openName = openDetail?.master?.projectName ?? ctxKey
  const openTier = openDetail?.scores ? TIER_LABEL[tierKey(openDetail.scores.tier)] : null

  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const actionRef = useRef<HTMLButtonElement>(null)
  const stick = useRef(true)
  const abortRef = useRef<AbortController | null>(null)
  const nextId = useRef(1)
  const { data: portfolio, error: portfolioError } = usePortfolio()

  useEffect(() => () => abortRef.current?.abort(), [])

  // follow the answer while it streams, unless the viewer scrolled up to read
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [turns, open])

  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 2200)
    return () => clearTimeout(t)
  }, [flash])

  const onScroll = () => {
    const el = scrollRef.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 64
  }

  async function ask(text: string) {
    const q = text.trim().slice(0, MAX_CHARS)
    if (!q || busy) return
    const messages = chatMessages(history(turns), q)
    const id = nextId.current + 1
    nextId.current += 2
    const answer: AssistantTurn = {
      id, role: 'assistant', text: '', stage: null, stageDetail: null, steps: [], cards: [], sources: [], retries: [],
      done: null, streaming: true, problem: null,
    }
    setTurns((ts) => [...ts, { id: id - 1, role: 'user', text: q }, answer])
    setInput('')
    setBusy(true)
    setAnnounce('')
    stick.current = true
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const update = (f: (t: AssistantTurn) => AssistantTurn) =>
      setTurns((ts) => ts.map((t) => (t.id === id && t.role === 'assistant' ? f(t) : t)))
    try {
      await streamChat({ messages, projectKey: ctxKey ?? undefined }, (e) => {
        update((t) => applyEvent(t, e))
        if (e.event === 'done') setAnnounce(`Answer: ${e.data.text}`)
        if (e.event === 'error') setAnnounce(`The assistant hit a problem: ${e.data.message}`)
      }, ctrl.signal)
      // the stream closed without done or error: the connection dropped
      update((t) => (t.streaming
        ? { ...t, streaming: false, problem: { kind: 'cut', message: 'The answer stopped before it finished; the connection may have dropped.' } }
        : t))
    } catch (e) {
      const problem: Problem = ctrl.signal.aborted ? { kind: 'stopped', message: 'Stopped.' } : problemOf(e)
      update((t) => ({ ...t, streaming: false, problem }))
      if (!ctrl.signal.aborted) setAnnounce(problem.message)
    } finally {
      if (abortRef.current === ctrl) abortRef.current = null
      // Stop (or Send) is about to become a disabled Send: keep a keyboard viewer's focus in the drawer
      if (document.activeElement === actionRef.current) inputRef.current?.focus()
      setBusy(false)
    }
  }

  const stop = () => abortRef.current?.abort()

  const clear = () => {
    abortRef.current?.abort()
    setTurns([])
    setAnnounce('Conversation cleared')
    stick.current = true
    // the clear button turns disabled under the focus: the input takes it
    inputRef.current?.focus()
  }

  const showSource = (turnId: number, n: number) => {
    const el = document.getElementById(anchor(turnId, n))
    if (!el) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ block: 'nearest', behavior: reduced ? 'auto' : 'smooth' })
    el.focus({ preventScroll: true })
    setFlash(`${turnId}:${n}`)
  }

  // resize by the left edge; pointer capture keeps the drag when the pointer leaves the handle
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    setDragging(true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (dragging) setWidth(clampW(window.innerWidth - e.clientX))
  }
  const onHandleKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowLeft') setWidth((w) => clampW(w + 32))
    if (e.key === 'ArrowRight') setWidth((w) => clampW(w - 32))
  }

  const online = !portfolioError
  const scopeName = ministry ?? agency
  const welcome = !can(role, 'canSeeDrivers')
    ? 'Ask about public infrastructure projects: their risk, progress, cost and the latest news, or what a term means.'
    : `Ask about ${scopeName ? `${scopeName}’s` : 'any open'} projects: why one is at risk, what changed, how two compare, or where the blockers are.`
  const suggestions = starters(role, portfolio, ctxKey ? { tier: openTier } : null)

  return (
    <MotionConfig reducedMotion="user">
      <AnimatePresence>
        {!open && (
          <motion.button
            key="launcher"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={() => setOpen(true)}
            data-no-print
            className="fixed bottom-5 right-5 z-40 flex size-14 items-center justify-center rounded-full bg-accent text-fg-inverse shadow-lg shadow-black/25 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/40"
            aria-label="Open the project assistant"
          >
            <Bot className="size-6" strokeWidth={2} />
            <span className={cn('absolute -right-0.5 -top-0.5 size-3.5 rounded-full border-2 border-surface-base', online ? 'bg-stable' : 'bg-critical')} />
          </motion.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <motion.aside
            key="drawer"
            data-no-print
            role="complementary"
            aria-label="Project assistant"
            onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'tween', duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
            style={{ width, maxWidth: '100vw' }}
            className={cn(
              'fixed inset-y-0 right-0 z-[45] flex flex-col border-l border-border-default bg-surface-base shadow-2xl',
              dragging && 'select-none'
            )}
          >
            {/* the drag handle on the left edge; arrow keys resize it too */}
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize the assistant"
              aria-valuenow={width}
              aria-valuemin={MIN_W}
              tabIndex={0}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={() => setDragging(false)}
              onPointerCancel={() => setDragging(false)}
              onKeyDown={onHandleKey}
              className="group absolute inset-y-0 left-0 z-10 w-3 -translate-x-1/2 cursor-ew-resize touch-none focus-visible:outline-none"
            >
              <div className={cn(
                'mx-auto h-full w-1 rounded-full transition-colors group-hover:bg-accent/30 group-focus-visible:bg-accent/50',
                dragging && 'bg-accent/50'
              )} />
            </div>

            <div className="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface-panel px-4 py-3.5">
              <div className="relative flex size-10 shrink-0 items-center justify-center rounded-full bg-accent text-fg-inverse">
                <Bot className="size-5" strokeWidth={2} />
                <span className={cn('absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-surface-panel', online ? 'bg-stable' : 'bg-critical')} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-base font-semibold text-fg-base">Project Intelligence</div>
                <div className="truncate text-xs text-fg-dimmed">
                  {!can(role, 'canSeeDrivers') ? 'Answers from public project data' : scopeName ? `Answers from ${scopeName}` : 'Answers from every open project'}
                </div>
              </div>
              <button
                onClick={clear}
                disabled={turns.length === 0}
                className="flex size-9 items-center justify-center rounded-lg text-fg-dimmed transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:pointer-events-none disabled:opacity-40"
                aria-label="Clear the conversation"
                title="Clear the conversation"
              >
                <Eraser className="size-4" />
              </button>
              <button
                onClick={() => setOpen(false)}
                className="flex size-9 items-center justify-center rounded-lg text-fg-dimmed transition-colors hover:bg-surface-elevated hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                aria-label="Close the assistant"
              >
                <ChevronRight className="size-5" />
              </button>
            </div>

            <div ref={scrollRef} onScroll={onScroll} data-lenis-prevent className="flex-1 space-y-5 overflow-y-auto overscroll-contain px-4 py-5 text-sm">
              <AssistantRow>
                <div className="rounded-2xl rounded-tl-sm border border-border-subtle bg-surface-panel px-3.5 py-2.5 leading-relaxed text-fg-base shadow-sm">
                  {welcome}
                </div>
              </AssistantRow>
              {turns.map((t, i) =>
                t.role === 'user' ? (
                  <div key={t.id} className="flex justify-end">
                    <div className="min-w-0 max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-tr-sm bg-accent px-3.5 py-2.5 leading-relaxed text-fg-inverse shadow-sm">
                      {t.text}
                    </div>
                  </div>
                ) : (
                  <ErrorBoundary key={t.id} fallback={<AssistantRow><p className="text-xs text-fg-dimmed">This answer could not be shown.</p></AssistantRow>}>
                    <Answer t={t} latest={i === turns.length - 1} flash={flash} onCite={(n) => showSource(t.id, n)} />
                  </ErrorBoundary>
                )
              )}
            </div>
            <div className="sr-only" aria-live="polite">{announce}</div>

            <div className="shrink-0 space-y-3 border-t border-border-subtle bg-surface-panel px-4 py-3.5">
              {ctxKey && (
                <div className="flex">
                  <span className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full bg-accent/10 py-1 pl-2.5 pr-1 text-xs text-accent ring-1 ring-inset ring-accent/20">
                    <Crosshair className="size-3.5 shrink-0" aria-hidden="true" />
                    <span className="truncate" title={openName ?? undefined}>Asking about {openName}</span>
                    <button
                      type="button"
                      onClick={() => setDropped(askKey)}
                      className="flex size-5 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-accent/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      aria-label="Stop asking about this project"
                      title="Stop asking about this project"
                    >
                      <X className="size-3.5" />
                    </button>
                  </span>
                </div>
              )}
              {turns.length === 0 && (
                <div>
                  <div className="mb-2 flex items-center gap-1.5 text-xs text-fg-dimmed">
                    <Sparkles className="size-3.5" aria-hidden="true" /> Try asking
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => ask(s)}
                        disabled={busy}
                        className="rounded-full border border-border-subtle bg-surface-base px-3 py-1.5 text-left text-xs text-fg-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-50"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  ask(input)
                }}
                className="relative flex items-center"
              >
                <input
                  ref={inputRef}
                  autoFocus
                  value={input}
                  maxLength={MAX_CHARS}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder={ctxKey ? 'Ask about this project or any other…' : 'Ask about projects…'}
                  aria-label="Question"
                  className="w-full rounded-xl border border-border-default bg-surface-base py-3 pl-4 pr-12 text-sm text-fg-base shadow-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent"
                />
                {/* one button, Send or Stop: when the answer ends it turns into a disabled Send (the input is empty),
                    so ask() moves the focus to the input first rather than let it drop to the page */}
                <button
                  ref={actionRef}
                  type={busy ? 'button' : 'submit'}
                  onClick={busy ? stop : undefined}
                  disabled={!busy && !input.trim()}
                  aria-label={busy ? 'Stop the answer' : 'Send'}
                  title={busy ? 'Stop the answer' : undefined}
                  className={cn(
                    'absolute right-2 flex size-8 items-center justify-center rounded-lg text-fg-inverse transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-40',
                    busy ? 'bg-fg-base' : 'bg-accent'
                  )}
                >
                  {busy ? <Square className="size-3.5 fill-current" strokeWidth={2} /> : <Send className="size-4" strokeWidth={2} />}
                </button>
              </form>
              <p className="text-xs text-fg-dimmed">Answers come from PAIMANA data; the AI can make mistakes.</p>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </MotionConfig>
  )
}

const anchor = (turnId: number, n: number) => `chat-source-${turnId}-${n}`

function AssistantRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent" aria-hidden="true">
        <Bot className="size-4" strokeWidth={2} />
      </div>
      <div className="min-w-0 flex-1 space-y-2.5">{children}</div>
    </div>
  )
}

/** why the narrative is a template, or that it passed the number check; one row of fixed height, no jump on done */
function Verdict({ done }: { done: ChatDone }) {
  const secs = `${Math.max(1, Math.round(done.elapsedMs / 1000))} s`
  const note = done.llm === 'unavailable' ? 'AI summary unavailable, showing the data'
    : done.llm === 'busy' ? 'Assistant busy, showing the data'
    : !done.validated ? 'Not checked against the data' : null
  return (
    <div className="flex min-h-6 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-dimmed">
      {note ? (
        <span title={done.reasons.join('; ') || undefined}>{note}</span>
      ) : (
        <span
          className="inline-flex items-center gap-1 rounded-full bg-stable/10 px-2.5 py-0.5 font-medium text-stable ring-1 ring-inset ring-stable/20"
          title="Every number in this answer was traced to the data the assistant looked up"
        >
          <ShieldCheck className="size-3.5" aria-hidden="true" />
          Checked against the data
        </span>
      )}
      <span>{secs}</span>
    </div>
  )
}

function ProblemNote({ p }: { p: Problem }) {
  if (p.kind === 'offline') {
    return (
      <div className="space-y-1.5 rounded-xl border border-critical/25 bg-critical/5 px-3.5 py-2.5">
        <div className="font-medium text-critical">The backend is not reachable. Start it with:</div>
        <code className="block break-all text-xs text-fg-muted">{START_BACKEND}</code>
      </div>
    )
  }
  if (p.kind === 'limit') {
    return (
      <div className="rounded-xl border border-warning/25 bg-warning/5 px-3.5 py-2.5 text-fg-base">
        <div className="font-medium text-warning">Too many questions in a short time</div>
        <div className="mt-0.5 text-xs text-fg-muted">{p.message}</div>
      </div>
    )
  }
  if (p.kind === 'failed') {
    return <div className="rounded-xl border border-critical/25 bg-critical/5 px-3.5 py-2.5 text-fg-base">The assistant could not answer: {p.message}</div>
  }
  return <div className="text-xs text-fg-dimmed">{p.message}</div>
}

/** one answer: the tool steps, the data cards, the narrative with its source chips, the sources, the verdict */
function Answer({ t, latest, flash, onCite }: {
  t: AssistantTurn
  latest: boolean
  flash: string | null
  onCite: (n: number) => void
}) {
  const byN = new Map(t.sources.map((s) => [String(s.n), s]))
  const flashed = flash?.startsWith(`${t.id}:`) ? Number(flash.slice(String(t.id).length + 1)) : null
  const writing = t.streaming && !t.problem
  return (
    <AssistantRow>
      <ToolSteps steps={t.steps} stage={t.stage} detail={t.stageDetail} retries={t.retries} streaming={t.streaming} latest={latest} />
      {t.cards.map((c, i) => <ChatCardView key={i} card={c} />)}
      {(t.text || writing) && (
        <div className="rounded-2xl rounded-tl-sm border border-border-subtle bg-surface-panel px-3.5 py-2.5 leading-relaxed text-fg-base shadow-sm">
          {t.text ? (
            <p className="whitespace-pre-wrap break-words">
              <CitedText
                text={t.text}
                style="number"
                renderCite={(ref) => {
                  const s = byN.get(ref)
                  return s ? (
                    <CiteChip label={ref} title={`Source ${ref}: ${s.title}`} active={flashed === s.n} onClick={() => onCite(s.n)} />
                  ) : null
                }}
              />
              {writing && <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-fg-dimmed/60" aria-hidden="true" />}
            </p>
          ) : (
            <div className="flex h-6 items-center gap-1" aria-hidden="true">
              {[0, 1, 2].map((d) => (
                <span key={d} className="size-1.5 animate-bounce rounded-full bg-fg-dimmed" style={{ animationDelay: `${d * 120}ms` }} />
              ))}
            </div>
          )}
        </div>
      )}
      {t.sources.length > 0 && <SourcesList items={t.sources} anchor={(n) => anchor(t.id, n)} flashed={flashed} />}
      {t.problem && <ProblemNote p={t.problem} />}
      {t.done ? <Verdict done={t.done} /> : t.streaming && <div className="min-h-6" aria-hidden="true" />}
    </AssistantRow>
  )
}
