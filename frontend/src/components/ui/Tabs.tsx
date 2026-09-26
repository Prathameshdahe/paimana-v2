import React from 'react'
import * as RadixTabs from '@radix-ui/react-tabs'
import { cn } from '@/lib/formatters'

export const Tabs = RadixTabs.Root

export function TabsList({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixTabs.List>) {
  return (
    <RadixTabs.List
      className={cn(
        'inline-flex items-center gap-1 bg-surface-input/60 p-1 rounded-md border border-border-default',
        className
      )}
      {...props}
    />
  )
}

export function TabsTrigger({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixTabs.Trigger>) {
  return (
    <RadixTabs.Trigger
      className={cn(
        'inline-flex items-center justify-center whitespace-nowrap rounded px-3 py-1.5 text-xs font-medium tracking-wide transition-all select-none',
        'text-fg-muted hover:text-fg-base',
        'data-[state=active]:bg-surface-elevated data-[state=active]:text-fg-base data-[state=active]:border data-[state=active]:border-border-default data-[state=active]:shadow-sm',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent',
        className
      )}
      {...props}
    />
  )
}

export function TabsContent({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof RadixTabs.Content>) {
  return (
    <RadixTabs.Content
      className={cn('focus-visible:outline-none mt-4', className)}
      {...props}
    />
  )
}
