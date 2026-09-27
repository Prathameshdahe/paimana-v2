import React from 'react'
import { cn } from '@/lib/formatters'
import { InfoTip } from '@/components/ui/Tooltip'

/** The one page container: max width, gutters, vertical rhythm, and a fade-in on route change. */
export function Page({ className, children, narrow }: { className?: string; children: React.ReactNode; narrow?: boolean }) {
  return (
    <div
      className={cn(
        'mx-auto w-full space-y-5 px-4 py-6 sm:px-6 animate-page-in',
        narrow ? 'max-w-[1100px]' : 'max-w-[1440px]',
        className
      )}
    >
      {children}
    </div>
  )
}

/** Title, one-line subtitle, an optional (i) for caveats, and right-hand actions. */
export function PageHeader({
  title,
  subtitle,
  info,
  actions,
}: {
  title: React.ReactNode
  subtitle?: React.ReactNode
  info?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-fg-base">
          {title}
          {info && <InfoTip label="About this page">{info}</InfoTip>}
        </h1>
        {subtitle && <p className="mt-1 text-sm text-fg-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">{actions}</div>}
    </div>
  )
}
