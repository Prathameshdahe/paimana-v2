/**
 * src/contracts/audit.ts
 *
 * GET /api/models: the champion registry (model/registry.json) and the
 * champion run's backtest tables, model/runs/<runId>/backtest_summary.csv
 * (clause b: ML vs baselines) and ablation.csv (clause c: what each feature
 * group adds). Metric values are null where the CSV has none.
 */

/** registry.json champions entry; its keys stay as in the file (snake_case). */
export interface Champion {
  entry_id: string
  run_id: string
  model: string
  since: string
}

export type BacktestModel = 'naive' | 'rule' | 'logreg' | 'lightgbm'

interface Metrics {
  target: string
  horizon: number
  nFolds: number
  n: number
  nPos: number
  baseRate: number | null
  prAuc: number | null
  rocAuc: number | null
  brier: number | null
  ece: number | null
  precision50: number | null
  recall100: number | null
  /** quarters from the first top-100 flag to the slip it was flagged for */
  leadTimeQ: number | null
}

export interface BacktestRow extends Metrics {
  split: 'val' | 'test'
  model: BacktestModel
}

export interface AblationRow extends Metrics {
  /** 'state', '+dynamics', ... '+external' */
  step: string
  groups: string
  nFeatures: number
  model: string
  /** this step minus the step before; null on the first step */
  prAucGain: number | null
  precision50Gain: number | null
  recall100Gain: number | null
}

export interface ModelsOut {
  /** keyed by `${target}_h${horizon}`, e.g. y_any_h2 */
  champions: Record<string, Champion>
  runId: string | null
  backtest: BacktestRow[]
  ablation: AblationRow[]
}
