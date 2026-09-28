export type ActionEvidenceReference = {
  evidence_type?: string | null
  path?: string | null
  driver_id?: string | null
  driver_rank?: number | null
  source_id?: string | null
  period?: string | null
  method?: string | null
}

export type ActionContract = {
  action_id?: string | null
  kind?: string | null
  status?: string | null
  driver_id?: string | null
  driver_rank?: number | null
  driver_relationship?: string | null
  controllability?: string | null
  lever?: string | null
  recommendation?: string | null
  owner?: string | null
  owner_source?: string | null
  decision_right?: string | null
  approval_required?: boolean | null
  expected_impact?: number | null
  expected_impact_unit?: string | null
  impact_method?: string | null
  impact_explanation?: string | null
  evidence_status?: string | null
  confidence_status?: string | null
  evidence_references?: ActionEvidenceReference[] | null
  constraints?: string[] | null
  monitoring_plan?: string | null
  success_metric?: string | null
  review_window?: string | null
  stop_conditions?: string[] | null
  limitations?: string[] | null
  evidence_paths?: string[] | null
  persona?: string | null
  attribution_confidence?: number | null
  attribution_band?: string | null
  attribution_label?: string | null
  expected_impact_low?: number | null
  expected_impact_high?: number | null
  approval_threshold?: number | null
}

const structuredActionFields = [
  'action_id', 'driver_rank', 'driver_relationship', 'controllability', 'owner_source',
  'decision_right', 'approval_required', 'expected_impact_unit', 'impact_method',
  'impact_explanation', 'evidence_status', 'confidence_status', 'evidence_references',
  'constraints', 'monitoring_plan', 'success_metric', 'review_window', 'stop_conditions', 'limitations',
]

export function isLegacyAction(action: ActionContract): boolean {
  return structuredActionFields.every(field => !(field in action))
}

export function actionCountLabel(actions: ActionContract[] | null | undefined): string {
  const items = actions ?? []
  if (!items.length) return 'No action'
  if (items.length === 1 && items[0].kind === 'ACTION_PROPOSAL') return '1 action proposal'
  if (items.length === 1 && items[0].kind === 'NEXT_CHECK') return '1 verification check'
  return `${items.length} recommendation${items.length === 1 ? '' : 's'}`
}

export function actionStatusLabel(action?: ActionContract | null): string {
  if (!action) return 'Abstention'
  if (action.kind === 'ACTION_PROPOSAL') return 'Action proposal'
  if (action.status === 'BLOCKED' || action.driver_relationship === 'BLOCKED') return 'Blocked'
  return 'Verification / next check'
}

export function actionBoundary(action?: ActionContract | null): string {
  if (action?.kind === 'ACTION_PROPOSAL') return 'Recommendation is evidence-linked guidance, not a guaranteed outcome.'
  if (action?.driver_relationship === 'ASSOCIATION' || action?.kind === 'NEXT_CHECK') return 'Association only—not contribution or causation.'
  return 'Recommendation is evidence-linked guidance, not a guaranteed outcome.'
}

export function actionImpactLabel(action?: ActionContract | null): string {
  if (!action || action.expected_impact == null) {
    return action?.impact_explanation || 'Impact is not estimated with available evidence.'
  }
  return `${action.expected_impact}${action.expected_impact_unit ? ` ${action.expected_impact_unit}` : ''}`
}

export function safeEvidencePath(path?: string | null): string {
  if (!path || path.startsWith('/') || /^[A-Za-z]:[\\/]/.test(path)) return 'Protected evidence reference'
  return path
}

export function actionPersonaFrame(persona: string): string {
  return persona === 'CFO'
    ? 'Finance framing: focus on approval, decision risk, reconciliation and monitoring.'
    : 'Marketing framing: focus on operational next checks, controllable levers and success metrics.'
}
