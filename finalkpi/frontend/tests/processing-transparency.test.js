import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const source = fs.readFileSync(filename, 'utf8')
    const compiled = ts.transpileModule(source, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
        esModuleInterop: true,
      },
      fileName: filename,
    }).outputText
    module._compile(compiled, filename)
  }
}

const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const ProcessingTransparencyView = require('../components/processing-transparency.tsx').default

const stage = (overrides = {}) => ({
  stage_id: 'narrative_generation',
  label: 'Narrative generation',
  method_category: 'DETERMINISTIC',
  execution_status: 'USED',
  quantitative_truth: false,
  purpose: 'Renders saved, evidence-bound wording.',
  method_id: 'approved_narrative_templates_v1',
  evidence_refs: [],
  limitation: null,
  llm_role: null,
  ...overrides,
})

const transparency = (overrides = {}) => ({
  contract_version: '1.0',
  quantitative_truth_policy: 'Quantitative values come from governed deterministic methods; LLMs select approved wording only.',
  stages: [stage()],
  summary: {
    quantitative_stages: 3,
    llm_used: false,
    sql_executed: false,
    retrieval_used: false,
    causal_method_used: false,
  },
  ...overrides,
})

function render(contract, props = {}) {
  return renderToStaticMarkup(React.createElement(ProcessingTransparencyView, { transparency: contract, ...props }))
}

const runtimeStage = (overrides = {}) => ({
  stage: 'authorization', processing_type: 'DETERMINISTIC', method: 'identity_and_scope_policy',
  latency_ms: 0, status: 'COMPLETED', cache_status: 'NOT_APPLICABLE', provider: null, model: null,
  model_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0,
  usage_source: 'NOT_APPLICABLE', ...overrides,
})

const runtimeTelemetry = (overrides = {}) => ({
  execution_id: 'exec-test-123', started_at: '2026-09-27T10:00:00+00:00',
  completed_at: '2026-09-27T10:00:01+00:00', total_latency_ms: 1000,
  stages: [runtimeStage(), runtimeStage({stage: 'source_preparation', latency_ms: 12.4})],
  llm_summary: {provider: null, model: null, model_calls: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, usage_source: 'NOT_APPLICABLE'},
  cache_summary: {hits: 0, misses: 1, not_applicable: 0},
  limits: {timeout_ms: 5000, max_model_calls: 2, max_input_tokens: 8192, fallback_behavior: 'deterministic_evidence_bound_fallback', pricing_version: 'rates-v1'},
  ...overrides,
})

test('deterministic diagnosis says LLM not used', () => {
  const html = render(transparency())
  assert.match(html, /LLM not used/)
  assert.match(html, /Quantitative values were computed before narrative generation\./)
})

test('LLM success is described as approved wording only', () => {
  const html = render(transparency({
    stages: [
      stage(),
      stage({ stage_id: 'llm_wording_selection', label: 'Optional LLM wording selection', method_category: 'LLM', llm_role: 'WORDING_ONLY' }),
    ],
    summary: { ...transparency().summary, llm_used: true },
  }))
  assert.match(html, /LLM used for approved wording only/)
  assert.match(html, /Approved wording only/)
  assert.match(html, /<small>LLM used<\/small><strong>Yes<\/strong>/)
})

test('skipped SQL and retrieval statuses use neutral styling', () => {
  const contract = transparency({ stages: [
    stage({ stage_id: 'sql_query_execution', label: 'SQL query execution', method_category: 'SQL_QUERY', execution_status: 'SKIPPED' }),
    stage({ stage_id: 'retrieval', label: 'Evidence retrieval', method_category: 'RETRIEVAL', execution_status: 'SKIPPED' }),
  ] })
  const html = render(contract)
  assert.equal((html.match(/class="status neutral">Skipped<\/span>/g) ?? []).length, 2)
  assert.doesNotMatch(html, /class="status (?:warning|danger)">Skipped/)
  assert.match(html, /SQL capability is not SQL execution\./)
  assert.match(html, /Chat retrieval, when used, is separate from diagnosis retrieval\./)
})

test('fallback status is shown as a warning', () => {
  const html = render(transparency({ stages: [
    stage({ execution_status: 'FALLBACK' }),
    stage({ stage_id: 'llm_wording_selection', label: 'Optional LLM wording selection', method_category: 'LLM', execution_status: 'FALLBACK' }),
  ] }))
  assert.equal((html.match(/class="status warning">Fallback<\/span>/g) ?? []).length, 2)
  assert.match(html, /LLM not used/)
})

test('blocked status is visually distinct', () => {
  const html = render(transparency({ stages: [stage({ execution_status: 'BLOCKED' })] }))
  assert.match(html, /class="status danger">Blocked<\/span>/)
})

test('evidence references are inside a closed disclosure', () => {
  const html = render(transparency({ stages: [stage({ evidence_refs: ['movement_assessment'] })] }))
  assert.match(html, /<details class="processing-evidence"><summary>Evidence references \(1\)<\/summary>/)
  assert.doesNotMatch(html, /<details class="processing-evidence" open/)
  assert.match(html, /<li>movement_assessment<\/li>/)
})

