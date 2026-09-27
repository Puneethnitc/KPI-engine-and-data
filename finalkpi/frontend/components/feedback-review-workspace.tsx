'use client'

import { useEffect, useState } from 'react'
import { API_BASE } from './app-shell'
import {
  feedbackStateTone,
  formatFeedbackState,
  proposalOutcomeFacts,
  proposalCreatePayload,
  type FeedbackAggregation,
  type FeedbackRecord,
  type ImprovementProposal,
  type ProposalType,
} from '../lib/feedback-learning'
import CandidateLearningPanel from './candidate-learning-panel'

const proposalLabels: Record<string, string> = {
  REVIEW_REQUIRED: 'Review required', KPI_CONTRACT_CHANGE: 'KPI contract change',
  DATA_QUALITY_FIX: 'Data quality fix', DRIVER_CONFIGURATION_CHANGE: 'Driver configuration change',
  BUSINESS_RULE_CHANGE: 'Business rule change', ANALYTICAL_METHOD_REVIEW: 'Analytical method review',
  CONFIDENCE_POLICY_CHANGE: 'Confidence policy change', NARRATIVE_TEMPLATE_CHANGE: 'Narrative template change',
  ACTION_POLICY_CHANGE: 'Action policy change', ACCESS_POLICY_REVIEW: 'Access policy review',
  EVALUATION_CASE_ADDITION: 'Evaluation case addition',
}

function StateBadge({ state }: { state?: string }) {
  return <span className={`feedback-state ${feedbackStateTone(state)}`}>{formatFeedbackState(state)}</span>
}

function scopeLabel(scope?: Record<string, string>) {
  return scope ? Object.entries(scope).map(([key, value]) => `${key}: ${value}`).join(' · ') : 'Scope unavailable'
}

function dateTime(value?: string) {
  if (!value) return 'Time unavailable'
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString()
}

