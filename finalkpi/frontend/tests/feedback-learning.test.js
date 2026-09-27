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
const FeedbackCapture = require('../components/feedback-capture.tsx').default
const model = require('../lib/feedback-learning.ts')

const run = {
  run_id: 'run-authorized-1',
  kpi_id: 'orders',
  movement_assessment: { delta: 2, actual_value: 12 },
  reconciliation_verdict: { status: 'AGREED' },
  driver_analysis: { ranked_drivers: [{ driver_id: 'traffic_drop' }], excluded_drivers: [] },
  decomposition: { volume_effect: 1 },
  confidence_profile: { overall: { status: 'MODERATE' } },
  narrative_claims: [{ text: 'Associated movement', claim_type: 'CORRELATIONAL' }],
  decision_cards: [{ action_id: 'action-1' }],
}

const aggregation = {
  aggregation_key: 'agg-server-key',
  kpi_id: 'orders', scope: { region: 'North' }, target_type: 'DRIVER', target_id: 'traffic_drop',
  mode: 'ANALYST_CORRECTION', feedback_count: 2, business_feedback_count: 0, analyst_correction_count: 2,
  useful_count: 0, not_useful_count: 0, reason_counts: {}, issue_category_counts: { DRIVER: 2 },
  correction_type_counts: { REINTERPRET: 2 }, action_taken_counts: {}, unique_authorized_submitter_count: 2,
  earliest_created_at: '2026-01-01T00:00:00Z', latest_created_at: '2026-01-02T00:00:00Z',
  source_feedback_ids: ['fb-1', 'fb-2'], affected_run_ids: ['run-1', 'run-2'], current_artifact_versions: {},
  proposal_type_options: [
    { proposal_type: 'DRIVER_CONFIGURATION_CHANGE', target_artifact_type: 'DRIVER_CONFIGURATION', fields: [
      { name: 'driver_id', label: 'Driver', max_length: 200 },
      { name: 'proposed_configuration', label: 'Proposed configuration', max_length: 2000, source: 'analyst_correction' },
    ] },
    { proposal_type: 'EVALUATION_CASE_ADDITION', target_artifact_type: 'EVALUATION_CASE', fields: [
      { name: 'case_description', label: 'Case description', max_length: 1200 },
      { name: 'expected_outcome', label: 'Expected outcome', options: ['ABSTAIN'] },
    ] },
  ],
}

function render(node) { return renderToStaticMarkup(node) }

 test('business feedback payload contains only permitted client fields', () => {
  const payload = model.buildBusinessFeedbackRequest({
    run, userId: 'demo-marketing', targetType: 'MOVEMENT', targetId: 'delta', rating: 'USEFUL',
    reasonCode: 'ACTIONABLE', comment: 'Helpful', actionTaken: 'YES', outcomeObservation: 'Checked',
  })
  assert.deepEqual(Object.keys(payload).sort(), [
    'action_taken', 'comment', 'mode', 'outcome_observation', 'rating', 'reason_code',
    'run_id', 'target_id', 'target_type', 'user_id',
  ].sort())
  assert.equal(payload.mode, 'BUSINESS_FEEDBACK')
  assert.equal(model.feedbackSuccessMessage(payload.mode), 'Feedback captured for review.')
  assert.equal('kpi_id' in payload, false)
  assert.equal('snapshot' in payload || 'original_snapshot' in payload, false)
  assert.equal('reviewer' in payload, false)
})

test('successful feedback request posts typed JSON and resolves only on success', async () => {
  const payload = model.buildBusinessFeedbackRequest({ run, userId: 'demo-marketing', targetType: 'KPI', targetId: 'orders', rating: 'NOT_USEFUL' })
  let request
  await model.postFeedbackRequest(payload, async (url, options) => {
    request = { url, options }
    return { ok: true }
  })
  assert.equal(request.url, '/api/backend/feedback')
  assert.equal(request.options.method, 'POST')
  assert.deepEqual(JSON.parse(request.options.body), payload)
})

test('failed submission preserves caller form values and returns backend validation message', async () => {
  const payload = model.buildBusinessFeedbackRequest({ run, userId: 'demo-marketing', targetType: 'KPI', targetId: 'orders', rating: 'USEFUL', comment: 'keep this' })
  const before = { ...payload }
  await assert.rejects(
    model.postFeedbackRequest(payload, async () => ({ ok: false, json: async () => ({ detail: 'Target is unavailable.' }) })),
    /Target is unavailable/,
  )
  assert.deepEqual(payload, before)
})

