import test from 'node:test'
import assert from 'node:assert/strict'
import { actionImpactRangeLabel } from '../lib/action-workspace.ts'

test('action proposal shows saved bounds and omits unsupported ranges', () => {
  assert.equal(actionImpactRangeLabel({ expected_impact_low: 0, expected_impact_high: 206.36, expected_impact_unit: 'count' }), '0 to 206.36 count')
  assert.equal(actionImpactRangeLabel({ expected_impact_low: null, expected_impact_high: 206.36 }), null)
  assert.equal(actionImpactRangeLabel(undefined), null)
})
