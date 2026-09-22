import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError } from '../services/api'
import { testAgent, type AgentTestResponse } from '../services/agents'

const AGENT_OPTIONS = [
  { identifier: 'economist', label: 'Economist' },
  { identifier: 'lawyer', label: 'Lawyer' },
  { identifier: 'doctor', label: 'Doctor' },
  { identifier: 'scientist', label: 'Scientist' },
  { identifier: 'ethicist', label: 'Ethicist' },
  { identifier: 'analyst', label: 'Analyst' },
]

export default function AgentTest() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [agent, setAgent] = useState('economist')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<AgentTestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSubmitting(true)
    try {
      setResult(await testAgent(agent, message))
    } catch (err) {
      setError(
        err instanceof ApiClientError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'Unable to reach the agent. Please try again.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">AI Debate Arena</h1>
        <nav className="flex items-center gap-4">
          <Link to="/" className="text-sm text-gray-400 hover:text-white">
            Home
          </Link>
          <span className="text-sm text-gray-400">Agent Test</span>
          <button
            onClick={handleLogout}
            className="bg-red-600 hover:bg-red-700 rounded-lg px-4 py-2 text-sm font-semibold"
          >
            Logout
          </button>
        </nav>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        <h2 className="text-2xl font-semibold mb-2">Agent Test</h2>
        <p className="text-gray-400 mb-8">
          Test a single role-based agent. Authenticated as {user?.email}.
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">Agent</label>
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value)}
              className="w-full bg-gray-800 rounded-lg px-4 py-2 border border-gray-700 focus:outline-none focus:border-indigo-500"
            >
              {AGENT_OPTIONS.map((option) => (
                <option key={option.identifier} value={option.identifier}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-400 mb-1">Message</label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              required
              rows={4}
              placeholder="Ask the agent to analyze a topic..."
              className="w-full bg-gray-800 rounded-lg px-4 py-2 border border-gray-700 focus:outline-none focus:border-indigo-500"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 rounded-lg py-2 font-semibold"
          >
            {submitting ? 'Analyzing...' : 'Send'}
          </button>
        </form>

        {error && (
          <p className="mt-4 text-red-400 text-sm bg-red-900/30 rounded-lg px-4 py-2">
            {error}
          </p>
        )}

        {result && (
          <div className="mt-6 bg-gray-900 rounded-2xl border border-gray-800 p-6 space-y-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-400">
                Agent: <span className="text-white">{result.role}</span> (
                {result.agent})
              </span>
              <span className="text-gray-500">
                {result.provider} / {result.model}
              </span>
            </div>
            <div className="bg-gray-800 rounded-lg px-4 py-3 whitespace-pre-wrap text-sm leading-relaxed">
              {result.response}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}