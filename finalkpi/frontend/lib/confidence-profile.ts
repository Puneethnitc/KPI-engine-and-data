export type ConfidenceDimension = {
  status: string
  score: number | null
  score_scale: string
  score_interpretation: string
  method: string
  inputs: Record<string, unknown>
  reasons: string[]
  limitations: string[]
  evaluated_at: string
  applicable: boolean
  blocking: boolean
  evidence_refs: string[]
}

export type AttributionConfidenceEvidenceItem = {
  id: string
  name: string
  value: unknown
  weight_contribution: number
  note?: string
  doc_ids?: string[]
}

export type AttributionConfidenceCap = {
  name: string
  max: number
  reason: string
}

export type AttributionConfidenceDriver = {
  driver_id: string
  display_name: string
  attribution_confidence: number | null
  band: string | null
  label: string | null
  prior: number | null
  evidence: AttributionConfidenceEvidenceItem[]
  caps_applied: AttributionConfidenceCap[]
  model_version: string
  calibration: { status: string; split: string | null }
  status?: string
}

export type ConfidenceProfile = {
  version: string
  evaluated_at: string
  overall: {
    status: string
    method: string
    reasons: string[]
    blocking_dimensions: string[]
    movement_conclusion: string
    explanation_conclusion: string
  }
  attribution_status: string
  attribution_confidence?: AttributionConfidenceDriver[]
  movement: ConfidenceDimension
  source: ConfidenceDimension
  attribution?: ConfidenceDimension
  driver?: ConfidenceDimension
  causal: ConfidenceDimension
}

export type ConfidenceDimensionView = {
  key: keyof Pick<ConfidenceProfile, 'movement' | 'source' | 'attribution' | 'causal'>
  title: string
  status: string
  statusLabel: string
  tone: 'good' | 'limited' | 'warning' | 'neutral'
  scoreLabel: string
  method: string
  reason: string
  limitation: string
  boundaryMessage: string | null
  details: ConfidenceDimension
}

export type AttributionConfidenceBar = {
  driverId: string
  displayName: string
  percent: number | null
  band: string | null
  bandLabel: string | null
  tone: ConfidenceDimensionView['tone']
  isUnexplained: boolean
  isInsufficientHistory: boolean
  evidence: AttributionConfidenceEvidenceItem[]
  capsApplied: AttributionConfidenceCap[]
  calibrationStatus: string
}

const dimensionTitles = {
  movement: 'Movement evidence',
  source: 'Source evidence',
  attribution: 'Attribution evidence',
  causal: 'Causal evidence',
} as const

const statusLabels: Record<string, string> = {
  HIGH: 'High evidence',
  MODERATE: 'Moderate evidence',
  LOW: 'Low evidence',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  CONFLICTING_EVIDENCE: 'Conflicting evidence',
  NOT_ASSESSED: 'Not assessed',
}

