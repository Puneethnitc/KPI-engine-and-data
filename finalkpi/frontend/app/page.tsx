'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  Activity, ArrowRight, BarChart3, CheckCircle2, ChevronRight, Database,
  LayoutDashboard, MessageSquare, Moon, RefreshCw, Send, ShieldAlert,
  Sparkles, Sun, TrendingDown, X,
} from 'lucide-react'

type Movement = {
  actual_value: number; expected_value: number; delta: number;
  is_material: boolean; is_statistically_significant: boolean;
  is_business_material: boolean; detector_agreement?: string;
  status: string; z_score?: number;
}
type Decomposition = {
  total_delta: number; volume_effect: number; price_effect: number;
  mix_effect: number; residual: number; is_identity_held: boolean;
}
type Candidate = {
  driver_id: string; max_correlation: number; optimal_lag_days: number;
  sample_size: number; driver_change_pct: number; claim_type: string;
}
type Decision = { kind: string; recommendation: string; owner: string; status: string; expected_impact: number | null }
type Result = {
  run_id: string; kpi_id: string; target_date: string; as_of: string;
  verdict: string; segment: { region: string; category: string };
  movement_assessment?: Movement | null;
  reconciliation_verdict?: { status: string; details?: { reason?: string }; gap_pct?: number | null } | null;
  decomposition_status: string; decomposition?: Decomposition | null;
  correlational_candidates: Candidate[];
  driver_exclusions?: { driver_id: string; reason: string }[];
  causal_verdict?: string | null;
  causal_verification?: { reason?: string; confidence_interval?: [number, number] | null; did_effect?: number | null } | null;
  confidence?: { status: string; claim_type: string; reasons?: string[]; calibrated_probability?: number | null } | null;
  decision_cards: Decision[]; narrative: string; grounding_passed: boolean;
  narrative_method?: string; llm_status?: string;
}

const KPIS = [
  { id: 'net_sales_revenue', label: 'Net sales revenue', unit: 'INR', icon: TrendingDown },
  { id: 'orders', label: 'Orders', unit: 'count', icon: BarChart3 },
  { id: 'units_sold', label: 'Units sold', unit: 'count', icon: BarChart3 },
  { id: 'traffic_total', label: 'Traffic', unit: 'count', icon: Activity },
  { id: 'conversion_rate', label: 'Conversion rate', unit: 'ratio', icon: Activity },
] as const
type KpiId = typeof KPIS[number]['id']

const driverLabels: Record<string, string> = {
  traffic_drop: 'Traffic movement', ad_spend_drop: 'Ad-spend movement',
  checkout_latency_spike: 'Checkout latency', competitor_price_cut: 'Competitor pricing',
  stockout: 'Stock availability',
}

