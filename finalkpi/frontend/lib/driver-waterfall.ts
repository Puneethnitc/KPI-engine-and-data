export type WaterfallInput = { label: string; value: number; offsetting?: boolean }
export type WaterfallBar = { label: string; value: number; start: number; end: number; kind: 'total' | 'up' | 'down' | 'offsetting' | 'residual' }

function precision(value: number, minimum: number): number {
  if (value === 0) return minimum
  for (let digits = minimum; digits <= 7; digits++) {
    if (Number(value.toFixed(digits)) !== 0) return digits
  }
  return 7
}

export function formatKpiValue(value: number | null | undefined, unit: string, signed = false): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const ratio = unit === 'ratio' || unit === 'orders_per_visit' || unit.endsWith('_rate')
  const scaled = ratio ? value * 100 : value
  if (scaled !== 0 && Math.abs(scaled) < 1e-7) {
    const sign = scaled < 0 ? '−' : signed ? '+' : ''
    return `${sign}${unit === 'INR' ? '₹' : ''}${Math.abs(scaled).toExponential(2)}${ratio ? signed ? ' pp' : '%' : ''}`
  }
  const digits = precision(scaled, Math.abs(scaled) < 0.1 && scaled !== 0 ? 3 : unit === 'INR' ? 2 : 1)
  const number = Math.abs(scaled).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  const sign = value < 0 ? '−' : signed && value > 0 ? '+' : ''
  return `${sign}${unit === 'INR' ? '₹' : ''}${number}${ratio ? (signed ? ' pp' : '%') : ''}`
}

export function waterfallScale(expected: number | null | undefined, actual: number | null | undefined, drivers: WaterfallInput[] | null | undefined, residual: number | null | undefined) {
  if (expected == null || actual == null || !Number.isFinite(expected) || !Number.isFinite(actual)) return null
  const bars: WaterfallBar[] = [{ label: 'Expected', value: expected, start: expected, end: expected, kind: 'total' }]
  let cursor = expected
  for (const driver of drivers ?? []) {
    if (!Number.isFinite(driver.value)) continue
    const end = cursor + driver.value
    bars.push({ label: driver.label, value: driver.value, start: cursor, end, kind: driver.offsetting ? 'offsetting' : driver.value >= 0 ? 'up' : 'down' })
    cursor = end
  }
  const remainder = residual != null && Number.isFinite(residual) ? residual : actual - cursor
  bars.push({ label: 'Unexplained', value: remainder, start: cursor, end: cursor + remainder, kind: 'residual' })
  bars.push({ label: 'Actual', value: actual, start: actual, end: actual, kind: 'total' })
  const values = [expected, actual, ...bars.flatMap(bar => [bar.start, bar.end])]
  const lowest = Math.min(...values)
  const highest = Math.max(...values)
  const spread = highest - lowest || Math.max(Math.abs(expected), 1) * 0.1
  const margin = spread * 0.18
  const min = lowest - margin
  const max = highest + margin
  const ticks = Array.from({ length: 5 }, (_, index) => min + (max - min) * index / 4)
  return { bars, min, max, ticks, reconciliationGap: actual - (cursor + remainder) }
}
