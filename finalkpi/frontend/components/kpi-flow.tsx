'use client'

import './kpi-flow.css'

export type KpiStory = {
  nodes: { kpi_id: string; actual: number | null; expected: number | null; percent_change: number | null; material: boolean; status: 'up' | 'down' | 'normal'; missing: boolean; consequence_of: string | null }[]
  edges: { stage: string; from: string; to: string; contribution_inr: number; contribution_pct: number | null; factor_percent_change: number | null }[]
  root_stage: string | null
  missing_stages: string[]
  revenue_delta: number | null
  cause_chains: KpiChain[]
  act_first: KpiChain[]
  headline_facts: { kind: string; delta?: number | null; percent_change?: number | null; stage?: string | null }[]
}

type KpiChain = { driver_id: string; stages: string[]; via_kpi: string; revenue_impact: number; recoverable_impact_inr: number; attribution_confidence: number; band: string | null; causal_verdict: string; corroboration_doc_ids: string[]; owner: string; shared_cause: boolean; attribution_source_kpis: string[]; stage_impacts: { stage: string; explained_share: number; revenue_impact: number; attribution_source_kpi: string }[] }

const labels: Record<string, string> = { traffic_total: 'Traffic', conversion_rate: 'Conversion', orders: 'Orders', units_sold: 'Units', net_sales_revenue: 'Revenue', traffic: 'Traffic', conversion: 'Conversion', units: 'Units', basket: 'Basket' }
const sequence = ['traffic_total', 'conversion_rate', 'orders', 'units_sold', 'basket', 'net_sales_revenue']
const name = (id: string) => labels[id] ?? id.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
const money = (amount: number) => `₹${Math.abs(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
const signedMoney = (amount: number) => `${amount < 0 ? '−' : '+'}${money(amount)}`
const signedPercent = (amount: number) => `${amount < 0 ? '−' : '+'}${Math.abs(amount).toFixed(1)}%`

const stageKpi: Record<string, string> = { traffic: 'traffic_total', conversion: 'conversion_rate', units: 'units_sold', basket: 'net_sales_revenue' }
const verdictLabel = (verdict: string) => verdict === 'NOT_TESTED' ? 'not tested' : verdict === 'SUPPORTED_CONDITIONAL' ? 'verified by causal test' : verdict.replaceAll('_', ' ').toLowerCase()

// "a", "a and b", "a, b and c"
function listPhrase(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

export function headline(story: KpiStory): string {
  const revenue = story.headline_facts.find(fact => fact.kind === 'revenue')
  if (revenue?.delta == null) return 'Revenue comparison is unavailable for this scope.'
  const direction = revenue.delta < 0 ? 'fell' : revenue.delta > 0 ? 'rose' : 'was unchanged'
  const main = `Revenue ${direction} ${money(revenue.delta)}${revenue.percent_change == null ? '' : ` (${signedPercent(revenue.percent_change)})`}.`
  const rootStage = story.headline_facts.find(fact => fact.kind === 'root_stage')?.stage ?? null
  const rootNode = rootStage ? story.nodes.find(node => node.kpi_id === stageKpi[rootStage]) : undefined
  const root = rootStage
    ? ` The largest share came from ${name(rootStage).toLowerCase()}${rootNode && !rootNode.material ? ', although no stage moved enough on its own to be material' : ''}.`
    : ''
  // Stages that did not move materially, excluding the root (already described above).
  const quietStages = story.headline_facts
    .filter(fact => fact.kind === 'normal_stage' && fact.stage && fact.stage !== 'basket' && fact.stage !== rootStage)
    .map(fact => name(fact.stage!).toLowerCase())
  const quiet = quietStages.length && rootNode?.material !== false
    ? ` ${listPhrase(quietStages).replace(/^\w/, letter => letter.toUpperCase())} ${quietStages.length === 1 ? 'was' : 'were'} within the normal range.`
    : ''
  return main + root + quiet
}

// Label under each box. "Consequence" only for KPIs that actually moved materially.
function nodeLabel(id: string, story: KpiStory, node: KpiStory['nodes'][number] | undefined): string {
  if (id === 'basket') return 'Revenue per unit'
  if (!node || node.missing) return 'Missing'
  const rootKpi = story.root_stage ? stageKpi[story.root_stage] : undefined
  if (rootKpi === id) return 'Largest share'
  if (node.consequence_of && node.material) return `Result of ${name(node.consequence_of).toLowerCase()}`
  return node.material ? 'Material change' : 'Normal range'
}

type Edge = KpiStory['edges'][number]
const NO_EFFECT = 0.5

// Revenue effect shown inside a stage's box; null for result boxes (orders, revenue).
function effectLine(id: string, edge: Edge | undefined): { text: string; tone: 'up' | 'down' | 'none' } | null {
  if (id === 'orders' || id === 'net_sales_revenue' || !edge) return null
  const share = edge.contribution_pct == null ? '' : ` (${Math.abs(edge.contribution_pct).toFixed(0)}%)`
  if (Math.abs(edge.contribution_inr) < NO_EFFECT) return { text: id === 'units_sold' ? 'Units per order: no effect' : 'No effect on revenue', tone: 'none' }
  const verb = edge.contribution_inr < 0 ? 'Removes' : 'Adds'
  return { text: `${verb} ${signedMoney(edge.contribution_inr)}${id === 'traffic_total' ? ` ${edge.contribution_inr < 0 ? 'from' : 'to'} revenue` : ''}${share}`, tone: edge.contribution_inr < 0 ? 'down' : 'up' }
}

const barStages: { stage: string; label: string }[] = [
  { stage: 'traffic', label: 'Traffic' }, { stage: 'conversion', label: 'Conversion' },
  { stage: 'units', label: 'Units per order' }, { stage: 'basket', label: 'Price per unit' },
]

// Segment widths from absolute ₹ effect. Percentages are whole numbers that sum to exactly 100
// (largest-remainder rounding), so the labels never disagree with the caption.
export function revenueBarSegments(story: KpiStory) {
  const found = barStages.flatMap(item => {
    const edge = story.edges.find(candidate => candidate.stage === item.stage)
    return edge ? [{ ...item, inr: edge.contribution_inr }] : []
  })
  const total = found.reduce((sum, item) => sum + Math.abs(item.inr), 0)
  if (!found.length || total <= 0) return []
  const raw = found.map(item => Math.abs(item.inr) / total * 100)
  const floors = raw.map(Math.floor)
  let remainder = 100 - floors.reduce((sum, value) => sum + value, 0)
  raw.map((value, index) => ({ index, frac: value - floors[index] })).sort((a, b) => b.frac - a.frac).forEach(item => { if (remainder-- > 0) floors[item.index] += 1 })
  return found.map((item, index) => ({ ...item, percent: floors[index], tone: Math.abs(item.inr) < NO_EFFECT ? 'none' : item.inr < 0 ? 'down' : 'up' }))
}

export default function KpiFlow({ story, onSelect }: { story: KpiStory | null; onSelect: (kpiId: string) => void }) {
  if (!story) return <section className="kpi-connect card"><h2>How the KPIs connect</h2><p>Not available for this older run.</p></section>
  const nodes = new Map(story.nodes.map(node => [node.kpi_id, node]))
  const segments = revenueBarSegments(story)
  const totalChange = story.revenue_delta ?? segments.reduce((sum, item) => sum + item.inr, 0)
  const drivers = story.cause_chains.slice(0, 3)
  return <section className="kpi-connect card" aria-labelledby="kpi-connect-heading">
    <div className="kpi-connect-heading"><div><span className="eyebrow">One connected story</span><h2 id="kpi-connect-heading">How the KPIs connect</h2></div></div>
    {/* The explanation expands inline, so it never covers the content below. */}
    <details className="kpi-connect-info"><summary>ⓘ How to read this</summary><p>Traffic and conversion create orders; orders become units; units times price become revenue. Each arrow shows how much of the revenue change came from that step, so a drop in orders caused by lower traffic is counted once, not as a second loss. Driver links are statistical evidence; they are not proof of cause unless a causal test verifies them.</p></details>
    <p className="kpi-connect-headline">{headline(story)}</p>
    {story.missing_stages.length > 0 && <p className="kpi-connect-missing">Missing stages: {story.missing_stages.map(name).join(', ')}. The available totals determine the displayed bridge.</p>}
    <div className="kpi-driver-row"><span className="kpi-driver-label">Likely drivers</span>{drivers.length ? drivers.map(chain => <span className="kpi-driver-chip" key={chain.driver_id}>{name(chain.driver_id)}{chain.shared_cause ? ' · shared cause' : ''}</span>) : <span className="kpi-driver-chip muted">No driver with enough confidence</span>}</div>
    <div className="kpi-connect-flow" aria-label="KPI relationship flow">
      {sequence.map((id, index) => {
        const node = nodes.get(id)
        const edge = id === 'basket' ? story.edges.find(item => item.stage === 'basket') : id === 'orders' ? undefined : story.edges.find(item => item.from === id && item.stage !== 'basket')
        const basketChange = story.edges.find(item => item.stage === 'basket')?.factor_percent_change
        const effect = effectLine(id, edge)
        const tone = id === 'basket' ? basketChange == null || Math.abs(basketChange) < 5 ? 'normal' : basketChange < 0 ? 'down' : 'up' : node?.status ?? 'normal'
        return <div className="kpi-flow-step" key={id}>
          <button type="button" className={`kpi-flow-node ${tone}`} onClick={() => onSelect(id === 'basket' ? 'net_sales_revenue' : id)} disabled={id !== 'basket' && (!node || node.missing)} aria-label={`Select ${name(id)} detail`}>
            <small>{name(id)}</small><strong>{id === 'basket' ? basketChange == null ? '—' : signedPercent(basketChange) : node?.percent_change == null ? '—' : signedPercent(node.percent_change)}</strong>
            <span>{nodeLabel(id, story, node)}</span>
            {effect && <span className={`kpi-flow-effect ${effect.tone}`}>{effect.text}</span>}
          </button>
          {index < sequence.length - 1 && <div className="kpi-flow-arrow" aria-hidden="true"><i /></div>}
        </div>
      })}
    </div>
    <div className="kpi-revenue-bar">
      <h3>Where the revenue change came from</h3>
      {segments.length ? <>
        <div className="kpi-bar-track" role="img" aria-label={`Where the revenue change came from: ${segments.map(item => `${item.label} ${item.percent}%`).join(', ')}`}>
          {segments.filter(item => item.percent > 0).map(item => <div key={item.stage} className={`kpi-bar-segment ${item.tone}`} style={{ width: `${item.percent}%` }}>{item.percent >= 8 ? `${item.label} ${item.percent}%` : ''}</div>)}
        </div>
        <ul className="kpi-bar-legend">{segments.map(item => <li key={item.stage}><i className={item.tone} />{item.label} {item.percent}%</li>)}</ul>
        <p className="kpi-bar-caption">Segments add up to the total revenue change of {signedMoney(totalChange)}.</p>
      </> : <p className="kpi-bar-caption">The revenue split is not available for this run.</p>}
    </div>
    <div className="kpi-connect-actions"><h3>Act first</h3>{story.act_first.length ? <ol>{story.act_first.map(chain => <li key={chain.driver_id}><strong>{name(chain.driver_id)}</strong><span>via {chain.stages.map(name).join(' + ')} · potential {money(chain.recoverable_impact_inr)} · {(chain.attribution_confidence * 100).toFixed(0)}% confidence · {verdictLabel(chain.causal_verdict)} · Owner: {name(chain.owner)}{chain.stage_impacts.some(item => item.attribution_source_kpi !== chain.via_kpi) ? ' · downstream attribution proxy' : ''}</span></li>)}</ol> : <p>No driver reached the 35% confidence needed to recommend an action.</p>}</div>
  </section>
}
