import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import {
  driverAnalysisStatusLabel,
  driverAnalysisViewModel,
  driverContributionLabel,
  driverCoverageLabel,
  driverExclusionLabel,
  driverExplainedShareLabel,
  driverTemporalLabel,
} from '../lib/driver-analysis.ts'

function rankedDriver(overrides = {}) {
  return {
    rank: 1,
    driver_id: 'stock_availability',
    display_name: 'Stock availability',
    source_id: 'sales_daily',
    source_grain: 'daily',
    aggregation: 'mean',
    driver_unit: 'share_in_stock',
    controllability: 'controllable',
    relationship_type: 'ATTRIBUTION',
    direction: 'POSITIVE',
    claim_type: 'ATTRIBUTED_DRIVER',
    method: 'JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT',
    beta: 0.4564,
    beta_ci: [0.2, 0.7],
    lag_days: 0,
    driver_change: -0.85,
    driver_change_z: -4.2,
    contribution: -27.49,
    contribution_interval: [-40.1, -15.2],
    explained_share: 1.603,
    p_value: 0.001,
    p_value_adj: 0.004,
    sample_size: 40,
    coverage_ratio: 0.88889,
    selected_lag_days: 0,
    lag_candidates_tested: 4,
    tested_lags: [{ lag_days: 0, sample_size: 40, out_of_sample_r2: 0.6, in_sample_r2: 0.7, eligible: true }],
    temporal_order: 'BEFORE',
    temporal_order_supported: true,
    direction_consistent: true,
    expected_direction: 'positive',
    stability_status: 'STABLE',
    stability_details: { first_half_beta: 0.4, second_half_beta: 0.5 },
    moved: true,
    offsetting: false,
    grain_adjusted: false,
    collinearity_warning: false,
    target_period_available: true,
    limitations: ['No multiple-testing correction is applied.'],
    claim_boundary: 'Statistical attribution of observed movement; causal status is shown separately.',
    evidence_references: [{ source_id: 'sales_daily' }],
    ...overrides,
  }
}

