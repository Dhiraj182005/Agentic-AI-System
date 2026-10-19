import { useEffect, useState, type FormEvent } from 'react'
import { apiErrorMessage } from '../services/api'
import { testAgent, type AgentTestResponse } from '../services/agents'
import { listCoreAgents, type CoreAgent } from '../services/debates'
import AgentMessage from '../components/AgentMessage'
import AgentThinking from '../components/AgentThinking'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'

export default function AgentTest() {
  const [agents, setAgents] = useState<CoreAgent[]>([])
  const [agent, setAgent] = useState('economist')
  const [message, setMessage] = useState('')
  const [result, setResult] = useState<AgentTestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    listCoreAgents()
      .then((response) => {
        if (cancelled) return
        setAgents(response)
        if (response.length > 0 && !response.some((item) => item.role === 'economist')) {
          setAgent(response[0].role)
        }
      })
      .catch((err) => {
        if (!cancelled) setLoadError(apiErrorMessage(err, 'Unable to load agents.'))
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSubmitting(true)
    try {
      setResult(await testAgent(agent, message))
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to reach the agent. Please try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageShell>
      <h1 className="page-title mb-2">Agent Test</h1>
      <p className="mb-8 text-gray-400">
        Test a single role-based agent against a message.
      </p>

      {loadError && (
        <div className="mb-6">
          <ErrorBanner title="Could not load agents" message={loadError} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="agent" className="label">
            Agent
          </label>
          <select
            id="agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="input appearance-none"
          >
            {agents.map((option) => (
              <option key={option.role} value={option.role}>
                {option.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="agent-message" className="label">
            Message
          </label>
          <textarea
            id="agent-message"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required
            rows={4}
            placeholder="Ask the agent to analyze a topic..."
            className="input resize-y"
          />
        </div>

        <button
          type="submit"
          disabled={submitting || loadError !== null || agents.length === 0}
          className="btn-primary w-full py-3"
        >
          {submitting ? 'Analyzing...' : 'Send'}
        </button>
      </form>

      {submitting && <AgentThinking agent={agent} />}

      {error && (
        <div className="mt-4">
          <ErrorBanner title="Request failed" message={error} />
        </div>
      )}

      {result && (
        <div className="mt-6">
          <AgentMessage result={result} />
        </div>
      )}
    </PageShell>
  )
}
