/**
 * src/lib/formatters.ts
 *
 * Shared formatting utilities for PAIMANA.
 * All currency, date, percentage, and score formatting MUST go through these
 * functions. Avoid calling .toLocaleString() directly in JSX.
 */

import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

// ── Currency: Indian Numbering System ────────────────────────────────────────

/**
 * Formats a value in ₹ Crore using the Indian numbering system.
 * Indian grouping: last 3 digits, then groups of 2 from right.
 *
 * Examples:
 *   formatINR(12482)   → "₹12,482 Cr"
 *   formatINR(371300)  → "₹3,71,300 Cr"
 *   formatINR(3713000) → "₹37,13,000 Cr"
 */
export function formatINR(valueCr: number): string {
  const absValue = Math.abs(Math.round(valueCr))
  const str = absValue.toString()
  const sign = valueCr < 0 ? '-' : ''

  if (str.length <= 3) {
    return `${sign}₹${str} Cr`
  }

  const last3 = str.slice(-3)
  const remaining = str.slice(0, -3)
  const groups: string[] = []

  let i = remaining.length
  while (i > 0) {
    const start = Math.max(0, i - 2)
    groups.unshift(remaining.slice(start, i))
    i = start
  }

  return `${sign}₹${[...groups, last3].join(',')} Cr`
}

/**
 * Compact format for large portfolio-level figures.
 * Examples:
 *   formatINRShort(3713000) → "₹37.13L Cr"
 *   formatINRShort(42780)   → "₹42,780 Cr"  (falls back to formatINR below 1L)
 */
export function formatINRShort(valueCr: number): string {
  const abs = Math.abs(valueCr)
  const sign = valueCr < 0 ? '-' : ''

  if (abs >= 100_000) {
    return `${sign}₹${(abs / 100_000).toFixed(2)}L Cr`
  }
  if (abs >= 1_000) {
    return `${sign}₹${(abs / 1_000).toFixed(2)}K Cr`
  }
  return formatINR(valueCr)
}

/**
 * Delta format — shows sign explicitly for comparative contexts.
 * Examples:
 *   formatINRDelta(+1840)  → "+₹1,840 Cr"
 *   formatINRDelta(-320)   → "-₹320 Cr"
 */
export function formatINRDelta(valueCr: number): string {
  const sign = valueCr >= 0 ? '+' : ''
  return `${sign}${formatINR(valueCr)}`
}

// ── Dates ─────────────────────────────────────────────────────────────────────

/**
 * Formats an ISO 8601 date string to short month-year display.
 * Example: "2027-03-31" → "Mar 2027"
 */
export function formatDate(isoDate: string): string {
  const date = new Date(isoDate)
  return date.toLocaleDateString('en-IN', {
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Formats a date range as "start → end".
 * Example: "2022-06-30", "2027-09-30" → "Jun 2022 → Sep 2027"
 */
export function formatDateRange(startIso: string, endIso: string): string {
  return `${formatDate(startIso)} → ${formatDate(endIso)}`
}

// ── Duration ──────────────────────────────────────────────────────────────────

/**
 * Formats a month count with singular/plural handling.
 * Examples:
 *   formatMonths(1)  → "1 month"
 *   formatMonths(18) → "18 months"
 */
export function formatMonths(months: number): string {
  const rounded = Math.round(months)
  return `${rounded} ${rounded === 1 ? 'month' : 'months'}`
}

/**
 * Formats months with sign for delta contexts.
 * Examples:
 *   formatMonthsDelta(+6)  → "+6 months recovered"
 *   formatMonthsDelta(-3)  → "-3 months added"
 */
export function formatMonthsDelta(months: number): string {
  const sign = months >= 0 ? '+' : ''
  return `${sign}${formatMonths(Math.abs(months))} ${months >= 0 ? 'recovered' : 'added'}`
}

/**
 * Formats runway days remaining before Point of No Return.
 * Examples:
 *   formatRunwayDays(8)    → "8d"
 *   formatRunwayDays(45)   → "45d"
 *   formatRunwayDays(0)    → "Expired"
 *   formatRunwayDays(-10)  → "Expired"
 */
export function formatRunwayDays(days: number): string {
  if (days <= 0) return 'Expired'
  return `${days}d`
}

// ── Percentages ───────────────────────────────────────────────────────────────

/**
 * Formats a number as a percentage with configurable decimal places.
 * Examples:
 *   formatPct(34.18)     → "34.2%"
 *   formatPct(34.18, 0)  → "34%"
 *   formatPct(-8.5)      → "-8.5%"
 */
export function formatPct(value: number, decimals = 1): string {
  return `${value.toFixed(decimals)}%`
}

/**
 * Formats a percentage delta with explicit sign.
 * Examples:
 *   formatPctDelta(+12.4)  → "+12.4%"
 *   formatPctDelta(-5.0)   → "-5.0%"
 */
export function formatPctDelta(value: number, decimals = 1): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${formatPct(value, decimals)}`
}

// ── Risk Score ────────────────────────────────────────────────────────────────

/**
 * Formats a composite risk score for display.
 * Example: formatRiskScore(87) → "87 / 100"
 */
export function formatRiskScore(score: number): string {
  return `${Math.round(score)} / 100`
}

// ── Tailwind Utility ──────────────────────────────────────────────────────────

/**
 * Merges Tailwind CSS classes safely using clsx + tailwind-merge.
 * Prevents duplicate/conflicting class strings.
 * Named `cn` by convention — use everywhere instead of string concatenation.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
