'use client'

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react'
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

// ── Zoom/pan tuning constants ─────────────────────────────────────────────
// Sensitivity for scroll-to-zoom. Smaller = gentler. Tuned against recording.
const ZOOM_SENSITIVITY = 0.0015
// Maximum normalised delta applied per animation frame (prevents large jumps).
const MAX_DELTA_PER_FRAME = 80
// Minimum visible window (observations).
const MIN_WINDOW = 7
// Damping factor applied to wheel-based panning (1 = no damping).
const PAN_DAMPING = 0.8

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

  // Integer viewport bounds exposed to React (used for rendering slice).
  // We keep fractional precision in vpRef and only round when committing.
  const [rangeStart, setRangeStart] = useState<number>(0)
  const [rangeEnd, setRangeEnd] = useState<number>(0)

  // Fractional (floating-point) viewport – the true source of truth during
  // wheel and drag interactions.  React state is derived from this on each rAF.
  const vpRef = useRef<{ start: number; end: number }>({ start: 0, end: 0 })

  // Pending accumulated wheel deltas waiting for the next animation frame.
  const pendingWheelRef = useRef<{ deltaY: number; deltaX: number; anchorRatio: number | null } | null>(null)
  const rafIdRef = useRef<number | null>(null)

  const [hoveredPoint, setHoveredPoint] = useState<TimeseriesPoint | null>(null)
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null)

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const scrubberRef = useRef<HTMLDivElement>(null)
  const panRef = useRef<{ clientX: number; start: number; end: number } | null>(null)
  const scrubRef = useRef<{ pointerOffset: number } | null>(null)
  const [isPanning, setIsPanning] = useState(false)
  const [isScrubbing, setIsScrubbing] = useState(false)
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

        // Open chart at the latest 90 days by default
        const total = pts.length
        const defaultStart = Math.max(0, total - 90)
        const defaultEnd = Math.max(0, total - 1)
        // Sync fractional ref so wheel/drag handlers start from a consistent state.
        vpRef.current = { start: defaultStart, end: defaultEnd }
        setRangeStart(defaultStart)
        setRangeEnd(defaultEnd)
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

  // Cancel any pending rAF on unmount to prevent state updates after unmount.
  useEffect(() => {
    return () => {
      if (rafIdRef.current != null) {
        cancelAnimationFrame(rafIdRef.current)
        rafIdRef.current = null
      }
    }
  }, [])

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

  // Zoom Actions – route through applyFractionalVp to keep vpRef in sync.
  function handleZoomIn() {
    if (!rawPoints.length) return
    const { start, end } = vpRef.current
    const span = end - start
    if (span <= MIN_WINDOW) return
    const shrink = span * 0.2
    applyFractionalVp(start + shrink / 2, end - shrink / 2)
  }

  function handleZoomOut() {
    if (!rawPoints.length) return
    const { start, end } = vpRef.current
    const span = Math.max(1, end - start)
    const grow = Math.max(4, span * 0.25)
    applyFractionalVp(start - grow / 2, end + grow / 2)
  }

  // Reset returns to default 90-day range
  function handleResetZoom() {
    if (!rawPoints.length) return
    const total = rawPoints.length
    const defaultStart = Math.max(0, total - 90)
    const defaultEnd = total - 1
    vpRef.current = { start: defaultStart, end: defaultEnd }
    setRangeStart(defaultStart)
    setRangeEnd(defaultEnd)
  }

  function handlePreset(days: number) {
    if (!rawPoints.length) return
    const endIdx = rawPoints.length - 1
    const startIdx = Math.max(0, endIdx - days + 1)
    vpRef.current = { start: startIdx, end: endIdx }
    setRangeStart(startIdx)
    setRangeEnd(endIdx)
  }

  // Chart Geometry Calculations
  const padding = { top: 24, right: 24, bottom: 44, left: 60 }
  const height = 280
  const innerWidth = Math.max(200, chartWidth - padding.left - padding.right)
  const innerHeight = height - padding.top - padding.bottom

  const lastPointIndex = Math.max(0, rawPoints.length - 1)
  const visibleSpan = Math.max(0, rangeEnd - rangeStart)
  const isFullRange = rangeStart === 0 && rangeEnd >= lastPointIndex

  // ── Fractional viewport helpers ─────────────────────────────────────────
  // Commit fractional vpRef values into integer React state for rendering.
  function commitVp() {
    const { start, end } = vpRef.current
    // Round to nearest integer for array slice, never invert the span.
    const rs = Math.max(0, Math.round(start))
    const re = Math.max(rs + MIN_WINDOW - 1, Math.min(lastPointIndex, Math.round(end)))
    setRangeStart(rs)
    setRangeEnd(re)
  }

  // Clamp and write fractional viewport then commit.
  function applyFractionalVp(start: number, end: number) {
    if (!rawPoints.length) return
    const span = Math.max(MIN_WINDOW - 1, end - start)
    // Clamp so we never exceed [0, lastPointIndex].
    const clampedStart = Math.max(0, Math.min(start, lastPointIndex - span))
    const clampedEnd = Math.min(lastPointIndex, clampedStart + span)
    vpRef.current = { start: clampedStart, end: clampedEnd }
    commitVp()
  }

  function setClampedRange(start: number, end: number) {
    applyFractionalVp(start, end)
  }

  function panToStart(start: number) {
    const span = vpRef.current.end - vpRef.current.start
    applyFractionalVp(start, start + span)
  }

  // ── rAF-batched wheel handler ────────────────────────────────────────────
  // Accumulate wheel deltas and apply at most one viewport update per frame.
  function scheduleWheelFrame() {
    if (rafIdRef.current != null) return // already scheduled
    rafIdRef.current = requestAnimationFrame(() => {
      rafIdRef.current = null
      const pending = pendingWheelRef.current
      if (!pending || rawPoints.length < 2) return
      pendingWheelRef.current = null

      const { start, end } = vpRef.current
      const span = end - start

      if (pending.anchorRatio === null) {
        // ── Pan branch ───────────────────────────────────────────────────
        // Normalise deltaX for panning; apply mild damping.
        const rawDelta = pending.deltaX
        // Clamp so one burst of momentum doesn't teleport the window.
        const clampedDelta = Math.max(-MAX_DELTA_PER_FRAME, Math.min(MAX_DELTA_PER_FRAME, rawDelta))
        const panOffset = (clampedDelta / Math.max(1, innerWidth)) * Math.max(1, span) * PAN_DAMPING
        applyFractionalVp(start + panOffset, end + panOffset)
      } else {
        // ── Zoom branch ──────────────────────────────────────────────────
        // Normalise deltaY; clamp to prevent jumps from large wheel events.
        const rawDelta = pending.deltaY
        const clampedDelta = Math.max(-MAX_DELTA_PER_FRAME, Math.min(MAX_DELTA_PER_FRAME, rawDelta))
        // Exponential factor: positive deltaY (scroll down) → zoom in (shrink span).
        // Negate so Math.exp gives a factor < 1 when scrolling down.
        const factor = Math.exp(-clampedDelta * ZOOM_SENSITIVITY)
        const nextSpan = Math.max(MIN_WINDOW - 1, Math.min(lastPointIndex, span * factor))
        const anchorIndex = start + pending.anchorRatio * span
        const nextStart = anchorIndex - pending.anchorRatio * nextSpan
        applyFractionalVp(nextStart, nextStart + nextSpan)
      }
    })
  }

  function handleChartWheel(event: WheelEvent<HTMLDivElement>) {
    if (rawPoints.length < 2) return
    event.preventDefault()

    // ── Normalize wheel delta by deltaMode ──────────────────────────────
    // DOM_DELTA_PIXEL = 0 (default, trackpad), DOM_DELTA_LINE = 1, DOM_DELTA_PAGE = 2
    const linePixels = 16   // approximate pixels per line
    const pagePixels = 600  // approximate pixels per page
    const multiplier = event.deltaMode === 1 ? linePixels : event.deltaMode === 2 ? pagePixels : 1
    const normY = event.deltaY * multiplier
    const normX = event.deltaX * multiplier

    const isPanGesture = event.shiftKey || (Math.abs(normX) > Math.abs(normY))

    if (isPanGesture) {
      // Accumulate panning delta; anchorRatio=null signals pan branch.
      const delta = event.shiftKey ? normY : normX
      if (pendingWheelRef.current) {
        pendingWheelRef.current.deltaX += delta
      } else {
        pendingWheelRef.current = { deltaY: 0, deltaX: delta, anchorRatio: null }
      }
    } else {
      // Accumulate zooming delta.  Anchor ratio is captured from the first
      // event in the batch; this keeps zoom stable during rapid gestures.
      const bounds = event.currentTarget.getBoundingClientRect()
      // Correctly account for left padding when computing anchor.
      const plotX = Math.max(0, Math.min(innerWidth, event.clientX - bounds.left - padding.left))
      const anchorRatio = Math.max(0, Math.min(1, plotX / innerWidth))
      if (pendingWheelRef.current && pendingWheelRef.current.anchorRatio !== null) {
        pendingWheelRef.current.deltaY += normY
        // keep the first anchor; it's stable enough for a single gesture burst
      } else {
        pendingWheelRef.current = { deltaY: normY, deltaX: 0, anchorRatio }
      }
    }

    scheduleWheelFrame()
  }

  function handleChartPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return
    // Capture fractional viewport at drag start.
    panRef.current = { clientX: event.clientX, start: vpRef.current.start, end: vpRef.current.end }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsPanning(true)
  }

  function handleChartPointerMove(event: PointerEvent<HTMLDivElement>) {
    const pan = panRef.current
    if (!pan) return
    // 1:1 proportional panning: pointer movement / plot width × visible span.
    const span = pan.end - pan.start
    const indexDelta = ((pan.clientX - event.clientX) / Math.max(1, innerWidth)) * Math.max(1, span)
    applyFractionalVp(pan.start + indexDelta, pan.end + indexDelta)
  }

  function finishChartPan(event: PointerEvent<HTMLDivElement>) {
    if (!panRef.current) return
    panRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setIsPanning(false)
  }

  function scrubberStartForClientX(clientX: number, pointerOffset = visibleSpan / 2) {
    const rail = scrubberRef.current
    if (!rail || rawPoints.length < 2) return
    const bounds = rail.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (clientX - bounds.left) / bounds.width))
    panToStart(ratio * lastPointIndex - pointerOffset)
  }

  function handleScrubberPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || rawPoints.length < 2) return
    const rail = scrubberRef.current
    if (!rail) return
    const bounds = rail.getBoundingClientRect()
    const pointerIndex = Math.max(0, Math.min(lastPointIndex, ((event.clientX - bounds.left) / bounds.width) * lastPointIndex))
    const clickedWindow = pointerIndex >= rangeStart && pointerIndex <= rangeEnd
    const pointerOffset = clickedWindow ? pointerIndex - rangeStart : visibleSpan / 2
    scrubRef.current = { pointerOffset }
    event.currentTarget.setPointerCapture(event.pointerId)
    setIsScrubbing(true)
    scrubberStartForClientX(event.clientX, pointerOffset)
  }

  function handleScrubberPointerMove(event: PointerEvent<HTMLDivElement>) {
    if (!scrubRef.current) return
    scrubberStartForClientX(event.clientX, scrubRef.current.pointerOffset)
  }

  function finishScrubbing(event: PointerEvent<HTMLDivElement>) {
    if (!scrubRef.current) return
    scrubRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setIsScrubbing(false)
  }

  function handleScrubberKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = Math.max(1, Math.round(Math.max(1, visibleSpan) * (event.key.startsWith('Page') ? 0.5 : 0.1)))
    if (event.key === 'ArrowLeft' || event.key === 'PageUp') panToStart(rangeStart - step)
    else if (event.key === 'ArrowRight' || event.key === 'PageDown') panToStart(rangeStart + step)
    else if (event.key === 'Home') panToStart(0)
    else if (event.key === 'End') panToStart(lastPointIndex - visibleSpan)
    else return
    event.preventDefault()
  }

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
      <div
        className={`trend-chart-plot${isPanning ? ' is-panning' : ''}`}
        style={{ position: 'relative', width: '100%', height: `${height}px` }}
        onWheel={handleChartWheel}
        onPointerDown={handleChartPointerDown}
        onPointerMove={handleChartPointerMove}
        onPointerUp={finishChartPan}
        onPointerCancel={finishChartPan}
      >
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

      {/* Compact timeline navigator: no native range sliders or duplicate handles. */}
      <div className="trend-chart-navigator">
        <div
          ref={scrubberRef}
          className={`trend-chart-scrubber${isScrubbing ? ' is-scrubbing' : ''}`}
          role="scrollbar"
          tabIndex={0}
          aria-label="Visible chart period"
          aria-orientation="horizontal"
          aria-valuemin={0}
          aria-valuemax={lastPointIndex}
          aria-valuenow={rangeStart}
          aria-valuetext={`${visiblePoints[0]?.observation_date ?? 'No start date'} to ${visiblePoints[visiblePoints.length - 1]?.observation_date ?? 'no end date'}`}
          onKeyDown={handleScrubberKeyDown}
          onPointerDown={handleScrubberPointerDown}
          onPointerMove={handleScrubberPointerMove}
          onPointerUp={finishScrubbing}
          onPointerCancel={finishScrubbing}
        >
          <span
            className="trend-chart-scrubber-window"
            style={{
              left: `${lastPointIndex ? (rangeStart / lastPointIndex) * 100 : 0}%`,
              width: `${lastPointIndex ? Math.max(2, (visibleSpan / lastPointIndex) * 100) : 100}%`,
            }}
          />
        </div>
        <div className="trend-chart-interaction-help">
          <span>{visiblePoints[0]?.observation_date} – {visiblePoints[visiblePoints.length - 1]?.observation_date}</span>
          <span>Scroll to zoom · Shift-scroll or drag to move · Hover to read</span>
        </div>
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
