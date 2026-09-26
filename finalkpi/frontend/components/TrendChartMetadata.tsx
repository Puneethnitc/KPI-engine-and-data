'use client'

type TrendChartMetadataProps = {
  source?: string | null
  method?: string | null
  dataVersion?: string | null
  totalObservations: number
}

export function TrendChartMetadata({
  source,
  method,
  dataVersion,
  totalObservations,
}: TrendChartMetadataProps) {
  return (
    <div
      className="chart-traceability-metadata"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: '12px 20px',
        paddingTop: '12px',
        borderTop: '1px solid var(--line)',
        fontSize: '11px',
        color: 'var(--faint)',
      }}
    >
      <div>
        <strong style={{ color: 'var(--muted)' }}>Source:</strong> {source || 'Unavailable'}
      </div>
      <div>
        <strong style={{ color: 'var(--muted)' }}>Baseline Method:</strong> {method || 'Unavailable'}
      </div>
      <div>
        <strong style={{ color: 'var(--muted)' }}>Data Version / Freshness:</strong> {dataVersion || 'Unavailable'}
      </div>
      <div>
        <strong style={{ color: 'var(--muted)' }}>Observations:</strong> {totalObservations} daily data points
      </div>
    </div>
  )
}