test('target options are derived from the authorized run and reject arbitrary IDs', () => {
  const targets = model.feedbackTargetOptions(run)
  assert.ok(targets.some(option => option.target_type === 'DRIVER' && option.target_id === 'traffic_drop'))
  assert.ok(targets.some(option => option.target_type === 'ACTION' && option.target_id === 'action-1'))
  assert.ok(!targets.some(option => option.target_id === 'private-secret'))
  assert.throws(() => model.buildBusinessFeedbackRequest({ run, userId: 'demo-cfo', targetType: 'DRIVER', targetId: 'private-secret', rating: 'USEFUL' }), /Select a target/)
})

test('analyst controls are hidden from business users and form targets come from the saved run', () => {
  const html = render(React.createElement(FeedbackCapture, { run, userId: 'demo-marketing', reviewer: false }))
  assert.ok(html.includes('Diagnosis run'))
  assert.ok(html.includes('Driver: traffic_drop'))
  assert.ok(!html.includes('Analyst correction'))
  assert.ok(!html.includes('Issue category'))
})

test('analyst correction accepts only allowed issue categories and valid run evidence references', () => {
  const payload = model.buildAnalystCorrectionRequest({
    run, userId: 'demo-cfo', reviewer: true, targetType: 'DRIVER', targetId: 'traffic_drop',
    issueCategory: 'DRIVER', correctionType: 'REINTERPRET', proposedCorrection: 'Association only',
    rationale: 'No contribution evidence', evidenceRefs: ['driver_analysis.ranked_drivers'],
  })
  assert.equal(payload.mode, 'ANALYST_CORRECTION')
  assert.equal(payload.issue_category, 'DRIVER')
  assert.deepEqual(payload.evidence_refs, ['driver_analysis.ranked_drivers'])
  assert.throws(() => model.buildAnalystCorrectionRequest({
    run, userId: 'demo-cfo', reviewer: true, targetType: 'DRIVER', targetId: 'traffic_drop',
    issueCategory: 'DRIVER', correctionType: 'FIX', proposedCorrection: 'x', rationale: 'y', evidenceRefs: ['private.file'],
  }), /Evidence references/)
  assert.throws(() => model.buildAnalystCorrectionRequest({
    run, userId: 'demo-marketing', reviewer: false, targetType: 'DRIVER', targetId: 'traffic_drop',
    issueCategory: 'DRIVER', correctionType: 'FIX', proposedCorrection: 'x', rationale: 'y', evidenceRefs: [],
  }), /not available/)
  assert.deepEqual(model.ANALYST_ISSUES, ['DATA', 'KPI_CONTRACT', 'BUSINESS_RULE', 'DRIVER', 'ANALYTICAL_METHOD', 'CONFIDENCE', 'NARRATIVE', 'ACTION', 'ACCESS_POLICY'])
})

test('feedback lifecycle uses backend event data and maps neutral, info, approved and rejected tones', () => {
  const record = { feedback_id: 'fb-1', state: 'TRIAGED', events: [{ event_id: 1, from_state: null, to_state: 'CAPTURED' }, { event_id: 2, from_state: 'CAPTURED', to_state: 'TRIAGED' }] }
  assert.equal(record.events[1].to_state, 'TRIAGED')
  assert.equal(model.feedbackStateTone('CAPTURED'), 'neutral')
  assert.equal(model.feedbackStateTone('PROPOSED'), 'neutral')
  assert.equal(model.feedbackStateTone('TRIAGED'), 'info')
  assert.equal(model.feedbackStateTone('ACCEPTED'), 'good')
  assert.equal(model.feedbackStateTone('REJECTED'), 'danger')
})

