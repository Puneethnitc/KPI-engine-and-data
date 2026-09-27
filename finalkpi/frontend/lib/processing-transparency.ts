export type ProcessingStage = {
  stage_id: string
  label: string
  method_category: 'DETERMINISTIC' | 'SQL_QUERY' | 'BUSINESS_RULE' | 'STATISTICAL' | 'TRADITIONAL_ML' | 'CAUSAL' | 'RETRIEVAL' | 'LLM'
  execution_status: 'USED' | 'SKIPPED' | 'NOT_REQUESTED' | 'UNAVAILABLE' | 'FALLBACK' | 'BLOCKED'
  quantitative_truth: boolean
  purpose: string
  method_id: string
  evidence_refs: string[]
  limitation: string | null
  llm_role: string | null
}

export type ProcessingTransparency = {
  contract_version: string
  quantitative_truth_policy: string
  stages: ProcessingStage[]
  summary: {
    quantitative_stages: number
    llm_used: boolean
    retrieval_used: boolean
    sql_executed: boolean
    causal_method_used: boolean
  }
}

export type RuntimeTelemetryStage = {
  stage: string
  processing_type: string
  method: string
  latency_ms: number
  status: string
  cache_status: string
  provider: string | null
  model: string | null
  model_calls: number
  input_tokens: number | null
  output_tokens: number | null
  estimated_cost_usd: number | null
  usage_source: string
}

export type RuntimeTelemetry = {
  execution_id: string
  started_at: string
  completed_at: string
  total_latency_ms: number
  stages: RuntimeTelemetryStage[]
  llm_summary: {
    provider: string | null
    model: string | null
    model_calls: number
    input_tokens: number | null
    output_tokens: number | null
    estimated_cost_usd: number | null
    usage_source: string
  }
  cache_summary: { hits: number; misses: number; not_applicable: number }
  limits: {
    timeout_ms?: number | null
    max_model_calls?: number | null
    max_input_tokens?: number | null
    fallback_behavior?: string | null
    pricing_version?: string | null
    [key: string]: unknown
  }
}

export function runtimeLatencyLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable'
  if (value === 0) return '0 ms'
  return value < 1000 ? `${value.toFixed(1)} ms` : `${(value / 1000).toFixed(2)} s`
}

export function runtimeTokenLabel(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? 'Unavailable' : String(value)
}

export function runtimeCostLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'Unavailable'
  if (value === 0) return '$0.00'
  if (Math.abs(value) < 0.0001) return '<$0.0001'
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4,
  }).format(value)
}

export function runtimeTimestampLabel(value: string | null | undefined): string {
  return value || 'Unavailable'
}

export function processingStatusLabel(status: ProcessingStage['execution_status']): string {
  return status === 'NOT_REQUESTED' ? 'Not requested' : status.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function processingCategoryLabel(category: ProcessingStage['method_category']): string {
  return category === 'SQL_QUERY' ? 'SQL query' : category.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase())
}

export function processingStatusTone(status: ProcessingStage['execution_status']): 'good' | 'warning' | 'danger' | 'neutral' {
  if (status === 'USED') return 'good'
  if (status === 'FALLBACK') return 'warning'
  if (status === 'BLOCKED') return 'danger'
  return 'neutral'
}
