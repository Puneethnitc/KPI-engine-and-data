import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { createRequire } from 'node:module'
import {
  actionBoundary,
  actionCountLabel,
  actionImpactLabel,
  actionPersonaFrame,
  isLegacyAction,
  safeEvidencePath,
} from '../lib/action-workspace.ts'

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
const ActionWorkspace = require('../components/action-workspace.tsx').default

const action = {
  action_id: 'ACTION_stock_availability_NEXT_CHECK', kind: 'NEXT_CHECK', status: 'AWAITING_REVIEW',
  driver_id: 'stock_availability', driver_rank: 1, driver_relationship: 'ASSOCIATION', controllability: 'CONTROLLABLE',
  lever: 'Availability', recommendation: 'Check inventory and lost-unit records for the affected slice.',
  owner: 'operations_lead', owner_source: 'contract.candidate_drivers.owner', decision_right: 'Operations capacity approval', approval_required: false,
  expected_impact: null, expected_impact_unit: null, impact_method: 'NOT_ESTIMATED',
  impact_explanation: 'Impact is not estimated: no validated deterministic method is configured.',
  evidence_status: 'HIGH', confidence_status: 'LOW',
  evidence_references: [{ evidence_type: 'ranked_driver', path: 'driver_analysis.ranked_drivers', driver_id: 'stock_availability', driver_rank: 1, source_id: 'sales_daily', period: '2024-01-31', method: 'daily_date_grouping' }],
  constraints: ['Association is diagnostic only.'], monitoring_plan: 'Monitor stock_availability and the declared KPI at the governed native grain.',
  success_metric: 'Verify the stock_availability signal before rollout.', review_window: 'Review after the next governed observation window.',
  stop_conditions: ['Stop if coverage falls below minimum.'], limitations: ['No causal estimate.'], evidence_paths: ['driver_analysis.ranked_drivers'],
}

function render(node) { return renderToStaticMarkup(node) }

 test('null expected impact renders an explanation and never zero', () => {
  assert.equal(actionImpactLabel(action), action.impact_explanation)
  const html = render(React.createElement(ActionWorkspace, { actions: [action], persona: 'marketing_manager', verdict: 'MATERIAL_CAUSE_UNVERIFIED' }))
  assert.ok(html.includes('Impact is not estimated'))
  assert.ok(!html.includes('Expected impact: 0'))
})

test('supplied expected impact renders with its unit', () => {
  assert.equal(actionImpactLabel({ expected_impact: 12, expected_impact_unit: 'units' }), '12 units')
})

test('next checks show the association boundary', () => {
  assert.equal(actionBoundary(action), 'Association only—not contribution or causation.')
  assert.ok(render(React.createElement(ActionWorkspace, { actions: [action], persona: 'CFO' })).includes('Association only'))
})

test('action proposals show approval and preserve exact recommendation text', () => {
  const proposal = { ...action, kind: 'ACTION_PROPOSAL', status: 'AWAITING_APPROVAL', approval_required: true, driver_relationship: 'CONDITIONAL_CAUSAL_SUPPORT', recommendation: 'Assess a replenishment response and operational capacity.' }
  const html = render(React.createElement(ActionWorkspace, { actions: [proposal], persona: 'CFO' }))
  assert.ok(html.includes('Action proposal'))
  assert.ok(html.includes('Approval required'))
  assert.ok(html.includes('Yes'))
  assert.ok(html.includes(proposal.recommendation))
})

test('ownership, monitoring, constraints, limitations and stop conditions render', () => {
  const html = render(React.createElement(ActionWorkspace, { actions: [action], persona: 'marketing_manager' }))
  for (const expected of ['Operations lead', 'contract.candidate_drivers.owner', 'Operations capacity approval', 'Monitoring plan', 'Success metric', 'Review window', 'Stop conditions', 'Association is diagnostic only.']) assert.ok(html.includes(expected), expected)
})

test('structured evidence references are safe and absolute paths are hidden', () => {
  assert.equal(safeEvidencePath('/srv/private/source.csv'), 'Protected evidence reference')
  const html = render(React.createElement(ActionWorkspace, { actions: [{ ...action, evidence_references: [{ path: '/srv/private/source.csv', evidence_type: 'ranked_driver' }] }], persona: 'CFO' }))
  assert.ok(html.includes('Protected evidence reference'))
  assert.ok(!html.includes('/srv/private/source.csv'))
})

