/**
 * src/contracts/audit.ts
 *
 * GET /api/models: the champion registry (model/registry.json) and the
 * champion run's backtest tables, model/runs/<runId>/backtest_summary.csv
 * (clause b: ML vs baselines) and ablation.csv (clause c: what each feature
 * group adds), its SHAP summary and calibration bins, the registry history
 * and the live accuracy of logged predictions. Metric values are null where
 * the CSV has none.
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

/** shap_summary.csv of the champion run, y_any h2 only: the top 20 features by mean |SHAP| */
export interface ShapSummaryRow {
  feature: string
  group: string
  meanAbsShap: number
}

/** calibration.csv: one bin of one model's pooled validation predictions */
export interface CalibrationBin {
  target: string
  horizon: number
  model: string
  bin: number
  n: number
  meanPred: number
  obsRate: number
}

/** one registered model (pooled validation PR-AUC and ECE, test PR-AUC) */
export interface RegistryEntry {
  entryId: string
  runId: string
  model: string
  target: string
  horizon: number
  goldVersion: string
  createdAt: string | null
  prAuc: number | null
  ece: number | null
  testPrAuc: number | null
  champion: boolean
}

/** a champion / challenger decision with its reason */
export interface RegistryDecision {
  at: string
  target: string
  horizon: number
  challenger: string
  championBefore: string | null
  decision: string
  reason: string
}

/** realised outcomes of logged predictions; every metric is null until outcomes are realised */
export interface LiveAccuracy {
  nLogged: number
  nRealised: number
  firstAsof: string | null
  nCriticalHighRealised: number
  precisionCriticalHigh: number | null
  baseRate: number | null
  prAuc: number | null
  note: string
}

export interface ModelsOut {
  /** keyed by `${target}_h${horizon}`, e.g. y_any_h2 */
  champions: Record<string, Champion>
  runId: string | null
  backtest: BacktestRow[]
  ablation: AblationRow[]
  shapSummary: ShapSummaryRow[]
  calibration: CalibrationBin[]
  /** the last 100 registered entries, oldest first */
  registry: RegistryEntry[]
  /** the last 100 decisions, oldest first */
  decisions: RegistryDecision[]
  liveAccuracy: LiveAccuracy
}
