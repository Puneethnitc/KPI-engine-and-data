'use client'

import Link from 'next/link'
import { FormEvent, PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import {
  Activity, ArrowDownRight, ArrowRight, BarChart3, Bot, CheckCircle2, ChevronDown,
  Database, GripVertical, LayoutDashboard, Maximize2, Minimize2, RefreshCw, Send,
  ShieldAlert, Sparkles, TrendingDown, X,
} from 'lucide-react'
import { AppHeader, DateFilter, identityForPersona, useDemoContext } from '../components/app-shell'
import ActionWorkspace from '../components/action-workspace'
import { DriverVsKpiChart } from '../components/simple-charts'
import FunnelBridgeCard, { type FunnelBridge } from '../components/funnel-bridge'
import type { DriverAnalysis } from '../lib/driver-analysis'
import type { ActionContract } from '../lib/action-workspace'
import { statusLabel } from '../lib/presentation'
import { contractViewerHref } from '../lib/semantic-contract'
import { CustomSelect } from '../components/ui/custom-select'
import { movementScopeOptions, movementSelection } from '../lib/movement-navigation'
import { KpiTrendChart } from '../components/kpi-trend-chart'
import DriverAnalysisOverview, { type CausalTest } from '../components/driver-analysis-overview'
import { deviationView } from '../lib/deviation-view'
import { sourceStatus, reconciliationStatus, reconciliationMode } from '../lib/data-foundation'
import { buildDiagnosisRequest, parseScenarioExecution, mergeScopeOption, isTrendChartAllowed, isAssistantAllowed, validateGovernedAccessDenied, buildScenarioMetadata } from '../lib/demo-scenarios'
import ConfidenceWorkspace from '../components/confidence-workspace'
import type { ConfidenceProfile } from '../lib/confidence-profile'
import ProcessingTransparencyView from '../components/processing-transparency'
import KpiFlow, { type KpiStory } from '../components/kpi-flow'
import type { ProcessingTransparency } from '../lib/processing-transparency'

type Movement = {
  actual_value: number
  expected_value: number
  delta: number
  is_material: boolean
  is_statistically_significant: boolean
  is_business_material: boolean
  detector_agreement?: string
  status: string
  baseline_scale?: number | null
  robust_score?: number | null
}

// A single MovementScanner result (GET /api/movements) -- distinct from
// `Movement` above, which is one diagnosis's own movement_assessment for the
// KPI/slice currently selected. A ScannedMovement is one row of the
// persona-wide "Top movements today" feed, across every authorised slice.
type ScannedMovement = {
  kpi_id: string
  target_date: string
  region: string | null
  category: string | null
  is_material: boolean
  priority: number
  delta: number | null
  rel_delta: number | null
  actual_value: number | null
  expected_value: number | null
  detector_agreement: string
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
  contribution: number
  explained_share: number | null
  lag_days: number
  sample_size: number
  offsetting: boolean
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
  funnel_bridge_status?: string | null
  funnel_bridge?: FunnelBridge | null
  correlational_candidates: Candidate[]
  driver_analysis?: DriverAnalysis | null
  driver_exclusions?: { driver_id: string; reason: string }[]
  causal_verdict?: string | null
  causal_verification?: CausalTest | null
  confidence?: { status: string; claim_type: string; reasons?: string[]; calibrated_probability?: number | null } | null
  confidence_profile?: ConfidenceProfile | null
  processing_transparency?: ProcessingTransparency | null
  decision_cards: ActionContract[]
  narrative: string
  grounding_passed: boolean
  narrative_method?: string
  telemetry?: { model_call_count?: number; total_latency_ms?: number; estimated_cost?: number }
  contract_snapshot?: { materiality?: { statistical_thresholds?: { z_threshold?: number } } }
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
type RegisteredKpi = { kpi_id: string; version: number; definition: string; display_name?: string; unit: string; dimensions: string[]; governance?: { contract_hash: string } }
type EvidenceSummary = {
  as_of?: string | null
  source_readiness: { status: string }
  sources?: { source_id: string; coverage_status: string; latest_available_time?: string | null; latest_event_time?: string | null }[]
  reconciliation?: { status: string; blocking: boolean; reason?: string | null; gap_percent?: number | null; comparison_basis?: string | null; details?: { mode?: string | null } }
}

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
  marketing_spend: 'Marketing spend',
  checkout_latency: 'Checkout latency',
  competitor_price_index: 'Competitor pricing',
  stock_availability: 'Stock availability',
  price_discount: 'Price discount depth',
  promo_flag: 'Promotion flag',
  weather_temp: 'Weather temperature',
}

// Mirrors kpi_engine/contracts/registry.py's LEGACY_DRIVER_IDS: a saved run
// computed before the driver rename (backend Stage 1, plan §1.3) still
// carries the old id, so this display-only label lookup resolves it. Nothing
// else about that saved run (its own contract_snapshot, evidence, etc.) is
// touched or reinterpreted -- only the friendly label shown for the id.
const legacyDriverIds: Record<string, string> = {
  ad_spend_drop: 'marketing_spend',
  checkout_latency_spike: 'checkout_latency',
  competitor_price_cut: 'competitor_price_index',
  stockout: 'stock_availability',
}
function resolveDriverId(id: string) { return legacyDriverIds[id] ?? id }
function driverLabel(id: string) { return driverLabels[resolveDriverId(id)] ?? titleCase(id) }

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
  const { ready, persona, region, setRegion, category, setCategory, date, setDate, theme, options, scenarioId, scenarios, selectScenario, activeScenario, returnToManual, scenarioLocked } = useDemoContext()
  const [registeredKpis, setRegisteredKpis] = useState<RegisteredKpi[]>([])
  const [selected, setSelected] = useState<KpiId>('net_sales_revenue')
  const [results, setResults] = useState<Record<string, Result>>({})
  const [evidenceData, setEvidenceData] = useState<EvidenceSummary | null>(null)
  const [marketingBrief, setMarketingBrief] = useState<MarketingBrief | null>(null)
  const [kpiStory, setKpiStory] = useState<KpiStory | null>(null)
  const [scenarioHistory, setScenarioHistory] = useState<{ baseline_count?: number, required_observation_count?: number } | null>(null)
  const [movements, setMovements] = useState<ScannedMovement[]>([])
  const [movementsLoading, setMovementsLoading] = useState(false)
  const [movementsFetched, setMovementsFetched] = useState(false)
  const [priorityInfoOpen, setPriorityInfoOpen] = useState(false)
  const [foundationInfoOpen, setFoundationInfoOpen] = useState(false)
  const [movementRunToken, setMovementRunToken] = useState(0)
  const [loading, setLoading] = useState(true)
  // False on the server and on the first browser render, so both render the same
  // markup (avoids a hydration mismatch on client-only state such as URL filters).
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])
  const [error, setError] = useState('')
  const [accessDeniedMessage, setAccessDeniedMessage] = useState('')
  const [scenarioMeta, setScenarioMeta] = useState<{
    observedBroadOutcome?: string;
    expectedBroadOutcome?: string;
    expectedOutcomeObserved?: boolean;
    usesDemoFixture?: boolean;
    resolvedScenarioScope?: any;
    scenarioId?: string;
  } | null>(null)
  const [assistantMode, setAssistantMode] = useState<AssistantMode>('closed')
  const [panelWidth, setPanelWidth] = useState(410)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [asking, setAsking] = useState(false)
  const conversationEnd = useRef<HTMLDivElement>(null)
  const detailRef = useRef<HTMLElement>(null)
  const pendingMovement = useRef<string | null>(null)
  const diagnosisRequest = useRef(0)

  const result = results[selected]
  const kpi = registeredKpis.find(item => item.kpi_id === selected) ?? registeredKpis[0] ?? { kpi_id: selected, unit: 'count', version: 1, definition: '', dimensions: [] }
  const selectedKpiLabel = kpiLabel(kpi.kpi_id)
  const movement = result?.movement_assessment
  const overviewDriverNames = Object.fromEntries([
    ...(result?.driver_analysis?.ranked_drivers ?? []),
    ...(result?.driver_analysis?.excluded_drivers ?? []),
  ].map(candidate => [candidate.driver_id, driverLabel(candidate.driver_id)]))
  const deviation = deviationView(movement?.actual_value, movement?.expected_value, movement?.baseline_scale, movement?.robust_score, result?.contract_snapshot?.materiality?.statistical_thresholds?.z_threshold)
  const isAssistantOpen = assistantMode === 'opening' || assistantMode === 'open'

  useEffect(() => { conversationEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, asking])
  async function loadMetadata() {
    try {
      const metadataUser = activeScenario ? activeScenario.user_id : identityForPersona(persona)
      const metadataParams = new URLSearchParams({ user_id: metadataUser })
      if (region !== 'ALL') metadataParams.set('region', region)
      if (category !== 'ALL') metadataParams.set('category', category)
      const kpiResponse = await fetch(`${API_BASE}/api/kpis?${metadataParams}`, { cache: 'no-store' })
      if (!kpiResponse.ok) throw new Error('Could not load KPI metadata')
      const kpiPayload = await kpiResponse.json()
      const nextKpis: RegisteredKpi[] = kpiPayload.items ?? []
      setRegisteredKpis(nextKpis)
      if (nextKpis.length && !nextKpis.some(item => item.kpi_id === selected)) setSelected(nextKpis[0].kpi_id)
    } catch {
      setError('KPI metadata is unavailable. Filter choices may be incomplete.')
    }
  }

  useEffect(() => {
    if (!result?.run_id) {
      setEvidenceData(null)
      return
    }
    const userId = activeScenario ? activeScenario.user_id : identityForPersona(persona)
    fetch(`${API_BASE}/api/diagnoses/${result.run_id}/evidence?user_id=${userId}`)
      .then(r => r.ok ? r.json() : null)
      .then(setEvidenceData)
      .catch(() => setEvidenceData(null))
  }, [result?.run_id, persona, activeScenario])

  function openMovement(item: ScannedMovement) {
    if (scenarioLocked) return
    const target = movementSelection(item, date, options, persona)
    if (!target) return
    returnToManual()
    setRegion(target.region)
    setCategory(target.category)
    setDate(target.date)
    setSelected(target.kpiId)
    setLoading(true)
    setResults({})
    setMarketingBrief(null)
    setKpiStory(null)
    pendingMovement.current = target.kpiId
    diagnosisRequest.current += 1
    setMovementRunToken(value => value + 1)
  }

  async function diagnose() {
    if (!ready) return
    if (!options.dates.includes(date)) {
      diagnosisRequest.current += 1
      setLoading(false)
      setResults({})
      setMarketingBrief(null)
      setKpiStory(null)
      return
    }
    const requestId = ++diagnosisRequest.current
    setLoading(true)
    setError('')
    setAccessDeniedMessage('')
    setResults({})
    setMarketingBrief(null)
    setKpiStory(null)
    setScenarioHistory(null)
    setScenarioMeta(null)

    if (activeScenario) {
      setSelected(activeScenario.primary_kpi)
    }

    const requestScope = { persona, region, category, target_date: date }
    if (process.env.NODE_ENV !== 'production' && !scenarioLocked && (!movementScopeOptions(options.regions, 'region', persona).includes(region) || !movementScopeOptions(options.categories, 'category', persona).includes(category))) {
      const message = 'Visible filter scope is not present in backend filter metadata.'
      console.error(message, { requestScope, options })
      setError(message)
      setLoading(false)
      return
    }
    try {
      const userId = activeScenario ? activeScenario.user_id : identityForPersona(persona)
      const req = buildDiagnosisRequest({ apiBase: API_BASE, scenarioId, persona, region, category, date, userId })

      const response = await fetch(req.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req.body),
      })
      const rawPayload = await response.json().catch(() => null)
      if (requestId !== diagnosisRequest.current) return
      const execution = parseScenarioExecution(response.status, rawPayload)

      if (!execution.ok) {
        throw new Error(execution.error ?? 'Diagnosis failed')
      }

      if (execution.accessDenied) {
        if (validateGovernedAccessDenied(execution.payload, activeScenario?.scenario_id)) {
           // Treated as a successful scenario run
           const payload = execution.payload!
           setResults(payload.results as Record<string, Result> ?? {})
           setMarketingBrief(payload.marketing_brief as MarketingBrief ?? null)
           setKpiStory(payload.kpi_story as KpiStory ?? null)
           setScenarioMeta(buildScenarioMetadata(payload))
           setMessages([])
           setConversationId(undefined)
           setAssistantMode('closed')
           setDraft('')
           return
        } else {
           setAccessDeniedMessage('Access denied: You do not have permission to view this data.')
           return
        }
      }

      const payload = execution.payload!
      const responseScope = (payload.marketing_brief as any)?.scope
      if (!scenarioLocked && responseScope && ((responseScope.region ?? 'ALL') !== region || (responseScope.category ?? 'ALL') !== category || responseScope.target_date !== date)) {
        const message = 'Returned diagnosis scope does not match the visible filters.'
        console.error(message, { requestScope, responseScope })
        throw new Error(message)
      }

      const firstResult = Object.values(payload.results ?? {})[0] as Result | undefined
      // In scenario mode, the returned scope is governed by the catalog and matches what we enforced in DemoProvider.
      // So we can be a bit more relaxed or assume it matches.

      setResults(payload.results as Record<string, Result> ?? {})
      setMarketingBrief(payload.marketing_brief as MarketingBrief ?? null)
      setKpiStory(payload.kpi_story as KpiStory ?? null)
      setScenarioHistory(payload.history as any ?? null)
      if (scenarioId) {
        setScenarioMeta(buildScenarioMetadata(payload))
      }
      setMessages([])
      setConversationId(undefined)
    } catch (requestError) {
      if (requestId === diagnosisRequest.current) setError(requestError instanceof Error ? requestError.message : 'Could not reach the KPI backend')
    } finally {
      if (requestId === diagnosisRequest.current) setLoading(false)
    }
  }

  useEffect(() => { void loadMetadata() }, [])
  useEffect(() => { if (ready) void diagnose() }, [ready, region, category, date, persona, scenarioId, movementRunToken])
  useEffect(() => {
    if (!loading && result && pendingMovement.current === selected) {
      pendingMovement.current = null
      detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [loading, result, selected])
  useEffect(() => {
    if (!ready || !date) return
    if (!options.dates.includes(date)) {
      setMovements([])
      setMovementsLoading(false)
      setMovementsFetched(true)
      return
    }
    const controller = new AbortController()
    const userId = activeScenario ? activeScenario.user_id : identityForPersona(persona)
    setMovementsLoading(true)
    setMovementsFetched(false)
    const params = new URLSearchParams({ date, user_id: userId })
    fetch(`${API_BASE}/api/movements?${params}`, { cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() : null)
      .then(payload => { if (!controller.signal.aborted) setMovements(payload?.movements ?? []) })
      .catch(() => { if (!controller.signal.aborted) setMovements([]) })
      .finally(() => { if (!controller.signal.aborted) { setMovementsLoading(false); setMovementsFetched(true) } })
    return () => controller.abort()
  }, [ready, date, persona, activeScenario, options.dates])
  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get('runId')
    if (!runId) return
    fetch(`${API_BASE}/api/diagnoses/${encodeURIComponent(runId)}?user_id=${identityForPersona(persona)}`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error('The selected insight is not available to this identity.')))
      .then(payload => {
        const run = payload.result ?? payload
        setResults(current => ({ ...current, [run.kpi_id]: run }))
        setKpiStory(null)
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
    if (!isAssistantAllowed(result.verdict)) {
      setError('The assistant is unavailable for an access-denied result.')
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
  const hasPositiveOpportunity = marketingBrief?.positive_opportunity ?? false
  const regionOptions = mergeScopeOption(movementScopeOptions(options.regions, 'region', persona), region)
  const categoryOptions = mergeScopeOption(movementScopeOptions(options.categories, 'category', persona), category)
  const scenarioOptions = [{ value: '', label: 'Standard view' }, ...scenarios.map(s => ({ value: s.scenario_id, label: s.title }))]

  return <div className={`app-shell ${theme}`} style={{ '--assistant-width': `${panelWidth}px` } as React.CSSProperties}>
    <AppHeader active="Overview" />

    <main className="workspace" data-ai={isAssistantOpen ? 'open' : assistantMode}>
      <section className="dashboard-column">
        <div className="page-heading">
          <div><span className="eyebrow"><LayoutDashboard size={14} /> {persona === 'CFO' ? 'Financial reviewer workspace' : persona === 'regional_manager_north' ? 'Regional manager (North) workspace' : 'Marketing manager workspace'}</span><h1>Performance overview</h1><p>What changed, what may explain it, and what to verify next.</p></div>
          <div className="filter-row" style={{ display: 'flex', alignItems: 'flex-end', gap: '10px', flexWrap: 'wrap' }}>
            <div style={{ width: '200px' }}>
              <CustomSelect label="Demo scenario" ariaLabel="Demo scenario" value={scenarioId} onChange={selectScenario} options={scenarioOptions} />
            </div>
            <div style={{ width: '130px' }} title={scenarioLocked ? 'Locked by active scenario' : ''}>
              <CustomSelect label="Region" ariaLabel="Region" value={region} onChange={setRegion} options={regionOptions} disabled={scenarioLocked} />
            </div>
            <div style={{ width: '150px' }} title={scenarioLocked ? 'Locked by active scenario' : ''}>
              <CustomSelect label="Category" ariaLabel="Category" value={category} onChange={setCategory} options={categoryOptions} disabled={scenarioLocked} />
            </div>
            <DateFilter date={date} dates={options.dates} onChange={setDate} disabled={scenarioLocked} />
            <button className="run-button" style={{ minHeight: '40px', height: '40px' }} disabled={!mounted || !ready || loading || !options.dates.includes(date)} onClick={() => void diagnose()}>
              <RefreshCw size={15} className={loading ? 'spin' : ''} /> Run
            </button>
          </div>
        </div>

        {activeScenario && (
          <div className="scenario-banner card" style={{ background: 'var(--brand)', color: 'var(--foreground)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <span className="eyebrow" style={{ color: 'var(--foreground-muted)' }}>Active Demo Scenario</span>
                <h3>{activeScenario.title}</h3>
                <p>{activeScenario.purpose}</p>
                <div style={{ marginTop: '8px', fontSize: '14px', display: 'flex', gap: '12px' }}>
                  <span><strong>Governed Scope:</strong> {activeScenario.persona} · {activeScenario.region} · {activeScenario.category}</span>
                  <span><strong>Source:</strong> {activeScenario.source_mode}</span>
                  {activeScenario.uses_demo_fixture && <span className="evidence-pill">Simulated demonstration data</span>}
                </div>
                {scenarioMeta && (
                   <div style={{ marginTop: '8px', fontSize: '15px' }}>
                     <strong>Expected Outcome:</strong> {scenarioMeta.expectedBroadOutcome}
                     {' · '}
                     <strong>Observed Outcome:</strong> {scenarioMeta.observedBroadOutcome}
                     {' '}
                     {scenarioMeta.expectedOutcomeObserved ? (
                       <span style={{ color: 'var(--success)', fontWeight: 'bold' }}>✓ Matched</span>
                     ) : (
                       <span style={{ color: 'var(--danger)', fontWeight: 'bold' }}>⚠️ Mismatch</span>
                     )}
                   </div>
                )}
              </div>
              <button onClick={returnToManual} className="button secondary">Return to manual analysis</button>
            </div>
          </div>
        )}

        <div className="context-strip"><strong>{region} · {category} · {date}</strong><span>{materialCount} of {registeredKpis.length} KPIs are material</span></div>
        {accessDeniedMessage && <div className="alert error"><ShieldAlert size={18} /><span>{accessDeniedMessage}</span></div>}
        {result?.verdict === 'ACCESS_DENIED' && (
          <div className="alert warning" style={{ borderLeft: '4px solid var(--warning)' }}>
            <ShieldAlert size={18} />
            <div>
              <strong>Access denied as expected</strong>
              <p>{result.narrative}</p>
            </div>
          </div>
        )}
        {error && <div className="alert error"><ShieldAlert size={18} /><span>{error}</span></div>}
        {loading && <div className="alert"><Activity className="spin" size={18} /><span>Running the governed KPI engine across daily, weekly, and monthly sources…</span></div>}

        {(movementsLoading || movementsFetched) && (
          <section className="card movements-card" aria-labelledby="movements-title">
            <div className="movements-heading">
              <div>
                <span className="eyebrow">Detection only, ranked by priority</span>
                <div className="movements-title-row"><h3 id="movements-title">Top movements today</h3>
                  <button type="button" className="movements-info-button" aria-label="How movement priority is ranked" aria-expanded={priorityInfoOpen} aria-controls="movements-priority-info" onClick={() => setPriorityInfoOpen(value => !value)}>ⓘ</button>
                </div>
              </div>
              {movementsLoading && <Activity className="spin" size={16} />}
            </div>
            {priorityInfoOpen && <div id="movements-priority-info" className="movements-popover" role="note">
              Priority = how far the change is outside its normal range (capped at 3× the alert threshold) × the change in revenue terms × this KPI’s weight. Material movements are flagged separately.
            </div>}
            {movementsLoading && !movementsFetched ? <div className="movements-list" aria-label="Loading movements">{[1, 2, 3].map(rank => <div className="movement-skeleton" key={rank} />)}</div>
              : movements.length === 0 ? <p className="movements-empty">No movements were found for this date and persona.</p>
              : <div className="movements-list">
              {movements.slice(0, 5).map((item, index) => {
                const unit = registeredKpis.find(candidate => candidate.kpi_id === item.kpi_id)?.unit ?? 'count'
                const active = selected === item.kpi_id && region === (item.region ?? 'ALL') && category === (item.category ?? 'ALL') && date === item.target_date
                return (
                  <button
                    key={`${item.kpi_id}-${item.region ?? 'ALL'}-${item.category ?? 'ALL'}`}
                    onClick={() => openMovement(item)}
                    disabled={scenarioLocked}
                    title={scenarioLocked ? 'Return to Standard view to open a movement; this demo scenario locks its scope.' : `Priority ${item.priority.toLocaleString('en-IN', { maximumFractionDigits: 1 })}`}
                    className={`movement-row${active ? ' active' : ''}`}
                    aria-current={active ? 'true' : undefined}
                  >
                    <span className="movement-rank">{index + 1}</span>
                    <span className="movement-name"><strong>{kpiLabel(item.kpi_id)}</strong><small>{item.region ?? 'All regions'} · {item.category ?? 'All categories'}</small></span>
                    <span className="movement-change"><strong>{formatDelta(item.delta, unit)}</strong><small>{item.rel_delta == null ? 'Change % unavailable' : `${(item.rel_delta * 100).toFixed(1)}% change`} · Priority {item.priority.toLocaleString('en-IN', { maximumFractionDigits: 1 })}</small></span>
                    <span className={`movement-material ${item.is_material ? 'material' : 'not-material'}`}>{item.is_material ? 'Material' : 'Not material'}</span>
                  </button>
                )
              })}
            </div>}
            <small className="movements-footnote">
              Movement detection only -- no driver ranking or causal check yet. Click a row to open that slice's full diagnosis.
            </small>
          </section>
        )}

        {marketingBrief && result?.verdict !== 'ACCESS_DENIED' && <section className="marketing-brief" aria-labelledby="briefing-title">
          <div className="briefing-lead"><div><span className="eyebrow">{persona === 'CFO' ? 'Financial reviewer briefing' : persona === 'regional_manager_north' ? 'Regional manager (North) briefing' : 'Marketing manager briefing'}</span><h2 id="briefing-title">What you need to know today</h2><p>{marketingBrief.summary}</p><small>{marketingBrief.first_weak_stage ? `First observed weak funnel stage: ${marketingBrief.first_weak_stage.label}${marketingBrief.first_weak_stage.material ? ' · material' : ''}` : 'No first weak stage established'}</small></div><span className="evidence-pill">{region} · {category} · {date}</span></div>
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
          <details className="brief-method"><summary>Method and evidence details</summary><p>{marketingBrief.method}. Co-movement is not proof of causality and related KPI movements are not summed as separate causes.</p><small>Overall evidence: {result?.confidence_profile?.overall.status ?? 'PROFILE_NOT_SAVED'} · Causal verification: {result?.causal_verdict ?? 'UNTESTABLE'} · Engine verdict: {result?.verdict}</small></details>
        </section>}

        {!loading && result?.verdict !== 'ACCESS_DENIED' && <KpiFlow story={kpiStory} onSelect={kpiId => { setSelected(kpiId); detailRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} />}

        <section ref={detailRef} className="kpi-selector supporting-kpis" aria-label="Registered KPIs">
          {registeredKpis.map(item => {
            const itemResult = results[item.kpi_id]
            const itemMovement = itemResult?.movement_assessment
            const Icon = kpiIcon(item.kpi_id)
            if (result?.verdict === 'ACCESS_DENIED') {
               return <button key={item.kpi_id} className={selected === item.kpi_id ? 'kpi-tile active' : 'kpi-tile'} onClick={() => setSelected(item.kpi_id)}><span><Icon size={16} />{kpiLabel(item.kpi_id)}</span><strong>—</strong><small>—</small></button>
            }
            if (itemResult?.verdict === 'INSUFFICIENT_HISTORY') {
               return <button key={item.kpi_id} className={selected === item.kpi_id ? 'kpi-tile active' : 'kpi-tile'} onClick={() => setSelected(item.kpi_id)}><span><Icon size={16} />{kpiLabel(item.kpi_id)}</span><strong>—</strong><small>Insufficient history</small></button>
            }
            return <button key={item.kpi_id} className={selected === item.kpi_id ? 'kpi-tile active' : 'kpi-tile'} onClick={() => setSelected(item.kpi_id)}><span><Icon size={16} />{kpiLabel(item.kpi_id)}</span><strong>{formatValue(itemMovement?.actual_value, item.unit)}</strong><small className={(itemMovement?.delta ?? 0) < 0 ? 'negative' : 'positive'}>{formatDelta(itemMovement?.delta, item.unit)} vs baseline</small></button>
          })}
        </section>

        {result?.verdict !== 'ACCESS_DENIED' && (
        <section className="hero-card card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(230px, 0.8fr) minmax(320px, 1.2fr)', gap: '24px', alignItems: 'center' }}>
            <div className="hero-summary">
              <span className="eyebrow">Primary observed KPI</span>
              <h2>{selectedKpiLabel}</h2>
              <Link className="contract-inline-link" href={contractViewerHref(selected)} aria-label={`View ${selectedKpiLabel} semantic contract`}>View KPI contract</Link>
              <div className="hero-number">{formatValue(movement?.actual_value, kpi.unit)}</div>
              <p className={(movement?.delta ?? 0) < 0 ? 'negative' : 'positive'}>
                <ArrowDownRight size={16} /> {formatDelta(movement?.delta, kpi.unit)} versus the engine baseline
              </p>
              <span className={`evidence-pill ${movement?.is_material ? 'warning' : 'good'}`}>
                {movement?.is_material ? 'Material movement' : 'Not material'}
              </span>
            </div>

            <div className="comparison-chart" role="img" aria-label={`${selectedKpiLabel} actual compared with expected baseline`}>
              <div className="chart-head"><span>Target Date Summary</span><small>Deviation from expected</small></div>
              <div className="deviation-values"><span>Expected <strong>{formatValue(movement?.expected_value, kpi.unit)}</strong></span><span>Actual <strong>{formatValue(movement?.actual_value, kpi.unit)}</strong></span></div>
              {deviation.percent == null ? <p className="deviation-unavailable">Percentage difference unavailable for this baseline.</p> : <>
                <strong className={`deviation-change ${deviation.percent < 0 ? 'down' : 'up'}`}>{deviation.percent >= 0 ? '+' : ''}{deviation.percent.toFixed(1)}% ({formatDelta(deviation.delta, kpi.unit)})</strong>
                <div className="deviation-track" aria-hidden="true">
                  {deviation.alertLeft != null && <i className="deviation-band alert" style={{ left: `${deviation.alertLeft}%`, width: `${deviation.alertWidth}%` }} />}
                  {deviation.normalLeft != null && <i className="deviation-band normal" style={{ left: `${deviation.normalLeft}%`, width: `${deviation.normalWidth}%` }} />}
                  <i className="deviation-zero" />
                  <i className={`deviation-fill ${deviation.percent < 0 ? 'down' : 'up'}`} style={{ left: `${deviation.barLeft}%`, width: `${deviation.barWidth}%` }} />
                </div>
                <div className="deviation-axis"><span>Below expected</span><strong>0% expected</strong><span>Above expected</span></div>
                {deviation.normalWidth != null && <small className="deviation-key">Shaded centre: normal range{deviation.alertWidth != null ? ' · outer band: alert threshold' : ''}</small>}
              </>}
              <div className="chart-caption"><Database size={14} /> Target date {date} · As of {result?.as_of ? new Date(result.as_of).toLocaleString('en-IN') : 'awaiting run'}</div>
            </div>
          </div>

          {/* Real Governed Time-Series Trend Line Chart */}
          {activeScenario?.source_mode === 'demo_fixture' ? (
             <div className="alert info">Trend chart unavailable because this scenario uses an isolated demonstration fixture.</div>
          ) : !isTrendChartAllowed(activeScenario?.source_mode, result?.verdict) ? null : (
            <KpiTrendChart
              apiBase={API_BASE}
              kpiId={selected}
              kpiLabel={selectedKpiLabel}
              unit={kpi.unit}
              region={region}
              category={category}
              targetDate={date}
              userId={activeScenario ? activeScenario.user_id : identityForPersona(persona)}
            />
          )}
        </section>
        )}

        {result && result.verdict !== 'ACCESS_DENIED' && (
          <>
        {result?.verdict === 'INSUFFICIENT_HISTORY' && (
          <div className="alert info">
            <Activity size={18} />
            <div>
              <strong>Sparse history / new launch</strong>
              <p>Normal driver ranking and attribution were skipped. Baseline observation count: {scenarioHistory?.baseline_count ?? 'unknown'} / Required: {scenarioHistory?.required_observation_count ?? 'unknown'}</p>
            </div>
          </div>
        )}

        {result?.verdict === 'CONTRADICTED' && (
          <div className="alert warning">
            <ShieldAlert size={18} />
            <div>
              <strong>Contradictory sources</strong>
              <p>Contradictory reconciliation status: {result.reconciliation_verdict?.status}. Attribution and downstream action were blocked.</p>
            </div>
          </div>
        )}

            <DriverAnalysisOverview analysis={result?.driver_analysis} profile={result?.confidence_profile} causalTest={result?.causal_verification} expected={movement?.expected_value} actual={movement?.actual_value} isMaterial={movement?.is_material} unit={kpi.unit} displayNames={overviewDriverNames} seriesChart={(driverId, label) => activeScenario?.source_mode === 'demo_fixture' ? null : <DriverVsKpiChart apiBase={API_BASE} kpiId={selected} kpiLabel={selectedKpiLabel} kpiUnit={kpi.unit} driverId={driverId} driverLabel={label} region={region} category={category} targetDate={date} userId={activeScenario ? activeScenario.user_id : identityForPersona(persona)} asOf={result?.as_of} />} />
            {result?.funnel_bridge && <FunnelBridgeCard bridge={result.funnel_bridge} status={result.funnel_bridge_status} movements={Object.fromEntries(Object.entries(results).map(([id, item]) => [id, item.movement_assessment]))} />}

        <section className="insight-grid"><article className="card narrative-card"><span className="eyebrow">Executive conclusion</span><h3>{result?.verdict ? statusLabel(result.verdict) : 'Awaiting analysis'}</h3><p>{result?.narrative || 'Narrative is not available for this run.'}</p><details className="technical-details"><summary>Technical narrative and evidence</summary><div className="meta-line"><CheckCircle2 size={15} /> Grounding {result?.grounding_passed ? 'passed' : 'not established'} · {titleCase(result?.narrative_method)}</div></details></article>
        </section>

        <ActionWorkspace actions={result?.decision_cards} persona={persona} verdict={result?.verdict} onAsk={recommendation => void askQuestion(`What evidence supports this recommendation: ${recommendation}`)} />

        {result?.verdict !== 'ACCESS_DENIED' && evidenceData?.source_readiness && (
          <section className="card source-summary-card">
            <div className="card-heading">
              <div>
                <span className="eyebrow">Data foundation</span>
                <h3>Sources and reconciliation</h3>
              </div>
              <div className="source-summary-actions"><button type="button" className="movements-info-button" aria-label="Explain data foundation statuses" aria-expanded={foundationInfoOpen} onClick={() => setFoundationInfoOpen(value => !value)}>ⓘ</button><span className={`evidence-pill ${
                evidenceData.source_readiness.status === 'READY' ? 'good' :
                evidenceData.source_readiness.status === 'QUALITY_FAILED' ? 'warning' : 'limited'
              }`}>
                {titleCase(evidenceData.source_readiness.status)}
              </span></div>
            </div>
            {foundationInfoOpen && <div className="source-summary-popover" role="note">
              <p><strong>FULL</strong> covers the selected period. <strong>PARTIAL</strong> is loaded but incomplete: weekly marketing publishes two days after week end; finance closes about five days after month end.</p>
              <p><strong>EMPTY</strong> has no rows for this scope. <strong>NOT_LOADED</strong> was not needed for this KPI. <strong>RESTRICTED</strong> was used but is hidden for your role.</p>
              <p><strong>AGREED</strong> means sources agree. <strong>PENDING_CLOSE</strong> means finance is awaiting close. <strong>DRIFT</strong> means a larger than usual gap. <strong>CONTRADICTED</strong> means a material disagreement.</p>
            </div>}
            <div className="source-summary-grid">
              {([['sales_daily', 'Daily sales'], ['marketing_weekly', 'Weekly marketing'], ['finance_monthly', 'Monthly finance']] as const).map(([id, label]) => {
                const source = evidenceData.sources?.find(item => item.source_id === id)
                const status = sourceStatus(source?.coverage_status, id)
                const latest = source?.latest_available_time ?? source?.latest_event_time
                return <div className="source-tile" key={id}>
                  <div className="source-tile-head"><strong>{label}</strong><span className={`source-status ${status.tone}`}>{status.label}</span></div>
                  <small>Latest available: {latest ? latest.slice(0, 10) : status.label === 'RESTRICTED' ? 'Hidden for your role' : 'Unavailable'}</small>
                  <p>{status.meaning}</p>
                </div>
              })}
            </div>
            <div className="source-reconciliation">
              <div><strong>Independent reconciliation</strong><p>{evidenceData.reconciliation?.reason ?? reconciliationStatus(evidenceData.reconciliation?.status).meaning}</p>
                <small>{evidenceData.reconciliation?.gap_percent != null ? `Gap: ${evidenceData.reconciliation.gap_percent.toFixed(1)}%` : 'Gap: hidden or unavailable'}{reconciliationMode(evidenceData.reconciliation?.comparison_basis ?? evidenceData.reconciliation?.details?.mode) ? ` · ${reconciliationMode(evidenceData.reconciliation?.comparison_basis ?? evidenceData.reconciliation?.details?.mode)}` : ''}</small>
              </div>
              <span className={`source-status ${reconciliationStatus(evidenceData.reconciliation?.status).tone}`}>{reconciliationStatus(evidenceData.reconciliation?.status).label}</span>
            </div>
            <small className="source-as-of">Requested as-of cutoff: {evidenceData.as_of ?? 'latest available'}</small>
          </section>
        )}

        {result && <ProcessingTransparencyView transparency={result.processing_transparency} compact />}

        <footer className="source-footer"><span>Run {result?.run_id ?? '—'}</span><span>Source status: {titleCase(result?.reconciliation_verdict?.status)}</span><span>Persona: {persona === 'CFO' ? 'CFO' : persona === 'regional_manager_north' ? 'Regional manager (North)' : 'Marketing manager'}</span></footer>
          </>
        )}
      </section>

      {isAssistantAllowed(result?.verdict) && assistantMode === 'closed' && <Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} disabled={loading} />}
      {isAssistantAllowed(result?.verdict) && assistantMode === 'minimized' && <button className="restore-pill" onClick={() => setAssistantMode('open')}><Bot size={17} /> Ask KPI Assistant</button>}

      {isAssistantAllowed(result?.verdict) && isAssistantOpen && <aside className="assistant-panel" aria-label="KPI assistant"><button className="resize-handle" aria-label="Resize assistant" onPointerDown={beginResize}><GripVertical size={17} /></button><header className="assistant-header"><div className="assistant-title"><span><Bot size={18} /></span><div><strong>KPI Assistant</strong><small>{selectedKpiLabel} · {region} · {date}</small></div></div><div className="assistant-actions"><button onClick={() => setPanelWidth(panelWidth === 600 ? 410 : 600)} aria-label="Toggle assistant width"><Maximize2 size={16} /></button><button onClick={() => setAssistantMode('minimized')} aria-label="Minimize assistant"><Minimize2 size={16} /></button><button onClick={() => { setAssistantMode('closed'); setMessages([]); setConversationId(undefined) }} aria-label="Close assistant"><X size={18} /></button></div></header><div className="assistant-context"><Sparkles size={14} /> Grounded in run {result?.run_id ?? 'not available'}</div><div className="conversation">{!messages.length && <div className="assistant-empty"><span><Sparkles size={22} /></span><h2>Ask your marketing analyst</h2><p>I’ll explain the movement, distinguish evidence from hypotheses, and surface safe next steps.</p></div>}{messages.map(message => <article key={message.id} className={`message ${message.role}`}><p>{message.text}</p>{message.citations?.length ? <details><summary>{message.citations.length} evidence reference{message.citations.length === 1 ? '' : 's'}</summary>{message.citations.map((citation, index) => <small key={`${citation.source_path}-${index}`}>{citation.evidence_type}: {citation.source_path}{citation.line_or_row_ref ? ` · ${citation.line_or_row_ref}` : ''}</small>)}</details> : null}{message.limitations?.length ? <div className="limitations"><strong>Limits</strong>{message.limitations.map(item => <small key={item}>{item}</small>)}</div> : null}</article>)}{asking && <div className="thinking"><i /><i /><i /></div>}<div ref={conversationEnd} /></div><div className="assistant-suggestions">{['What changed?', 'Is the cause proven?', 'What should I verify next?'].map(item => <button key={item} onClick={() => void askQuestion(item)}>{item}</button>)}</div><Composer value={draft} setValue={setDraft} submit={() => void askQuestion()} panel disabled={asking} /></aside>}
    </main>
  </div>
}
