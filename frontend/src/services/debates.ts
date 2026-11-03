import request, { requestBlob } from './api'

export interface CoreAgent {
  id: string
  name: string
  role: string
  description: string
}

export interface SpecialistDefinition {
  name: string
  domain: string
  subdomain: string
  expertise: string
  debate_objective: string
  instructions: string[]
  capabilities: string[]
  reason: string
}

export interface DebateAgent {
  id: string
  name: string
  role: string
  description: string
  /** "builtin" or "dynamic" (debate-scoped AI specialist role). */
  source?: 'builtin' | 'dynamic'
  definition?: (SpecialistDefinition & { provenance?: Record<string, unknown> }) | null
}

export interface Debate {
  id: string
  topic: string
  context: string | null
  expert_selection_mode: 'manual' | 'auto'
  domain_tags: string[] | null
  status: string
  execution_state?: string
  mode: string
  total_rounds: number
  round_count: number
  verify_evidence: boolean
  agents: DebateAgent[]
  created_at: string
  started_at: string | null
  completed_at: string | null
  failure_reason: string | null
}

/** Validated structured turn; null for older free-text messages. */
export interface StructuredTurn {
  position: string
  position_changed: boolean
  main_argument: string
  rebuttal_to: {
    ref: string | null
    message_id: string | null
    agent_name: string | null
    round_number: number | null
    argument: string
  } | null
  reasoning: string
  factual_claims: string[]
  evidence_references: string[]
  concession: string | null
  recommendation: string | null
  uncertainties: string[]
  word_count?: number
}

export interface TranscriptMessage {
  id: string
  round_number: number
  turn_number: number
  agent: { id: string; name: string; role: string }
  message_type: string
  content: string
  structured?: StructuredTurn | null
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
  context: string | null
  specialists?: SpecialistDefinition[]
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
export const MAX_CONTEXT_LENGTH = 2000

export interface RecommendedAgent {
  id: string
  name: string
  role: string
  reason: string
}

export interface TopicAnalysisSummary {
  main_domain: string
  secondary_domains: string[]
  key_questions: string[]
  recommended_agent_count: number
  specialists_rationale: string
}

export interface RecommendAgentsResponse {
  topic: string
  selection_mode: 'auto'
  selection_source: 'llm' | 'fallback'
  agents: RecommendedAgent[]
  analysis?: TopicAnalysisSummary | null
  specialists?: SpecialistDefinition[]
  rejected_specialists?: { name: string; reason: string }[]
  cached?: boolean
}

export const DEBATE_MODES: { value: 'balanced' | 'pro_con'; label: string }[] = [
  { value: 'balanced', label: 'Balanced' },
  { value: 'pro_con', label: 'Pro / Con' },
]

/** "1 round", "3 rounds". */
export function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

export function debateStatusLabel(status: string): string {
  switch (status) {
    case 'created': return 'Created'
    case 'starting': return 'Starting'
    case 'analyzing': return 'Analyzing'
    case 'generating_verdict': return 'Generating verdict'
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

export async function recommendAgents(
  topic: string,
  options: { context?: string; mode?: 'balanced' | 'pro_con' } = {},
): Promise<RecommendAgentsResponse> {
  return request<RecommendAgentsResponse>(
    '/api/v1/debates/recommend-agents',
    {
      method: 'POST',
      body: JSON.stringify({
        topic,
        context: options.context?.trim() || null,
        mode: options.mode ?? 'balanced',
        include_specialists: true,
      }),
    },
    true,
  )
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

/** Continue a failed debate from the failed turn; blocks until it ends. */
export async function resumeDebate(id: string): Promise<Debate> {
  return request<Debate>(
    `/api/v1/debates/${id}/resume`,
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

/**
 * Download the stored-data PDF conclusion report for a debate. The backend
 * answers with application/pdf plus a Content-Disposition filename built from
 * the topic slug; the caller turns the blob into a file save.
 */
export async function downloadDebateReport(
  id: string,
): Promise<{ blob: Blob; filename: string | null }> {
  return requestBlob(`/api/v1/debates/${id}/report.pdf`)
}

export function debateStatusTone(status: string): string {
  switch (status) {
    case 'pending':
      return 'border-gray-700 bg-gray-800/60 text-gray-300'
    case 'running':
      return 'border-blue-700 bg-blue-950/60 text-blue-300'
    case 'completed':
      return 'border-emerald-800 bg-emerald-950/60 text-emerald-300'
    case 'failed':
      return 'border-red-800 bg-red-950/60 text-red-300'
    case 'cancelled':
      return 'border-amber-800 bg-amber-950/60 text-amber-300'
    default:
      return 'border-gray-700 bg-gray-800/60 text-gray-300'
  }
}
