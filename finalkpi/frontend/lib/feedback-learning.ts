export const FEEDBACK_MODES = ['BUSINESS_FEEDBACK', 'ANALYST_CORRECTION'] as const
export type FeedbackMode = typeof FEEDBACK_MODES[number]

export const FEEDBACK_TARGET_TYPES = [
  'RUN', 'KPI', 'MOVEMENT', 'RECONCILIATION', 'DRIVER', 'CONTRIBUTION',
  'CONFIDENCE', 'NARRATIVE_CLAIM', 'ACTION',
] as const
export type FeedbackTargetType = typeof FEEDBACK_TARGET_TYPES[number]

export const BUSINESS_RATINGS = ['USEFUL', 'NOT_USEFUL'] as const
export type BusinessRating = typeof BUSINESS_RATINGS[number]
export const BUSINESS_REASONS = [
  'ACTIONABLE', 'NOT_ACTIONABLE', 'INCORRECT', 'UNCLEAR', 'TOO_LATE', 'ALREADY_KNOWN', 'OTHER',
] as const
export type BusinessReason = typeof BUSINESS_REASONS[number]
export const ACTION_TAKEN_VALUES = ['YES', 'NO', 'NOT_APPLICABLE', 'UNKNOWN'] as const
export type ActionTaken = typeof ACTION_TAKEN_VALUES[number]
export const ANALYST_ISSUES = [
  'DATA', 'KPI_CONTRACT', 'BUSINESS_RULE', 'DRIVER', 'ANALYTICAL_METHOD',
  'CONFIDENCE', 'NARRATIVE', 'ACTION', 'ACCESS_POLICY',
] as const
export type AnalystIssueCategory = typeof ANALYST_ISSUES[number]

export type FeedbackEvent = {
  event_id: number
  feedback_id: string
  event_type: string
  from_state: string | null
  to_state: string
  actor_user_id: string
  actor_persona: string
  reason: string | null
  created_at: string
}

export type FeedbackRecord = {
  feedback_id: string
  legacy?: boolean
  mode?: FeedbackMode
  feedback_type?: string
  run_id: string
  user_id: string
  persona?: string
  kpi_id: string
  scope?: Record<string, string>
  target_type: FeedbackTargetType | string
  target_id: string | null
  state?: 'CAPTURED' | 'TRIAGED' | 'ACCEPTED' | 'REJECTED' | string
  status?: string
  created_at: string
  rating?: BusinessRating | null
  reason_code?: BusinessReason | null
  comment?: string | null
  action_taken?: ActionTaken | null
  outcome_observation?: string | null
  issue_category?: AnalystIssueCategory | null
  correction_type?: string | null
  proposed_correction?: string | null
  rationale?: string | null
  evidence_refs?: string[]
  events?: FeedbackEvent[]
  versions?: Record<string, unknown>
  comments?: string | null
}

export type ProposalType =
  | 'REVIEW_REQUIRED' | 'KPI_CONTRACT_CHANGE' | 'DATA_QUALITY_FIX'
  | 'DRIVER_CONFIGURATION_CHANGE' | 'BUSINESS_RULE_CHANGE' | 'ANALYTICAL_METHOD_REVIEW'
  | 'CONFIDENCE_POLICY_CHANGE' | 'NARRATIVE_TEMPLATE_CHANGE' | 'ACTION_POLICY_CHANGE'
  | 'ACCESS_POLICY_REVIEW' | 'EVALUATION_CASE_ADDITION'

export type ProposalField = {
  name: string
  label: string
  max_length?: number
  options?: string[]
  source?: string
}

export type ProposalTypeOption = {
  proposal_type: ProposalType
  target_artifact_type: string
  fields: ProposalField[]
}

export type FeedbackAggregation = {
  aggregation_key: string
  kpi_id: string
  scope: Record<string, string>
  target_type: FeedbackTargetType
  target_id: string
  mode: FeedbackMode
  feedback_count: number
  business_feedback_count: number
  analyst_correction_count: number
  useful_count: number
  not_useful_count: number
  reason_counts: Record<string, number>
  issue_category_counts: Record<string, number>
  correction_type_counts: Record<string, number>
  action_taken_counts: Record<string, number>
  unique_authorized_submitter_count: number
  earliest_created_at: string
  latest_created_at: string
  source_feedback_ids: string[]
  affected_run_ids: string[]
  current_artifact_versions: Record<string, unknown>
  proposal_type_options: ProposalTypeOption[]
  message: 'Feedback aggregated' | string
}

