import {
  actionBoundary,
  actionCountLabel,
  actionImpactLabel,
  actionPersonaFrame,
  actionStatusLabel,
  isLegacyAction,
  safeEvidencePath,
  type ActionContract,
} from '../lib/action-workspace'
import { statusLabel } from '../lib/presentation'

export default function ActionWorkspace({
  actions,
  persona,
  verdict,
  onAsk,
}: {
  actions?: ActionContract[] | null
  persona: string
  verdict?: string | null
  onAsk?: (recommendation: string) => void
}) {
  if (verdict === 'ACCESS_DENIED') return null
  const visibleActions = actions ?? []
  const blocked = verdict === 'CONTRADICTED' || visibleActions.some(action => action.status === 'BLOCKED')
  const abstention = verdict === 'INSUFFICIENT_HISTORY' || verdict === 'SEASONAL_REVIEW' || verdict === 'NO_MATERIAL_MOVEMENT'

  return <section className="card action-card action-workspace" aria-label="Structured action recommendations">
    <div className="section-heading compact">
      <div>
        <span className="eyebrow">Evidence-linked guidance</span>
        <h2>Decision workspace</h2>
      </div>
      <span className={`status ${blocked ? 'warn' : 'ok'}`}>{blocked ? 'Actions blocked' : actionCountLabel(visibleActions)}</span>
    </div>
    <p className="action-persona-frame">{actionPersonaFrame(persona)}</p>
    {blocked && <div className="alert warning"><strong>Actions blocked.</strong> Contradictory evidence must be reconciled before operational action is considered.</div>}
    {!blocked && !visibleActions.length && <div className="empty-state">{actions == null ? 'Action guidance is not available for this older run.' : abstention ? 'The engine is abstaining from action.' : 'The engine is abstaining from action until the evidence is sufficient.'}</div>}
    {!blocked && visibleActions.length > 0 && <div className="action-list">
      {visibleActions.map((action, index) => isLegacyAction(action)
        ? <LegacyActionItem action={action} index={index} key={`legacy-${index}`} />
        : <ActionItem action={action} index={index} key={action.action_id ?? `${action.kind ?? 'action'}-${index}`} onAsk={onAsk} />)}
    </div>}
  </section>
}

function ActionItem({ action, index, onAsk }: { action: ActionContract; index: number; onAsk?: (recommendation: string) => void }) {
  const references = action.evidence_references ?? []
  const list = (items?: string[] | null) => items?.length ? <ul>{items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{item}</li>)}</ul> : null

  return <article className="action-item">
    <div className="action-item-heading">
      <span className="action-index">{String(index + 1).padStart(2, '0')}</span>
      <div><span className="eyebrow">{actionStatusLabel(action)}</span><h3>{action.lever || 'Evidence collection'}</h3></div>
      {onAsk && action.recommendation && <button className="action-ask" onClick={() => onAsk(action.recommendation ?? '')} aria-label="Ask AI about this recommendation">Ask AI</button>}
    </div>
    <p className="action-boundary">{actionBoundary(action)}</p>
    <div className="action-facts">
      <Fact label="Driver" value={action.driver_id || 'No specific driver'} />
      <OptionalFact label="Rank" value={action.driver_rank} />
      <OptionalFact label="Relationship" value={action.driver_relationship ? statusLabel(action.driver_relationship) : null} />
      <OptionalFact label="Control" value={action.controllability ? statusLabel(action.controllability) : null} />
      <Fact label="Owner" value={action.owner ? statusLabel(action.owner) : null} />
      <OptionalFact label="Decision right" value={action.decision_right} />
      <Fact label="Approval required" value={action.approval_required == null ? 'Not specified' : action.approval_required ? 'Yes' : 'No'} />
      <OptionalFact label="Evidence" value={action.evidence_status ? statusLabel(action.evidence_status) : null} />
      <OptionalFact label="Confidence" value={action.confidence_status ? statusLabel(action.confidence_status) : null} />
      <Fact label="Expected impact" value={actionImpactLabel(action)} />
      <OptionalFact label="Monitoring" value={action.monitoring_plan} />
    </div>
    {action.recommendation && <div className="action-recommendation"><strong>Recommendation</strong><p>{action.recommendation}</p></div>}
    <details className="action-details"><summary>Execution details and evidence</summary><div className="action-detail-grid">
      <Detail label="Owner source" value={action.owner_source} />
      <Detail label="Impact method" value={action.impact_method} />
      <Detail label="Constraints" value={list(action.constraints)} />
      <Detail label="Limitations" value={list(action.limitations)} />
      <Detail label="Monitoring plan" value={action.monitoring_plan} />
      <Detail label="Success metric" value={action.success_metric} />
      <Detail label="Review window" value={action.review_window} />
      <Detail label="Stop conditions" value={list(action.stop_conditions)} />
    </div><div className="action-evidence"><strong>Evidence references</strong>{references.length ? <ul>{references.map((reference, referenceIndex) => <li key={`${reference.path ?? 'reference'}-${referenceIndex}`}><span>{statusLabel(reference.evidence_type)}</span> · {safeEvidencePath(reference.path)}{reference.period ? ` · ${reference.period}` : ''}{reference.method ? ` · ${reference.method}` : ''}</li>)}</ul> : <span className="action-muted">No structured evidence references supplied.</span>}</div></details>
  </article>
}

function LegacyActionItem({ action, index }: { action: ActionContract; index: number }) {
  return <article className="action-legacy-card">
    <span className="eyebrow">Legacy recommendation snapshot · {String(index + 1).padStart(2, '0')}</span>
    <h3>{action.lever || 'Evidence collection'}</h3>
    <p className="action-boundary">{actionBoundary(action)}</p>
    <p className="action-recommendation"><strong>{actionStatusLabel(action)}</strong><br />{action.recommendation || 'No recommendation text was saved.'}</p>
    <div className="action-legacy-facts"><Fact label="Driver" value={action.driver_id || 'Not specified'} /><Fact label="Owner" value={action.owner ? statusLabel(action.owner) : null} /><Fact label="Impact" value={actionImpactLabel(action)} /></div>
  </article>
}

function Fact({ label, value }: { label: string; value: unknown }) {
  return <div className="action-fact"><small>{label}</small><strong>{value == null || value === '' ? '—' : String(value)}</strong></div>
}

function OptionalFact({ label, value }: { label: string; value: unknown }) {
  return value == null || value === '' ? null : <Fact label={label} value={value} />
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  if (value == null || value === '') return null
  return <div className="action-detail"><strong>{label}</strong>{typeof value === 'string' ? <p>{value}</p> : value}</div>
}
