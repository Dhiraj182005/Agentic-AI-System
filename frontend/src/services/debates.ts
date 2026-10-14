import request from './api'

export interface CoreAgent {
  id: string
  name: string
  role: string
  description: string
}

export interface DebateAgent {
  id: string
  name: string
  role: string
  description: string
}

export interface Debate {
  id: string
  topic: string
  expert_selection_mode: 'manual' | 'auto'
  domain_tags: string[] | null
  status: string
  mode: string
  total_rounds: number
  round_count: number
  verify_evidence: boolean
  agents: DebateAgent[]
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface TranscriptMessage {
  id: string
  round_number: number
  turn_number: number
  agent: { id: string; name: string; role: string }
  message_type: string
  content: string
  created_at: string
}

export interface TranscriptResponse {
  debate_id: string
  messages: TranscriptMessage[]
}

export interface DebateRound {
  round_number: number
  status: string
  started_at: string | null
  completed_at: string | null
}

export interface DebateRoundsResponse {
  debate_id: string
  rounds: DebateRound[]
}

export interface DebateListResponse {
  items: Debate[]
}

export interface CreateDebateInput {
  topic: string
  expert_selection_mode: 'manual' | 'auto'
  agent_ids: string[]
  domain_tags: string[] | null
  mode: 'balanced' | 'pro_con'
  total_rounds: number
  verify_evidence: boolean
}

export const MIN_AGENTS = 2
export const MIN_ROUNDS = 1
export const MAX_ROUNDS = 10
export const MAX_TOPIC_LENGTH = 1000

export const DEBATE_MODES: { value: 'balanced' | 'pro_con'; label: string }[] = [
  { value: 'balanced', label: 'Balanced' },
  { value: 'pro_con', label: 'Pro / Con' },
]

export function debateStatusLabel(status: string): string {
  switch (status) {
    case 'pending':
      return 'Created (waiting to start)'
    case 'running':
      return 'Running'
    case 'completed':
      return 'Completed'
    case 'failed':
      return 'Failed'
    case 'cancelled':
      return 'Cancelled'
    default:
      return status
  }
}

export async function listCoreAgents(): Promise<CoreAgent[]> {
  return request<CoreAgent[]>('/api/v1/agents', {}, true)
}

export async function createDebate(input: CreateDebateInput): Promise<Debate> {
  return request<Debate>(
    '/api/v1/debates',
    { method: 'POST', body: JSON.stringify(input) },
    true,
  )
}

export async function listDebates(): Promise<DebateListResponse> {
  return request<DebateListResponse>('/api/v1/debates', {}, true)
}

export async function getDebate(id: string): Promise<Debate> {
  return request<Debate>(`/api/v1/debates/${id}`, {}, true)
}

export async function startDebate(id: string): Promise<Debate> {
  return request<Debate>(
    `/api/v1/debates/${id}/start`,
    { method: 'POST' },
    true,
  )
}

export async function getTranscript(id: string): Promise<TranscriptResponse> {
  return request<TranscriptResponse>(`/api/v1/debates/${id}/messages`, {}, true)
}

export async function getRounds(id: string): Promise<DebateRoundsResponse> {
  return request<DebateRoundsResponse>(`/api/v1/debates/${id}/rounds`, {}, true)
}

export function debateStatusTone(status: string): string {
  switch (status) {
    case 'pending':
      return 'border-gray-700 text-gray-300'
    case 'running':
      return 'border-blue-700 bg-blue-950/60 text-blue-300'
    case 'completed':
      return 'border-emerald-800 bg-emerald-950/60 text-emerald-300'
    case 'failed':
      return 'border-red-800 bg-red-950/60 text-red-300'
    case 'cancelled':
      return 'border-amber-800 bg-amber-950/60 text-amber-300'
    default:
      return 'border-gray-700 text-gray-300'
  }
}