function analysis(overrides = {}) {
  return {
    status: 'ASSESSED',
    method: 'JOINT_ROBUST_REGRESSION_EXPLAINED_MOVEMENT',
    target_kpi: 'orders',
    target_period: { start: '2023-01-01', end: '2023-04-01' },
    scope: { region: 'North' },
    delta_kpi: -17.15,
    residual: 0.73,
    residual_share: -0.0426,
    candidate_count: 2,
    ranked_count: 1,
    moved_count: 1,
    offsetting_count: 0,
    excluded_count: 1,
    hypotheses_tested: 8,
    correction_method: 'benjamini_hochberg',
    collinearity_warning: false,
    limitations: ['No multiple-testing correction beyond Benjamini-Hochberg is applied.'],
    ranked_drivers: [rankedDriver()],
    excluded_drivers: [{
      driver_id: 'checkout_latency', source_id: 'sales_daily', reason_code: 'DID_NOT_MOVE',
      reason: 'Driver moved |z|=0.3, below the 1.5 threshold', sample_size: 12,
      failed_checks: ['driver_moved'], evidence_references: [],
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

test('contribution and explained-share have separate labels and nulls never render as zero', () => {
  assert.equal(driverContributionLabel(-27.49), '-27.49')
  assert.equal(driverExplainedShareLabel(1.603), '160%')
  assert.equal(driverContributionLabel(null), 'Not estimated')
  assert.equal(driverExplainedShareLabel(null), 'Not estimated')
  assert.notEqual(driverContributionLabel(null), '0')
})

test('attribution boundary and temporal interpretation are explicit', () => {
  const model = driverAnalysisViewModel(analysis(), 'Marketing Manager')
  assert.equal(model.ranked[0].relationship_type, 'ATTRIBUTION')
  assert.match(model.ranked[0].claim_boundary, /Statistical attribution/)
  assert.equal(driverTemporalLabel('BEFORE', true), 'Driver changes preceded KPI changes at the selected lag')
  assert.equal(driverTemporalLabel('COINCIDENT', false), 'Coincident changes; temporal precedence is not supported')
})

test('a moved offsetting driver is separated from the drivers that explain the movement', () => {
  const model = driverAnalysisViewModel(analysis({
    ranked_drivers: [
      rankedDriver({ driver_id: 'A', offsetting: false, contribution: 20 }),
      rankedDriver({ driver_id: 'B', offsetting: true, contribution: -5 }),
    ],
  }), 'CFO')
  assert.deepEqual(model.ranked.map(item => item.driver_id), ['A'])
  assert.deepEqual(model.offsetting.map(item => item.driver_id), ['B'])
})

test('a driver that did not move is listed separately from a hard exclusion', () => {
  const model = driverAnalysisViewModel(analysis({
    excluded_drivers: [
      { driver_id: 'quiet_driver', source_id: 'sales_daily', reason_code: 'DID_NOT_MOVE', reason: 'did not move', sample_size: 10, failed_checks: [], evidence_references: [] },
      { driver_id: 'unavailable_driver', source_id: 'sales_daily', reason_code: 'SOURCE_UNAVAILABLE', reason: 'unavailable', sample_size: 0, failed_checks: [], evidence_references: [] },
    ],
  }), 'CFO')
  assert.deepEqual(model.didNotMove.map(item => item.driver_id), ['quiet_driver'])
  assert.deepEqual(model.excluded.map(item => item.driver_id), ['unavailable_driver'])
})

test('a non-material movement does not present drivers as explanations', () => {
  const model = driverAnalysisViewModel(analysis({ status: 'EXPLORATORY_NON_MATERIAL' }), 'CFO')
  assert.deepEqual(model.ranked, [])
  assert.match(model.abstention, /not presented as explanations/)
})

test('stable and sensitive states remain distinguishable', () => {
  const stable = driverAnalysisViewModel(analysis(), 'CFO').ranked[0]
  const sensitive = driverAnalysisViewModel(analysis({ ranked_drivers: [rankedDriver({ stability_status: 'SENSITIVE' })] }), 'CFO').ranked[0]
  assert.equal(stable.stability_status, 'STABLE')
  assert.equal(sensitive.stability_status, 'SENSITIVE')
  assert.notEqual(stable.stability_status, sensitive.stability_status)
})

test('exclusion codes have understandable labels and blocked/insufficient/no-candidate states abstain', () => {
  assert.equal(driverExclusionLabel('DID_NOT_MOVE'), 'Driver did not move enough to explain any part of the change')
  assert.equal(driverAnalysisStatusLabel('BLOCKED'), 'Blocked by source contradiction')
  const blocked = driverAnalysisViewModel(analysis({ status: 'BLOCKED', ranked_drivers: [] }), 'CFO')
  const sparse = driverAnalysisViewModel(analysis({ status: 'INSUFFICIENT_EVIDENCE', ranked_drivers: [] }), 'CFO')
  const empty = driverAnalysisViewModel(analysis({ status: 'ASSESSED', ranked_drivers: [], excluded_drivers: [] }), 'CFO')
  assert.match(blocked.abstention, /Source contradiction blocks/)
  assert.match(sparse.abstention, /No driver met/)
  assert.match(empty.abstention, /No driver explained this movement/)
})

test('coverage label reports the joint model sample, not an invented complete sample', () => {
  assert.equal(driverCoverageLabel(0.75, 10), '75.0% joint-model coverage · n=10')
  assert.equal(driverCoverageLabel(null, null), 'Coverage not established')
})

test('persona wording changes without changing ranked quantitative evidence', () => {
  const saved = analysis()
  const cfo = driverAnalysisViewModel(saved, 'CFO')
  const marketing = driverAnalysisViewModel(saved, 'Marketing Manager')
  assert.notEqual(cfo.personaFrame, marketing.personaFrame)
  assert.match(cfo.personaFrame, /statistical estimates of what moved/)
  assert.match(marketing.personaFrame, /controllable levers/)
  assert.deepEqual(cfo.ranked, marketing.ranked)
})

test('access denied suppresses the driver-analysis workspace', () => {
  assert.equal(driverAnalysisViewModel(analysis(), 'CFO', 'ACCESS_DENIED'), null)
})

test('overview page resolves pre-rename driver ids to a friendly label (Stage 1 follow-up)', () => {
  // Mirrors kpi_engine/contracts/registry.py's LEGACY_DRIVER_IDS: a saved run
  // computed before the driver rename still carries the old id, and the
  // "What explains the change" card must still show a friendly label for it
  // rather than falling back to the raw id's title-cased text.
  const overview = fs.readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8')
  assert.match(overview, /ad_spend_drop:\s*'marketing_spend'/)
  assert.match(overview, /checkout_latency_spike:\s*'checkout_latency'/)
  assert.match(overview, /competitor_price_cut:\s*'competitor_price_index'/)
  assert.match(overview, /stockout:\s*'stock_availability'/)
  assert.match(overview, /driverLabel\(candidate\.driver_id\)/)
})
