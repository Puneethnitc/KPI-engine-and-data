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
  if (!model) return <p className="driver-waterfall-empty">Waterfall values are not available for this older run.</p>
  const width = Math.max(700, model.bars.length * 125 + 95)
  const plot = { left: 84, right: width - 24, top: 42, bottom: 290 }
  const step = (plot.right - plot.left) / model.bars.length
  const barWidth = Math.min(70, step * 0.58)
  const y = (value: number) => plot.bottom - (value - model.min) / (model.max - model.min) * (plot.bottom - plot.top)
  return <div className="driver-waterfall" role="img" aria-label={title}>
    <div className="driver-waterfall-scroll"><svg viewBox={`0 0 ${width} 365`} width={width} height={365} aria-hidden="true">
      {model.ticks.map((tick, index) => <g key={index}>
        <line x1={plot.left} x2={plot.right} y1={y(tick)} y2={y(tick)} className="waterfall-grid" />
        <text x={plot.left - 12} y={y(tick) + 4} textAnchor="end" className="waterfall-axis-label">{formatKpiValue(tick, unit)}</text>
      </g>)}
      {model.bars.map((bar, index) => {
        const x = plot.left + step * (index + 0.5)
        const from = bar.kind === 'total' ? model.min : bar.start
        const top = y(Math.max(from, bar.end))
        const bottom = y(Math.min(from, bar.end))
        const height = Math.max(2, bottom - top)
        const labelY = Math.max(24, top - 8)
        return <g key={`${bar.label}-${index}`}>
          {index > 0 && <line x1={x - step + barWidth / 2} x2={x - barWidth / 2} y1={y(model.bars[index - 1].end)} y2={y(model.bars[index - 1].end)} className="waterfall-connector" />}
          <rect x={x - barWidth / 2} y={top} width={barWidth} height={height} rx={5} className={`waterfall-bar ${bar.kind}`} />
          <text x={x} y={labelY} textAnchor="middle" className="waterfall-value">{formatKpiValue(bar.value, unit, bar.kind !== 'total')}</text>
          <text x={x} y={plot.bottom + 25} textAnchor="middle" className="waterfall-bar-label">{bar.label.length > 18 ? `${bar.label.slice(0, 17)}…` : bar.label}</text>
        </g>
      })}
    </svg></div>
    {Math.abs(model.reconciliationGap) > 1e-6 && <p className="driver-waterfall-note">Saved contributions do not exactly reach Actual; the difference is {formatKpiValue(model.reconciliationGap, unit, true)}.</p>}
  </div>
}
