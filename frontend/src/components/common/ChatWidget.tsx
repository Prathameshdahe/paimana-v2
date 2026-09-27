import { useState, useRef, useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bot, Send, Sparkles, X } from 'lucide-react'
import { askQuestion } from '@/lib/queryEngine'
import { cn } from '@/lib/formatters'
import { useRole } from '@/lib/auth/RoleContext'

interface Message {
  role: 'user' | 'assistant'
  text: string
}

const STARTERS = [
  'critical railway projects',
  'projects in Maharashtra over 50% overrun',
  'how many warning projects',
  'top 5 power projects by risk',
]

/**
 * Floating project-intelligence Q&A widget. Answers against the real
 * dataset via queryEngine.ts (local rule-based, no LLM yet — see that
 * file's header for the Ollama swap point).
 */
export function ChatWidget() {
  const { role } = useRole()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', text: 'Ask me about projects — sector, state, risk tier, overrun %, or delay months.' },
  ])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Only render for these specific roles
  if (!role || !['ipmd_analyst', 'ministry_official'].includes(role)) {
    return null
  }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, open])

  function submit(text: string) {
    const q = text.trim()
    if (!q) return
    const result = askQuestion(q)
    setMessages((m) => [...m, { role: 'user', text: q }, { role: 'assistant', text: result.answer }])
    setInput('')
  }

  return (
    <div data-no-print className="fixed bottom-5 right-5 z-50 font-mono">
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
                <div className="text-xs font-semibold uppercase tracking-widest text-fg-base">
                  Project Intelligence
                </div>
                <div className="text-[10px] text-fg-dimmed">Rule-based · answers from live data</div>
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
            <div 
              ref={scrollRef} 
              onWheel={(e) => e.stopPropagation()}
              className="flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-3 text-[12px]"
            >
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
              <div className="mb-1.5 flex items-center gap-1 text-[10px] uppercase tracking-widest text-fg-dimmed">
                <Sparkles className="size-3" />
                Try asking
              </div>
              <div className="flex flex-wrap gap-1.5">
                {STARTERS.map((s) => (
                  <button
                    key={s}
                    onClick={() => submit(s)}
                    className="rounded-full border border-border-subtle px-2.5 py-1 text-[10px] text-fg-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-fg-base"
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
                className="flex-1 rounded-full border border-border-subtle bg-surface-base px-3.5 py-2 text-[12px] text-fg-base outline-none focus:border-accent"
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
