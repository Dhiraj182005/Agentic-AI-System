import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError } from '../services/api'
import {
  DEBATE_MODES,
  MAX_ROUNDS,
  MAX_TOPIC_LENGTH,
  MIN_AGENTS,
  MIN_ROUNDS,
  createDebate,
  listCoreAgents,
  type CoreAgent,
} from '../services/debates'

export default function DebateNew() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [agents, setAgents] = useState<CoreAgent[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [topic, setTopic] = useState('')
  const [selectionMode, setSelectionMode] = useState<'manual' | 'auto'>('manual')
  const [selected, setSelected] = useState<string[]>([])
  const [tags, setTags] = useState('')
  const [mode, setMode] = useState<'balanced' | 'pro_con'>('balanced')
  const [rounds, setRounds] = useState(3)
  const [verifyEvidence, setVerifyEvidence] = useState(false)

  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    listCoreAgents()
      .then(setAgents)
      .catch((err) =>
        setLoadError(
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Unable to load core agents.',
        ),
      )
  }, [])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  function toggleAgent(role: string) {
    setSelected((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    )
  }

  function validate(): string[] {
    const found: string[] = []
    if (!topic.trim()) found.push('Topic is required.')
    if (selectionMode === 'manual' && selected.length < MIN_AGENTS) {
      found.push(`Select at least ${MIN_AGENTS} agents for a debate.`)
    }
    if (rounds < MIN_ROUNDS || rounds > MAX_ROUNDS) {
      found.push(`Number of rounds must be between ${MIN_ROUNDS} and ${MAX_ROUNDS}.`)
    }
    return found
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const found = validate()
    setErrors(found)
    if (found.length > 0) return

    setSubmitting(true)
    try {
      const debate = await createDebate({
        topic: topic.trim(),
        expert_selection_mode: selectionMode,
        agent_ids: selectionMode === 'manual' ? selected : [],
        domain_tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        mode,
        total_rounds: rounds,
        verify_evidence: verifyEvidence,
      })
      navigate(`/debates/${debate.id}`)
    } catch (err) {
      setErrors([
        err instanceof ApiClientError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'Could not create the debate. Please try again.',
      ])
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
          <Link to="/debates" className="text-sm text-gray-400 hover:text-white">
            Debates
          </Link>
          <span className="text-sm text-gray-400">New Debate</span>
          <button
            onClick={handleLogout}
            className="bg-red-600 hover:bg-red-700 rounded-lg px-4 py-2 text-sm font-semibold"
          >
            Logout
          </button>
        </nav>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        <h2 className="text-2xl font-semibold mb-2">Create a Debate</h2>
        <p className="text-gray-400 mb-8">
          Configure the topic and choose the participating agents. Authenticated as{' '}
          {user?.email}. Creating a debate does not start it.
        </p>

        {loadError && (
          <div className="mb-6 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
            <p className="text-sm font-medium text-red-300">Could not load agents</p>
            <p className="mt-1 text-sm text-red-300/80">{loadError}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label htmlFor="topic" className="block text-sm text-gray-400 mb-1">
              Debate topic
            </label>
            <input
              id="topic"
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              maxLength={MAX_TOPIC_LENGTH}
              placeholder="Should governments regulate generative AI?"
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div>
            <span className="block text-sm text-gray-400 mb-2">Agent selection</span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="selection_mode"
                  value="manual"
                  checked={selectionMode === 'manual'}
                  onChange={() => setSelectionMode('manual')}
                />
                Manual
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="selection_mode"
                  value="auto"
                  checked={selectionMode === 'auto'}
                  onChange={() => setSelectionMode('auto')}
                />
                Auto
              </label>
            </div>
            {selectionMode === 'auto' && (
              <p className="mt-2 text-sm text-gray-500">
                Automatic selection currently picks every active core agent (
                {agents.length} agents).
              </p>
            )}
          </div>

          <div>
            <span className="block text-sm text-gray-400 mb-2">
              Core agents ({selectionMode === 'manual' ? `${selected.length} selected` : 'automatic'})
            </span>
            <div className="grid gap-3 sm:grid-cols-2">
              {agents.map((agent) => {
                const disabled = selectionMode === 'auto'
                const checked = selectionMode === 'auto' || selected.includes(agent.role)
                return (
                  <label
                    key={agent.role}
                    className={`rounded-lg border border-gray-800 bg-gray-900 p-4 ${
                      disabled ? 'opacity-70' : 'cursor-pointer hover:border-indigo-500'
                    }`}
                  >
                    <span className="flex items-center gap-2 font-semibold">
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => toggleAgent(agent.role)}
                      />
                      {agent.name}
                    </span>
                    <span className="mt-1 block text-sm text-gray-400">
                      {agent.description}
                    </span>
                  </label>
                )
              })}
              {agents.length === 0 && !loadError && (
                <p className="text-sm text-gray-500">Loading agents...</p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="tags" className="block text-sm text-gray-400 mb-1">
              Domain tags (optional, comma separated)
            </label>
            <input
              id="tags"
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="technology, policy"
              className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="mode" className="block text-sm text-gray-400 mb-1">
                Debate mode
              </label>
              <select
                id="mode"
                value={mode}
                onChange={(e) => setMode(e.target.value as 'balanced' | 'pro_con')}
                className="w-full appearance-none rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white focus:border-indigo-500 focus:outline-none"
              >
                {DEBATE_MODES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="rounds" className="block text-sm text-gray-400 mb-1">
                Number of rounds
              </label>
              <input
                id="rounds"
                type="number"
                min={MIN_ROUNDS}
                max={MAX_ROUNDS}
                value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))}
                className="w-full rounded-lg border border-gray-700 bg-gray-800 px-4 py-2.5 text-white focus:border-indigo-500 focus:outline-none"
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-300">
            <input
              type="checkbox"
              checked={verifyEvidence}
              onChange={(e) => setVerifyEvidence(e.target.checked)}
            />
            Verify evidence
          </label>

          {errors.length > 0 && (
            <div className="rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
              <p className="text-sm font-medium text-red-300">Fix the following</p>
              <ul className="mt-1 list-disc pl-5 text-sm text-red-300/80">
                {errors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || loadError !== null}
            className="w-full rounded-lg bg-indigo-600 py-2.5 font-semibold transition-colors hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Debate'}
          </button>
        </form>
      </main>
    </div>
  )
}
