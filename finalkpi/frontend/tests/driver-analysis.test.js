import assert from 'node:assert/strict'
import test from 'node:test'
import {
  driverAnalysisStatusLabel,
  driverAnalysisViewModel,
  driverCoverageLabel,
  driverCorrelationLabel,
  driverExclusionLabel,
  driverScoreLabel,
  driverTemporalLabel,
} from '../lib/driver-analysis.ts'

function rankedDriver(overrides = {}) {
  return {
    rank: 1,
    driver_id: 'traffic_drop',
    display_name: 'Online traffic',
    source_id: 'sales_daily',
    source_grain: 'daily',
    aggregation: 'sum',
    driver_unit: 'visits/day',
    controllability: 'controllable',
    relationship_type: 'ASSOCIATION',
    direction: 'POSITIVE',
    score: 0.612345,
    score_name: 'coverage_sample_stability_adjusted_association',
    score_scale: '0..1 ranking index; not probability',
    score_components: { correlation: 0.8, coverage: 0.9, sample: 0.95, stability: 1 },
    raw_correlation: 0.8,
    adjusted_significance: null,
    sample_size: 40,
    missing_observations: 5,
    coverage_ratio: 0.88889,
    selected_lag_days: 2,
    lag_candidates_tested: 4,
    tested_lags: [{ lag_days: 0, correlation: 0.3 }, { lag_days: 2, correlation: 0.8 }],
    temporal_order: 'BEFORE',
    temporal_order_supported: true,
    stability_status: 'STABLE',
    stability_details: { full_window_correlation: 0.8, recent_window_correlation: 0.77 },
    seasonality_control: 'NONE',
    trend_control: 'FIRST_DIFFERENCE',
    eligibility_checks: { minimum_coverage: 0.6, threshold_passed: true },
    evidence_references: [{ source_id: 'sales_daily' }],
    limitations: ['No multiple-testing correction is applied.'],
    claim_boundary: 'Association only - not contribution or causation.',
    ...overrides,
  }
}

function analysis(overrides = {}) {
  return {
    status: 'ASSESSED',
    method: 'NATIVE_GRAIN_FIRST_DIFFERENCE_LAGGED_PEARSON_ASSOCIATION',
    target_kpi: 'orders',
    target_period: { start: '2023-01-01', end: '2023-04-01' },
    scope: { region: 'North' },
    candidate_count: 2,
    eligible_count: 1,
    ranked_count: 1,
    excluded_count: 1,
    hypotheses_tested: 8,
    windows_tested: 2,
    correction_method: null,
    limitations: ['No multiple-testing correction is applied; ranking is exploratory.'],
    ranked_drivers: [rankedDriver()],
    excluded_drivers: [{
      driver_id: 'stockout', source_id: 'sales_daily', reason_code: 'LOW_COVERAGE',
      reason: 'Pair coverage below minimum', sample_size: 12,
      failed_checks: ['minimum_coverage'], evidence_references: [],
    }],
    ...overrides,
  }
}

test('ranked order is deterministic by rank then driver identifier', () => {
  const first = rankedDriver({ rank: 1, driver_id: 'z-driver' })
  const second = rankedDriver({ rank: 2, driver_id: 'a-driver' })
  const model = driverAnalysisViewModel(analysis({ ranked_drivers: [second, first] }), 'CFO')
  assert.deepEqual(model.ranked.map(item => item.driver_id), ['z-driver', 'a-driver'])
})

test('score and raw correlation have separate labels and nulls never render as zero', () => {
  assert.equal(driverScoreLabel(0.612345), '0.612 / 1 ranking index')
  assert.equal(driverCorrelationLabel(0.8), '0.800')
  assert.equal(driverScoreLabel(null), 'Not scored')
  assert.equal(driverCorrelationLabel(null), 'Not estimated')
  assert.notEqual(driverScoreLabel(null), '0')
})

test('association boundary and temporal interpretation are explicit', () => {
  const model = driverAnalysisViewModel(analysis(), 'Marketing Manager')
  assert.equal(model.ranked[0].relationship_type, 'ASSOCIATION')
  assert.match(model.ranked[0].claim_boundary, /not contribution or causation/)
  assert.equal(driverTemporalLabel('BEFORE', true), 'Driver changes preceded KPI changes at the selected lag')
  assert.equal(driverTemporalLabel('COINCIDENT', false), 'Coincident changes; temporal precedence is not supported')
})

test('stable and sensitive states remain distinguishable', () => {
  const stable = driverAnalysisViewModel(analysis(), 'CFO').ranked[0]
  const sensitive = driverAnalysisViewModel(analysis({ ranked_drivers: [rankedDriver({ stability_status: 'SENSITIVE' })] }), 'CFO').ranked[0]
  assert.equal(stable.stability_status, 'STABLE')
  assert.equal(sensitive.stability_status, 'SENSITIVE')
  assert.notEqual(stable.stability_status, sensitive.stability_status)
})

test('exclusion codes have understandable labels and blocked/insufficient/no-candidate states abstain', () => {
  assert.equal(driverExclusionLabel('LOW_COVERAGE'), 'Coverage below the required minimum')
  assert.equal(driverAnalysisStatusLabel('BLOCKED'), 'Blocked by source contradiction')
  const blocked = driverAnalysisViewModel(analysis({ status: 'BLOCKED', ranked_drivers: [] }), 'CFO')
  const sparse = driverAnalysisViewModel(analysis({ status: 'INSUFFICIENT_EVIDENCE', ranked_drivers: [] }), 'CFO')
  const empty = driverAnalysisViewModel(analysis({ status: 'ASSESSED', ranked_drivers: [], excluded_drivers: [] }), 'CFO')
  assert.match(blocked.abstention, /Source contradiction blocks/)
  assert.match(sparse.abstention, /No driver met/)
  assert.match(empty.abstention, /No eligible driver was ranked/)
})

test('missingness is paired coverage, not an invented complete sample', () => {
  assert.equal(driverCoverageLabel(0.75, 10), '75.0% paired coverage · 10 missing observations')
  assert.equal(driverCoverageLabel(null, null), 'Coverage not established')
})

test('persona wording changes without changing ranked quantitative evidence', () => {
  const saved = analysis()
  const cfo = driverAnalysisViewModel(saved, 'CFO')
  const marketing = driverAnalysisViewModel(saved, 'Marketing Manager')
  assert.notEqual(cfo.personaFrame, marketing.personaFrame)
  assert.match(cfo.personaFrame, /non-monetary diagnostic signals/)
  assert.match(marketing.personaFrame, /controllable levers/)
  assert.deepEqual(cfo.ranked, marketing.ranked)
})

test('access denied suppresses the driver-analysis workspace', () => {
  assert.equal(driverAnalysisViewModel(analysis(), 'CFO', 'ACCESS_DENIED'), null)
})
