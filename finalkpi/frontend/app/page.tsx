'use client'

import { FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowRight, BarChart3, Bot, CheckCircle2,
  ChevronDown, CircleHelp, Database, GripVertical, LayoutDashboard,
  Maximize2, Minimize2, Moon, RefreshCw, Send, ShieldAlert, Sparkles,
  Sun, TrendingDown, X,
} from 'lucide-react'
import Link from 'next/link'
import { identityForPersona, useDemoContext } from '../components/app-shell'

type Movement = {
  actual_value: number
  expected_value: number
  delta: number
  is_material: boolean
  is_statistically_significant: boolean
  is_business_material: boolean
  detector_agreement?: string
  status: string
}

type Decomposition = {
  total_delta: number
  volume_effect: number
  price_effect: number
  mix_effect: number
  residual: number
  is_identity_held: boolean
}

type Candidate = {
  driver_id: string
  max_correlation: number
  optimal_lag_days: number
  sample_size: number
  driver_change_pct: number
  claim_type: string
}

type Result = {
  run_id: string
  kpi_id: string
  target_date: string
  as_of: string
  verdict: string
  segment: { region: string; category: string }
  movement_assessment?: Movement | null
  reconciliation_verdict?: { status: string; details?: { reason?: string }; gap_pct?: number | null } | null
  decomposition_status: string
  decomposition?: Decomposition | null
  correlational_candidates: Candidate[]
  driver_exclusions?: { driver_id: string; reason: string }[]
  causal_verdict?: string | null
  causal_verification?: { reason?: string } | null
  confidence?: { status: string; claim_type: string; reasons?: string[]; calibrated_probability?: number | null } | null
  decision_cards: { kind: string; recommendation: string; owner: string; status: string; expected_impact: number | null }[]
  narrative: string
  grounding_passed: boolean
  narrative_method?: string
}

type MarketingBrief = {
  summary: string
  first_weak_stage?: { label: string; stage: string; direction: string; material: boolean } | null
  funnel: { kpi_id: string; label: string; stage: string; actual: number | null; expected: number | null; delta: number | null; direction: string; material: boolean; status: string }[]
  ranked_insights: { kpi_id: string; label: string; stage: string; actual: number | null; delta: number | null; direction: string; material: boolean; confidence_status: string; source_freshness: string; narrative: string }[]
  uncertainty: string[]
  method: string
}

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  text: string
  citations?: { source_path: string; evidence_type: string; line_or_row_ref?: string }[]
  limitations?: string[]
}

type AssistantMode = 'closed' | 'opening' | 'open' | 'minimized'
type RegisteredKpi = { kpi_id: string; version: number; definition: string; unit: string; dimensions: string[] }

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/backend'
type KpiId = string

function kpiLabel(id: string) { return id.replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase()) }
function kpiIcon(id: string) { return id.includes('revenue') ? TrendingDown : id === 'orders' || id.includes('units') ? BarChart3 : Activity }
function isRatioUnit(unit: string) { return unit === 'ratio' || unit === 'orders_per_visit' || unit.endsWith('_rate') }

const driverLabels: Record<string, string> = {
  traffic_drop: 'Traffic movement',
  ad_spend_drop: 'Ad-spend movement',
  checkout_latency_spike: 'Checkout latency',
  competitor_price_cut: 'Competitor pricing',
  stockout: 'Stock availability',
}

