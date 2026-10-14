import request from './api'

export type FallacyType =
  | 'ad_hominem'
  | 'straw_man'
  | 'false_dilemma'
  | 'slippery_slope'
  | 'appeal_to_authority'
  | 'appeal_to_emotion'
  | 'hasty_generalization'
  | 'circular_reasoning'
  | 'red_herring'
  | 'false_cause'
  | 'bandwagon'
  | 'loaded_question'
  | 'tu_quoque'
  | 'no_fallacy'

export type Severity = 'low' | 'medium' | 'high'

export interface Fallacy {
  id: string | null
  debate_id: string
  message_id: string
  agent_id: string
  agent_name: string
  fallacy_type: FallacyType
  severity: Severity
  confidence: number
  explanation: string
  evidence_span: string | null
  created_at: string | null
}

export interface FallacyListResponse {
  debate_id: string
  fallacies: Fallacy[]
}

export interface FallacyAnalysisListResponse {
  debate_id: string
  analyzed_count: number
  fallacies: Fallacy[]
}

export interface ArgumentEvaluation {
  id: string
  debate_id: string
  message_id: string
  agent_id: string
  agent_name: string
  logical_soundness: number
  evidence_score: number
  relevance_score: number
  effectiveness_score: number
  overall_score: number
  explanation: string
  created_at: string
}

export interface EvaluationListResponse {
  debate_id: string
  evaluations: ArgumentEvaluation[]
}

export const FALLACY_LABELS: Record<FallacyType, string> = {
  ad_hominem: 'Ad Hominem',
  straw_man: 'Straw Man',
  false_dilemma: 'False Dilemma',
  slippery_slope: 'Slippery Slope',
  appeal_to_authority: 'Appeal to Authority',
  appeal_to_emotion: 'Appeal to Emotion',
  hasty_generalization: 'Hasty Generalization',
  circular_reasoning: 'Circular Reasoning',
  red_herring: 'Red Herring',
  false_cause: 'False Cause',
  bandwagon: 'Bandwagon',
  loaded_question: 'Loaded Question',
  tu_quoque: 'Tu Quoque',
  no_fallacy: 'No Fallacy',
}

export const SEVERITY_LABELS: Record<Severity, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
}

export function fallacyLabel(fallacyType: string): string {
  return (
    FALLACY_LABELS[fallacyType as FallacyType] ??
    fallacyType.replace(/_/g, ' ')
  )
}

export function severityLabel(severity: string): string {
  return (
    SEVERITY_LABELS[severity as Severity] ??
    severity.charAt(0).toUpperCase() + severity.slice(1)
  )
}

export function confidencePercent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`
}

export function scoreDisplay(score: number): string {
  return Number.isInteger(score) ? String(score) : score.toFixed(1)
}

export async function analyzeDebateFallacies(
  debateId: string,
): Promise<FallacyAnalysisListResponse> {
  return request<FallacyAnalysisListResponse>(
    `/api/v1/debates/${debateId}/fallacies/analyze`,
    { method: 'POST' },
    true,
  )
}

export async function getDebateFallacies(
  debateId: string,
): Promise<FallacyListResponse> {
  return request<FallacyListResponse>(
    `/api/v1/debates/${debateId}/fallacies`,
    {},
    true,
  )
}

export async function analyzeMessageFallacies(
  messageId: string,
): Promise<Fallacy> {
  return request<Fallacy>(
    `/api/v1/messages/${messageId}/fallacies/analyze`,
    { method: 'POST' },
    true,
  )
}

export async function evaluateMessage(
  messageId: string,
): Promise<ArgumentEvaluation> {
  return request<ArgumentEvaluation>(
    `/api/v1/messages/${messageId}/evaluation`,
    { method: 'POST' },
    true,
  )
}

export async function getDebateEvaluations(
  debateId: string,
): Promise<EvaluationListResponse> {
  return request<EvaluationListResponse>(
    `/api/v1/debates/${debateId}/evaluations`,
    {},
    true,
  )
}
