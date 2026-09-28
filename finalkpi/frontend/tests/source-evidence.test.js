import test from 'node:test'
import assert from 'node:assert/strict'
import {
  reconciliationTone, reconciliationWindowLabel, coverageTone, qualityTone, readinessTone,
  renderNullable, isFixtureIdentifier, fileIdentifierLabel,
  evidenceSuppressedForDenied, sourcesForDisplay,
} from '../lib/evidence-helpers.js'

test('Evidence presentation helpers', async (t) => {
  // ---- reconciliationTone ---------------------------------------------------
  await t.test('NOT_APPLICABLE is neutral', () => {
    assert.equal(reconciliationTone('NOT_APPLICABLE', false), 'neutral')
  })

  await t.test('NOT_AVAILABLE_FOR_PERIOD is limited', () => {
    assert.equal(reconciliationTone('NOT_AVAILABLE_FOR_PERIOD', false), 'limited')
  })

  await t.test('AGREED is good', () => {
    assert.equal(reconciliationTone('AGREED', false), 'good')
  })

  await t.test('DRIFT is warning', () => {
    assert.equal(reconciliationTone('DRIFT', false), 'warning')
  })

  await t.test('CONTRADICTED is warning', () => {
    assert.equal(reconciliationTone('CONTRADICTED', true), 'warning')
  })

  await t.test('blocking=true always returns warning regardless of status', () => {
    assert.equal(reconciliationTone('AGREED', true), 'warning')
  })

  await t.test('PENDING_CLOSE is neutral, like NOT_APPLICABLE', () => {
    assert.equal(reconciliationTone('PENDING_CLOSE', false), 'neutral')
  })

  // ---- reconciliationWindowLabel ---------------------------------------------
  await t.test('null details renders no window label', () => {
    assert.equal(reconciliationWindowLabel(null), null)
  })

  await t.test('missing comparison_window renders no window label', () => {
    assert.equal(reconciliationWindowLabel({}), null)
  })

  await t.test('closed comparison window is labelled closed', () => {
    assert.equal(
      reconciliationWindowLabel({
        comparison_window: { start: '2024-01-01', end: '2024-01-31' },
        finance_status: 'closed', finance_revision: 2,
      }),
      '2024-01-01 to 2024-01-31 (closed)',
    )
  })

  await t.test('provisional snapshot window shows its revision', () => {
    assert.equal(
      reconciliationWindowLabel({
        comparison_window: { start: '2024-05-01', end: '2024-05-09' },
        finance_status: 'provisional_mid_month', finance_revision: 1,
      }),
      '2024-05-01 to 2024-05-09 (provisional, revision 1)',
    )
  })

  // ---- coverageTone ---------------------------------------------------------
  await t.test('FULL coverage is good', () => {
    assert.equal(coverageTone('FULL'), 'good')
  })

  await t.test('PARTIAL coverage is limited', () => {
    assert.equal(coverageTone('PARTIAL'), 'limited')
  })

  await t.test('STALE coverage is limited', () => {
    assert.equal(coverageTone('STALE'), 'limited')
  })

  await t.test('EMPTY coverage is warning', () => {
    assert.equal(coverageTone('EMPTY'), 'warning')
  })

  await t.test('MISSING coverage is warning', () => {
    assert.equal(coverageTone('MISSING'), 'warning')
  })

  await t.test('NOT_LOADED coverage is neutral', () => {
    assert.equal(coverageTone('NOT_LOADED'), 'neutral')
  })

  // ---- qualityTone ----------------------------------------------------------
  await t.test('OK quality is good', () => {
    assert.equal(qualityTone('OK'), 'good')
  })

  await t.test('QUALITY_FAILED is warning', () => {
    assert.equal(qualityTone('QUALITY_FAILED'), 'warning')
  })

  await t.test('NOT_LOADED quality is neutral', () => {
    assert.equal(qualityTone('NOT_LOADED'), 'neutral')
  })

  // ---- readinessTone --------------------------------------------------------
  await t.test('READY readiness is good', () => {
    assert.equal(readinessTone('READY'), 'good')
  })

  await t.test('PARTIAL readiness is limited', () => {
    assert.equal(readinessTone('PARTIAL'), 'limited')
  })

  await t.test('STALE readiness is limited', () => {
    assert.equal(readinessTone('STALE'), 'limited')
  })

  await t.test('MISSING readiness is warning', () => {
    assert.equal(readinessTone('MISSING'), 'warning')
  })

  await t.test('QUALITY_FAILED readiness is warning', () => {
    assert.equal(readinessTone('QUALITY_FAILED'), 'warning')
  })

  // ---- renderNullable -------------------------------------------------------
  await t.test('null renders as em-dash', () => {
    assert.equal(renderNullable(null), '—')
  })

  await t.test('undefined renders as em-dash', () => {
    assert.equal(renderNullable(undefined), '—')
  })

  await t.test('zero is rendered (not treated as falsy)', () => {
    assert.equal(renderNullable(0), '0')
  })

  await t.test('formatter is applied to non-null values', () => {
    assert.equal(renderNullable(3.14, (v) => v.toFixed(1)), '3.1')
  })

  // ---- isFixtureIdentifier --------------------------------------------------
  await t.test('production filename is not a fixture', () => {
    assert.equal(isFixtureIdentifier('sales.csv'), false)
  })

  await t.test('demo_fixtures/ prefix marks a fixture', () => {
    assert.equal(isFixtureIdentifier('demo_fixtures/contradicted_july_2023/sales.csv'), true)
  })

  await t.test('null is not a fixture', () => {
    assert.equal(isFixtureIdentifier(null), false)
  })

  // ---- fileIdentifierLabel --------------------------------------------------
  await t.test('null identifier renders em-dash', () => {
    assert.equal(fileIdentifierLabel(null), '—')
  })

  await t.test('production file shows plain name', () => {
    assert.equal(fileIdentifierLabel('sales.csv'), 'sales.csv')
  })

  await t.test('fixture identifier has Fixture: prefix', () => {
    assert.equal(
      fileIdentifierLabel('demo_fixtures/contradicted_july_2023/sales.csv'),
      'Fixture: demo_fixtures/contradicted_july_2023/sales.csv'
    )
  })

  // ---- access-denied suppression -------------------------------------------
  await t.test('ACCESS_DENIED run suppresses evidence', () => {
    assert.equal(evidenceSuppressedForDenied({ verdict: 'ACCESS_DENIED' }), true)
  })

  await t.test('non-denied run does not suppress evidence', () => {
    assert.equal(evidenceSuppressedForDenied({ verdict: 'MATERIAL_CAUSE_UNVERIFIED' }), false)
  })

  await t.test('null run does not suppress evidence', () => {
    assert.equal(evidenceSuppressedForDenied(null), false)
  })

  // ---- sourcesForDisplay ----------------------------------------------------
  await t.test('ACCESS_DENIED returns empty sources (no data leak)', () => {
    const evidence = { sources: [{ source_id: 'sales_daily' }] }
    const run = { verdict: 'ACCESS_DENIED' }
    assert.deepEqual(sourcesForDisplay(evidence, run), [])
  })

  await t.test('authorized run returns source rows', () => {
    const evidence = { sources: [{ source_id: 'sales_daily' }, { source_id: 'marketing_weekly' }] }
    const run = { verdict: 'MATERIAL_CAUSE_UNVERIFIED' }
    assert.equal(sourcesForDisplay(evidence, run).length, 2)
  })

  await t.test('null evidence returns empty array', () => {
    assert.deepEqual(sourcesForDisplay(null, { verdict: 'READY' }), [])
  })
})
