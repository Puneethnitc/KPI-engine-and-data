export type RankedDriver = {
  rank: number
  driver_id: string
  display_name: string
  source_id: string
  source_grain: string
  aggregation: string
  driver_unit: string | null
  controllability: string
  relationship_type: 'ASSOCIATION'
  direction: 'POSITIVE' | 'NEGATIVE'
  score: number | null
  score_name: string
  score_scale: string
  score_components: Record<string, unknown>
  raw_correlation: number | null
  adjusted_significance: number | null
  sample_size: number
  missing_observations: number | null
  coverage_ratio: number | null
  selected_lag_days: number | null
  lag_candidates_tested: number
  tested_lags: { lag_days: number; sample_size: number; correlation: number | null; eligible: boolean }[]
  temporal_order: string
  temporal_order_supported: boolean | null
  stability_status: string
  stability_details: Record<string, unknown>
  seasonality_control: string
  trend_control: string
  eligibility_checks: Record<string, unknown>
  evidence_references: Record<string, unknown>[]
  limitations: string[]
  claim_boundary: string
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
  candidate_count: number
  eligible_count: number
  ranked_count: number
  excluded_count: number
  hypotheses_tested: number
  windows_tested: number
  correction_method: string | null
  limitations: string[]
  ranked_drivers: RankedDriver[]
  excluded_drivers: ExcludedDriver[]
}

const statusText: Record<string, string> = {
  ASSESSED: 'Analysis assessed',
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
}

export function driverAnalysisStatusLabel(status: string): string {
  return statusText[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function driverExclusionLabel(reasonCode: string): string {
  return exclusionText[reasonCode] ?? reasonCode.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function driverScoreLabel(score: number | null): string {
  return score == null ? 'Not scored' : `${score.toFixed(3)} / 1 ranking index`
}

export function driverCorrelationLabel(correlation: number | null): string {
  return correlation == null ? 'Not estimated' : correlation.toFixed(3)
}

export function driverCoverageLabel(coverage: number | null, missing: number | null): string {
  if (coverage == null) return 'Coverage not established'
  return `${(coverage * 100).toFixed(1)}% paired coverage · ${missing ?? 'unknown'} missing observations`
}

export function driverTemporalLabel(order: string, supported: boolean | null): string {
  if (order === 'BEFORE' && supported === true) return 'Driver changes preceded KPI changes at the selected lag'
  if (order === 'COINCIDENT') return 'Coincident changes; temporal precedence is not supported'
  if (order === 'AFTER') return 'Driver changes followed KPI changes'
  return 'Temporal order not assessed'
}

export function driverAnalysisViewModel(
  analysis: DriverAnalysis | null | undefined,
  persona: string,
  verdict?: string | null,
) {
  if (!analysis || verdict === 'ACCESS_DENIED') return null
  const ranked = [...analysis.ranked_drivers].sort((left, right) => left.rank - right.rank || left.driver_id.localeCompare(right.driver_id))
  const personaFrame = persona === 'CFO'
    ? 'Financial review: use these as non-monetary diagnostic signals; check reconciliation and decision risk before acting.'
    : 'Marketing review: distinguish controllable levers from contextual signals and verify the next operational fact.'
  return {
    statusLabel: driverAnalysisStatusLabel(analysis.status),
    ranked,
    excluded: [...analysis.excluded_drivers].sort((left, right) => left.driver_id.localeCompare(right.driver_id)),
    personaFrame,
    abstention: analysis.status === 'BLOCKED'
      ? 'Source contradiction blocks driver interpretation; no ranked driver can support downstream claims.'
      : analysis.status === 'INSUFFICIENT_EVIDENCE'
        ? 'No driver met the governed history, coverage, and association checks.'
        : analysis.status === 'NOT_APPLICABLE'
          ? 'The KPI contract declares no candidate drivers for this analysis.'
          : ranked.length === 0
            ? 'No eligible driver was ranked; see excluded candidates for the deterministic reasons.'
            : null,
  }
}
