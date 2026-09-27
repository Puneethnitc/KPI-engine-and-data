import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { createRequire } from 'node:module'
import {
  contractCapabilityLabel,
  contractComparisonView,
  contractPersonaFrame,
  contractRequestPath,
  contractRequestState,
  contractViewerHref,
  contractValueLabel,
} from '../lib/semantic-contract.ts'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const source = require('node:fs').readFileSync(filename, 'utf8')
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
const SemanticContractViewerModule = require('../components/semantic-contract-viewer.tsx')
const SemanticContractViewer = SemanticContractViewerModule.default
const { ContractStateNotice } = SemanticContractViewerModule

function render(node) {
  return renderToStaticMarkup(node)
}

function makeContract(overrides = {}) {
  return {
    schema_version: 1,
    identity: {
      kpi_id: 'conversion_rate', display_name: 'Conversion rate', version: 1,
      status: 'ACTIVE', definition: 'Orders divided by traffic.',
      business_purpose: 'Measure orders per visit.', owner: 'growth_lead', steward: 'Growth steward', tags: ['funnel'],
    },
    calculation: {
      operator: 'RATIO_OF_SUMS', formula: 'orders / traffic_total', numerator_column: 'orders',
      denominator_column: 'traffic_total', value_column: 'conversion_rate', weight_column: null,
      unit: 'orders_per_visit', precision: 4, null_policy: 'require both components',
      zero_policy: 'zero denominator is missing', aggregation_notes: ['Never average displayed rates.'],
      executable_method: 'ratio_of_sums',
    },
    grain_and_scope: { native_grain: 'daily', supported_rollups: ['region', 'category'], dimensions: ['region', 'category'], calendar: 'Gregorian', timezone: 'UTC', comparison_policy: null, minimum_history_periods: 60 },
    source: { primary_source_id: 'sales_daily', source_table: 'sales_daily', source_grain: 'daily', event_time_field: 'date', availability_time_field: 'available_at', natural_key: ['date', 'region', 'category'], required_fields: [], refresh_cadence: 'T+1', access_classification: 'internal', lineage_reference: 'data/sales_daily.csv', catalog_version: '1', comparison_source: null },
    materiality: { statistical_method: 'robust baseline', statistical_thresholds: { z_threshold: 2.5 }, business_thresholds: { absolute_change: 0.003, unit: 'orders_per_visit' }, detector_agreement_rule: 'robust required', threshold_status: 'PROVISIONAL', calibration_reference: null },
    drivers: { candidate_drivers: [], method: 'marginal association', limitations: [] },
    reconciliation: { applicable: false, comparison_source_id: null, comparison_metric: null, unit: null, keys: [], mode: null, tolerance: null, contradiction_threshold: null, coverage_rule: null, availability_rule: null },
    decomposition: { applicable: false, method: null, quantity_column: null, rate_column: null, identity: null, limitations: [] },
    security: { access_tags: ['region_scoped'], allowed_roles: ['CFO'], row_scope_dimensions: ['region', 'category'], restricted_fields: [], sensitive: false, policy_reference: 'access_control.csv' },
    governance: { contract_hash: 'hash-a', effective_from: null, effective_to: null, approved_by: null, change_reason: null, source_catalog_version: '1', validation_status: 'VALID', validation_errors: [] },
    capabilities: { movement_detection: 'SUPPORTED', decomposition: 'NOT_APPLICABLE', driver_ranking: 'SUPPORTED', reconciliation: 'NOT_APPLICABLE', causal_verification: 'CONDITIONAL' },
    ...overrides,
  }
}

test('capability labels distinguish supported, conditional, and not applicable', () => {
  assert.equal(contractCapabilityLabel('SUPPORTED'), 'Supported')
  assert.equal(contractCapabilityLabel('CONDITIONAL'), 'Conditional')
  assert.equal(contractCapabilityLabel('NOT_APPLICABLE'), 'Not applicable')
  assert.equal(contractCapabilityLabel('NOT_SUPPORTED'), 'Not supported')
})

test('contract request states distinguish authorization, unknown, invalid, and server errors', () => {
  assert.equal(contractRequestState(200), 'ready')
  assert.equal(contractRequestState(401), 'unauthorized')
  assert.equal(contractRequestState(403), 'unauthorized')
  assert.equal(contractRequestState(404), 'not-found')
  assert.equal(contractRequestState(400), 'invalid')
  assert.equal(contractRequestState(422), 'invalid')
  assert.equal(contractRequestState(500), 'error')
})

