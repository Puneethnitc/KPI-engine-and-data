export type ShareInput = { label: string; share: number | null | undefined }
export type PieSlice = { label: string; share: number; kind: 'driver' | 'other' | 'unexplained' }
export type ContributionInput = { label: string; value: number | null | undefined }

export function percentChange(actual: number | null | undefined, expected: number | null | undefined): number | null {
  if (actual == null || expected == null || !Number.isFinite(actual) || !Number.isFinite(expected) || expected === 0) return null
  return (actual - expected) / Math.abs(expected) * 100
}

export function formatPercent(value: number, signed = true): string {
  const digits = Math.abs(value) < 10 ? 1 : 0
  const text = Math.abs(value).toFixed(digits)
  return `${value < 0 ? '−' : signed && value > 0 ? '+' : ''}${text}%`
}

export const FUNNEL_KPIS: { id: string; label: string }[] = [
  { id: 'traffic_total', label: 'Traffic' },
  { id: 'conversion_rate', label: 'Conversion' },
  { id: 'orders', label: 'Orders' },
  { id: 'units_sold', label: 'Units' },
  { id: 'net_sales_revenue', label: 'Revenue' },
]

export function kpiChangeBars(movements: Record<string, { actual_value?: number | null; expected_value?: number | null } | null | undefined>) {
  return FUNNEL_KPIS.flatMap(({ id, label }) => {
    const movement = movements[id]
    const change = movement ? percentChange(movement.actual_value, movement.expected_value) : null
    return change == null ? [] : [{ label, value: change }]
  })
}

/** Pie only when it is honest: every share >= 0 and the total is at most 100%. */
export function driverChartPlan(drivers: ShareInput[], residualShare: number | null | undefined):
  { mode: 'pie'; slices: PieSlice[] } | { mode: 'bars'; reason: string } | { mode: 'none' } {
  const known = drivers.filter(item => item.share != null && Number.isFinite(item.share)) as { label: string; share: number }[]
  if (!known.length) return { mode: 'none' }
  const residual = residualShare != null && Number.isFinite(residualShare) ? residualShare : null
  const shares = [...known.map(item => item.share), ...(residual == null ? [] : [residual])]
  const total = shares.reduce((sum, value) => sum + value, 0)
  if (shares.some(value => value < -1e-9) || total > 1 + 1e-6) {
    return { mode: 'bars', reason: 'Shown as bars because some drivers push in opposite directions' }
  }
  const slices: PieSlice[] = known.map(item => ({ label: item.label, share: item.share, kind: 'driver' }))
  const other = 1 - total
  if (other > 0.005) slices.push({ label: residual == null ? 'Other / unexplained' : 'Other drivers', share: other, kind: 'other' })
  if (residual != null && residual > 0.005) slices.push({ label: 'Unexplained', share: residual, kind: 'unexplained' })
  return { mode: 'pie', slices }
}

export function sortedContributions(items: ContributionInput[]) {
  return items
    .filter((item): item is { label: string; value: number } => item.value != null && Number.isFinite(item.value))
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
}

export function indexTo100(values: (number | null)[]): (number | null)[] {
  const base = values.find(value => value != null && Number.isFinite(value) && value !== 0)
  return values.map(value => base == null || value == null ? null : value / base * 100)
}
