'use client'

import Link from 'next/link'
import { ArrowRight, MessageSquare, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../components/app-shell'
import { contextHref, reviewStateLabel, statusLabel } from '../../lib/presentation'

type Insight = { run_id: string; kpi_id: string; target_date: string; verdict?: string; confidence_status?: string; actual: number | null; delta: number | null; scope: { region: string; category: string }; review_state: string; owner: string }
type Feedback = { id: number; run_id: string; feedback_type: string; status: string; comments: string }

export default function InsightsPage() {
  const { persona, region, category, date } = useDemoContext()
  const [items, setItems] = useState<Insight[]>([])
  const [feedback, setFeedback] = useState<Feedback[]>([])
  const [loading, setLoading] = useState(true)
  const [reviewing, setReviewing] = useState<number | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    setError('')
    const identity = identityForPersona(persona)
    Promise.all([
      fetch(`${API_BASE}/api/insights?persona=${encodeURIComponent(persona)}&user_id=${identity}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Could not load insights'))),
      fetch(`${API_BASE}/api/feedback?user_id=${identity}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Could not load feedback'))),
    ]).then(([insights, feedbackPayload]) => {
      setItems(insights.items ?? [])
      setFeedback(feedbackPayload.items ?? [])
    }).catch(requestError => setError(requestError.message)).finally(() => setLoading(false))
  }, [persona])

  async function review(id: number, status: 'ACCEPTED' | 'REJECTED') {
    setReviewing(id)
    try {
      const response = await fetch(`${API_BASE}/api/feedback/${id}?user_id=demo-cfo`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) })
      if (!response.ok) throw new Error('Feedback review failed')
      setFeedback(current => current.map(item => item.id === id ? { ...item, status } : item))
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Feedback review failed')
    } finally {
      setReviewing(null)
    }
  }

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
      <section className="detail-grid">
        <article className="card detail-card"><span className="eyebrow">Feedback and corrections</span><h2>{feedback.filter(item => item.status === 'PENDING_REVIEW').length} pending review</h2>{feedback.slice(0, 5).map(item => <p key={item.id}><strong>{statusLabel(item.feedback_type)}</strong> · {item.comments || 'No comment'} <small>{reviewStateLabel(item.status)}</small>{item.status === 'PENDING_REVIEW' && <span className="feedback-actions"><button disabled={reviewing === item.id || persona !== 'CFO'} onClick={() => void review(item.id, 'ACCEPTED')}>Accept</button><button disabled={reviewing === item.id || persona !== 'CFO'} onClick={() => void review(item.id, 'REJECTED')}>Reject</button></span>}</p>)}{!feedback.length && <p>No feedback has been submitted yet.</p>}</article>
        <article className="card detail-card"><span className="eyebrow">Learning and evaluation</span><h2>Offline review only</h2><p>Accepted: {feedback.filter(item => item.status === 'ACCEPTED').length} · Rejected: {feedback.filter(item => item.status === 'REJECTED').length}</p><p>Stored feedback does not rewrite historical diagnoses or claim that the model learned.</p></article>
      </section>
    </>}
  </AppShell>
}
