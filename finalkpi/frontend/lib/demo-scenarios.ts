export type DemoScenario = {
  scenario_id: string
  title: string
  purpose: string
  demonstration_category: string
  persona: string
  user_id: string
  kpis: string[]
  primary_kpi: string
  region: string
  category: string
  target_date: string
  as_of: string | null
  source_mode: 'production' | 'demo_fixture'
  fixture_id: string | null
  uses_demo_fixture: boolean
  fixture_label: string | null
  expected_broad_outcome: string
}

export type ScenarioExecutionRequest = {
  url: string
  body: Record<string, unknown>
}

export function identityForPersona(persona: string) {
  if (persona === 'CFO') return 'demo-cfo'
  if (persona === 'regional_manager_north') return 'demo-regional-north'
  return 'demo-marketing'
}

export function personaLabel(persona: string) {
  if (persona === 'CFO') return 'CFO'
  return persona.replaceAll('_', ' ').replace(/(^|\s)\S/g, character => character.toUpperCase())
}

export function buildDiagnosisRequest(args: {
  apiBase: string
  scenarioId?: string | null
  persona: string
  region: string
  category: string
  date: string
  userId: string
}): ScenarioExecutionRequest {
  if (args.scenarioId) {
    return {
      url: `${args.apiBase}/api/demo-scenarios/${encodeURIComponent(args.scenarioId)}/execute`,
      body: { user_id: args.userId },
    }
  }
  return {
    url: `${args.apiBase}/api/diagnoses`,
    body: {
      kpis: ['all'],
      target_date: args.date,
      region: args.region,
      category: args.category,
      persona: args.persona,
      user_id: args.userId,
    },
  }
}

export function parseScenarioExecution(status: number, payload: any) {
  const nested = payload?.detail && typeof payload.detail === 'object' ? payload.detail : payload
  const isScenarioPayload = Boolean(nested?.scenario && nested?.resolved_scope)
  if (status === 403 && isScenarioPayload) {
    return { ok: true, accessDenied: true, payload: nested as Record<string, unknown> }
  }
  if (!status.toString().startsWith('2')) {
    const message = typeof payload?.detail === 'string' ? payload.detail : payload?.detail?.narrative || 'Diagnosis failed'
    return { ok: false, accessDenied: status === 403 || status === 401, payload: null, error: message }
  }
  return { ok: true, accessDenied: false, payload: nested as Record<string, unknown> }
}

export function mergeScopeOption(options: string[], value: string): string[] {
  if (!value) return options
  return options.includes(value) ? options : [...options, value]
}

export function isTrendChartAllowed(sourceMode?: string, verdict?: string): boolean {
  if (sourceMode === 'demo_fixture') return false
  if (verdict === 'ACCESS_DENIED' || verdict === 'INSUFFICIENT_HISTORY') return false
  return true
}

export function isAssistantAllowed(verdict?: string): boolean {
  return verdict !== 'ACCESS_DENIED'
}

export function validateGovernedAccessDenied(payload: any, activeScenarioId?: string): boolean {
  if (!payload || !activeScenarioId) return false
  return payload.scenario?.scenario_id === activeScenarioId && payload.observed_broad_outcome === 'ACCESS_DENIED'
}

export function buildScenarioMetadata(payload: any) {
  if (!payload) return null
  return {
    observedBroadOutcome: payload.observed_broad_outcome,
    expectedBroadOutcome: payload.expected_broad_outcome,
    expectedOutcomeObserved: payload.expected_outcome_observed,
    usesDemoFixture: payload.uses_demo_fixture,
    resolvedScenarioScope: payload.resolved_scope,
    scenarioId: payload.scenario?.scenario_id,
  }
}
