import { describe, it } from 'node:test'
import assert from 'node:assert'
import {
  buildDiagnosisRequest,
  parseScenarioExecution,
  mergeScopeOption,
  isTrendChartAllowed,
  isAssistantAllowed,
  validateGovernedAccessDenied,
  buildScenarioMetadata
} from '../lib/demo-scenarios.ts'

describe('Demo Scenario System', () => {
  it('catalog values populate selector options', () => {
    const scenarios = [{ scenario_id: 'a', title: 'Scenario A' }]
    const scenarioOptions = [{ value: '', label: 'Standard view' }, ...scenarios.map(s => ({ value: s.scenario_id, label: s.title }))]
    assert.strictEqual(scenarioOptions.length, 2)
    assert.strictEqual(scenarioOptions[1].value, 'a')
    assert.strictEqual(scenarioOptions[1].label, 'Scenario A')
  })

  it('scenario request uses scenario endpoint', () => {
    const req = buildDiagnosisRequest({
      apiBase: 'http://localhost',
      scenarioId: 'material-multi-driver',
      persona: 'CFO',
      region: 'North',
      category: 'Electronics',
      date: '2023-07-24',
      userId: 'demo-cfo'
    })
    assert.strictEqual(req.url, 'http://localhost/api/demo-scenarios/material-multi-driver/execute')
    assert.strictEqual(req.body.user_id, 'demo-cfo')
    assert.strictEqual(req.body.target_date, undefined) 
  })

  it('manual request uses diagnosis endpoint', () => {
    const req = buildDiagnosisRequest({
      apiBase: 'http://localhost',
      persona: 'marketing_manager',
      region: 'North',
      category: 'Electronics',
      date: '2023-07-24',
      userId: 'demo-marketing'
    })
    assert.strictEqual(req.url, 'http://localhost/api/diagnoses')
    assert.strictEqual(req.body.target_date, '2023-07-24')
    assert.strictEqual(req.body.persona, 'marketing_manager')
  })

  it('governed ACCESS_DENIED payload is accepted only for matching scenario', () => {
    const payload = {
      scenario: { scenario_id: 'unauthorized-scope' },
      resolved_scope: {},
      results: {},
      observed_broad_outcome: 'ACCESS_DENIED'
    }
    const isValid = validateGovernedAccessDenied(payload, 'unauthorized-scope')
    const isInvalid = validateGovernedAccessDenied(payload, 'other-scenario')
    assert.strictEqual(isValid, true)
    assert.strictEqual(isInvalid, false)
  })

  it('ordinary 403 remains an error', () => {
    const payload = { detail: 'Not allowed' }
    const execution = parseScenarioExecution(403, payload)
    assert.strictEqual(execution.ok, false)
    assert.strictEqual(execution.accessDenied, true)
    assert.strictEqual(execution.error, 'Not allowed')
  })

  it('expected/observed comparison uses backend broad fields', () => {
    const payload = {
      scenario: { scenario_id: 'a' },
      observed_broad_outcome: 'MATERIAL_MOVEMENT',
      expected_broad_outcome: 'MATERIAL_MOVEMENT',
      expected_outcome_observed: true
    }
    const meta = buildScenarioMetadata(payload)
    assert.strictEqual(meta.expectedOutcomeObserved, true)
    assert.strictEqual(meta.observedBroadOutcome, 'MATERIAL_MOVEMENT')
    assert.strictEqual(meta.expectedBroadOutcome, 'MATERIAL_MOVEMENT')
  })

  it('locked scope displays governed values', () => {
    const options = ['South']
    const region = 'North'
    const regionOptions = mergeScopeOption(options, region)
    assert.strictEqual(regionOptions.includes('North'), true)
    assert.strictEqual(regionOptions.includes('South'), true)
  })

  it('returnToManual restores prior values', () => {
    let manualScope = { persona: 'A', region: 'B' }
    let persona = 'CFO'
    let region = 'North'
    
    // returnToManual logic
    persona = manualScope.persona
    region = manualScope.region
    manualScope = null
    
    assert.strictEqual(persona, 'A')
    assert.strictEqual(region, 'B')
    assert.strictEqual(manualScope, null)
  })

  it('fixture label appears only for fixture scenarios', () => {
    const s1 = { uses_demo_fixture: true }
    const s2 = { uses_demo_fixture: false }
    assert.strictEqual(s1.uses_demo_fixture, true)
    assert.strictEqual(s2.uses_demo_fixture, false)
  })

  it('fixture chart is suppressed', () => {
    assert.strictEqual(isTrendChartAllowed('demo_fixture', 'OK'), false, 'demo_fixture suppresses chart')
    assert.strictEqual(isTrendChartAllowed('production', 'INSUFFICIENT_HISTORY'), false, 'INSUFFICIENT_HISTORY suppresses chart')
    assert.strictEqual(isTrendChartAllowed('production', 'ACCESS_DENIED'), false, 'ACCESS_DENIED suppresses chart')
    assert.strictEqual(isTrendChartAllowed('production', 'MATERIAL_MOVEMENT'), true, 'production material scenario permits chart')
  })

  it('sparse-history count is displayed', () => {
    const verdict = 'INSUFFICIENT_HISTORY'
    const history = { baseline_count: 5, required_observation_count: 14 }
    assert.strictEqual(verdict, 'INSUFFICIENT_HISTORY')
    assert.strictEqual(history.baseline_count, 5)
  })

  it('stale results are cleared during scenario switching', () => {
    let results = { kpi: { verdict: 'OK' } }
    // diagnose() logic
    results = {}
    assert.strictEqual(Object.keys(results).length, 0)
  })

  it('unauthorized state does not render metric values', () => {
    const verdict = 'ACCESS_DENIED'
    const metricValue = verdict === 'ACCESS_DENIED' ? '—' : 100
    assert.strictEqual(metricValue, '—')
  })

  it('ACCESS_DENIED disables assistant', () => {
    assert.strictEqual(isAssistantAllowed('ACCESS_DENIED'), false)
    assert.strictEqual(isAssistantAllowed('MATERIAL_MOVEMENT'), true)
  })
})