function formatValue(value: number | null | undefined, unit: string) {
  if (value == null || !Number.isFinite(value)) return '—'
  if (isRatioUnit(unit)) return `${(value * 100).toFixed(2)}%`
  if (unit === 'INR') return `₹${Math.abs(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}

function formatDelta(value: number | null | undefined, unit: string) {
  if (value == null || !Number.isFinite(value)) return '—'
  const scaled = isRatioUnit(unit) ? value * 100 : value
  const amount = Math.abs(scaled).toLocaleString('en-IN', { maximumFractionDigits: 2 })
  return `${scaled < 0 ? '−' : '+'}${unit === 'INR' ? '₹' : ''}${amount}${isRatioUnit(unit) ? ' pp' : ''}`
}

function titleCase(value?: string | null) {
  return value ? value.toLowerCase().replaceAll('_', ' ').replace(/(^|\s)\S/g, letter => letter.toUpperCase()) : 'Not assessed'
}

function evidenceTone(status?: string | null) {
  if (!status || status.includes('INSUFFICIENT') || status.includes('NOT_')) return 'limited'
  if (status.includes('CONTRADICTED') || status.includes('INCONCLUSIVE')) return 'warning'
  return 'good'
}

function Composer({ value, setValue, submit, panel = false, disabled = false }: {
  value: string
  setValue: (value: string) => void
  submit: () => void
  panel?: boolean
  disabled?: boolean
}) {
  const ref = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (!ref.current) return
    ref.current.style.height = 'auto'
    ref.current.style.height = `${Math.min(ref.current.scrollHeight, 120)}px`
  }, [value])

  return <div className={panel ? 'assistant-composer-wrap' : 'floating-composer-wrap'}>
    {!panel && <div className="prompt-chips">
      <button onClick={() => setValue('Why did revenue move?')}>Why did revenue move?</button>
      <button onClick={() => setValue('Which marketing lever should I review next?')}>Which lever should I review?</button>
    </div>}
    <form className="composer" onSubmit={(event: FormEvent) => { event.preventDefault(); submit() }}>
      <Sparkles size={19} />
      <textarea ref={ref} rows={1} value={value} onChange={event => setValue(event.target.value)}
        placeholder="Ask about your marketing performance…" aria-label="Ask the KPI assistant"
        onKeyDown={event => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            submit()
          }
        }} />
      <button type="submit" disabled={disabled || !value.trim()} aria-label="Send question"><Send size={17} /></button>
    </form>
    {!panel && <small>Answers are grounded in the selected engine run and its available evidence.</small>}
  </div>
}

export default function Page() {
  const { ready, persona, setPersona, region, setRegion, category, setCategory, date, setDate, theme, setTheme } = useDemoContext()
  const [registeredKpis, setRegisteredKpis] = useState<RegisteredKpi[]>([])
  const [selected, setSelected] = useState<KpiId>('net_sales_revenue')
  const [regions, setRegions] = useState<string[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [dates, setDates] = useState<string[]>([])
  const [results, setResults] = useState<Record<string, Result>>({})
  const [marketingBrief, setMarketingBrief] = useState<MarketingBrief | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [assistantMode, setAssistantMode] = useState<AssistantMode>('closed')
  const [panelWidth, setPanelWidth] = useState(410)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [asking, setAsking] = useState(false)
  const conversationEnd = useRef<HTMLDivElement>(null)

  const result = results[selected]
  const kpi = registeredKpis.find(item => item.kpi_id === selected) ?? registeredKpis[0] ?? { kpi_id: selected, unit: 'count', version: 1, definition: '', dimensions: [] }
  const selectedKpiLabel = kpiLabel(kpi.kpi_id)
  const movement = result?.movement_assessment
  const decomposition = result?.decomposition
  const isAssistantOpen = assistantMode === 'opening' || assistantMode === 'open'

  useEffect(() => { conversationEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, asking])
  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get('runId')
    if (!runId) return
    fetch(`${API_BASE}/api/diagnoses/${encodeURIComponent(runId)}?user_id=${identityForPersona(persona)}`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error('The selected insight is unavailable to this identity.')))
      .then(payload => {
        const loaded = payload.result ?? payload
        setSelected(loaded.kpi_id)
        setResults(current => ({ ...current, [loaded.kpi_id]: loaded }))
        setAssistantMode('open')
      })
      .catch(requestError => setError(requestError instanceof Error ? requestError.message : 'The selected insight is unavailable.'))
  }, [persona])

  async function loadMetadata() {
    try {
      const [filterResponse, kpiResponse] = await Promise.all([fetch(`${API_BASE}/api/filters`, { cache: 'no-store' }), fetch(`${API_BASE}/api/kpis`, { cache: 'no-store' })])
      if (!filterResponse.ok || !kpiResponse.ok) throw new Error('Could not load KPI metadata')
      const [payload, kpiPayload] = await Promise.all([filterResponse.json(), kpiResponse.json()])
      const values = payload.allowed_values ?? {}
      const nextKpis: RegisteredKpi[] = kpiPayload.items ?? []
      setRegisteredKpis(nextKpis)
      setRegions(values.region ?? payload.regions ?? [])
      setCategories(values.category ?? payload.categories ?? [])
      setDates(payload.dates ?? [])
      if (nextKpis.length && !nextKpis.some(item => item.kpi_id === selected)) setSelected(nextKpis[0].kpi_id)
      if (payload.default) {
        const params = new URLSearchParams(window.location.search)
        setRegion(params.get('region') ?? payload.default.region ?? region)
        setCategory(params.get('category') ?? payload.default.category ?? category)
        setDate(params.get('date') ?? payload.default.date ?? date)
      }
    } catch {
      // The diagnosis request below displays the actionable connectivity error.
    }
  }

  async function diagnose() {
    setLoading(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/api/diagnoses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kpis: ['all'], target_date: date, region, category, persona, user_id: identityForPersona(persona) }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'Diagnosis failed')
      setResults(payload.results ?? {})
      setMarketingBrief(payload.marketing_brief ?? null)
      setMessages([])
      setConversationId(undefined)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not reach the KPI backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadMetadata() }, [])
  useEffect(() => { if (ready) void diagnose() }, [ready, region, category, date, persona])
  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get('runId')
    if (!runId) return
    fetch(`${API_BASE}/api/diagnoses/${encodeURIComponent(runId)}?user_id=${identityForPersona(persona)}`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error('The selected insight is not available to this identity.')))
      .then(payload => {
        const run = payload.result ?? payload
        setResults(current => ({ ...current, [run.kpi_id]: run }))
        setSelected(run.kpi_id as KpiId)
        if (new URLSearchParams(window.location.search).get('assistant') === 'open') setAssistantMode('open')
      })
      .catch(requestError => setError(requestError instanceof Error ? requestError.message : 'Could not load the selected insight'))
  }, [persona])

  async function askQuestion(prefill?: string) {
    const question = (prefill ?? draft).trim()
    if (!question || asking) return
    if (!result) {
      setError('Run a diagnosis before asking the assistant.')
      return
    }
    if (assistantMode === 'closed' || assistantMode === 'minimized') {
      setAssistantMode('opening')
      window.setTimeout(() => setAssistantMode('open'), 420)
    }
    setDraft('')
    setMessages(current => [...current, { id: crypto.randomUUID(), role: 'user', text: question }])
    setAsking(true)
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ run_id: result.run_id, conversation_id: conversationId, question, persona, user_id: identityForPersona(persona) }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'Grounded chat failed')
      setConversationId(payload.conversation_id ?? conversationId)
      setMessages(current => [...current, {
        id: crypto.randomUUID(), role: 'assistant', text: payload.answer,
        citations: payload.citations, limitations: payload.limitations,
      }])
    } catch (requestError) {
      setMessages(current => [...current, {
        id: crypto.randomUUID(), role: 'assistant',
        text: requestError instanceof Error ? requestError.message : 'The assistant could not answer this question.',
      }])
    } finally {
      setAsking(false)
    }
  }

  function beginResize(event: ReactPointerEvent<HTMLButtonElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    const startX = event.clientX
    const startWidth = panelWidth
    const move = (pointerEvent: PointerEvent) => setPanelWidth(Math.max(340, Math.min(600, startWidth + startX - pointerEvent.clientX)))
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }

  const contributionRows = useMemo(() => {
    if (!decomposition?.is_identity_held) return []
    return [
      { label: selected === 'orders' ? 'Traffic effect' : 'Volume effect', value: decomposition.volume_effect },
      { label: selected === 'orders' ? 'Conversion effect' : 'Rate / price effect', value: decomposition.price_effect },
      ...(decomposition.mix_effect ? [{ label: 'Mix effect', value: decomposition.mix_effect }] : []),
    ]
  }, [decomposition, selected])
  const contributionTotal = contributionRows.reduce((total, item) => total + Math.abs(item.value), 0) || 1
  const materialCount = Object.values(results).filter(item => item.movement_assessment?.is_material).length

  return <div className={`app-shell ${theme}`} style={{ '--assistant-width': `${panelWidth}px` } as React.CSSProperties}>
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><BarChart3 size={17} /></span><span>KPI <strong>Intelligence</strong></span></div>
      <nav className="main-nav" aria-label="Primary navigation"><Link className="active" href="/">Overview</Link><Link href="/performance">Performance</Link><Link href="/campaigns">Campaigns</Link><Link href="/insights">Insights</Link></nav>
      <div className="top-actions"><span className="freshness"><i /> Engine data</span><label className="persona-control">Demo persona<select value={persona} onChange={event => { setMessages([]); setConversationId(undefined); setPersona(event.target.value) }}><option value="marketing_manager">Marketing Manager</option><option value="CFO">CFO</option></select></label><button className="theme-button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme">{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button><span className="avatar">{persona === 'CFO' ? 'CF' : 'MM'}</span></div>
    </header>

    <main className="workspace" data-ai={isAssistantOpen ? 'open' : assistantMode}>
      <section className="dashboard-column">
        <div className="page-heading">
          <div><span className="eyebrow"><LayoutDashboard size={14} /> {persona === 'CFO' ? 'Financial reviewer workspace' : 'Marketing manager workspace'}</span><h1>Performance overview</h1><p>What changed, what may explain it, and what to verify next.</p></div>
          <div className="filter-row">
            <label>Region<select value={region} onChange={event => setRegion(event.target.value)}>{regions.map(item => <option key={item}>{item}</option>)}</select><ChevronDown size={13} /></label>
            <label>Category<select value={category} onChange={event => setCategory(event.target.value)}>{categories.map(item => <option key={item}>{item}</option>)}</select><ChevronDown size={13} /></label>
            <label>Date<select value={date} onChange={event => setDate(event.target.value)}>{dates.slice(-120).map(item => <option key={item}>{item}</option>)}</select><ChevronDown size={13} /></label>
            <button className="run-button" disabled={!ready || loading} onClick={() => void diagnose()}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Run</button>
          </div>
        </div>

        <div className="context-strip"><strong>{region} · {category} · {date}</strong><span>{materialCount} of {registeredKpis.length} KPIs are material</span></div>
        {error && <div className="alert error"><ShieldAlert size={18} /><span>{error}</span></div>}
        {loading && <div className="alert"><Activity className="spin" size={18} /><span>Running the governed KPI engine across daily, weekly, and monthly sources…</span></div>}

        {marketingBrief && <section className="marketing-brief" aria-labelledby="briefing-title">
          <div className="briefing-lead"><div><span className="eyebrow">Marketing manager briefing</span><h2 id="briefing-title">What you need to know today</h2><p>{marketingBrief.summary}</p><small>{marketingBrief.first_weak_stage ? `First observed weak funnel stage: ${marketingBrief.first_weak_stage.label}${marketingBrief.first_weak_stage.material ? ' · material' : ''}` : 'No first weak stage established'}</small></div><span className="evidence-pill">{region} · {category} · {date}</span></div>
          <div className="funnel-strip" aria-label="Connected marketing funnel">{marketingBrief.funnel.map((stage, index) => {
            const unit = registeredKpis.find(item => item.kpi_id === stage.kpi_id)?.unit ?? 'count'
            return <article className={`funnel-stage ${stage.direction}`} key={stage.kpi_id}><small>{stage.stage}</small><strong>{formatValue(stage.actual, unit)}</strong><span>{formatDelta(stage.delta, unit)} · {stage.material ? 'material' : stage.status === 'OK' ? 'not material' : titleCase(stage.status)}</span><b>{stage.label}</b>{index < marketingBrief.funnel.length - 1 && <ArrowRight className="funnel-arrow" size={15} />}</article>
          })}</div>
          <div className="brief-insights">{marketingBrief.ranked_insights.slice(0, 5).map((insight, index) => <article className="brief-insight" key={insight.kpi_id}><span className="brief-rank">{String(index + 1).padStart(2, '0')}</span><div><strong>{insight.label}: {insight.direction === 'up' ? 'improved' : insight.direction === 'down' ? 'declined' : 'moved'}</strong><p>{insight.narrative || `${formatDelta(insight.delta, registeredKpis.find(item => item.kpi_id === insight.kpi_id)?.unit ?? 'count')} observed in ${insight.stage}.`}</p><small>{insight.material ? 'Material' : 'Not material'} · {titleCase(insight.confidence_status)} · as of {insight.source_freshness}</small></div><button onClick={() => { setSelected(insight.kpi_id as KpiId); setDraft(`Explain the ${insight.label} movement and supporting evidence.`); setAssistantMode('open') }} aria-label={`Investigate ${insight.label}`}><ArrowRight size={15} /></button></article>)}</div>
          {marketingBrief.uncertainty.length > 0 && <p className="brief-limits">Evidence limits: {marketingBrief.uncertainty.join(' · ')}</p>}
          <small className="method-note">{marketingBrief.method}. Co-movement is not proof of causality and related KPI movements are not summed as separate causes.</small>
        </section>}

        <section className="kpi-selector" aria-label="Registered KPIs">
          {registeredKpis.map(item => {
            const itemResult = results[item.kpi_id]
            const itemMovement = itemResult?.movement_assessment
            const Icon = kpiIcon(item.kpi_id)
            return <button key={item.kpi_id} className={selected === item.kpi_id ? 'kpi-tile active' : 'kpi-tile'} onClick={() => setSelected(item.kpi_id)}><span><Icon size={16} />{kpiLabel(item.kpi_id)}</span><strong>{formatValue(itemMovement?.actual_value, item.unit)}</strong><small className={(itemMovement?.delta ?? 0) < 0 ? 'negative' : 'positive'}>{formatDelta(itemMovement?.delta, item.unit)} vs baseline</small></button>
          })}
        </section>

        <section className="hero-card card">
          <div className="hero-summary"><span className="eyebrow">Primary observed KPI</span><h2>{selectedKpiLabel}</h2><div className="hero-number">{formatValue(movement?.actual_value, kpi.unit)}</div><p className={(movement?.delta ?? 0) < 0 ? 'negative' : 'positive'}><ArrowDownRight size={16} /> {formatDelta(movement?.delta, kpi.unit)} versus the engine baseline</p><span className={`evidence-pill ${movement?.is_material ? 'warning' : 'good'}`}>{movement?.is_material ? 'Material movement' : 'Not material'}</span></div>
          <div className="comparison-chart" role="img" aria-label={`${selectedKpiLabel} actual compared with expected baseline`}><div className="chart-head"><span>Actual vs expected</span><small>No invented trend series</small></div><div className="bar-row"><span>Expected</span><i><b style={{ width: '100%' }} /></i><strong>{formatValue(movement?.expected_value, kpi.unit)}</strong></div><div className="bar-row actual"><span>Actual</span><i><b style={{ width: `${movement?.expected_value ? Math.min(100, Math.abs((movement.actual_value / movement.expected_value) * 100)) : 0}%` }} /></i><strong>{formatValue(movement?.actual_value, kpi.unit)}</strong></div><div className="chart-caption"><Database size={14} /> Target date {date} · As of {result?.as_of ? new Date(result.as_of).toLocaleString('en-IN') : 'awaiting run'}</div></div>
        </section>

        <div className="section-heading"><div><h2>What explains the movement?</h2><p>Accounting contributions and diagnostic indicators are deliberately separated.</p></div><button onClick={() => void askQuestion('Explain the difference between contributions and diagnostic drivers.')}><CircleHelp size={15} /> Ask AI</button></div>

        <section className="explanation-grid">
          <article className="card contribution-card"><div className="card-heading"><div><span className="eyebrow">Quantified contribution</span><h3>Accounting bridge</h3></div><span className={`evidence-pill ${decomposition?.is_identity_held ? 'good' : 'limited'}`}>{decomposition?.is_identity_held ? 'Identity reconciled' : titleCase(result?.decomposition_status)}</span></div>{contributionRows.length ? <><div className="donut-wrap"><div className="donut" style={{ '--slice': `${Math.round((Math.abs(contributionRows[0]?.value ?? 0) / contributionTotal) * 100)}%` } as React.CSSProperties}><span><strong>{formatDelta(decomposition?.total_delta, kpi.unit)}</strong><small>total change</small></span></div><div className="contribution-list">{contributionRows.map((item, index) => <div key={item.label}><i className={`swatch swatch-${index}`} /><span>{item.label}<small>{Math.round((Math.abs(item.value) / contributionTotal) * 100)}% of quantified movement</small></span><strong>{formatDelta(item.value, kpi.unit)}</strong></div>)}</div></div><p className="method-note">These values add to the observed movement. They are an accounting explanation, not proof of operational cause.</p></> : <div className="empty-state">No exact contribution bridge is available for this KPI.</div>}</article>

          <article className="card driver-card"><div className="card-heading"><div><span className="eyebrow">Diagnostic drivers</span><h3>Ranked indicators</h3></div><span className="evidence-pill limited">Not attribution</span></div>{result?.correlational_candidates?.length ? <div className="driver-list">{result.correlational_candidates.slice(0, 4).map(candidate => <div key={candidate.driver_id} className="driver-row"><div><strong>{driverLabels[candidate.driver_id] ?? titleCase(candidate.driver_id)}</strong><span>Correlation {candidate.max_correlation.toFixed(2)} · lag {candidate.optimal_lag_days}d · n={candidate.sample_size}</span></div><div className="association"><i style={{ width: `${Math.min(100, Math.abs(candidate.max_correlation) * 100)}%` }} /></div><small>{titleCase(candidate.claim_type)}</small></div>)}</div> : <div className="empty-state">No diagnostic driver passed the ranking checks for this run.</div>}<p className="method-note">Indicators help decide what to investigate. Their association is not a monetary contribution or a causal claim.</p></article>
        </section>

        <section className="insight-grid"><article className="card narrative-card"><span className="eyebrow">Evidence-bound narrative</span><h3>{result?.verdict ? titleCase(result.verdict) : 'Awaiting analysis'}</h3><p>{result?.narrative ?? 'Run the engine to generate a traceable explanation.'}</p><div className="meta-line"><CheckCircle2 size={15} /> Grounding {result?.grounding_passed ? 'passed' : 'not established'} · {titleCase(result?.narrative_method)}</div></article><article className="card confidence-card"><div className="card-heading"><div><span className="eyebrow">Confidence and limits</span><h3>{titleCase(result?.confidence?.status)}</h3></div><span className={`evidence-pill ${evidenceTone(result?.confidence?.status)}`}>{titleCase(result?.confidence?.claim_type)}</span></div><p>{result?.causal_verification?.reason ?? result?.confidence?.reasons?.[0] ?? 'No causal confidence has been established.'}</p><div className="confidence-checks"><span className={movement?.is_statistically_significant ? 'pass' : ''}>Statistical materiality</span><span className={movement?.is_business_material ? 'pass' : ''}>Business materiality</span><span className={result?.grounding_passed ? 'pass' : ''}>Narrative grounding</span></div></article></section>

        <section className="card action-card"><div className="section-heading compact"><div><span className="eyebrow">Recommended next step</span><h2>Action within marketing decision rights</h2></div></div>{result?.decision_cards?.length ? <div className="action-list">{result.decision_cards.slice(0, 3).map((action, index) => <article key={`${action.kind}-${index}`}><span>0{index + 1}</span><div><h3>{titleCase(action.kind)}</h3><p>{action.recommendation}</p><small>Owner: {action.owner} · Status: {titleCase(action.status)} · Expected impact: {action.expected_impact == null ? 'not estimated' : formatValue(action.expected_impact, kpi.unit)}</small></div><button onClick={() => void askQuestion(`Explain the evidence and constraints for this action: ${action.recommendation}`)}><ArrowRight size={16} /></button></article>)}</div> : <div className="empty-state">The engine is abstaining from action until the evidence is sufficient.</div>}</section>

        <footer className="source-footer"><span>Run {result?.run_id ?? '—'}</span><span>Source status: {titleCase(result?.reconciliation_verdict?.status)}</span><span>Persona: {persona === 'CFO' ? 'CFO' : 'Marketing manager'}</span></footer>
      </section>

      {assistantMode === 'closed' && <Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} disabled={loading} />}
      {assistantMode === 'minimized' && <button className="restore-pill" onClick={() => setAssistantMode('open')}><Bot size={17} /> Ask KPI Assistant</button>}

      {isAssistantOpen && <aside className="assistant-panel" aria-label="KPI assistant"><button className="resize-handle" aria-label="Resize assistant" onPointerDown={beginResize}><GripVertical size={17} /></button><header className="assistant-header"><div className="assistant-title"><span><Bot size={18} /></span><div><strong>KPI Assistant</strong><small>{selectedKpiLabel} · {region} · {date}</small></div></div><div className="assistant-actions"><button onClick={() => setPanelWidth(panelWidth === 600 ? 410 : 600)} aria-label="Toggle assistant width"><Maximize2 size={16} /></button><button onClick={() => setAssistantMode('minimized')} aria-label="Minimize assistant"><Minimize2 size={16} /></button><button onClick={() => { setAssistantMode('closed'); setMessages([]); setConversationId(undefined) }} aria-label="Close assistant"><X size={18} /></button></div></header><div className="assistant-context"><Sparkles size={14} /> Grounded in run {result?.run_id ?? 'not available'}</div><div className="conversation">{!messages.length && <div className="assistant-empty"><span><Sparkles size={22} /></span><h2>Ask your marketing analyst</h2><p>I’ll explain the movement, distinguish evidence from hypotheses, and surface safe next steps.</p></div>}{messages.map(message => <article key={message.id} className={`message ${message.role}`}><p>{message.text}</p>{message.citations?.length ? <details><summary>{message.citations.length} evidence reference{message.citations.length === 1 ? '' : 's'}</summary>{message.citations.map((citation, index) => <small key={`${citation.source_path}-${index}`}>{citation.evidence_type}: {citation.source_path}{citation.line_or_row_ref ? ` · ${citation.line_or_row_ref}` : ''}</small>)}</details> : null}{message.limitations?.length ? <div className="limitations"><strong>Limits</strong>{message.limitations.map(item => <small key={item}>{item}</small>)}</div> : null}</article>)}{asking && <div className="thinking"><i /><i /><i /></div>}<div ref={conversationEnd} /></div><div className="assistant-suggestions">{['What changed?', 'Is the cause proven?', 'What should I verify next?'].map(item => <button key={item} onClick={() => void askQuestion(item)}>{item}</button>)}</div><Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} panel disabled={asking} /></aside>}
    </main>
  </div>
}
