'use client'

import { useEffect, useRef, useState } from 'react'
import { formatKpiValue, waterfallScale, type WaterfallInput } from '../lib/driver-waterfall'

export default function DriverWaterfall({
  expected, actual, drivers, residual, unit, title = 'Movement waterfall',
}: {
  expected?: number | null
  actual?: number | null
  drivers?: WaterfallInput[] | null
  residual?: number | null
  unit: string
  title?: string
}) {
  const model = waterfallScale(expected, actual, drivers, residual)
  const hasModel = model !== null
  const scrollRef = useRef<HTMLDivElement>(null)
  const [availableWidth, setAvailableWidth] = useState(0)
  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const measure = () => setAvailableWidth(container.getBoundingClientRect().width)
    measure()
    const resize = new ResizeObserver(measure)
    resize.observe(container)
    window.addEventListener('resize', measure)
    return () => { resize.disconnect(); window.removeEventListener('resize', measure) }
  }, [hasModel])
  if (!model) return <p className="driver-waterfall-empty">Waterfall values are not available for this older run.</p>
  const width = Math.max(availableWidth, model.bars.length * 110 + 95)
  const plot = { left: 84, right: width - 24, top: 42, bottom: 290 }
  const step = (plot.right - plot.left) / model.bars.length
  const barWidth = Math.min(70, step * 0.58)
  const y = (value: number) => plot.bottom - (value - model.min) / (model.max - model.min) * (plot.bottom - plot.top)
  const steps = model.bars.filter(bar => bar.kind !== 'total')
  const smallSteps = steps.filter(bar => bar.start !== bar.end && Math.abs(y(bar.start) - y(bar.end)) < 12)
  return <div className="driver-waterfall" role="img" aria-label={title}>
    <div className="driver-waterfall-scroll" ref={scrollRef}><svg viewBox={`0 0 ${width} 365`} width={width} height={365} aria-hidden="true">
      {model.ticks.map((tick, index) => <g key={index}>
        <line x1={plot.left} x2={plot.right} y1={y(tick)} y2={y(tick)} className="waterfall-grid" />
        <text x={plot.left - 12} y={y(tick) + 4} textAnchor="end" className="waterfall-axis-label">{formatKpiValue(tick, unit)}</text>
      </g>)}
      {model.bars.map((bar, index) => {
        const x = plot.left + step * (index + 0.5)
        const top = y(Math.max(bar.start, bar.end))
        const bottom = y(Math.min(bar.start, bar.end))
        const height = bottom - top
        const labelY = Math.max(24, top - 8)
        return <g key={`${bar.label}-${index}`}>
          {index > 0 && <line x1={x - step + barWidth / 2} x2={x - barWidth / 2} y1={y(model.bars[index - 1].end)} y2={y(model.bars[index - 1].end)} className="waterfall-connector" />}
          <rect x={x - barWidth / 2} y={top} width={barWidth} height={height} rx={5} className={`waterfall-bar ${bar.kind}`} />
          <text x={x} y={labelY} textAnchor="middle" className="waterfall-value">{formatKpiValue(bar.value, unit, bar.kind !== 'total')}</text>
          <text x={x} y={plot.bottom + 25} textAnchor="middle" className="waterfall-bar-label">{bar.label.length > 18 ? `${bar.label.slice(0, 17)}…` : bar.label}</text>
        </g>
      })}
    </svg>
    {smallSteps.length > 0 && <div className="waterfall-step-detail"><strong>≈ Step detail (each step has its own zoomed vertical scale)</strong><div className="waterfall-step-insets">{smallSteps.map((bar, index) => {
      const low = Math.min(bar.start, bar.end)
      const high = Math.max(bar.start, bar.end)
      const padding = (high - low) * 0.15
      const detailY = (value: number) => 102 - (value - low + padding) / (high - low + 2 * padding) * 80
      return <div className="waterfall-step-inset" key={`${bar.label}-${index}`}><small>{bar.label}: {formatKpiValue(bar.value, unit, true)}</small><svg viewBox="0 0 190 120" width={190} height={120} aria-hidden="true">
        {[bar.start, bar.end].map((tick, tickIndex) => <text key={tickIndex} x={90} y={detailY(tick) + 4} textAnchor="end" className="waterfall-axis-label">{formatKpiValue(tick, unit)}</text>)}
        <rect x={102} y={detailY(high)} width={48} height={Math.abs(detailY(bar.start) - detailY(bar.end))} rx={5} className={`waterfall-bar ${bar.kind}`} />
      </svg></div>
    })}</div></div>}</div>
    {Math.abs(model.reconciliationGap) > 1e-6 && <p className="driver-waterfall-note">Saved contributions do not exactly reach Actual; the difference is {formatKpiValue(model.reconciliationGap, unit, true)}.</p>}
  </div>
}
