import { SignedBarChart, ChartEmpty } from './simple-charts'
import { formatPercent, kpiChangeBars } from '../lib/simple-charts'

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
  movements,
}: {
  bridge?: FunnelBridge | null
  status?: string | null
  movements: Record<string, { actual_value?: number | null; expected_value?: number | null } | null | undefined>
}) {
  if (!bridge && !status) return <article className="card funnel-bridge-card" aria-label="Funnel bridge"><p>Funnel bridge is not available for this older run.</p></article>
  if (!bridge) return null
  const bars = kpiChangeBars(movements)
  return <article className="card funnel-bridge-card" aria-label="Funnel bridge">
    <div className="card-heading">
      <div><span className="eyebrow">Where the movement happened</span><h3>Funnel bridge</h3></div>
      <span className={`evidence-pill ${bridge.identity_held ? 'good' : 'limited'}`}>{bridge.identity_held ? 'Identity reconciled' : 'Incomplete'}</span>
    </div>
    <p className="method-note">Revenue = traffic x conversion x average order value. This is an exact accounting split of the movement, not a cause.</p>
    <h4 className="simple-chart-title">How much each KPI changed (%)</h4>
    {bars.length ? <SignedBarChart title="How much each KPI changed (%)" items={bars} format={value => formatPercent(value)} /> : <ChartEmpty>Percent changes are not available for this run.</ChartEmpty>}
    <small className="simple-chart-note">Actual compared with expected for the selected scope and date.</small>
  </article>
}
