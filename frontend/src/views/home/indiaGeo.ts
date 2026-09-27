/** State boundaries and name matching shared by the India maps (Home, Radar). */

export const GEO_URL = '/india-states-simplified.geojson'

export const MAP_CENTER: [number, number] = [83, 21]

/**
 * One key for both spellings: our data uses modern names ("Jammu & Kashmir",
 * "Odisha"), the boundary file pre-2011 GADM ones ("Jammu and Kashmir",
 * "Orissa"). The file predates Telangana and Ladakh, so those two (and the
 * non-geographic Multi-State / PAN India / Offshore buckets) are listed under
 * the map instead of drawn on it.
 */
export function normStateKey(name: string): string {
  const n = name.trim().toLowerCase().replace(/&/g, 'and').replace(/\s+islands$/, '')
  const alias: Record<string, string> = {
    orissa: 'odisha',
    uttaranchal: 'uttarakhand',
    'dadra and nagar haveli': 'dadra and nagar haveli and daman and diu',
    'daman and diu': 'dadra and nagar haveli and daman and diu',
  }
  return alias[n] ?? n
}

/** data values the boundary file has no polygon for */
export const OFF_MAP = new Set(['multi-state', 'pan india', 'offshore', 'telangana', 'ladakh'])
