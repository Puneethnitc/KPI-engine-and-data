import test from 'node:test'
import assert from 'node:assert/strict'
import { formatKpiValue, waterfallScale } from '../lib/driver-waterfall.ts'
import { exclusionReason, driverRows } from '../lib/driver-analysis-overview.ts'

test('waterfall carries each contribution from the prior subtotal and spans small changes', () => {
  const model = waterfallScale(100, 105, [{ label: 'A', value: 7 }, { label: 'B', value: -3, offsetting: true }], 1)
  assert.equal(model.bars[1].start, 100)
  assert.equal(model.bars[1].end, 107)
  assert.equal(model.bars[2].kind, 'offsetting')
  assert.equal(model.bars[3].end, 105)
  assert.equal(model.reconciliationGap, 0)
  assert.ok(model.max > 107 && model.min < 100)
  assert.equal(waterfallScale(null, 5, [], 0), null)
})

test('unit-aware labels preserve visible nonzero values', () => {
  assert.equal(formatKpiValue(0.0123, 'conversion_rate', true), '+1.2 pp')
  assert.equal(formatKpiValue(-0.0123, 'conversion_rate', true), '−1.2 pp')
  assert.equal(formatKpiValue(1234.5, 'INR', true), '+₹1,234.50')
  assert.equal(formatKpiValue(2.5, 'count', true), '+2.5')
  assert.equal(formatKpiValue(0.001, 'count', true), '+0.001')
  assert.equal(formatKpiValue(0.01, 'count', true), '+0.010')
  assert.equal(formatKpiValue(0.000000001, 'count', true), '+1.00e-9')
  assert.equal(formatKpiValue(0, 'count', true), '0.0')
})

test('exclusion reasons are plain and unknown codes remain readable', () => {
  assert.equal(exclusionReason('DID_NOT_MOVE'), "Didn't change enough on this date")
  assert.equal(exclusionReason('SOURCE_UNAVAILABLE'), "Data for this date isn't published yet")
  assert.equal(exclusionReason('BELOW_THRESHOLD'), 'Too weak a relationship')
  assert.equal(exclusionReason('INSUFFICIENT_HISTORY'), 'Not enough history')
  assert.equal(exclusionReason('NEW_CODE'), 'New code')
})

test('older runs without confidence or diagnostics still produce ordered rows', () => {
  const model = driverRows({ ranked_drivers: [{ driver_id: 'stock', rank: 1, contribution: -2 }], excluded_drivers: [{ driver_id: 'weather', reason_code: 'DID_NOT_MOVE' }] }, null)
  assert.equal(model.main, null)
  assert.equal(model.rows.length, 2)
})
