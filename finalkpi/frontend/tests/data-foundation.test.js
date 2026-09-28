import test from 'node:test'
import assert from 'node:assert/strict'
import { sourceStatus, reconciliationStatus, reconciliationMode } from '../lib/data-foundation.ts'

test('source status labels and role restriction meanings', () => {
  for (const status of ['FULL', 'PARTIAL', 'EMPTY', 'NOT_LOADED', 'RESTRICTED']) {
    assert.equal(sourceStatus(status, 'finance_monthly').label, status)
  }
  assert.match(sourceStatus('RESTRICTED', 'finance_monthly').meaning, /used in the analysis, hidden for your role/)
  assert.match(sourceStatus('PARTIAL', 'marketing_weekly').meaning, /not published yet/)
})

test('reconciliation labels and modes', () => {
  for (const status of ['AGREED', 'PENDING_CLOSE', 'DRIFT', 'CONTRADICTED']) {
    assert.equal(reconciliationStatus(status).label, status)
  }
  assert.equal(reconciliationMode('closed_month'), 'Closed month')
  assert.equal(reconciliationMode('month_to_date_snapshot'), 'Month-to-date snapshot')
})
