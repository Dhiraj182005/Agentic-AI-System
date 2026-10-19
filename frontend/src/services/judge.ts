import request from './api'

export type JudgmentOutcome = 'winner' | 'tie' | 'inconclusive'

export interface AgentDimensions {
  logical_soundness: number | null
  evidence_quality: number | null
  factual_support: number | null
  relevance: number | null
  effectiveness: number | null
  completeness: number | null
  fallacy_risk: number | null
}

export interface AgentScoreCard {
  agent_id: string
  agent_name: string
  agent_role: string
  dimensions: AgentDimensions
  unavailable_dimensions: string[]
  final_score: number
  strengths: string[]
  weaknesses: string[]
  reasoning_quality: string
  evidence_quality_assessment: string
  factual_support_assessment: string
  fallacy_impact_assessment: string
  confidence: string
  limitations: string[]
}

export interface Judgment {
  id: string
  debate_id: string
  status: string
  overall_score: number
  outcome: JudgmentOutcome
  winner_agent_id: string | null
  winner_name: string | null
  summary: string
  limitations: string[] | null
  scoring_rubric: Record<string, unknown>
  agent_scores: AgentScoreCard[]
  created_at: string
  updated_at: string
}

export const OUTCOME_LABELS: Record<JudgmentOutcome, string> = {
  winner: 'Winner Decided',
  tie: 'Tie',
  inconclusive: 'Inconclusive',
}

export const DIMENSION_LABELS: Record<keyof AgentDimensions, string> = {
  logical_soundness: 'Logical Soundness',
  evidence_quality: 'Evidence Quality',
  factual_support: 'Factual Support',
  relevance: 'Relevance',
  effectiveness: 'Effectiveness',
  completeness: 'Completeness',
  fallacy_risk: 'Fallacy Risk',
}

export const DIMENSION_KEYS: (keyof AgentDimensions)[] = [
  'logical_soundness',
  'evidence_quality',
  'factual_support',
  'relevance',
  'effectiveness',
  'completeness',
  'fallacy_risk',
]

export function outcomeLabel(outcome: string): string {
  return (
    OUTCOME_LABELS[outcome as JudgmentOutcome] ??
    outcome.charAt(0).toUpperCase() + outcome.slice(1)
  )
}

export function dimensionDisplay(value: number | null): string {
  if (value === null || value === undefined) return 'Unavailable'
  return Number.isInteger(value) ? `${value}/10` : `${value.toFixed(1)}/10`
}

export function overallDisplay(score: number): string {
  return Number.isInteger(score) ? `${score}/10` : `${score.toFixed(2)}/10`
}

export async function generateJudgment(debateId: string): Promise<Judgment> {
  return request<Judgment>(`/api/v1/debates/${debateId}/judge`, {
    method: 'POST',
  }, true)
}

export async function getJudgment(debateId: string): Promise<Judgment> {
  return request<Judgment>(`/api/v1/debates/${debateId}/judgment`, {}, true)
}
