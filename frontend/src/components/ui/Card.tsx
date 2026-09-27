import React from 'react'
import { cn } from '@/lib/formatters'
import { InfoTip } from './Tooltip'

interface CardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'title'> {
  /** 'section' = rounded panel. 'flat' = no border, flush. */
  variant?: 'section' | 'flat'
  title?: React.ReactNode
  /** a caveat or method note, behind an (i) next to the title */
  info?: React.ReactNode
  titleRight?: React.ReactNode
}

/** A rounded panel with an optional header row: title, info tip, right-hand actions. */
export function Card({ className, variant = 'section', title, info, titleRight, children, ...props }: CardProps) {
  return (
    <div
      className={cn(
        variant === 'section'
          ? 'overflow-hidden rounded-xl border border-border-subtle bg-surface-panel shadow-card animate-card-in'
          : 'bg-transparent',
        className
      )}
      {...props}
    >
      {(title || titleRight) && (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border-subtle px-5 py-3">
          {title && (
            <span className="flex min-w-0 items-center gap-1.5 text-sm font-semibold text-fg-base">
              {title}
              {info && <InfoTip>{info}</InfoTip>}
            </span>
          )}
          {titleRight && <div className="shrink-0 text-xs text-fg-muted">{titleRight}</div>}
        </div>
      )}
      {children}
    </div>
  )
}
