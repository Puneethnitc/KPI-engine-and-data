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

export type ConfidenceProfile = {
  version: string
  evaluated_at: string
  overall: {
    status: string
    method: string
    reasons: string[]
    blocking_dimensions: string[]
  }
  movement: ConfidenceDimension
  source: ConfidenceDimension
  driver: ConfidenceDimension
  causal: ConfidenceDimension
}

export type ConfidenceDimensionView = {
  key: keyof Pick<ConfidenceProfile, 'movement' | 'source' | 'driver' | 'causal'>
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

const dimensionTitles = {
  movement: 'Movement evidence',
  source: 'Source evidence',
  driver: 'Driver evidence',
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

export function confidenceStatusLabel(status: string): string {
  return statusLabels[status] ?? status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function confidenceStatusTone(status: string): ConfidenceDimensionView['tone'] {
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

export function confidenceWorkspaceModel(
  profile: ConfidenceProfile | null | undefined,
  persona: string,
  verdict?: string | null,
) {
  if (!profile || verdict === 'ACCESS_DENIED') return null
  const keys = ['movement', 'source', 'driver', 'causal'] as const
  const dimensions = keys.map(key => {
    const details = profile[key]
    return {
      key,
      title: dimensionTitles[key],
      status: details.status,
      statusLabel: confidenceStatusLabel(details.status),
      tone: confidenceStatusTone(details.status),
      scoreLabel: confidenceScoreLabel(details.score),
      method: details.method.replaceAll('_', ' ').toLowerCase(),
      reason: details.reasons[0] ?? 'No supporting reason was recorded.',
      limitation: details.limitations[0] ?? 'No additional limitation recorded.',
      boundaryMessage: key === 'driver'
        ? 'Association only - not a causal estimate.'
        : key === 'causal' && details.status === 'NOT_ASSESSED'
          ? 'Not assessed: no approved causal design exists for this run.'
          : null,
      details,
    } satisfies ConfidenceDimensionView
  })
  const personaFrame = persona === 'CFO'
    ? 'Decision focus: financial materiality, reconciliation, and the risk of acting on unverified evidence.'
    : 'Decision focus: operational signals, controllable diagnostic levers, and the next fact to verify.'
  return {
    overall: {
      status: profile.overall.status,
      statusLabel: confidenceStatusLabel(profile.overall.status),
      tone: confidenceStatusTone(profile.overall.status),
      reasons: profile.overall.reasons,
      blockingDimensions: profile.overall.blocking_dimensions,
    },
    personaFrame,
    dimensions,
  }
}