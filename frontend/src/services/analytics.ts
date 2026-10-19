import request from './api'

export interface StatusCount {
  status: string
  count: number
}

export interface DashboardSummary {
  total_debates: number
  completed_debates: number
  running_debates: number
  failed_debates: number
  pending_debates: number
  cancelled_debates: number
  total_messages: number
  total_claims: number
  verified_claims: number
  unverified_claims: number
  debates_with_judgment: number
  completion_rate: number | null
  status_distribution: StatusCount[]
}

export interface ActivityBucket {
  date: string
  count: number
}

export interface DebateActivity {
  days: number
  start_date: string
  end_date: string
  bucket: string
  buckets: ActivityBucket[]
  total_debates_in_range: number
}

export interface NamedCount {
  name: string
  count: number
}

export interface ClaimVerificationStats {
  total_verifications: number
  verdict_counts: NamedCount[]
  confidence_counts: NamedCount[]
  verified_claims: number
  unverified_claims: number
  scope: string
}

export interface DimensionAverage {
  dimension: string
  average: number | null
}

export interface AgentPerformanceItem {
  agent_id: string
  agent_name: string
  agent_role: string
  appearances: number
  average_score: number | null
  dimension_averages: DimensionAverage[]
  strengths: string[]
  weaknesses: string[]
}

export interface AgentPerformanceStats {
  agents: AgentPerformanceItem[]
  judgments_analyzed: number
  available: boolean
}

export interface ArgumentQualityStats {
  available: boolean
  fallacy_available: boolean
  evaluation_available: boolean
  fallacy_total: number
  fallacy_type_counts: NamedCount[]
  severity_counts: NamedCount[]
  fallacy_analyzed_message_count: number
  evaluation_total: number
  evaluated_message_count: number
  unevaluated_message_count: number | null
  dimension_averages: DimensionAverage[]
  notes: string[]
}

export interface RecentDebateItem {
  id: string
  topic: string
  created_at: string
  status: string
  agent_count: number
  round_count: number
  message_count: number
  has_verification: boolean
  has_judgment: boolean
}

export interface RecentDebates {
  debates: RecentDebateItem[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export const ACTIVITY_RANGE_OPTIONS = [7, 30, 90, 365] as const

export function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1)
}

export function verdictLabel(verdict: string): string {
  if (verdict === 'supported') return 'Supported'
  if (verdict === 'contradicted') return 'Contradicted'
  if (verdict === 'insufficient_evidence') return 'Insufficient evidence'
  return verdict.replace(/_/g, ' ')
}

export function dimensionLabel(dimension: string): string {
  return dimension
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function countLabel(name: string): string {
  if (name === 'insufficient_evidence') return 'Insufficient evidence'
  return name
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function percent(value: number, total: number): string {
  if (total <= 0) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

export async function getSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>('/api/v1/analytics/summary', {}, true)
}

export async function getDebateActivity(days: number): Promise<DebateActivity> {
  return request<DebateActivity>(
    `/api/v1/analytics/debate-activity?days=${days}`,
    {},
    true,
  )
}

export async function getClaimVerification(): Promise<ClaimVerificationStats> {
  return request<ClaimVerificationStats>(
    '/api/v1/analytics/claim-verification',
    {},
    true,
  )
}

export async function getAgentPerformance(): Promise<AgentPerformanceStats> {
  return request<AgentPerformanceStats>(
    '/api/v1/analytics/agent-performance',
    {},
    true,
  )
}

export async function getArgumentQuality(): Promise<ArgumentQualityStats> {
  return request<ArgumentQualityStats>(
    '/api/v1/analytics/argument-quality',
    {},
    true,
  )
}

export async function getRecentDebates(
  page: number,
  pageSize: number,
): Promise<RecentDebates> {
  return request<RecentDebates>(
    `/api/v1/analytics/recent-debates?page=${page}&page_size=${pageSize}`,
    {},
    true,
  )
}