test('contradictory evidence blocks the workspace and sparse results abstain', () => {
  const blocked = render(React.createElement(ActionWorkspace, { actions: [], persona: 'CFO', verdict: 'CONTRADICTED' }))
  assert.ok(blocked.includes('Actions blocked'))
  const sparse = render(React.createElement(ActionWorkspace, { actions: [], persona: 'CFO', verdict: 'INSUFFICIENT_HISTORY' }))
  assert.ok(sparse.includes('The engine is abstaining from action.'))
  assert.ok(!sparse.includes('Actions blocked'))
})

test('unauthorized results suppress action details', () => {
  const html = render(React.createElement(ActionWorkspace, { actions: [], persona: 'CFO', verdict: 'ACCESS_DENIED' }))
  assert.ok(!html.includes('Decision workspace'))
  assert.ok(!html.includes('owner'))
})

test('legacy cards render safely without inventing new values', () => {
  const legacy = { kind: 'NEXT_CHECK', recommendation: 'Review the event timeline.', owner: 'analyst', status: 'AWAITING_REVIEW', expected_impact: null }
  const html = render(React.createElement(ActionWorkspace, { actions: [legacy], persona: 'marketing_manager' }))
  assert.ok(html.includes('Review the event timeline.'))
  assert.ok(html.includes('Not specified'))
  assert.ok(!html.includes('undefined'))
  assert.ok(html.includes('Legacy recommendation snapshot'))
})

test('structured and legacy layouts are distinct and optional facts are omitted', () => {
  assert.equal(isLegacyAction({ kind: 'NEXT_CHECK', driver_id: 'stock_availability', lever: 'Availability', recommendation: 'Check records.', owner: 'analyst', status: 'AWAITING_REVIEW', evidence_paths: [], expected_impact: null }), true)
  assert.equal(isLegacyAction(action), false)
  const sparse = { ...action, driver_rank: null, owner_source: null, decision_right: null, evidence_status: null, confidence_status: null, monitoring_plan: null, success_metric: null, review_window: null, stop_conditions: null, evidence_references: [] }
  const html = render(React.createElement(ActionWorkspace, { actions: [sparse], persona: 'CFO' }))
  assert.ok(!html.includes('Owner source'))
  assert.ok(!html.includes('Decision right'))
  assert.ok(!html.includes('Stop conditions'))
  assert.ok(html.includes('Impact is not estimated'))
})

test('workspace count labels distinguish proposals, verification and blocked states', () => {
  assert.equal(actionCountLabel([{ kind: 'ACTION_PROPOSAL' }]), '1 action proposal')
  assert.equal(actionCountLabel([{ kind: 'NEXT_CHECK' }]), '1 verification check')
  assert.equal(actionCountLabel([]), 'No action')
  const blocked = render(React.createElement(ActionWorkspace, { actions: [], persona: 'CFO', verdict: 'CONTRADICTED' }))
  assert.ok(blocked.includes('Actions blocked'))
})

test('secondary action details are collapsible and legacy monitoring text is absent', () => {
  const html = render(React.createElement(ActionWorkspace, { actions: [action], persona: 'CFO' }))
  assert.ok(html.includes('<details'))
  assert.ok(html.includes('Execution details and evidence'))
  assert.ok(!html.includes('Monitor: traffic, conversion rate, orders and revenue'))
})

test('responsive CSS scopes structured cards and provides tablet/mobile grids', () => {
  const css = fs.readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8')
  assert.ok(css.includes('.action-item, .action-legacy-card'))
  assert.ok(!css.includes('.action-list article'))
  assert.ok(css.includes('.action-facts, .action-detail-grid, .action-legacy-facts { grid-template-columns: repeat(2'))
  assert.ok(css.includes('.action-facts, .action-detail-grid, .action-legacy-facts { grid-template-columns: 1fr; }'))
})

test('persona framing changes while action facts remain unchanged', () => {
  const cfo = render(React.createElement(ActionWorkspace, { actions: [action], persona: 'CFO' }))
  const marketing = render(React.createElement(ActionWorkspace, { actions: [action], persona: 'marketing_manager' }))
  assert.ok(cfo.includes('approval, decision risk, reconciliation'))
  assert.ok(marketing.includes('operational next checks, controllable levers'))
  for (const fact of [action.recommendation, 'Operations lead', action.decision_right, action.monitoring_plan]) {
    assert.ok(cfo.includes(fact))
    assert.ok(marketing.includes(fact))
  }
})
