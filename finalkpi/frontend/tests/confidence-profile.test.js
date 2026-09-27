import assert from 'node:assert/strict'
import test from 'node:test'
import {
  confidenceScoreLabel,
  confidenceProfileUnavailableMessage,
  confidenceStatusLabel,
  confidenceStatusTone,
  confidenceWorkspaceModel,
} from '../lib/confidence-profile.ts'

const statuses = ['HIGH', 'MODERATE', 'LOW', 'INSUFFICIENT_EVIDENCE', 'CONFLICTING_EVIDENCE', 'NOT_ASSESSED']

function makeDimension(status, reason = `Reason for ${status}`) {
  return {
    status,
    score: null,
    score_scale: 'No calibrated numeric score is emitted.',
    score_interpretation: 'Categorical status; not a probability.',
    method: 'deterministic_test_method',
    inputs: { observed_value: 42 },
    reasons: [reason],
    limitations: ['Calibration has not been validated.'],
    evaluated_at: '2026-09-27T00:00:00+00:00',
    applicable: true,
    blocking: false,
    evidence_refs: ['test:movement'],
  }
}

function makeProfile(overrides = {}) {
  return {
    version: '1.0',
    evaluated_at: '2026-09-27T00:00:00+00:00',
    overall: {
      status: 'MODERATE',
      method: 'BLOCKING_GATES_V1',
      reasons: ['Movement is assessed; causality is not.'],
      blocking_dimensions: [],
    },
    movement: makeDimension('HIGH'),
    source: makeDimension('HIGH'),
    driver: makeDimension('MODERATE'),
    causal: makeDimension('NOT_ASSESSED', 'No approved causal design exists.'),
    ...overrides,
  }
}

test('every evidence status has a clear label and intentional tone', () => {
  const expected = {
    HIGH: ['High evidence', 'good'],
    MODERATE: ['Moderate evidence', 'limited'],
    LOW: ['Low evidence', 'limited'],
    INSUFFICIENT_EVIDENCE: ['Insufficient evidence', 'limited'],
    CONFLICTING_EVIDENCE: ['Conflicting evidence', 'warning'],
    NOT_ASSESSED: ['Not assessed', 'neutral'],
  }
  for (const status of statuses) {
    assert.equal(confidenceStatusLabel(status), expected[status][0])
    assert.equal(confidenceStatusTone(status), expected[status][1])
  }
})

test('null scores render as uncalibrated, never zero or a percentage', () => {
  assert.equal(confidenceScoreLabel(null), 'Not calibrated')
  assert.notEqual(confidenceScoreLabel(null), '0%')
  assert.equal(confidenceScoreLabel(0), '0')
})

test('all four dimensions remain independently represented', () => {
  const model = confidenceWorkspaceModel(makeProfile(), 'CFO', 'MATERIAL_CAUSE_UNVERIFIED')
  assert.deepEqual(model.dimensions.map(item => item.key), ['movement', 'source', 'driver', 'causal'])
  assert.deepEqual(model.dimensions.map(item => item.status), ['HIGH', 'HIGH', 'MODERATE', 'NOT_ASSESSED'])
})

test('causal NOT_ASSESSED is distinct from LOW', () => {
  const notAssessed = confidenceWorkspaceModel(makeProfile(), 'CFO').dimensions[3]
  const low = confidenceWorkspaceModel(makeProfile({ causal: makeDimension('LOW') }), 'CFO').dimensions[3]
  assert.equal(notAssessed.statusLabel, 'Not assessed')
  assert.equal(notAssessed.boundaryMessage, 'Not assessed: no approved causal design exists for this run.')
  assert.equal(low.statusLabel, 'Low evidence')
  assert.equal(low.boundaryMessage, null)
})

test('contradictory and sparse outcomes use explicit overall messages', () => {
  const conflicting = confidenceWorkspaceModel(makeProfile({
    overall: { status: 'CONFLICTING_EVIDENCE', method: 'BLOCKING_GATES_V1', reasons: ['Sources contradict.'], blocking_dimensions: ['source', 'causal'] },
    source: makeDimension('CONFLICTING_EVIDENCE', 'Independent sources contradict.'),
  }), 'CFO')
  const sparse = confidenceWorkspaceModel(makeProfile({
    overall: { status: 'INSUFFICIENT_EVIDENCE', method: 'BLOCKING_GATES_V1', reasons: ['History is too sparse.'], blocking_dimensions: [] },
    movement: makeDimension('INSUFFICIENT_EVIDENCE', 'Baseline history is insufficient.'),
  }), 'Marketing Manager')
  assert.equal(conflicting.overall.statusLabel, 'Conflicting evidence')
  assert.equal(conflicting.overall.blockingDimensions.length, 2)
  assert.equal(sparse.overall.statusLabel, 'Insufficient evidence')
  assert.equal(sparse.dimensions[0].reason, 'Baseline history is insufficient.')
})

test('persona framing changes wording but preserves statuses and quantitative facts', () => {
  const profile = makeProfile()
  const cfo = confidenceWorkspaceModel(profile, 'CFO')
  const marketing = confidenceWorkspaceModel(profile, 'Marketing Manager')
  assert.notEqual(cfo.personaFrame, marketing.personaFrame)
  assert.match(cfo.personaFrame, /financial materiality, reconciliation/)
  assert.match(marketing.personaFrame, /operational signals, controllable diagnostic levers/)
  assert.deepEqual(
    cfo.dimensions.map(({ key, status, scoreLabel, reason, details }) => ({ key, status, scoreLabel, reason, input: details.inputs.observed_value })),
    marketing.dimensions.map(({ key, status, scoreLabel, reason, details }) => ({ key, status, scoreLabel, reason, input: details.inputs.observed_value })),
  )
})

test('access-denied runs suppress the confidence workspace', () => {
  assert.equal(confidenceWorkspaceModel(makeProfile(), 'CFO', 'ACCESS_DENIED'), null)
  assert.equal(confidenceProfileUnavailableMessage(makeProfile(), 'ACCESS_DENIED'), null)
})

test('legacy historical runs say the profile was not saved and was not recomputed', () => {
  const message = confidenceProfileUnavailableMessage(null, 'MATERIAL_CAUSE_UNVERIFIED')
  assert.match(message, /No confidence profile was saved/)
  assert.match(message, /not been recomputed from current data/)
})