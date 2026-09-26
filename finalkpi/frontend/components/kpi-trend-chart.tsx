'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Calendar, RefreshCw, ShieldAlert } from 'lucide-react'
import {
  buildContiguousSegments,
  formatDateLabel,
  formatDelta,
  formatValue,
  PointCoord,
  segmentToSvgPath,
  TimeseriesPoint,
  TimeseriesResponse,
} from './trend-chart-utils'
import { TrendChartControls } from './TrendChartControls'
import { TrendChartMetadata } from './TrendChartMetadata'

export type KpiTrendChartProps = {
  apiBase: string
  kpiId: string
  kpiLabel: string
  unit: string
  region: string
  category: string
  targetDate: string
  userId: string
}

export function KpiTrendChart({
  apiBase,
  kpiId,
  kpiLabel,
  unit,
  region,
  category,
  targetDate,
  userId,
}: KpiTrendChartProps) {
  const [data, setData] = useState<TimeseriesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isAccessDenied, setIsAccessDenied] = useState(false)

  // Zoom & Pan Range state (indices into points array)
  const [rangeStart, setRangeStart] = useState<number>(0)
  const [rangeEnd, setRangeEnd] = useState<number>(0)
  const [hoveredPoint, setHoveredPoint] = useState<TimeseriesPoint | null>(null)
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null)

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const [chartWidth, setChartWidth] = useState<number>(650)

  // Fetch real timeseries from backend with persona userId
  useEffect(() => {
    let isMounted = true
    setLoading(true)
    setError(null)
    setIsAccessDenied(false)

    const url = `${apiBase}/api/kpis/${encodeURIComponent(kpiId)}/timeseries?region=${encodeURIComponent(region)}&category=${encodeURIComponent(category)}&end_date=${encodeURIComponent(targetDate)}&user_id=${encodeURIComponent(userId)}`

    fetch(url, { cache: 'no-store' })
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          if (res.status === 403 || res.status === 401) {
            setIsAccessDenied(true)
            throw new Error(body.detail ?? `Access Denied: Identity "${userId}" is unauthorized for scope ${region} / ${category}.`)
          }
          throw new Error(body.detail ?? `Time-series endpoint returned HTTP status ${res.status}`)
        }
        return res.json()
      })
      .then((payload: TimeseriesResponse) => {
        if (!isMounted) return
        setData(payload)
        const pts = payload.points || []

        // Requirement 2: Open chart at the latest 90 days by default
        const total = pts.length
        const defaultStart = Math.max(0, total - 90)
        setRangeStart(defaultStart)
        setRangeEnd(Math.max(0, total - 1))
      })
      .catch(err => {
        if (!isMounted) return
        setError(err instanceof Error ? err.message : 'Could not fetch time-series history')
      })
      .finally(() => {
        if (isMounted) setLoading(false)
      })

    return () => {
      isMounted = false
    }
  }, [apiBase, kpiId, region, category, targetDate, userId])

  // ResizeObserver for responsive SVG width
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          setChartWidth(entry.contentRect.width)
        }
      }
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  const rawPoints = data?.points || []
  const visiblePoints = useMemo(() => {
    if (!rawPoints.length) return []
    const start = Math.max(0, Math.min(rangeStart, rawPoints.length - 1))
    const end = Math.max(start, Math.min(rangeEnd, rawPoints.length - 1))
    return rawPoints.slice(start, end + 1)
  }, [rawPoints, rangeStart, rangeEnd])

  // Zoom Actions
  function handleZoomIn() {
    if (!rawPoints.length) return
    const currentLen = rangeEnd - rangeStart + 1
    if (currentLen <= 7) return
    const delta = Math.floor(currentLen * 0.2)
    setRangeStart(prev => Math.min(prev + Math.floor(delta / 2), rangeEnd - 6))
    setRangeEnd(prev => Math.max(prev - Math.ceil(delta / 2), rangeStart + 6))
  }

  function handleZoomOut() {
    if (!rawPoints.length) return
    const currentLen = rangeEnd - rangeStart + 1
    const delta = Math.max(4, Math.floor(currentLen * 0.25))
    setRangeStart(prev => Math.max(0, prev - Math.floor(delta / 2)))
    setRangeEnd(prev => Math.min(rawPoints.length - 1, prev + Math.ceil(delta / 2)))
  }

  // Requirement 2: Reset returns to default 90-day range
  function handleResetZoom() {
    if (!rawPoints.length) return
    const total = rawPoints.length
    const defaultStart = Math.max(0, total - 90)
    setRangeStart(defaultStart)
    setRangeEnd(Math.max(0, total - 1))
  }

  function handlePreset(days: number) {
    if (!rawPoints.length) return
    const endIdx = rawPoints.length - 1
    const startIdx = Math.max(0, endIdx - days + 1)
    setRangeStart(startIdx)
    setRangeEnd(endIdx)
  }

  // Chart Geometry Calculations
  const padding = { top: 24, right: 24, bottom: 44, left: 60 }
  const height = 280
  const innerWidth = Math.max(200, chartWidth - padding.left - padding.right)
  const innerHeight = height - padding.top - padding.bottom

  const { minY, maxY, pointsWithCoords } = useMemo(() => {
    if (!visiblePoints.length) {
      return { minY: 0, maxY: 100, pointsWithCoords: [] as PointCoord[] }
    }

    let min = Infinity
    let max = -Infinity

    for (const pt of visiblePoints) {
      if (pt.actual != null && Number.isFinite(pt.actual)) {
        min = Math.min(min, pt.actual)
        max = Math.max(max, pt.actual)
      }
      if (pt.expected != null && Number.isFinite(pt.expected)) {
        min = Math.min(min, pt.expected)
        max = Math.max(max, pt.expected)
      }
    }

    if (min === Infinity || max === -Infinity) {
      min = 0; max = 100
    } else if (min === max) {
      min = min * 0.9
      max = max * 1.1 || 100
    } else {
      const margin = (max - min) * 0.08
      min = Math.max(0, min - margin)
      max = max + margin
    }

    const len = visiblePoints.length
    const pointsWithCoords: PointCoord[] = visiblePoints.map((pt, idx) => {
      const x = len === 1 ? innerWidth / 2 : (idx / (len - 1)) * innerWidth
      const yActual = pt.actual != null ? innerHeight - ((pt.actual - min) / (max - min)) * innerHeight : null
      const yExpected = pt.expected != null ? innerHeight - ((pt.expected - min) / (max - min)) * innerHeight : null
      return { pt, x, yActual, yExpected }
    })

    return { minY: min, maxY: max, pointsWithCoords }
  }, [visiblePoints, innerWidth, innerHeight])

  // Requirement 4: Split SVG paths into contiguous segments to prevent visually bridging nulls
  const actualSegments = useMemo(() => {
    return buildContiguousSegments(pointsWithCoords, 'yActual')
  }, [pointsWithCoords])

  const expectedSegments = useMemo(() => {
    return buildContiguousSegments(pointsWithCoords, 'yExpected')
  }, [pointsWithCoords])

  // Y-Axis Ticks
  const yTicks = useMemo(() => {
    const ticksCount = 5
    const step = (maxY - minY) / (ticksCount - 1)
    return Array.from({ length: ticksCount }).map((_, i) => {
      const val = minY + i * step
      const y = innerHeight - (i / (ticksCount - 1)) * innerHeight
      return { val, y }
    })
  }, [minY, maxY, innerHeight])

  // X-Axis Ticks (up to 6 readable date labels)
  const xTicks = useMemo(() => {
    if (!visiblePoints.length) return []
    const count = Math.min(6, visiblePoints.length)
    const step = (visiblePoints.length - 1) / Math.max(1, count - 1)
    const result = []
    for (let i = 0; i < count; i++) {
      const idx = Math.round(i * step)
      const pt = visiblePoints[idx]
      if (pt) {
        const x = visiblePoints.length === 1 ? innerWidth / 2 : (idx / (visiblePoints.length - 1)) * innerWidth
        result.push({ date: pt.observation_date, label: formatDateLabel(pt.observation_date), x })
      }
    }
    return result
  }, [visiblePoints, innerWidth])

  if (loading) {
    return (
      <div
        className="card"
        style={{
          padding: '24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '260px',
          color: 'var(--muted)',
          gap: '10px',
          fontSize: '13px',
        }}
      >
        <RefreshCw size={16} className="spin" />
        <span>Loading governed KPI historical trend series for {userId}…</span>
      </div>
    )
  }

  // Requirement 1: Access Denied State (no silent fallback)
  if (isAccessDenied || error) {
    return (
      <div
        className="card"
        style={{
          padding: '28px',
          textAlign: 'center',
          color: isAccessDenied ? 'var(--red)' : 'var(--muted)',
          minHeight: '220px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          border: isAccessDenied ? '1px solid color-mix(in srgb, var(--red) 45%, var(--line))' : '1px solid var(--line)',
        }}
      >
        {isAccessDenied ? <ShieldAlert size={28} style={{ color: 'var(--red)' }} /> : <Calendar size={28} style={{ color: 'var(--faint)' }} />}
        <strong style={{ color: 'var(--text)', fontSize: '14px' }}>
          {isAccessDenied ? 'Access Denied: Scope Unauthorized' : 'Insufficient Historical Trend Data'}
        </strong>
        <p style={{ fontSize: '12px', margin: 0, maxWidth: '440px' }}>
          {error || 'The backend returned no historical daily data points for the selected scope.'}
        </p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="card trend-chart-card"
      style={{
        padding: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
        position: 'relative',
        width: '100%',
      }}
    >
      {/* Header & Controls */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '12px',
        }}
      >
        <div>
          <span className="eyebrow">Governed Trend Series ({userId})</span>
          <h3 style={{ margin: '4px 0 0', fontSize: '16px', fontWeight: 650, color: 'var(--text)' }}>
            {kpiLabel} Historical Performance
          </h3>
        </div>

        {/* Zoom & Range Controls Subcomponent */}
        <TrendChartControls
          totalPoints={rawPoints.length}
          rangeStart={rangeStart}
          rangeEnd={rangeEnd}
          onPreset={handlePreset}
          onZoomIn={handleZoomIn}
          onZoomOut={handleZoomOut}
          onReset={handleResetZoom}
        />
      </div>

      {/* Legend & Meta summary */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '16px',
          fontSize: '11px',
          color: 'var(--muted)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              width: '14px',
              height: '3px',
              backgroundColor: 'var(--blue)',
              borderRadius: '2px',
              display: 'inline-block',
            }}
          />
          <strong style={{ color: 'var(--text)' }}>Actual Series</strong>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              width: '14px',
              height: '2px',
              borderTop: '2px dashed var(--muted)',
              display: 'inline-block',
            }}
          />
          <span>Governed Baseline</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: 'var(--amber)',
              display: 'inline-block',
            }}
          />
          <span>Material Event</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span
            style={{
              width: '2px',
              height: '10px',
              backgroundColor: 'var(--blue)',
              display: 'inline-block',
            }}
          />
          <span>Target Date ({targetDate})</span>
        </div>

        <div style={{ marginLeft: 'auto', fontSize: '11px', color: 'var(--faint)' }}>
          Showing {visiblePoints.length} days ({visiblePoints[0]?.observation_date} to{' '}
          {visiblePoints[visiblePoints.length - 1]?.observation_date})
        </div>
      </div>

      {/* SVG Chart Body */}
      <div style={{ position: 'relative', width: '100%', height: `${height}px` }}>
        <svg
          ref={svgRef}
          width="100%"
          height={height}
          style={{ overflow: 'visible', display: 'block' }}
          onMouseLeave={() => setHoveredPoint(null)}
        >
          <g transform={`translate(${padding.left}, ${padding.top})`}>
            {/* Gridlines & Y-Axis labels */}
            {yTicks.map((tick, i) => (
              <g key={i}>
                <line
                  x1={0}
                  y1={tick.y}
                  x2={innerWidth}
                  y2={tick.y}
                  stroke="var(--line)"
                  strokeDasharray={i === 0 || i === yTicks.length - 1 ? 'none' : '3 3'}
                  strokeOpacity={0.6}
                />
                <text
                  x={-10}
                  y={tick.y + 4}
                  textAnchor="end"
                  fontSize={11}
                  fill="var(--muted)"
                  fontFamily="sans-serif"
                >
                  {formatValue(tick.val, unit)}
                </text>
              </g>
            ))}

            {/* X-Axis Grid & Labels */}
            {xTicks.map((t, i) => (
              <g key={i}>
                <line
                  x1={t.x}
                  y1={0}
                  x2={t.x}
                  y2={innerHeight}
                  stroke="var(--line)"
                  strokeDasharray="2 2"
                  strokeOpacity={0.4}
                />
                <text
                  x={t.x}
                  y={innerHeight + 24}
                  textAnchor="middle"
                  fontSize={11}
                  fill="var(--muted)"
                  fontFamily="sans-serif"
                >
                  {t.label}
                </text>
              </g>
            ))}

            {/* Target Date Highlight Line */}
            {pointsWithCoords.map(item => {
              if (item.pt.observation_date === targetDate) {
                return (
                  <g key="target-highlight">
                    <line
                      x1={item.x}
                      y1={0}
                      x2={item.x}
                      y2={innerHeight}
                      stroke="var(--blue)"
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                    />
                    {item.yActual != null && (
                      <circle
                        cx={item.x}
                        cy={item.yActual}
                        r={6}
                        fill="var(--blue)"
                        stroke="var(--panel)"
                        strokeWidth={2}
                      />
                    )}
                  </g>
                )
              }
              return null
            })}

            {/* Requirement 4: Render Baseline Expected segments (non-bridged) */}
            {expectedSegments.map((seg, segIdx) => {
              if (seg.length < 2) {
                const single = seg[0]
                if (!single || single.yExpected == null) return null
                return (
                  <circle
                    key={`exp-dot-${segIdx}`}
                    cx={single.x}
                    cy={single.yExpected}
                    r={3}
                    fill="var(--faint)"
                  />
                )
              }
              const d = segmentToSvgPath(seg, 'yExpected')
              return (
                <path
                  key={`exp-seg-${segIdx}`}
                  d={d}
                  fill="none"
                  stroke="var(--faint)"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  opacity={0.85}
                />
              )
            })}

            {/* Requirement 4: Render Actual Series segments (non-bridged) */}
            {actualSegments.map((seg, segIdx) => {
              if (seg.length < 2) {
                const single = seg[0]
                if (!single || single.yActual == null) return null
                return (
                  <circle
                    key={`act-dot-${segIdx}`}
                    cx={single.x}
                    cy={single.yActual}
                    r={4}
                    fill="var(--blue)"
                  />
                )
              }
              const d = segmentToSvgPath(seg, 'yActual')
              return (
                <path
                  key={`act-seg-${segIdx}`}
                  d={d}
                  fill="none"
                  stroke="var(--blue)"
                  strokeWidth={2.5}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )
            })}

            {/* Material Event Markers & Hover Targets */}
            {pointsWithCoords.map((item, idx) => {
              const isMaterial = item.pt.material_event
              const isHovered = hoveredPoint?.observation_date === item.pt.observation_date

              return (
                <g key={idx}>
                  {/* Material Event Amber Marker Dot */}
                  {isMaterial && item.yActual != null && (
                    <circle
                      cx={item.x}
                      cy={item.yActual}
                      r={isHovered ? 7 : 5}
                      fill="var(--amber)"
                      stroke="var(--panel)"
                      strokeWidth={1.5}
                    />
                  )}

                  {/* Interactive Hover Hit Area */}
                  <rect
                    x={item.x - Math.max(10, innerWidth / (pointsWithCoords.length * 2))}
                    y={0}
                    width={Math.max(20, innerWidth / pointsWithCoords.length)}
                    height={innerHeight}
                    fill="transparent"
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={() => {
                      setHoveredPoint(item.pt)
                      if (svgRef.current) {
                        setTooltipPos({
                          x: item.x + padding.left,
                          y: (item.yActual ?? innerHeight / 2) + padding.top,
                        })
                      }
                    }}
                  />

                  {/* Hover Indicator Circle */}
                  {isHovered && item.yActual != null && (
                    <circle
                      cx={item.x}
                      cy={item.yActual}
                      r={6}
                      fill="var(--blue)"
                      stroke="white"
                      strokeWidth={2}
                    />
                  )}
                </g>
              )
            })}
          </g>
        </svg>

        {/* Hover Tooltip Overlay */}
        {hoveredPoint && tooltipPos && (
          <div
            style={{
              position: 'absolute',
              left: `${Math.min(chartWidth - 220, Math.max(10, tooltipPos.x - 100))}px`,
              top: `${Math.max(10, tooltipPos.y - 110)}px`,
              backgroundColor: 'var(--panel)',
              color: 'var(--text)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              padding: '10px 14px',
              fontSize: '11px',
              boxShadow: '0 8px 24px rgba(0, 0, 0, 0.4)',
              zIndex: 50,
              pointerEvents: 'none',
              minWidth: '180px',
            }}
          >
            <div
              style={{
                fontWeight: 700,
                color: 'var(--text)',
                marginBottom: '4px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <span>{hoveredPoint.observation_date}</span>
              {hoveredPoint.material_event && (
                <span
                  style={{
                    backgroundColor: 'rgba(245, 158, 11, 0.2)',
                    color: 'var(--amber)',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    fontSize: '9px',
                    fontWeight: 700,
                  }}
                >
                  Material
                </span>
              )}
            </div>

            {/* Requirement 4: Truthfully render missing values in tooltip */}
            <div style={{ display: 'flex', justifyContent: 'space-between', margin: '2px 0' }}>
              <span style={{ color: 'var(--muted)' }}>Actual:</span>
              <strong style={{ color: hoveredPoint.actual != null ? 'var(--text)' : 'var(--faint)' }}>
                {formatValue(hoveredPoint.actual, unit)}
              </strong>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', margin: '2px 0' }}>
              <span style={{ color: 'var(--muted)' }}>Baseline:</span>
              <span style={{ color: 'var(--faint)' }}>
                {formatValue(hoveredPoint.expected, unit)}
              </span>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', margin: '2px 0' }}>
              <span style={{ color: 'var(--muted)' }}>Variance:</span>
              <span
                style={{
                  fontWeight: 650,
                  color:
                    hoveredPoint.delta == null
                      ? 'var(--faint)'
                      : hoveredPoint.delta < 0
                      ? 'var(--red)'
                      : 'var(--green)',
                }}
              >
                {formatDelta(hoveredPoint.delta, unit)}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Range Slider Brush */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '11px', color: 'var(--muted)' }}>
        <span>Timeline Slider:</span>
        <input
          type="range"
          min={0}
          max={Math.max(0, rawPoints.length - 1)}
          value={rangeStart}
          onChange={e => {
            const val = parseInt(e.target.value, 10)
            if (val < rangeEnd) setRangeStart(val)
          }}
          aria-label="Start Date Slider"
          style={{ flex: 1, height: '4px', accentColor: 'var(--blue)', cursor: 'pointer' }}
        />
        <input
          type="range"
          min={0}
          max={Math.max(0, rawPoints.length - 1)}
          value={rangeEnd}
          onChange={e => {
            const val = parseInt(e.target.value, 10)
            if (val > rangeStart) setRangeEnd(val)
          }}
          aria-label="End Date Slider"
          style={{ flex: 1, height: '4px', accentColor: 'var(--blue)', cursor: 'pointer' }}
        />
      </div>

      {/* Requirement 3: Traceability Metadata Subcomponent */}
      <TrendChartMetadata
        source={data?.source}
        method={data?.method}
        dataVersion={data?.data_version}
        totalObservations={rawPoints.length}
      />
    </div>
  )
}
