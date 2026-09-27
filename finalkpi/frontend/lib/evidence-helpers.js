/**
 * Typed presentation helpers for the evidence workspace.
 * These are tested directly without requiring React rendering.
 */

/** Map a reconciliation status to a CSS tone class. */
export function reconciliationTone(status, blocking) {
  if (blocking) return 'warning'
  if (status === 'AGREED') return 'good'
  if (status === 'DRIFT') return 'warning'
  if (status === 'NOT_APPLICABLE') return 'neutral'
  if (status === 'NOT_AVAILABLE_FOR_PERIOD') return 'limited'
  return 'neutral'
}

/** Map a coverage_status to a CSS tone class. */
export function coverageTone(status) {
  if (status === 'FULL') return 'good'
  if (status === 'PARTIAL') return 'limited'
  if (status === 'STALE') return 'limited'
  if (status === 'EMPTY' || status === 'MISSING') return 'warning'
  if (status === 'NOT_LOADED') return 'neutral'
  return 'neutral'
}

/** Map a quality_status to a CSS tone class. */
export function qualityTone(status) {
  if (status === 'OK') return 'good'
  if (status === 'QUALITY_FAILED') return 'warning'
  return 'neutral'
}

/** Map an overall source_readiness status to a CSS tone. */
export function readinessTone(status) {
  if (status === 'READY') return 'good'
  if (status === 'PARTIAL' || status === 'STALE') return 'limited'
  if (status === 'MISSING' || status === 'QUALITY_FAILED') return 'warning'
  return 'neutral'
}

/**
 * Format a nullable value for display. Null/undefined → '—'.
 * @param {any} value
 * @param {(v: any) => string} [formatter]
 * @returns {string}
 */
export function renderNullable(value, formatter) {
  if (value === null || value === undefined) return '—'
  return formatter ? formatter(value) : String(value)
}

/**
 * Returns true if the file_identifier represents a governed demo fixture.
 * Fixture identifiers start with 'demo_fixtures/'.
 */
export function isFixtureIdentifier(fileIdentifier) {
  return typeof fileIdentifier === 'string' && fileIdentifier.startsWith('demo_fixtures/')
}

/**
 * Returns a display label for a file_identifier:
 * - fixture → 'Fixture: demo_fixtures/...'
 * - production → just the filename
 * - null → '—'
 */
export function fileIdentifierLabel(fileIdentifier) {
  if (!fileIdentifier) return '—'
  if (isFixtureIdentifier(fileIdentifier)) return `Fixture: ${fileIdentifier}`
  return fileIdentifier
}

/**
 * For an access-denied evidence response, returns true so the workspace is suppressed.
 */
export function evidenceSuppressedForDenied(run) {
  return run?.verdict === 'ACCESS_DENIED'
}

/**
 * Determine the source rows that should be rendered from an evidence payload.
 * Returns [] for ACCESS_DENIED verdicts (no data leak).
 */
export function sourcesForDisplay(evidence, run) {
  if (!evidence || evidenceSuppressedForDenied(run)) return []
  return evidence.sources ?? []
}