// Runs saved before a field existed (e.g. movement_conclusion) have no status;
// treat a missing status as "Not assessed" instead of crashing.
export function confidenceStatusLabel(status: string | null | undefined): string {
  if (!status) return statusLabels.NOT_ASSESSED
  return statusLabels[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function confidenceStatusTone(status: string | null | undefined): ConfidenceDimensionView['tone'] {
  if (!status) return 'neutral'
  if (status === 'HIGH') return 'good'
  if (status === 'CONFLICTING_EVIDENCE') return 'warning'
  if (status === 'NOT_ASSESSED') return 'neutral'
  return 'limited'
}

export function confidenceScoreLabel(score: number | null): string {
  return score == null ? 'Not calibrated' : String(score)
}

export function confidenceProfileUnavailableMessage(
  profile: ConfidenceProfile | null | undefined,
  verdict?: string | null,
): string | null {
  if (verdict === 'ACCESS_DENIED' || profile) return null
  return 'No confidence profile was saved for this historical run. It has not been recomputed from current data.'
}

const attributionBandTone: Record<string, AttributionConfidenceBar['tone']> = {
  HIGH: 'good',
  MODERATE: 'limited',
  LOW: 'limited',
  VERY_LOW: 'warning',
  EXPLORATORY: 'neutral',
}

export function attributionPercent(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null
  const percent = Math.max(0, Math.min(value * 100, 99.9))
  return value >= 0.995 ? Math.round(percent * 10) / 10 : Math.round(percent)
}

export function attributionConfidenceBars(
  profile: ConfidenceProfile | null | undefined,
): AttributionConfidenceBar[] {
  if (!profile) return []
  return (profile.attribution_confidence ?? []).map(driver => ({
    driverId: driver.driver_id,
    displayName: driver.driver_id === 'unexplained' ? 'Unexplained' : driver.display_name,
    percent: attributionPercent(driver.attribution_confidence),
    band: driver.band,
    bandLabel: driver.label,
    tone: driver.band ? (attributionBandTone[driver.band] ?? 'neutral') : 'neutral',
    isUnexplained: driver.driver_id === 'unexplained',
    isInsufficientHistory: driver.status === 'INSUFFICIENT_HISTORY',
    evidence: driver.evidence ?? [],
    capsApplied: driver.caps_applied ?? [],
    calibrationStatus: driver.calibration?.status ?? 'HAND_SET_PRIOR',
  } satisfies AttributionConfidenceBar))
}

export function confidenceWorkspaceModel(
  profile: ConfidenceProfile | null | undefined,
  persona: string,
  verdict?: string | null,
) {
  if (!profile || verdict === 'ACCESS_DENIED') return null
  const keys = ['movement', 'source', 'attribution', 'causal'] as const
  const dimensions = keys.flatMap(key => {
    const saved = profile[key] ?? (key === 'attribution' ? profile.driver : undefined)
    if (!saved) return []
    const details: ConfidenceDimension = {
      ...saved,
      method: saved.method ?? 'not recorded',
      reasons: saved.reasons ?? [],
      limitations: saved.limitations ?? [],
      evidence_refs: saved.evidence_refs ?? [],
    }
    return [{
      key,
      title: dimensionTitles[key],
      status: details.status,
      statusLabel: confidenceStatusLabel(details.status),
      tone: confidenceStatusTone(details.status),
      scoreLabel: confidenceScoreLabel(details.score),
      method: details.method.replaceAll('_', ' ').toLowerCase(),
      reason: details.reasons[0] ?? 'No supporting reason was recorded.',
      limitation: details.limitations[0] ?? 'No additional limitation recorded.',
      boundaryMessage: key === 'attribution'
        ? 'Attribution Confidence is a transparent evidence-weighted estimate, not yet a calibrated probability.'
        : key === 'causal' && details.status === 'NOT_ASSESSED'
          ? 'Not assessed: no approved causal design targets the top-ranked driver for this run.'
          : null,
      details,
    } satisfies ConfidenceDimensionView]
  })
  const personaFrame = persona === 'CFO'
    ? 'Decision focus: financial materiality, reconciliation, and the risk of acting on unverified evidence.'
    : 'Decision focus: operational signals, controllable diagnostic levers, and the next fact to verify.'
  return {
    overall: {
      status: profile.overall.status,
      statusLabel: confidenceStatusLabel(profile.overall.status),
      tone: confidenceStatusTone(profile.overall.status),
      reasons: profile.overall.reasons ?? [],
      blockingDimensions: profile.overall.blocking_dimensions ?? [],
      movementConclusion: {
        status: profile.overall.movement_conclusion ?? 'NOT_ASSESSED',
        statusLabel: confidenceStatusLabel(profile.overall.movement_conclusion),
        tone: confidenceStatusTone(profile.overall.movement_conclusion),
      },
      explanationConclusion: {
        status: profile.overall.explanation_conclusion ?? 'NOT_ASSESSED',
        statusLabel: confidenceStatusLabel(profile.overall.explanation_conclusion),
        tone: confidenceStatusTone(profile.overall.explanation_conclusion),
      },
    },
    attributionStatus: profile.attribution_status,
    attributionBars: attributionConfidenceBars(profile),
    personaFrame,
    dimensions,
  }
}
