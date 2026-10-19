import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../services/api'
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
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

export default function DebateNew() {
  const { user } = useAuth()
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
    let cancelled = false
    listCoreAgents()
      .then((response) => {
        if (!cancelled) setAgents(response)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(apiErrorMessage(err, 'Unable to load core agents.'))
      })
    return () => {
      cancelled = true
    }
  }, [])

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
      setErrors([apiErrorMessage(err, 'Could not create the debate. Please try again.')])
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageShell>
      <h1 className="page-title mb-2">Create a Debate</h1>
      <p className="mb-8 text-gray-400">
        Configure the topic and choose the participating agents. Authenticated as{' '}
        {user?.email}. Creating a debate does not start it.
      </p>

      {loadError && (
        <div className="mb-6">
          <ErrorBanner title="Could not load agents" message={loadError} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label htmlFor="topic" className="label">
            Debate topic
          </label>
          <input
            id="topic"
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            maxLength={MAX_TOPIC_LENGTH}
            placeholder="Should governments regulate generative AI?"
            className="input"
          />
        </div>

        <fieldset>
          <legend className="label">Agent selection</legend>
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
            <p className="field-hint">
              Automatic selection currently picks every active core agent (
              {agents.length} agents).
            </p>
          )}
        </fieldset>

        <div>
          <span className="label">
            Core agents (
            {selectionMode === 'manual' ? `${selected.length} selected` : 'automatic'})
          </span>
          <div className="grid gap-3 sm:grid-cols-2">
            {agents.map((agent) => {
              const disabled = selectionMode === 'auto'
              const checked = selectionMode === 'auto' || selected.includes(agent.role)
              return (
                <label
                  key={agent.role}
                  className={`rounded-lg border border-gray-800 bg-gray-900 p-4 transition-colors ${
                    disabled
                      ? 'opacity-70'
                      : 'cursor-pointer hover:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-500/50'
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
              <LoadingState label="Loading agents..." className="py-4 text-left" />
            )}
          </div>
        </div>

        <div>
          <label htmlFor="tags" className="label">
            Domain tags (optional, comma separated)
          </label>
          <input
            id="tags"
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="technology, policy"
            className="input"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="mode" className="label">
              Debate mode
            </label>
            <select
              id="mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as 'balanced' | 'pro_con')}
              className="input appearance-none"
            >
              {DEBATE_MODES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="rounds" className="label">
              Number of rounds
            </label>
            <input
              id="rounds"
              type="number"
              min={MIN_ROUNDS}
              max={MAX_ROUNDS}
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
              className="input"
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
          <div role="alert" className="alert-error">
            <p className="font-medium text-red-200">Fix the following</p>
            <ul className="mt-1 list-disc pl-5">
              {errors.map((error) => (
                <li key={error}>{error}</li>
              ))}
            </ul>
          </div>
        )}

        <button
          type="submit"
          disabled={submitting || loadError !== null}
          className="btn-primary w-full py-3"
        >
          {submitting ? 'Creating...' : 'Create Debate'}
        </button>
      </form>
    </PageShell>
  )
}
