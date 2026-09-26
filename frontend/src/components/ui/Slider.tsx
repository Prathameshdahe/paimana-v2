import React, { useState } from 'react'
import * as RadixSlider from '@radix-ui/react-slider'
import { cn } from '@/lib/formatters'

export interface SliderProps extends React.ComponentPropsWithoutRef<typeof RadixSlider.Root> {
  label?: string
  valueDisplay?: React.ReactNode
  min?: number
  max?: number
  step?: number
}

export function Slider({
  className,
  label,
  valueDisplay,
  min = 0,
  max = 100,
  step = 1,
  value,
  onValueChange,
  onValueCommit,
  ...props
}: SliderProps) {
  const [isDragging, setIsDragging] = useState(false)

  return (
    <div className="space-y-2">
      {(label || valueDisplay) && (
        <div className="flex items-center justify-between text-xs">
          {label && (
            <span
              className={cn(
                'font-medium transition-colors duration-150',
                isDragging ? 'text-accent font-semibold' : 'text-fg-muted'
              )}
            >
              {label}
            </span>
          )}
          {valueDisplay && (
            <span
              className={cn(
                'font-mono tabular-nums transition-all duration-150 inline-block',
                isDragging
                  ? 'text-accent font-bold scale-110 bg-accent/15 px-1.5 py-0.5 rounded-sm border border-accent/40 shadow-xs'
                  : 'text-fg-base px-1.5 py-0.5'
              )}
            >
              {valueDisplay}
            </span>
          )}
        </div>
      )}
      <RadixSlider.Root
        className={cn(
          'relative flex items-center select-none touch-none w-full h-5 cursor-pointer',
          className
        )}
        min={min}
        max={max}
        step={step}
        value={value}
        onValueChange={(val) => {
          setIsDragging(true)
          if (onValueChange) onValueChange(val)
        }}
        onValueCommit={(val) => {
          setIsDragging(false)
          if (onValueCommit) onValueCommit(val)
        }}
        onPointerDown={() => setIsDragging(true)}
        onPointerUp={() => setIsDragging(false)}
        onPointerCancel={() => setIsDragging(false)}
        {...props}
      >
        <RadixSlider.Track className="bg-surface-input relative grow rounded-full h-1.5 border border-border-default">
          <RadixSlider.Range
            className={cn(
              'absolute rounded-full h-full transition-colors',
              isDragging ? 'bg-accent ring-1 ring-accent' : 'bg-accent'
            )}
          />
        </RadixSlider.Track>
        <RadixSlider.Thumb
          className={cn(
            'block w-4 h-4 rounded-full shadow-md transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-accent',
            isDragging
              ? 'scale-125 bg-accent border-2 border-surface-panel ring-4 ring-accent/30'
              : 'bg-fg-base border-2 border-accent hover:scale-110'
          )}
          aria-label={label}
        />
      </RadixSlider.Root>
      <div className="flex justify-between text-[10px] font-mono text-fg-dimmed">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  )
}
