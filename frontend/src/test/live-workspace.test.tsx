import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ExecutionDashboard from '../components/ExecutionDashboard'
import AnalysisTimeline from '../components/AnalysisTimeline'
import VerdictPanel from '../components/VerdictPanel'
import useExecution from '../hooks/useExecution'
import { getExecution, type ExecutionSnapshot } from '../services/execution'
import { DebateWebSocketClient } from '../services/websocket'
import type { Verdict } from '../services/verdict'

vi.mock('../services/execution', () => ({ getExecution: vi.fn(), beginDebate: vi.fn() }))

const snapshot = (overrides: Partial<ExecutionSnapshot> = {}): ExecutionSnapshot => ({
  debate_id: 'd1', execution_state: 'running', transcript_status: 'running', sequence: 4,
  current_round: 1, total_rounds: 3, completed_rounds: 0, completed_turns: 1, total_turns: 6,
  debate_progress: 16.7, current_agent: { id: 'a2', name: 'Lawyer', role: 'lawyer' },
  agents: [{ id: 'a1', name: 'Scientist', role: 'scientist', status: 'waiting', current_round: null, latest_completed_round: 1, completed_turns: 1 },
    { id: 'a2', name: 'Lawyer', role: 'lawyer', status: 'generating_argument', current_round: 1, latest_completed_round: 0, completed_turns: 0 }],
  rounds: [{ number: 1, status: 'running', started_at: '2026-11-03T10:00:00Z', completed_at: null }],
  analysis: { state: 'not_started' }, verdict_available: false,
  events: [{ id: '4', sequence: 4, debate_id: 'd1', type: 'agent_turn_started', timestamp: '2026-11-03T10:01:00Z', data: { agent: { id: 'a2', name: 'Lawyer', role: 'lawyer' } } }], ...overrides,
})