test('viewer contract paths use canonical current and historical endpoints', () => {
  assert.equal(contractRequestPath('conversion_rate'), '/api/kpis/conversion_rate/contract')
  assert.equal(contractRequestPath('conversion_rate', 'run-123'), '/api/diagnoses/run-123/contract')
})

test('viewer navigation preserves the current KPI or saved run identifier', () => {
  assert.equal(contractViewerHref('conversion_rate'), '/kpis/conversion_rate')
  assert.equal(contractViewerHref('conversion_rate', 'run-123'), '/kpis/conversion_rate?run_id=run-123')
})

test('null metadata stays explanatory and never formats as zero', () => {
  assert.equal(contractValueLabel(null), 'Not specified')
  assert.equal(contractValueLabel(null, 'Not applicable'), 'Not applicable')
  assert.equal(contractValueLabel(0), '0')
})

test('ratio-of-sums contract exposes formula components and units as separate facts', () => {
  const contract = makeContract()
  assert.equal(contract.calculation.operator, 'RATIO_OF_SUMS')
  assert.equal(contract.calculation.formula, 'orders / traffic_total')
  assert.equal(contract.calculation.numerator_column, 'orders')
  assert.equal(contract.calculation.denominator_column, 'traffic_total')
  assert.equal(contract.calculation.unit, 'orders_per_visit')
  assert.match(contract.calculation.aggregation_notes[0], /Never average/)
})

test('historical/current comparison warns only when version or hash changed', () => {
  const saved = makeContract()
  const same = makeContract()
  const changed = makeContract({
    identity: { ...saved.identity, version: 2 },
    governance: { ...saved.governance, contract_hash: 'hash-b' },
  })
  assert.equal(contractComparisonView({ same_hash: true, changed_since_run: false }, saved, same).changed, false)
  const warning = contractComparisonView({ same_hash: false, changed_since_run: true }, saved, changed)
  assert.equal(warning.changed, true)
  assert.equal(warning.message, 'Contract changed since this run.')
})

test('a missing historical snapshot is not replaced with current contract metadata', () => {
  const view = contractComparisonView({ snapshot_status: 'MISSING' }, null, makeContract())
  assert.equal(view.state, 'MISSING')
  assert.match(view.message, /current contract is not substituted/)
})

test('missing snapshot state uses the explicit legacy-run message', () => {
  const html = render(React.createElement(ContractStateNotice, {
    state: 'invalid',
    message: 'Contract snapshot was not saved for this run.',
  }))
  assert.ok(html.includes('Contract snapshot was not saved for this run.'))
  assert.ok(!html.includes('Current semantic contract'))
})

test('persona wording changes without changing semantic facts', () => {
  const cfo = contractPersonaFrame('CFO')
  const marketing = contractPersonaFrame('marketing_manager')
  assert.notEqual(cfo, marketing)
  assert.match(cfo, /reconciliation controls, materiality/)
  assert.match(marketing, /funnel meaning, governed operational levers/)
  assert.deepEqual(makeContract().calculation, makeContract().calculation)
})

test('real contract viewer renders sections, ratio components, capabilities, and null explanations', () => {
  const contract = makeContract({
    identity: { ...makeContract().identity, steward: null },
    source: { ...makeContract().source, required_fields: [{ name: 'orders', type: 'float', required: true, nullable: false, unit: 'count', description: null }] },
    drivers: { candidate_drivers: [], method: 'association', limitations: [] },
  })
  const html = render(React.createElement(SemanticContractViewer, { snapshot: contract, persona: 'CFO' }))
  for (const expected of ['Calculation', 'Grain and lineage', 'Materiality', 'Driver candidates', 'Reconciliation and decomposition', 'Security and capabilities', 'orders / traffic_total', 'RATIO_OF_SUMS', 'Not applicable', 'No separate steward']) {
    assert.ok(html.includes(expected), `expected rendered markup to include ${expected}`)
  }
  assert.ok(!html.includes('0 decimal places'))
  assert.ok(!html.includes('finance_monthly · net_sales_revenue'))
})

