import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiErrorMessage } from '../services/api'
import {
  DEBATE_MODES,
  MAX_ROUNDS,
  MAX_CONTEXT_LENGTH,
  MAX_TOPIC_LENGTH,
  MIN_AGENTS,
  MIN_ROUNDS,
  createDebate,
  listCoreAgents,
  recommendAgents,
  type CoreAgent,
  type RecommendedAgent,
  type SpecialistDefinition,
  type TopicAnalysisSummary,
} from '../services/debates'
import PageShell from '../components/ui/PageShell'
import PageHeader from '../components/ui/PageHeader'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

const REC_DEBOUNCE_MS = 600

function StepHeading({ id, step, title }: { id: string; step: number; title: string }) {
  return (
    <h2 id={id} className="section-title flex items-center gap-3">
      <span
        aria-hidden="true"
        className="flex h-6 w-6 items-center justify-center rounded-full bg-indigo-600/20 text-xs font-semibold text-indigo-300"
      >
        {step}
      </span>
      {title}
    </h2>
  )
}

export default function DebateNew() {
  const navigate = useNavigate()

  const [agents, setAgents] = useState<CoreAgent[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)

  const [topic, setTopic] = useState('')
  const [context, setContext] = useState('')
  const [selectionMode, setSelectionMode] = useState<'manual' | 'auto'>('manual')
  const [selected, setSelected] = useState<string[]>([])
  const [tags, setTags] = useState('')
  const [mode, setMode] = useState<'balanced' | 'pro_con'>('balanced')
  const [rounds, setRounds] = useState(3)
  const [verifyEvidence, setVerifyEvidence] = useState(true)

  const [recommendations, setRecommendations] = useState<RecommendedAgent[]>([])
  const [analysis, setAnalysis] = useState<TopicAnalysisSummary | null>(null)
  const [specialists, setSpecialists] = useState<SpecialistDefinition[]>([])
  const [rejectedSpecialists, setRejectedSpecialists] = useState<{ name: string; reason: string }[]>([])
  const [excludedSpecialists, setExcludedSpecialists] = useState<string[]>([])
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
    setAnalysis(null)
    setSpecialists([])
    setRejectedSpecialists([])
    setExcludedSpecialists([])
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
      const response = await recommendAgents(topicForRequest, { context, mode })
      // Drop superseded responses so an older answer never overwrites a newer one.
      if (seq !== recSeqRef.current) return
      // The topic changed while this request was in flight: the queued
      // refresh owns the state now, so this result is discarded.
      if (desiredTopicRef.current.trim() !== topicForRequest) return
      setRecommendations(response.agents)
      setAnalysis(response.analysis ?? null)
      setSpecialists(response.specialists ?? [])
      setRejectedSpecialists(response.rejected_specialists ?? [])
      setExcludedSpecialists([])
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

  const includedSpecialists = specialists.filter((s) => !excludedSpecialists.includes(s.name))

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
      } else if (recError || recommendations.length + includedSpecialists.length < MIN_AGENTS) {
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
    await submit(true)
  }

  async function submit(startNow: boolean) {
    if (submitting) return
    const found = validate()
    setErrors(found)
    if (found.length > 0) return

    setSubmitting(true)
    try {
      const debate = await createDebate({
        topic: topic.trim(),
        context: context.trim() || null,
        specialists: selectionMode === 'auto' ? includedSpecialists : [],
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
      // The debate page starts it (live updates are wired up there).
      navigate(`/debates/${debate.id}`, startNow ? { state: { autoStart: true } } : undefined)
    } catch (err) {
      setErrors([apiErrorMessage(err, 'Could not create the debate. Please try again.')])
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageShell maxWidth="sm">
      <PageHeader
        title="New Debate"
        description="Describe the question, review the expert panel MAVES selects for it, and start the debate. You can follow every round live."
      />

      {loadError && (
        <div className="mb-6">
          <ErrorBanner title="Could not load agents" message={loadError} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6" noValidate>
        <section className="card space-y-4" aria-labelledby="step-topic">
          <StepHeading id="step-topic" step={1} title="Topic" />
          <div>
            <label htmlFor="topic" className="label">
              Debate question
            </label>
            <textarea
              id="topic"
              rows={2}
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              maxLength={MAX_TOPIC_LENGTH}
              placeholder="e.g. Should governments regulate generative AI models before public release?"
              className="input resize-y"
              aria-describedby="topic-hint"
            />
            <p id="topic-hint" className="field-hint flex justify-between gap-3">
              <span>Phrase it as a clear, debatable question.</span>
              <span className="tabular-nums">
                {topic.length}/{MAX_TOPIC_LENGTH}
              </span>
            </p>
          </div>
          <div>
            <label htmlFor="context" className="label">
              Context <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <textarea
              id="context"
              rows={3}
              value={context}
              onChange={(e) => setContext(e.target.value)}
              maxLength={MAX_CONTEXT_LENGTH}
              placeholder="e.g. Focus on hospitals in low-income countries over the next five years."
              className="input resize-y"
              aria-describedby="context-hint"
            />
            <p id="context-hint" className="field-hint flex justify-between gap-3">
              <span>Scope, region or framing every agent should keep in mind.</span>
              <span className="tabular-nums">
                {context.length}/{MAX_CONTEXT_LENGTH}
              </span>
            </p>
          </div>
        </section>

        <section className="card space-y-4" aria-labelledby="step-agents">
          <StepHeading id="step-agents" step={2} title="Expert panel" />
          <fieldset>
            <legend className="label">Agent selection</legend>
            <div className="inline-flex flex-wrap rounded-lg border border-gray-700 bg-gray-800 p-1">
              {(['auto', 'manual'] as const).map((value) => (
                <label
                  key={value}
                  className={`cursor-pointer rounded-md px-4 py-1.5 text-sm font-medium transition-colors focus-within:ring-2 focus-within:ring-indigo-500 ${
                    selectionMode === value
                      ? 'bg-indigo-600 text-white'
                      : 'text-gray-300 hover:text-white'
                  }`}
                >
                  <input
                    type="radio"
                    name="selection_mode"
                    value={value}
                    checked={selectionMode === value}
                    onChange={() => setSelectionMode(value)}
                    className="sr-only"
                  />
                  {value === 'auto' ? 'Automatic (topic-aware)' : 'Manual'}
                </label>
              ))}
            </div>
            <p className="field-hint">
              {selectionMode === 'auto'
                ? 'MAVES analyzes your topic and recommends the most relevant experts, each with a short reason.'
                : `Pick at least ${MIN_AGENTS} agents yourself.`}
            </p>
          </fieldset>

        {selectionMode === 'auto' && (
          <div
            className="rounded-xl border border-gray-800 bg-gray-950/50 p-4"
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

            {analysis && (
              <div className="mt-4 rounded-lg border border-gray-800 bg-gray-950/40 p-3 text-xs text-gray-400" data-testid="topic-analysis">
                <p>
                  <span className="font-semibold text-gray-300">Main domain:</span> {analysis.main_domain}
                  {analysis.secondary_domains.length > 0 && <> · {analysis.secondary_domains.join(', ')}</>}
                </p>
                {analysis.key_questions.length > 0 && (
                  <ul className="mt-1 list-disc pl-5">
                    {analysis.key_questions.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {specialists.length > 0 && (
              <div className="mt-4" data-testid="specialists-section">
                <h3 className="text-sm font-semibold text-gray-200">Additional AI specialist roles</h3>
                <p className="field-hint mb-2">
                  Generated for this topic because the built-in agents do not cover this
                  expertise. They are AI perspectives, not human experts, and follow the same
                  evidence and debate rules. Untick any you do not want.
                </p>
                <ul className="space-y-2">
                  {specialists.map((spec) => {
                    const included = !excludedSpecialists.includes(spec.name)
                    return (
                      <li key={spec.name}>
                        <label className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors focus-within:ring-2 focus-within:ring-indigo-500/50 ${included ? 'border-violet-500/50 bg-violet-500/5' : 'border-gray-800 opacity-60'}`}>
                          <input
                            type="checkbox"
                            checked={included}
                            onChange={() =>
                              setExcludedSpecialists((current) =>
                                included ? [...current, spec.name] : current.filter((n) => n !== spec.name),
                              )
                            }
                            className="mt-1"
                            data-testid="specialist-toggle"
                          />
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
                              {spec.name}
                              <span className="rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-300">
                                AI specialist role
                              </span>
                              <span className="text-xs font-normal text-gray-500">
                                {spec.domain}{spec.subdomain ? ` · ${spec.subdomain}` : ''}
                              </span>
                            </span>
                            <span className="mt-1 block text-sm text-gray-300">{spec.expertise}</span>
                            {spec.reason && (
                              <span className="mt-1 block text-xs text-gray-400">Why: {spec.reason}</span>
                            )}
                          </span>
                        </label>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {rejectedSpecialists.length > 0 && (
              <details className="mt-3 text-xs text-gray-500">
                <summary className="cursor-pointer">
                  {rejectedSpecialists.length} proposed role(s) were removed by validation
                </summary>
                <ul className="mt-1 list-disc pl-5">
                  {rejectedSpecialists.map((r) => (
                    <li key={r.name + r.reason}>
                      {r.name}: {r.reason}
                    </li>
                  ))}
                </ul>
              </details>
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
        </section>

        <section className="card space-y-4" aria-labelledby="step-config">
          <StepHeading id="step-config" step={3} title="Format" />
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

        <label className="flex items-start gap-3 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={verifyEvidence}
            onChange={(e) => setVerifyEvidence(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Verify claims automatically after the debate
            <span className="block text-xs text-gray-400">
              Extracts factual claims, searches web sources and checks them, then
              writes the final verdict. Uses extra language-model calls.
            </span>
          </span>
        </label>
        </section>

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

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={() => void submit(false)}
            disabled={submitting || loadError !== null}
            className="btn-secondary py-3"
          >
            Save without starting
          </button>
          <button
            type="submit"
            disabled={submitting || loadError !== null}
            className="btn-primary px-8 py-3 text-base"
            data-testid="start-debate-submit"
          >
            {submitting ? 'Creating debate...' : 'Start Debate'}
          </button>
        </div>
        <p className="text-right text-xs text-gray-500">
          A debate runs every round in sequence; this usually takes about a minute.
        </p>
      </form>
    </PageShell>
  )
}
