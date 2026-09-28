export type ExecutiveSummaryData = {
  status: 'LLM' | 'TEMPLATE'
  reason?: string
  sentences: { text: string; facts: string[] }[]
  do_first: { text: string; facts: string[] }
  facts: { id: string; text: string }[]
}

export function summaryBadge(status: string | undefined): string {
  return status === 'LLM' ? 'Written by AI from verified facts' : 'Template (AI unavailable)'
}

function Chips({ ids, facts }: { ids: string[]; facts: Map<string, string> }) {
  const known = ids.filter(id => facts.has(id))
  return <>{known.length > 0 && ' '}{known.map(id => <abbr key={id} className="fact-chip" title={facts.get(id)} tabIndex={0}>{id}</abbr>)}</>
}

export default function ExecutiveSummary({ summary, eyebrow, scope, fallbackText, note, footer }: {
  summary?: ExecutiveSummaryData | null
  eyebrow: string
  scope?: string
  fallbackText?: string | null
  note?: string | null
  footer?: React.ReactNode
}) {
  const hasSummary = !!summary?.sentences?.length
  if (!hasSummary && !fallbackText) return null
  const facts = new Map((summary?.facts ?? []).map(fact => [fact.id, fact.text]))
  return <section className="card executive-summary" aria-labelledby="executive-summary-title">
    <div className="card-heading">
      <div><span className="eyebrow">{eyebrow}</span><h2 id="executive-summary-title">What you need to know today</h2></div>
      <div className="executive-summary-meta">
        {hasSummary && <span className={`evidence-pill ${summary!.status === 'LLM' ? 'good' : 'limited'}`} title={summary!.reason}>{summaryBadge(summary!.status)}</span>}
        {scope && <span className="evidence-pill">{scope}</span>}
      </div>
    </div>
    {hasSummary ? <>
      <p className="executive-summary-text">{summary!.sentences.map((sentence, index) => <span key={index}>{sentence.text}<Chips ids={sentence.facts} facts={facts} />{' '}</span>)}</p>
      {summary!.do_first?.text && <p className="executive-summary-first"><strong>What to do first:</strong> {summary!.do_first.text}<Chips ids={summary!.do_first.facts} facts={facts} /></p>}
      <small className="simple-chart-note">Numbers come only from the fact chips (hover or focus a chip to read the fact). The AI never calculates figures.</small>
    </> : <p className="executive-summary-text">{fallbackText}</p>}
    {note && <small className="executive-summary-note">{note}</small>}
    {footer}
  </section>
}
