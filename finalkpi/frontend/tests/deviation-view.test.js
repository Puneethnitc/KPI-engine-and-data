import test from 'node:test'
import assert from 'node:assert/strict'
import { deviationView } from '../lib/deviation-view.ts'

test('positive deviation extends right of expected and exposes detector bands', () => {
  const view = deviationView(114.6, 100, 0.05, 2.7, 3)
  assert.ok(Math.abs(view.percent - 14.6) < 0.001)
  assert.equal(view.barLeft, 50)
  assert.ok(view.barWidth > 0)
  assert.ok(view.normalWidth > 0)
  assert.ok(view.alertWidth > view.normalWidth)
})

test('negative deviation extends left of expected', () => {
  const view = deviationView(85, 100)
  assert.equal(view.percent, -15)
  assert.ok(view.barLeft < 50)
  assert.ok(view.barWidth > 0)
})

test('equal actual and expected produce a zero-width bar', () => {
  const view = deviationView(100, 100)
  assert.equal(view.percent, 0)
  assert.equal(view.barWidth, 0)
})

test('zero or missing expected values have no percent deviation', () => {
  assert.equal(deviationView(100, 0).percent, null)
  assert.equal(deviationView(100, null).percent, null)
})
