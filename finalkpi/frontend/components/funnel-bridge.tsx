import DriverWaterfall from './driver-waterfall'

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
  expected,
  actual,
}: {
  bridge?: FunnelBridge | null
  status?: string | null
  unit: string
  expected?: number | null
  actual?: number | null
}) {
  if (!bridge && !status) return <article className="card funnel-bridge-card" aria-label="Funnel bridge"><p>Funnel bridge is not available for this older run.</p></article>
  if (!bridge) return null
  return <article className="card funnel-bridge-card" aria-label="Funnel bridge">
    <div className="card-heading">
      <div><span className="eyebrow">Where the movement happened</span><h3>Funnel bridge</h3></div>
      <span className={`evidence-pill ${bridge.identity_held ? 'good' : 'limited'}`}>{bridge.identity_held ? 'Identity reconciled' : 'Incomplete'}</span>
    </div>
    <p className="method-note">Revenue = traffic x conversion x average order value. This is an exact accounting split of the movement, not a cause.</p>
    <DriverWaterfall title="Funnel accounting waterfall" expected={expected} actual={actual} drivers={(bridge.components ?? []).map(item => ({ label: componentLabel[item.name] ?? item.name, value: item.effect }))} residual={actual != null && expected != null ? actual - expected - bridge.components.reduce((sum, item) => sum + item.effect, 0) : null} unit={unit} />
  </article>
}
