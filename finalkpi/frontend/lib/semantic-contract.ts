export type ContractCapability = 'SUPPORTED' | 'CONDITIONAL' | 'NOT_APPLICABLE' | 'NOT_SUPPORTED'

export type SemanticContract = {
  schema_version: number
  identity: {
    kpi_id: string
    display_name: string
    version: string | number
    status: string
    definition: string
    business_purpose: string
    owner: string
    steward: string | null
    tags: string[]
  }
  calculation: {
    operator: string
    formula: string
    numerator_column: string | null
    denominator_column: string | null
    value_column: string | null
    weight_column: string | null
    unit: string
    precision: number
    null_policy: string
    zero_policy: string
    aggregation_notes: string[]
    executable_method: string
  }
  grain_and_scope: {
    native_grain: string
    supported_rollups: string[]
    dimensions: string[]
    calendar: string
    timezone: string
    comparison_policy: Record<string, unknown> | null
    minimum_history_periods: number
  }
  source: {
    primary_source_id: string
    source_table: string
    source_grain: string
    event_time_field: string
    availability_time_field: string
    natural_key: string[]
    required_fields: { name: string; type: string; required: boolean; nullable: boolean; unit: string | null; description: string | null }[]
    refresh_cadence: string | null
    access_classification: string
    lineage_reference: string | null
    catalog_version: string
    comparison_source: Record<string, unknown> | null
  }
  materiality: {
    statistical_method: string
    statistical_thresholds: Record<string, number>
    business_thresholds: Record<string, unknown>
    detector_agreement_rule: string
    threshold_status: string
    calibration_reference: string | null
  }
  drivers: {
    candidate_drivers: {
      driver_id: string
      display_name: string
      source_id: string
      column: string
      grain: string
      aggregation: string
      unit: string | null
      controllability: string
      expected_direction: string | null
      allowed_lags: number[] | string | null
      minimum_pairs: number | null
      minimum_coverage: number | null
      owner: string
    }[]
    method: string
    limitations: string[]
  }
  reconciliation: {
    applicable: boolean
    comparison_source_id: string | null
    comparison_metric: string | null
    unit: string | null
    keys: string[]
    mode: string | null
    tolerance: number | null
    contradiction_threshold: number | null
    coverage_rule: string | null
    availability_rule: string | null
    redacted?: boolean
    redaction_reason?: string
  }
  decomposition: {
    applicable: boolean
    method: string | null
    quantity_column: string | null
    rate_column: null
    reference_rate_label: string | null
    derived_rate_formula: string | null
    identity: string | null
    limitations: string[]
  }
  security: {
    access_tags: string[]
    allowed_roles: string[]
    row_scope_dimensions: string[]
    restricted_fields: string[]
    sensitive: boolean
    policy_reference: string
  }
  governance: {
    contract_hash: string
    effective_from: string | null
    effective_to: string | null
    approved_by: string | null
    change_reason: string | null
    source_catalog_version: string
    validation_status: string
    validation_errors: string[]
  }
  capabilities: Record<string, ContractCapability>
}

export type ContractComparison = {
  snapshot_status: string
  same_version: boolean | null
  same_hash: boolean | null
  changed_since_run: boolean | null
}

export type ContractRequestState = 'ready' | 'unauthorized' | 'not-found' | 'invalid' | 'error'

export function contractRequestPath(kpiId: string, runId?: string | null): string {
  return runId
    ? `/api/diagnoses/${encodeURIComponent(runId)}/contract`
    : `/api/kpis/${encodeURIComponent(kpiId)}/contract`
}

export function contractViewerHref(kpiId: string, runId?: string | null): string {
  const path = `/kpis/${encodeURIComponent(kpiId)}`
  return runId ? `${path}?run_id=${encodeURIComponent(runId)}` : path
}

export function contractRequestState(status: number): ContractRequestState {
  if (status === 401 || status === 403) return 'unauthorized'
  if (status === 404) return 'not-found'
  if (status === 400 || status === 422) return 'invalid'
  return status >= 200 && status < 300 ? 'ready' : 'error'
}

export function contractCapabilityLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    SUPPORTED: 'Supported',
    CONDITIONAL: 'Conditional',
    NOT_APPLICABLE: 'Not applicable',
    NOT_SUPPORTED: 'Not supported',
  }
  return value ? labels[value] ?? value.replaceAll('_', ' ') : 'Not specified'
}

export function contractValueLabel(value: unknown, missing = 'Not specified'): string {
  if (value == null || value === '') return missing
  if (Array.isArray(value)) return value.length ? value.join(', ') : missing
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>)
    .map(([key, entry]) => `${key.replaceAll('_', ' ')}: ${contractValueLabel(entry)}`).join(' · ') || missing
  return String(value)
}

export function contractComparisonView(
  comparison?: ContractComparison | null,
  snapshot?: SemanticContract | null,
  current?: SemanticContract | null,
) {
  if (!snapshot) return { state: 'MISSING', changed: false, message: 'No contract snapshot was saved for this historical run. The current contract is not substituted.' }
  const changed = comparison?.changed_since_run ?? Boolean(
    current && (snapshot.governance.contract_hash !== current.governance.contract_hash || snapshot.identity.version !== current.identity.version),
  )
  if (!current) return { state: 'CURRENT_UNAVAILABLE', changed: false, message: 'The current registry contract could not be loaded; the saved run snapshot remains authoritative.' }
  return {
    state: changed ? 'CHANGED' : 'SAME',
    changed,
    message: changed ? 'Contract changed since this run.' : 'Saved run contract matches the current registry.',
  }
}

export function contractPersonaFrame(persona: string): string {
  return persona === 'CFO'
    ? 'Finance review: focus on the authoritative definition, reconciliation controls, materiality, and version lineage.'
    : 'Marketing review: focus on funnel meaning, governed operational levers, and the scope in which this KPI is valid.'
}
