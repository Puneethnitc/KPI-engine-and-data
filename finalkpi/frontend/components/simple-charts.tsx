'use client'

import { useEffect, useRef, useState } from 'react'
import { formatKpiValue } from '../lib/driver-waterfall'
import { formatPercent, indexTo100, type PieSlice } from '../lib/simple-charts'

const PIE_COLOURS = ['#2f6fdb', '#d9822b', '#7b5cc4', '#1a8f9c', '#b0508a', '#5a8f29']
const NEUTRAL_COLOURS = { other: '#8a94a3', unexplained: '#c3c9d2' }

export function ChartEmpty({ children }: { children: React.ReactNode }) {
  return <p className="simple-chart-empty" role="status">{children}</p>
}

/** One row per item; bar grows from a shared zero line. Red = down, green = up. */
export function SignedBarChart({ title, items, format }: { title: string; items: { label: string; value: number }[]; format: (value: number) => string }) {
  if (!items.length) return <ChartEmpty>Not available for this run.</ChartEmpty>
  const max = Math.max(...items.map(item => Math.abs(item.value)), 1e-9)
  const hasNegative = items.some(item => item.value < 0)
  const hasPositive = items.some(item => item.value > 0)
  const negativeSpan = hasNegative ? Math.max(...items.map(item => Math.max(-item.value, 0))) : 0
  const positiveSpan = hasPositive ? Math.max(...items.map(item => Math.max(item.value, 0))) : 0
  const total = negativeSpan + positiveSpan || max
  const zero = negativeSpan / total * 100
  return <div className="simple-bars" role="img" aria-label={`${title}: ${items.map(item => `${item.label} ${format(item.value)}`).join(', ')}`}>
    {items.map(item => {
      const width = Math.abs(item.value) / total * 100
      const down = item.value < 0
      return <div className="simple-bar-row" key={item.label}>
        <span className="simple-bar-label">{item.label}</span>
        <div className="simple-bar-track">
          <i className="simple-bar-zero" style={{ left: `${zero}%` }} />
          <b className={`simple-bar ${down ? 'down' : 'up'}`} style={down ? { right: `${100 - zero}%`, width: `${width}%` } : { left: `${zero}%`, width: `${width}%` }} />
        </div>
        <span className={`simple-bar-value ${down ? 'down' : 'up'}`}>{down ? '▼ ' : item.value > 0 ? '▲ ' : ''}{format(item.value)}</span>
      </div>
    })}
  </div>
}

export function SharePie({ slices }: { slices: PieSlice[] }) {
  const radius = 80
  const inner = 48
  let angle = -Math.PI / 2
  let colourIndex = 0
  const parts = slices.map(slice => {
    const colour = slice.kind === 'driver' ? PIE_COLOURS[colourIndex++ % PIE_COLOURS.length] : NEUTRAL_COLOURS[slice.kind]
    const sweep = Math.min(slice.share, 0.9999) * Math.PI * 2
    const start = angle
    angle += sweep
    const point = (r: number, a: number) => `${(100 + r * Math.cos(a)).toFixed(2)} ${(100 + r * Math.sin(a)).toFixed(2)}`
    const large = sweep > Math.PI ? 1 : 0
    const d = `M ${point(radius, start)} A ${radius} ${radius} 0 ${large} 1 ${point(radius, angle)} L ${point(inner, angle)} A ${inner} ${inner} 0 ${large} 0 ${point(inner, start)} Z`
    return { slice, colour, d }
  })
  return <div className="simple-pie">
    <svg viewBox="0 0 200 200" role="img" aria-label={`Share of the change: ${slices.map(item => `${item.label} ${(item.share * 100).toFixed(0)}%`).join(', ')}`}>
      {parts.map(part => <path key={part.slice.label} d={part.d} fill={part.colour} stroke="var(--panel)" strokeWidth={2} />)}
    </svg>
    <ul className="simple-pie-legend">
      {parts.map(part => <li key={part.slice.label}><i style={{ background: part.colour }} /><span>{part.slice.label}</span><strong>{(part.slice.share * 100).toFixed(0)}%</strong></li>)}
    </ul>
  </div>
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const measure = () => setWidth(node.getBoundingClientRect().width)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

type Point = { date: string; value: number | null }
type SeriesState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; driver: Point[]; kpi: Point[]; driverUnit?: string | null }

