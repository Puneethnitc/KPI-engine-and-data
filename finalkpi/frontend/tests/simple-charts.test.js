import test from 'node:test'
import assert from 'node:assert/strict'
import { driverChartPlan, percentChange, kpiChangeBars, sortedContributions, indexTo100 } from '../lib/simple-charts.ts'

test('percentChange compares actual with expected', () => {
  assert.equal(percentChange(90, 100), -10)
  assert.equal(percentChange(120, 100), 20)
  assert.equal(percentChange(5, 0), null)
  assert.equal(percentChange(null, 100), null)
})

test('kpiChangeBars keeps funnel order and skips missing KPIs', () => {
  const bars = kpiChangeBars({ net_sales_revenue: { actual_value: 80, expected_value: 100 }, traffic_total: { actual_value: 110, expected_value: 100 }, orders: null })
  assert.deepEqual(bars.map(b => b.label), ['Traffic', 'Revenue'])
  assert.equal(bars[1].value, -20)
})

test('pie is used when all shares are non-negative and total at most 100%', () => {
  const plan = driverChartPlan([{ label: 'A', share: 0.5 }, { label: 'B', share: 0.2 }], 0.1)
  assert.equal(plan.mode, 'pie')
  assert.deepEqual(plan.slices.map(s => s.kind), ['driver', 'driver', 'other', 'unexplained'])
  assert.ok(Math.abs(plan.slices.reduce((t, s) => t + s.share, 0) - 1) < 1e-9)
})

test('a share above 100% or a negative share falls back to bars', () => {
  assert.equal(driverChartPlan([{ label: 'A', share: 1.3 }], 0).mode, 'bars')
  assert.equal(driverChartPlan([{ label: 'A', share: 0.9 }, { label: 'B', share: -0.2 }], 0.1).mode, 'bars')
  assert.equal(driverChartPlan([{ label: 'A', share: 0.6 }, { label: 'B', share: 0.5 }], null).mode, 'bars')
  assert.equal(driverChartPlan([{ label: 'A', share: 0.4 }], -0.1).mode, 'bars')
})

test('no shares means no chart', () => {
  assert.equal(driverChartPlan([{ label: 'A', share: null }], null).mode, 'none')
})

test('contributions sort by size and indexing starts at 100', () => {
  assert.deepEqual(sortedContributions([{ label: 'a', value: -1 }, { label: 'b', value: 5 }, { label: 'c', value: null }]).map(i => i.label), ['b', 'a'])
  assert.deepEqual(indexTo100([null, 50, 100]), [null, 100, 200])
})
