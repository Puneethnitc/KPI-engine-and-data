import assert from 'node:assert/strict'
import test from 'node:test'
import { createRequire } from 'node:module'
import { confidenceWorkspaceModel } from '../lib/confidence-profile.ts'
import { attributionConfidenceBars } from '../lib/confidence-profile.ts'
import { driverAnalysisViewModel, corroborationViewModel } from '../lib/driver-analysis.ts'
import { actionImpactLabel } from '../lib/action-workspace.ts'

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
const DriverAnalysisWorkspace = require('../components/driver-analysis-workspace.tsx').default
const CorroborationPanel = require('../components/corroboration-panel.tsx').default
const ActionWorkspace = require('../components/action-workspace.tsx').default
const FunnelBridgeCard = require('../components/funnel-bridge.tsx').default

test('old diagnosis fields build every available view without an exception', () => {
  const old = {
    confidence_profile: {
      overall: { status: 'MODERATE', reasons: [], blocking_dimensions: [], movement_conclusion: 'HIGH', explanation_conclusion: 'MODERATE' },
      movement: { status: 'HIGH', score: null },
      driver: { status: 'MODERATE', score: null },
    },
    driver_analysis: { status: 'ASSESSED', method: 'LEGACY', target_kpi: 'orders', ranked_drivers: [], excluded_drivers: [], limitations: [] },
    actions: [{ kind: 'NEXT_CHECK', recommendation: 'Review the event timeline.', owner: 'analyst' }],
  }
  const confidence = confidenceWorkspaceModel(old.confidence_profile, 'CFO')
  assert.deepEqual(confidence.dimensions.map(item => item.key), ['movement', 'attribution'])
  assert.deepEqual(attributionConfidenceBars(old.confidence_profile), [])
  assert.equal(driverAnalysisViewModel(old.driver_analysis, 'CFO').ranked.length, 0)
  assert.equal(corroborationViewModel(undefined).assessed, false)
  assert.match(actionImpactLabel(old.actions[0]), /older run/)
  assert.match(renderToStaticMarkup(React.createElement(DriverAnalysisWorkspace, { analysis: old.driver_analysis, persona: 'CFO' })), /Driver analysis evidence/)
  assert.match(renderToStaticMarkup(React.createElement(CorroborationPanel, {})), /older run/)
  assert.match(renderToStaticMarkup(React.createElement(ActionWorkspace, { actions: old.actions, persona: 'CFO' })), /older run/)
  assert.match(renderToStaticMarkup(React.createElement(FunnelBridgeCard, { unit: 'USD' })), /older run/)
})
