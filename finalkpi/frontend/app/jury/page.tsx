'use client'
import Link from 'next/link'
import { CheckCircle2, Circle, ExternalLink, Play, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import AppShell, { API_BASE, useDemoContext } from '../../components/app-shell'
import { contextHref } from '../../lib/presentation'
import { juryRequirements, parseJuryResult, requirementPassed, type JuryScenarioResult } from '../../lib/jury-workflow'

export default function JuryPage() {
  const demo = useDemoContext()
  const [results, setResults] = useState<Record<string, JuryScenarioResult>>({})
  const [running, setRunning] = useState<string | null>(null)
  async function runScenario(id: string) {
    const scenario = demo.scenarios.find(item => item.scenario_id === id); if (!scenario) return
    setRunning(id)
    try {
      const response = await fetch(`${API_BASE}/api/demo-scenarios/${encodeURIComponent(id)}/execute`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: scenario.user_id }) })
      const payload = await response.json(); setResults(current => ({ ...current, [id]: parseJuryResult(scenario, response.status, payload) }))
    } catch { setResults(current => ({ ...current, [id]: { scenarioId: id, expected: scenario.expected_broad_outcome, observed: 'ERROR', matched: false, runId: null, accessDenied: false, error: 'Backend unavailable' } })) }
    finally { setRunning(null) }
  }
  async function runAll() { for (const scenario of demo.scenarios) await runScenario(scenario.scenario_id) }
  const completed = Object.values(results).filter(item => item.matched).length
  return <AppShell active="Jury Mode" context="governed end-to-end demonstration">
    <div className="page-heading route-heading"><div><span className="eyebrow">Problem 11 · jury workflow</span><h1>Guided prototype walkthrough</h1><p>Run governed scenarios, verify expected outcomes, then inspect evidence produced by the real engine.</p></div><button className="run-button" disabled={Boolean(running) || !demo.scenarios.length} onClick={() => void runAll()}><Play size={14} /> {running ? 'Running…' : 'Run all scenarios'}</button></div>
    <section className="card jury-readiness"><div><span className="eyebrow">Live readiness</span><h2>{completed} of {demo.scenarios.length} scenarios verified</h2><p>Passing means the broad outcome matched its governed expectation—not proven real-world accuracy.</p></div><div className="jury-progress" aria-label={`${completed} of ${demo.scenarios.length} scenarios verified`}><span style={{ width: `${demo.scenarios.length ? completed / demo.scenarios.length * 100 : 0}%` }} /></div></section>
    <section className="jury-requirements"><div className="section-heading"><div><span className="eyebrow">Minimum requirements</span><h2>Demonstration checklist</h2></div></div><div className="jury-check-grid">{juryRequirements.map(([id, label, ids]) => { const passed = requirementPassed(ids, results); return <article className="jury-check" key={id}>{passed ? <CheckCircle2 className="jury-pass" size={17} /> : <Circle size={17} />}<div><strong>{label}</strong><small>{ids.join(' · ')}</small></div></article> })}</div><p className="jury-note">Inspect persona narratives, contracts, lineage, actions, feedback learning, processing methods, runtime economics and auditability in the linked workspaces.</p></section>
    <section className="jury-scenario-list">{demo.scenarios.map((scenario, index) => { const result = results[scenario.scenario_id]; return <article className="card jury-scenario" key={scenario.scenario_id}><div className="jury-scenario-number">{String(index + 1).padStart(2, '0')}</div><div className="jury-scenario-main"><div className="jury-scenario-heading"><div><span className="eyebrow">{scenario.demonstration_category}</span><h2>{scenario.title}</h2></div>{result && <span className={`status ${result.matched ? 'ok' : 'warn'}`}>{result.matched ? 'Matched' : 'Needs review'}</span>}</div><p>{scenario.purpose}</p><div className="jury-scope"><span>{scenario.persona}</span><span>{scenario.region} / {scenario.category}</span><span>{scenario.target_date}</span><span>{scenario.source_mode === 'demo_fixture' ? 'Labelled fixture' : 'Production data'}</span></div><div className="jury-outcome"><span>Expected <strong>{scenario.expected_broad_outcome}</strong></span><span>Observed <strong>{result?.observed ?? 'Not run'}</strong></span></div>{result?.error && <p className="jury-error">{result.error}</p>}<div className="jury-actions"><button className="action-ask" disabled={Boolean(running)} onClick={() => void runScenario(scenario.scenario_id)}>{running === scenario.scenario_id ? 'Running…' : result ? 'Run again' : 'Run scenario'}</button>{result?.runId && <Link className="contract-inline-link" href={contextHref(`/performance/${result.runId}`, { persona: scenario.persona, region: scenario.region, category: scenario.category, date: scenario.target_date })}>Open evidence workspace <ExternalLink size={12} /></Link>}{result?.accessDenied && <span className="jury-security"><ShieldAlert size={13} /> Access denied without business-data leakage</span>}</div></div></article> })}</section>
    <section className="card jury-finish"><span className="eyebrow">Reviewer route</span><h2>Finish the evidence review</h2><div className="jury-links"><Link href={contextHref('/kpis', demo)}>Semantic contracts</Link><Link href={contextHref('/performance', demo)}>Investigations</Link><Link href={contextHref('/insights', demo)}>Feedback and learning</Link><Link href={contextHref('/', demo)}>Persona narrative</Link></div><p>For each saved run, verify freshness and lineage, analytical method, contribution, confidence, action ownership, LLM boundaries and runtime cost.</p></section>
  </AppShell>
}
