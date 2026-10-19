import { useEffect, useRef, useState, type FormEvent } from 'react'
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
  recommendAgents,
  type CoreAgent,
  type RecommendedAgent,
} from '../services/debates'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

const REC_DEBOUNCE_MS = 600

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

  const [recommendations, setRecommendations] = useState<RecommendedAgent[]>([])
  const [recSource, setRecSource] = useState<'llm' | 'fallback' | null>(null)
  const [recTopic, setRecTopic] = useState<string | null>(null)
  const [recLoading, setRecLoading] = useState(false)
  const [recError, setRecError] = useState<string | null>(null)

  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)

  const recSeqRef = useRef(0)
  const recTimerRef = useRef<number | null>(null)
  const recInFlightSeqRef = useRef(0)
  const recQueuedRef = useRef(false)
  const desiredTopicRef = useRef('')
  const selectionModeRef = useRef(selectionMode)

  useEffect(() => {
    selectionModeRef.current = selectionMode
  }, [selectionMode])

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

  function resetRecommendations() {
    desiredTopicRef.current = ''
    if (recTimerRef.current !== null) {
      window.clearTimeout(recTimerRef.current)
      recTimerRef.current = null
    }
    recSeqRef.current += 1
    recQueuedRef.current = false
    setRecommendations([])
    setRecSource(null)
    setRecTopic(null)
    setRecError(null)
    setRecLoading(false)
    setSelected([])
  }

  async function fireRecommendation() {
    const topicForRequest = desiredTopicRef.current.trim()
    if (!topicForRequest) {
      setRecLoading(false)
      return
    }
    // Never run two recommendation requests at once; queue the latest topic.
    if (recInFlightSeqRef.current !== 0) {
      recQueuedRef.current = true
      return
    }
    const seq = ++recSeqRef.current
    recInFlightSeqRef.current = seq
    setRecLoading(true)
    setRecError(null)
    try {
      const response = await recommendAgents(topicForRequest)
      // Drop superseded responses so an older answer never overwrites a newer one.
      if (seq !== recSeqRef.current) return
      // The topic changed while this request was in flight: the queued
      // refresh owns the state now, so this result is discarded.
      if (desiredTopicRef.current.trim() !== topicForRequest) return
      setRecommendations(response.agents)
      setRecSource(response.selection_source)
      setRecTopic(topicForRequest)
      if (selectionModeRef.current === 'auto') {
        setSelected(response.agents.map((agent) => agent.role))
      }
    } catch (err) {
      if (seq !== recSeqRef.current) return
      if (desiredTopicRef.current.trim() !== topicForRequest) return
      setRecommendations([])
      setRecSource(null)
      setRecTopic(null)
      if (selectionModeRef.current === 'auto') setSelected([])
      setRecError(
        apiErrorMessage(
          err,
          'Could not generate recommendations. Try again or switch to manual selection.',
        ),
      )
    } finally {
      if (recInFlightSeqRef.current === seq) recInFlightSeqRef.current = 0
      if (seq === recSeqRef.current) {
        const stale = desiredTopicRef.current.trim() !== topicForRequest
        if (recQueuedRef.current || stale) {
          recQueuedRef.current = false
          void fireRecommendation()
          return
        }
        setRecLoading(false)
      }
    }
  }

  function scheduleRecommendation(nextTopic: string) {
    desiredTopicRef.current = nextTopic
    if (recTimerRef.current !== null) {
      window.clearTimeout(recTimerRef.current)
    }
    recTimerRef.current = window.setTimeout(() => {
      recTimerRef.current = null
      void fireRecommendation()
    }, REC_DEBOUNCE_MS)
  }

  function refreshRecommendation() {
    desiredTopicRef.current = topic.trim()
    if (recInFlightSeqRef.current !== 0) {
      recQueuedRef.current = true
      return
    }
    void fireRecommendation()
  }

  useEffect(() => {
    if (selectionMode !== 'auto') return
    const trimmed = topic.trim()
    if (!trimmed) {
      resetRecommendations()
      return
    }
    // Fresh recommendations for this exact topic: do not request them again
    // when toggling back into auto mode.
    if (recTopic === trimmed && !recError && recommendations.length > 0) {
      desiredTopicRef.current = trimmed
      return
    }
    scheduleRecommendation(trimmed)
    return () => {
      if (recTimerRef.current !== null) {
        window.clearTimeout(recTimerRef.current)
        recTimerRef.current = null
      }
    }
    // recTopic/recError/recommendations are read-only guards for scheduling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic, selectionMode])

  function toggleAgent(role: string) {
    setSelected((current) =>
      current.includes(role)
        ? current.filter((item) => item !== role)
        : [...current, role],
    )
  }

  function validate(): string[] {
    const found: string[] = []
    const trimmedTopic = topic.trim()
    if (!trimmedTopic) found.push('Topic is required.')
    if (selectionMode === 'manual') {
      if (selected.length < MIN_AGENTS) {
        found.push(`Select at least ${MIN_AGENTS} agents for a debate.`)
      }
    } else {
      if (recLoading) {
        found.push('Agent recommendations are still loading.')
      } else if (recError || recommendations.length < MIN_AGENTS) {
        found.push(
          'Get agent recommendations for this topic first (or switch to manual selection).',
        )
      } else if (recTopic !== trimmedTopic) {
        found.push(
          'The topic changed — wait for refreshed recommendations before creating the debate.',
        )
      }
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
        agent_ids:
          selectionMode === 'manual'
            ? selected
            : recommendations.map((agent) => agent.role),
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
              Auto analyzes your topic and recommends the most relevant experts,
              each with a short reason. Switch to Manual to adjust the selection
              yourself.
            </p>
          )}
        </fieldset>

        {selectionMode === 'auto' && (
          <div
            className="card"
            data-testid="recommendations-section"
            data-rec-topic={recTopic ?? ''}
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="card-title">Recommended experts</h2>
              <button
                type="button"
                onClick={refreshRecommendation}
                className="btn-ghost text-sm"
                data-testid="refresh-recommendations"
              >
                Refresh
              </button>
            </div>

            {recLoading && (
              <div data-testid="recommendations-loading">
                <LoadingState
                  label="Analyzing the topic for expert recommendations..."
                  className="py-4 text-left"
                />
              </div>
            )}

            {!recLoading && recError && (
              <div className="mb-3" data-testid="recommendations-error">
                <ErrorBanner
                  title="Recommendation failed"
                  message={recError}
                  onRetry={refreshRecommendation}
                />
              </div>
            )}

            {!recLoading && !recError && recommendations.length === 0 && (
              <p className="field-hint" data-testid="recommendations-empty">
                Enter a debate topic to get expert recommendations.
              </p>
            )}

            {recommendations.length > 0 && (
              <ul className="space-y-3">
                {recommendations.map((agent) => (
                  <li
                    key={agent.role}
                    className="rounded-lg border border-gray-800 bg-gray-950 p-3"
                    data-testid="recommendation-item"
                  >
                    <p className="flex items-center gap-2 text-sm font-semibold text-white">
                      {agent.name}
                      <span className="badge bg-indigo-500/15 text-indigo-300">
                        {agent.role}
                      </span>
                    </p>
                    <p className="mt-1 text-sm text-gray-400" data-testid="agent-reason">
                      {agent.reason}
                    </p>
                  </li>
                ))}
              </ul>
            )}

            {!recLoading && recSource === 'fallback' && recommendations.length > 0 && (
              <p className="field-hint mt-3" data-testid="recommendations-fallback">
                Generated with the offline topic matcher because the language model
                was unavailable.
              </p>
            )}
          </div>
        )}

        <div>
          <span className="label">
            Core agents (
            {selectionMode === 'manual'
              ? `${selected.length} selected`
              : `${recommendations.length} recommended`}
            )
          </span>
          <div className="grid gap-3 sm:grid-cols-2">
            {agents.map((agent) => {
              const isAuto = selectionMode === 'auto'
              const recommended = recommendations.some((item) => item.role === agent.role)
              const disabled = isAuto
              const checked = isAuto ? recommended : selected.includes(agent.role)
              return (
                <label
                  key={agent.role}
                  className={`rounded-lg border bg-gray-900 p-4 transition-colors ${
                    isAuto
                      ? recommended
                        ? 'border-indigo-500/60'
                        : 'border-gray-800 opacity-60'
                      : 'border-gray-800 cursor-pointer hover:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-500/50'
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
