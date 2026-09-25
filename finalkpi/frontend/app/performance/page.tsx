'use client'

import Link from 'next/link'
import { AlertTriangle, ArrowRight, CheckCircle2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../components/app-shell'

type Investigation = { run_id: string; kpi_id: string; target_date: string; actual: number | null; expected: number | null; delta: number | null; is_material: boolean; detector_agreement?: string; reconciliation_status?: string; verdict?: string; confidence_status?: string; review_state: string; owner: string; scope: { region: string; category: string } }
const label = (id: string) => id.replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase())
const number = (value: number | null) => value == null ? '—' : value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
const pendingStates = new Set(['UNREVIEWED', 'AWAITING_REVIEW', 'PENDING_REVIEW'])
const staleStates = new Set(['CONTRADICTED', 'STALE', 'UNAVAILABLE_OR_MISSING', 'PARTIAL'])

export default function PerformancePage() {
  const { persona } = useDemoContext()
  const [items, setItems] = useState<Investigation[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  useEffect(() => { setLoading(true); fetch(`${API_BASE}/api/investigations?persona=${encodeURIComponent(persona)}&user_id=${identityForPersona(persona)}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Could not load investigations'))).then(payload => setItems(payload.items ?? [])).catch(requestError => setError(requestError.message)).finally(() => setLoading(false)) }, [persona])
  const material = items.filter(item => item.is_material).length
  const unresolved = items.filter(item => item.review_state !== 'APPROVED').length
  return <AppShell active="Performance" context="Investigation queue">
    <div className="page-heading route-heading"><div><span className="eyebrow">Decision queue</span><h1>Performance investigations</h1><p>Prioritized movements that need attention, verification, or approval.</p></div><span className="evidence-pill">{items.length} stored runs</span></div>
    <div className="summary-strip"><div><strong>{material}</strong><span>Material movements</span></div><div><strong>{items.filter(item => pendingStates.has(item.review_state)).length}</strong><span>Open investigations</span></div><div><strong>{items.filter(item => staleStates.has(item.reconciliation_status ?? '')).length}</strong><span>Source warnings</span></div><div><strong>{items.filter(item => item.review_state === 'PENDING_REVIEW').length}</strong><span>Awaiting review</span></div></div>
    {error && <div className="alert error"><AlertTriangle size={17} />{error}</div>}
    {loading ? <State><RefreshCw className="spin" /> Loading governed investigations…</State> : !items.length ? <State><CheckCircle2 size={20} /> No stored investigations yet. Run a diagnosis from Overview to populate this queue.</State> : <div className="table-wrap card"><table><caption className="sr-only">Prioritized investigation queue</caption><thead><tr><th>Priority</th><th>KPI</th><th>Actual</th><th>Expected</th><th>Delta</th><th>Materiality</th><th>Sources</th><th>Evidence</th><th>Owner</th><th>Review</th><th /></tr></thead><tbody>{items.map((item, index) => <tr key={item.run_id}><td><strong>{String(index + 1).padStart(2, '0')}</strong></td><td>{label(item.kpi_id)}</td><td>{number(item.actual)}</td><td>{number(item.expected)}</td><td className={(item.delta ?? 0) < 0 ? 'negative' : 'positive'}>{number(item.delta)}</td><td><span className={`status ${item.is_material ? 'warn' : 'ok'}`}>{item.is_material ? 'Material' : 'Non-material'}</span></td><td>{item.reconciliation_status ?? 'Not assessed'}</td><td>{item.confidence_status ?? item.verdict ?? 'Not assessed'}</td><td>{item.owner}</td><td>{item.review_state}</td><td><Link className="icon-link" href={`/performance/${item.run_id}`} aria-label={`Open ${label(item.kpi_id)} investigation`}><ArrowRight size={15} /></Link></td></tr>)}</tbody></table></div>}
  </AppShell>
}
