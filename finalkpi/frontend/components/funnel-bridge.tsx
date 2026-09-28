export type FunnelBridgeComponent = {
  name: string
  baseline: number
  actual: number
  effect: number
  share: number | null
}

export type FunnelBridge = {
  components: FunnelBridgeComponent[]
  total_delta: number
  identity_held: boolean
}

const componentLabel: Record<string, string> = {
  traffic: 'Traffic',
  conversion: 'Conversion',
  aov: 'Average order value',
}

export default function FunnelBridgeCard({
  bridge,
  status,
  unit,
}: {
  bridge?: FunnelBridge | null
  status?: string | null
  unit: string
}) {
  if (!bridge && !status) return <article className="card funnel-bridge-card" aria-label="Funnel bridge"><p>Funnel bridge is not available for this older run.</p></article>
  if (!bridge) return null
  if (status !== 'IDENTITY_HELD') return null
  const maxAbs = Math.max(1e-9, ...bridge.components.map(item => Math.abs(item.effect)))
  return <article className="card funnel-bridge-card" aria-label="Funnel bridge">
    <div className="card-heading">
      <div><span className="eyebrow">Where the movement happened</span><h3>Funnel bridge</h3></div>
      <span className={`evidence-pill ${bridge.identity_held ? 'good' : 'limited'}`}>{bridge.identity_held ? 'Identity reconciled' : 'Incomplete'}</span>
    </div>
    <p className="method-note">Revenue = traffic x conversion x average order value. This is an exact accounting split of the movement, not a cause.</p>
    <div className="funnel-bridge-list">
      {bridge.components.map(item => <div className="funnel-bridge-row" key={item.name}>
        <span className="funnel-bridge-label">{componentLabel[item.name] ?? item.name}</span>
        <div className="funnel-bridge-bar">
          <i
            className={item.effect >= 0 ? 'funnel-bridge-fill positive' : 'funnel-bridge-fill negative'}
            style={{ width: `${Math.min(100, (Math.abs(item.effect) / maxAbs) * 100)}%` }}
          />
        </div>
        <span className="funnel-bridge-value">
          <strong>{item.effect >= 0 ? '+' : ''}{item.effect.toFixed(2)} {unit}</strong>
          <small>{item.share == null ? 'share not estimated' : `${(item.share * 100).toFixed(0)}% of the change`}</small>
        </span>
      </div>)}
    </div>
    <p className="funnel-bridge-total">Total change: <strong>{bridge.total_delta.toFixed(2)} {unit}</strong></p>
  </article>
}