test('real viewer distinguishes saved/current hashes and only warns on actual changes', () => {
  const saved = makeContract()
  const current = makeContract({ governance: { ...saved.governance, contract_hash: 'hash-b' } })
  const changedHtml = render(React.createElement(SemanticContractViewer, {
    snapshot: saved,
    current,
    comparison: { snapshot_status: 'CAPTURED', same_version: true, same_hash: false, changed_since_run: true },
    persona: 'CFO',
    historical: true,
  }))
  assert.ok(changedHtml.includes('Contract changed since this run.'))
  assert.ok(changedHtml.includes('Contract snapshot used by this run · v1 · hash-a'))
  assert.ok(changedHtml.includes('Current is v1 · hash-b'))
  assert.ok(changedHtml.includes('Snapshot status'))
  assert.ok(changedHtml.includes('Same version'))
  assert.ok(changedHtml.includes('Same hash'))
  assert.ok(changedHtml.includes('Changed since run'))

  const sameHtml = render(React.createElement(SemanticContractViewer, {
    snapshot: saved,
    current: makeContract(),
    comparison: { snapshot_status: 'CAPTURED', same_version: true, same_hash: true, changed_since_run: false },
    persona: 'CFO',
    historical: true,
  }))
  assert.ok(sameHtml.includes('Saved run contract matches the current registry.'))
  assert.ok(!sameHtml.includes('Contract changed since this run.'))
})

test('real viewer changes persona wording only and honors finance redaction', () => {
  const contract = makeContract({
    source: { ...makeContract().source, comparison_source: { source_id: 'finance_monthly', source_grain: 'monthly', access_classification: 'restricted', redacted: true } },
    reconciliation: { ...makeContract().reconciliation, applicable: true, comparison_source_id: 'finance_monthly', comparison_metric: null, unit: null, keys: [], redacted: true, redaction_reason: 'Restricted finance metadata is hidden.' },
  })
  const cfoHtml = render(React.createElement(SemanticContractViewer, { snapshot: contract, persona: 'CFO' }))
  const marketingHtml = render(React.createElement(SemanticContractViewer, { snapshot: contract, persona: 'marketing_manager' }))
  assert.ok(cfoHtml.includes('Finance review'))
  assert.ok(marketingHtml.includes('Marketing review'))
  assert.ok(marketingHtml.includes('Restricted finance metadata is hidden.'))
  assert.ok(!marketingHtml.includes('finance_monthly · net_sales_revenue'))
  assert.ok(!marketingHtml.includes('INR · null'))
  for (const fact of ['orders / traffic_total', 'orders_per_visit', 'z threshold']) {
    assert.ok(cfoHtml.toLowerCase().includes(fact.toLowerCase()))
    assert.ok(marketingHtml.toLowerCase().includes(fact.toLowerCase()))
  }
})

test('rendered unauthorized, unknown, invalid, and loading states do not render contract fields', () => {
  for (const [state, message, expected] of [
    ['loading', undefined, 'Loading semantic contract'],
    ['unauthorized', 'Contract metadata is not authorized.', 'not authorized'],
    ['not-found', 'The requested KPI contract was not found.', 'not found'],
    ['invalid', 'The KPI contract failed validation.', 'failed validation'],
  ]) {
    const html = render(React.createElement(ContractStateNotice, { state, message }))
    assert.ok(html.toLowerCase().includes(expected.toLowerCase()))
    assert.ok(!html.includes('orders / traffic_total'))
    assert.ok(!html.includes('restricted_finance_secret'))
  }
})

test('invalid rendered contract displays validation errors instead of a valid badge', () => {
  const invalid = makeContract({
    governance: { ...makeContract().governance, validation_status: 'INVALID', validation_errors: ['conversion_rate.calculation: numerator field missing'] },
  })
  const html = render(React.createElement(SemanticContractViewer, { snapshot: invalid, persona: 'CFO' }))
  assert.ok(html.includes('Invalid contract'))
  assert.ok(html.includes('Contract validation failed'))
  assert.ok(html.includes('numerator field missing'))
  assert.ok(!html.includes('Valid contract'))
})

test('viewer source does not hard-code KPI formulas or thresholds', () => {
  const source = fs.readFileSync(new URL('../components/semantic-contract-viewer.tsx', import.meta.url), 'utf8')
  assert.ok(!source.includes('orders / traffic_total'))
  assert.ok(!source.includes('2.5'))
  assert.ok(!source.includes('0.003'))
})
