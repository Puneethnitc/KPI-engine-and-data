export type TimeseriesPoint = {
  observation_date: string
  actual: number | null
  expected: number | null
  lower: number | null
  upper: number | null
  delta: number | null
  material_event: boolean
  baseline_count: number
  source_available_at?: string
}

export type TimeseriesResponse = {
  kpi_id: string
  region: string
  category: string
  points: TimeseriesPoint[]
  source: string
  method: string
  data_version: string
  start_date: string | null
  end_date: string | null
}

export type PointCoord = {
  pt: TimeseriesPoint
  x: number
  yActual: number | null
  yExpected: number | null
}

export function formatValue(value: number | null | undefined, unit: string): string {
  if (value == null || !Number.isFinite(value)) return 'No observation'
  const isRatio = unit === 'ratio' || unit === 'orders_per_visit' || unit.endsWith('_rate')
  if (isRatio) return `${(value * 100).toFixed(2)}%`
  if (unit === 'INR') return `₹${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

export function formatDelta(value: number | null | undefined, unit: string): string {
  if (value == null || !Number.isFinite(value)) return 'No observation'
  const isRatio = unit === 'ratio' || unit === 'orders_per_visit' || unit.endsWith('_rate')
  const scaled = isRatio ? value * 100 : value
  const amount = Math.abs(scaled).toLocaleString('en-IN', { maximumFractionDigits: 2 })
  return `${scaled < 0 ? '−' : '+'}${unit === 'INR' ? '₹' : ''}${amount}${isRatio ? ' pp' : ''}`
}

export function formatDateLabel(isoDate: string): string {
  if (!isoDate) return ''
  const parts = isoDate.split('-')
  if (parts.length < 3) return isoDate
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const monthIdx = parseInt(parts[1], 10) - 1
  return `${monthNames[monthIdx] ?? parts[1]} ${parseInt(parts[2], 10)}`
}

/**
 * Split coordinates into contiguous non-null segments to prevent visually bridging missing data points.
 */
export function buildContiguousSegments(
  points: PointCoord[],
  key: 'yActual' | 'yExpected'
): PointCoord[][] {
  const segments: PointCoord[][] = []
  let currentSegment: PointCoord[] = []

  for (const pt of points) {
    if (pt[key] != null) {
      currentSegment.push(pt)
    } else {
      if (currentSegment.length > 0) {
        segments.push(currentSegment)
        currentSegment = []
      }
    }
  }
  if (currentSegment.length > 0) {
    segments.push(currentSegment)
  }

  return segments
}

/**
 * Build SVG path string for a contiguous array of points.
 */
export function segmentToSvgPath(segment: PointCoord[], key: 'yActual' | 'yExpected'): string {
  if (segment.length < 2) return ''
  return segment
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p[key]!.toFixed(1)}`)
    .join(' ')
}
