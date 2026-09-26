import React from 'react'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import { cn } from '@/lib/formatters'

export const TooltipProvider = RadixTooltip.Provider

export function Tooltip({
  children,
  content,
  side = 'top',
}: {
  children: React.ReactNode
  content: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
}) {
  return (
    <RadixTooltip.Root delayDuration={150}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={4}
          className={cn(
            'z-50 overflow-hidden rounded border border-border-strong bg-surface-elevated px-2.5 py-1 text-xs text-fg-base shadow-md animate-in fade-in-0 zoom-in-95'
          )}
        >
          {content}
          <RadixTooltip.Arrow className="fill-surface-elevated" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}
