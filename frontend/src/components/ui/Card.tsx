import React from 'react'
import { cn } from '@/lib/formatters'

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 'section' = bordered structural region. 'flat' = no border, flush. */
  variant?: 'section' | 'flat'
  title?: string
  titleRight?: React.ReactNode
}

/**
 * Structural region — NOT a floating card.
 * Sharp corners, 1px hairline borders, tight padding.
 * Replaces the generic rounded-md p-4 bubble card.
 */
export function Card({
  className,
  variant = 'section',
  title,
  titleRight,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        variant === 'section'
          ? 'border border-border-subtle bg-surface-panel'
          : 'bg-transparent',
        className
      )}
      {...props}
    >
      {(title || titleRight) && (
        <div className="flex items-center justify-between border-b border-border-subtle px-5 py-3">
          {title && (
            <span className="text-xs font-mono font-semibold uppercase tracking-widest text-fg-muted">
              {title}
            </span>
          )}
          {titleRight && <div className="shrink-0">{titleRight}</div>}
        </div>
      )}
      {children}
    </div>
  )
}