beforeEach(() => { vi.mocked(getExecution).mockReset() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('persisted live workspace', () => {
  it('shows actual turn counts, round and current agent without estimated percentages', () => {
    render(<ExecutionDashboard execution={snapshot()} connection="connected" onRound={vi.fn()} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1')
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuemax', '6')
    expect(screen.getByText(/Round 1 of 3/)).toHaveTextContent('Lawyer is speaking')
    expect(screen.getByText('Generating argument')).toBeInTheDocument()
    expect(screen.getByText(/agent turn started/)).toBeInTheDocument()
  })
  it('does not label the workflow completed when all turns are saved', () => {
    render(<ExecutionDashboard execution={snapshot({ execution_state: 'analyzing', transcript_status: 'completed', completed_turns: 6, debate_progress: 100, current_agent: null })} connection="connected" onRound={vi.fn()} />)
    expect(screen.getByRole('heading', { name: 'Post-debate analysis' })).toBeInTheDocument()
    expect(screen.getByText(/Transcript complete. Analysis and verdict are separate steps/)).toBeInTheDocument()
  })
  it('opens completed rounds and displays updated agent/round status from a new snapshot', () => {
    const onRound = vi.fn()
    const view = render(<ExecutionDashboard execution={snapshot()} connection="connected" onRound={onRound} />)
    view.rerender(<ExecutionDashboard execution={snapshot({ current_round: 2, completed_rounds: 1, rounds: [{ number: 1, status: 'completed', started_at: null, completed_at: '2026-11-03T10:02:00Z' }], agents: [{ id: 'a1', name: 'Scientist', role: 'scientist', status: 'generating_rebuttal', current_round: 2, latest_completed_round: 1, completed_turns: 1 }] })} connection="connected" onRound={onRound} />)
    fireEvent.click(screen.getByRole('button', { name: 'Round 1 completed' }))
    expect(onRound).toHaveBeenCalledWith(1)
    expect(screen.getByText('Generating rebuttal')).toBeInTheDocument()
    expect(screen.getByText(/Round 2 of 3/)).toBeInTheDocument()
  })
  it('distinguishes running extraction, a failed extraction, and a successful zero', () => {
    const view = render(<AnalysisTimeline analysis={{ state: 'running', current_stage: 'extraction', stages: { extraction: { state: 'running', started_at: '2026-11-03T10:00:00Z' } } }} />)
    expect(screen.getByRole('heading', { name: 'Analyzing debate...' })).toBeInTheDocument()
    expect(screen.getByText(/task completion time is unknown/)).toBeInTheDocument()
    view.rerender(<AnalysisTimeline analysis={{ state: 'failed', stages: { extraction: { state: 'failed', error: 'Structured extraction failed. Retry required.' } } }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Structured extraction failed')
    view.rerender(<AnalysisTimeline analysis={{ state: 'completed', claims_total: 0, stages: { extraction: { state: 'completed', summary: { claims: 0 } } } }} />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('claims: 0')).toBeInTheDocument()
  })
  it('disables duplicate generation while an existing job is running', () => {
    render(<VerdictPanel status="completed" verdict={null} loading={false} generating={false} error={null} notice={null} onGenerate={vi.fn()} analysis={{ state: 'running', current_stage: 'verification' }} />)
    expect(screen.getByTestId('generate-verdict')).toBeDisabled()
    expect(screen.getByText(/Analysis already in progress — showing live progress/)).toBeInTheDocument()
  })
  it('renders an inconclusive saved verdict and wires evidence/PDF actions', () => {
    const navigate = vi.fn(), download = vi.fn()
    const verdict: Verdict = { id: 'v1', debate_id: 'd1', position: 'inconclusive', answer: 'The available sources do not establish the proposition.', summary: 'More evidence is needed.', reasoning: 'The retrieved sources are insufficient.', confidence: 'low', confidence_basis: 'No decisive verified claims.', preferred_position: null, supporting_arguments: [], counterarguments: [], limitations: ['Evidence coverage is incomplete.'], unresolved_questions: [], evidence_snapshot: { total_claims: 1, supported: 0, contradicted: 0, insufficient_evidence: 1, unverified: 0, evidence_sources: 1 }, evidence_basis: 'none', inconclusive_reason: 'no_verified_evidence', stale: false, created_at: '', updated_at: '' }
    render(<VerdictPanel status="completed" verdict={verdict} loading={false} generating={false} error={null} notice={null} onGenerate={vi.fn()} analysis={{ state: 'partial' }} onNavigate={navigate} onDownload={download} />)
    expect(screen.getByTestId('verdict-answer')).toHaveTextContent(verdict.answer)
    expect(screen.getByTestId('verdict-position')).toHaveTextContent('Inconclusive')
    fireEvent.click(screen.getByRole('button', { name: 'View Evidence' }))
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF Report' }))
    expect(navigate).toHaveBeenCalledWith('evidence')
    expect(download).toHaveBeenCalledOnce()
  })
})

describe('execution refresh and synchronization', () => {
  it('recovers saved running state on refresh and ignores an older HTTP response', async () => {
    let first!: (value: ExecutionSnapshot) => void
    vi.mocked(getExecution).mockReturnValueOnce(new Promise(resolve => { first = resolve })).mockResolvedValue(snapshot({ sequence: 8, completed_turns: 3 }))
    const hook = renderHook(() => useExecution('d1', 'connected'))
    await act(async () => { await hook.result.current.refresh() })
    await act(async () => { first(snapshot({ sequence: 4, completed_turns: 1 })) })
    expect(hook.result.current.execution?.completed_turns).toBe(3)
    hook.unmount()
    const refreshed = renderHook(() => useExecution('d1', 'connected'))
    await waitFor(() => expect(refreshed.result.current.execution?.sequence).toBe(8))
  })
  it('uses fallback polling only while disconnected and cleans it up', async () => {
    vi.useFakeTimers()
    vi.mocked(getExecution).mockResolvedValue(snapshot())
    const hook = renderHook(({ connection }: { connection: 'connected' | 'disconnected' }) => useExecution('d1', connection), { initialProps: { connection: 'connected' } })
    await act(async () => { await Promise.resolve() })
    expect(getExecution).toHaveBeenCalledTimes(1)
    await act(async () => { vi.advanceTimersByTime(8000) })
    expect(getExecution).toHaveBeenCalledTimes(1)
    hook.rerender({ connection: 'disconnected' })
    await act(async () => { vi.advanceTimersByTime(8000) })
    expect(getExecution).toHaveBeenCalledTimes(2)
    hook.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})

class Socket {
  static OPEN = 1; static CONNECTING = 0
  static instances: Socket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null
  constructor() { Socket.instances.push(this) }
  open() { this.readyState = 1; this.onopen?.() }
  close(code = 1000) { this.readyState = 3; this.onclose?.({ code }) }
}

describe('WebSocket reconnection and event ordering', () => {
  it('deduplicates events, drops other debates/older frames and reconnects automatically', () => {
    vi.useFakeTimers(); Socket.instances = []; vi.stubGlobal('WebSocket', Socket)
    const event = vi.fn(), state = vi.fn()
    const client = new DebateWebSocketClient('d1', { onEvent: event, onStateChange: state })
    client.connect(); const first = Socket.instances[0]; first.open()
    for (const [sequence, debate_id] of [[10, 'd1'], [10, 'd1'], [9, 'd1'], [11, 'other'], [11, 'd1']] as const) first.onmessage?.({ data: JSON.stringify({ type: 'round_started', sequence, debate_id, data: {}, timestamp: '' }) })
    expect(event).toHaveBeenCalledTimes(2)
    first.close(1006); vi.advanceTimersByTime(1000)
    expect(Socket.instances).toHaveLength(2)
    Socket.instances[1].open()
    expect(state).toHaveBeenLastCalledWith('connected')
    client.disconnect(); vi.advanceTimersByTime(30000)
    expect(Socket.instances).toHaveLength(2)
  })
  it('does not reconnect permanently unauthorized subscriptions', () => {
    vi.useFakeTimers(); Socket.instances = []; vi.stubGlobal('WebSocket', Socket)
    const state = vi.fn()
    const client = new DebateWebSocketClient('d1', { onEvent: vi.fn(), onStateChange: state })
    client.connect(); Socket.instances[0].close(4401); vi.advanceTimersByTime(30000)
    expect(Socket.instances).toHaveLength(1)
    expect(state).toHaveBeenLastCalledWith('error')
    client.disconnect()
  })
})