test('null limitation and LLM role are omitted', () => {
  const html = render(transparency({ stages: [stage()] }))
  assert.doesNotMatch(html, /LLM role/)
  assert.doesNotMatch(html, /Limitation/)
})

test('historical stage metadata is rendered from the supplied saved contract', () => {
  const saved = transparency({
    stages: [stage({
      label: 'Saved historic step', method_category: 'RETRIEVAL', execution_status: 'UNAVAILABLE',
      quantitative_truth: true, purpose: 'Saved purpose from this run.', limitation: 'Saved historic limit.',
      llm_role: 'Saved historic role',
    })],
    summary: { quantitative_stages: 17, llm_used: false, sql_executed: false, retrieval_used: true, causal_method_used: false },
  })
  const html = render(saved)
  for (const savedValue of ['17', 'Saved historic step', 'Retrieval', 'Unavailable', 'Saved purpose from this run.', 'Saved historic limit.', 'Saved historic role']) {
    assert.ok(html.includes(savedValue), `expected saved value ${savedValue}`)
  }
})

test('overview compact mode has a collapsed stage disclosure and detail mode shows all stages', () => {
  const contract = transparency({ stages: [
    stage({ stage_id: 'movement_materiality', label: 'Movement and materiality detection' }),
    stage({ stage_id: 'driver_ranking', label: 'Driver association ranking' }),
  ] })
  const compact = render(contract, { compact: true })
  assert.match(compact, /<details class="processing-stage-disclosure"><summary>View all processing stages \(2\)<\/summary>/)
  assert.doesNotMatch(compact, /processing-stage-disclosure[^>]* open/)

  const full = render(contract)
  assert.doesNotMatch(full, /processing-stage-disclosure/)
  assert.equal((full.match(/class="processing-stage"/g) ?? []).length, 2)
})

test('missing legacy metadata shows the explicit historical message', () => {
  const html = render(undefined)
  assert.match(html, /Processing provenance was not recorded for this historical run\./)
  assert.doesNotMatch(html, /processing-stage/)
})

test('access-denied contract renders only its sanitized blocked stage', () => {
  const sanitized = stage({
    stage_id: 'scope_contract_validation', label: 'Scope and contract validation',
    method_category: 'BUSINESS_RULE', execution_status: 'BLOCKED',
    purpose: 'The requested diagnosis was blocked by access control.', evidence_refs: [],
  })
  const html = render(transparency({ stages: [sanitized] }))
  assert.equal((html.match(/class="processing-stage"/g) ?? []).length, 1)
  assert.match(html, /Scope and contract validation/)
  assert.doesNotMatch(html, /driver ranking|source evidence|restricted query/i)
})

test('component does not infer stages absent from the returned contract', () => {
  const html = render(transparency({ stages: [stage({ stage_id: 'backend_custom_stage', label: 'Backend custom stage' })] }))
  assert.equal((html.match(/class="processing-stage"/g) ?? []).length, 1)
  assert.match(html, /Backend custom stage/)
  assert.doesNotMatch(html, /Source loading and normalization|Driver association ranking/)
})

test('runtime panel shows deterministic zero usage and configured cache/runtime limits', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry()})
  assert.match(html, /Execution ID/)
  assert.match(html, /exec-test-123/)
  assert.match(html, /1\.00 s/)
  assert.match(html, /Cache hits/)
  assert.match(html, /Cache misses/)
  assert.match(html, /authorization/)
  assert.match(html, /source_preparation/)
  assert.match(html, /<td>0<\/td><td>0<\/td><td>0<\/td><td>\$0\.00<\/td>/)
  assert.match(html, /Pricing version/)
  assert.match(html, /Quantitative KPI calculations are performed by deterministic\/statistical engine stages\. LLMs are used only where explicitly shown\./)
})

test('null token usage and cost display Unavailable, never zero', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry({
    stages: [runtimeStage({processing_type: 'LLM', provider: 'groq', model: 'provider/model', model_calls: 1, input_tokens: null, output_tokens: null, estimated_cost_usd: null, usage_source: 'UNAVAILABLE'})],
    llm_summary: {provider: 'groq', model: 'provider/model', model_calls: 1, input_tokens: null, output_tokens: null, estimated_cost_usd: null, usage_source: 'UNAVAILABLE'},
  })})
  assert.match(html, /<td>Unavailable<\/td>/)
  assert.match(html, /<small>Input tokens<\/small><strong>Unavailable<\/strong>/)
  assert.match(html, /<small>Estimated USD cost<\/small><strong>Unavailable<\/strong>/)
  assert.match(html, /UNAVAILABLE/)
})

