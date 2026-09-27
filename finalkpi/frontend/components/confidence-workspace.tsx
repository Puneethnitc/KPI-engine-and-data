import { confidenceProfileUnavailableMessage, confidenceWorkspaceModel, type ConfidenceProfile } from '../lib/confidence-profile'

export default function ConfidenceWorkspace({
  profile,
  persona,
  verdict,
}: {
  profile?: ConfidenceProfile | null
  persona: string
  verdict?: string | null
}) {
  const unavailableMessage = confidenceProfileUnavailableMessage(profile, verdict)
  if (verdict === 'ACCESS_DENIED') return null
  if (unavailableMessage) return <section className="confidence-workspace confidence-unavailable" aria-label="Confidence and uncertainty">
    <span className="eyebrow">Evidence conclusion</span>
    <h2>Confidence profile unavailable</h2>
    <p>{unavailableMessage}</p>
  </section>

  const model = confidenceWorkspaceModel(profile, persona, verdict)
  if (!model) return null

  return <section className="confidence-workspace" aria-label="Confidence and uncertainty">
    <div className="confidence-workspace-heading">
      <div>
        <span className="eyebrow">Evidence conclusion</span>
        <h2>Four independent evidence dimensions</h2>
        <p>{model.personaFrame}</p>
      </div>
      <span className={`evidence-pill ${model.overall.tone}`}>{model.overall.statusLabel}</span>
    </div>

    <div className="confidence-overall">
      <strong>Overall: {model.overall.statusLabel}</strong>
      {model.overall.reasons.map((reason, index) => <p key={`overall-reason-${index}`}>{reason}</p>)}
      {model.overall.blockingDimensions.length > 0 && <p className="confidence-blocking">
        Blocking dimensions: {model.overall.blockingDimensions.map(key => model.dimensions.find(item => item.key === key)?.title ?? key).join(', ')}
      </p>}
    </div>

    <div className="confidence-dimensions">
      {model.dimensions.map(item => <article className="confidence-dimension" key={item.key}>
        <div className="confidence-dimension-heading">
          <h3>{item.title}</h3>
          <span className={`evidence-pill ${item.tone}`}>{item.statusLabel}</span>
        </div>
        <p className="confidence-score"><strong>Score:</strong> {item.scoreLabel}</p>
        {item.details.score == null && <small>Calibration against labelled outcomes has not been validated.</small>}
        <p><strong>Method:</strong> {item.method}</p>
        <p><strong>Supporting reason:</strong> {item.reason}</p>
        <p><strong>Main limitation:</strong> {item.limitation}</p>
        {item.boundaryMessage && <p className="confidence-boundary">{item.boundaryMessage}</p>}
        {item.details.blocking && <p className="confidence-blocking">This dimension blocks downstream causal and action claims.</p>}
        <details>
          <summary>Evidence details</summary>
          <p><strong>Score interpretation:</strong> {item.details.score_interpretation}</p>
          <p><strong>Score scale:</strong> {item.details.score_scale}</p>
          <p><strong>Evaluated:</strong> {item.details.evaluated_at}</p>
          <p><strong>Evidence references:</strong> {item.details.evidence_refs.length ? item.details.evidence_refs.join(', ') : 'No protected evidence references are available.'}</p>
          {item.details.reasons.slice(1).map((reason, index) => <p key={`reason-${index}`}>{reason}</p>)}
          {item.details.limitations.slice(1).map((limitation, index) => <p key={`limitation-${index}`}>{limitation}</p>)}
          <pre>{JSON.stringify(item.details.inputs, null, 2)}</pre>
        </details>
      </article>)}
    </div>
  </section>
}