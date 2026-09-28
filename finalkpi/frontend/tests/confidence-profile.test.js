import assert from 'node:assert/strict'
import test from 'node:test'
import {
  attributionConfidenceBars,
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

function makeAttributionDriver(overrides = {}) {
  return {
    driver_id: 'marketing_spend',
    display_name: 'Marketing spend',
    attribution_confidence: 0.74,
    band: 'MODERATE',
    label: 'Likely a contributing cause',
    prior: 0.5,
    evidence: [
      { id: 'E1', name: 'explained_share', value: 0.62, weight_contribution: 1.24, note: 'Explains 62%' },
    ],
    caps_applied: [],
    model_version: 'attribution-confidence-v1',
    calibration: { status: 'HAND_SET_PRIOR', split: null },
    ...overrides,
  }
}

function makeProfile(overrides = {}) {
  return {
    version: '1.0',
    evaluated_at: '2026-09-27T00:00:00+00:00',
    overall: {
      status: 'MODERATE',
      method: 'WEAKEST_REQUIRED_DIMENSION_V1',
      reasons: ['Movement is assessed; causality is not.'],
      blocking_dimensions: [],
      movement_conclusion: 'HIGH',
      explanation_conclusion: 'MODERATE',
    },
    attribution_status: 'CONFIDENT',
    attribution_confidence: [makeAttributionDriver()],
    movement: makeDimension('HIGH'),
    source: makeDimension('HIGH'),
    attribution: makeDimension('MODERATE'),
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

test('all four dimensions remain independently represented, with attribution replacing driver', () => {
  const model = confidenceWorkspaceModel(makeProfile(), 'CFO', 'MATERIAL_CAUSE_UNVERIFIED')
  assert.deepEqual(model.dimensions.map(item => item.key), ['movement', 'source', 'attribution', 'causal'])
  assert.deepEqual(model.dimensions.map(item => item.status), ['HIGH', 'HIGH', 'MODERATE', 'NOT_ASSESSED'])
})

test('causal NOT_ASSESSED is distinct from LOW', () => {
  const notAssessed = confidenceWorkspaceModel(makeProfile(), 'CFO').dimensions[3]
  const low = confidenceWorkspaceModel(makeProfile({ causal: makeDimension('LOW') }), 'CFO').dimensions[3]
  assert.equal(notAssessed.statusLabel, 'Not assessed')
  assert.equal(notAssessed.boundaryMessage, 'Not assessed: no approved causal design targets the top-ranked driver for this run.')
  assert.equal(low.statusLabel, 'Low evidence')
  assert.equal(low.boundaryMessage, null)
})

test('contradictory and sparse outcomes use explicit overall messages', () => {
  const conflicting = confidenceWorkspaceModel(makeProfile({
    overall: {
      status: 'CONFLICTING_EVIDENCE', method: 'WEAKEST_REQUIRED_DIMENSION_V1', reasons: ['Sources contradict.'],
      blocking_dimensions: ['source', 'causal'], movement_conclusion: 'CONFLICTING_EVIDENCE',
      explanation_conclusion: 'CONFLICTING_EVIDENCE',
    },
    source: makeDimension('CONFLICTING_EVIDENCE', 'Independent sources contradict.'),
  }), 'CFO')
  const sparse = confidenceWorkspaceModel(makeProfile({
    overall: {
      status: 'INSUFFICIENT_EVIDENCE', method: 'WEAKEST_REQUIRED_DIMENSION_V1', reasons: ['History is too sparse.'],
      blocking_dimensions: [], movement_conclusion: 'INSUFFICIENT_EVIDENCE', explanation_conclusion: 'INSUFFICIENT_EVIDENCE',
    },
    movement: makeDimension('INSUFFICIENT_EVIDENCE', 'Baseline history is insufficient.'),
  }), 'Marketing Manager')
  assert.equal(conflicting.overall.statusLabel, 'Conflicting evidence')
  assert.equal(conflicting.overall.blockingDimensions.length, 2)
  assert.equal(sparse.overall.statusLabel, 'Insufficient evidence')
  assert.equal(sparse.dimensions[0].reason, 'Baseline history is insufficient.')
})

test('two headline conclusions are reported independently of the overall status', () => {
  const model = confidenceWorkspaceModel(makeProfile(), 'CFO')
  assert.equal(model.overall.movementConclusion.status, 'HIGH')
  assert.equal(model.overall.movementConclusion.statusLabel, 'High evidence')
  assert.equal(model.overall.explanationConclusion.status, 'MODERATE')
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

test('attribution confidence bars render a percent, band and evidence for each driver', () => {
  const bars = attributionConfidenceBars(makeProfile())
  assert.equal(bars.length, 1)
  assert.equal(bars[0].driverId, 'marketing_spend')
  assert.equal(bars[0].percent, 74)
  assert.equal(bars[0].band, 'MODERATE')
  assert.equal(bars[0].evidence[0].id, 'E1')
  assert.equal(bars[0].isUnexplained, false)
})

test('the unexplained row and capped drivers are visible in the bars', () => {
  const profile = makeProfile({
    attribution_confidence: [
      makeAttributionDriver({ attribution_confidence: 0.5, band: 'LOW', caps_applied: [
        { name: 'no_causal_test', max: 0.75, reason: 'No causal test result for this driver' },
      ] }),
      { driver_id: 'unexplained', display_name: 'Unexplained residual', attribution_confidence: 0.5,
        band: 'LOW', label: 'Possible; needs verification', prior: null, evidence: [], caps_applied: [],
        model_version: 'attribution-confidence-v1', calibration: { status: 'HAND_SET_PRIOR', split: null } },
    ],
  })
  const bars = attributionConfidenceBars(profile)
  assert.equal(bars[0].capsApplied.length, 1)
  assert.equal(bars[1].isUnexplained, true)
  assert.equal(bars[1].displayName, 'Unexplained')
})

test('a driver with insufficient history has no percent but is still listed', () => {
  const profile = makeProfile({
    attribution_confidence: [
      { driver_id: 'weather_temp', display_name: 'Weather temp', attribution_confidence: null, band: null,
        label: null, prior: null, evidence: [], caps_applied: [], model_version: 'attribution-confidence-v1',
        calibration: { status: 'HAND_SET_PRIOR', split: null }, status: 'INSUFFICIENT_HISTORY' },
    ],
  })
  const bars = attributionConfidenceBars(profile)
  assert.equal(bars[0].percent, null)
  assert.equal(bars[0].isInsufficientHistory, true)
})
