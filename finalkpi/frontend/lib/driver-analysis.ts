export type RankedDriver = {
  rank: number
  driver_id: string
  display_name: string
  source_id: string
  source_grain: string
  aggregation: string
  driver_unit: string | null
  controllability: string
  relationship_type: 'ATTRIBUTION'
  direction: 'POSITIVE' | 'NEGATIVE'
  claim_type: string
  method: string
  beta: number
  beta_ci: [number | null, number | null]
  lag_days: number
  driver_change: number | null
  driver_change_z: number
  contribution: number
  contribution_interval: [number | null, number | null]
  explained_share: number | null
  p_value: number | null
  p_value_adj: number | null
  sample_size: number
  coverage_ratio: number | null
  selected_lag_days: number | null
  lag_candidates_tested: number
  tested_lags: { lag_days: number; sample_size: number; out_of_sample_r2: number | null; in_sample_r2: number | null; eligible: boolean }[]
  temporal_order: string
  temporal_order_supported: boolean | null
  direction_consistent: boolean | null
  expected_direction: string | null
  stability_status: string
  stability_details: Record<string, unknown>
  moved: boolean
  offsetting: boolean
  grain_adjusted: boolean
  collinearity_warning: boolean
  target_period_available: boolean
  limitations: string[]
  claim_boundary: string
  evidence_references: Record<string, unknown>[]
  corroboration?: Corroboration | null
  attribution_confidence?: number | null
  band?: string | null
  label?: string | null
}

export type CorroborationDocument = {
  doc_id: string
  date: string
  available_at: string
  source_type: string
  region: string
  category: string
  stance: 'supports' | 'refutes' | 'neutral'
  matched_by: 'driver_tag' | 'keyword'
  matched_terms: string[]
  snippet: string
}

export type Corroboration = {
  status: 'CORROBORATED' | 'CONTRADICTED' | 'NONE' | 'RETRIEVAL_FAILED' | string
  documents: CorroborationDocument[]
  document_count: number
  match_basis: 'driver_tag' | 'keyword' | 'none' | string
  supporting_documents: string[]
  refuting_documents: string[]
}

export type ExcludedDriver = {
  driver_id: string
  source_id: string
  reason_code: string
  reason: string
  sample_size: number
  failed_checks: string[]
  evidence_references: Record<string, unknown>[]
}

export type DriverAnalysis = {
  status: string
  method: string
  target_kpi: string
  target_period: Record<string, unknown>
  scope: Record<string, string>
  delta_kpi: number
  residual: number
  residual_share: number | null
  candidate_count: number
  ranked_count: number
  moved_count: number
  offsetting_count: number
  excluded_count: number
  hypotheses_tested: number
  correction_method: string | null
  collinearity_warning: boolean
  limitations: string[]
  ranked_drivers: RankedDriver[]
  excluded_drivers: ExcludedDriver[]
  association_diagnostics?: Record<string, unknown>
  shapley_equivalence_check?: { drivers_checked: string[]; max_abs_diff: number; passed: boolean } | null
}

const statusText: Record<string, string> = {
  ASSESSED: 'Analysis assessed',
  EXPLORATORY_NON_MATERIAL: 'Exploratory (movement not material)',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  NOT_APPLICABLE: 'No governed drivers declared',
  BLOCKED: 'Blocked by source contradiction',
}

const exclusionText: Record<string, string> = {
  INSUFFICIENT_HISTORY: 'Insufficient history for minimum sample',
  LOW_COVERAGE: 'Coverage below the required minimum',
  CONSTANT_SERIES: 'KPI or driver has no usable variation',
  BELOW_THRESHOLD: 'Association below the governed threshold',
  TEMPORAL_ORDER_FAILED: 'Temporal-order check failed',
  SOURCE_UNAVAILABLE: 'Required source or target-period observation unavailable',
  UNSTABLE_RELATIONSHIP: 'Relationship was unstable across checks',
  BLOCKED_BY_RECONCILIATION: 'Blocked by contradictory source reconciliation',
  INCOMPLETE_WEEKLY_COVERAGE: 'Weekly source coverage is incomplete',
  TARGET_LEAKAGE: 'Driver duplicates the target KPI',
  DID_NOT_MOVE: 'Driver did not move enough to explain any part of the change',
  MONTHLY_CONTEXTUAL_ONLY: 'Monthly drivers are contextual only, not attributed a contribution',
}

