import {
  driverAnalysisViewModel,
  driverCoverageLabel,
  driverCorrelationLabel,
  driverExclusionLabel,
  driverScoreLabel,
  driverTemporalLabel,
  type DriverAnalysis,
} from '../lib/driver-analysis'

export default function DriverAnalysisWorkspace({
  analysis,
  persona,
  verdict,
}: {
  analysis?: DriverAnalysis | null
  persona: string
  verdict?: string | null
}) {
  if (verdict === 'ACCESS_DENIED') return null
  if (!analysis) return <article className="card driver-card">
    <div className="card-heading"><div><span className="eyebrow">Driver evidence</span><h3>Analysis not saved</h3></div></div>
    <p>No driver-analysis snapshot was saved for this run. Historical rankings are not recomputed from current data.</p>
  </article>

  const model = driverAnalysisViewModel(analysis, persona, verdict)
  if (!model) return null

  return <article className="card driver-card" aria-label="Driver analysis evidence">
    <div className="card-heading">
      <div><span className="eyebrow">Driver evidence</span><h3>Ranked associations</h3></div>
      <span className={`evidence-pill ${analysis.status === 'BLOCKED' ? 'warning' : model.ranked.length ? 'good' : 'limited'}`}>{model.statusLabel}</span>
    </div>
    <p className="driver-persona-frame">{model.personaFrame}</p>
    <p className="driver-boundary">Association only - not contribution or causation.</p>
    <p className="driver-method-line"><strong>Method:</strong> {analysis.method.replaceAll('_', ' ').toLowerCase()} · target {analysis.target_kpi} · {String(analysis.target_period.start ?? 'period start unavailable')} to {String(analysis.target_period.end ?? 'period end unavailable')} · {analysis.candidate_count} candidates · {analysis.hypotheses_tested} lag hypotheses · {analysis.windows_tested} window checks</p>

    {model.abstention && <div className={`driver-abstention ${analysis.status === 'BLOCKED' ? 'warning' : ''}`} role="status">{model.abstention}</div>}
    {model.ranked.length > 0 && <div className="driver-evidence-list">
      {model.ranked.map(driver => <section className="driver-evidence-item" key={driver.driver_id}>
        <div className="driver-evidence-heading">
          <div><span className="driver-rank">#{driver.rank}</span><strong>{driver.display_name}</strong><small>{driver.controllability === 'controllable' ? 'Controllable lever' : 'Contextual indicator'} · {driver.source_id} · {driver.source_grain} · {driver.aggregation} · {driver.driver_unit ?? 'unit not specified'}</small></div>
          <span className={`driver-stability ${driver.stability_status.toLowerCase()}`}>{driver.stability_status}</span>
        </div>
        <div className="driver-metrics">
          <span><small>Ranking score</small><strong>{driverScoreLabel(driver.score)}</strong></span>
          <span><small>Raw correlation</small><strong>{driverCorrelationLabel(driver.raw_correlation)}</strong></span>
          <span><small>Direction</small><strong>{driver.direction.toLowerCase()}</strong></span>
          <span><small>Lag</small><strong>{driver.selected_lag_days == null ? 'Not assessed' : `${driver.selected_lag_days} days`}</strong></span>
          <span><small>Sample</small><strong>n={driver.sample_size}</strong></span>
          <span><small>Coverage</small><strong>{driverCoverageLabel(driver.coverage_ratio, driver.missing_observations)}</strong></span>
        </div>
        <p><strong>Temporal order:</strong> {driverTemporalLabel(driver.temporal_order, driver.temporal_order_supported)}</p>
        <p><strong>Important limitation:</strong> {driver.limitations[0] ?? 'No additional limitation recorded.'}</p>
        <p className="driver-boundary">{driver.claim_boundary}</p>
        <details>
          <summary>Why this driver ranked here</summary>
          <p><strong>Score:</strong> {driver.score_name} · {driver.score_scale}</p>
          <pre>{JSON.stringify(driver.score_components, null, 2)}</pre>
          <p><strong>Tested lags:</strong> {driver.lag_candidates_tested}</p>
          <pre>{JSON.stringify(driver.tested_lags, null, 2)}</pre>
          <p><strong>Stability diagnostics:</strong> {driver.stability_status}</p>
          <pre>{JSON.stringify(driver.stability_details, null, 2)}</pre>
          <p><strong>Eligibility checks:</strong></p>
          <pre>{JSON.stringify(driver.eligibility_checks, null, 2)}</pre>
          <p><strong>Seasonality control:</strong> {driver.seasonality_control} · <strong>Trend control:</strong> {driver.trend_control}</p>
          <p><strong>Evidence references:</strong></p>
          <pre>{JSON.stringify(driver.evidence_references, null, 2)}</pre>
          {driver.limitations.map((limitation, index) => <p key={`limit-${index}`}>{limitation}</p>)}
        </details>
      </section>)}
    </div>}

    {model.excluded.length > 0 && <details className="driver-exclusions">
      <summary>Excluded candidates ({model.excluded.length})</summary>
      {model.excluded.map(item => <div className="driver-exclusion" key={item.driver_id}>
        <strong>{item.driver_id.replaceAll('_', ' ')}</strong>
        <span className="evidence-pill limited">{driverExclusionLabel(item.reason_code)}</span>
        <p>{item.reason}</p>
        <small>{item.source_id} · {item.sample_size} usable pairs · failed checks: {item.failed_checks.join(', ') || 'none recorded'}</small>
        <details><summary>Evidence references</summary><pre>{JSON.stringify(item.evidence_references, null, 2)}</pre></details>
      </div>)}
    </details>}

    <details className="driver-methodology">
      <summary>Overall method and limitations</summary>
      <p><strong>Multiple-testing correction:</strong> {analysis.correction_method ?? 'None; ranking is exploratory.'}</p>
      <p><strong>Windows tested:</strong> {analysis.windows_tested} · <strong>Lag hypotheses tested:</strong> {analysis.hypotheses_tested}</p>
      {analysis.limitations.map((limitation, index) => <p key={`analysis-limit-${index}`}>{limitation}</p>)}
    </details>
  </article>
}