test('provider-reported usage and cost are displayed without false precision', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry({
    stages: [runtimeStage({stage: 'narrative_generation', processing_type: 'LLM', method: 'approved_wording_selection', latency_ms: 1234.5, provider: 'groq', model: 'provider/model', model_calls: 1, input_tokens: 820, output_tokens: 44, estimated_cost_usd: 0.000163, usage_source: 'PROVIDER_REPORTED'})],
    llm_summary: {provider: 'groq', model: 'provider/model', model_calls: 1, input_tokens: 820, output_tokens: 44, estimated_cost_usd: 0.000163, usage_source: 'PROVIDER_REPORTED'},
  })})
  assert.match(html, /groq/)
  assert.match(html, /provider\/model/)
  assert.match(html, /820/)
  assert.match(html, /44/)
  assert.match(html, /PROVIDER_REPORTED/)
  assert.match(html, /\$0\.0002/)
  assert.match(html, /1\.23 s/)
})

test('stage ordering and status are preserved from the backend response', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry({stages: [
    runtimeStage({stage: 'source_preparation', status: 'COMPLETED'}),
    runtimeStage({stage: 'reconciliation', status: 'SKIPPED'}),
    runtimeStage({stage: 'narrative_generation', processing_type: 'LLM', status: 'FALLBACK', model_calls: 1, input_tokens: null, output_tokens: null, estimated_cost_usd: null, usage_source: 'UNAVAILABLE'}),
  ]})})
  const sourceAt = html.indexOf('source_preparation')
  const reconAt = html.indexOf('reconciliation')
  const narrativeAt = html.indexOf('narrative_generation')
  assert.ok(sourceAt >= 0 && sourceAt < reconAt && reconAt < narrativeAt)
  assert.match(html, /SKIPPED/)
  assert.match(html, /FALLBACK/)
})

test('statistical, business-rule, and causal stage classifications render unchanged', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry({stages: [
    runtimeStage({stage: 'authorization', processing_type: 'BUSINESS_RULE'}),
    runtimeStage({stage: 'movement_detection', processing_type: 'STATISTICAL'}),
    runtimeStage({stage: 'causal_verification', processing_type: 'CAUSAL'}),
  ]})})
  assert.match(html, /authorization<\/td><td>BUSINESS_RULE/)
  assert.match(html, /movement_detection<\/td><td>STATISTICAL/)
  assert.match(html, /causal_verification<\/td><td>CAUSAL/)
})

test('provider/model column is hidden when stages have no model and missing telemetry remains compatible', () => {
  const deterministic = render(transparency(), {telemetry: runtimeTelemetry()})
  assert.doesNotMatch(deterministic, /Provider \/ model/)
  const legacy = render(transparency())
  assert.match(legacy, /Runtime telemetry is unavailable for this historical run\./)
  assert.doesNotMatch(legacy, /runtime-telemetry-table/)
})

test('telemetry renderer ignores unapproved sensitive or raw detail fields', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry({
    prompt: 'SECRET_PROMPT_SENTINEL', sql: 'SELECT SECRET_SQL_SENTINEL',
    credential: 'SECRET_CREDENTIAL_SENTINEL', path: '/private/SECRET_PATH_SENTINEL',
    retrieved_text: 'SECRET_RETRIEVED_SENTINEL',
    stages: [runtimeStage({details: {exception: 'SECRET_EXCEPTION_SENTINEL', prompt: 'SECRET_PROMPT_SENTINEL'}})],
  })})
  for (const secret of ['SECRET_PROMPT_SENTINEL', 'SECRET_SQL_SENTINEL', 'SECRET_CREDENTIAL_SENTINEL', 'SECRET_PATH_SENTINEL', 'SECRET_RETRIEVED_SENTINEL', 'SECRET_EXCEPTION_SENTINEL']) {
    assert.doesNotMatch(html, new RegExp(secret))
  }
})

test('access-denied run suppresses operational telemetry', () => {
  const html = render(transparency(), {telemetry: runtimeTelemetry(), suppressRuntimeTelemetry: true})
  assert.doesNotMatch(html, /Operational telemetry/)
  assert.doesNotMatch(html, /exec-test-123/)
})

test('overview and investigation detail both use the shared view in the expected positions', () => {
  const overview = fs.readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8')
  const detail = fs.readFileSync(new URL('../app/performance/[runId]/page.tsx', import.meta.url), 'utf8')
  assert.match(overview, /<ProcessingTransparencyView transparency=\{result\.processing_transparency\} compact \/>/)
  assert.ok(overview.indexOf('<ProcessingTransparencyView') > overview.indexOf('<ActionWorkspace'))
  assert.match(detail, /<ProcessingTransparencyView[\s\S]*?transparency=\{run\.processing_transparency\}[\s\S]*?telemetry=\{run\.telemetry\}[\s\S]*?suppressRuntimeTelemetry=\{run\.verdict === 'ACCESS_DENIED'\}/)
  assert.ok(detail.indexOf('<ConfidenceWorkspace') < detail.indexOf('<ProcessingTransparencyView'))
  assert.ok(detail.indexOf('<ProcessingTransparencyView') < detail.indexOf('Evidence-bound narrative'))
})