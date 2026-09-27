export type ReviewState = 'UNREVIEWED' | 'AWAITING_REVIEW' | 'PENDING_REVIEW' | 'ACCEPTED' | 'REJECTED' | 'OTHER'

const reviewLabels: Record<ReviewState, string> = {
  UNREVIEWED: 'Not reviewed',
  AWAITING_REVIEW: 'Awaiting review',
  PENDING_REVIEW: 'Awaiting review',
  ACCEPTED: 'Accepted',
  REJECTED: 'Rejected',
  OTHER: 'Other status',
}

const pendingReviewStates = new Set<ReviewState>(['UNREVIEWED', 'AWAITING_REVIEW', 'PENDING_REVIEW'])
const sourceWarningStates = new Set(['DRIFT', 'CONTRADICTED', 'PARTIAL', 'STALE', 'UNAVAILABLE_OR_MISSING', 'MISSING_REPORT'])
const technicalLabels: Record<string, string> = {
  NOT_APPLICABLE: 'No independent comparison configured',
  NOT_AVAILABLE_FOR_PERIOD: 'Independent comparison unavailable for this period',
  AGREED: 'Source totals agreed',
  DRIFT: 'Source totals drift',
  NOT_RECONCILED: 'Independent comparison unavailable',
  CONTRADICTED: 'Conflicting source evidence',
  UNTESTABLE: 'Cannot be causally tested with available data',
  NO_DESIGN: 'No valid causal comparison design',
  ACCESS_DENIED: 'Access denied',
  MATERIAL_CAUSE_UNVERIFIED: 'Material movement; cause unverified',
  NO_MATERIAL_MOVEMENT: 'No material movement',
  SEASONAL_REVIEW: 'Seasonal review; no cause diagnosed',
  ABSTAIN: 'Engine abstained from attribution',
  INSUFFICIENT_HISTORY: 'Insufficient history',
  AWAITING_REVIEW: 'Awaiting review',
  PENDING_REVIEW: 'Awaiting review',
  UNREVIEWED: 'Not reviewed',
  growth_lead: 'Growth lead',
  analyst: 'Analyst',
  marketing_lead: 'Marketing lead',
  operations_lead: 'Operations lead',
}

export function normalizeReviewState(value?: string | null): ReviewState {
  const normalized = (value ?? '').toUpperCase()
  if (normalized === 'APPROVED') return 'ACCEPTED'
  if (normalized === 'OPEN') return 'UNREVIEWED'
  if (normalized === 'PENDING') return 'PENDING_REVIEW'
  if (normalized === 'UNREVIEWED' || normalized === 'AWAITING_REVIEW' || normalized === 'PENDING_REVIEW' || normalized === 'ACCEPTED' || normalized === 'REJECTED') return normalized
  return 'OTHER'
}

export function reviewStateLabel(value?: string | null): string {
  return reviewLabels[normalizeReviewState(value)]
}

export function isReviewPending(value?: string | null): boolean {
  return pendingReviewStates.has(normalizeReviewState(value))
}

export function isAwaitingReview(value?: string | null): boolean {
  const state = normalizeReviewState(value)
  return state === 'AWAITING_REVIEW' || state === 'PENDING_REVIEW'
}

export function isSourceWarning(value?: string | null): boolean {
  return sourceWarningStates.has((value ?? '').toUpperCase())
}

export function statusLabel(value?: string | null): string {
  if (!value) return 'Not assessed'
  return technicalLabels[value] ?? technicalLabels[value.toUpperCase()] ??
    value.toLowerCase().replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase())
}

export function movementStatusLabel(status?: string | null): string {
  if (!status) return 'Not assessed'
  const labels: Record<string, string> = {
    CONFIRMED_BOTH: 'Confirmed by robust & seasonal detectors',
    ROBUST_ONLY: 'Confirmed by robust detector',
    SEASONAL_REVIEW: 'Seasonal forecast flag (review required)',
    NOT_MATERIAL: 'Below materiality threshold',
    INSUFFICIENT: 'Insufficient history',
    UNAUTHORIZED: 'Scope access not authorized',
  }
  return labels[status.toUpperCase()] ?? statusLabel(status)
}

export function sourceStatusLabel(status?: string | null): string {
  if (!status) return 'Not assessed'
  const labels: Record<string, string> = {
    READY: 'Governed sources aligned & ready',
    LIMITED: 'Comparison unavailable for period',
    DRIFT: 'Source totals drift beyond tolerance',
    CONTRADICTED: 'Conflicting source evidence',
    QUALITY_FAILED: 'Data quality validation failed',
  }
  return labels[status.toUpperCase()] ?? statusLabel(status)
}

export function driverStatusLabel(status?: string | null): string {
  if (!status) return 'Not assessed'
  const labels: Record<string, string> = {
    CANDIDATES_FOUND: 'Correlational candidates identified',
    NO_CANDIDATE_PASSED: 'No candidate passed correlation threshold',
    INSUFFICIENT_DATA: 'Insufficient candidate driver data',
  }
  return labels[status.toUpperCase()] ?? statusLabel(status)
}

export function causalStatusLabel(status?: string | null): string {
  if (!status) return 'Not assessed — no approved comparison design'
  const labels: Record<string, string> = {
    NOT_ASSESSED: 'Not assessed — no approved comparison design',
    INCONCLUSIVE: 'Observational verification inconclusive',
    CONDITIONAL_SUPPORT: 'Conditionally supported by DiD check',
    CONFLICTING: 'Observational check rejected',
    INSUFFICIENT: 'Insufficient data for causal design',
  }
  return labels[status.toUpperCase()] ?? statusLabel(status)
}

export function contextHref(path: string, context: { persona: string; region: string; category: string; date: string; scenario?: string }, extra: Record<string, string | undefined> = {}): string {
  const params = new URLSearchParams({ persona: context.persona, region: context.region, category: context.category, date: context.date })
  if (context.scenario) params.set('scenario', context.scenario)
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined) params.set(key, value)
  }
  return `${path}?${params.toString()}`
}
