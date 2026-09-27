import { useState, useRef, useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Bot, Send, Sparkles, X, ChevronRight } from 'lucide-react'
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
 * Full-height side drawer Copilot. Answers against the real dataset via 
 * queryEngine.ts (local rule-based, no LLM yet — see that file's header 
 * for the Ollama swap point).
 */
export function ChatWidget() {
  const { role } = useRole()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [width, setWidth] = useState(450)
  const [isDragging, setIsDragging] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', text: 'Ask me about projects — sector, state, risk tier, overrun %, or delay months.' },
  ])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Only render for these specific roles
  if (!role || !['ipmd_analyst', 'ministry_official'].includes(role)) {
    return null
  }

  useEffect(() => {
    if (open) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
    }
  }, [messages, open])

  function submit(text: string) {
    const q = text.trim()
    if (!q) return
    const result = askQuestion(q)
    setMessages((m) => [...m, { role: 'user', text: q }, { role: 'assistant', text: result.answer }])
    setInput('')
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)

    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = window.innerWidth - e.clientX
      // Sensible min/max boundaries
      if (newWidth >= 320 && newWidth <= window.innerWidth * 0.75) {
        setWidth(newWidth)
      }
    }

    const handleMouseUp = () => {
      setIsDragging(false)
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  return (
    <>
      {/* Floating Toggle Button (Visible only when drawer is closed) */}
      <AnimatePresence>
        {!open && (
          <motion.div
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            className="fixed bottom-5 right-5 z-40"
          >
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              onClick={() => setOpen(true)}
              className="relative flex h-14 w-14 items-center justify-center rounded-full bg-accent text-fg-inverse shadow-lg shadow-black/25"
              aria-label="Open project assistant"
            >
              <Bot className="size-6" strokeWidth={2} />
              <span className="absolute -top-0.5 -right-0.5 size-3 rounded-full border-2 border-surface-base bg-stable" />
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Full-Height Drawer */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ x: '100%', opacity: 0.5 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: '100%', opacity: 0.5 }}
            transition={isDragging ? { duration: 0 } : { type: 'spring', damping: 25, stiffness: 200 }}
            style={{ width: `${width}px` }}
            className={cn(
              "fixed inset-y-0 right-0 z-50 flex flex-col border-l border-border-strong bg-surface-panel shadow-[-10px_0_30px_rgba(0,0,0,0.1)]",
              isDragging && "select-none transition-none"
            )}
          >
            {/* Resizable Drag Handle */}
            <div
              onMouseDown={handleMouseDown}
              className="absolute left-0 top-0 bottom-0 w-2 -translate-x-1/2 cursor-ew-resize group z-50"
              title="Drag to resize"
            >
              <div className={cn(
                "w-1 h-full mx-auto transition-colors",
                isDragging ? "bg-accent/40" : "group-hover:bg-accent/20"
              )} />
            </div>

            {/* Header */}
            <div className="flex shrink-0 items-center gap-3 border-b border-border-subtle bg-surface-elevated px-4 py-4">
              <button
                onClick={() => setOpen(false)}
                className="flex size-8 items-center justify-center rounded-md text-fg-dimmed transition-colors hover:bg-surface-base hover:text-fg-base"
                aria-label="Close"
              >
                <ChevronRight className="size-5" />
              </button>
              
              <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-fg-inverse">
                <Bot className="size-5" strokeWidth={2} />
                <span className="absolute -bottom-0.5 -right-0.5 size-2.5 rounded-full border-2 border-surface-elevated bg-stable" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold uppercase tracking-widest text-fg-base">
                  Project Intelligence
                </div>
                <div className="text-xs text-fg-dimmed mt-0.5">Rule-based · live dataset</div>
              </div>
            </div>

            {/* Messages Area */}
            <div 
              ref={scrollRef} 
              onWheel={(e) => e.stopPropagation()}
              className="flex-1 space-y-5 overflow-y-auto overscroll-contain px-5 py-6 text-sm"
            >
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={cn('flex items-start gap-3', m.role === 'user' && 'flex-row-reverse')}
                >
                  {m.role === 'assistant' && (
                    <div className="mt-1 flex size-7 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                      <Bot className="size-4" strokeWidth={2} />
                    </div>
                  )}
                  <div
                    className={cn(
                      'max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 leading-relaxed shadow-sm',
                      m.role === 'user'
                        ? 'rounded-tr-sm bg-accent text-fg-inverse'
                        : 'rounded-tl-sm border border-border-subtle bg-surface-base text-fg-base'
                    )}
                  >
                    {m.text}
                  </div>
                </div>
              ))}
            </div>

            {/* Starter Prompts & Input Area */}
            <div className="shrink-0 border-t border-border-subtle bg-surface-base px-4 py-4">
              
              <div className="mb-3">
                <div className="mb-2 flex items-center gap-1.5 text-[11px] uppercase tracking-widest text-fg-dimmed">
                  <Sparkles className="size-3.5" />
                  Try asking
                </div>
                <div className="flex flex-wrap gap-2">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      onClick={() => submit(s)}
                      className="rounded-full border border-border-subtle bg-surface-panel px-3 py-1.5 text-xs text-fg-muted transition-colors hover:border-accent/40 hover:bg-accent/10 hover:text-fg-base"
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
                className="relative mt-2 flex items-center"
              >
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask about projects..."
                  className="w-full rounded-xl border border-border-strong bg-white pl-4 pr-12 py-3 text-sm text-fg-base shadow-sm outline-none transition-colors focus:border-accent focus:ring-1 focus:ring-accent"
                />
                <button
                  type="submit"
                  disabled={!input.trim()}
                  aria-label="Send"
                  className="absolute right-2 flex size-8 items-center justify-center rounded-lg bg-accent text-fg-inverse transition-all hover:opacity-90 disabled:bg-surface-input disabled:text-fg-muted"
                >
                  <Send className="size-4" strokeWidth={2} />
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  )
}
