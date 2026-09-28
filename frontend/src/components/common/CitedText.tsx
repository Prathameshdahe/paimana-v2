import React from 'react'
import { splitCitations, type CiteStyle } from '@/lib/citations'
import { cn } from '@/lib/formatters'

/**
 * LLM text with its citation markers as React nodes (lib/citations): renderCite draws one ref (a chip, or null to
 * keep the marker as plain text when it points at nothing). No HTML is ever injected.
 */
export function CitedText({ text, style, renderCite, className }: {
  text: string
  style: CiteStyle
  renderCite: (ref: string) => React.ReactNode | null
  className?: string
}) {
  return (
    <span className={className}>
      {splitCitations(text, style).map((s, i) =>
        s.kind === 'text' ? (
          <React.Fragment key={i}>{s.text}</React.Fragment>
        ) : s.kind === 'bold' ? (
          <strong key={i} className="font-semibold">{s.text}</strong>
        ) : (
          <React.Fragment key={i}>
            {s.refs.map((r, j) => (
              <React.Fragment key={`${r}-${j}`}>{renderCite(r) ?? `[${r}]`}</React.Fragment>
            ))}
          </React.Fragment>
        )
      )}
    </span>
  )
}

/** a superscript citation chip: small, keyboard-reachable, labelled with what it points at */
export function CiteChip({ label, title, active, onClick, className }: {
  label: string
  title: string
  active?: boolean
  onClick?: () => void
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={title}
      title={title}
      className={cn(
        // raised by position, not vertical-align, so a cited line keeps its height
        'relative -top-1.5 mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded px-1 text-xs font-semibold leading-none transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        active ? 'bg-accent text-fg-inverse' : 'bg-accent/15 text-accent hover:bg-accent/25',
        className
      )}
    >
      {label}
    </button>
  )
}
