import {
  processingCategoryLabel,
  processingStatusLabel,
  processingStatusTone,
  runtimeCostLabel,
  runtimeLatencyLabel,
  runtimeTimestampLabel,
  runtimeTokenLabel,
  type ProcessingStage,
  type ProcessingTransparency,
  type RuntimeTelemetry,
} from '../lib/processing-transparency'

export default function ProcessingTransparencyView({
  transparency,
  telemetry,
  compact = false,
  suppressRuntimeTelemetry = false,
}: {
  transparency?: ProcessingTransparency | null
  telemetry?: RuntimeTelemetry | null
  compact?: boolean
  suppressRuntimeTelemetry?: boolean
}) {
  const summary = transparency?.summary
  const stageList = transparency && <div className="processing-stage-list">
    {transparency.stages.map(stage => <ProcessingStageView key={stage.stage_id} stage={stage} />)}
  </div>

  return <section className={`card processing-transparency${compact ? ' compact' : ''}`} aria-label="How this insight was produced">
    <div className="section-heading compact">
      <div><span className="eyebrow">Processing provenance</span><h2>How this insight was produced</h2></div>
      {transparency && <span className="evidence-pill">v{transparency.contract_version}</span>}
    </div>
    {transparency ? <>
      <p className="processing-policy">{transparency.quantitative_truth_policy}</p>
      <div className="processing-summary" aria-label="Processing summary">
        <SummaryFact label="Quantitative stages used" value={summary!.quantitative_stages} />
        <SummaryFact label="LLM used" value={summary!.llm_used ? 'Yes' : 'No'} />
        <SummaryFact label="SQL executed" value={summary!.sql_executed ? 'Yes' : 'No'} />
        <SummaryFact label="Retrieval used" value={summary!.retrieval_used ? 'Yes' : 'No'} />
        <SummaryFact label="Causal method used" value={summary!.causal_method_used ? 'Yes' : 'No'} />
      </div>
      <div className="processing-policy-notes">
        <strong>{summary!.llm_used ? 'LLM used for approved wording only' : 'LLM not used'}</strong>
        <span>Quantitative values were computed before narrative generation.</span>
        <span>SQL capability is not SQL execution.</span>
        <span>Chat retrieval, when used, is separate from diagnosis retrieval.</span>
      </div>
      {compact
        ? <details className="processing-stage-disclosure"><summary>View all processing stages ({transparency.stages.length})</summary>{stageList}</details>
        : stageList}
    </> : <p className="processing-legacy-message">Processing provenance was not recorded for this historical run.</p>}
    {!suppressRuntimeTelemetry && <RuntimeTelemetryView telemetry={telemetry} />}
  </section>
}