test('aggregation views omit raw comments and business proposal choices come from backend metadata', () => {
  const source = fs.readFileSync(new URL('../components/feedback-review-workspace.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('item.proposal_type_options'))
  assert.ok(source.includes('item.reason_counts'))
  assert.ok(!source.includes('aggregation.comments'))
  const business = { ...aggregation, mode: 'BUSINESS_FEEDBACK', proposal_type_options: [
    { proposal_type: 'REVIEW_REQUIRED', target_artifact_type: 'REVIEW_ONLY', fields: [] },
    aggregation.proposal_type_options.find(option => option.proposal_type === 'EVALUATION_CASE_ADDITION'),
  ] }
  assert.deepEqual(business.proposal_type_options.map(option => option.proposal_type), ['REVIEW_REQUIRED', 'EVALUATION_CASE_ADDITION'])
  assert.throws(() => model.proposalCreatePayload({ userId: 'demo-cfo', aggregation: business, proposalType: 'DRIVER_CONFIGURATION_CHANGE', title: 't', rationale: 'r', changeFields: {}, expectedImprovement: 'e', affectedCases: [], rollbackPlan: 'b' }), /not compatible/)
})

test('analyst proposal options follow backend compatibility metadata and correction selection', () => {
  const payload = model.proposalCreatePayload({
    userId: 'demo-cfo', aggregation, proposalType: 'DRIVER_CONFIGURATION_CHANGE', sourceFeedbackId: 'fb-2',
    title: 'Review driver wording', rationale: 'Association only',
    changeFields: { driver_id: 'traffic_drop', proposed_configuration: 'Association only' },
    expectedImprovement: 'Avoid causal inference', affectedCases: ['material-a'], rollbackPlan: 'Retain current version',
  })
  assert.equal(payload.aggregation_key, 'agg-server-key')
  assert.deepEqual(payload.proposed_change, { source_feedback_id: 'fb-2', driver_id: 'traffic_drop', proposed_configuration: 'Association only' })
  assert.throws(() => model.proposalCreatePayload({
    userId: 'demo-cfo', aggregation, proposalType: 'BUSINESS_RULE_CHANGE', sourceFeedbackId: 'fb-2',
    title: 't', rationale: 'r', changeFields: {}, expectedImprovement: 'e', affectedCases: [], rollbackPlan: 'b',
  }), /not compatible/)
})

test('proposal review asks for approval-only confirmation and accepted state remains unapplied', () => {
  const source = fs.readFileSync(new URL('../components/feedback-review-workspace.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('Accepting this proposal records approval only. It does not apply the change or verify an improvement.'))
  assert.ok(source.includes('outcome.applied ? \'Yes\' : \'No\''))
  assert.ok(source.includes('outcome.verified ? \'Yes\' : \'No\''))
  const accepted = model.proposalOutcomeFacts({ state: 'ACCEPTED', applied: false, verified: false, message: 'Proposal accepted; not yet applied or verified' })
  assert.deepEqual(accepted, { accepted: true, applied: false, verified: false, message: 'Proposal accepted; not yet applied or verified' })
})

test('legacy feedback is visibly read-only and has no lifecycle controls', () => {
  const source = fs.readFileSync(new URL('../components/feedback-review-workspace.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('Legacy · read only'))
  assert.ok(source.includes('!item.legacy'))
  assert.ok(source.includes('item.legacy ? item.status : item.state'))
})

test('authorization load failures clear feedback metadata and pages use shared components', () => {
  const workspace = fs.readFileSync(new URL('../components/feedback-review-workspace.tsx', import.meta.url), 'utf8')
  const detail = fs.readFileSync(new URL('../app/performance/[runId]/page.tsx', import.meta.url), 'utf8')
  const insights = fs.readFileSync(new URL('../app/insights/page.tsx', import.meta.url), 'utf8')
  assert.ok(workspace.includes('setFeedback([])'))
  assert.ok(workspace.includes('setAggregations([])'))
  assert.ok(workspace.includes('setProposals([])'))
  assert.ok(detail.includes('<FeedbackCapture'))
  assert.ok(detail.includes("run.verdict !== 'ACCESS_DENIED'"))
  assert.ok(insights.includes('<FeedbackReviewWorkspace'))
  assert.ok(!detail.includes('original_snapshot'))
  assert.ok(!detail.includes('kpi_id: run.kpi_id'))
})

 test('workspaces prevent duplicate requests while pending and page integration keeps insights list', () => {
  const workspace = fs.readFileSync(new URL('../components/feedback-review-workspace.tsx', import.meta.url), 'utf8')
  const capture = fs.readFileSync(new URL('../components/feedback-capture.tsx', import.meta.url), 'utf8')
  const insights = fs.readFileSync(new URL('../app/insights/page.tsx', import.meta.url), 'utf8')
  assert.ok(workspace.includes('disabled={!!savingId}'))
  assert.ok(workspace.includes('if (savingId || proposal.state !== \'PROPOSED\') return'))
  assert.ok(capture.includes('disabled={saving || !target'))
  assert.ok(insights.includes('items.map(item =>'))
})
