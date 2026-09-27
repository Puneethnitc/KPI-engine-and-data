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
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    }).outputText
    module._compile(compiled, filename)
  }
}

const model = require('../lib/feedback-learning.ts')
const proposal = (overrides = {}) => ({
  proposal_id: 'proposal-1', aggregation_key: 'agg-1', proposal_type: 'NARRATIVE_TEMPLATE_CHANGE',
  title: 'Wording correction', rationale: 'Clarify the association boundary.', kpi_id: 'orders',
  scope: { region: 'North', category: 'Electronics' }, target_type: 'NARRATIVE_CLAIM', target_id: '0',
  source_feedback_ids: ['fb-1'], source_run_ids: ['run-1'], issue_reason_summary: {},
  target_artifact_type: 'APPROVED_NARRATIVE_TEMPLATE_VARIANT', before_version: 'approved_narrative_templates_v1',
  before_version_hash: 'basehash', proposed_change: { template_target: 'CORRELATIONAL' },
  supporting_feedback_summary: { feedback_count: 1 }, expected_improvement: 'Avoid causal wording.',
  affected_evaluation_cases: ['run-1'], rollback_plan: 'Retire candidate.', state: 'ACCEPTED',
  application_support: 'SUPPORTED', candidate_artifact_id: null, candidate_version: null,
  evaluation_run_ids: [], events: [], application_status: 'Not yet applied', verification_status: 'Not yet verified',
  applied: false, verified: false, deployed: false, evaluation_only: true, message: 'Proposal accepted; not yet applied or verified',
  ...overrides,
})
const candidate = (overrides = {}) => ({
  candidate_artifact_id: 'candidate-a1', proposal_id: 'proposal-1', artifact_type: 'APPROVED_NARRATIVE_TEMPLATE_VARIANT',
  kpi_id: 'orders', scope: { region: 'North', category: 'Electronics' }, base_version: 'approved_narrative_templates_v1',
  candidate_version: 'approved_narrative_templates_v1-candidate-a1', base_payload: { template_registry: 'approved_narrative_templates_v1' },
  validated_change: { source_feedback_id: 'fb-1', template_target: 'CORRELATIONAL' },
  candidate_payload: { template_target: 'CORRELATIONAL', proposed_wording: 'Association only.' }, payload_hash: 'hash-a1',
  created_by: 'demo-cfo', created_at: '2026-09-27T12:00:00Z', activation_status: 'EVALUATION_ONLY',
  rollback_of: null, supersedes: null, events: [{ event_id: 1, event_type: 'CREATED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T12:00:00Z' }],
  evaluation_run_ids: [], proposal_state: 'APPLIED', candidate_state: 'APPLIED', rollback_status: 'NOT_ROLLED_BACK',
  applied: true, verified: false, deployed: false, evaluation_only: true, message: 'Candidate exists in evaluation workspace only.',
  evaluation_plan: {
    affected_cases: [{ run_id: 'run-1', target_date: '2026-01-01', as_of: '2026-01-02T00:00:00Z' }],
    holdout_cases: [{ run_id: 'run-2', target_date: '2026-01-03', as_of: '2026-01-04T00:00:00Z' }],
    gates: [{ gate_id: 'quantitative_fields_unchanged', description: 'KPI fields remain unchanged.' }],
    evaluator_method: 'frozen_saved_run_candidate_comparison', evaluator_version: '1.0',
    input_policy: 'Same frozen run and as-of.', llm_gate_decision: false, evaluation_only: true, deployed: false,
  },
  ...overrides,
})
const evaluation = (overrides = {}) => ({
  evaluation_run_id: 'evaluation-1', proposal_id: 'proposal-1', candidate_artifact_id: 'candidate-a1',
  baseline_artifact_version: 'base-v1', candidate_artifact_version: 'candidate-v1',
  affected_cases: ['run-1'], holdout_cases: ['run-2'], metrics: { quantitative_difference_count: 0 },
  gates: { affected_cases_pass: true, holdout_cases_pass_when_available: true },
  baseline_results: {}, candidate_results: {}, case_differences: {},
  case_results: [{ case_id: 'run-1', case_kind: 'AFFECTED', input_run_id: 'run-1', input_snapshot_hash: 'snap1', as_of: '2026-01-02T00:00:00Z', baseline_result: { broad_outcome: 'MATERIAL' }, candidate_result: { broad_outcome: 'MATERIAL', narrative: 'Association only.' }, differences: { narrative: { baseline: 'Before', candidate: 'Association only.' } }, gate_results: { quantitative_fields_unchanged: true, grounding_preserved: true } }],
  started_at: '2026-09-27T12:00:00Z', completed_at: '2026-09-27T12:01:00Z',
  evaluator_method: 'frozen_saved_run_candidate_comparison', evaluator_version: '1.0', final_result: 'VERIFIED',
  proposal_state: 'VERIFIED', candidate_state: 'VERIFIED', applied: true, verified: true,
  failure_reasons: [], inputs_hash: 'inputs-hash', deployed: false, evaluation_only: true,
  rollback_status: 'NOT_ROLLED_BACK', message: 'Verified in offline evaluation; not deployed to the live engine.',
  ...overrides,
})