export function DriverVsKpiChart({ apiBase, kpiId, kpiLabel, kpiUnit, driverId, driverLabel, region, category, targetDate, userId, asOf }: {
  apiBase: string
  kpiId: string
  kpiLabel: string
  kpiUnit: string
  driverId: string
  driverLabel: string
  region: string
  category: string
  targetDate: string
  userId: string
  asOf?: string | null
}) {
  const [state, setState] = useState<SeriesState>({ status: 'loading' })
  const [hover, setHover] = useState<number | null>(null)
  const [ref, width] = useWidth<HTMLDivElement>()
  useEffect(() => {
    let cancelled = false
    setState({ status: 'loading' })
    const base = `region=${encodeURIComponent(region)}&category=${encodeURIComponent(category)}&end_date=${encodeURIComponent(targetDate)}&user_id=${encodeURIComponent(userId)}`
    const start = new Date(new Date(targetDate).getTime() - 59 * 86400000).toISOString().slice(0, 10)
    const get = async (url: string) => {
      const res = await fetch(url, { cache: 'no-store' })
      if (!res.ok) throw new Error(res.status === 403 || res.status === 401 ? 'You do not have access to this data.' : 'Series is not available.')
      return res.json()
    }
    Promise.all([
      get(`${apiBase}/api/kpis/${encodeURIComponent(kpiId)}/driver-series?driver_id=${encodeURIComponent(driverId)}&${base}${asOf ? `&as_of=${encodeURIComponent(asOf)}` : ''}`),
      get(`${apiBase}/api/kpis/${encodeURIComponent(kpiId)}/timeseries?${base}&start_date=${start}`),
    ]).then(([driver, kpi]) => {
      if (cancelled) return
      setState({
        status: 'ready',
        driverUnit: driver.unit,
        driver: (driver.points ?? []).map((p: { observation_date: string; value: number | null }) => ({ date: p.observation_date, value: p.value })),
        kpi: (kpi.points ?? []).map((p: { observation_date: string; actual: number | null }) => ({ date: p.observation_date, value: p.actual })),
      })
    }).catch(error => { if (!cancelled) setState({ status: 'error', message: error instanceof Error ? error.message : 'Series is not available.' }) })
    return () => { cancelled = true }
  }, [apiBase, kpiId, driverId, region, category, targetDate, userId, asOf])

  const heading = <div className="card-heading"><div><span className="eyebrow">Over time</span><h3>Main cause vs KPI over time</h3></div></div>
  if (state.status === 'loading') return <div className="simple-chart-card">{heading}<ChartEmpty>Loading…</ChartEmpty></div>
  if (state.status === 'error') return <div className="simple-chart-card">{heading}<ChartEmpty>{state.message}</ChartEmpty></div>
  const dates = Array.from(new Set([...state.driver, ...state.kpi].map(p => p.date))).sort()
  const driverByDate = new Map(state.driver.map(p => [p.date, p.value]))
  const kpiByDate = new Map(state.kpi.map(p => [p.date, p.value]))
  const driverValues = dates.map(d => driverByDate.get(d) ?? null)
  const kpiValues = dates.map(d => kpiByDate.get(d) ?? null)
  const driverIdx = indexTo100(driverValues)
  const kpiIdx = indexTo100(kpiValues)
  const all = [...driverIdx, ...kpiIdx].filter((v): v is number => v != null)
  if (dates.length < 2 || all.length < 2 || !width) return <div className="simple-chart-card" ref={ref}>{heading}<ChartEmpty>Not enough data to draw this chart.</ChartEmpty></div>

  const ratio = (u: string | null | undefined) => !!u && /share|fraction|ratio|rate|percent/i.test(u)
  const driverName = `${driverLabel}${state.driverUnit ? ` (${ratio(state.driverUnit) ? '%' : state.driverUnit})` : ''}`
  const fmtDriver = (v: number | null) => v == null ? '—' : ratio(state.driverUnit) ? `${(v * 100).toFixed(1)}%` : v.toLocaleString('en-IN', { maximumFractionDigits: 2 })
  const fmtKpi = (v: number | null) => v == null ? '—' : formatKpiValue(v, kpiUnit)

  let lo = Math.min(...all), hi = Math.max(...all)
  const pad = (hi - lo || 1) * 0.1
  lo -= pad; hi += pad
  const height = 280
  const m = { left: 48, right: 14, top: 14, bottom: 34 }
  const x = (i: number) => m.left + (width - m.left - m.right) * i / (dates.length - 1)
  const y = (v: number) => m.top + (height - m.top - m.bottom) * (1 - (v - lo) / (hi - lo))
  const path = (values: (number | null)[]) => values.reduce<string>((d, v, i) => v == null ? d : `${d}${d && values[i - 1] != null ? ' L' : ' M'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`, '').trim()
  const targetIndex = dates.indexOf(targetDate)
  const ticks = Array.from({ length: 5 }, (_, i) => lo + (hi - lo) * i / 4)
  const labelEvery = Math.max(1, Math.ceil(dates.length / (width < 500 ? 3 : 6)))
  const shortDate = (d: string) => new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
  const active = hover ?? null
  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    const i = Math.round((event.clientX - box.left - m.left) / (width - m.left - m.right) * (dates.length - 1))
    setHover(Math.min(dates.length - 1, Math.max(0, i)))
  }
  return <div className="simple-chart-card" ref={ref}>
    {heading}
    <ul className="simple-line-legend">
      <li><i className="driver" />{driverName}</li>
      <li><i className="kpi" />{kpiLabel}</li>
    </ul>
    <svg width={width} height={height} role="img" aria-label={`${driverName} and ${kpiLabel} over the 60 days up to ${targetDate}, both indexed to 100 on the first day`} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
      {ticks.map(t => <g key={t}><line x1={m.left} x2={width - m.right} y1={y(t)} y2={y(t)} className="simple-line-grid" /><text x={m.left - 8} y={y(t) + 5} textAnchor="end" className="simple-line-axis">{t.toFixed(0)}</text></g>)}
      {dates.map((d, i) => i % labelEvery === 0 && <text key={d} x={x(i)} y={height - 10} textAnchor="middle" className="simple-line-axis">{shortDate(d)}</text>)}
      {targetIndex >= 0 && <g><line x1={x(targetIndex)} x2={x(targetIndex)} y1={m.top} y2={height - m.bottom} className="simple-line-target" /><text x={Math.min(x(targetIndex), width - 60)} y={m.top + 12} textAnchor={x(targetIndex) > width - 70 ? 'end' : 'start'} dx={x(targetIndex) > width - 70 ? -4 : 4} className="simple-line-axis">Target date</text></g>}
      <path d={path(driverIdx)} className="simple-line driver" />
      <path d={path(kpiIdx)} className="simple-line kpi" />
      {active != null && <g><line x1={x(active)} x2={x(active)} y1={m.top} y2={height - m.bottom} className="simple-line-cursor" />
        {driverIdx[active] != null && <circle cx={x(active)} cy={y(driverIdx[active]!)} r={4.5} className="simple-dot driver" />}
        {kpiIdx[active] != null && <circle cx={x(active)} cy={y(kpiIdx[active]!)} r={4.5} className="simple-dot kpi" />}</g>}
    </svg>
    <div className="simple-line-readout" aria-live="polite">{active == null ? 'Hover or touch the chart for daily values.' : `${shortDate(dates[active])}: ${driverLabel} ${fmtDriver(driverValues[active])} · ${kpiLabel} ${fmtKpi(kpiValues[active])}`}</div>
    <small className="simple-chart-note">Both lines are indexed to 100 on the first day so they share one scale. Timing shows association, not proof of cause.</small>
  </div>
}