export default function FeedbackReviewWorkspace({ persona, userId }: { persona: string; userId: string }) {
  const reviewer = persona === 'CFO'
  const [feedback, setFeedback] = useState<FeedbackRecord[]>([])
  const [aggregations, setAggregations] = useState<FeedbackAggregation[]>([])
  const [proposals, setProposals] = useState<ImprovementProposal[]>([])
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [selectedAggregationKey, setSelectedAggregationKey] = useState('')
  const [proposalType, setProposalType] = useState<ProposalType | ''>('')
  const [title, setTitle] = useState('')
  const [rationale, setRationale] = useState('')
  const [expectedImprovement, setExpectedImprovement] = useState('')
  const [affectedCases, setAffectedCases] = useState('')
  const [rollbackPlan, setRollbackPlan] = useState('')
  const [sourceFeedbackId, setSourceFeedbackId] = useState('')
  const [changeFields, setChangeFields] = useState<Record<string, string>>({})
  const [successMessage, setSuccessMessage] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      const query = `?user_id=${encodeURIComponent(userId)}`
      const requests: Promise<Response>[] = [fetch(`${API_BASE}/api/feedback${query}`)]
      if (reviewer) {
        requests.push(fetch(`${API_BASE}/api/feedback/aggregations${query}`))
        requests.push(fetch(`${API_BASE}/api/improvement-proposals${query}`))
      }
      const responses = await Promise.all(requests)
      if (responses.some(response => !response.ok)) throw new Error('Feedback review data is unavailable for this scope.')
      const payloads = await Promise.all(responses.map(response => response.json()))
      setFeedback(payloads[0].items ?? [])
      setAggregations(reviewer ? payloads[1].items ?? [] : [])
      setProposals(reviewer ? payloads[2].items ?? [] : [])
    } catch (loadError) {
      setFeedback([])
      setAggregations([])
      setProposals([])
      setError(loadError instanceof Error ? loadError.message : 'Feedback review data is unavailable for this scope.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [persona, userId])

  async function appendFeedbackEvent(item: FeedbackRecord, eventType: 'TRIAGED' | 'REJECTED') {
    if (savingId || item.legacy) return
    setSavingId(item.feedback_id)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/api/feedback/${encodeURIComponent(item.feedback_id)}/events?user_id=${encodeURIComponent(userId)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_type: eventType }),
      })
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) {
          setFeedback([])
          setAggregations([])
          setProposals([])
        }
        throw new Error('Feedback is no longer available for review.')
      }
      await load()
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'Feedback review failed.')
    } finally {
      setSavingId(null)
    }
  }

  async function createProposal(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const aggregation = aggregations.find(item => item.aggregation_key === selectedAggregationKey)
    if (!aggregation || !proposalType || savingId) return
    setSavingId(aggregation.aggregation_key)
    setError('')
    setSuccessMessage('')
    try {
      const payload = proposalCreatePayload({
        userId, aggregation, proposalType, sourceFeedbackId,
        title, rationale, changeFields, expectedImprovement,
        affectedCases: affectedCases.split(',').map(item => item.trim()).filter(Boolean), rollbackPlan,
      })
      const response = await fetch(`${API_BASE}/api/improvement-proposals`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      })
      const result = await response.json().catch(() => null)
      if (!response.ok) throw new Error(result?.detail ?? 'Proposal could not be created.')
      setSuccessMessage('Improvement proposed. It has not been applied or verified.')
      setTitle('')
      setRationale('')
      setExpectedImprovement('')
      setAffectedCases('')
      setRollbackPlan('')
      setChangeFields({})
      await load()
    } catch (proposalError) {
      setError(proposalError instanceof Error ? proposalError.message : 'Proposal could not be created.')
    } finally {
      setSavingId(null)
    }
  }

  async function reviewProposal(proposal: ImprovementProposal, eventType: 'ACCEPTED' | 'REJECTED') {
    if (savingId || proposal.state !== 'PROPOSED') return
    if (eventType === 'ACCEPTED' && !window.confirm('Accepting this proposal records approval only. It does not apply the change or verify an improvement.')) return
    setSavingId(proposal.proposal_id)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/api/improvement-proposals/${encodeURIComponent(proposal.proposal_id)}/events?user_id=${encodeURIComponent(userId)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_type: eventType }),
      })
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) {
          setFeedback([])
          setAggregations([])
          setProposals([])
        }
        throw new Error('Proposal is no longer available for review.')
      }
      await load()
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : 'Proposal review failed.')
    } finally {
      setSavingId(null)
    }
  }

  const selectedAggregation = aggregations.find(item => item.aggregation_key === selectedAggregationKey)
  const proposalOptions = selectedAggregation?.proposal_type_options ?? []
  const selectedOption = proposalOptions.find(option => option.proposal_type === proposalType)
  const sourceCorrectionOptions = selectedAggregation?.source_feedback_ids.flatMap(id => {
    const record = feedback.find(item => item.feedback_id === id)
    return record?.mode === 'ANALYST_CORRECTION' ? [{ id, label: `${id} · ${record.proposed_correction ?? record.issue_category ?? 'Correction'}` }] : []
  }) ?? []

  return <section className="feedback-review-workspace">
    <div className="section-heading">
      <div><span className="eyebrow">Human review</span><h2>Feedback and improvement proposals</h2><p>Feedback is evidence for review; proposals do not change production behavior.</p></div>
      <button className="icon-link" type="button" aria-label="Refresh feedback review" onClick={() => void load()} disabled={loading || !!savingId}>↻</button>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {successMessage && <div className="alert info" role="status">{successMessage}</div>}
    {loading ? <p>Loading authorized feedback…</p> : error ? null : <>
      <section className="feedback-review-section">
        <div className="feedback-review-heading"><div><h3>Feedback queue</h3><p>{feedback.length} authorized record{feedback.length === 1 ? '' : 's'}</p></div></div>
        {!feedback.length ? <p>No feedback is available in this authorized scope.</p> : <div className="feedback-queue-list">{feedback.map(item => {
          const state = item.legacy ? item.status : item.state
          return <article className="feedback-queue-item" key={item.feedback_id}>
            <div className="feedback-queue-main">
              <div className="feedback-queue-title"><strong>{item.feedback_id}</strong><StateBadge state={state} />{item.legacy && <span className="feedback-legacy-tag">Legacy · read only</span>}</div>
              <p>{item.mode ?? item.feedback_type ?? 'Legacy feedback'} · {item.kpi_id} · {scopeLabel(item.scope)}</p>
              <p>Target: {item.target_type}{item.target_id ? ` · ${item.target_id}` : ''} · {item.reason_code ?? item.issue_category ?? 'No reason code'} · {dateTime(item.created_at)}</p>
              {!item.legacy && state === 'CAPTURED' && <p className="feedback-next-step">Next permitted step: triage or reject this feedback.</p>}
              {!item.legacy && state === 'TRIAGED' && <p className="feedback-next-step">Next permitted step: include this feedback in a compatible proposal.</p>}
              {!item.legacy && item.comment && <p className="feedback-queue-comment">{item.comment}</p>}
              {!item.legacy && item.proposed_correction && <p className="feedback-queue-comment"><strong>Proposed correction:</strong> {item.proposed_correction}</p>}
              {!item.legacy && item.rationale && <p className="feedback-queue-comment"><strong>Rationale:</strong> {item.rationale}</p>}
              {!!item.events?.length && <details className="feedback-history"><summary>Lifecycle history ({item.events.length})</summary><ol>{item.events.map(event => <li key={event.event_id}><StateBadge state={event.to_state} /> {event.event_type} · {event.actor_persona} · {dateTime(event.created_at)}{event.reason ? ` · ${event.reason}` : ''}</li>)}</ol></details>}
            </div>
            {reviewer && !item.legacy && ['CAPTURED', 'TRIAGED'].includes(state ?? '') && <div className="feedback-queue-actions">
              {state === 'CAPTURED' && <button type="button" disabled={!!savingId} onClick={() => void appendFeedbackEvent(item, 'TRIAGED')}>Triage</button>}
              <button type="button" className="reject-button" disabled={!!savingId} onClick={() => void appendFeedbackEvent(item, 'REJECTED')}>Reject</button>
            </div>}
          </article>
        })}</div>}
      </section>

      {reviewer && <>
        <section className="feedback-review-section">
          <div className="feedback-review-heading"><div><h3>Deterministic aggregations</h3><p>Grouped from authorized, structured feedback. Free text is excluded.</p></div></div>
          {!aggregations.length ? <p>No eligible captured or triaged feedback groups are available.</p> : <div className="feedback-aggregation-list">{aggregations.map(item => <article className="feedback-aggregation-item" key={item.aggregation_key}>
            <div className="feedback-queue-title"><strong title={item.aggregation_key}>{item.aggregation_key.slice(0, 20)}…</strong><StateBadge state="TRIAGED" /></div>
            <p>{item.kpi_id} · {scopeLabel(item.scope)}</p>
            <p>{item.target_type} · {item.target_id}</p>
            <div className="feedback-count-grid">
              <span>Total <strong>{item.feedback_count}</strong></span><span>Business <strong>{item.business_feedback_count}</strong></span><span>Analyst <strong>{item.analyst_correction_count}</strong></span><span>Useful / not useful <strong>{item.useful_count} / {item.not_useful_count}</strong></span><span>Submitters <strong>{item.unique_authorized_submitter_count}</strong></span>
            </div>
            <p>Reasons: {Object.entries(item.reason_counts).map(([key, count]) => `${key} ${count}`).join(' · ') || '—'}</p>
            <p>Issues: {Object.entries(item.issue_category_counts).map(([key, count]) => `${key} ${count}`).join(' · ') || '—'}</p>
            <p>Actions: {Object.entries(item.action_taken_counts).map(([key, count]) => `${key} ${count}`).join(' · ') || '—'}</p>
            <small>{dateTime(item.earliest_created_at)} – {dateTime(item.latest_created_at)}</small>
            <div><button type="button" disabled={!item.proposal_type_options.length} onClick={() => {
              setSelectedAggregationKey(item.aggregation_key)
              setProposalType(item.proposal_type_options[0]?.proposal_type ?? '')
              setSourceFeedbackId('')
              setChangeFields({})
              setTitle('')
              setRationale('')
              setExpectedImprovement('')
              setAffectedCases('')
              setRollbackPlan('')
            }}>Create proposal</button></div>
          </article>)}</div>}
        </section>

        {selectedAggregation && <section className="feedback-review-section proposal-create-section">
          <div className="feedback-review-heading"><div><h3>New improvement proposal</h3><p>Approval records review only. No change is applied here.</p></div><button type="button" onClick={() => setSelectedAggregationKey('')}>Close</button></div>
          <form className="proposal-form" onSubmit={event => void createProposal(event)}>
            <label>Proposal type
              <select value={proposalType} onChange={event => { setProposalType(event.target.value as ProposalType); setChangeFields({}) }} required>
                {proposalOptions.map(option => <option key={option.proposal_type} value={option.proposal_type}>{proposalLabels[option.proposal_type] ?? option.proposal_type}</option>)}
              </select>
            </label>
            {selectedOption?.fields.map(field => <label key={field.name}>{field.label}
              {field.source === 'analyst_correction' ? <>
                <select value={sourceFeedbackId} onChange={event => {
                  setSourceFeedbackId(event.target.value)
                  const record = feedback.find(item => item.feedback_id === event.target.value)
                  setChangeFields(current => ({ ...current, [field.name]: record?.proposed_correction ?? '' }))
                }} required>
                  <option value="">Select supporting analyst correction</option>
                  {sourceCorrectionOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
                </select>
                <input value={changeFields[field.name] ?? ''} readOnly aria-label={`${field.label} from selected correction`} />
              </> : field.options ? <select value={changeFields[field.name] ?? ''} onChange={event => setChangeFields(current => ({ ...current, [field.name]: event.target.value }))} required>
                <option value="">Select expected outcome</option>{field.options.map(option => <option key={option} value={option}>{option.replaceAll('_', ' ')}</option>)}
              </select> : <input maxLength={field.max_length} value={changeFields[field.name] ?? (field.name === 'driver_id' || field.name === 'action_target' ? selectedAggregation.target_id : '')} onChange={event => setChangeFields(current => ({ ...current, [field.name]: event.target.value }))} required />}
            </label>)}
            <label>Title<input value={title} maxLength={200} onChange={event => setTitle(event.target.value)} required /></label>
            <label>Rationale<textarea value={rationale} maxLength={2000} onChange={event => setRationale(event.target.value)} required /></label>
            <label>Expected improvement<textarea value={expectedImprovement} maxLength={1000} onChange={event => setExpectedImprovement(event.target.value)} required /></label>
            <label>Affected evaluation case IDs <span className="form-optional">Optional, comma separated</span><input value={affectedCases} onChange={event => setAffectedCases(event.target.value)} /></label>
            <label>Rollback plan<textarea value={rollbackPlan} maxLength={1000} onChange={event => setRollbackPlan(event.target.value)} required /></label>
            <button type="submit" className="run-button" disabled={!!savingId}>{savingId === selectedAggregation.aggregation_key ? 'Saving…' : 'Propose improvement'}</button>
          </form>
        </section>}

        <section className="feedback-review-section">
          <div className="feedback-review-heading"><div><h3>Improvement proposals</h3><p>Accepted proposals remain unapplied and unverified.</p></div></div>
          {!proposals.length ? <p>No proposals have been created.</p> : <div className="feedback-proposal-list">{proposals.map(proposal => {
            const outcome = proposalOutcomeFacts(proposal)
            return <article className="feedback-proposal-item" key={proposal.proposal_id}>
            <div className="feedback-queue-title"><strong>{proposal.title}</strong><StateBadge state={proposal.state} /></div>
            <p>{proposalLabels[proposal.proposal_type] ?? proposal.proposal_type} · {proposal.kpi_id} · {scopeLabel(proposal.scope)} · {proposal.target_artifact_type}</p>
            <p>{proposal.rationale}</p>
            <dl><dt>Before version</dt><dd>{proposal.before_version}</dd><dt>Proposed change</dt><dd><pre>{JSON.stringify(proposal.proposed_change, null, 2)}</pre></dd><dt>Supporting feedback</dt><dd>{proposal.supporting_feedback_summary.feedback_count as number} · {proposal.source_feedback_ids.join(', ')}</dd><dt>Expected improvement</dt><dd>{proposal.expected_improvement}</dd><dt>Evaluation cases</dt><dd>{proposal.affected_evaluation_cases.join(', ') || 'Not specified'}</dd><dt>Rollback</dt><dd>{proposal.rollback_plan}</dd></dl>
            <div className="proposal-outcome-flags"><span>Accepted: {outcome.accepted ? 'Yes' : 'No'}</span><span>Applied: {outcome.applied ? 'Yes' : 'No'}</span><span>Verified: {outcome.verified ? 'Yes' : 'No'}</span><strong>{outcome.message}</strong></div>
            {!!proposal.events.length && <details className="feedback-history"><summary>Proposal event history ({proposal.events.length})</summary><ol>{proposal.events.map(event => <li key={event.event_id}><StateBadge state={event.to_state} /> {event.event_type} · {event.actor_persona} · {dateTime(event.created_at)}{event.reason ? ` · ${event.reason}` : ''}</li>)}</ol></details>}
            {proposal.state === 'PROPOSED' && <div className="feedback-queue-actions">
              <button type="button" disabled={!!savingId} onClick={() => void reviewProposal(proposal, 'ACCEPTED')}>Accept proposal</button>
              <button type="button" className="reject-button" disabled={!!savingId} onClick={() => void reviewProposal(proposal, 'REJECTED')}>Reject</button>
            </div>}
            <CandidateLearningPanel
              proposal={proposal}
              feedback={feedback}
              userId={userId}
              reviewer={reviewer}
              onAuthorizationFailure={() => { setFeedback([]); setAggregations([]); setProposals([]) }}
              onRefresh={() => void load()}
            />
            </article>
          })}</div>}
        </section>
      </>}
    </>}
  </section>
}
