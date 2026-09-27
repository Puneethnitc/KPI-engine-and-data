'use client'

import { useEffect, useState } from 'react'
import { API_BASE } from './app-shell'
import {
  buildLearningTrace,
  candidateActionAvailability,
  nextLearningStep,
  type CandidateArtifact,
  type FeedbackRecord,
  type ImprovementProposal,
  type ProposalEvaluation,
} from '../lib/feedback-learning'
import { formatFeedbackState, feedbackStateTone } from '../lib/feedback-learning'

function StateBadge({ state }: { state: string }) {
  return <span className={`feedback-state ${feedbackStateTone(state)}`}>{formatFeedbackState(state)}</span>
}

function formatDate(value?: string | null) {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString()
}

function safeJson(value: unknown) {
  const text = JSON.stringify(value, null, 2)
  return text.length > 6000 ? `${text.slice(0, 6000)}\n[truncated]` : text
}

export default function CandidateLearningPanel({
  proposal,
  feedback,
  userId,
  reviewer,
  onAuthorizationFailure,
  onRefresh,
}: {
  proposal: ImprovementProposal
  feedback: FeedbackRecord[]
  userId: string
  reviewer: boolean
  onAuthorizationFailure: () => void
  onRefresh: () => void
}) {
  const [candidate, setCandidate] = useState<CandidateArtifact | null>(null)
  const [evaluation, setEvaluation] = useState<ProposalEvaluation | null>(null)
  const [loading, setLoading] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [rollbackReason, setRollbackReason] = useState('')
  const [applicationResult, setApplicationResult] = useState('')

  async function loadDetails() {
    if (!proposal.candidate_artifact_id) {
      setCandidate(null)
      setEvaluation(null)
      return
    }
    setLoading(true)
    setError('')
    try {
      const identity = encodeURIComponent(userId)
      const candidateResponse = await fetch(`${API_BASE}/api/candidate-artifacts/${encodeURIComponent(proposal.candidate_artifact_id)}?user_id=${identity}`)
      if (!candidateResponse.ok) {
        if (candidateResponse.status === 403 || candidateResponse.status === 404) onAuthorizationFailure()
        throw new Error('Candidate details are unavailable for this scope.')
      }
      const candidatePayload: CandidateArtifact = await candidateResponse.json()
      setCandidate(candidatePayload)
      const evaluationId = candidatePayload.evaluation_run_ids.at(-1)
      if (evaluationId) {
        const evaluationResponse = await fetch(`${API_BASE}/api/proposal-evaluations/${encodeURIComponent(evaluationId)}?user_id=${identity}`)
        if (!evaluationResponse.ok) {
          if (evaluationResponse.status === 403 || evaluationResponse.status === 404) onAuthorizationFailure()
          throw new Error('Evaluation details are unavailable for this scope.')
        }
        setEvaluation(await evaluationResponse.json())
      } else {
        setEvaluation(null)
      }
    } catch (loadError) {
      setCandidate(null)
      setEvaluation(null)
      setError(loadError instanceof Error ? loadError.message : 'Candidate details are unavailable for this scope.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadDetails() }, [proposal.proposal_id, proposal.candidate_artifact_id, userId])

  async function applyCandidate() {
    if (!reviewer || pending || proposal.state !== 'ACCEPTED' || proposal.application_support !== 'SUPPORTED') return
    if (!window.confirm('Application creates an evaluation-only candidate. It does not change the live engine.')) return
    setPending(true)
    setError('')
    setApplicationResult('')
    try {
      const response = await fetch(`${API_BASE}/api/improvement-proposals/${encodeURIComponent(proposal.proposal_id)}/apply?user_id=${encodeURIComponent(userId)}`, { method: 'POST' })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) onAuthorizationFailure()
        throw new Error(body?.detail ?? 'Candidate application failed.')
      }
      if (body?.status === 'APPLICATION_NOT_SUPPORTED') {
        setApplicationResult('APPLICATION_NOT_SUPPORTED: This proposal remains accepted but cannot be applied by the prototype.')
      } else if (body?.status === 'APPLICATION_FAILED') {
        setApplicationResult(body.message ?? 'Candidate application failed; no partial artifact was recorded.')
      } else {
        setApplicationResult('Candidate created for evaluation only. It is not deployed to the live engine.')
      }
      onRefresh()
    } catch (applyError) {
      setError(applyError instanceof Error ? applyError.message : 'Candidate application failed.')
    } finally {
      setPending(false)
    }
  }

  async function evaluateCandidate() {
    if (!reviewer || pending || proposal.state !== 'APPLIED' || !candidate) return
    setPending(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/api/improvement-proposals/${encodeURIComponent(proposal.proposal_id)}/evaluate?user_id=${encodeURIComponent(userId)}`, { method: 'POST' })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) onAuthorizationFailure()
        throw new Error(body?.detail ?? 'Offline evaluation could not be completed.')
      }
      setEvaluation(body)
      await loadDetails()
      onRefresh()
    } catch (evaluationError) {
      setError(evaluationError instanceof Error ? evaluationError.message : 'Offline evaluation failed.')
    } finally {
      setPending(false)
    }
  }

  async function rollbackCandidate() {
    if (!reviewer || pending || !candidate || rollbackReason.trim().length === 0 || rollbackReason.length > 1000) return
    if (!window.confirm('Roll back this evaluation-only candidate? Its proposal and evaluation history will remain. The live engine was never changed.')) return
    setPending(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE}/api/improvement-proposals/${encodeURIComponent(proposal.proposal_id)}/rollback?user_id=${encodeURIComponent(userId)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: rollbackReason.trim() }),
      })
      const body = await response.json().catch(() => null)
      if (!response.ok) {
        if (response.status === 403 || response.status === 404) onAuthorizationFailure()
        throw new Error(body?.detail ?? 'Candidate rollback failed.')
      }
      setCandidate(body)
      await loadDetails()
      onRefresh()
    } catch (rollbackError) {
      setError(rollbackError instanceof Error ? rollbackError.message : 'Candidate rollback failed.')
    } finally {
      setPending(false)
    }
  }

  const trace = buildLearningTrace(proposal, feedback, candidate ?? undefined, evaluation ? [evaluation] : [])
  const actions = candidateActionAvailability(proposal, candidate, reviewer)
  const nextStep = nextLearningStep(proposal)

  return <div className="candidate-learning-panel">
    <div className="learning-trace-block">
      <strong>Learning-loop trace</strong>
      <ol className="learning-trace">{trace.map(step => <li key={step.id}>
        <span className={`feedback-state ${feedbackStateTone(step.state)}`}>{step.label}</span>
        <span>{step.id}</span>
        {step.at && <small>{formatDate(step.at)}</small>}
        {step.actor && <small>{step.actor}</small>}
        {step.reason && <small>{step.reason}</small>}
      </li>)}</ol>
      {nextStep && <p className="learning-next-step">Next permitted step: {nextStep}</p>}
    </div>

    {proposal.state === 'ACCEPTED' && <section className="candidate-application-block">
      <div><strong>Candidate application</strong><p>{proposalLabels(proposal.proposal_type)} · {proposal.target_artifact_type} · base {proposal.before_version}</p><pre>{safeJson(proposal.proposed_change)}</pre></div>
      <p className="safety-note">Application creates an evaluation-only candidate. It does not change the live engine.</p>
      {actions.unsupported
        ? <p className="alert info"><strong>APPLICATION_NOT_SUPPORTED</strong> This proposal remains accepted but cannot be applied by the prototype.</p>
        : actions.showApply && <button type="button" className="run-button" disabled={!reviewer || pending} onClick={() => void applyCandidate()}>{pending ? 'Creating candidate…' : 'Create evaluation candidate'}</button>}
      {applicationResult && <p className="alert info" role="status">{applicationResult}</p>}
    </section>}

    {error && <p className="alert error" role="alert">{error}</p>}
    {loading && proposal.candidate_artifact_id && <p>Loading candidate details…</p>}
    {candidate && <section className="candidate-artifact-block">
      <div className="candidate-safety-banner"><strong>{candidate.evaluation_only ? 'Evaluation only' : 'Not evaluation only'}</strong><span>{candidate.deployed ? 'Deployed to the live engine' : 'Not deployed to the live engine'}</span></div>
      <div className="feedback-review-heading"><div><h4>Candidate artifact</h4><p><StateBadge state={candidate.candidate_state} /></p></div><span className="feedback-state neutral">{candidate.activation_status}</span></div>
      <dl className="candidate-details">
        <dt>Candidate ID</dt><dd>{candidate.candidate_artifact_id}</dd>
        <dt>Proposal ID</dt><dd>{candidate.proposal_id}</dd>
        <dt>Artifact type</dt><dd>{candidate.artifact_type}</dd>
        <dt>KPI / scope</dt><dd>{candidate.kpi_id} · {Object.entries(candidate.scope).map(([key, value]) => `${key}: ${value}`).join(' · ')}</dd>
        <dt>Base version</dt><dd>{candidate.base_version}</dd>
        <dt>Candidate version</dt><dd>{candidate.candidate_version}</dd>
        <dt>Payload hash</dt><dd>{candidate.payload_hash}</dd>
        <dt>Created by / at</dt><dd>{candidate.created_by} · {formatDate(candidate.created_at)}</dd>
        <dt>Lifecycle</dt><dd>{candidate.candidate_state} · {candidate.rollback_status}</dd>
      </dl>
      <details className="feedback-history"><summary>Structured candidate change</summary><pre>{safeJson(candidate.candidate_payload)}</pre></details>
      <details className="feedback-history"><summary>Candidate event history ({candidate.events.length})</summary><ol>{candidate.events.map(event => <li key={event.event_id}><StateBadge state={event.event_type} /> {event.actor_persona} · {formatDate(event.created_at)}{event.reason ? ` · ${event.reason}` : ''}</li>)}</ol></details>

      {actions.showEvaluate && reviewer && <section className="offline-evaluation-plan">
        <h4>Offline evaluation plan</h4>
        <p>{candidate.evaluation_plan.input_policy}</p>
        <p>An LLM does not determine whether these gates pass.</p>
        <div className="evaluation-plan-grid"><div><strong>Affected cases</strong>{candidate.evaluation_plan.affected_cases.map(item => <small key={item.run_id}>{item.run_id} · {item.target_date} · as-of {item.as_of}</small>)}</div><div><strong>Holdout cases</strong>{candidate.evaluation_plan.holdout_cases.map(item => <small key={item.run_id}>{item.run_id} · {item.target_date} · as-of {item.as_of}</small>)}{!candidate.evaluation_plan.holdout_cases.length && <small>No compatible authorized holdout was available.</small>}</div></div>
        <details className="feedback-history"><summary>Deterministic acceptance gates</summary><ol>{candidate.evaluation_plan.gates.map(gate => <li key={gate.gate_id}><strong>{gate.gate_id}</strong> · {gate.description}</li>)}</ol></details>
        <button type="button" className="run-button" disabled={!reviewer || pending} onClick={() => void evaluateCandidate()}>{pending ? 'Evaluating…' : 'Run offline evaluation'}</button>
      </section>}

      {evaluation && <section className="offline-evaluation-results">
        <div className="feedback-review-heading"><div><h4>Evaluation result</h4><p><StateBadge state={evaluation.final_result} /> · {evaluation.evaluation_run_id}</p></div><span>{evaluation.baseline_artifact_version} → {evaluation.candidate_artifact_version}</span></div>
        <p>{evaluation.final_result === 'VERIFIED' ? 'Verified in offline evaluation; not deployed to the live engine.' : 'The candidate failed offline verification and has not changed the live engine.'}</p>
        <div className="evaluation-metadata"><span>Started {formatDate(evaluation.started_at)}</span><span>Completed {formatDate(evaluation.completed_at)}</span><span>{evaluation.evaluator_method} · v{evaluation.evaluator_version}</span></div>
        <div className="evaluation-gate-list"><strong>Acceptance gates</strong>{Object.entries(evaluation.gates).map(([gate, passed]) => <p key={gate}><StateBadge state={passed ? 'ACCEPTED' : 'REJECTED'} /> {gate}</p>)}</div>
        {evaluation.failure_reasons.length > 0 && <div className="alert error"><strong>Failed gates</strong><ul>{evaluation.failure_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul></div>}
        <div className="evaluation-case-list">{evaluation.case_results.map(item => <details className="evaluation-case" key={`${item.case_kind}-${item.case_id}`}>
          <summary>{item.case_kind}: {item.case_id} · as-of {item.as_of}</summary>
          <div><span>Baseline outcome: {item.baseline_result.broad_outcome as string}</span><span>Candidate outcome: {item.candidate_result.broad_outcome as string}</span></div>
          <p>Case gates: {Object.entries(item.gate_results).map(([gate, passed]) => `${gate}: ${passed ? 'PASS' : 'FAIL'}`).join(' · ')}</p>
          <p>Differences</p><pre>{safeJson(item.differences)}</pre>
          {item.candidate_result.narrative && <><p>Candidate narrative</p><blockquote>{item.candidate_result.narrative as string}</blockquote></>}
        </details>)}</div>
      </section>}

      {actions.showRollback && <section className="candidate-rollback-block">
        <h4>Retire candidate</h4>
        <label>Rollback reason<textarea value={rollbackReason} maxLength={1000} rows={2} onChange={event => setRollbackReason(event.target.value)} required /></label>
        <small>{rollbackReason.length}/1,000</small>
        <button type="button" className="reject-button" disabled={pending || !rollbackReason.trim()} onClick={() => void rollbackCandidate()}>{pending ? 'Rolling back…' : 'Roll back candidate'}</button>
      </section>}
      {candidate.rollback_status === 'ROLLED_BACK' && <p className="alert info"><strong>ROLLED_BACK</strong> The candidate was retired. The live engine was unchanged. Proposal and evaluation history remain available.</p>}
    </section>}
  </div>
}

function proposalLabels(type: string) {
  return type.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, character => character.toUpperCase())
}
