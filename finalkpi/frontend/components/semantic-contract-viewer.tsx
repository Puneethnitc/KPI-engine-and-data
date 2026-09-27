import {
  contractCapabilityLabel,
  contractComparisonView,
  contractPersonaFrame,
  contractValueLabel,
  type ContractComparison,
  type SemanticContract,
} from '../lib/semantic-contract'

export function ContractStateNotice({
  state,
  message,
}: {
  state: 'loading' | 'unauthorized' | 'not-found' | 'invalid' | 'error'
  message?: string
}) {
  if (state === 'loading') return <div className="state" role="status">Loading semantic contract…</div>
  const alert = state === 'unauthorized' || state === 'invalid' || state === 'error'
  const title = state === 'unauthorized' ? 'Contract metadata is not authorized.'
    : state === 'not-found' ? 'The requested KPI contract or saved run was not found.'
      : state === 'invalid' ? 'The KPI contract is invalid.'
        : 'The contract could not be loaded.'
  return <div className={`alert ${alert ? 'error' : 'warning'}`} role={alert ? 'alert' : 'status'}>
    {message ?? title}
  </div>
}

export default function SemanticContractViewer({
  snapshot,
  current,
  comparison,
  persona,
  historical = false,
}: {
  snapshot: SemanticContract
  current?: SemanticContract | null
  comparison?: ContractComparison | null
  persona: string
  historical?: boolean
}) {
  const comparisonView = historical ? contractComparisonView(comparison, snapshot, current) : null
  const capabilities = Object.entries(snapshot.capabilities)

  return <div className="contract-viewer">
    {historical && comparisonView && <div className={`contract-change-banner ${comparisonView.changed ? 'changed' : ''}`} role="status">
      <strong>{comparisonView.message}</strong>
      <span>Contract snapshot used by this run · v{snapshot.identity.version} · {snapshot.governance.contract_hash}</span>
      {current && <span>Current is v{current.identity.version} · {current.governance.contract_hash}</span>}
      {comparison && <div className="contract-facts">
        <Fact label="Snapshot status" value={comparison.snapshot_status} />
        <Fact label="Same version" value={comparison.same_version == null ? '—' : comparison.same_version ? 'Yes' : 'No'} />
        <Fact label="Same hash" value={comparison.same_hash == null ? '—' : comparison.same_hash ? 'Yes' : 'No'} />
        <Fact label="Changed since run" value={comparison.changed_since_run == null ? '—' : comparison.changed_since_run ? 'Yes' : 'No'} />
      </div>}
    </div>}
    <header className="contract-hero">
      <div>
        <span className="eyebrow">{historical ? 'Saved run contract snapshot' : 'Current semantic contract'}</span>
        <h1>{snapshot.identity.display_name}</h1>
        <p>{snapshot.identity.definition}</p>
        <small>{snapshot.identity.kpi_id} · Version {snapshot.identity.version} · {snapshot.identity.status} · Owner {snapshot.identity.owner}</small>
      </div>
      <span className={`evidence-pill ${snapshot.governance.validation_status === 'VALID' ? 'good' : 'warning'}`}>
        {snapshot.governance.validation_status === 'VALID' ? 'Valid contract' : 'Invalid contract'}
      </span>
    </header>
    {snapshot.governance.validation_status !== 'VALID' && <div className="alert error" role="alert">
      <strong>Contract validation failed</strong>
      <ul>{snapshot.governance.validation_errors.map((error, index) => <li key={index}>{error}</li>)}</ul>
    </div>}
    <p className="contract-persona-frame">{contractPersonaFrame(persona)}</p>
    <p className="contract-purpose"><strong>Business purpose:</strong> {snapshot.identity.business_purpose}</p>

    <section className="contract-section" aria-labelledby="contract-calculation">
      <div className="contract-section-heading"><span className="eyebrow">Executable semantics</span><h2 id="contract-calculation">Calculation</h2></div>
      <div className="contract-facts">
        <Fact label="Formula" value={snapshot.calculation.formula} />
        <Fact label="Operator" value={snapshot.calculation.operator} />
        <Fact label="Unit and precision" value={`${snapshot.calculation.unit} · ${snapshot.calculation.precision} decimal places`} />
        <Fact label="Value field" value={snapshot.calculation.value_column} />
        <Fact label="Numerator" value={snapshot.calculation.numerator_column} />
        <Fact label="Denominator" value={snapshot.calculation.denominator_column} />
        <Fact label="Weight field" value={snapshot.calculation.weight_column} />
        <Fact label="Executable method" value={snapshot.calculation.executable_method} />
        <Fact label="Null policy" value={snapshot.calculation.null_policy} />
        <Fact label="Zero policy" value={snapshot.calculation.zero_policy} />
      </div>
      {snapshot.calculation.operator === 'RATIO_OF_SUMS' && <p className="contract-callout">This KPI is calculated as the sum of its numerator divided by the sum of its denominator. It is not an average of displayed rates.</p>}
      {snapshot.calculation.aggregation_notes.map((note, index) => <p className="contract-note" key={index}>{note}</p>)}
    </section>

    <section className="contract-section" aria-labelledby="contract-grain-source">
      <div className="contract-section-heading"><span className="eyebrow">Source and scope</span><h2 id="contract-grain-source">Grain and lineage</h2></div>
      <div className="contract-facts">
        <Fact label="Native grain" value={snapshot.grain_and_scope.native_grain} />
        <Fact label="Source" value={`${snapshot.source.primary_source_id} · ${snapshot.source.source_table}`} />
        <Fact label="Source grain" value={snapshot.source.source_grain} />
        <Fact label="Dimensions" value={contractValueLabel(snapshot.grain_and_scope.dimensions)} />
        <Fact label="Event time" value={snapshot.source.event_time_field} />
        <Fact label="Available at" value={snapshot.source.availability_time_field} />
        <Fact label="Natural key" value={contractValueLabel(snapshot.source.natural_key)} />
        <Fact label="Calendar / timezone" value={`${snapshot.grain_and_scope.calendar} · ${snapshot.grain_and_scope.timezone}`} />
        <Fact label="Refresh" value={snapshot.source.refresh_cadence} />
        <Fact label="Source classification" value={snapshot.source.access_classification} />
        <Fact label="Source lineage" value={snapshot.source.lineage_reference} />
        <Fact label="Catalog version" value={snapshot.source.catalog_version} />
        <Fact label="Minimum history" value={snapshot.grain_and_scope.minimum_history_periods} />
      </div>
      <details><summary>Declared source fields</summary><div className="contract-table-wrap"><table><thead><tr><th>Field</th><th>Type</th><th>Required</th><th>Nullable</th><th>Unit</th></tr></thead><tbody>
        {snapshot.source.required_fields.map(field => <tr key={field.name}><td>{field.name}</td><td>{field.type}</td><td>{field.required ? 'Yes' : 'No'}</td><td>{field.nullable ? 'Yes' : 'No'}</td><td>{field.unit ?? 'Not specified'}</td></tr>)}
      </tbody></table></div></details>
    </section>

    <section className="contract-section" aria-labelledby="contract-materiality">
      <div className="contract-section-heading"><span className="eyebrow">Alert policy</span><h2 id="contract-materiality">Materiality</h2></div>
      <div className="contract-facts">
        <Fact label="Statistical method" value={snapshot.materiality.statistical_method} />
        <Fact label="Z threshold" value={snapshot.materiality.statistical_thresholds.z_threshold} />
        <Fact label="Business threshold" value={`${snapshot.materiality.business_thresholds.absolute_change ?? 'Not specified'} ${snapshot.materiality.business_thresholds.unit ?? ''}`} />
        <Fact label="Detector agreement" value={snapshot.materiality.detector_agreement_rule} />
        <Fact label="Threshold status" value={snapshot.materiality.threshold_status} />
        <Fact label="Calibration reference" value={snapshot.materiality.calibration_reference} />
      </div>
    </section>

    <section className="contract-section" aria-labelledby="contract-drivers">
      <div className="contract-section-heading"><span className="eyebrow">Governed hypotheses</span><h2 id="contract-drivers">Driver candidates</h2></div>
      {!snapshot.drivers.candidate_drivers.length ? <p>No driver candidates are declared for this KPI.</p> : <div className="contract-table-wrap"><table><thead><tr><th>Driver</th><th>Source / grain</th><th>Aggregation</th><th>Unit</th><th>Control</th><th>Direction</th><th>Lags</th><th>Minimum pairs</th><th>Coverage</th></tr></thead><tbody>
        {snapshot.drivers.candidate_drivers.map(driver => <tr key={driver.driver_id}><td><strong>{driver.display_name}</strong><small>{driver.driver_id} · {driver.column}</small></td><td>{driver.source_id} · {driver.grain}</td><td>{driver.aggregation}</td><td>{driver.unit ?? 'Not specified'}</td><td>{driver.controllability.toLowerCase()}</td><td>{driver.expected_direction ?? 'Not specified'}</td><td>{contractValueLabel(driver.allowed_lags)}</td><td>{driver.minimum_pairs ?? 'Engine policy'}</td><td>{driver.minimum_coverage == null ? 'Engine policy' : `${(driver.minimum_coverage * 100).toFixed(0)}%`}</td></tr>)}
      </tbody></table></div>}
      <p className="contract-note"><strong>Method:</strong> {snapshot.drivers.method}</p>
      {snapshot.drivers.limitations.map((limitation, index) => <p className="contract-note" key={index}>{limitation}</p>)}
    </section>

    <section className="contract-section" aria-labelledby="contract-controls">
      <div className="contract-section-heading"><span className="eyebrow">Financial controls</span><h2 id="contract-controls">Reconciliation and decomposition</h2></div>
      <div className="contract-facts">
        <Fact label="Reconciliation" value={snapshot.reconciliation.applicable ? 'Applicable' : 'Not applicable'} />
        <Fact label="Comparison source / metric" value={snapshot.reconciliation.redacted ? 'Restricted finance comparison metadata' : `${snapshot.reconciliation.comparison_source_id ?? 'Not applicable'} · ${snapshot.reconciliation.comparison_metric ?? 'Not applicable'}`} />
        <Fact label="Unit / tolerance" value={snapshot.reconciliation.redacted ? 'Redacted by role policy' : snapshot.reconciliation.applicable ? `${snapshot.reconciliation.unit} · ${snapshot.reconciliation.tolerance}%` : 'Not applicable'} />
        <Fact label="Reconciliation mode" value={snapshot.reconciliation.mode} />
        <Fact label="Coverage rule" value={snapshot.reconciliation.coverage_rule} />
        <Fact label="Availability rule" value={snapshot.reconciliation.availability_rule} />
        <Fact label="Decomposition" value={snapshot.decomposition.applicable ? snapshot.decomposition.method : 'Not applicable'} />
        <Fact label="Accounting identity" value={snapshot.decomposition.identity} />
        <Fact label="Derived rate formula" value={snapshot.decomposition.derived_rate_formula} />
        <Fact label="Reference rate label" value={snapshot.decomposition.reference_rate_label} />
      </div>
      {snapshot.reconciliation.redaction_reason && <p className="contract-redaction">{snapshot.reconciliation.redaction_reason}</p>}
      {snapshot.decomposition.limitations.map((limitation, index) => <p className="contract-note" key={`decomposition-${index}`}>{limitation}</p>)}
    </section>

    <section className="contract-section" aria-labelledby="contract-security-capabilities">
      <div className="contract-section-heading"><span className="eyebrow">Governance</span><h2 id="contract-security-capabilities">Security and capabilities</h2></div>
      <div className="contract-facts">
        <Fact label="Owner / steward" value={`${snapshot.identity.owner} · ${snapshot.identity.steward ?? 'No separate steward'}`} />
        <Fact label="Access tags" value={contractValueLabel(snapshot.security.access_tags)} />
        <Fact label="Allowed roles" value={contractValueLabel(snapshot.security.allowed_roles)} />
        <Fact label="Row-scope dimensions" value={contractValueLabel(snapshot.security.row_scope_dimensions)} />
        <Fact label="Policy reference" value={snapshot.security.policy_reference} />
        <Fact label="Source catalog version" value={snapshot.governance.source_catalog_version} />
      </div>
      <div className="contract-capabilities">{capabilities.map(([name, value]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><span className={`evidence-pill ${value === 'SUPPORTED' ? 'good' : value === 'CONDITIONAL' ? 'limited' : 'neutral'}`}>{contractCapabilityLabel(value)}</span></div>)}</div>
      <details><summary>Contract governance record</summary><div className="contract-facts">
        <Fact label="Contract version" value={snapshot.identity.version} />
        <Fact label="Contract hash" value={snapshot.governance.contract_hash} />
        <Fact label="Effective period" value={`${snapshot.governance.effective_from ?? 'Unspecified'} – ${snapshot.governance.effective_to ?? 'Open'}`} />
        <Fact label="Approved by" value={snapshot.governance.approved_by} />
        <Fact label="Change reason" value={snapshot.governance.change_reason} />
        <Fact label="Validation" value={snapshot.governance.validation_status} />
      </div></details>
    </section>
  </div>
}

function Fact({ label, value }: { label: string; value: unknown }) {
  return <div className="contract-fact"><small>{label}</small><strong>{contractValueLabel(value)}</strong></div>
}