export function driverAnalysisStatusLabel(status: string): string {
  return statusText[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function driverExclusionLabel(reasonCode: string): string {
  return exclusionText[reasonCode] ?? reasonCode.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function driverContributionLabel(contribution: number | null, unit?: string | null): string {
  if (contribution == null) return 'Not estimated'
  return `${contribution.toFixed(2)}${unit ? ` ${unit}` : ''}`
}

export function driverExplainedShareLabel(share: number | null): string {
  return share == null ? 'Not estimated' : `${(share * 100).toFixed(0)}%`
}

export function driverCoverageLabel(coverage: number | null, sampleSize: number | null): string {
  if (coverage == null) return 'Coverage not established'
  return `${(coverage * 100).toFixed(1)}% joint-model coverage · n=${sampleSize ?? 'unknown'}`
}

export function driverTemporalLabel(order: string, supported: boolean | null): string {
  if (order === 'BEFORE' && supported === true) return 'Driver changes preceded KPI changes at the selected lag'
  if (order === 'COINCIDENT') return 'Coincident changes; temporal precedence is not supported'
  if (order === 'AFTER') return 'Driver changes followed KPI changes'
  return 'Temporal order not assessed'
}

const corroborationText: Record<string, string> = {
  CORROBORATED: 'Documents support this driver',
  CONTRADICTED: 'Documents contradict this driver',
  NONE: 'No documents found in scope',
  RETRIEVAL_FAILED: 'Evidence corpus unavailable',
}

const stanceText: Record<string, string> = {
  supports: 'Supports',
  refutes: 'Refutes',
  neutral: 'Neutral',
}

const sourceTypeText: Record<string, string> = {
  support_ticket: 'Support ticket',
  internal_note: 'Internal note',
  promo_calendar: 'Promotion calendar',
  news: 'News',
}

export function corroborationStatusLabel(status: string): string {
  return corroborationText[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function corroborationStanceLabel(stance: string): string {
  return stanceText[stance] ?? stance
}

export function corroborationSourceTypeLabel(sourceType: string): string {
  return sourceTypeText[sourceType] ?? sourceType.replaceAll('_', ' ').replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

/**
 * Stage 6-lite: build the per-driver corroboration view model.
 *
 * The status is never inferred here -- it is read from the engine, which is the
 * only place that has seen the as-of, scope and entitlement filters. A driver
 * with no corroboration block at all (an older saved run) renders as
 * "not assessed" rather than "no evidence found", because those are different
 * claims and the run predates the feature.
 */
export function corroborationViewModel(corroboration: Corroboration | null | undefined) {
  if (!corroboration) {
    return {
      assessed: false,
      statusLabel: 'Not assessed in this run',
      boundary: 'This run predates evidence corroboration, so no document was checked against this driver.',
      documents: [],
      supporting: 0,
      refuting: 0,
      tone: 'none' as const,
    }
  }
  const documents = corroboration.documents ?? []
  const supporting = documents.filter(doc => doc.stance === 'supports').length
  const refuting = documents.filter(doc => doc.stance === 'refutes').length
  return {
    assessed: true,
    statusLabel: corroborationStatusLabel(corroboration.status),
    boundary:
      corroboration.status === 'RETRIEVAL_FAILED'
        ? 'The evidence corpus could not be loaded. This is a retrieval failure, not an absence of evidence.'
        : corroboration.status === 'CORROBORATED' || corroboration.status === 'CONTRADICTED'
          ? 'These documents support or contradict the driver. They do not establish that it caused the change.'
          : 'No in-scope, entitled, published document mentioned this driver inside the evidence window.',
    documents,
    supporting,
    refuting,
    tone: corroboration.status === 'CORROBORATED'
      ? 'good' as const
      : corroboration.status === 'CONTRADICTED'
        ? 'warning' as const
        : 'limited' as const,
  }
}

export function driverAnalysisViewModel(
  analysis: DriverAnalysis | null | undefined,
  persona: string,
  verdict?: string | null,
) {
  if (!analysis || verdict === 'ACCESS_DENIED') return null
  const ranked = [...(analysis.ranked_drivers ?? [])].sort((left, right) => left.rank - right.rank || left.driver_id.localeCompare(right.driver_id))
  const explaining = ranked.filter(driver => !driver.offsetting)
  const offsetting = ranked.filter(driver => driver.offsetting)
  const excluded = [...(analysis.excluded_drivers ?? [])].sort((left, right) => left.driver_id.localeCompare(right.driver_id))
  const didNotMove = excluded.filter(item => item.reason_code === 'DID_NOT_MOVE')
  const otherExcluded = excluded.filter(item => item.reason_code !== 'DID_NOT_MOVE')
  const personaFrame = persona === 'CFO'
    ? 'Financial review: these are statistical estimates of what moved, not monetary or causal proof; check reconciliation and decision risk before acting.'
    : 'Marketing review: distinguish controllable levers from contextual signals and verify the next operational fact.'
  const notPresented = analysis.status === 'EXPLORATORY_NON_MATERIAL'
  return {
    statusLabel: driverAnalysisStatusLabel(analysis.status),
    ranked: notPresented ? [] : explaining,
    offsetting: notPresented ? [] : offsetting,
    didNotMove,
    excluded: otherExcluded,
    residual: analysis.residual,
    residualShare: analysis.residual_share,
    personaFrame,
    abstention: analysis.status === 'BLOCKED'
      ? 'Source contradiction blocks driver interpretation; no ranked driver can support downstream claims.'
      : analysis.status === 'EXPLORATORY_NON_MATERIAL'
        ? 'The movement did not pass both materiality checks; drivers are not presented as explanations.'
        : analysis.status === 'INSUFFICIENT_EVIDENCE'
          ? 'No driver met the governed history, coverage, and movement checks.'
          : analysis.status === 'NOT_APPLICABLE'
            ? 'The KPI contract declares no candidate drivers for this analysis.'
            : explaining.length === 0
              ? 'No driver explained this movement; see excluded and did-not-move candidates for the deterministic reasons.'
              : null,
  }
}
