import request from './api'

export type VerdictPosition = 'supports' | 'opposes' | 'mixed' | 'inconclusive'
export type VerdictConfidence = 'low' | 'medium' | 'high'

export interface VerdictSource {
  title: string
  url: string
  source_name: string
  source_type?: 'web' | 'google_fact_check'
  publisher?: string | null
  external_rating?: string | null
}

export interface FactCheckStageStatus {
  status: 'ok' | 'up_to_date' | 'unavailable' | 'failed' | 'partial'
  searched: number
  matched: number
  no_match: number
  failed: number
  new_items: number
  error: string | null
}

export interface VerdictClaimRef {
  id: string
  text: string
  agent_name: string
  verdict: string | null
  confidence: string | null
  sources: VerdictSource[]
}

export interface VerdictArgument {
  point: string
  agent_name: string | null
  impact: string | null
  claims: VerdictClaimRef[]
}

export interface EvidenceSnapshot {
  total_claims: number
  factual_claims?: number | null
  non_factual_claims?: number
  partially_supported?: number
  supported: number
  contradicted: number
  insufficient_evidence: number
  unverified: number
  evidence_sources: number
  analysis_state?: string
  analysis_failures?: number
  model?: string | null
}

export interface QuestionAssumption {
  assumption: string
  assessment: string
  status: 'supported' | 'contested' | 'unsupported' | 'unclear'
}

export interface SubVerdict {
  question: string
  position: VerdictPosition
  answer: string
}

/** State of the post-debate claim extraction / evidence / verification run. */
export interface AnalysisStatus {
  run_id?: string
  current_stage?: string | null
  stages?: Record<string, { state: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'; started_at?: string; finished_at?: string; summary?: Record<string, unknown>; error?: string }>
  joined?: boolean
  message?: string
  coverage?: {
    agents: number; rounds: number; messages: number; messages_analyzed: number
    fallacy_analyses: number; fallacies_detected: number; quality_evaluations: number
    claims: number; factual_claims: number; claims_verified: number; insufficient_evidence: number
    google_fact_checks: number; tavily_sources: number; failed_operations: number; pending_operations: number
    fallacy_status: string; quality_status: string; verification_status: string; extraction_status: string
    verdict_status: string
    rubric: { version: number; weights: Record<string, number>; formula: string }
    agent_comparisons: { agent_id: string; agent_name: string; messages: number; evaluations: number; average_score: number | null }[]
  }
  fallacy?: { total: number; completed: number; failed: number }
  evaluation?: { total: number; completed: number; failed: number }

  state: 'not_started' | 'running' | 'completed' | 'partial' | 'failed' | string
  trigger?: string
  started_at?: string
  finished_at?: string
  extraction?: 'done' | 'existing' | 'failed' | null
  claims_total?: number
  claims_factual?: number
  claims_selected?: number
  searched?: number
  no_sources?: number
  verified?: number
  already_verified?: number
  failures?: { stage: string; error: string; claim_id?: string }[]
  fact_check?: FactCheckStageStatus | null
  verdict?: string
}

export interface Verdict {
  id: string
  debate_id: string
  position: VerdictPosition
  answer: string
  preferred_position: string | null
  summary: string
  reasoning: string
  supporting_arguments: VerdictArgument[]
  counterarguments: VerdictArgument[]
  confidence: VerdictConfidence
  confidence_basis: string
  limitations: string[]
  unresolved_questions: string[]
  evidence_snapshot: EvidenceSnapshot
  evidence_basis: 'none' | 'partial' | 'substantial'
  inconclusive_reason:
    | 'no_verified_evidence'
    | 'conflicting_evidence'
    | 'incomplete_evidence'
    | 'analysis_incomplete'
    | null
  assumptions?: QuestionAssumption[]
  sub_verdicts?: SubVerdict[]
  stale: boolean
  created_at: string
  updated_at: string
}

export const POSITION_LABELS: Record<VerdictPosition, string> = {
  supports: 'Supports the proposition',
  opposes: 'Opposes the proposition',
  mixed: 'Mixed - depends on conditions',
  inconclusive: 'Inconclusive',
}

export function positionLabel(position: string): string {
  return POSITION_LABELS[position as VerdictPosition] ?? position
}

/** Tailwind classes for the verdict position accent. */
export function positionTone(position: string): string {
  switch (position) {
    case 'supports':
      return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
    case 'opposes':
      return 'border-rose-500/40 bg-rose-500/10 text-rose-300'
    case 'mixed':
      return 'border-sky-500/40 bg-sky-500/10 text-sky-300'
    default:
      return 'border-amber-500/40 bg-amber-500/10 text-amber-300'
  }
}

export const EVIDENCE_BASIS_TEXT: Record<Verdict['evidence_basis'], string> = {
  none: 'No claim is supported or contradicted by stored evidence yet.',
  partial: 'Fewer than half of the claims are backed or refuted by stored evidence.',
  substantial: 'At least half of the claims are backed or refuted by stored evidence.',
}

export const INCONCLUSIVE_REASON_TEXT: Record<
  NonNullable<Verdict['inconclusive_reason']>,
  string
> = {
  no_verified_evidence:
    'Inconclusive because no factual claim could be supported or contradicted by the sources found - not because the question is unanswerable.',
  analysis_incomplete:
    'Inconclusive because the evidence analysis did not finish (a search or verification step failed). This is a technical gap, not evidence about the question - regenerate to retry the missing steps.',
  conflicting_evidence:
    'Inconclusive because the verified evidence points in different directions.',
  incomplete_evidence:
    'Inconclusive because the verified evidence covers too little of the debate to settle the question.',
}

/** What each confidence label means. Not a calibrated probability. */
export const CONFIDENCE_MEANING: Record<VerdictConfidence, string> = {
  low: 'Little or no verified evidence, or evidence that conflicts.',
  medium: 'Some claims verified; the conclusion could change with more evidence.',
  high: 'Most claims verified and consistent with the conclusion.',
}

export async function getVerdict(debateId: string): Promise<Verdict> {
  return request<Verdict>(`/api/v1/debates/${debateId}/verdict`, {}, true)
}

/**
 * Generate or regenerate the verdict. Missing analysis stages (claim
 * extraction, evidence search, verification) run first, so this can take a
 * few minutes on small provider rate limits.
 */
export async function generateVerdict(
  debateId: string,
  regenerate = false,
): Promise<Verdict> {
  const params = new URLSearchParams({ run_missing_analysis: 'true' })
  if (regenerate) params.set('regenerate', 'true')
  return request<Verdict>(
    `/api/v1/debates/${debateId}/verdict?${params.toString()}`,
    { method: 'POST' },
    true,
  )
}

export async function getAnalysisStatus(debateId: string): Promise<AnalysisStatus> {
  return request<AnalysisStatus>(`/api/v1/debates/${debateId}/analysis`, {}, true)
}

export const ASSUMPTION_TONE: Record<QuestionAssumption['status'], string> = {
  supported: 'text-emerald-300 border-emerald-500/40',
  contested: 'text-amber-300 border-amber-500/40',
  unsupported: 'text-rose-300 border-rose-500/40',
  unclear: 'text-gray-300 border-gray-600',
}

export async function startAnalysis(debateId: string, regenerate = false): Promise<AnalysisStatus> {
  return request(`/api/v1/debates/${debateId}/analysis?regenerate=${regenerate}`, { method: 'POST' }, true)
}
