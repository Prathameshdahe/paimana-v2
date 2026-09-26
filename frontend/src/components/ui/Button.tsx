import React from 'react'
import { cn } from '@/lib/formatters'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
}

export function Button({
  className,
  variant = 'secondary',
  size = 'md',
  children,
  disabled,
  ...props
}: ButtonProps) {
  const variantClasses = {
    primary:
      'bg-fg-base text-fg-inverse font-medium hover:bg-fg-muted disabled:opacity-40',
    secondary:
      'bg-surface-elevated text-fg-muted border border-border-default hover:text-fg-base hover:border-border-strong disabled:opacity-40',
    ghost:
      'bg-transparent text-fg-muted hover:text-fg-base disabled:opacity-40',
  }

  const sizeClasses = {
    sm: 'px-2 py-1 text-[11px] font-mono',
    md: 'px-3 py-1.5 text-xs font-mono',
  }

  return (
    <button
      className={cn(
        'inline-flex items-center gap-1.5 transition-colors select-none cursor-pointer',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
        'disabled:pointer-events-none',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  )
}
