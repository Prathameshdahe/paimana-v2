import React from 'react'
import * as RadixTooltip from '@radix-ui/react-tooltip'
import { Info } from 'lucide-react'
import { cn } from '@/lib/formatters'

export const TooltipProvider = RadixTooltip.Provider

export function Tooltip({
  children,
  content,
  side = 'top',
  className,
}: {
  children: React.ReactNode
  content: React.ReactNode
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}) {
  return (
    <RadixTooltip.Root delayDuration={150}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          collisionPadding={12}
          className={cn(
            'z-[60] max-w-xs rounded-lg border border-border-default bg-surface-panel px-3 py-2 text-xs leading-relaxed text-fg-base shadow-pop',
            className
          )}
        >
          {content}
          <RadixTooltip.Arrow className="fill-surface-panel" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}

/** An (i) that shows a caveat or method note on hover or focus, instead of a paragraph on the page. */
export function InfoTip({ children, label = 'About this', className }: { children: React.ReactNode; label?: string; className?: string }) {
  return (
    <Tooltip content={<div className="space-y-1.5 font-normal">{children}</div>}>
      <button
        type="button"
        aria-label={label}
        className={cn(
          'inline-flex shrink-0 items-center justify-center rounded-full text-fg-dimmed transition-colors hover:text-fg-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent',
          className
        )}
      >
        <Info className="size-4" strokeWidth={2} />
      </button>
    </Tooltip>
  )
}
