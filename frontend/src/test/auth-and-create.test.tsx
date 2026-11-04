import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { AuthProvider, useAuth } from '../context/AuthContext'
import Login from '../pages/Login'
import DebateNew from '../pages/DebateNew'
import ProtectedRoute from '../components/ProtectedRoute'
import { TOKEN_STORAGE_KEY } from '../services/api'

vi.mock('../components/ui/AppHeader', () => ({ default: () => <header>MAVES</header> }))
const token = () => `${btoa('{}')}.${btoa(JSON.stringify({ sub: 'qa-user', exp: Math.floor(Date.now() / 1000) + 3600 }))}.test-signature`
const user = { id: 'qa-user', email: 'qa@example.com', created_at: '2026-11-03T10:00:00Z' }
let invalid = false
let failCreate = false
let created: Record<string, unknown> | null = null

beforeEach(() => {
  invalid = failCreate = false; created = null; localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const path = new URL(input).pathname
    let body: unknown = {}; let status = 200
    if (path.endsWith('/auth/demo')) body = { enabled: false }
    else if (path.endsWith('/auth/login')) { status = invalid ? 401 : 200; body = invalid ? { detail: 'Incorrect email or password' } : { access_token: token(), token_type: 'bearer' } }
    else if (path.endsWith('/auth/me')) body = user
    else if (path.endsWith('/agents')) body = ['Scientist', 'Lawyer'].map(name => ({ id: name, role: name.toLowerCase(), name, description: `${name} expertise` }))
    else if (path.endsWith('/debates') && init?.method === 'POST') {
      created = JSON.parse(String(init.body)); status = failCreate ? 503 : 201
      body = failCreate ? { detail: 'Database temporarily unavailable' } : { id: 'new-debate' }
    }
    return new Response(JSON.stringify(body), { status })
  }))
})

function Account() {
  const auth = useAuth()
  return <><p>{auth.user?.email}</p><button onClick={auth.logout}>Sign out</button></>
}
function loginScreen() {
  return render(<MemoryRouter initialEntries={['/login']}><AuthProvider><Routes>
    <Route path="/login" element={<Login />} />
    <Route path="/" element={<ProtectedRoute><Account /></ProtectedRoute>} />
  </Routes></AuthProvider></MemoryRouter>)
}
function Destination() {
  const location = useLocation()
  return <p>{location.pathname} {location.state?.autoStart ? 'auto-start requested' : 'saved only'}</p>
}
function createScreen() {
  localStorage.setItem(TOKEN_STORAGE_KEY, token())
  return render(<MemoryRouter initialEntries={['/debates/new']}><Routes>
    <Route path="/debates/new" element={<DebateNew />} />
    <Route path="/debates/:id" element={<Destination />} />
  </Routes></MemoryRouter>)
}

describe('authentication API integration', () => {
  it('logs in through the API, restores the user and clears the token on logout', async () => {
    loginScreen()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: user.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password' } })
    fireEvent.click(screen.getByRole('button', { name: /^Login$/ }))
    expect(await screen.findByText(user.email)).toBeInTheDocument()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
  it('shows invalid credentials and permits another login attempt', async () => {
    invalid = true; loginScreen()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: user.email } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /^Login$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password')
    expect(screen.getByRole('button', { name: /^Login$/ })).toBeEnabled()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  })
  it('restores a valid saved session on browser refresh', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, token())
    render(<MemoryRouter><AuthProvider><ProtectedRoute><Account /></ProtectedRoute></AuthProvider></MemoryRouter>)
    expect(await screen.findByText(user.email)).toBeInTheDocument()
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/auth/me'))).toBe(true)
  })
})

describe('debate creation API integration', () => {
  async function fill() {
    fireEvent.change(screen.getByLabelText('Debate question'), { target: { value: 'Should cities subsidize public transport?' } })
    fireEvent.click(await screen.findByRole('checkbox', { name: /Scientist/ }))
    fireEvent.click(screen.getByRole('checkbox', { name: /Lawyer/ }))
    fireEvent.change(screen.getByLabelText('Number of rounds'), { target: { value: '2' } })
  }
  it('sends selected agents and rounds, then requests live execution on the debate page', async () => {
    createScreen(); await fill()
    fireEvent.click(screen.getByRole('button', { name: 'Start Debate' }))
    expect(await screen.findByText('/debates/new-debate auto-start requested')).toBeInTheDocument()
    expect(created).toMatchObject({ agent_ids: ['scientist', 'lawyer'], total_rounds: 2, expert_selection_mode: 'manual', verify_evidence: true })
  })
  it('preserves the form and displays backend failure for retry', async () => {
    failCreate = true; createScreen(); await fill()
    fireEvent.click(screen.getByRole('button', { name: 'Start Debate' }))
    expect(await screen.findByText('Database temporarily unavailable')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Start Debate' })).toBeEnabled())
    expect(screen.getByLabelText('Debate question')).toHaveValue('Should cities subsidize public transport?')
  })
})
