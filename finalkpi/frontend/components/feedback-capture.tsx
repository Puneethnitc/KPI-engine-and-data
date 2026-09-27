'use client'

import { useState } from 'react'
import {
  ACTION_TAKEN_VALUES,
  ANALYST_ISSUES,
  BUSINESS_RATINGS,
  BUSINESS_REASONS,
  buildAnalystCorrectionRequest,
  buildBusinessFeedbackRequest,
  feedbackEvidenceOptions,
  feedbackSuccessMessage,
  feedbackTargetOptions,
  postFeedbackRequest,
  type ActionTaken,
  type AnalystIssueCategory,
  type AuthorizedRunForFeedback,
  type BusinessRating,
  type BusinessReason,
  type FeedbackTargetType,
} from '../lib/feedback-learning'

const targetTypeLabels: Record<FeedbackTargetType, string> = {
  RUN: 'Diagnosis run', KPI: 'KPI', MOVEMENT: 'Movement', RECONCILIATION: 'Reconciliation',
  DRIVER: 'Driver', CONTRIBUTION: 'Contribution', CONFIDENCE: 'Confidence',
  NARRATIVE_CLAIM: 'Narrative claim', ACTION: 'Action',
}

export default function FeedbackCapture({
  run,
  userId,
  reviewer,
  disabled = false,
}: {
  run: AuthorizedRunForFeedback
  userId: string
  reviewer: boolean
  disabled?: boolean
}) {
  const targets = feedbackTargetOptions(run)
  const [mode, setMode] = useState<'BUSINESS_FEEDBACK' | 'ANALYST_CORRECTION'>('BUSINESS_FEEDBACK')
  const [selectedTarget, setSelectedTarget] = useState(() => targets[0] ? `${targets[0].target_type}:${targets[0].target_id}` : '')
  const target = targets.find(item => `${item.target_type}:${item.target_id}` === selectedTarget)
  const [rating, setRating] = useState<BusinessRating>('USEFUL')
  const [reason, setReason] = useState<BusinessReason | ''>('')
  const [comment, setComment] = useState('')
  const [actionTaken, setActionTaken] = useState<ActionTaken | ''>('')
  const [outcome, setOutcome] = useState('')
  const [issue, setIssue] = useState<AnalystIssueCategory>('DRIVER')
  const [correctionType, setCorrectionType] = useState('REINTERPRET')
  const [proposedCorrection, setProposedCorrection] = useState('')
  const [rationale, setRationale] = useState('')
  const [selectedEvidence, setSelectedEvidence] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const evidenceOptions = feedbackEvidenceOptions(run)

  if (disabled || !targets.length) return null

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!target || saving || (mode === 'ANALYST_CORRECTION' && !reviewer)) return
    setSaving(true)
    setMessage('')
    setError('')
    try {
      const payload = mode === 'BUSINESS_FEEDBACK'
        ? buildBusinessFeedbackRequest({
          run, userId, targetType: target.target_type, targetId: target.target_id,
          rating, reasonCode: reason, comment, actionTaken, outcomeObservation: outcome,
        })
        : buildAnalystCorrectionRequest({
          run, userId, reviewer, targetType: target.target_type, targetId: target.target_id,
          issueCategory: issue, correctionType, proposedCorrection, rationale,
          evidenceRefs: selectedEvidence,
        })
      await postFeedbackRequest(payload)
      setMessage(feedbackSuccessMessage(mode))
      setComment('')
      setReason('')
      setActionTaken('')
      setOutcome('')
      setCorrectionType('REINTERPRET')
      setProposedCorrection('')
      setRationale('')
      setSelectedEvidence([])
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Feedback could not be submitted. Your entries are still here.')
    } finally {
      setSaving(false)
    }
  }

  return <section className="card feedback-capture">
    <div className="section-heading compact">
      <div><span className="eyebrow">Feedback</span><h2>Review this diagnosis</h2></div>
      {reviewer && <div className="feedback-mode-tabs" role="group" aria-label="Feedback mode">
        <button type="button" className={mode === 'BUSINESS_FEEDBACK' ? 'selected' : ''} onClick={() => setMode('BUSINESS_FEEDBACK')}>Business feedback</button>
        <button type="button" className={mode === 'ANALYST_CORRECTION' ? 'selected' : ''} onClick={() => setMode('ANALYST_CORRECTION')}>Analyst correction</button>
      </div>}
    </div>
    <form className="feedback-capture-form" onSubmit={event => void submit(event)}>
      <label>Target
        <select value={selectedTarget} onChange={event => setSelectedTarget(event.target.value)} required>
          {targets.map(option => <option key={`${option.target_type}:${option.target_id}`} value={`${option.target_type}:${option.target_id}`}>{targetTypeLabels[option.target_type]} · {option.label}</option>)}
        </select>
      </label>
      {mode === 'BUSINESS_FEEDBACK' ? <>
        <label>Rating
          <select value={rating} onChange={event => setRating(event.target.value as BusinessRating)}>
            {BUSINESS_RATINGS.map(value => <option key={value} value={value}>{value === 'USEFUL' ? 'Useful' : 'Not useful'}</option>)}
          </select>
        </label>
        <label>Reason <span className="form-optional">Optional</span>
          <select value={reason} onChange={event => setReason(event.target.value as BusinessReason | '')}>
            <option value="">Choose a reason</option>
            {BUSINESS_REASONS.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ').toLowerCase()}</option>)}
          </select>
        </label>
        <label>Action taken <span className="form-optional">Optional</span>
          <select value={actionTaken} onChange={event => setActionTaken(event.target.value as ActionTaken | '')}>
            <option value="">Not specified</option>
            {ACTION_TAKEN_VALUES.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ').toLowerCase()}</option>)}
          </select>
        </label>
        <label className="feedback-wide">Comment <span className="form-optional">Optional</span>
          <textarea value={comment} maxLength={1000} rows={3} onChange={event => setComment(event.target.value)} aria-label="Feedback comment" />
          <small>{comment.length}/1,000</small>
        </label>
        <label className="feedback-wide">Outcome observation <span className="form-optional">Optional</span>
          <textarea value={outcome} maxLength={1000} rows={2} onChange={event => setOutcome(event.target.value)} aria-label="Outcome observation" />
          <small>{outcome.length}/1,000</small>
        </label>
      </> : <>
        <p className="feedback-wide feedback-boundary">Submitting a correction does not modify the historical diagnosis or production rules.</p>
        <label>Issue category
          <select value={issue} onChange={event => setIssue(event.target.value as AnalystIssueCategory)}>
            {ANALYST_ISSUES.map(value => <option key={value} value={value}>{value.replaceAll('_', ' ').toLowerCase()}</option>)}
          </select>
        </label>
        <label>Correction type
          <input value={correctionType} maxLength={64} onChange={event => setCorrectionType(event.target.value)} required />
          <small>{correctionType.length}/64</small>
        </label>
        <label className="feedback-wide">Proposed correction
          <textarea value={proposedCorrection} maxLength={2000} rows={3} onChange={event => setProposedCorrection(event.target.value)} required />
          <small>{proposedCorrection.length}/2,000</small>
        </label>
        <label className="feedback-wide">Rationale
          <textarea value={rationale} maxLength={2000} rows={3} onChange={event => setRationale(event.target.value)} required />
          <small>{rationale.length}/2,000</small>
        </label>
        {!!evidenceOptions.length && <fieldset className="feedback-wide feedback-evidence-options">
          <legend>Supporting evidence references <span className="form-optional">Optional</span></legend>
          {evidenceOptions.map(reference => <label key={reference}><input type="checkbox" checked={selectedEvidence.includes(reference)} onChange={event => setSelectedEvidence(current => event.target.checked ? [...current, reference] : current.filter(item => item !== reference))} />{reference}</label>)}
        </fieldset>}
      </>}
      <div className="feedback-submit-row feedback-wide">
        <button type="submit" className="run-button" disabled={saving || !target || (mode === 'ANALYST_CORRECTION' && !reviewer)}>{saving ? 'Submitting…' : 'Submit feedback'}</button>
        {message && <span className="feedback-success" role="status">{message}</span>}
        {error && <span className="feedback-error" role="alert">{error}</span>}
      </div>
    </form>
  </section>
}
