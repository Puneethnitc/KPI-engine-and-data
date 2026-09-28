'use client'

import Link from 'next/link'
import { ArrowLeft, BookOpen, CheckCircle2, ShieldAlert, AlertTriangle, AlertCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../../components/app-shell'
import { contextHref, statusLabel } from '../../../lib/presentation'
import { contractViewerHref } from '../../../lib/semantic-contract'
import DriverAnalysisWorkspace from '../../../components/driver-analysis-workspace'
import ActionWorkspace from '../../../components/action-workspace'
import FeedbackCapture from '../../../components/feedback-capture'
import type { AuthorizedRunForFeedback } from '../../../lib/feedback-learning'
import type { DriverAnalysis } from '../../../lib/driver-analysis'
import type { ActionContract } from '../../../lib/action-workspace'
import ConfidenceWorkspace from '../../../components/confidence-workspace'
import type { ConfidenceProfile } from '../../../lib/confidence-profile'
import ProcessingTransparencyView from '../../../components/processing-transparency'
import type { ProcessingTransparency, RuntimeTelemetry } from '../../../lib/processing-transparency'

type Run = { run_id: string; kpi_id: string; target_date: string; as_of: string; verdict: string; narrative: string; persona: string; segment: { region: string; category: string }; movement_assessment?: { actual_value: number; expected_value: number; delta: number; is_material: boolean }; reconciliation_verdict?: { status: string }; decomposition?: { is_identity_held: boolean; volume_effect: number; price_effect: number; mix_effect: number }; driver_analysis?: DriverAnalysis | null; confidence_profile?: ConfidenceProfile | null; confidence?: { status: string; reasons?: string[] }; narrative_claims?: { text?: string; claim_type?: string }[]; decision_cards?: ActionContract[] }
type SavedRun = Run & { processing_transparency?: ProcessingTransparency | null; telemetry?: RuntimeTelemetry | null }

type SourceEntry = { source_id: string; display_name: string; source_role: string; file_identifier: string | null; native_grain: string; refresh_cadence: string | null; event_time_field: string; availability_time_field: string; requested_as_of: string | null; latest_event_time: string | null; latest_available_time: string | null; coverage_start: string | null; coverage_end: string | null; records_read: number | null; records_after_scope: number | null; coverage_status: string; quality_status: string; access_classification: string; authorized: boolean; transformations: string[]; }
type AlignmentEntry = { source_id: string; target_grain: string; calendar: string; aggregation: string; join_keys: string[]; availability_rule: string; period_completeness_rule: string; alignment_status: string; limitations: string[]; }
type ReconciliationEvidence = { status: string; applicable: boolean; primary_source: string | null; comparison_source: string | null; metric: string | null; unit: string | null; scope: Record<string, string> | null; primary_period: string | null; comparison_period: string | null; primary_value: number | null; comparison_value: number | null; absolute_gap: number | null; gap_percent: number | null; tolerance: number | null; comparison_basis: string | null; blocking: boolean; reason: string | null; quality_status: string | null; }
type LineageEntry = { claim: string; source_id: string; contract_version: string | null; query_identifier: string | null; row_or_period_reference: string | null; analytical_method: string | null; claim_type: string; access_classification: string; }
type SourceReadiness = { status: string; required_sources: string[]; available_sources: string[]; limitations: string[]; }
type EvidenceResponse = { run_id: string; kpi_id?: string; target_date?: string; as_of?: string; scope?: Record<string, string>; source_data_version?: string; contract_version?: string; source_mode?: 'production' | 'demo_fixture'; snapshot_status?: string; source_readiness: SourceReadiness; sources: SourceEntry[]; alignment: AlignmentEntry[]; reconciliation: ReconciliationEvidence; lineage: LineageEntry[]; narrative_claim_evidence?: unknown[]; limitations?: string[]; }

function titleCase(value?: string | null) {
  return value ? value.toLowerCase().replaceAll('_', ' ').replace(/(^|\s)\S/g, letter => letter.toUpperCase()) : 'Not assessed'
}

export default function DetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const [runId, setRunId] = useState('')
  const { persona, region, category, date, ready } = useDemoContext()
  const [run, setRun] = useState<SavedRun | null>(null)
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { params.then(value => setRunId(value.runId)) }, [params])

  useEffect(() => {
    if (!runId || !ready) return;
    const identity = identityForPersona(persona);
    Promise.all([
      fetch(`${API_BASE}/api/diagnoses/${runId}?user_id=${identity}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Investigation unavailable'))),
      fetch(`${API_BASE}/api/diagnoses/${runId}/evidence?user_id=${identity}`).then(response => response.ok ? response.json() : Promise.reject(new Error('Evidence unavailable')))
    ]).then(([payload, evidencePayload]) => {
      setRun(payload.result ?? payload);
      setEvidence(evidencePayload);
    }).catch(requestError => setError(requestError.message))
  }, [runId, persona, ready])

  if (error) return <AppShell active="Performance"><State><ShieldAlert />{error}</State></AppShell>
  if (!run || !evidence) return <AppShell active="Performance"><State>Loading investigation…</State></AppShell>

  const movement = run.movement_assessment
  const evidenceLimitations = evidence.limitations ?? []

  return <AppShell active="Performance" context={`${run.kpi_id} · ${run.target_date} · ${run.segment.region} · ${run.segment.category} · ${run.run_id}`}>
    <Link className="back-link" href={contextHref('/performance', { persona, region: run.segment.region, category: run.segment.category, date: run.target_date })}><ArrowLeft size={15} /> Back to investigations</Link>
    <div className="page-heading route-heading">
      <div>
        <span className="eyebrow">{run.kpi_id}</span>
        <h1>Investigation detail</h1>
        <p>{run.segment.region} · {run.segment.category} · {run.target_date} · {persona === 'CFO' ? 'Finance review' : 'Marketing review'}</p>
        <Link className="contract-inline-link" href={contractViewerHref(run.kpi_id, run.run_id)}>View contract snapshot used for this run</Link>
      </div>
      <span className={`status ${movement?.is_material ? 'warn' : 'ok'}`}>{statusLabel(run.verdict)}</span>
    </div>

    <section className="detail-grid">
      <article className="card detail-card">
        <span className="eyebrow">What changed</span>
        <h2>{movement?.actual_value.toLocaleString('en-IN')} <small>actual</small></h2>
        <p>Expected {movement?.expected_value.toLocaleString('en-IN')} · Delta {movement?.delta.toLocaleString('en-IN')}</p>
      </article>
      <article className="card detail-card">
        <span className="eyebrow">Materiality</span>
        <h2>{movement?.is_material ? 'Material movement' : 'Not material'}</h2>
        <p>Reconciliation: {statusLabel(run.reconciliation_verdict?.status)}</p>
      </article>
    </section>
    <ConfidenceWorkspace profile={run.confidence_profile} persona={persona} verdict={run.verdict} />
    <ProcessingTransparencyView
      transparency={run.processing_transparency}
      telemetry={run.telemetry}
      suppressRuntimeTelemetry={run.verdict === 'ACCESS_DENIED'}
    />

    <section className="detail-section">
      <span className="eyebrow">Evidence-bound narrative</span>
      <h2>{run.narrative}</h2>
      <p className="method-note">Observed movement is distinct from accounting contribution, diagnostic indicators, and observational support.</p>
    </section>

    <section className="detail-grid">
      <article className="card detail-card">
        <span className="eyebrow">Accounting contribution</span>
        <h2>{run.decomposition?.is_identity_held ? 'Identity reconciled' : 'Unavailable'}</h2>
        <p>{run.decomposition ? `Volume ${run.decomposition.volume_effect.toFixed(2)} · Rate/price ${run.decomposition.price_effect.toFixed(2)} · Mix ${run.decomposition.mix_effect.toFixed(2)}` : 'No exact bridge is available for this KPI.'}</p>
      </article>
    </section>
    <DriverAnalysisWorkspace analysis={run.driver_analysis} persona={persona} verdict={run.verdict} />
    {run.verdict !== 'ACCESS_DENIED' && <ActionWorkspace actions={run.decision_cards} persona={persona} verdict={run.verdict} />}

    {run.verdict !== 'ACCESS_DENIED' && (
      <section className="evidence-workspace">
        <div className="section-heading" style={{ marginTop: '32px', marginBottom: '16px' }}>
          <div>
            <h2>Source Evidence Workspace</h2>
            <p>Verification of data integration, alignment, and independent source reconciliation.</p>
            <small>
              {evidence.source_mode === 'demo_fixture' ? 'Simulated demonstration fixture' : 'Production sources'}
              {' · '}snapshot {evidence.snapshot_status ? titleCase(evidence.snapshot_status) : 'not captured'}
              {evidence.source_data_version ? ` · data version ${evidence.source_data_version.slice(0, 12)}` : ''}
              {evidence.contract_version ? ` · contract v${evidence.contract_version}` : ''}
            </small>
          </div>
        </div>

        {evidenceLimitations.length > 0 && (
          <div className="alert warning" style={{ marginBottom: '24px' }}>
            <AlertTriangle size={18} />
            <div>
              <strong>Evidence limitations</strong>
              <ul style={{ margin: '8px 0 0', paddingLeft: '20px' }}>
                {evidenceLimitations.map((limit: string, idx: number) => (
                  <li key={idx}>{limit}</li>
                ))}
              </ul>
            </div>
          </div>
        )}

        <div className="card detail-card" style={{ marginBottom: '24px' }}>
          <span className="eyebrow">Source inventory & readiness</span>
          <div style={{ overflowX: 'auto', marginTop: '16px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid var(--border)' }}>
                  <th style={{ padding: '8px' }}>Source</th>
                  <th style={{ padding: '8px' }}>Role</th>
                  <th style={{ padding: '8px' }}>File Identifier</th>
                  <th style={{ padding: '8px' }}>Grain</th>
                  <th style={{ padding: '8px' }}>Cadence</th>
                  <th style={{ padding: '8px' }}>Latest Event</th>
                  <th style={{ padding: '8px' }}>Available At</th>
                  <th style={{ padding: '8px' }}>Coverage</th>
                  <th style={{ padding: '8px' }}>Quality</th>
                  <th style={{ padding: '8px' }}>Access</th>
                </tr>
              </thead>
              <tbody>
                {evidence.sources?.map((s) => (
                  <tr key={s.source_id} style={{ borderBottom: '1px solid var(--border)' }}>
                    <td style={{ padding: '8px' }}><strong>{s.display_name}</strong></td>
                    <td style={{ padding: '8px' }}>{s.source_role}</td>
                    <td style={{ padding: '8px', wordBreak: 'break-all' }}>
                      {s.file_identifier ? (s.file_identifier.startsWith('demo_fixtures') ? <span style={{ color: 'var(--brand)' }}>Fixture: {s.file_identifier}</span> : s.file_identifier) : '—'}
                    </td>
                    <td style={{ padding: '8px' }}>{s.native_grain}</td>
                    <td style={{ padding: '8px' }}>{s.refresh_cadence}</td>
                    <td style={{ padding: '8px' }}>{s.latest_event_time ?? '—'}</td>
                    <td style={{ padding: '8px' }}>{s.latest_available_time ?? '—'}</td>
                    <td style={{ padding: '8px' }}>
                      <span className={`evidence-pill ${s.coverage_status === 'FULL' ? 'good' : s.coverage_status === 'PARTIAL' ? 'limited' : s.coverage_status === 'EMPTY' ? 'warning' : 'neutral'}`}>{s.coverage_status}</span>
                    </td>
                    <td style={{ padding: '8px' }}>
                      <span className={`evidence-pill ${s.quality_status === 'OK' ? 'good' : s.quality_status === 'QUALITY_FAILED' ? 'warning' : 'neutral'}`}>{s.quality_status}</span>
                    </td>
                    <td style={{ padding: '8px' }}>{s.access_classification}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="detail-grid" style={{ marginBottom: '24px' }}>
          <div className="card detail-card">
            <span className="eyebrow">Data alignment</span>
            {evidence.alignment?.map((a) => (
              <div key={a.source_id} style={{ marginTop: '12px', paddingBottom: '12px', borderBottom: '1px solid var(--border)' }}>
                <strong>{a.source_id}</strong>
                <p style={{ margin: '4px 0', fontSize: '13px' }}><strong>Target grain:</strong> {a.target_grain}</p>
                <p style={{ margin: '4px 0', fontSize: '13px' }}><strong>Calendar:</strong> {a.calendar}</p>
                <p style={{ margin: '4px 0', fontSize: '13px' }}><strong>Aggregation:</strong> {a.aggregation}</p>
                <p style={{ margin: '4px 0', fontSize: '13px' }}><strong>Keys:</strong> {a.join_keys.join(', ')}</p>
                <p style={{ margin: '4px 0', fontSize: '13px' }}><strong>Rule:</strong> {a.period_completeness_rule}</p>
              </div>
            ))}
          </div>

          <div className="card detail-card">
            <span className="eyebrow">Independent reconciliation</span>
            {evidence.reconciliation && (
              <div style={{ marginTop: '12px' }}>
                <span className={`evidence-pill ${
                  evidence.reconciliation.blocking ? 'warning' :
                  evidence.reconciliation.status === 'AGREED' ? 'good' :
                  evidence.reconciliation.status === 'DRIFT' ? 'warning' :
                  evidence.reconciliation.status === 'NOT_APPLICABLE' ? 'neutral' : 'limited'
                }`} style={{ marginBottom: '12px', display: 'inline-block' }}>
                  {titleCase(evidence.reconciliation.status)}
                </span>
                <p style={{ fontSize: '13px', margin: '0 0 12px 0' }}>{evidence.reconciliation.reason}</p>

                {evidence.reconciliation.applicable && (
                  <div style={{ background: 'var(--background)', padding: '12px', borderRadius: '4px', fontSize: '13px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span><strong>Metric:</strong> {evidence.reconciliation.metric}</span>
                      <span><strong>Unit:</strong> {evidence.reconciliation.unit}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                      <span><strong>{evidence.reconciliation.primary_source}:</strong> {evidence.reconciliation.primary_value?.toLocaleString('en-IN') ?? '—'}</span>
                      <span><strong>{evidence.reconciliation.comparison_source}:</strong> {evidence.reconciliation.comparison_value?.toLocaleString('en-IN') ?? '—'}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
                      <span><strong>Difference:</strong> {evidence.reconciliation.absolute_gap?.toLocaleString('en-IN') ?? '—'} ({evidence.reconciliation.gap_percent?.toFixed(2) ?? '—'}%)</span>
                      <span><strong>Tolerance:</strong> {evidence.reconciliation.tolerance}%</span>
                    </div>
                    <p style={{ margin: '8px 0 0 0', color: 'var(--muted)' }}>
                      <strong>Basis:</strong> {evidence.reconciliation.comparison_basis} · {evidence.reconciliation.blocking ? 'Blocking' : 'Non-blocking'}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <section className="card detail-card">
          <span className="eyebrow"><BookOpen size={14} /> Evidence lineage</span>
          <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {evidence.lineage?.slice(0, 8).map((item, index) => (
              <div className="evidence-row" key={`${item.source_id}-${index}`} style={{ display: 'flex', gap: '12px' }}>
                <CheckCircle2 size={15} style={{ flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <strong>{item.source_id}</strong>
                  <p style={{ margin: '4px 0' }}>{item.claim}</p>
                  <p style={{ margin: '0', fontSize: '12px', color: 'var(--muted)' }}>{item.claim_type} · ref {item.row_or_period_reference ?? '—'}</p>
                  <small style={{ display: 'block', marginTop: '4px', color: 'var(--muted)' }}>{item.analytical_method ?? '—'} · access {item.access_classification}</small>
                </div>
              </div>
            ))}
            {(!evidence.lineage || evidence.lineage.length === 0) && (
              <p>No explicit evidence lineage attached to this claim.</p>
            )}
          </div>
        </section>
      </section>
    )}

    <section className="card detail-card" style={{ marginTop: '24px' }}>
      <span className="eyebrow">Recommended next check</span>
      {run.decision_cards?.length ? run.decision_cards.map((card, index) => <p key={index}><strong>{card.owner}:</strong> {card.recommendation} <small>Expected impact: {card.expected_impact == null ? 'not estimated' : card.expected_impact}</small></p>) : <p>The engine abstains until more evidence is available.</p>}
    </section>

    {run.verdict !== 'ACCESS_DENIED' && <FeedbackCapture run={run as SavedRun & AuthorizedRunForFeedback} userId={identityForPersona(persona)} reviewer={persona === 'CFO'} />}
  </AppShell>
}
