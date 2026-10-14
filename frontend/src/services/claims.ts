import request from './api'

export type ClaimType = 'factual' | 'opinion' | 'prediction' | 'definition' | 'other'

export interface Claim {
  id: string
  debate_id: string
  message_id: string
  agent_id: string
  agent_name: string
  text: string
  claim_type: ClaimType
  position: number
  created_at: string
}

export interface ClaimListResponse {
  debate_id: string
  claims: Claim[]
}

export interface EvidenceItem {
  id: string
  claim_id: string
  title: string
  url: string
  snippet: string
  source_name: string
  relevance_score: number | null
  retrieved_at: string
}

export interface EvidenceListResponse {
  claim_id: string
  evidence: EvidenceItem[]
}

export const CLAIM_TYPE_LABELS: Record<ClaimType, string> = {
  factual: 'Factual',
  opinion: 'Opinion',
  prediction: 'Prediction',
  definition: 'Definition',
  other: 'Other',
}

export type Verdict = 'supported' | 'contradicted' | 'insufficient_evidence'

export type Confidence = 'low' | 'medium' | 'high'

export interface ClaimVerification {
  id: string
  claim_id: string
  verdict: Verdict
  confidence: Confidence
  explanation: string
  evidence_summary: string
  evidence_ids: string[]
  created_at: string
  updated_at: string
}

export const VERDICT_LABELS: Record<Verdict, string> = {
  supported: 'Supported',
  contradicted: 'Contradicted',
  insufficient_evidence: 'Insufficient Evidence',
}

export const CONFIDENCE_LABELS: Record<Confidence, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
}

export function verdictLabel(verdict: string): string {
  return (
    VERDICT_LABELS[verdict as Verdict] ?? verdict.replace(/_/g, ' ')
  )
}

export function confidenceLabel(confidence: string): string {
  return (
    CONFIDENCE_LABELS[confidence as Confidence] ??
    confidence.charAt(0).toUpperCase() + confidence.slice(1)
  )
}

export function claimTypeLabel(claimType: string): string {
  return (
    CLAIM_TYPE_LABELS[claimType as ClaimType] ?? claimType.charAt(0).toUpperCase() + claimType.slice(1)
  )
}

export async function extractClaims(debateId: string): Promise<ClaimListResponse> {
  return request<ClaimListResponse>(
    `/api/v1/debates/${debateId}/claims/extract`,
    { method: 'POST' },
    true,
  )
}

export async function getClaims(debateId: string): Promise<ClaimListResponse> {
  return request<ClaimListResponse>(`/api/v1/debates/${debateId}/claims`, {}, true)
}

export async function retrieveEvidence(claimId: string): Promise<EvidenceListResponse> {
  return request<EvidenceListResponse>(
    `/api/v1/claims/${claimId}/evidence/retrieve`,
    { method: 'POST' },
    true,
  )
}

export async function getEvidence(claimId: string): Promise<EvidenceListResponse> {
  return request<EvidenceListResponse>(`/api/v1/claims/${claimId}/evidence`, {}, true)
}

export async function verifyClaim(claimId: string): Promise<ClaimVerification> {
  return request<ClaimVerification>(
    `/api/v1/claims/${claimId}/verify`,
    { method: 'POST' },
    true,
  )
}

export async function getVerification(claimId: string): Promise<ClaimVerification> {
  return request<ClaimVerification>(
    `/api/v1/claims/${claimId}/verification`,
    {},
    true,
  )
}
