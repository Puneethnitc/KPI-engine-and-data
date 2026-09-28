import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

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
// The component imports its stylesheet; CSS has no meaning in these unit tests.
Module._extensions['.css'] = () => {}

const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const flow = require('../components/kpi-flow.tsx')
const KpiFlow = flow.default

function node(kpi_id, percent_change, material, consequence_of = null) {
  return { kpi_id, actual: 1, expected: 1, percent_change, material, status: material ? (percent_change < 0 ? 'down' : 'up') : 'normal', missing: false, consequence_of }
}

// Mirrors the screenshot case: revenue up 14.4%, nothing individually material,
// traffic has the largest share. The engine currently flags every moved node as a consequence.
const quietStory = {
  nodes: [
    node('traffic_total', 8.6, false), node('conversion_rate', 2.2, false, 'traffic'),
    node('orders', 9.9, false, 'traffic'), node('units_sold', 9.9, false, 'traffic'),
    node('net_sales_revenue', 14.4, true, 'traffic'),
  ],
  edges: [{ stage: 'traffic', from: 'traffic_total', to: 'net_sales_revenue', contribution_inr: 232, contribution_pct: 61.4, factor_percent_change: 8.6 },
          { stage: 'units', from: 'units_sold', to: 'net_sales_revenue', contribution_inr: 0.2, contribution_pct: 0, factor_percent_change: 0 }],
  root_stage: 'traffic', missing_stages: [], revenue_delta: 377, cause_chains: [], act_first: [],
  headline_facts: [
    { kind: 'revenue', delta: 377, percent_change: 14.4 }, { kind: 'root_stage', stage: 'traffic' },
    { kind: 'normal_stage', stage: 'traffic' }, { kind: 'normal_stage', stage: 'conversion' }, { kind: 'normal_stage', stage: 'units' },
  ],
}

test('headline never calls the largest-share stage "not material" in a separate contradictory sentence', () => {
  const text = flow.headline(quietStory)
  assert.match(text, /^Revenue rose ₹377 \(\+14\.4%\)\./)
  assert.match(text, /largest share came from traffic, although no stage moved enough on its own to be material/)
  assert.doesNotMatch(text, /traffic and conversion and units/)
})

test('headline lists quiet stages with natural grammar when the root is material', () => {
  const story = { ...quietStory, nodes: quietStory.nodes.map(item => item.kpi_id === 'traffic_total' ? { ...item, material: true, status: 'up' } : item) }
  assert.match(flow.headline(story), /Conversion and units were within the normal range\./)
})

test('non-material KPIs are never labelled as a result of the root', () => {
  const html = renderToStaticMarkup(React.createElement(KpiFlow, { story: quietStory, onSelect: () => {} }))
  assert.match(html, /Largest share/)
  assert.doesNotMatch(html, /Result of traffic<\/span><\/button>[\s\S]*Conversion/) // conversion is not material
  assert.equal((html.match(/Result of traffic/g) ?? []).length, 1) // only revenue (material)
  assert.match(html, /no effect/) // near-zero arrow is labelled, not "+₹0 · 0.0%"
})

test('older runs without a story render a neutral message', () => {
  const html = renderToStaticMarkup(React.createElement(KpiFlow, { story: null, onSelect: () => {} }))
  assert.match(html, /Not available for this older run/)
})