function number(value: number | null | undefined, unit: string, signed = false) {
  if (value == null || !Number.isFinite(value)) return '—'
  const v = unit === 'ratio' ? value * 100 : value
  const sign = signed && v > 0 ? '+' : ''
  if (unit === 'INR') return `${sign}₹${Math.abs(v).toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}${v < 0 ? ' decrease' : ''}`
  if (unit === 'ratio') return `${sign}${v.toFixed(2)}%`
  return `${sign}${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}
function signedNumber(value: number | null | undefined, unit: string) {
  if (value == null) return '—'
  if (unit === 'INR') return `${value < 0 ? '−' : '+'}₹${Math.abs(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const scaled = unit === 'ratio' ? value * 100 : value
  return `${scaled < 0 ? '−' : '+'}${Math.abs(scaled).toLocaleString('en-IN', { maximumFractionDigits: 3 })}${unit === 'ratio' ? ' pp' : ''}`
}
function labelFor(id: string) { return KPIS.find(k => k.id === id)?.label ?? id.replaceAll('_', ' ') }
function statusFor(result?: Result) {
  if (!result) return 'Loading'
  if (result.verdict === 'CONTRADICTED') return 'Sources conflict'
  if (!result.movement_assessment) return result.verdict.replaceAll('_', ' ')
  return result.movement_assessment.is_material ? 'Material movement' : 'Not material'
}

function ImpactBar({ name, value, scale, unit }: { name: string; value: number; scale: number; unit: string }) {
  return <div className="demo-impact-row">
    <span>{name}</span>
    <div className="demo-impact-track"><i className={value < 0 ? 'negative' : 'positive'} style={{ width: `${Math.max(4, Math.min(100, Math.abs(value) / scale * 100))}%` }} /></div>
    <strong className={value < 0 ? 'demo-negative' : 'demo-positive'}>{signedNumber(value, unit)}</strong>
  </div>
}

export default function Page() {
  const [view, setView] = useState<'overview' | 'detail'>('overview')
  const [selected, setSelected] = useState<KpiId>('net_sales_revenue')
  const [region, setRegion] = useState('North')
  const [category, setCategory] = useState('Electronics')
  const [date, setDate] = useState('2023-07-24')
  const [results, setResults] = useState<Record<string, Result>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [chatDraft, setChatDraft] = useState('')
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState('')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')

  useEffect(() => {
    const saved = localStorage.getItem('kpi-demo-theme')
    const mode = saved === 'light' || saved === 'dark' ? saved : (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
    setTheme(mode)
  }, [])
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('kpi-demo-theme', theme) }, [theme])

  async function diagnose() {
    setLoading(true); setError('')
    try {
      const params = new URLSearchParams({ kpi: 'all', date, region, category })
      const response = await fetch(`/api/diagnose?${params.toString()}`, { cache: 'no-store' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error ?? 'Diagnosis failed')
      setResults(payload.results)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not reach the engine') }
    finally { setLoading(false) }
  }
  useEffect(() => { void diagnose() }, [])

  const result = results[selected]
  const kpi = KPIS.find(k => k.id === selected)!
  const movement = result?.movement_assessment
  const sourceStatus = result?.reconciliation_verdict?.status ?? 'NOT_EVALUATED'
  const scale = Math.max(1, Math.abs(result?.decomposition?.volume_effect ?? 0), Math.abs(result?.decomposition?.price_effect ?? 0), Math.abs(result?.decomposition?.mix_effect ?? 0))
  const materialCount = useMemo(() => Object.values(results).filter(r => r.movement_assessment?.is_material).length, [results])

  function ask(text: string) {
    setQuestion(text); setChatOpen(true)
    if (!result) { setAnswer('Run the diagnosis first so I can use its evidence.'); return }
    const q = text.toLowerCase()
    if (q.includes('cause') || q.includes('why')) {
      setAnswer(`The engine reports ${result.causal_verdict ?? 'no causal verdict'}. ${result.causal_verification?.reason ?? 'It has not established a cause.'} The candidate drivers below are correlations, not proof.`)
    } else if (q.includes('source') || q.includes('evidence')) {
      setAnswer(`Source status: ${sourceStatus}. ${result.reconciliation_verdict?.details?.reason ?? ''} The engine narrative is ${result.grounding_passed ? 'grounded in its evidence object' : 'not fully grounded'}.`)
    } else if (q.includes('next') || q.includes('action')) {
      setAnswer(result.decision_cards[0]?.recommendation ?? 'No action is supported yet. Review the evidence and source status.')
    } else {
      setAnswer(`${labelFor(selected)} moved ${signedNumber(movement?.delta, kpi.unit)} versus the engine baseline on ${date}. ${movement?.is_material ? 'It passed both materiality checks.' : 'It did not pass both materiality checks.'} ${result.correlational_candidates.length ? `${driverLabels[result.correlational_candidates[0].driver_id] ?? result.correlational_candidates[0].driver_id} is a correlational candidate, not a proven cause.` : 'No driver candidate was established.'}`)
    }
  }

  return <div className="demo-shell">
    <aside className="demo-sidebar">
      <div className="demo-brand"><span className="demo-brand-mark"><Sparkles size={18} /></span><div><strong>signalcraft</strong><small>KPI intelligence</small></div></div>
      <div className="demo-side-label">WORKSPACE</div>
      <button className={view === 'overview' ? 'demo-nav active' : 'demo-nav'} onClick={() => setView('overview')}><LayoutDashboard size={17} /> Overview</button>
      <div className="demo-side-label">REGISTERED KPIS</div>
      {KPIS.map(item => <button key={item.id} className={view === 'detail' && selected === item.id ? 'demo-nav active' : 'demo-nav'} onClick={() => { setSelected(item.id); setView('detail'); setQuestion(''); setAnswer('') }}><item.icon size={16} /> {item.label}</button>)}
      <div className="demo-side-bottom"><span className="demo-live-dot" /> Engine-backed demo <small>CSV sources · 2023–24</small></div>
    </aside>

    <div className="demo-main">
      <header className="demo-topbar"><div className="demo-top-title">Northstar / KPI investigation <span>MENTOR DEMO</span></div><div className="demo-top-actions"><span className="demo-source-mini"><Database size={14} /> Sales daily · finance monthly</span><button aria-label="Toggle light and dark mode" className="demo-icon-button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button><button className="demo-ask-button" onClick={() => setChatOpen(true)}><MessageSquare size={15} /> Ask about this KPI</button></div></header>
      <main className="demo-content">
        <div className="demo-heading"><div><div className="demo-eyebrow">INTELLIGENCE WORKSPACE <ChevronRight size={12} /> {view === 'overview' ? 'OVERVIEW' : kpi.label.toUpperCase()}</div><h1>{view === 'overview' ? 'KPI overview' : kpi.label}</h1><p>{view === 'overview' ? 'Spot material movements, then open the underlying evidence.' : 'Observed movement, accounting effects, and evidence limits—kept separate.'}</p></div><div className="demo-run-id">{result?.run_id ?? 'Awaiting engine'}</div></div>

        <div className="demo-filters">
          <label>Target date<input type="date" min="2023-03-01" max="2024-12-30" value={date} onChange={e => setDate(e.target.value)} /></label>
          <label>Region<select value={region} onChange={e => setRegion(e.target.value)}>{['North', 'South', 'East', 'West'].map(x => <option key={x}>{x}</option>)}</select></label>
          <label>Category<select value={category} onChange={e => setCategory(e.target.value)}>{['Electronics', 'Apparel', 'Home'].map(x => <option key={x}>{x}</option>)}</select></label>
          <button className="demo-primary" disabled={loading} onClick={() => void diagnose()}><RefreshCw size={15} className={loading ? 'demo-spin' : ''} /> {loading ? 'Running engine…' : 'Run diagnosis'}</button>
          <span className="demo-asof">{result ? `As of ${new Date(result.as_of).toLocaleString('en-IN')}` : 'Supplied historical dataset'}</span>
        </div>
        {error && <div className="demo-alert error"><ShieldAlert size={17} /> {error}</div>}
        {loading && <div className="demo-alert"><Activity size={17} /> Running the five registered KPIs on the supplied source files. This can take a few seconds.</div>}

        {view === 'overview' ? <>
          <div className="demo-section-head"><div><span className="demo-eyebrow">PORTFOLIO HEALTH</span><h2>Five registered KPIs</h2></div><span>{materialCount} material movements · {region} / {category}</span></div>
          <div className="demo-kpi-grid">{KPIS.map(item => { const itemResult = results[item.id]; const assessment = itemResult?.movement_assessment; return <button key={item.id} className="demo-kpi-card" onClick={() => { setSelected(item.id); setView('detail') }}><div className="demo-card-top"><item.icon size={17} /><span className={assessment?.is_material ? 'demo-pill amber' : 'demo-pill'}>{statusFor(itemResult)}</span></div><span className="demo-card-label">{item.label}</span><strong>{assessment ? number(assessment.actual_value, item.unit) : '—'}</strong><small className={assessment?.delta && assessment.delta < 0 ? 'demo-negative' : 'demo-positive'}>{assessment ? `${signedNumber(assessment.delta, item.unit)} vs baseline` : 'Awaiting result'}</small></button> })}</div>
          <div className="demo-two-col"><section className="demo-panel"><div className="demo-section-head"><div><span className="demo-eyebrow">PRIORITIZED QUEUE</span><h2>Investigations to review</h2></div></div><div className="demo-queue">{KPIS.map(item => { const itemResult = results[item.id]; return <button key={item.id} onClick={() => { setSelected(item.id); setView('detail') }}><span><strong>{item.label}</strong><small>{statusFor(itemResult)}</small></span><span>{signedNumber(itemResult?.movement_assessment?.delta, item.unit)}</span><span className="demo-pill">{itemResult?.reconciliation_verdict?.status?.replaceAll('_', ' ') ?? '—'}</span><ArrowRight size={15} /></button> })}</div></section>
          <section className="demo-panel demo-source-panel"><span className="demo-eyebrow">DATA TRUST</span><h2>Source status is part of the answer</h2><p>Sales is daily, marketing is weekly, and finance is monthly. A missing finance snapshot is displayed as <strong>NOT_RECONCILED</strong>—never silently treated as agreement.</p><div className="demo-source-line"><Database size={17} /> Revenue source check <span className="demo-pill amber">{results.net_sales_revenue?.reconciliation_verdict?.status?.replaceAll('_', ' ') ?? 'Awaiting result'}</span></div><button className="demo-text-button" onClick={() => { setSelected('net_sales_revenue'); setView('detail') }}>Inspect revenue evidence <ArrowRight size={14} /></button></section></div>
        </> : <>
          <button className="demo-back" onClick={() => setView('overview')}>← Back to overview</button>
          <div className={sourceStatus === 'CONTRADICTED' ? 'demo-alert error' : 'demo-alert amber'}><ShieldAlert size={18} /><div><strong>Sources: {sourceStatus.replaceAll('_', ' ')}</strong><span>{result?.reconciliation_verdict?.details?.reason ?? 'No second-source comparison is available for this KPI.'}</span></div></div>
          <div className="demo-section-head"><div><span className="demo-eyebrow">OBSERVED MOVEMENT</span><h2>Actual versus engine baseline</h2></div><span className="demo-pill amber">{statusFor(result)}</span></div>
          <div className="demo-stat-grid"><div className="demo-stat"><small>ACTUAL</small><strong>{number(movement?.actual_value, kpi.unit)}</strong></div><div className="demo-stat"><small>EXPECTED BASELINE</small><strong>{number(movement?.expected_value, kpi.unit)}</strong></div><div className="demo-stat"><small>DELTA</small><strong className={movement?.delta && movement.delta < 0 ? 'demo-negative' : 'demo-positive'}>{signedNumber(movement?.delta, kpi.unit)}</strong></div></div>
          <div className="demo-two-col"><section className="demo-panel"><span className="demo-eyebrow">WHAT CHANGED · EXACT ACCOUNTING</span><h2>Accounting bridge</h2>{result?.decomposition?.is_identity_held ? <><p>These effects add to the observed KPI movement. They do not establish a cause.</p><div className="demo-impact-list"><ImpactBar name="Units sold effect" value={result.decomposition.volume_effect} scale={scale} unit={kpi.unit} /><ImpactBar name="Rate effect" value={result.decomposition.price_effect} scale={scale} unit={kpi.unit} />{result.decomposition.mix_effect !== 0 && <ImpactBar name="Mix effect" value={result.decomposition.mix_effect} scale={scale} unit={kpi.unit} />}</div><div className="demo-bridge-total"><span>Reconciled total</span><strong>{signedNumber(result.decomposition.total_delta, kpi.unit)}</strong></div></> : <p>No exact bridge is available for this KPI. Status: {result?.decomposition_status ?? 'Not evaluated'}.</p>}</section>
          <section className="demo-panel"><span className="demo-eyebrow">POSSIBLE DRIVERS · CORRELATIONAL</span><h2>Ranked candidates</h2>{result?.correlational_candidates?.length ? result.correlational_candidates.map(candidate => <div className="demo-candidate" key={candidate.driver_id}><div><strong>{driverLabels[candidate.driver_id] ?? candidate.driver_id}</strong><span className="demo-pill">CORRELATIONAL</span></div><p>Association {candidate.max_correlation.toFixed(2)} · lag {candidate.optimal_lag_days} day(s) · {candidate.sample_size} paired observations</p><div className="demo-association" aria-label={`Absolute association ${Math.abs(candidate.max_correlation).toFixed(2)} of 1`}><i style={{ width: `${Math.min(100, Math.abs(candidate.max_correlation) * 100)}%` }} /></div><small>Driver movement: {candidate.driver_change_pct.toFixed(2)}%. This is not a ₹ causal effect.</small></div>) : <p>No driver candidate passed the current ranking checks.</p>}</section></div>
          <div className="demo-two-col"><section className="demo-panel"><span className="demo-eyebrow">OBSERVATIONAL CHECK</span><h2>Cause: {result?.causal_verdict ?? 'not assessed'}</h2><p>{result?.causal_verification?.reason ?? 'The engine has not established a causal estimate.'}</p><div className="demo-pill">Confidence: {result?.confidence?.status ?? 'NOT_ASSESSED'}</div><p className="demo-small-note">A correlation or accounting identity is not proof of causation.</p></section><section className="demo-panel"><span className="demo-eyebrow">HUMAN REVIEW</span><h2>Next useful check</h2><p>{result?.decision_cards?.[0]?.recommendation ?? 'Review the source and movement evidence before taking action.'}</p><div className="demo-pill">{result?.decision_cards?.[0]?.status ?? 'AWAITING_REVIEW'}</div><p className="demo-small-note">No operational action has been executed.</p></section></div>
          <section className="demo-panel demo-narrative"><div className="demo-section-head"><div><span className="demo-eyebrow">EVIDENCE-BOUND NARRATIVE</span><h2>Engine explanation</h2></div><span className="demo-pill">{result?.narrative_method?.replaceAll('_', ' ') ?? '—'}</span></div><p>{result?.narrative ?? 'Run a diagnosis to see an explanation.'}</p><details><summary>View run and evidence details</summary><div className="demo-evidence-meta">Run {result?.run_id} · Grounding {result?.grounding_passed ? 'passed' : 'not passed'} · Detector {movement?.detector_agreement ?? '—'} · Statistical check {movement?.is_statistically_significant ? 'passed' : 'not passed'} · Business threshold {movement?.is_business_material ? 'passed' : 'not passed'}</div>{result?.driver_exclusions?.map(x => <p key={x.driver_id}><strong>{driverLabels[x.driver_id] ?? x.driver_id}:</strong> {x.reason}</p>)}</details></section>
        </>}
      </main>
    </div>

    {chatOpen && <aside className="demo-chat"><div className="demo-chat-head"><div><span className="demo-eyebrow">EVIDENCE ASSISTANT</span><h2>Ask about this KPI</h2></div><button className="demo-icon-button" onClick={() => setChatOpen(false)} aria-label="Close chat"><X size={17} /></button></div><div className="demo-chat-context">Context: {labelFor(selected)} · {region}/{category} · {date}</div><div className="demo-chat-body"><div className="demo-chat-bubble"><Sparkles size={16} /><p>I can summarize this engine run and point to its evidence. This is a scripted demo assistant, not a live LLM.</p></div>{question && <div className="demo-chat-question">{question}</div>}{answer && <div className="demo-chat-bubble"><CheckCircle2 size={16} /><p>{answer}</p></div>}</div><div className="demo-suggestions">{['What changed?', 'What evidence supports this?', 'Is the cause proven?', 'What should I check next?'].map(x => <button key={x} onClick={() => ask(x)}>{x}</button>)}</div><form className="demo-chat-form" onSubmit={e => { e.preventDefault(); if (chatDraft.trim()) { ask(chatDraft.trim()); setChatDraft('') } }}><input value={chatDraft} onChange={e => setChatDraft(e.target.value)} placeholder="Ask about this result…" aria-label="Ask a question" /><button aria-label="Send question"><Send size={16} /></button></form></aside>}
  </div>
}
