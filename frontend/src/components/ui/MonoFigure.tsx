import React from 'react'
import { cn } from '@/lib/formatters'

interface MonoFigureProps extends React.HTMLAttributes<HTMLSpanElement> {
  children: React.ReactNode
  size?: 'xs' | 'sm' | 'base' | 'lg' | 'xl' | '2xl' | '3xl'
  sentiment?: 'critical' | 'warning' | 'stable' | 'accent' | 'default' | 'muted'
}

const sizeClasses = {
  xs: 'text-xs leading-none',
  sm: 'text-xs leading-none',
  base: 'text-sm leading-none',
  lg: 'text-base leading-none',
  xl: 'text-lg font-medium leading-none',
  '2xl': 'text-xl font-semibold leading-none',
  '3xl': 'text-2xl font-semibold leading-none tracking-tight',
}

const sentimentClasses = {
  critical: 'text-critical',
  warning: 'text-warning',
  stable: 'text-stable',
  accent: 'text-accent',
  default: 'text-fg-base',
  muted: 'text-fg-muted',
}

export function MonoFigure({
  children,
  size = 'base',
  sentiment = 'default',
  className,
  ...props
}: MonoFigureProps) {
  return (
    <span
      className={cn(
        'font-mono tabular-nums',
        sizeClasses[size],
        sentimentClasses[sentiment],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}
