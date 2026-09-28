'use client'

import type { CSSProperties } from 'react'
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

function arrowLabel(edge: KpiStory['edges'][number] | undefined): string {
  if (!edge) return ''
  if (Math.abs(edge.contribution_inr) < 0.5) return 'no effect'
  return `${signedMoney(edge.contribution_inr)}${edge.contribution_pct == null ? '' : ` · ${Math.abs(edge.contribution_pct).toFixed(0)}%`}`
}

export default function KpiFlow({ story, onSelect }: { story: KpiStory | null; onSelect: (kpiId: string) => void }) {
  if (!story) return <section className="kpi-connect card"><h2>How the KPIs connect</h2><p>Not available for this older run.</p></section>
  const nodes = new Map(story.nodes.map(node => [node.kpi_id, node]))
  const maxEffect = Math.max(1, ...story.edges.map(edge => Math.abs(edge.contribution_inr)))
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
        const width = edge ? 2 + Math.round(6 * Math.abs(edge.contribution_inr) / maxEffect) : 2
        const tone = id === 'basket' ? basketChange == null || Math.abs(basketChange) < 5 ? 'normal' : basketChange < 0 ? 'down' : 'up' : node?.status ?? 'normal'
        return <div className="kpi-flow-step" key={id}>
          <button type="button" className={`kpi-flow-node ${tone}`} onClick={() => onSelect(id === 'basket' ? 'net_sales_revenue' : id)} disabled={id !== 'basket' && (!node || node.missing)} aria-label={`Select ${name(id)} detail`}>
            <small>{name(id)}</small><strong>{id === 'basket' ? basketChange == null ? '—' : signedPercent(basketChange) : node?.percent_change == null ? '—' : signedPercent(node.percent_change)}</strong>
            <span>{nodeLabel(id, story, node)}</span>
          </button>
          {index < sequence.length - 1 && <div className="kpi-flow-arrow" style={{ '--edge-width': `${width}px` } as CSSProperties}><span>{arrowLabel(edge)}</span><i /></div>}
        </div>
      })}
    </div>
    <div className="kpi-connect-actions"><h3>Act first</h3>{story.act_first.length ? <ol>{story.act_first.map(chain => <li key={chain.driver_id}><strong>{name(chain.driver_id)}</strong><span>via {chain.stages.map(name).join(' + ')} · potential {money(chain.recoverable_impact_inr)} · {(chain.attribution_confidence * 100).toFixed(0)}% confidence · {verdictLabel(chain.causal_verdict)} · Owner: {name(chain.owner)}{chain.stage_impacts.some(item => item.attribution_source_kpi !== chain.via_kpi) ? ' · downstream attribution proxy' : ''}</span></li>)}</ol> : <p>No driver reached the 35% confidence needed to recommend an action.</p>}</div>
  </section>
}