export type ProposalEvent = {
  event_id: number
  proposal_id: string
  event_type: string
  from_state: string | null
  to_state: string
  actor_user_id: string
  actor_persona: string
  reason: string | null
  created_at: string
}

export type ImprovementProposal = {
  proposal_id: string
  aggregation_key: string
  proposal_type: ProposalType
  title: string
  rationale: string
  kpi_id: string
  scope: Record<string, string>
  target_type: FeedbackTargetType
  target_id: string
  source_feedback_ids: string[]
  source_run_ids: string[]
  issue_reason_summary: Record<string, unknown>
  target_artifact_type: string
  before_version: string
  before_version_hash: string | null
  proposed_change: Record<string, unknown>
  supporting_feedback_summary: Record<string, unknown>
  supporting_evidence_refs?: { feedback_id: string; evidence_refs: string[] }[]
  expected_improvement: string
  affected_evaluation_cases: string[]
  rollback_plan: string
  created_by?: string
  created_at?: string
  state: 'PROPOSED' | 'ACCEPTED' | 'REJECTED' | string
  application_support?: 'SUPPORTED' | 'APPLICATION_NOT_SUPPORTED' | string
  candidate_artifact_id?: string | null
  candidate_version?: string | null
  evaluation_run_ids?: string[]
  events: ProposalEvent[]
  application_status: string
  verification_status: string
  applied: boolean
  verified: boolean
  message: string
}

export type EvaluationPlan = {
  affected_cases: { run_id: string; target_date: string | null; as_of: string | null }[]
  holdout_cases: { run_id: string; target_date: string | null; as_of: string | null }[]
  gates: { gate_id: string; description: string }[]
  evaluator_method: string
  evaluator_version: string
  input_policy: string
  llm_gate_decision: false
  evaluation_only: true
  deployed: false
}

export type CandidateArtifactEvent = {
  event_id: number
  event_type: string
  actor_user_id: string
  actor_persona: string
  reason: string | null
  created_at: string
}

export type CandidateArtifact = {
  candidate_artifact_id: string
  proposal_id: string
  artifact_type: string
  kpi_id: string
  scope: Record<string, string>
  base_version: string
  candidate_version: string
  base_payload: Record<string, unknown>
  validated_change: Record<string, unknown>
  candidate_payload: Record<string, unknown>
  payload_hash: string
  created_by: string
  created_at: string
  activation_status: 'EVALUATION_ONLY' | string
  rollback_of: string | null
  supersedes: string | null
  events: CandidateArtifactEvent[]
  evaluation_run_ids: string[]
  proposal_state: string
  candidate_state: string
  rollback_status: string
  applied: boolean
  verified: boolean
  deployed: false
  evaluation_only: true
  message: string
  evaluation_plan: EvaluationPlan
}

export type EvaluationCaseResult = {
  case_id: string
  case_kind: 'AFFECTED' | 'HOLDOUT' | string
  input_run_id: string
  input_snapshot_hash: string
  as_of: string | null
  baseline_result: Record<string, any>
  candidate_result: Record<string, any>
  differences: Record<string, unknown>
  gate_results: Record<string, boolean>
}

export type ProposalEvaluation = {
  evaluation_run_id: string
  proposal_id: string
  candidate_artifact_id: string
  baseline_artifact_version: string
  candidate_artifact_version: string
  affected_cases: string[]
  holdout_cases: string[]
  metrics: Record<string, number>
  gates: Record<string, boolean>
  baseline_results: Record<string, unknown>
  candidate_results: Record<string, unknown>
  case_differences: Record<string, unknown>
  case_results: EvaluationCaseResult[]
  started_at: string
  completed_at: string
  evaluator_method: string
  evaluator_version: string
  final_result: 'VERIFIED' | 'FAILED_VERIFICATION' | string
  proposal_state: string
  candidate_state: string
  applied: true
  verified: boolean
  failure_reasons: string[]
  inputs_hash: string
  deployed: false
  evaluation_only: true
  rollback_status: string
  message: string
}

export type AuthorizedRunForFeedback = {
  run_id: string
  kpi_id: string
  movement_assessment?: Record<string, unknown> | null
  reconciliation_verdict?: Record<string, unknown> | null
  driver_analysis?: { ranked_drivers?: { driver_id?: string }[]; excluded_drivers?: { driver_id?: string }[] } | null
  correlational_candidates?: { driver_id?: string }[]
  driver_exclusions?: { driver_id?: string }[]
  decomposition?: Record<string, unknown> | null
  decomposition_status?: string | null
  confidence_profile?: Record<string, unknown> | null
  confidence?: Record<string, unknown> | null
  narrative_claims?: unknown[]
  decision_cards?: { action_id?: string }[]
}