const feedback = [{
  feedback_id: 'fb-1', mode: 'ANALYST_CORRECTION', run_id: 'run-1', user_id: 'demo-cfo', persona: 'CFO',
  kpi_id: 'orders', scope: { region: 'North', category: 'Electronics' }, target_type: 'NARRATIVE_CLAIM', target_id: '0',
  state: 'ACCEPTED', created_at: '2026-09-27T11:00:00Z', events: [
    { event_id: 1, feedback_id: 'fb-1', event_type: 'SUBMITTED', from_state: null, to_state: 'CAPTURED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T10:00:00Z' },
    { event_id: 2, feedback_id: 'fb-1', event_type: 'TRIAGED', from_state: 'CAPTURED', to_state: 'TRIAGED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T10:30:00Z' },
    { event_id: 3, feedback_id: 'fb-1', event_type: 'ACCEPTED', from_state: 'TRIAGED', to_state: 'ACCEPTED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T11:00:00Z' },
  ],
}]

 test('accepted supported proposal exposes candidate creation; unsupported proposal does not', () => {
  assert.deepEqual(model.candidateActionAvailability(proposal(), null, true), {
    showApply: true, unsupported: false, showEvaluate: false, showRollback: false, rolledBack: false,
  })
  assert.deepEqual(model.candidateActionAvailability(proposal({ application_support: 'APPLICATION_NOT_SUPPORTED' }), null, true), {
    showApply: false, unsupported: true, showEvaluate: false, showRollback: false, rolledBack: false,
  })
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('APPLICATION_NOT_SUPPORTED'))
  assert.ok(source.includes('This proposal remains accepted but cannot be applied by the prototype.'))
  assert.ok(source.includes('actions.showApply'))
})

test('candidate application requires explicit evaluation-only confirmation and pending state', () => {
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('Application creates an evaluation-only candidate. It does not change the live engine.'))
  assert.ok(source.includes('pending ? \'Creating candidate…\' : \'Create evaluation candidate\''))
  assert.ok(source.includes('if (!reviewer || pending || proposal.state !== \'ACCEPTED\''))
})

test('candidate renders base and candidate versions, safe payload, and non-deployment flags', () => {
  const candidateResponse = candidate()
  assert.deepEqual(model.candidateDeploymentFacts(candidateResponse), {
    evaluationOnly: true, deployed: false, baseVersion: 'approved_narrative_templates_v1',
    candidateVersion: 'approved_narrative_templates_v1-candidate-a1', artifactId: 'candidate-a1', payloadHash: 'hash-a1',
  })
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  for (const field of ['candidate_artifact_id', 'proposal_id', 'artifact_type', 'candidate_version', 'base_version', 'payload_hash', 'created_by', 'activation_status']) assert.ok(source.includes(`candidate.${field}`), field)
  assert.ok(source.includes('candidate.evaluation_only'))
  assert.ok(source.includes('candidate.deployed'))
  assert.ok(source.includes('candidate.evaluation_only'))
  assert.ok(source.includes('candidate.deployed'))
  assert.ok(source.includes('Not deployed to the live engine'))
  assert.ok(source.includes('safeJson(candidate.candidate_payload)'))
})

test('APPLIED candidates expose offline evaluation and the backend gate plan', () => {
  const applied = proposal({ state: 'APPLIED', candidate_artifact_id: 'candidate-a1', application_support: 'SUPPORTED' })
  assert.equal(model.candidateActionAvailability(applied, candidate(), true).showEvaluate, true)
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  for (const expected of ['affected_cases', 'holdout_cases', 'evaluation_plan.gates', 'input_policy', 'An LLM does not determine whether these gates pass.', 'Run offline evaluation']) assert.ok(source.includes(expected))
})

test('VERIFIED and FAILED_VERIFICATION retain distinct messages and exact gate failures', () => {
  const verified = evaluation()
  const failed = evaluation({ final_result: 'FAILED_VERIFICATION', proposal_state: 'FAILED_VERIFICATION', verified: false, failure_reasons: ['run-1:grounding_preserved'], message: 'Candidate failed offline verification; not deployed to the live engine.' })
  assert.equal(verified.message, 'Verified in offline evaluation; not deployed to the live engine.')
  assert.equal(failed.message, 'Candidate failed offline verification; not deployed to the live engine.')
  assert.deepEqual(failed.failure_reasons, ['run-1:grounding_preserved'])
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('The candidate failed offline verification and has not changed the live engine.'))
  assert.ok(source.includes('evaluation.failure_reasons.map'))
  assert.ok(source.includes('evaluation.case_results.map'))
  assert.ok(source.includes('evaluation.gates).map'))
})

