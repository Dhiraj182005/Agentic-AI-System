import request from './api'
import type { AnalysisStatus } from './verdict'
import type { DebateEvent } from './websocket'

export interface ExecutionSnapshot {
  debate_id: string
  execution_state: string
  transcript_status: string
  sequence: number
  current_round: number
  total_rounds: number
  completed_rounds: number
  completed_turns: number
  total_turns: number
  debate_progress: number
  current_agent: { id: string; name: string; role: string } | null
  agents: { id: string; name: string; role: string; status: string; current_round: number | null; latest_completed_round: number; completed_turns: number }[]
  rounds: { number: number; status: string; started_at: string | null; completed_at: string | null }[]
  analysis: AnalysisStatus
  verdict_available: boolean
  events: DebateEvent[]
}

export function getExecution(id: string): Promise<ExecutionSnapshot> {
  return request(`/api/v1/debates/${id}/execution`, {}, true)
}

export function beginDebate(id: string, resume = false): Promise<ExecutionSnapshot> {
  return request(`/api/v1/debates/${id}/execute?resume=${resume}`, { method: 'POST' }, true)
}
