import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { waterfallScale } from '../lib/driver-waterfall.ts'
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
const DriverWaterfall = require('../components/driver-waterfall.tsx').default
const DriverAnalysisOverview = require('../components/driver-analysis-overview.tsx').default

function renderOverview(isMaterial, confidence) {
  return renderToStaticMarkup(React.createElement(DriverAnalysisOverview, {
    analysis: {
      ranked_drivers: [{ driver_id: 'pos', rank: 1, contribution: -10, direction: 'POSITIVE', expected_direction: 'POSITIVE' }],
      excluded_drivers: [], residual: 0,
      association_diagnostics: { ranked_drivers: [{ driver_id: 'pos', raw_correlation: -0.67 }] },
    },
    profile: { attribution_confidence: [{ driver_id: 'pos', attribution_confidence: confidence }] },
    expected: 100, actual: 90, isMaterial, unit: 'orders',
  }))
}

test('zero-based Expected and Actual bars render at the 2920/3793 height ratio', () => {
  const model = waterfallScale(3793, 2920, [{ label: 'Driver', value: -870 }], -3)
  assert.equal(model.min, 0)
  assert.equal(model.bars[0].start, 0)
  assert.equal(model.bars.at(-1).start, 0)
  const html = renderToStaticMarkup(React.createElement(DriverWaterfall, {
    expected: 3793, actual: 2920, drivers: [{ label: 'Driver', value: -870 }], residual: -3, unit: 'orders',
  }))
  const heights = [...html.matchAll(/<rect[^>]*height="([\d.]+)"[^>]*class="waterfall-bar total"/g)].map(match => Number(match[1]))
  assert.equal(heights.length, 2)
  assert.ok(Math.abs(heights[1] / heights[0] - 2920 / 3793) < 0.001)
  assert.match(html, /Step detail \(each step has its own zoomed vertical scale\)/)
})

test('legacy correlation is only in row details with method explanation', () => {
  const html = renderOverview(true, 0.4)
  assert.doesNotMatch(html, /<th>Correlation<\/th>/)
  assert.match(html, /<summary>Legacy association \(different method\) ⓘ<\/summary>/)
  assert.match(html, /Lagged first differences; this can disagree with the attribution regression direction/)
  assert.match(html, /Legacy association: -0.67/)
  assert.match(html, /observed POSITIVE/)
  assert.equal(driverRows({ ranked_drivers: [{ driver_id: 'pos', rank: 1, contribution: -10 }] }, {
    attribution_confidence: [{ driver_id: 'pos', attribution_confidence: 0.35 }],
  }).main.driver.driver_id, 'pos')
})

test('banner distinguishes non-material exploration from material low-confidence movement', () => {
  const exploratory = renderOverview(false, 0.8)
  assert.match(exploratory, /This change is within the normal range\. Drivers are shown for exploration only/)
  assert.doesNotMatch(exploratory, /Main cause:|No confident cause/)
  const material = renderOverview(true, 0.34)
  assert.match(material, /No confident cause/)
  assert.doesNotMatch(material, /within the normal range/)
})
