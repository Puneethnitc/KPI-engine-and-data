'use client'

import Link from 'next/link'
import { AlertTriangle, ArrowRight, CheckCircle2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../components/app-shell'
import { contextHref, isAwaitingReview, isReviewPending, isSourceWarning, reviewStateLabel, statusLabel } from '../../lib/presentation'

type Investigation = { run_id: string; kpi_id: string; target_date: string; actual: number | null; expected: number | null; delta: number | null; is_material: boolean; detector_agreement?: string; reconciliation_status?: string; verdict?: string; confidence_status?: string; review_state: string; owner: string; scope: { region: string; category: string } }
const label = (id: string) => id.replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase())
const number = (value: number | null, unit: string, delta = false) => {
  if (value == null) return '—'
  if (unit === 'INR') return `${delta ? (value < 0 ? '−' : '+') : ''}₹${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  if (unit === 'orders_per_visit' || unit.endsWith('_rate')) return `${(value * 100).toFixed(2)}${delta ? ' pp' : '%'}`
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2, notation: Math.abs(value) >= 10000 ? 'compact' : 'standard' })
}
export default function PerformancePage() {
  const { persona, region, category, date, options } = useDemoContext()
  const [items, setItems] = useState<Investigation[]>([])
  const [units, setUnits] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [materialOnly, setMaterialOnly] = useState(false)
  const [awaitingOnly, setAwaitingOnly] = useState(false)
  const [sourceWarningOnly, setSourceWarningOnly] = useState(false)
  const [kpiFilter, setKpiFilter] = useState('')
  const [ownerFilter, setOwnerFilter] = useState('')
  const [confidenceFilter, setConfidenceFilter] = useState('')
  useEffect(() => { if (!options.dates.length) return; setLoading(true); Promise.all([fetch(`${API_BASE}/api/investigations?persona=${encodeURIComponent(persona)}&user_id=${identityForPersona(persona)}`), fetch(`${API_BASE}/api/kpis`)]).then(async ([runsResponse, kpisResponse]) => { if (!runsResponse.ok || !kpisResponse.ok) throw new Error('Could not load the governed investigation metadata'); const [runs, kpis] = await Promise.all([runsResponse.json(), kpisResponse.json()]); setItems((runs.items ?? []).filter((item: Investigation) => item.scope.region === region && item.scope.category === category && item.target_date === date)); setUnits(Object.fromEntries((kpis.items ?? []).map((item: { kpi_id: string; unit: string }) => [item.kpi_id, item.unit]))) }).catch(requestError => setError(requestError.message)).finally(() => setLoading(false)) }, [persona, region, category, date, options.dates.length])
  const visibleItems = items.filter(item =>
    (!materialOnly || item.is_material) &&
    (!awaitingOnly || isAwaitingReview(item.review_state)) &&
    (!sourceWarningOnly || isSourceWarning(item.reconciliation_status)) &&
    (!kpiFilter || item.kpi_id === kpiFilter) &&
    (!ownerFilter || item.owner === ownerFilter) &&
    (!confidenceFilter || item.confidence_status === confidenceFilter),
  )
  const material = visibleItems.filter(item => item.is_material).length
  const unresolved = visibleItems.filter(item => isReviewPending(item.review_state)).length
  const warningCount = visibleItems.filter(item => isSourceWarning(item.reconciliation_status)).length
  const awaitingCount = visibleItems.filter(item => isAwaitingReview(item.review_state)).length
  const owners = [...new Set(items.map(item => item.owner).filter(Boolean))].sort()
  return <AppShell active="Performance" context="Investigation queue">
    <div className="page-heading route-heading"><div><span className="eyebrow">Decision queue</span><h1>Performance investigations</h1><p>Prioritized movements for {region} · {category} · {date}</p></div><span className="evidence-pill">{visibleItems.length} visible · {items.length} total</span></div>
    <div className="queue-filters"><label><input type="checkbox" checked={materialOnly} onChange={event => setMaterialOnly(event.target.checked)} /> Material only</label><label><input type="checkbox" checked={awaitingOnly} onChange={event => setAwaitingOnly(event.target.checked)} /> Awaiting review</label><label><input type="checkbox" checked={sourceWarningOnly} onChange={event => setSourceWarningOnly(event.target.checked)} /> Source warning</label><label>KPI<select value={kpiFilter} onChange={event => setKpiFilter(event.target.value)}><option value="">All KPIs</option>{[...new Set(items.map(item => item.kpi_id))].map(id => <option key={id} value={id}>{label(id)}</option>)}</select></label><label>Owner<select value={ownerFilter} onChange={event => setOwnerFilter(event.target.value)}><option value="">All owners</option>{owners.map(owner => <option key={owner} value={owner}>{statusLabel(owner)}</option>)}</select></label><label>Confidence<select value={confidenceFilter} onChange={event => setConfidenceFilter(event.target.value)}><option value="">All evidence states</option>{[...new Set(items.map(item => item.confidence_status).filter((value): value is string => Boolean(value)))].map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label></div>
    <div className="summary-strip"><div><strong>{material}</strong><span>Material movements</span></div><div><strong>{unresolved}</strong><span>Open investigations</span></div><div><strong>{warningCount}</strong><span>Source warnings</span></div><div><strong>{awaitingCount}</strong><span>Awaiting review</span></div></div>
    {error && <div className="alert error"><AlertTriangle size={17} />{error}</div>}
    {loading ? <State><RefreshCw className="spin" /> Loading governed investigations…</State> : !items.length ? <State><CheckCircle2 size={20} /> No stored investigations yet. Run a diagnosis from Overview to populate this queue.</State> : !visibleItems.length ? <State>No investigations match the current filters.</State> : <div className="table-wrap card"><table><caption className="sr-only">Prioritized investigation queue</caption><thead><tr><th>Priority</th><th>KPI</th><th>Actual</th><th>Expected</th><th>Delta</th><th>Materiality</th><th>Sources</th><th>Evidence</th><th>Owner</th><th>Review</th><th /></tr></thead><tbody>{visibleItems.map((item, index) => { const unit = units[item.kpi_id] ?? 'count'; return <tr key={item.run_id}><td data-label="Priority"><strong>{String(index + 1).padStart(2, '0')}</strong></td><td data-label="KPI">{label(item.kpi_id)}</td><td data-label="Actual">{number(item.actual, unit)}</td><td data-label="Expected">{number(item.expected, unit)}</td><td data-label="Variance" className={(item.delta ?? 0) < 0 ? 'negative' : 'positive'}>{number(item.delta, unit, true)}</td><td data-label="Materiality"><span className={`status ${item.is_material ? 'warn' : 'ok'}`}>{item.is_material ? 'Material' : 'Non-material'}</span></td><td data-label="Sources">{statusLabel(item.reconciliation_status)}</td><td data-label="Evidence">{statusLabel(item.confidence_status ?? item.verdict)}</td><td data-label="Owner">{statusLabel(item.owner)}</td><td data-label="Review">{reviewStateLabel(item.review_state)}</td><td data-label="Details"><Link className="icon-link" href={contextHref(`/performance/${item.run_id}`, { persona, region, category, date })} aria-label={`Open ${label(item.kpi_id)} investigation`}><ArrowRight size={15} /></Link></td></tr>})}</tbody></table></div>}
  </AppShell>
}