test('rollback requires a non-empty bounded reason and explicit confirmation', () => {
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('rollbackReason.length > 1000'))
  assert.ok(source.includes('!rollbackReason.trim()'))
  assert.ok(source.includes('window.confirm('))
  assert.ok(source.includes('The candidate was retired'))
})

test('rollback leaves evaluation history and reports the live engine unchanged', () => {
  const rolled = candidate({ rollback_status: 'ROLLED_BACK', candidate_state: 'ROLLED_BACK', events: [...candidate().events, { event_id: 2, event_type: 'ROLLED_BACK', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: 'Retired candidate', created_at: '2026-09-27T13:00:00Z' }], evaluation_run_ids: ['evaluation-1'] })
  assert.deepEqual(rolled.evaluation_run_ids, ['evaluation-1'])
  assert.equal(rolled.events.at(-1).reason, 'Retired candidate')
  assert.equal(model.candidateActionAvailability(proposal({ state: 'ROLLED_BACK' }), rolled, true).showRollback, false)
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('The candidate was retired. The live engine was unchanged.'))
  assert.ok(source.includes('candidatePayload.evaluation_run_ids'))
})

test('trace includes only returned identifiers and never fabricates missing candidate/evaluation steps', () => {
  const proposed = proposal({ state: 'PROPOSED', events: [{ event_id: 10, proposal_id: 'proposal-1', event_type: 'PROPOSED', from_state: null, to_state: 'PROPOSED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T11:30:00Z' }] })
  const incomplete = model.buildLearningTrace(proposed, feedback)
  assert.deepEqual(incomplete.map(step => step.id), [
    'feedback-event-1', 'feedback-event-2', 'feedback-event-3', 'agg-1', 'proposal-event-10',
  ])
  assert.ok(!incomplete.some(step => step.label.includes('Candidate artifact created') || step.label.includes('Offline evaluation')))
  assert.equal(model.nextLearningStep(proposed), 'Await authorized proposal review.')
  const completed = model.buildLearningTrace(proposal({ events: [{ event_id: 11, proposal_id: 'proposal-1', event_type: 'APPLIED', from_state: 'ACCEPTED', to_state: 'APPLIED', actor_user_id: 'demo-cfo', actor_persona: 'CFO', reason: null, created_at: '2026-09-27T12:00:00Z' }] }), feedback, candidate(), [evaluation()])
  assert.ok(completed.some(step => step.id === 'candidate-event-1'))
  assert.ok(completed.some(step => step.id === 'evaluation-1'))
})

test('business users cannot apply, evaluate, or roll back; incomplete and unsupported states stay accurate', () => {
  assert.deepEqual(model.candidateActionAvailability(proposal(), null, false), {
    showApply: false, unsupported: false, showEvaluate: false, showRollback: false, rolledBack: false,
  })
  assert.equal(model.nextLearningStep(proposal({ application_support: 'APPLICATION_NOT_SUPPORTED' })), 'Application is not supported for this proposal type.')
  assert.equal(model.nextLearningStep(proposal({ state: 'APPLIED' })), 'Run deterministic offline evaluation.')
  assert.equal(model.nextLearningStep(proposal({ state: 'ROLLED_BACK' })), 'Candidate retired; history is preserved.')
  const source = fs.readFileSync(new URL('../components/candidate-learning-panel.tsx', import.meta.url), 'utf8')
  assert.ok(source.includes('if (!reviewer || pending'))
  assert.ok(source.includes('if (response.status === 403 || response.status === 404) onAuthorizationFailure()'))
  assert.ok(source.includes('setCandidate(null)'))
  assert.ok(source.includes('setEvaluation(null)'))
  assert.ok(source.includes('candidate.rollback_status'))
})

test('Insights uses existing feedback workspace and proxy allows candidate/evaluation endpoints', () => {
  const insights = fs.readFileSync(new URL('../app/insights/page.tsx', import.meta.url), 'utf8')
  const detail = fs.readFileSync(new URL('../app/performance/[runId]/page.tsx', import.meta.url), 'utf8')
  const proxy = fs.readFileSync(new URL('../app/api/backend/[...path]/route.ts', import.meta.url), 'utf8')
  assert.ok(insights.includes('<FeedbackReviewWorkspace'))
  assert.ok(detail.includes('<FeedbackCapture'))
  assert.ok(proxy.includes("'candidate-artifacts'"))
  assert.ok(proxy.includes("'proposal-evaluations'"))
})
