import React from 'react'
import { cn } from '@/lib/formatters'

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: React.ReactNode
}

export function Input({ className, icon, ...props }: InputProps) {
  return (
    <div className="relative flex items-center">
      {icon && (
        <div className="absolute left-2.5 text-fg-muted pointer-events-none flex items-center">
          {icon}
        </div>
      )}
      <input
        className={cn(
          'w-full bg-surface-input border border-border-default rounded-md px-3 py-1.5 text-xs text-fg-base placeholder:text-fg-dimmed focus:outline-none focus:border-accent transition-colors',
          icon ? 'pl-8' : 'pl-3',
          className
        )}
        {...props}
      />
    </div>
  )
}
