import type { DemoScenario } from './demo-scenarios'
export type JuryScenarioResult = { scenarioId: string; expected: string; observed: string; matched: boolean; runId: string | null; accessDenied: boolean; error?: string }
export const juryRequirements = [
  ['materiality', 'Material KPI movement', ['material-multi-driver', 'non-material-baseline']],
  ['reconciliation', 'Source reconciliation and contradictory evidence', ['contradictory-sources']],
  ['drivers', 'Multi-factor driver ranking and contribution', ['material-multi-driver']],
  ['uncertainty', 'Confidence, abstention and limitations', ['low-confidence-abstention']],
  ['sparse', 'Sparse-history handling', ['sparse-history-new-launch']],
  ['security', 'Role-based security and entitlements', ['unauthorized-scope']],
] as const
export function scenarioRunId(payload: any): string | null {
  if (payload?.engine_result?.run_id) return String(payload.engine_result.run_id)
  const values = payload?.results && typeof payload.results === 'object' ? Object.values(payload.results) : []
  const first = values.find((value: any) => value?.run_id) as any
  return first?.run_id ? String(first.run_id) : null
}
export function parseJuryResult(scenario: DemoScenario, status: number, payload: any): JuryScenarioResult {
  const body = payload?.detail && typeof payload.detail === 'object' ? payload.detail : payload
  const observed = String(body?.observed_broad_outcome || (status === 403 ? 'ACCESS_DENIED' : 'ERROR'))
  return { scenarioId: scenario.scenario_id, expected: scenario.expected_broad_outcome, observed,
    matched: Boolean(body?.expected_outcome_observed) && observed === scenario.expected_broad_outcome,
    runId: status === 403 ? null : scenarioRunId(body), accessDenied: observed === 'ACCESS_DENIED',
    ...(!status.toString().startsWith('2') && status !== 403 ? { error: typeof payload?.detail === 'string' ? payload.detail : 'Scenario execution failed' } : {}) }
}
export function requirementPassed(ids: readonly string[], results: Record<string, JuryScenarioResult>) { return ids.every(id => results[id]?.matched) }
