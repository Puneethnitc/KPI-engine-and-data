import type { RankedDriver, ExcludedDriver, DriverAnalysis } from './driver-analysis'
import type { ConfidenceProfile, AttributionConfidenceDriver } from './confidence-profile'

export function exclusionReason(code: string | null | undefined): string {
  const known: Record<string, string> = {
    DID_NOT_MOVE: "Didn't change enough on this date",
    SOURCE_UNAVAILABLE: "Data for this date isn't published yet",
    BELOW_THRESHOLD: 'Too weak a relationship',
    INSUFFICIENT_HISTORY: 'Not enough history',
  }
  if (!code) return 'Reason not saved for this older run'
  return known[code] ?? code.replaceAll('_', ' ').toLowerCase().replace(/^./, letter => letter.toUpperCase())
}

export function driverRows(analysis: DriverAnalysis | null | undefined, profile: ConfidenceProfile | null | undefined) {
  const confidence = new Map<string, AttributionConfidenceDriver>((profile?.attribution_confidence ?? []).map(item => [item.driver_id, item]))
  const association = new Map<string, number>()
  const diagnostics = analysis?.association_diagnostics as { ranked_drivers?: { driver_id: string; raw_correlation?: number }[] } | undefined
  for (const item of diagnostics?.ranked_drivers ?? []) {
    if (typeof item.raw_correlation === 'number') association.set(item.driver_id, item.raw_correlation)
  }
  const ranked = (analysis?.ranked_drivers ?? []).map((driver: RankedDriver) => ({
    kind: 'ranked' as const, driver, confidence: confidence.get(driver.driver_id), correlation: association.get(driver.driver_id),
  }))
  const main = [...ranked].sort((a, b) =>
    (b.confidence?.attribution_confidence ?? b.driver.attribution_confidence ?? -1) -
    (a.confidence?.attribution_confidence ?? a.driver.attribution_confidence ?? -1))[0]
  const confidentMain = main && (main.confidence?.attribution_confidence ?? main.driver.attribution_confidence ?? 0) >= 0.35 ? main : null
  const ordered = [
    ...(confidentMain ? [confidentMain] : []),
    ...ranked.filter(item => item !== confidentMain && !item.driver.offsetting).sort((a, b) => a.driver.rank - b.driver.rank),
    ...ranked.filter(item => item.driver.offsetting).sort((a, b) => a.driver.rank - b.driver.rank),
  ]
  const excluded = (analysis?.excluded_drivers ?? []).map((driver: ExcludedDriver) => ({ kind: 'excluded' as const, driver, confidence: confidence.get(driver.driver_id), correlation: association.get(driver.driver_id) }))
  return { rows: [...ordered, ...excluded], main: confidentMain }
}
