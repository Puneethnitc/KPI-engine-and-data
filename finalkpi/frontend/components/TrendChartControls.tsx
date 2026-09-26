'use client'

import { RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'

type TrendChartControlsProps = {
  totalPoints: number
  rangeStart: number
  rangeEnd: number
  onPreset: (days: number) => void
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
}

export function TrendChartControls({
  totalPoints,
  rangeStart,
  rangeEnd,
  onPreset,
  onZoomIn,
  onZoomOut,
  onReset,
}: TrendChartControlsProps) {
  const currentLength = rangeEnd - rangeStart + 1

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          backgroundColor: 'var(--panel-2)',
          borderRadius: '6px',
          border: '1px solid var(--line)',
          padding: '2px',
        }}
      >
        {[
          { label: '30D', days: 30 },
          { label: '60D', days: 60 },
          { label: '90D', days: 90 },
          { label: 'All', days: totalPoints },
        ].map(p => (
          <button
            key={p.label}
            type="button"
            onClick={() => onPreset(p.days)}
            style={{
              padding: '3px 8px',
              fontSize: '11px',
              fontWeight: 600,
              borderRadius: '4px',
              border: 'none',
              background:
                currentLength === Math.min(p.days, totalPoints)
                  ? 'var(--panel-3)'
                  : 'transparent',
              color:
                currentLength === Math.min(p.days, totalPoints)
                  ? 'var(--text)'
                  : 'var(--muted)',
              cursor: 'pointer',
            }}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: '4px' }}>
        <button
          type="button"
          onClick={onZoomIn}
          title="Zoom In"
          aria-label="Zoom In"
          style={{
            width: '30px',
            height: '30px',
            display: 'grid',
            placeItems: 'center',
            backgroundColor: 'var(--panel-2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            color: 'var(--text)',
            cursor: 'pointer',
          }}
        >
          <ZoomIn size={14} />
        </button>
        <button
          type="button"
          onClick={onZoomOut}
          title="Zoom Out"
          aria-label="Zoom Out"
          style={{
            width: '30px',
            height: '30px',
            display: 'grid',
            placeItems: 'center',
            backgroundColor: 'var(--panel-2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            color: 'var(--text)',
            cursor: 'pointer',
          }}
        >
          <ZoomOut size={14} />
        </button>
        <button
          type="button"
          onClick={onReset}
          title="Reset to default 90-day range"
          aria-label="Reset View"
          style={{
            height: '30px',
            padding: '0 8px',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            backgroundColor: 'var(--panel-2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            color: 'var(--muted)',
            fontSize: '11px',
            cursor: 'pointer',
          }}
        >
          <RotateCcw size={12} /> Reset
        </button>
      </div>
    </div>
  )
}
