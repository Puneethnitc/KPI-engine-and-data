import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { juryRequirements, parseJuryResult, requirementPassed, scenarioRunId } from '../lib/jury-workflow.ts'
const scenario = { scenario_id: 'material-multi-driver', expected_broad_outcome: 'MATERIAL' }
test('parses matched scenario and run link', () => { const result = parseJuryResult(scenario, 200, { observed_broad_outcome: 'MATERIAL', expected_outcome_observed: true, engine_result: { run_id: 'run-1' } }); assert.equal(result.matched, true); assert.equal(result.runId, 'run-1') })
test('accepts governed denial without run leakage', () => { const denied = { scenario_id: 'unauthorized-scope', expected_broad_outcome: 'ACCESS_DENIED' }; const result = parseJuryResult(denied, 403, { detail: { observed_broad_outcome: 'ACCESS_DENIED', expected_outcome_observed: true } }); assert.equal(result.matched, true); assert.equal(result.accessDenied, true); assert.equal(result.runId, null); assert.equal(result.error, undefined) })
test('requirements require every mapped scenario', () => { const results = { a: { matched: true }, b: { matched: false } }; assert.equal(requirementPassed(['a'], results), true); assert.equal(requirementPassed(['a', 'b'], results), false); assert.equal(juryRequirements.length, 6) })
test('finds multi-KPI run id', () => assert.equal(scenarioRunId({ results: { orders: { run_id: 'run-orders' } } }), 'run-orders'))
test('page calls governed endpoints rather than hard-coding outcomes', () => { const source = fs.readFileSync(new URL('../app/jury/page.tsx', import.meta.url), 'utf8'); assert.match(source, /api\/demo-scenarios\/\$\{encodeURIComponent\(id\)\}\/execute/); assert.match(source, /parseJuryResult/); assert.doesNotMatch(source, /observed:\s*['"]MATERIAL['"]/) })
