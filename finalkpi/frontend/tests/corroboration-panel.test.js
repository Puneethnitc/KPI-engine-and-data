import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { createRequire } from 'node:module'
import {
  corroborationSourceTypeLabel,
  corroborationStanceLabel,
  corroborationStatusLabel,
  corroborationViewModel,
} from '../lib/driver-analysis.ts'

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
const CorroborationPanel = require('../components/corroboration-panel.tsx').default

function document(overrides = {}) {
  return {
    doc_id: 'TCK-1001',
    date: '2023-07-24',
    available_at: '2023-07-24',
    source_type: 'support_ticket',
    region: 'North',
    category: 'Electronics',
    stance: 'supports',
    matched_by: 'driver_tag',
    matched_terms: ['marketing_spend'],
    snippet: 'Regional marketing lead flagged that the Electronics paid-search budget for North was cut.',
    ...overrides,
  }
}

function corroboration(overrides = {}) {
  return {
    status: 'CORROBORATED',
    documents: [document()],
    document_count: 1,
    match_basis: 'driver_tag',
    supporting_documents: ['TCK-1001'],
    refuting_documents: [],
    ...overrides,
  }
}

test('status and stance labels read as plain language', () => {
  assert.equal(corroborationStatusLabel('CORROBORATED'), 'Documents support this driver')
  assert.equal(corroborationStatusLabel('CONTRADICTED'), 'Documents contradict this driver')
  assert.equal(corroborationStatusLabel('RETRIEVAL_FAILED'), 'Evidence corpus unavailable')
  assert.equal(corroborationStanceLabel('supports'), 'Supports')
  assert.equal(corroborationStanceLabel('refutes'), 'Refutes')
  assert.equal(corroborationSourceTypeLabel('support_ticket'), 'Support ticket')
  assert.equal(corroborationSourceTypeLabel('promo_calendar'), 'Promotion calendar')
})

test('a supporting document does not present itself as causal proof', () => {
  const model = corroborationViewModel(corroboration())
  assert.equal(model.assessed, true)
  assert.equal(model.tone, 'good')
  assert.equal(model.supporting, 1)
  assert.equal(model.refuting, 0)
  assert.match(model.boundary, /do not establish that it caused the change/)
})

test('a run with no corroboration block is not assessed, not empty evidence', () => {
  const model = corroborationViewModel(null)
  assert.equal(model.assessed, false)
  assert.equal(model.statusLabel, 'Not assessed in this run')
  assert.match(model.boundary, /predates evidence corroboration/)
  assert.equal(renderToStaticMarkup(React.createElement(CorroborationPanel, { corroboration: null })), '')
})

test('a retrieval failure is distinguished from an absence of evidence', () => {
  const model = corroborationViewModel(corroboration({ status: 'RETRIEVAL_FAILED', documents: [], document_count: 0 }))
  assert.equal(model.tone, 'limited')
  assert.match(model.boundary, /retrieval failure, not an absence of evidence/)
})

test('contradicting evidence is counted and styled as a warning', () => {
  const model = corroborationViewModel(corroboration({
    status: 'CONTRADICTED',
    documents: [document({ doc_id: 'PROMO-5001', stance: 'refutes' })],
    document_count: 1,
    refuting_documents: ['PROMO-5001'],
  }))
  assert.equal(model.tone, 'warning')
  assert.equal(model.refuting, 1)
  assert.equal(model.supporting, 0)
})

test('panel renders each document with type, date and stance', () => {
  const markup = renderToStaticMarkup(React.createElement(CorroborationPanel, {
    corroboration: corroboration({
      documents: [
        document({ doc_id: 'TCK-1001' }),
        document({ doc_id: 'PROMO-5001', stance: 'refutes', source_type: 'promo_calendar', matched_by: 'keyword' }),
      ],
      document_count: 2,
    }),
  }))
  assert.match(markup, /TCK-1001/)
  assert.match(markup, /PROMO-5001/)
  assert.match(markup, /Support ticket/)
  assert.match(markup, /Promotion calendar/)
  assert.match(markup, /2023-07-24/)
  assert.match(markup, /Supports/)
  assert.match(markup, /Refutes/)
  assert.match(markup, /North\/Electronics/)
  assert.match(markup, /matched by driver tag/)
  assert.match(markup, /matched by keyword/)
})

test('panel states the filter and stance rules it applied', () => {
  const markup = renderToStaticMarkup(React.createElement(CorroborationPanel, { corroboration: corroboration() }))
  assert.match(markup, /21 days/)
  assert.match(markup, /entitlements/)
  assert.match(markup, /stance, not its presence/)
})

test('a driver with no documents says so instead of showing an empty list', () => {
  const markup = renderToStaticMarkup(React.createElement(CorroborationPanel, {
    corroboration: corroboration({ status: 'NONE', documents: [], document_count: 0 }),
  }))
  assert.match(markup, /No documents were returned/)
  assert.match(markup, /No in-scope, entitled, published document/)
})

test('the panel is rendered under each ranked driver in the driver workspace', () => {
  const source = fs.readFileSync(new URL('../components/driver-analysis-workspace.tsx', import.meta.url), 'utf8')
  assert.match(source, /import CorroborationPanel from '\.\/corroboration-panel'/)
  assert.match(source, /<CorroborationPanel corroboration=\{driver\.corroboration\} \/>/)
})

test('the shared RankedDriver type carries the corroboration block', () => {
  const source = fs.readFileSync(new URL('../lib/driver-analysis.ts', import.meta.url), 'utf8')
  assert.match(source, /corroboration\?: Corroboration \| null/)
  assert.match(source, /export type Corroboration = \{/)
  assert.match(source, /stance: 'supports' \| 'refutes' \| 'neutral'/)
})
