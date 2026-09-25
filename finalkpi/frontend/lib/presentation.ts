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
const sourceWarningStates = new Set(['NOT_RECONCILED', 'CONTRADICTED', 'PARTIAL', 'STALE', 'UNAVAILABLE_OR_MISSING', 'MISSING_REPORT'])
const technicalLabels: Record<string, string> = {
  NOT_RECONCILED: 'Source totals not reconciled',
  CONTRADICTED: 'Conflicting source evidence',
  UNTESTABLE: 'Cannot be causally tested with available data',
  NO_DESIGN: 'No valid causal comparison design',
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
  return technicalLabels[value] ?? technicalLabels[value.toUpperCase()] ?? value.toLowerCase().replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase())
}

export function contextHref(path: string, context: { persona: string; region: string; category: string; date: string }, extra: Record<string, string | undefined> = {}): string {
  const params = new URLSearchParams({ persona: context.persona, region: context.region, category: context.category, date: context.date })
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined) params.set(key, value)
  }
  return `${path}?${params.toString()}`
}
