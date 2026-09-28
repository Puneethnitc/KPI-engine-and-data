import {
  corroborationSourceTypeLabel,
  corroborationStanceLabel,
  corroborationViewModel,
  type Corroboration,
} from '../lib/driver-analysis'

/**
 * Stage 6-lite: the evidence behind one driver.
 *
 * Documents are untrusted prose. They are shown with their type, date, stance
 * and a short snippet, never as a narrative claim, and the panel states
 * explicitly that a supporting document does not establish causation. The
 * status comes from the engine; this component only renders it.
 */
export default function CorroborationPanel({ corroboration }: { corroboration?: Corroboration | null }) {
  const model = corroborationViewModel(corroboration)
  if (!model.assessed) return <p className="driver-boundary">Evidence corroboration is not available for this older run.</p>

  return <details className="corroboration-panel">
    <summary>
      Evidence documents
      <span className={`evidence-pill ${model.tone}`}>{model.statusLabel}</span>
    </summary>
    <p className="driver-boundary">{model.boundary}</p>
    {model.documents.length > 0
      ? <div className="corroboration-documents">
        {model.documents.map(document => <article className={`corroboration-doc ${document.stance}`} key={document.doc_id}>
          <div className="corroboration-doc-heading">
            <strong>{document.doc_id}</strong>
            <span className={`corroboration-stance ${document.stance}`}>{corroborationStanceLabel(document.stance)}</span>
          </div>
          <small>
            {corroborationSourceTypeLabel(document.source_type)} · {document.date} · {document.region}/{document.category} · matched by {document.matched_by === 'driver_tag' ? 'driver tag' : 'keyword'}
          </small>
          <p>{document.snippet}</p>
        </article>)}
      </div>
      : <p className="driver-boundary">No documents were returned for this driver.</p>}
    <details>
      <summary>How this list was filtered</summary>
      <p>Published on or before the run's as-of date, dated within 21 days of the target date, in the requested region and category (or company-wide), and readable by this persona's entitlements. Documents that try to issue instructions are dropped before they are read.</p>
      <p>Matching is by driver tag first and keyword only as a fallback; a document's stance, not its presence, is what changes the status.</p>
    </details>
  </details>
}
