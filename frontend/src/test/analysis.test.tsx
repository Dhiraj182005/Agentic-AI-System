import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import DebateDetail from '../pages/DebateDetail'
import { TOKEN_STORAGE_KEY } from '../services/api'

vi.mock('../components/ui/AppHeader', () => ({ default: () => <header>MAVES</header> }))
const live = vi.hoisted(() => ({ handlers: null as null | import('../services/websocket').DebateEventHandlers }))
vi.mock('../services/websocket', () => ({ DebateWebSocketClient: class {
  constructor(_id: string, handlers: import('../services/websocket').DebateEventHandlers) { live.handlers = handlers }
  connect() { live.handlers?.onStateChange?.('disconnected') }
  disconnect() { /* deterministic offline transport; reconnect is tested separately */ }
} }))

const agent = { id: 'a1', name: 'Scientist', role: 'scientist' }
const message = { id: 'm1', agent, round_number: 1, turn_number: 1, content: 'This argument describes a testable claim.', message_type: 'opening', created_at: '2026-11-03T10:00:00Z', structured: null }
const fallacy = { id: 'f1', debate_id: 'd1', message_id: 'm1', agent_id: 'a1', agent_name: 'Scientist', fallacy_type: 'no_fallacy', severity: 'low', confidence: .9, explanation: 'No clear logical fallacy.', evidence_span: null, created_at: message.created_at }
const evaluation = { id: 'e1', debate_id: 'd1', message_id: 'm1', agent_id: 'a1', agent_name: 'Scientist', logical_soundness: 8, evidence_score: 7, relevance_score: 9, effectiveness_score: 8, overall_score: 8.1, explanation: 'Clear argument with limited support.', rubric_version: 2, criterion_scores: { logical_soundness: 8, factual_support: null }, strengths: ['Clear reasoning'], weaknesses: ['Limited evidence'], created_at: message.created_at, evaluated_at: message.created_at }

let stored = false
let failStored = false
let failBatch = false
let batchStarted = false
let neverLoad = false
let calls: string[] = []

function mount(tab = 'fallacies') {
  return render(<MemoryRouter initialEntries={[`/debates/d1#${tab}`]}><Routes><Route path="/debates/:debateId" element={<DebateDetail />} /></Routes></MemoryRouter>)
}

beforeEach(() => {
  stored = failStored = failBatch = batchStarted = neverLoad = false
  calls = []
  localStorage.setItem(TOKEN_STORAGE_KEY, 'test-token')
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const path = new URL(input).pathname
    calls.push(`${init?.method ?? 'GET'} ${path}`)
    let body: unknown = {}
    let status = 200
    if (path.endsWith('/analysis') && init?.method === 'POST') {
      batchStarted = true
      status = failBatch ? 503 : 202
      body = failBatch ? { detail: 'Analysis service unavailable' } : { state: 'running', run_id: 'run1' }
    } else if (path.endsWith('/analysis')) body = { state: batchStarted ? 'running' : 'not_started', failures: [] }
    else if (path.endsWith('/fallacies')) { status = failStored ? 503 : 200; body = { fallacies: stored ? [fallacy] : [], detail: 'Storage unavailable' } }
    else if (path.endsWith('/evaluations')) body = { evaluations: stored ? [evaluation] : [] }
    else if (path.includes('/verdict') || path.endsWith('/judgment')) { status = 404; body = { detail: 'Not generated' } }
    else if (path.endsWith('/claims')) body = { claims: [] }
    else if (path.endsWith('/rounds')) body = { rounds: [{ round_number: 1, status: 'completed' }] }
    else if (path.endsWith('/messages')) body = { messages: [message] }
    else if (path.endsWith('/d1')) {
      if (neverLoad) return new Promise<Response>(() => {})
      body = { id: 'd1', topic: 'A scientific debate', status: 'completed', agents: [agent], total_rounds: 1, mode: 'balanced', expert_selection_mode: 'manual', domain_tags: [], verify_evidence: true, created_at: message.created_at }
    }
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  }))
})

describe('persisted argument analysis', () => {
  it('shows loading until the debate is retrieved', async () => {
    neverLoad = true
    mount()
    expect(screen.getByText(/loading debate/i)).toBeInTheDocument()
  })
  it('shows an honest empty state and a working batch action', async () => {
    mount()
    const panel = await screen.findByTestId('section-analysis')
    expect(await within(panel).findByText('No fallacy analysis stored yet.')).toBeInTheDocument()
    fireEvent.click(within(panel).getByRole('button', { name: /Analyze all arguments/ }))
    await waitFor(() => expect(calls).toContain('POST /api/v1/debates/d1/analysis'))
    expect(await within(panel).findByRole('button', { name: 'Analysis in progress...' })).toBeDisabled()
  })
  it('renders stored no-fallacy outcomes after refresh', async () => {
    stored = true
    mount()
    expect(await screen.findByTestId('analysis-fallacy-none')).toHaveTextContent('No clear fallacy detected.')
  })
  it('renders actual criterion scores and unavailable dimensions', async () => {
    stored = true
    mount('quality')
    const panel = await screen.findByTestId('section-quality')
    await waitFor(() => expect(within(panel).getByText('Overall: 8.1/10')).toBeInTheDocument())
    expect(within(panel).getByText('factual support: Unavailable')).toBeInTheDocument()
    expect(within(panel).getByText(/Strengths: Clear reasoning/)).toBeInTheDocument()
  })
  it('surfaces storage failure instead of silently reporting no analysis', async () => {
    failStored = true
    mount()
    expect(await screen.findByTestId('stored-notice')).toHaveTextContent('could not be loaded')
  })
  it('shows backend batch failure and permits retry', async () => {
    failBatch = true
    mount()
    const panel = await screen.findByTestId('section-analysis')
    fireEvent.click(within(panel).getByRole('button', { name: /Analyze all arguments/ }))
    expect(await within(panel).findByText('Analysis service unavailable')).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: /Analyze all arguments/ })).toBeEnabled()
  })
  it('refreshes persisted results when background analysis finishes', async () => {
    mount()
    const panel = await screen.findByTestId('section-analysis')
    fireEvent.click(within(panel).getByRole('button', { name: /Analyze all arguments/ }))
    await waitFor(() => expect(batchStarted).toBe(true))
    stored = true
    expect(await within(panel).findByTestId('analysis-fallacy-none', {}, { timeout: 7500 })).toBeInTheDocument()
  }, 10000)
  it('sends the actual message ID for manual analysis and displays the result', async () => {
    const prior = globalThis.fetch
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      if (new URL(input).pathname.endsWith('/fallacies/analyze')) {
        calls.push(`${init?.method} ${new URL(input).pathname}`)
        return new Response(JSON.stringify(fallacy), { status: 200 })
      }
      return prior(input, init)
    }))
    mount('transcript')
    fireEvent.click(await screen.findByTestId('analyze-argument'))
    await waitFor(() => expect(calls).toContain('POST /api/v1/messages/m1/fallacies/analyze'))
    await waitFor(() => expect(screen.getByTestId('analysis-fallacy-none')).toBeInTheDocument())
  })
})
