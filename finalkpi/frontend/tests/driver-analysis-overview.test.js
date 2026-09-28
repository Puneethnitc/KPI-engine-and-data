import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { driverRows } from '../lib/driver-analysis-overview.ts'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const source = require('node:fs').readFileSync(filename, 'utf8')
    const compiled = ts.transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    }).outputText
    module._compile(compiled, filename)
  }
}
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const DriverAnalysisOverview = require('../components/driver-analysis-overview.tsx').default

test('highest Attribution Confidence determines the main cause and row order', () => {
  const analysis = { ranked_drivers: [
    { driver_id: 'first', rank: 1, contribution: -4, offsetting: false },
    { driver_id: 'second', rank: 2, contribution: -8, offsetting: false },
    { driver_id: 'offset', rank: 3, contribution: 2, offsetting: true },
  ], excluded_drivers: [{ driver_id: 'unused', reason_code: 'DID_NOT_MOVE' }] }
  const profile = { attribution_confidence: [
    { driver_id: 'first', attribution_confidence: 0.63 },
    { driver_id: 'second', attribution_confidence: 0.88 },
    { driver_id: 'offset', attribution_confidence: 0.4 },
  ] }
  const model = driverRows(analysis, profile)
  assert.equal(model.main.driver.driver_id, 'second')
  assert.deepEqual(model.rows.map(row => row.driver.driver_id), ['second', 'first', 'offset', 'unused'])
})

test('verified banner uses saved confidence, test result and document IDs', () => {
  const html = renderToStaticMarkup(React.createElement(DriverAnalysisOverview, {
    analysis: { ranked_drivers: [{ driver_id: 'stock_availability', display_name: 'Stock availability', rank: 1, contribution: -5, driver_change: -0.85, driver_change_z: -4, driver_unit: 'share_in_stock', corroboration: { status: 'CORROBORATED', documents: [{ doc_id: 'TCK-3001' }], supporting_documents: ['TCK-3001'] } }], excluded_drivers: [], residual: 0 },
    profile: { attribution_status: 'CONFIDENT', attribution_confidence: [{ driver_id: 'stock_availability', attribution_confidence: 0.998, label: 'Very likely a cause', evidence: [], caps_applied: [] }] },
    causalTest: { driver_id: 'stock_availability', verdict: 'SUPPORTED_CONDITIONAL', method: 'log_outcome_did_hac_placebo', did_effect: -1.02, controls_used: [{}, {}, {}, {}] },
    expected: 100, actual: 95, unit: 'orders',
  }))
  assert.match(html, /Main cause: Stock availability/)
  assert.match(html, /99.8% Very likely a cause/)
  assert.match(html, /Verified cause/)
  assert.match(html, /4 comparison slices/)
  assert.match(html, /TCK-3001/)
})

test('driver analysis caps displayed attribution confidence at 99.9%', () => {
  const html = renderToStaticMarkup(React.createElement(DriverAnalysisOverview, {
    analysis: { ranked_drivers: [{ driver_id: 'stock', contribution: 1 }], excluded_drivers: [] },
    profile: { attribution_confidence: [{ driver_id: 'stock', attribution_confidence: 1, label: 'Very likely a cause' }] },
    expected: 10, actual: 11, unit: 'orders',
  }))
  assert.match(html, /99.9% Very likely a cause/)
  assert.doesNotMatch(html, /100% Very likely a cause/)
})

test('old and ambiguous runs render neutral states without throwing', () => {
  const old = renderToStaticMarkup(React.createElement(DriverAnalysisOverview, { unit: 'orders' }))
  assert.match(old, /older run/)
  const ambiguous = renderToStaticMarkup(React.createElement(DriverAnalysisOverview, {
    analysis: { ranked_drivers: [{ driver_id: 'x', rank: 1, contribution: 0.01 }], excluded_drivers: [] },
    profile: { attribution_status: 'AMBIGUOUS' }, unit: 'orders',
  }))
  assert.match(ambiguous, /No confident cause/)
  assert.match(ambiguous, /verify first/)
})
