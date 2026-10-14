import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError } from '../services/api'
import { testAgent, type AgentTestResponse } from '../services/agents'
import AgentMessage from '../components/AgentMessage'
import AgentThinking from '../components/AgentThinking'

const AGENT_OPTIONS = [
  { identifier: 'economist', label: 'Economist', dot: 'bg-amber-400' },
  { identifier: 'lawyer', label: 'Lawyer', dot: 'bg-sky-400' },
  { identifier: 'doctor', label: 'Doctor', dot: 'bg-rose-400' },
  { identifier: 'scientist', label: 'Scientist', dot: 'bg-emerald-400' },
  { identifier: 'ethicist', label: 'Ethicist', dot: 'bg-violet-400' },
  { identifier: 'analyst', label: 'Analyst', dot: 'bg-cyan-400' },
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
              className="w-full appearance-none rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white focus:border-indigo-500 focus:outline-none"
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
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-indigo-600 py-2.5 font-semibold transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Analyzing...' : 'Send'}
          </button>
        </form>

        {submitting && <AgentThinking agent={agent} />}

        {error && (
          <div className="mt-4 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
            <p className="text-sm font-medium text-red-300">Request failed</p>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
          </div>
        )}

        {result && (
          <div className="mt-6">
            <AgentMessage result={result} />
          </div>
        )}
      </main>
    </div>
  )
}