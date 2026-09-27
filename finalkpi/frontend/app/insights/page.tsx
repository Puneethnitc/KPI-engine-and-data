'use client'

import Link from 'next/link'
import { ArrowRight, MessageSquare, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../components/app-shell'
import { contextHref, reviewStateLabel, statusLabel } from '../../lib/presentation'
import FeedbackReviewWorkspace from '../../components/feedback-review-workspace'

type Insight = { run_id: string; kpi_id: string; target_date: string; verdict?: string; confidence_status?: string; actual: number | null; delta: number | null; scope: { region: string; category: string }; review_state: string; owner: string }

export default function InsightsPage() {
  const { persona, region, category, date } = useDemoContext()
  const [items, setItems] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    const identity = identityForPersona(persona)
    fetch(`${API_BASE}/api/insights?persona=${encodeURIComponent(persona)}&user_id=${identity}`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error('Could not load insights')))
      .then(insights => {
      setItems(insights.items ?? [])
    }).catch(requestError => setError(requestError.message)).finally(() => setLoading(false))
  }, [persona])

  return <AppShell active="Insights" context="Saved investigations and review workspace">
    <div className="page-heading route-heading">
      <div><span className="eyebrow">Durable decision workspace</span><h1>Insights</h1><p>Saved runs, review state, feedback, and the limits of current evidence.</p></div>
      <span className="evidence-pill">{items.length} saved insights</span>
    </div>
    {error && <div className="alert error">{error}</div>}
    {loading ? <State><RefreshCw className="spin" /> Loading insight history…</State> : <>
      <section className="insight-feed">{items.map(item => {
        const itemContext = { persona, region: item.scope.region || region, category: item.scope.category || category, date: item.target_date || date }
        return <article className="card insight-item" key={item.run_id}>
          <div><span className="eyebrow">{statusLabel(item.kpi_id)}</span><h2>{statusLabel(item.verdict ?? 'Investigation')}</h2><p>{itemContext.region} · {itemContext.category} · {itemContext.date} · actual {item.actual ?? '—'} · delta {item.delta ?? '—'}</p><span className="status warn">{statusLabel(item.confidence_status ?? 'Evidence pending')}</span></div>
          <div className="insight-actions"><small>Owner: {statusLabel(item.owner)}<br />Review: {reviewStateLabel(item.review_state)}</small><Link className="icon-link" href={contextHref(`/performance/${item.run_id}`, itemContext)} aria-label="Open evidence"><ArrowRight size={16} /></Link><button className="icon-link" onClick={() => window.location.assign(contextHref('/', itemContext, { runId: item.run_id, assistant: 'open' }))} aria-label="Ask AI about this insight"><MessageSquare size={16} /></button></div>
        </article>
      })}</section>
      <FeedbackReviewWorkspace persona={persona} userId={identityForPersona(persona)} />
    </>}
  </AppShell>
}
