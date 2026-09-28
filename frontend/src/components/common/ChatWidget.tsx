import { useState, useRef, useEffect, type KeyboardEvent, type PointerEvent } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { Bot, ChevronRight, Send, Sparkles } from 'lucide-react'
import { apiGet, isOffline, START_BACKEND } from '@/lib/api'
import { usePortfolio, type ProjectQuery } from '@/lib/queries'
import { useProjectPanel } from '@/lib/useProjectPanel'
import { TIER_COLOR, TIER_LABEL, tierKey } from '@/lib/riskPalette'
import { cn, formatINRShort, formatProb, orDash } from '@/lib/formatters'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import type { ProjectPage, ProjectRow, Tier } from '@/contracts/project'

interface Message {
  role: 'user' | 'assistant'
  text: string
  /** the matching projects, shown as rows that open the side panel */
  projects?: ProjectRow[]
}

const MIN_W = 320
const maxW = () => Math.max(MIN_W, window.innerWidth * 0.75)
const clampW = (w: number) => Math.round(Math.min(maxW(), Math.max(MIN_W, w)))

const TIER_WORDS: Record<string, Tier> = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low' }
const stem = (w: string) => w.replace(/s$/, '')

/**
 * Turns a question into /api/projects filters: a tier word, a sector (any of
 * its words, plural-insensitive) and a state (full name) from the portfolio's
 * own names; with none of those the whole text is a name/key search (q=).
 */
function parseQuestion(text: string, sectors: string[], states: string[]): ProjectQuery {
  const lower = text.toLowerCase()
  const words = new Set((lower.match(/[a-z]+/g) ?? []).map(stem))
  const tierWord = Object.keys(TIER_WORDS).find((w) => words.has(w))
  const sector = sectors.find((s) => (s.toLowerCase().match(/[a-z]{4,}/g) ?? []).some((w) => words.has(stem(w))))
  const state = states.find((s) => lower.includes(s.toLowerCase()))
  const tier = tierWord ? TIER_WORDS[tierWord] : undefined
  if (!tier && !sector && !state) return { q: text.slice(0, 100) }
  return { tier, sector, state }
}

/**
 * The project assistant, for the roles the access map gives canChat (IPMD analysts, ministry officials); the
 * backend cuts every answer to the viewer's scope. Ported from Pranjal's frontend-dev: a full-height right drawer
 * resized by its left edge (320px to 75% of the window), a round launcher, starter chips.
 */
export function ChatWidget() {
  const { role } = useRole()
  return can(role, 'canChat') ? <Chat /> : null
}

