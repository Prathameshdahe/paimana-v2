/**
 * src/lib/riskPalette.ts
 * Single source of truth for the bright risk-tier palette — used by the
 * India map (dots + hover fill) and any chart that should read as "the
 * same visual language" as the map. Change here, changes everywhere.
 */
export const RISK_COLOR = {
  CRITICAL: '#ff4d5e',
  WARNING: '#ffb020',
  NORMAL: '#22c55e',
} as const

/** lighter tint of RISK_COLOR — for area fills / hover states */
export const RISK_FILL = {
  CRITICAL: '#ff8a94',
  WARNING: '#ffcc66',
  NORMAL: '#8ee6ab',
} as const