export type FeedbackTargetOption = { target_type: FeedbackTargetType; target_id: string; label: string }

function presentObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function leafPaths(value: unknown, prefix: string): string[] {
  const record = presentObject(value)
  if (!record) return []
  return Object.entries(record).flatMap(([key, nested]) => {
    const path = prefix ? `${prefix}.${key}` : key
    const child = presentObject(nested)
    if (child) return leafPaths(child, path)
    return nested == null ? [] : [path]
  })
}

export function feedbackTargetOptions(run: AuthorizedRunForFeedback): FeedbackTargetOption[] {
  const options: FeedbackTargetOption[] = [
    { target_type: 'RUN', target_id: run.run_id, label: 'Diagnosis run' },
    { target_type: 'KPI', target_id: run.kpi_id, label: `KPI: ${run.kpi_id}` },
  ]
  const addLeaves = (type: FeedbackTargetType, value: unknown, root: string, label: string) => {
    options.push(...leafPaths(value, root).map(path => ({ target_type: type, target_id: path.slice(root.length + 1), label: `${label}: ${path.slice(root.length + 1)}` })))
  }
  addLeaves('MOVEMENT', run.movement_assessment, 'movement_assessment', 'Movement')
  addLeaves('RECONCILIATION', run.reconciliation_verdict, 'reconciliation_verdict', 'Reconciliation')
  const driverIds = new Set([
    ...(run.driver_analysis?.ranked_drivers ?? []),
    ...(run.driver_analysis?.excluded_drivers ?? []),
    ...(run.correlational_candidates ?? []),
    ...(run.driver_exclusions ?? []),
  ].flatMap(item => item.driver_id ? [item.driver_id] : []))
  options.push(...[...driverIds].sort().map(id => ({ target_type: 'DRIVER' as const, target_id: id, label: `Driver: ${id}` })))
  addLeaves('CONTRIBUTION', run.decomposition, 'decomposition', 'Contribution')
  addLeaves('CONFIDENCE', run.confidence_profile, 'confidence_profile', 'Confidence')
  addLeaves('CONFIDENCE', run.confidence, 'confidence', 'Confidence')
  ;(run.narrative_claims ?? []).forEach((claim, index) => {
    if (claim && typeof claim === 'object') options.push({ target_type: 'NARRATIVE_CLAIM', target_id: String(index), label: `Narrative claim ${index + 1}` })
  })
  ;(run.decision_cards ?? []).forEach((action, index) => {
    if (action.action_id) options.push({ target_type: 'ACTION', target_id: action.action_id, label: `Action ${action.action_id}` })
    else options.push({ target_type: 'ACTION', target_id: String(index), label: `Action ${index + 1}` })
  })
  return options
}

export function feedbackEvidenceOptions(run: AuthorizedRunForFeedback): string[] {
  const candidates = [
    ['movement_assessment', run.movement_assessment],
    ['reconciliation_verdict', run.reconciliation_verdict],
    ['driver_analysis.ranked_drivers', run.driver_analysis?.ranked_drivers],
    ['driver_analysis.excluded_drivers', run.driver_analysis?.excluded_drivers],
    ['decomposition', run.decomposition],
    ['confidence_profile', run.confidence_profile],
    ['confidence', run.confidence],
    ['narrative_claims', run.narrative_claims],
    ['decision_cards', run.decision_cards],
  ] as const
  return candidates.flatMap(([path, value]) => value == null ? [] : [path])
}

export type BusinessFeedbackInput = {
  run: AuthorizedRunForFeedback
  userId: string
  targetType: FeedbackTargetType
  targetId: string
  rating: BusinessRating
  reasonCode?: BusinessReason | ''
  comment?: string
  actionTaken?: ActionTaken | ''
  outcomeObservation?: string
}

export function buildBusinessFeedbackRequest(input: BusinessFeedbackInput) {
  const targets = feedbackTargetOptions(input.run)
  if (!targets.some(target => target.target_type === input.targetType && target.target_id === input.targetId)) throw new Error('Select a target from this diagnosis.')
  return {
    mode: 'BUSINESS_FEEDBACK' as const,
    run_id: input.run.run_id,
    user_id: input.userId,
    target_type: input.targetType,
    target_id: input.targetId,
    rating: input.rating,
    ...(input.reasonCode ? { reason_code: input.reasonCode } : {}),
    ...(input.comment?.trim() ? { comment: input.comment.trim() } : {}),
    ...(input.actionTaken ? { action_taken: input.actionTaken } : {}),
    ...(input.outcomeObservation?.trim() ? { outcome_observation: input.outcomeObservation.trim() } : {}),
  }
}

