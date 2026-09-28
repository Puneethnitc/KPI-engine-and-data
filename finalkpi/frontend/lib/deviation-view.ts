export type DeviationView = {
  percent: number | null
  delta: number | null
  barLeft: number
  barWidth: number
  normalLeft: number | null
  normalWidth: number | null
  alertLeft: number | null
  alertWidth: number | null
}

export function deviationView(actual: number | null | undefined, expected: number | null | undefined, baselineScale?: number | null, robustScore?: number | null, alertThreshold?: number | null): DeviationView {
  const empty: DeviationView = { percent: null, delta: null, barLeft: 50, barWidth: 0, normalLeft: null, normalWidth: null, alertLeft: null, alertWidth: null }
  if (actual == null || expected == null || !Number.isFinite(actual) || !Number.isFinite(expected) || expected === 0) return empty

  const delta = actual - expected
  const percent = delta / Math.abs(expected) * 100
  // The detector uses a log ratio for positive values. Recover its baseline
  // scale from the robust score when older results omit baseline_scale.
  const recoveredScale = actual > 0 && expected > 0 && robustScore && Number.isFinite(robustScore)
    ? Math.abs(Math.log(actual / expected) / robustScore) : null
  const scale = baselineScale != null && Number.isFinite(baselineScale) && baselineScale > 0 ? baselineScale : recoveredScale
  const normalPercent = scale != null && scale > 0 ? (actual > 0 && expected > 0 ? Math.expm1(scale) * 100 : scale / Math.abs(expected) * 100) : null
  const alertPercent = normalPercent != null && alertThreshold != null && Number.isFinite(alertThreshold) && alertThreshold > 0
    ? (actual > 0 && expected > 0 ? Math.expm1(scale! * alertThreshold) * 100 : scale! * alertThreshold / Math.abs(expected) * 100) : null
  const extent = Math.max(5, Math.abs(percent) * 1.2, (alertPercent ?? 0) * 1.1)
  const position = (value: number) => 50 + Math.max(-extent, Math.min(extent, value)) / extent * 50
  const band = (limit: number | null) => limit == null ? null : { left: position(-limit), width: position(limit) - position(-limit) }
  const normal = band(normalPercent)
  const alert = band(alertPercent)
  const end = position(percent)
  return {
    percent, delta, barLeft: Math.min(50, end), barWidth: Math.abs(end - 50),
    normalLeft: normal?.left ?? null, normalWidth: normal?.width ?? null,
    alertLeft: alert?.left ?? null, alertWidth: alert?.width ?? null,
  }
}
