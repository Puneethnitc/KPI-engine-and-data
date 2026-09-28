import assert from 'node:assert/strict'
import test from 'node:test'
import { movementSelection, movementScopeOptions } from '../lib/movement-navigation.ts'
import { buildDiagnosisRequest } from '../lib/demo-scenarios.ts'

const options = { regions: ['North', 'South'], categories: ['Electronics', 'Home'], dates: ['2024-05-15', '2024-05-16'] }

test('click target replaces slice, date and KPI, including entitled ALL rollups', () => {
  const target = movementSelection({ kpi_id: 'orders', region: null, category: null, target_date: '2024-05-16' }, '2024-05-15', options, 'CFO')
  assert.deepEqual(target, { scenarioId: '', region: 'ALL', category: 'ALL', date: '2024-05-16', kpiId: 'orders' })
  const request = buildDiagnosisRequest({ apiBase: '/api/backend', scenarioId: '', persona: 'CFO', userId: 'demo-cfo', ...target })
  assert.deepEqual([request.body.region, request.body.category, request.body.scope], ['ALL', 'ALL', undefined]) // explicit ALL, not null (aggregate scope)
  assert.equal(request.body.target_date, '2024-05-16')
  assert.equal(movementSelection({ kpi_id: 'orders', region: 'South', category: 'Home', target_date: '2024-05-16' }, '2024-05-15', options, 'CFO')?.kpiId, 'orders')
})

test('unentitled ALL and unavailable calendar dates are not selectable', () => {
  assert.equal(movementScopeOptions(options.regions, 'region', 'regional_manager_north').includes('ALL'), false)
  assert.equal(movementSelection({ kpi_id: 'orders', region: null, category: 'Home' }, '2024-05-15', options, 'regional_manager_north'), null)
  assert.equal(movementSelection({ kpi_id: 'orders', region: 'North', category: 'Home', target_date: '2024-05-17' }, '2024-05-15', options, 'CFO'), null)
})