export type AnalystCorrectionInput = {
  run: AuthorizedRunForFeedback
  userId: string
  reviewer: boolean
  targetType: FeedbackTargetType
  targetId: string
  issueCategory: AnalystIssueCategory
  correctionType: string
  proposedCorrection: string
  rationale: string
  evidenceRefs: string[]
}

export function buildAnalystCorrectionRequest(input: AnalystCorrectionInput) {
  if (!input.reviewer) throw new Error('Analyst corrections are not available for this persona.')
  if (!feedbackTargetOptions(input.run).some(target => target.target_type === input.targetType && target.target_id === input.targetId)) throw new Error('Select a target from this diagnosis.')
  const validRefs = feedbackEvidenceOptions(input.run)
  if (input.evidenceRefs.some(reference => !validRefs.includes(reference))) throw new Error('Evidence references must come from this diagnosis.')
  return {
    mode: 'ANALYST_CORRECTION' as const,
    run_id: input.run.run_id,
    user_id: input.userId,
    target_type: input.targetType,
    target_id: input.targetId,
    issue_category: input.issueCategory,
    correction_type: input.correctionType.trim(),
    proposed_correction: input.proposedCorrection.trim(),
    rationale: input.rationale.trim(),
    evidence_refs: [...input.evidenceRefs],
  }
}

export async function postFeedbackRequest(
  payload: ReturnType<typeof buildBusinessFeedbackRequest> | ReturnType<typeof buildAnalystCorrectionRequest>,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  const response = await fetcher('/api/backend/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? 'Feedback could not be submitted. Your entries are still here.')
  }
}

export function feedbackSuccessMessage(mode: FeedbackMode): string {
  return mode === 'BUSINESS_FEEDBACK' ? 'Feedback captured for review.' : 'Correction captured for analyst review.'
}

export type FeedbackStateTone = 'neutral' | 'info' | 'good' | 'danger'
export function feedbackStateTone(state?: string): FeedbackStateTone {
  if (state === 'TRIAGED') return 'info'
  if (state === 'ACCEPTED') return 'good'
  if (state === 'REJECTED') return 'danger'
  return 'neutral'
}

export function formatFeedbackState(state?: string): string {
  return state ? state.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase()) : 'Unknown'
}

export function proposalOutcomeFacts(proposal: Pick<ImprovementProposal, 'state' | 'applied' | 'verified' | 'message'>) {
  return {
    accepted: proposal.state === 'ACCEPTED',
    applied: proposal.applied,
    verified: proposal.verified,
    message: proposal.message,
  }
}

export type LearningTraceStep = { id: string; label: string; state: string; at?: string | null; actor?: string; reason?: string | null }

export function buildLearningTrace(
  proposal: ImprovementProposal,
  feedback: FeedbackRecord[],
  candidate?: CandidateArtifact,
  evaluations: ProposalEvaluation[] = [],
): LearningTraceStep[] {
  const feedbackIds = new Set(proposal.source_feedback_ids)
  const steps: LearningTraceStep[] = []
  for (const record of feedback.filter(item => feedbackIds.has(item.feedback_id))) {
    for (const event of record.events ?? []) {
      steps.push({
        id: `feedback-event-${event.event_id}`,
        label: event.event_type === 'SUBMITTED' ? 'Feedback captured' : `Feedback ${formatFeedbackState(event.to_state).toLowerCase()}`,
        state: event.to_state,
        at: event.created_at,
        actor: event.actor_persona,
        reason: event.reason,
      })
    }
  }
  steps.sort((left, right) => (left.at ?? '').localeCompare(right.at ?? ''))
  if (proposal.aggregation_key) steps.push({ id: proposal.aggregation_key, label: 'Feedback aggregated', state: 'AGGREGATED' })
  for (const event of proposal.events ?? []) steps.push({
    id: `proposal-event-${event.event_id}`,
    label: event.event_type === 'PROPOSED' ? 'Improvement proposed' : `Proposal ${formatFeedbackState(event.to_state).toLowerCase()}`,
    state: event.to_state,
    at: event.created_at,
    actor: event.actor_persona,
    reason: event.reason,
  })
  for (const event of candidate?.events ?? []) steps.push({
    id: `candidate-event-${event.event_id}`,
    label: event.event_type === 'CREATED' ? 'Candidate artifact created' : 'Candidate rolled back',
    state: event.event_type,
    at: event.created_at,
    actor: event.actor_persona,
    reason: event.reason,
  })
  for (const evaluation of evaluations) steps.push({
    id: evaluation.evaluation_run_id,
    label: evaluation.final_result === 'VERIFIED' ? 'Offline evaluation verified' : 'Offline evaluation failed',
    state: evaluation.final_result,
    at: evaluation.completed_at,
    actor: evaluation.evaluator_method,
    reason: evaluation.failure_reasons.join(', ') || null,
  })
  return steps
}