function RuntimeTelemetryView({ telemetry }: { telemetry?: RuntimeTelemetry | null }) {
  if (!telemetry) return <div className="runtime-telemetry" aria-label="Runtime telemetry">
    <span className="eyebrow">Runtime telemetry</span>
    <p className="processing-legacy-message">Runtime telemetry is unavailable for this historical run.</p>
  </div>

  const stagesHaveModel = telemetry.stages.some(stage => stage.provider || stage.model)
  const summary = telemetry.llm_summary
  const limits = telemetry.limits ?? {}
  const limitFacts = ([
    ['Timeout', limits.timeout_ms == null ? '' : runtimeLatencyLabel(limits.timeout_ms)],
    ['Maximum model calls', limits.max_model_calls == null ? '' : String(limits.max_model_calls)],
    ['Maximum input tokens', limits.max_input_tokens == null ? '' : String(limits.max_input_tokens)],
    ['Fallback behavior', typeof limits.fallback_behavior === 'string' ? limits.fallback_behavior : ''],
    ['Pricing version', typeof limits.pricing_version === 'string' ? limits.pricing_version : ''],
  ] as [string, string][]).filter(([, value]) => value !== '')

  return <div className="runtime-telemetry" aria-label="Runtime telemetry">
    <div className="section-heading compact">
      <div><span className="eyebrow">Operational telemetry</span><h3>Runtime execution</h3></div>
      <span className="evidence-pill">Measured</span>
    </div>
    <div className="processing-summary runtime-telemetry-summary">
      <SummaryFact label="Execution ID" value={telemetry.execution_id} />
      <SummaryFact label="Total latency" value={runtimeLatencyLabel(telemetry.total_latency_ms)} />
      <SummaryFact label="Started" value={runtimeTimestampLabel(telemetry.started_at)} />
      <SummaryFact label="Completed" value={runtimeTimestampLabel(telemetry.completed_at)} />
      <SummaryFact label="Cache hits" value={telemetry.cache_summary.hits} />
      <SummaryFact label="Cache misses" value={telemetry.cache_summary.misses} />
      <SummaryFact label="Cache not applicable" value={telemetry.cache_summary.not_applicable} />
    </div>

    <div className="runtime-telemetry-table-wrap">
      <table className="runtime-telemetry-table">
        <thead><tr>
          <th>Stage</th><th>Processing type</th><th>Method</th><th>Status</th><th>Latency</th><th>Cache</th>
          {stagesHaveModel && <th>Provider / model</th>}
          <th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Estimated cost</th>
        </tr></thead>
        <tbody>{telemetry.stages.map((stage, index) => <tr key={`${stage.stage}-${index}`}>
          <td>{stage.stage}</td><td>{stage.processing_type}</td><td>{stage.method}</td><td>{stage.status}</td>
          <td>{runtimeLatencyLabel(stage.latency_ms)}</td><td>{stage.cache_status}</td>
          {stagesHaveModel && <td>{stage.provider || stage.model ? [stage.provider, stage.model].filter(Boolean).join(' / ') : null}</td>}
          <td>{stage.model_calls}</td><td>{runtimeTokenLabel(stage.input_tokens)}</td>
          <td>{runtimeTokenLabel(stage.output_tokens)}</td><td>{runtimeCostLabel(stage.estimated_cost_usd)}</td>
        </tr>)}</tbody>
      </table>
    </div>

    <div className="runtime-telemetry-subsection">
      <h4>LLM usage</h4>
      <div className="processing-summary">
        {summary.provider && <SummaryFact label="Provider" value={summary.provider} />}
        {summary.model && <SummaryFact label="Model" value={summary.model} />}
        <SummaryFact label="Model calls" value={summary.model_calls} />
        <SummaryFact label="Input tokens" value={runtimeTokenLabel(summary.input_tokens)} />
        <SummaryFact label="Output tokens" value={runtimeTokenLabel(summary.output_tokens)} />
        <SummaryFact label="Usage source" value={summary.usage_source} />
        <SummaryFact label="Estimated USD cost" value={runtimeCostLabel(summary.estimated_cost_usd)} />
      </div>
    </div>

    {limitFacts.length > 0 && <div className="runtime-telemetry-subsection">
      <h4>Configured runtime limits</h4>
      <div className="processing-summary">
        {limitFacts.map(([label, value]) => <SummaryFact key={label} label={label} value={value} />)}
      </div>
    </div>}
    <p className="runtime-telemetry-policy">Quantitative KPI calculations are performed by deterministic/statistical engine stages. LLMs are used only where explicitly shown.</p>
  </div>
}

function ProcessingStageView({ stage }: { stage: ProcessingStage }) {
  const tone = processingStatusTone(stage.execution_status)
  return <article className="processing-stage">
    <div className="processing-stage-heading">
      <div><h3>{stage.label}</h3><small>{processingCategoryLabel(stage.method_category)}</small></div>
      <span className={`status ${tone}`}>{processingStatusLabel(stage.execution_status)}</span>
    </div>
    <p>{stage.purpose}</p>
    <div className="processing-stage-facts">
      <span><strong>Quantitative truth</strong>{stage.quantitative_truth ? 'Yes' : 'No'}</span>
      {stage.llm_role && <span><strong>LLM role</strong>{stage.llm_role === 'WORDING_ONLY' ? 'Approved wording only' : stage.llm_role}</span>}
      {stage.limitation && <span><strong>Limitation</strong>{stage.limitation}</span>}
    </div>
    {stage.evidence_refs.length > 0 && <details className="processing-evidence"><summary>Evidence references ({stage.evidence_refs.length})</summary><ul>{stage.evidence_refs.map(reference => <li key={reference}>{reference}</li>)}</ul></details>}
  </article>
}

function SummaryFact({ label, value }: { label: string; value: string | number }) {
  return <div className="processing-summary-fact"><small>{label}</small><strong>{value}</strong></div>
}
