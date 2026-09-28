import React from 'react'
import { cn } from '@/lib/formatters'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
}

const VARIANT = {
  primary: 'bg-fg-base text-fg-inverse shadow-sm hover:bg-fg-base/85',
  secondary:
    'bg-surface-panel text-fg-base border border-border-default shadow-sm hover:bg-surface-elevated hover:border-border-strong',
  ghost: 'bg-transparent text-fg-muted hover:bg-surface-elevated hover:text-fg-base',
}

const SIZE = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-9 px-4 text-sm',
}

export function Button({ className, variant = 'secondary', size = 'md', children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium transition-colors select-none cursor-pointer',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
        'disabled:pointer-events-none disabled:opacity-40',
        VARIANT[variant],
        SIZE[size],
        className
      )}
      {...props}
    >
      {children}
    </button>
  )
}