export function nextLearningStep(proposal: ImprovementProposal): string | null {
  if (proposal.state === 'PROPOSED') return 'Await authorized proposal review.'
  if (proposal.state === 'ACCEPTED' && proposal.application_support === 'APPLICATION_NOT_SUPPORTED') return 'Application is not supported for this proposal type.'
  if (proposal.state === 'ACCEPTED') return 'Create an evaluation-only candidate.'
  if (proposal.state === 'APPLIED') return 'Run deterministic offline evaluation.'
  if (proposal.state === 'VERIFIED' || proposal.state === 'FAILED_VERIFICATION') return 'Candidate may be rolled back; it is not deployed.'
  if (proposal.state === 'ROLLED_BACK') return 'Candidate retired; history is preserved.'
  return null
}

export function candidateActionAvailability(
  proposal: ImprovementProposal,
  candidate: CandidateArtifact | null,
  reviewer: boolean,
) {
  const rolledBack = candidate?.rollback_status === 'ROLLED_BACK' || proposal.state === 'ROLLED_BACK'
  return {
    showApply: reviewer && proposal.state === 'ACCEPTED' && proposal.application_support === 'SUPPORTED' && !candidate,
    unsupported: proposal.state === 'ACCEPTED' && proposal.application_support === 'APPLICATION_NOT_SUPPORTED',
    showEvaluate: reviewer && proposal.state === 'APPLIED' && !!candidate && !rolledBack,
    showRollback: reviewer && !!candidate && !rolledBack && ['APPLIED', 'VERIFIED', 'FAILED_VERIFICATION'].includes(proposal.state),
    rolledBack,
  }
}

export function candidateDeploymentFacts(candidate: CandidateArtifact) {
  return {
    evaluationOnly: candidate.evaluation_only,
    deployed: candidate.deployed,
    baseVersion: candidate.base_version,
    candidateVersion: candidate.candidate_version,
    artifactId: candidate.candidate_artifact_id,
    payloadHash: candidate.payload_hash,
  }
}

export function proposalCreatePayload(input: {
  userId: string
  aggregation: FeedbackAggregation
  proposalType: ProposalType
  sourceFeedbackId?: string
  title: string
  rationale: string
  changeFields: Record<string, string>
  expectedImprovement: string
  affectedCases: string[]
  rollbackPlan: string
}) {
  const option = input.aggregation.proposal_type_options.find(item => item.proposal_type === input.proposalType)
  if (!option) throw new Error('This proposal type is not compatible with the selected feedback.')
  let proposedChange: Record<string, unknown> | null = null
  if (input.proposalType === 'REVIEW_REQUIRED') {
    proposedChange = null
  } else if (input.proposalType === 'EVALUATION_CASE_ADDITION') {
    proposedChange = { case_description: input.changeFields.case_description?.trim() ?? '', expected_outcome: input.changeFields.expected_outcome ?? '' }
  } else {
    const sourceCorrection = input.sourceFeedbackId
    if (!sourceCorrection || !input.aggregation.source_feedback_ids.includes(sourceCorrection)) throw new Error('Select a correction from this aggregation.')
    proposedChange = {
      source_feedback_id: sourceCorrection,
      [option.fields[0]?.name ?? '']: input.changeFields[option.fields[0]?.name ?? '']?.trim() ?? '',
      [option.fields[1]?.name ?? '']: input.changeFields[option.fields[1]?.name ?? '']?.trim() ?? '',
    }
  }
  return {
    user_id: input.userId,
    aggregation_key: input.aggregation.aggregation_key,
    proposal_type: input.proposalType,
    title: input.title.trim(),
    rationale: input.rationale.trim(),
    proposed_change: proposedChange,
    expected_improvement: input.expectedImprovement.trim(),
    affected_evaluation_cases: input.affectedCases,
    rollback_plan: input.rollbackPlan.trim(),
  }
}
