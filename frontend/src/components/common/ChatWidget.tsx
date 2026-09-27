import { useState, useRef, useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bot, Send, Sparkles, X } from 'lucide-react'
import { apiGet, isOffline, START_BACKEND } from '@/lib/api'
import { usePortfolio, type ProjectQuery } from '@/lib/queries'
import { cn, formatINRShort, formatProb, orDash } from '@/lib/formatters'
import { useRole } from '@/lib/auth/RoleContext'
import { can } from '@/lib/auth/access'
import type { ProjectPage, Tier } from '@/contracts/project'

interface Message {
  role: 'user' | 'assistant'
  text: string
}

const STARTERS = [
  'critical road projects',
  'power projects in Maharashtra',
  'how many high projects',
  'Haridwar bypass',
]

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

/** The project assistant, for the roles the access map gives canChat; answers stay in the viewer's scope. */
export function ChatWidget() {
  const { role } = useRole()
  return can(role, 'canChat') ? <Chat /> : null
}

function Chat() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', text: 'Ask about open projects by tier, sector or state, or search a project name.' },
  ])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, open])

  const { data: portfolio } = usePortfolio()

  async function answer(q: string): Promise<string> {
    const names = (rows: { name: string | null }[] | undefined) =>
      (rows ?? []).map((r) => r.name).filter((n): n is string => !!n)
    const query = parseQuestion(q, names(portfolio?.bySector), names(portfolio?.byState))
    const topN = Number(q.match(/top\s*(\d+)/i)?.[1] ?? 8)
    const scope = [query.tier, query.sector, query.state && `in ${query.state}`, query.q && `matching "${query.q}"`]
      .filter(Boolean)
      .join(' ')
    try {
      const page = await apiGet<ProjectPage>('/api/projects', { ...query, sort: 'risk', size: Math.min(topN, 20) })
      if (/\bhow many\b|\bcount\b|\bnumber of\b/i.test(q)) return `${page.total} ${scope} open project(s).`
      if (page.total === 0) return `No open ${scope} projects in the current portfolio.`
      const lines = page.items.map(
        (p) =>
          `${p.key} — ${p.name ?? ''} (${p.state ?? 'state unknown'}) — ${p.tier ?? 'no completion date'}, ` +
          `P(slip, 2q) ${orDash(p.pAny2q, formatProb)}, ${orDash(p.anticipatedCostCr, formatINRShort)}`
      )
      const more = page.total > page.items.length ? ` (top ${page.items.length} of ${page.total} by P(slip, 2q))` : ''
      return `${page.total} ${scope} project(s)${more}:\n${lines.join('\n')}`
    } catch (e) {
      return isOffline(e) ? `The backend is not reachable. Start it with: ${START_BACKEND}` : `Search failed: ${String(e)}`
    }
  }

  async function submit(text: string) {
    const q = text.trim()
    if (!q) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', text: q }])
    const reply = await answer(q)
    setMessages((m) => [...m, { role: 'assistant', text: reply }])
  }

  return (
    <div data-no-print className="fixed bottom-5 right-5 z-50">
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.96 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="mb-3 flex h-[520px] w-[380px] flex-col overflow-hidden rounded-2xl border border-border-default bg-surface-panel shadow-2xl shadow-black/20"
          >
            {/* Header */}
            <div className="flex items-center gap-2.5 border-b border-border-subtle bg-surface-elevated px-4 py-3">
              <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-fg-inverse">
                <Bot className="size-5" strokeWidth={2} />
                <span className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-surface-elevated bg-stable" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-semibold text-fg-base">
                  Project Intelligence
                </div>
                <div className="text-xs text-fg-dimmed">Keyword search · /api/projects</div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="flex size-7 items-center justify-center rounded-full text-fg-dimmed transition-colors hover:bg-surface-base hover:text-fg-base"
                aria-label="Close"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3 text-xs">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={cn('flex items-end gap-2', m.role === 'user' && 'flex-row-reverse')}
                >
                  {m.role === 'assistant' && (
                    <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                      <Bot className="size-3.5" strokeWidth={2} />
                    </div>
                  )}
                  <div
                    className={cn(
                      'max-w-[78%] whitespace-pre-wrap rounded-2xl px-3 py-2 leading-relaxed shadow-sm',
                      m.role === 'user'
                        ? 'rounded-br-sm bg-accent text-fg-inverse'
                        : 'rounded-bl-sm border border-border-subtle bg-surface-base text-fg-base'
                    )}
                  >
                    {m.text}
                  </div>
                </div>
              ))}
            </div>

            {/* Starter prompts */}
            <div className="border-t border-border-subtle px-3 pb-2 pt-2.5">
              <div className="mb-1.5 flex items-center gap-1 text-xs text-fg-dimmed">
                <Sparkles className="size-3" />
                Try asking
              </div>
              <div className="flex flex-wrap gap-1.5">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    onClick={() => submit(s)}
                    className="rounded-full border border-border-subtle px-2.5 py-1 text-xs text-fg-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-fg-base"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            {/* Input */}
            <form
              onSubmit={(e) => {
                e.preventDefault()
                submit(input)
              }}
              className="flex items-center gap-2 border-t border-border-subtle p-2.5"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="Ask about projects..."
                className="flex-1 rounded-full border border-border-subtle bg-surface-base px-3.5 py-2 text-xs text-fg-base outline-none focus:border-accent"
              />
              <button
                type="submit"
                disabled={!input.trim()}
                aria-label="Send"
                className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent text-fg-inverse transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <Send className="size-4" strokeWidth={2} />
              </button>
            </form>
          </motion.div>
        )}
      </AnimatePresence>

      <motion.button
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-14 w-14 items-center justify-center rounded-full bg-accent text-fg-inverse shadow-lg shadow-black/25"
        aria-label="Toggle project assistant"
      >
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={open ? 'close' : 'open'}
            initial={{ opacity: 0, rotate: -45 }}
            animate={{ opacity: 1, rotate: 0 }}
            exit={{ opacity: 0, rotate: 45 }}
            transition={{ duration: 0.15 }}
            className="flex items-center justify-center"
          >
            {open ? <X className="size-5" /> : <Bot className="size-6" strokeWidth={2} />}
          </motion.span>
        </AnimatePresence>
        {!open && (
          <span className="absolute -top-0.5 -right-0.5 size-3 rounded-full border-2 border-surface-base bg-stable" />
        )}
      </motion.button>
    </div>
  )
}
