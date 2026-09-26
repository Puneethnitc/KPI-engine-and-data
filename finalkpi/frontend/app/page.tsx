'use client'

import { FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowRight, BarChart3, Bot, CheckCircle2, ChevronDown, CircleHelp,
  Database, GripVertical, LayoutDashboard, Maximize2, Minimize2, RefreshCw, Send,
  ShieldAlert, Sparkles, TrendingDown, X,
} from 'lucide-react'
import { AppHeader, identityForPersona, useDemoContext } from '../components/app-shell'
import { statusLabel } from '../lib/presentation'
import { CustomSelect } from '../components/ui/custom-select'
import { KpiTrendChart } from '../components/kpi-trend-chart'

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
  persona: string
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
  telemetry?: { model_call_count?: number; total_latency_ms?: number; estimated_cost?: number }
}

type MarketingBrief = {
  summary: string
  first_weak_stage?: { label: string; stage: string; direction: string; material: boolean } | null
  funnel: { kpi_id: string; label: string; stage: string; actual: number | null; expected: number | null; delta: number | null; direction: string; material: boolean; status: string }[]
  ranked_insights: { kpi_id: string; label: string; stage: string; actual: number | null; delta: number | null; direction: string; material: boolean; confidence_status: string; source_freshness: string; narrative: string }[]
  stories?: { id: string; title: string; what_changed: string; affected_kpis: string[]; business_impact: string; evidence_strength: string; confidence_status: string; recommended_action?: { recommendation: string; owner: string; expected_impact: number | null } | null; causal_boundary: string; technical_details?: string[] }[]
  positive_opportunity?: boolean
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
function statusLabelForBrief(value?: string | null) {
  if (!value) return 'Confidence not assessed'
  const state = value.toUpperCase()
  if (state === 'NOT_ASSESSED') return 'Confidence not assessed'
  if (state === 'INSUFFICIENT_EVIDENCE' || state === 'LOW') return 'Insufficient evidence'
  if (state === 'CONTRADICTED' || state === 'CONFLICTING_EVIDENCE') return 'Conflicting evidence'
  return statusLabel(state)
}

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
  const { ready, persona, region, setRegion, category, setCategory, date, setDate, theme, options } = useDemoContext()
  const [registeredKpis, setRegisteredKpis] = useState<RegisteredKpi[]>([])
  const [selected, setSelected] = useState<KpiId>('net_sales_revenue')
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
  async function loadMetadata() {
    try {
      const kpiResponse = await fetch(`${API_BASE}/api/kpis`, { cache: 'no-store' })
      if (!kpiResponse.ok) throw new Error('Could not load KPI metadata')
      const kpiPayload = await kpiResponse.json()
      const nextKpis: RegisteredKpi[] = kpiPayload.items ?? []
      setRegisteredKpis(nextKpis)
      if (nextKpis.length && !nextKpis.some(item => item.kpi_id === selected)) setSelected(nextKpis[0].kpi_id)
    } catch {
      setError('KPI metadata is unavailable. Filter choices may be incomplete.')
    }
  }

  async function diagnose() {
    if (!ready) return
    setLoading(true)
    setError('')
    const requestScope = { persona, region, category, target_date: date }
    if (process.env.NODE_ENV !== 'production' && (!options.regions.includes(region) || !options.categories.includes(category) || !options.dates.includes(date))) {
      const message = 'Visible filter scope is not present in backend filter metadata.'
      console.error(message, { requestScope, options })
      setError(message)
      setLoading(false)
      return
    }
    try {
      const response = await fetch(`${API_BASE}/api/diagnoses`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kpis: ['all'], target_date: date, region, category, persona, user_id: identityForPersona(persona) }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail ?? 'Diagnosis failed')
      const responseScope = payload.marketing_brief?.scope
      if (responseScope && (responseScope.region !== region || responseScope.category !== category || responseScope.target_date !== date)) {
        const message = 'Returned diagnosis scope does not match the visible filters.'
        console.error(message, { requestScope, responseScope })
        throw new Error(message)
      }
      const firstResult = Object.values(payload.results ?? {})[0] as Result | undefined
      const resultScope = firstResult ? { persona: firstResult.persona, region: firstResult.segment?.region, category: firstResult.segment?.category, target_date: firstResult.target_date } : undefined
      if (resultScope && (resultScope.persona !== persona || resultScope.region !== region || resultScope.category !== category || resultScope.target_date !== date)) {
        const message = 'Returned diagnosis does not match the visible filter scope.'
        console.error(message, { requestScope, resultScope })
        throw new Error(message)
      }
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
    const rows = [
      { label: selected === 'orders' ? 'Traffic effect' : 'Volume effect', value: decomposition.volume_effect },
      { label: selected === 'orders' ? 'Conversion effect' : 'Rate / price effect', value: decomposition.price_effect },
      ...(decomposition.mix_effect ? [{ label: 'Mix effect', value: decomposition.mix_effect }] : []),
    ]
    if (decomposition.residual && Math.abs(decomposition.residual) > 1e-4) {
      rows.push({ label: 'Residual / Unexplained effect', value: decomposition.residual })
    }
    return rows
  }, [decomposition, selected])
  const contributionTotal = contributionRows.reduce((total, item) => total + Math.abs(item.value), 0) || 1
  const materialCount = Object.values(results).filter(item => item.movement_assessment?.is_material).length
  const briefStories = marketingBrief ? (marketingBrief.stories ?? marketingBrief.ranked_insights.map(insight => ({
    id: `KPI_${insight.kpi_id}`,
    title: `${insight.label} ${insight.direction === 'up' ? 'improved' : insight.direction === 'down' ? 'declined' : 'moved'}`,
    what_changed: insight.narrative || `${insight.label} moved in the selected scope.`,
    affected_kpis: [insight.kpi_id],
    business_impact: insight.material ? 'Material business movement.' : 'Observed movement did not meet both materiality checks.',
    evidence_strength: insight.material ? 'Material movement' : 'Observed movement',
    confidence_status: insight.confidence_status,
    recommended_action: null,
    causal_boundary: 'Observed movement does not establish causal attribution.',
    technical_details: [insight.narrative, insight.confidence_status, insight.kpi_id],
  }))) : []
  const hasPositiveOpportunity = marketingBrief?.positive_opportunity ?? marketingBrief?.ranked_insights.some(insight => insight.direction === 'up') ?? false

  return <div className={`app-shell ${theme}`} style={{ '--assistant-width': `${panelWidth}px` } as React.CSSProperties}>
    <AppHeader active="Overview" />

    <main className="workspace" data-ai={isAssistantOpen ? 'open' : assistantMode}>
      <section className="dashboard-column">
        <div className="page-heading">
          <div><span className="eyebrow"><LayoutDashboard size={14} /> {persona === 'CFO' ? 'Financial reviewer workspace' : 'Marketing manager workspace'}</span><h1>Performance overview</h1><p>What changed, what may explain it, and what to verify next.</p></div>
          <div className="filter-row" style={{ display: 'flex', alignItems: 'flex-end', gap: '10px', flexWrap: 'wrap' }}>
            <div style={{ width: '130px' }}>
              <CustomSelect label="Region" ariaLabel="Region" value={region} onChange={setRegion} options={options.regions} />
            </div>
            <div style={{ width: '150px' }}>
              <CustomSelect label="Category" ariaLabel="Category" value={category} onChange={setCategory} options={options.categories} />
            </div>
            <div style={{ width: '140px' }}>
              <CustomSelect label="Date" ariaLabel="Date" value={date} onChange={setDate} options={options.dates} searchable />
            </div>
            <button className="run-button" style={{ minHeight: '40px', height: '40px' }} disabled={!ready || loading} onClick={() => void diagnose()}>
              <RefreshCw size={15} className={loading ? 'spin' : ''} /> Run
            </button>
          </div>
        </div>

        <div className="context-strip"><strong>{region} · {category} · {date}</strong><span>{materialCount} of {registeredKpis.length} KPIs are material</span></div>
        {error && <div className="alert error"><ShieldAlert size={18} /><span>{error}</span></div>}
        {loading && <div className="alert"><Activity className="spin" size={18} /><span>Running the governed KPI engine across daily, weekly, and monthly sources…</span></div>}

        {marketingBrief && <section className="marketing-brief" aria-labelledby="briefing-title">
          <div className="briefing-lead"><div><span className="eyebrow">{persona === 'CFO' ? 'Financial reviewer briefing' : 'Marketing manager briefing'}</span><h2 id="briefing-title">What you need to know today</h2><p>{marketingBrief.summary}</p><small>{marketingBrief.first_weak_stage ? `First observed weak funnel stage: ${marketingBrief.first_weak_stage.label}${marketingBrief.first_weak_stage.material ? ' · material' : ''}` : 'No first weak stage established'}</small></div><span className="evidence-pill">{region} · {category} · {date}</span></div>
          <div className="funnel-strip" aria-label="Connected marketing funnel">{marketingBrief.funnel.map((stage, index) => {
            const unit = registeredKpis.find(item => item.kpi_id === stage.kpi_id)?.unit ?? 'count'
            return <article className={`funnel-stage ${stage.direction}`} key={stage.kpi_id}><small>{stage.stage}</small><strong>{formatValue(stage.actual, unit)}</strong><span>{formatDelta(stage.delta, unit)} · {stage.material ? 'material' : stage.status === 'OK' ? 'not material' : titleCase(stage.status)}</span><b>{stage.label}</b>{index < marketingBrief.funnel.length - 1 && <ArrowRight className="funnel-arrow" size={15} />}</article>
          })}</div>
          <div className="brief-insights">
            {briefStories.slice(0, 5).map((story, index) => {
              const storyKey = [story.id, ...(story.affected_kpis ?? []), index].join('-')
              return (
                <article className="brief-insight story-card" key={storyKey}>
                  <span className="brief-rank">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <strong>{story.title}</strong>
                    <p>{story.what_changed}</p>
                    <small>{story.affected_kpis.map(kpiLabel).join(' · ')} · {story.evidence_strength} · {statusLabelForBrief(story.confidence_status)}</small>
                    <p className="story-impact">{story.business_impact}</p>
                    {story.recommended_action && <p>Next: {story.recommended_action.recommendation} · Owner {statusLabel(story.recommended_action.owner)}</p>}
                    <small>{story.causal_boundary}</small>
                    {story.technical_details?.filter(Boolean).length ? (
                      <details className="technical-details">
                        <summary>View evidence details</summary>
                        {story.technical_details.filter(Boolean).map((detail, detailIndex) => (
                          <p key={`${storyKey}-detail-${detailIndex}`}>{detail}</p>
                        ))}
                      </details>
                    ) : null}
                  </div>
                  <button onClick={() => { setSelected((story.affected_kpis[0] ?? selected) as KpiId); setDraft(`Explain the ${story.title.toLowerCase()} story and supporting evidence.`); setAssistantMode('open') }} aria-label={`Investigate ${story.title}`}>
                    <ArrowRight size={17} />
                  </button>
                </article>
              )
            })}
            {!hasPositiveOpportunity && <p className="brief-no-positive">No verified positive opportunity was identified in this scope.</p>}
          </div>
          {marketingBrief.uncertainty.length > 0 && <details className="brief-limits"><summary>Evidence limitations ({marketingBrief.uncertainty.length})</summary><p>{marketingBrief.uncertainty.map(statusLabelForBrief).join(' · ')}</p></details>}
          <details className="brief-method"><summary>Method and evidence details</summary><p>{marketingBrief.method}. Co-movement is not proof of causality and related KPI movements are not summed as separate causes.</p><small>Raw assessment: {result?.verdict} · {result?.confidence?.status ?? 'NOT_ASSESSED'} · {result?.causal_verdict ?? 'UNTESTABLE'}</small></details>
        </section>}

        <section className="kpi-selector supporting-kpis" aria-label="Registered KPIs">
          {registeredKpis.map(item => {
            const itemResult = results[item.kpi_id]
            const itemMovement = itemResult?.movement_assessment
            const Icon = kpiIcon(item.kpi_id)
            return <button key={item.kpi_id} className={selected === item.kpi_id ? 'kpi-tile active' : 'kpi-tile'} onClick={() => setSelected(item.kpi_id)}><span><Icon size={16} />{kpiLabel(item.kpi_id)}</span><strong>{formatValue(itemMovement?.actual_value, item.unit)}</strong><small className={(itemMovement?.delta ?? 0) < 0 ? 'negative' : 'positive'}>{formatDelta(itemMovement?.delta, item.unit)} vs baseline</small></button>
          })}
        </section>

        <section className="hero-card card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(230px, 0.8fr) minmax(320px, 1.2fr)', gap: '24px', alignItems: 'center' }}>
            <div className="hero-summary">
              <span className="eyebrow">Primary observed KPI</span>
              <h2>{selectedKpiLabel}</h2>
              <div className="hero-number">{formatValue(movement?.actual_value, kpi.unit)}</div>
              <p className={(movement?.delta ?? 0) < 0 ? 'negative' : 'positive'}>
                <ArrowDownRight size={16} /> {formatDelta(movement?.delta, kpi.unit)} versus the engine baseline
              </p>
              <span className={`evidence-pill ${movement?.is_material ? 'warning' : 'good'}`}>
                {movement?.is_material ? 'Material movement' : 'Not material'}
              </span>
            </div>

            <div className="comparison-chart" role="img" aria-label={`${selectedKpiLabel} actual compared with expected baseline`}>
              <div className="chart-head"><span>Target Date Summary</span><small>Actual vs Baseline</small></div>
              <div className="bar-row"><span>Expected</span><i><b style={{ width: '100%' }} /></i><strong>{formatValue(movement?.expected_value, kpi.unit)}</strong></div>
              <div className="bar-row actual"><span>Actual</span><i><b style={{ width: `${movement?.expected_value ? Math.min(100, Math.abs((movement.actual_value / movement.expected_value) * 100)) : 0}%` }} /></i><strong>{formatValue(movement?.actual_value, kpi.unit)}</strong></div>
              <div className="chart-caption"><Database size={14} /> Target date {date} · As of {result?.as_of ? new Date(result.as_of).toLocaleString('en-IN') : 'awaiting run'}</div>
            </div>
          </div>

          {/* Real Governed Time-Series Trend Line Chart */}
          <KpiTrendChart
            apiBase={API_BASE}
            kpiId={selected}
            kpiLabel={selectedKpiLabel}
            unit={kpi.unit}
            region={region}
            category={category}
            targetDate={date}
            userId={identityForPersona(persona)}
          />
        </section>

        <div className="section-heading"><div><h2>What explains the movement?</h2><p>Accounting contributions and diagnostic indicators are deliberately separated.</p></div><button onClick={() => void askQuestion('Explain the difference between contributions and diagnostic drivers.')}><CircleHelp size={15} /> Ask AI</button></div>

        <section className="explanation-grid">
          <article className="card contribution-card"><div className="card-heading"><div><span className="eyebrow">Quantified contribution</span><h3>Accounting bridge</h3></div><span className={`evidence-pill ${decomposition?.is_identity_held ? 'good' : 'limited'}`}>{decomposition?.is_identity_held ? 'Identity reconciled' : titleCase(result?.decomposition_status)}</span></div>{contributionRows.length ? <><div className="donut-wrap"><div className="donut" style={{ '--slice': `${Math.round((Math.abs(contributionRows[0]?.value ?? 0) / contributionTotal) * 100)}%` } as React.CSSProperties}><span><strong>{formatDelta(decomposition?.total_delta, kpi.unit)}</strong><small>total change</small></span></div><div className="contribution-list">{contributionRows.map((item, index) => <div key={item.label}><i className={`swatch swatch-${index}`} /><span>{item.label}<small>{Math.round((Math.abs(item.value) / contributionTotal) * 100)}% of quantified movement</small></span><strong>{formatDelta(item.value, kpi.unit)}</strong></div>)}</div></div><p className="method-note">These values add to the observed movement. They are an accounting explanation, not proof of operational cause.</p></> : <div className="empty-state">No exact contribution bridge is available for this KPI.</div>}</article>

          <article className="card driver-card"><div className="card-heading"><div><span className="eyebrow">Diagnostic drivers</span><h3>Ranked indicators</h3></div><span className="evidence-pill limited">Not attribution</span></div>{result?.correlational_candidates?.length ? <div className="driver-list">{result.correlational_candidates.slice(0, 4).map(candidate => <div key={candidate.driver_id} className="driver-row"><div><strong>{driverLabels[candidate.driver_id] ?? titleCase(candidate.driver_id)}</strong><span>Correlation {candidate.max_correlation.toFixed(2)} · lag {candidate.optimal_lag_days}d · n={candidate.sample_size}</span></div><div className="association"><i style={{ width: `${Math.min(100, Math.abs(candidate.max_correlation) * 100)}%` }} /></div><small>{titleCase(candidate.claim_type)}</small></div>)}</div> : <div className="empty-state">No diagnostic driver passed the ranking checks for this run.</div>}<p className="method-note">Indicators help decide what to investigate. Their association is not a monetary contribution or a causal claim.</p></article>
        </section>

        <section className="insight-grid"><article className="card narrative-card"><span className="eyebrow">Executive conclusion</span><h3>{result?.verdict ? statusLabel(result.verdict) : 'Awaiting analysis'}</h3><p>{marketingBrief?.summary ?? 'Run the engine to generate a traceable explanation.'}</p><details className="technical-details"><summary>Technical narrative and evidence</summary><p>{result?.narrative ?? 'Narrative unavailable.'}</p><div className="meta-line"><CheckCircle2 size={15} /> Grounding {result?.grounding_passed ? 'passed' : 'not established'} · {titleCase(result?.narrative_method)}</div></details></article><article className="card confidence-card"><div className="card-heading"><div><span className="eyebrow">Confidence and limits</span><h3>{statusLabel(result?.confidence?.status)}</h3></div><span className={`evidence-pill ${evidenceTone(result?.confidence?.status)}`}>{statusLabel(result?.confidence?.claim_type)}</span></div><p>{result?.causal_verification?.reason ?? result?.confidence?.reasons?.[0] ?? 'Confidence not assessed; no causal comparison design is available.'}</p><details className="technical-details"><summary>Method details</summary><div className="confidence-checks"><span className={movement?.is_statistically_significant ? 'pass' : ''}>Statistical materiality</span><span className={movement?.is_business_material ? 'pass' : ''}>Business materiality</span><span className={result?.grounding_passed ? 'pass' : ''}>Narrative grounding</span></div><p>Data as of {result?.as_of ?? 'unavailable'} · method {result?.narrative_method ?? 'not instrumented'} · model calls {result?.telemetry?.model_call_count ?? 'Not instrumented'} · latency {result?.telemetry?.total_latency_ms ?? 'Not instrumented'} · cost {result?.telemetry?.estimated_cost ?? 'Not instrumented'}</p></details></article></section>

        <section className="card action-card" id="recommended-action"><div className="section-heading compact"><div><span className="eyebrow">Recommended next step</span><h2>Action within marketing decision rights</h2></div></div>{result?.decision_cards?.length ? <div className="action-list">{result.decision_cards.slice(0, 3).map((action, index) => <article key={`${action.kind}-${index}`}><span>{String(index + 1).padStart(2, '0')}</span><div><h3>{statusLabel(action.kind)}</h3><p><strong>Signal:</strong> {marketingBrief?.first_weak_stage?.label ?? selectedKpiLabel}</p><p><strong>Recommended next check:</strong> {action.recommendation}</p><p><strong>Monitor:</strong> traffic, conversion rate, orders and revenue</p><small>Owner: {statusLabel(action.owner)} · Evidence: {statusLabel(result?.confidence?.status)} · Expected impact {action.expected_impact == null ? 'not estimated with available evidence' : formatValue(action.expected_impact, kpi.unit)} · Review after source validation</small></div><button onClick={() => void askQuestion(`What evidence supports this next check: ${action.recommendation}`)} aria-label="Ask AI about recommended check"><ArrowRight size={18} /></button></article>)}</div> : <div className="empty-state">The engine is abstaining from action until the evidence is sufficient.</div>}</section>

        <footer className="source-footer"><span>Run {result?.run_id ?? '—'}</span><span>Source status: {titleCase(result?.reconciliation_verdict?.status)}</span><span>Persona: {persona === 'CFO' ? 'CFO' : 'Marketing manager'}</span></footer>
      </section>

      {assistantMode === 'closed' && <Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} disabled={loading} />}
      {assistantMode === 'minimized' && <button className="restore-pill" onClick={() => setAssistantMode('open')}><Bot size={17} /> Ask KPI Assistant</button>}

      {isAssistantOpen && <aside className="assistant-panel" aria-label="KPI assistant"><button className="resize-handle" aria-label="Resize assistant" onPointerDown={beginResize}><GripVertical size={17} /></button><header className="assistant-header"><div className="assistant-title"><span><Bot size={18} /></span><div><strong>KPI Assistant</strong><small>{selectedKpiLabel} · {region} · {date}</small></div></div><div className="assistant-actions"><button onClick={() => setPanelWidth(panelWidth === 600 ? 410 : 600)} aria-label="Toggle assistant width"><Maximize2 size={16} /></button><button onClick={() => setAssistantMode('minimized')} aria-label="Minimize assistant"><Minimize2 size={16} /></button><button onClick={() => { setAssistantMode('closed'); setMessages([]); setConversationId(undefined) }} aria-label="Close assistant"><X size={18} /></button></div></header><div className="assistant-context"><Sparkles size={14} /> Grounded in run {result?.run_id ?? 'not available'}</div><div className="conversation">{!messages.length && <div className="assistant-empty"><span><Sparkles size={22} /></span><h2>Ask your marketing analyst</h2><p>I’ll explain the movement, distinguish evidence from hypotheses, and surface safe next steps.</p></div>}{messages.map(message => <article key={message.id} className={`message ${message.role}`}><p>{message.text}</p>{message.citations?.length ? <details><summary>{message.citations.length} evidence reference{message.citations.length === 1 ? '' : 's'}</summary>{message.citations.map((citation, index) => <small key={`${citation.source_path}-${index}`}>{citation.evidence_type}: {citation.source_path}{citation.line_or_row_ref ? ` · ${citation.line_or_row_ref}` : ''}</small>)}</details> : null}{message.limitations?.length ? <div className="limitations"><strong>Limits</strong>{message.limitations.map(item => <small key={item}>{item}</small>)}</div> : null}</article>)}{asking && <div className="thinking"><i /><i /><i /></div>}<div ref={conversationEnd} /></div><div className="assistant-suggestions">{['What changed?', 'Is the cause proven?', 'What should I verify next?'].map(item => <button key={item} onClick={() => void askQuestion(item)}>{item}</button>)}</div><Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} panel disabled={asking} /></aside>}
    </main>
  </div>
}