function Chat() {
  const { ministry } = useRole()
  const panel = useProjectPanel()
  const [open, setOpen] = useState(false)
  const [width, setWidth] = useState(() => clampW(440))
  const [dragging, setDragging] = useState(false)
  const [pending, setPending] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      text: `Ask about ${ministry ? 'your ministry’s' : 'open'} projects by tier, sector or state, or search a project name.`,
    },
  ])
  const scrollRef = useRef<HTMLDivElement>(null)
  const { data: portfolio, error: portfolioError } = usePortfolio()

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, pending, open])

  // starters from the viewer's own portfolio, so a ministry sees its sectors and states
  const names = (rows: { name: string | null }[] | undefined) =>
    (rows ?? []).map((r) => r.name).filter((n): n is string => !!n)
  const sector = portfolio?.bySector.find((s) => s.name)?.name
  const state = names(portfolio?.byState).find((s) => !/multi/i.test(s))
  const starters = [
    'critical projects',
    sector && state ? `${sector} projects in ${state}` : 'projects in Maharashtra',
    'how many high projects',
    sector ? `top 5 ${sector} projects` : 'top 5 projects',
  ]

  async function answer(q: string): Promise<Message> {
    const query = parseQuestion(q, names(portfolio?.bySector), names(portfolio?.byState))
    const topN = Number(q.match(/top\s*(\d+)/i)?.[1] ?? 8)
    const scope = [query.tier, query.sector, query.state && `in ${query.state}`, query.q && `matching "${query.q}"`]
      .filter(Boolean)
      .join(' ')
    try {
      const page = await apiGet<ProjectPage>('/api/projects', { ...query, sort: 'risk', size: Math.min(topN, 20) })
      if (/\bhow many\b|\bcount\b|\bnumber of\b/i.test(q)) return { role: 'assistant', text: `${page.total} ${scope} open project(s).` }
      if (page.total === 0) return { role: 'assistant', text: `No open ${scope} projects in the current portfolio.` }
      const more = page.total > page.items.length ? `, the riskiest ${page.items.length} first` : ''
      return { role: 'assistant', text: `${page.total} ${scope} project(s)${more}:`, projects: page.items }
    } catch (e) {
      return {
        role: 'assistant',
        text: isOffline(e) ? `The backend is not reachable. Start it with: ${START_BACKEND}` : `Search failed: ${String(e)}`,
      }
    }
  }

  async function submit(text: string) {
    const q = text.trim()
    if (!q || pending) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: q }])
    setPending(true)
    const reply = await answer(q)
    setPending(false)
    setMessages((m) => [...m, reply])
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
            className="fixed bottom-5 right-5 z-40 flex size-14 items-center justify-center rounded-full bg-accent text-fg-inverse shadow-lg shadow-black/25"
            aria-label="Open project assistant"
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
            aria-label="Project Intelligence"
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
                <div className="truncate text-xs text-fg-dimmed">{ministry ? `Searches ${ministry}` : 'Searches every open project'}</div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="flex size-9 items-center justify-center rounded-lg text-fg-dimmed transition-colors hover:bg-surface-elevated hover:text-fg-base"
                aria-label="Close the assistant"
              >
                <ChevronRight className="size-5" />
              </button>
            </div>

            <div ref={scrollRef} data-lenis-prevent className="flex-1 space-y-4 overflow-y-auto overscroll-contain px-4 py-5 text-sm">
              {messages.map((m, i) => (
                <div key={i} className={cn('flex items-start gap-2.5', m.role === 'user' && 'flex-row-reverse')}>
                  {m.role === 'assistant' && (
                    <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                      <Bot className="size-4" strokeWidth={2} />
                    </div>
                  )}
                  <div
                    className={cn(
                      'min-w-0 max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 leading-relaxed shadow-sm',
                      m.role === 'user'
                        ? 'rounded-tr-sm bg-accent text-fg-inverse'
                        : 'rounded-tl-sm border border-border-subtle bg-surface-panel text-fg-base',
                      m.projects && 'w-full'
                    )}
                  >
                    {m.text}
                    {m.projects && (
                      <div className="-mx-1.5 mt-2 divide-y divide-border-subtle">
                        {m.projects.map((p) => {
                          const t = tierKey(p.tier)
                          return (
                            <button
                              key={p.key}
                              onClick={() => panel.open(p.key)}
                              className="flex w-full items-center gap-2.5 rounded-lg px-1.5 py-2 text-left transition-colors hover:bg-surface-elevated"
                            >
                              <span className="size-2.5 shrink-0 rounded-full" style={{ background: TIER_COLOR[t] }} title={TIER_LABEL[t]} />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate font-medium text-accent" title={p.name ?? undefined}>{p.name ?? p.key}</span>
                                <span className="block truncate text-xs text-fg-dimmed">
                                  {p.state ?? 'state unknown'} · {orDash(p.anticipatedCostCr, formatINRShort)}
                                </span>
                              </span>
                              <span className="shrink-0 text-xs font-semibold tabular-nums text-fg-base" title="chance of a new delay or cost revision within two quarters">
                                {orDash(p.pAny2q, formatProb)}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {pending && (
                <div className="flex items-center gap-2.5" aria-live="polite" aria-label="searching">
                  <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                    <Bot className="size-4" strokeWidth={2} />
                  </div>
                  <div className="flex gap-1 rounded-2xl rounded-tl-sm border border-border-subtle bg-surface-panel px-3.5 py-3">
                    {[0, 1, 2].map((d) => (
                      <span key={d} className="size-1.5 animate-bounce rounded-full bg-fg-dimmed" style={{ animationDelay: `${d * 120}ms` }} />
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="shrink-0 space-y-3 border-t border-border-subtle bg-surface-panel px-4 py-4">
              <div>
                <div className="mb-2 flex items-center gap-1.5 text-xs text-fg-dimmed">
                  <Sparkles className="size-3.5" /> Try asking
                </div>
                <div className="flex flex-wrap gap-2">
                  {starters.map((s) => (
                    <button
                      key={s}
                      onClick={() => submit(s)}
                      disabled={pending}
                      className="rounded-full border border-border-subtle bg-surface-base px-3 py-1.5 text-xs text-fg-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-fg-base disabled:opacity-50"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  submit(input)
                }}
                className="relative flex items-center"
              >
                <input
                  autoFocus
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask about projects…"
                  aria-label="Question"
                  className="w-full rounded-xl border border-border-default bg-surface-base py-3 pl-4 pr-12 text-sm text-fg-base shadow-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || pending}
                  aria-label="Send"
                  className="absolute right-2 flex size-8 items-center justify-center rounded-lg bg-accent text-fg-inverse transition-opacity hover:opacity-90 disabled:opacity-40"
                >
                  <Send className="size-4" strokeWidth={2} />
                </button>
              </form>
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </MotionConfig>
  )
}
