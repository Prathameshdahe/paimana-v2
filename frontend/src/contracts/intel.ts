/**
 * src/contracts/intel.ts
 *
 * Cross-project intelligence as served by the FastAPI backend (backend/schemas.py;
 * keys are camelCase): the Agency Performance Matrix (GET /api/agencies/matrix).
 */

/**
 * One canonical agency (printed names merged, gold/agency_map.csv). Biases are ratios
 * (0.56 = 56% longer / costlier than first planned). scheduleBias / costBias are shrunk
 * toward the sector median when n < 10; the *Raw ones are not; the CIs are bootstrap
 * 90% intervals of the raw median.
 */
export interface AgencyPoint {
  agency: string
  /** every printed name merged into this agency, " | " separated */
  names: string | null
  sector: string | null
  ministry: string | null
  nProjects: number
  nOpen: number
  capitalCr: number
  scheduleBias: number | null
  scheduleBiasRaw: number | null
  scheduleBiasQ25: number | null
  scheduleBiasQ75: number | null
  scheduleBiasCiLo: number | null
  scheduleBiasCiHi: number | null
  costBias: number | null
  costBiasRaw: number | null
  costBiasQ25: number | null
  costBiasQ75: number | null
  costBiasCiLo: number | null
  costBiasCiHi: number | null
  nCost: number
  sectorScheduleBias: number | null
  sectorCostBias: number | null
  /** n / (n + 10); 1 when not shrunk */
  shrinkWeight: number | null
  shrunk: boolean
  /** n < 5: left out unless include_hidden */
  hidden: boolean
  /** median schedule bias of projects sanctioned in the last 3 years minus earlier ones */
  trend: number | null
  nRecent: number
}

export interface AgencyMatrix {
  asof: string
  nAgencies: number
  nHidden: number
  method: string
  points: AgencyPoint[]
}
