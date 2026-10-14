import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError } from '../services/api'
import {
  DEBATE_MODES,
  debateStatusLabel,
  debateStatusTone,
  getDebate,
  getRounds,
  getTranscript,
  startDebate,
  type Debate,
  type DebateRound,
  type TranscriptMessage,
} from '../services/debates'
import {
  DebateWebSocketClient,
  type DebateEvent,
  type WebSocketState,
} from '../services/websocket'
import {
  claimTypeLabel,
  confidenceLabel,
  extractClaims,
  getClaims,
  getEvidence,
  getVerification,
  retrieveEvidence,
  verdictLabel,
  verifyClaim,
  type Claim,
  type ClaimVerification,
  type EvidenceItem,
} from '../services/claims'
import {
  analyzeMessageFallacies,
  confidencePercent,
  evaluateMessage,
  fallacyLabel,
  getDebateEvaluations,
  getDebateFallacies,
  scoreDisplay,
  severityLabel,
  type ArgumentEvaluation,
  type Fallacy,
} from '../services/analysis'

function verdictBadgeClass(verdict: string): string {
  const base =
    'rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide'
  if (verdict === 'supported')
    return `${base} border-emerald-700 bg-emerald-950/70 text-emerald-300`
  if (verdict === 'contradicted')
    return `${base} border-red-700 bg-red-950/70 text-red-300`
  return `${base} border-slate-600 bg-slate-800 text-slate-300`
}

function fallacyBadgeClass(fallacyType: string): string {
  const base =
    'rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide'
  if (fallacyType === 'no_fallacy')
    return `${base} border-emerald-700 bg-emerald-950/70 text-emerald-300`
  return `${base} border-amber-700 bg-amber-950/70 text-amber-300`
}

function severityBadgeClass(severity: string): string {
  const base =
    'rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide'
  if (severity === 'high')
    return `${base} border-red-700 bg-red-950/70 text-red-300`
  if (severity === 'medium')
    return `${base} border-amber-700 bg-amber-950/70 text-amber-300`
  return `${base} border-slate-600 bg-slate-800 text-slate-300`
}

function apiErrorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiClientError
    ? err.detail
    : err instanceof Error
      ? err.message
      : fallback
}

export default function DebateDetail() {
  const { debateId } = useParams<{ debateId: string }>()
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const [debate, setDebate] = useState<Debate | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [rounds, setRounds] = useState<DebateRound[]>([])
  const [messages, setMessages] = useState<TranscriptMessage[]>([])
  const [wsState, setWsState] = useState<WebSocketState>('disconnected')
  const [liveRound, setLiveRound] = useState<number | null>(null)
  const [currentSpeaker, setCurrentSpeaker] = useState<string | null>(null)
  const [liveNotice, setLiveNotice] = useState<string | null>(null)

  const [claims, setClaims] = useState<Claim[]>([])
  const [claimsLoading, setClaimsLoading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [claimsNotice, setClaimsNotice] = useState<string | null>(null)
  const [evidenceByClaim, setEvidenceByClaim] = useState<
    Record<string, EvidenceItem[]>
  >({})
  const [evidenceLoading, setEvidenceLoading] = useState<
    Record<string, boolean>
  >({})
  const [evidenceErrors, setEvidenceErrors] = useState<
    Record<string, string | null>
  >({})
  const [verificationByClaim, setVerificationByClaim] = useState<
    Record<string, ClaimVerification>
  >({})
  const [verifying, setVerifying] = useState<Record<string, boolean>>({})
  const [verificationErrors, setVerificationErrors] = useState<
    Record<string, string | null>
  >({})

  const [fallacyByMessage, setFallacyByMessage] = useState<
    Record<string, Fallacy>
  >({})
  const [analyzingFallacy, setAnalyzingFallacy] = useState<
    Record<string, boolean>
  >({})
  const [fallacyErrors, setFallacyErrors] = useState<
    Record<string, string | null>
  >({})
  const [evaluationByMessage, setEvaluationByMessage] = useState<
    Record<string, ArgumentEvaluation>
  >({})
  const [evaluatingArgument, setEvaluatingArgument] = useState<
    Record<string, boolean>
  >({})
  const [evaluationErrors, setEvaluationErrors] = useState<
    Record<string, string | null>
  >({})

  const wsClientRef = useRef<DebateWebSocketClient | null>(null)
  const wsDebateIdRef = useRef<string | null>(null)

  const loadExecutionState = useCallback(async (id: string) => {
    try {
      const [roundsResponse, transcriptResponse] = await Promise.all([
        getRounds(id),
        getTranscript(id),
      ])
      setRounds(roundsResponse.rounds)
      setMessages(transcriptResponse.messages)
    } catch {
      // The transcript is optional: the debate details remain visible.
    }
  }, [])

  // Read stored evidence for the given claims (database only, no provider
  // calls). Claims without stored evidence stay undefined so the UI can tell
  // "never retrieved" apart from "retrieved, nothing found".
  const loadStoredEvidence = useCallback(async (claimList: Claim[]) => {
    const entries = await Promise.all(
      claimList.map(async (claim) => {
        try {
          const response = await getEvidence(claim.id)
          return [claim.id, response.evidence] as const
        } catch {
          return [claim.id, undefined] as const
        }
      }),
    )
    const record: Record<string, EvidenceItem[]> = {}
    for (const [claimId, items] of entries) {
      if (items && items.length > 0) record[claimId] = items
    }
    setEvidenceByClaim((prev) => ({ ...prev, ...record }))
  }, [])

  // Read stored verification results for the given claims (database only,
  // never the LLM). Claims without a stored result stay undefined.
  const loadStoredVerifications = useCallback(async (claimList: Claim[]) => {
    const entries = await Promise.all(
      claimList.map(async (claim) => {
        try {
          const verification = await getVerification(claim.id)
          return [claim.id, verification] as const
        } catch {
          return [claim.id, undefined] as const
        }
      }),
    )
    const record: Record<string, ClaimVerification> = {}
    for (const [claimId, verification] of entries) {
      if (verification) record[claimId] = verification
    }
    setVerificationByClaim((prev) => ({ ...prev, ...record }))
  }, [])

  const loadClaims = useCallback(
    async (id: string) => {
      setClaimsLoading(true)
      try {
        const response = await getClaims(id)
        setClaims(response.claims)
        setClaimsNotice(null)
        await Promise.all([
          loadStoredEvidence(response.claims),
          loadStoredVerifications(response.claims),
        ])
      } catch (err) {
        setClaimsNotice(
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Unable to load claims.',
        )
      } finally {
        setClaimsLoading(false)
      }
    },
    [loadStoredEvidence, loadStoredVerifications],
  )

  // Claims only exist after a debate has produced messages.
  useEffect(() => {
    if (!debateId || !debate || debate.status === 'pending') return
    void loadClaims(debateId)
  }, [debateId, debate?.status, loadClaims])

  // Read stored fallacy analyses and argument evaluations (database only,
  // never the LLM) so results survive a page refresh.
  const loadAnalysis = useCallback(async (id: string) => {
    try {
      const [fallacies, evaluations] = await Promise.all([
        getDebateFallacies(id).catch(() => null),
        getDebateEvaluations(id).catch(() => null),
      ])
      if (fallacies) {
        const record: Record<string, Fallacy> = {}
        for (const item of fallacies.fallacies) record[item.message_id] = item
        setFallacyByMessage(record)
      }
      if (evaluations) {
        const record: Record<string, ArgumentEvaluation> = {}
        for (const item of evaluations.evaluations)
          record[item.message_id] = item
        setEvaluationByMessage(record)
      }
    } catch {
      // Argument analysis is optional: the transcript stays usable without it.
    }
  }, [])

  useEffect(() => {
    if (!debateId || !debate || debate.status === 'pending') return
    void loadAnalysis(debateId)
  }, [debateId, debate?.status, loadAnalysis])

  // Re-read the authoritative state over HTTP when the live channel reports a
  // terminal event, so the final view is exactly what the backend persisted.
  const reconcileAfterFinish = useCallback(
    async (id: string) => {
      wsClientRef.current?.disconnect()
      try {
        const refreshed = await getDebate(id)
        setDebate(refreshed)
        await loadExecutionState(refreshed.id)
      } catch {
        // Keep the live view if the refresh also fails.
      }
    },
    [loadExecutionState],
  )

  const handleLiveEvent = useCallback(
    (event: DebateEvent) => {
      const data = event.data ?? {}
      switch (event.type) {
        case 'debate_started':
          setLiveNotice(null)
          setDebate((prev) => (prev ? { ...prev, status: 'running' } : prev))
          break
        case 'round_started': {
          const roundNumber = data.round_number ?? 0
          setLiveRound(roundNumber)
          setCurrentSpeaker(null)
          setRounds((prev) => {
            const existing = prev.find(
              (round) => round.round_number === roundNumber,
            )
            if (existing) {
              return prev.map((round) =>
                round.round_number === roundNumber
                  ? {
                      ...round,
                      status: 'running',
                      started_at: round.started_at ?? event.timestamp,
                    }
                  : round,
              )
            }
            return [
              ...prev,
              {
                round_number: roundNumber,
                status: 'running',
                started_at: event.timestamp,
                completed_at: null,
              },
            ].sort((a, b) => a.round_number - b.round_number)
          })
          break
        }
        case 'agent_turn_started':
          setLiveRound((prev) => data.round_number ?? prev)
          setCurrentSpeaker(data.agent?.name ?? null)
          break
        case 'agent_message': {
          const messageId = data.message_id
          if (!messageId) break
          setMessages((prev) => {
            if (prev.some((message) => message.id === messageId)) return prev
            return [
              ...prev,
              {
                id: messageId,
                round_number: data.round_number ?? 0,
                turn_number: data.turn_number ?? 0,
                agent: data.agent ?? { id: '', name: 'Agent', role: '' },
                message_type: data.message_type ?? 'statement',
                content: data.content ?? '',
                created_at: event.timestamp,
              },
            ].sort(
              (a, b) =>
                a.round_number - b.round_number || a.turn_number - b.turn_number,
            )
          })
          break
        }
        case 'agent_turn_completed':
          setCurrentSpeaker(null)
          break
        case 'round_completed':
          setRounds((prev) =>
            prev.map((round) =>
              round.round_number === (data.round_number ?? 0)
                ? {
                    ...round,
                    status: 'completed',
                    completed_at: event.timestamp,
                  }
                : round,
            ),
          )
          break
        case 'debate_completed':
        case 'debate_failed':
          setLiveRound(null)
          setCurrentSpeaker(null)
          // End the start phase here too: otherwise the watch effect would
          // reopen the socket we are about to close while the POST is still
          // in flight.
          setStarting(false)
          setDebate((prev) =>
            prev
              ? {
                  ...prev,
                  status:
                    event.type === 'debate_completed' ? 'completed' : 'failed',
                }
              : prev,
          )
          void reconcileAfterFinish(debateId ?? '')
          break
        case 'error':
          setLiveNotice(data.message ?? 'The live connection reported an error.')
          break
        default:
          break
      }
    },
    [debateId, reconcileAfterFinish],
  )

  const handleLiveEventRef = useRef(handleLiveEvent)
  handleLiveEventRef.current = handleLiveEvent

  const hadConnectedRef = useRef(false)

  const handleWsState = useCallback(
    (state: WebSocketState) => {
      setWsState(state)
      if (state === 'connected') {
        // After a drop, recover missed rounds/messages over HTTP (there is no
        // event replay); the first connection never needs it.
        if (hadConnectedRef.current && debateId) {
          void loadExecutionState(debateId)
        }
        hadConnectedRef.current = true
      }
    },
    [debateId, loadExecutionState],
  )

  const handleWsStateRef = useRef(handleWsState)
  handleWsStateRef.current = handleWsState

  const ensureClient = useCallback((id: string) => {
    if (wsClientRef.current && wsDebateIdRef.current === id) {
      return wsClientRef.current
    }
    wsClientRef.current?.disconnect()
    const client = new DebateWebSocketClient(id, {
      onEvent: (event) => handleLiveEventRef.current(event),
      onStateChange: (state) => handleWsStateRef.current(state),
    })
    wsClientRef.current = client
    wsDebateIdRef.current = id
    return client
  }, [])

  // Watch while the debate can still emit events (local start in progress or
  // a running debate after a page refresh).
  useEffect(() => {
    if (!debateId || !debate) return
    if (starting || debate.status === 'running') {
      ensureClient(debateId).connect()
    } else {
      wsClientRef.current?.disconnect()
    }
  }, [debateId, debate?.status, starting, ensureClient])

  useEffect(() => {
    return () => {
      wsClientRef.current?.disconnect()
    }
  }, [])

  useEffect(() => {
    if (!debateId) {
      setError('Missing debate id.')
      setLoading(false)
      return
    }
    // Always fetch the current state from the backend on load, so a refresh
    // while a debate is running shows the real status.
    getDebate(debateId)
      .then(async (loaded) => {
        setDebate(loaded)
        if (loaded.status !== 'pending') {
          await loadExecutionState(loaded.id)
        }
      })
      .catch((err) =>
        setError(
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Unable to load this debate.',
        ),
      )
      .finally(() => setLoading(false))
  }, [debateId, loadExecutionState])

  async function handleStart() {
    if (!debate || starting) return
    setStarting(true)
    setError(null)
    setLiveNotice(null)
    // Open the live channel first: the start request blocks until the debate
    // finishes, and every event must be captured from the very beginning.
    ensureClient(debate.id).connect()
    try {
      // The start endpoint runs the whole debate before it answers, so the
      // response already carries the final state.
      const finished = await startDebate(debate.id)
      setDebate(finished)
      await loadExecutionState(finished.id)
    } catch (err) {
      setError(
        err instanceof ApiClientError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'The debate could not be started.',
      )
      try {
        const refreshed = await getDebate(debate.id)
        setDebate(refreshed)
        await loadExecutionState(refreshed.id)
      } catch {
        // Keep the current view if the refresh also fails.
      }
    } finally {
      setStarting(false)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  async function handleExtractClaims() {
    if (!debate || extracting) return
    setExtracting(true)
    setClaimsNotice(null)
    try {
      const response = await extractClaims(debate.id)
      setClaims(response.claims)
      await Promise.all([
        loadStoredEvidence(response.claims),
        loadStoredVerifications(response.claims),
      ])
    } catch (err) {
      setClaimsNotice(
        err instanceof ApiClientError
          ? err.detail
          : err instanceof Error
            ? err.message
            : 'Claim extraction failed.',
      )
    } finally {
      setExtracting(false)
    }
  }

  async function handleRetrieveEvidence(claimId: string) {
    if (evidenceLoading[claimId]) return
    setEvidenceLoading((prev) => ({ ...prev, [claimId]: true }))
    setEvidenceErrors((prev) => ({ ...prev, [claimId]: null }))
    try {
      const response = await retrieveEvidence(claimId)
      setEvidenceByClaim((prev) => ({ ...prev, [claimId]: response.evidence }))
    } catch (err) {
      setEvidenceErrors((prev) => ({
        ...prev,
        [claimId]:
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Evidence retrieval failed.',
      }))
    } finally {
      setEvidenceLoading((prev) => ({ ...prev, [claimId]: false }))
    }
  }

  async function handleVerifyClaim(claimId: string) {
    if (verifying[claimId]) return
    setVerifying((prev) => ({ ...prev, [claimId]: true }))
    setVerificationErrors((prev) => ({ ...prev, [claimId]: null }))
    try {
      const result = await verifyClaim(claimId)
      setVerificationByClaim((prev) => ({ ...prev, [claimId]: result }))
    } catch (err) {
      setVerificationErrors((prev) => ({
        ...prev,
        [claimId]:
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Claim verification failed.',
      }))
    } finally {
      setVerifying((prev) => ({ ...prev, [claimId]: false }))
    }
  }

  async function handleAnalyzeFallacy(messageId: string) {
    if (analyzingFallacy[messageId]) return
    setAnalyzingFallacy((prev) => ({ ...prev, [messageId]: true }))
    setFallacyErrors((prev) => ({ ...prev, [messageId]: null }))
    try {
      const result = await analyzeMessageFallacies(messageId)
      setFallacyByMessage((prev) => ({ ...prev, [messageId]: result }))
    } catch (err) {
      setFallacyErrors((prev) => ({
        ...prev,
        [messageId]: apiErrorMessage(err, 'Fallacy analysis failed.'),
      }))
    } finally {
      setAnalyzingFallacy((prev) => ({ ...prev, [messageId]: false }))
    }
  }

  async function handleEvaluateArgument(messageId: string) {
    if (evaluatingArgument[messageId]) return
    setEvaluatingArgument((prev) => ({ ...prev, [messageId]: true }))
    setEvaluationErrors((prev) => ({ ...prev, [messageId]: null }))
    try {
      const result = await evaluateMessage(messageId)
      setEvaluationByMessage((prev) => ({ ...prev, [messageId]: result }))
    } catch (err) {
      setEvaluationErrors((prev) => ({
        ...prev,
        [messageId]: apiErrorMessage(err, 'Argument evaluation failed.'),
      }))
    } finally {
      setEvaluatingArgument((prev) => ({ ...prev, [messageId]: false }))
    }
  }

  const modeLabel =
    DEBATE_MODES.find((option) => option.value === debate?.mode)?.label ??
    debate?.mode

  const messagesForRound = (roundNumber: number) =>
    messages.filter((message) => message.round_number === roundNumber)

  const canStart = debate?.status === 'pending' && !starting

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
          <button
            onClick={handleLogout}
            className="bg-red-600 hover:bg-red-700 rounded-lg px-4 py-2 text-sm font-semibold"
          >
            Logout
          </button>
        </nav>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        <h2 className="text-2xl font-semibold mb-2">Debate Details</h2>
        <p className="text-gray-400 mb-8">Signed in as {user?.email}</p>

        {loading && <p className="text-gray-400">Loading debate...</p>}

        {error && (
          <div className="mb-6 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
            <p className="text-sm font-medium text-red-300">
              {starting ? 'Debate could not be started' : 'Debate not available'}
            </p>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
            {!debate && (
              <Link
                to="/debates"
                className="mt-3 inline-block text-sm text-indigo-400 hover:text-indigo-300"
              >
                Back to your debates
              </Link>
            )}
          </div>
        )}

        {!loading && debate && (
          <>
            <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-start justify-between gap-4">
                <h3 className="text-xl font-semibold">{debate.topic}</h3>
                <span
                  data-testid="debate-status"
                  className={`shrink-0 rounded-full border px-3 py-1 text-xs ${debateStatusTone(debate.status)}`}
                >
                  Status: {debateStatusLabel(debate.status)}
                </span>
              </div>

              <dl className="mt-6 grid gap-3 sm:grid-cols-2">
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Selection mode</dt>
                  <dd className="capitalize">{debate.expert_selection_mode}</dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Debate mode</dt>
                  <dd>{modeLabel}</dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Rounds</dt>
                  <dd>
                    {Math.max(debate.round_count, rounds.length)}/
                    {debate.total_rounds}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Evidence verification</dt>
                  <dd>{debate.verify_evidence ? 'Enabled' : 'Disabled'}</dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Domain tags</dt>
                  <dd className="text-right">
                    {debate.domain_tags && debate.domain_tags.length > 0
                      ? debate.domain_tags.join(', ')
                      : 'None'}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Created</dt>
                  <dd>{new Date(debate.created_at).toLocaleString()}</dd>
                </div>
                {debate.started_at && (
                  <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                    <dt className="text-gray-400">Started</dt>
                    <dd>{new Date(debate.started_at).toLocaleString()}</dd>
                  </div>
                )}
                {debate.completed_at && (
                  <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                    <dt className="text-gray-400">Finished</dt>
                    <dd>{new Date(debate.completed_at).toLocaleString()}</dd>
                  </div>
                )}
              </dl>

              {debate.status === 'pending' && (
                <div className="mt-6">
                  <button
                    onClick={handleStart}
                    disabled={!canStart}
                    data-testid="start-debate"
                    className={`rounded-lg px-5 py-2.5 text-sm font-semibold ${
                      canStart
                        ? 'bg-indigo-600 hover:bg-indigo-700'
                        : 'cursor-not-allowed bg-indigo-900/50 text-indigo-300/60'
                    }`}
                  >
                    {starting ? 'Starting debate...' : 'Start debate'}
                  </button>
                  <p className="mt-2 text-xs text-gray-500">
                    This debate has not started yet. Once started, it runs all
                    rounds before the page returns. This can take about a
                    minute.
                  </p>
                </div>
              )}

              {(starting || debate.status === 'running') && (
                <div
                  className="mt-6 rounded-lg border border-blue-900/60 bg-blue-950/40 px-4 py-3"
                  data-testid="live-panel"
                >
                  <div className="flex items-center justify-between gap-3">
                    <p className="text-sm font-semibold text-blue-200">
                      Live debate
                    </p>
                    <span
                      data-testid="ws-state"
                      className={`text-xs font-medium ${
                        wsState === 'connected'
                          ? 'text-emerald-300'
                          : wsState === 'error'
                            ? 'text-red-300'
                            : 'text-amber-300'
                      }`}
                    >
                      {wsState === 'connected'
                        ? 'Connected'
                        : wsState === 'connecting'
                          ? 'Connecting...'
                          : wsState === 'error'
                            ? 'Live updates unavailable'
                            : 'Reconnecting...'}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-blue-300">
                    {liveRound
                      ? `Round ${liveRound} of ${debate.total_rounds}`
                      : 'Waiting for the first round...'}
                    {currentSpeaker ? ` — ${currentSpeaker} is speaking` : ''}
                  </p>
                  <p className="mt-1 text-xs text-blue-400/80">
                    The transcript and rounds below update as the debate runs.
                  </p>
                  {liveNotice && (
                    <p
                      className="mt-1 text-xs text-amber-300"
                      data-testid="live-notice"
                    >
                      {liveNotice}
                    </p>
                  )}
                </div>
              )}

              {debate.status === 'failed' && (
                <div className="mt-6 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
                  <p className="text-sm text-red-300">
                    The debate failed while it was running. Messages generated
                    before the failure are kept below.
                  </p>
                </div>
              )}
            </div>

            <div className="mt-6 rounded-2xl border border-gray-800 bg-gray-900 p-6">
              <h4 className="text-lg font-semibold mb-4">
                Participating agents ({debate.agents.length})
              </h4>
              <ul className="space-y-3">
                {debate.agents.map((agent) => (
                  <li
                    key={agent.id}
                    className="rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3"
                  >
                    <p className="font-semibold">{agent.name}</p>
                    <p className="text-sm text-gray-400">{agent.description}</p>
                  </li>
                ))}
              </ul>
            </div>

            {debate.status !== 'pending' && (
              <div className="mt-6 rounded-2xl border border-gray-800 bg-gray-900 p-6">
                <h4 className="text-lg font-semibold mb-4">Rounds</h4>
                {rounds.length === 0 ? (
                  <p className="text-sm text-gray-400">
                    No round has been recorded yet.
                  </p>
                ) : (
                  <ul className="space-y-3">
                    {rounds.map((round) => (
                      <li
                        key={round.round_number}
                        className="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3 text-sm"
                      >
                        <span className="font-semibold">
                          Round {round.round_number}
                        </span>
                        <span className="text-gray-400">
                          {debateStatusLabel(round.status)}
                        </span>
                        <span className="text-gray-500">
                          {round.started_at
                            ? new Date(round.started_at).toLocaleTimeString()
                            : 'not started'}
                          {' - '}
                          {round.completed_at
                            ? new Date(round.completed_at).toLocaleTimeString()
                            : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {messages.length > 0 && (
              <div className="mt-6 rounded-2xl border border-gray-800 bg-gray-900 p-6">
                <h4 className="text-lg font-semibold mb-4">Transcript</h4>
                <div className="space-y-6">
                  {rounds.map((round) => {
                    const roundMessages = messagesForRound(round.round_number)
                    if (roundMessages.length === 0) return null
                    return (
                      <section key={round.round_number}>
                        <h5 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
                          Round {round.round_number}
                        </h5>
                        <div className="space-y-4">
                          {roundMessages.map((message) => {
                            const analyzing = !!analyzingFallacy[message.id]
                            const evaluating = !!evaluatingArgument[message.id]
                            const fallacy = fallacyByMessage[message.id]
                            const fallacyError =
                              fallacyErrors[message.id] ?? null
                            const evaluation =
                              evaluationByMessage[message.id]
                            const evaluationError =
                              evaluationErrors[message.id] ?? null
                            return (
                              <article
                                key={message.id}
                                className="rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3"
                              >
                                <div className="mb-2 flex items-center justify-between gap-3">
                                  <p className="text-sm font-semibold text-indigo-300">
                                    {message.agent.name}
                                  </p>
                                  <span className="text-xs uppercase text-gray-500">
                                    {message.message_type}
                                  </span>
                                </div>
                                <p className="whitespace-pre-wrap text-sm text-gray-200">
                                  {message.content}
                                </p>

                                <div className="mt-3 flex flex-wrap gap-2">
                                  <button
                                    onClick={() =>
                                      handleAnalyzeFallacy(message.id)
                                    }
                                    disabled={analyzing}
                                    data-testid="analyze-argument"
                                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                                      analyzing
                                        ? 'cursor-not-allowed bg-purple-900/50 text-purple-300/60'
                                        : 'bg-purple-700 hover:bg-purple-600'
                                    }`}
                                  >
                                    {analyzing
                                      ? 'Analyzing argument...'
                                      : 'Analyze Argument'}
                                  </button>
                                  <button
                                    onClick={() =>
                                      handleEvaluateArgument(message.id)
                                    }
                                    disabled={evaluating}
                                    data-testid="evaluate-argument"
                                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                                      evaluating
                                        ? 'cursor-not-allowed bg-teal-900/50 text-teal-300/60'
                                        : 'bg-teal-700 hover:bg-teal-600'
                                    }`}
                                  >
                                    {evaluating
                                      ? 'Evaluating argument...'
                                      : 'Evaluate Argument'}
                                  </button>
                                </div>

                                {fallacyError && (
                                  <div
                                    className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2"
                                    data-testid="fallacy-error"
                                  >
                                    <p className="text-xs text-amber-200">
                                      {fallacyError}
                                    </p>
                                  </div>
                                )}

                                {fallacy && (
                                  <div
                                    className="mt-3 rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-3"
                                    data-testid="fallacy-result"
                                  >
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                                      Fallacy Analysis
                                    </p>
                                    {fallacy.fallacy_type === 'no_fallacy' ? (
                                      <p
                                        className="mt-2 text-sm text-emerald-300"
                                        data-testid="fallacy-none"
                                      >
                                        No clear fallacy detected.
                                      </p>
                                    ) : (
                                      <>
                                        <div className="mt-2 flex flex-wrap items-center gap-2">
                                          <span
                                            data-testid="fallacy-type"
                                            className={fallacyBadgeClass(
                                              fallacy.fallacy_type,
                                            )}
                                          >
                                            {fallacyLabel(fallacy.fallacy_type)}
                                          </span>
                                          <span
                                            data-testid="fallacy-severity"
                                            className={severityBadgeClass(
                                              fallacy.severity,
                                            )}
                                          >
                                            Severity:{' '}
                                            {severityLabel(fallacy.severity)}
                                          </span>
                                          <span
                                            data-testid="fallacy-confidence"
                                            className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400"
                                          >
                                            Confidence:{' '}
                                            {confidencePercent(
                                              fallacy.confidence,
                                            )}
                                          </span>
                                        </div>
                                        <p
                                          className="mt-2 text-sm text-gray-200"
                                          data-testid="fallacy-explanation"
                                        >
                                          {fallacy.explanation}
                                        </p>
                                        {fallacy.evidence_span && (
                                          <p
                                            className="mt-1 text-xs text-gray-400"
                                            data-testid="fallacy-span"
                                          >
                                            &quot;{fallacy.evidence_span}&quot;
                                          </p>
                                        )}
                                      </>
                                    )}
                                    <p className="mt-2 text-xs text-gray-500">
                                      A fallacy marks a flaw in the
                                      argument&apos;s reasoning only. It does
                                      not mean the underlying claim is false.
                                    </p>
                                  </div>
                                )}

                                {evaluationError && (
                                  <div
                                    className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2"
                                    data-testid="evaluation-error"
                                  >
                                    <p className="text-xs text-amber-200">
                                      {evaluationError}
                                    </p>
                                  </div>
                                )}

                                {evaluation && (
                                  <div
                                    className="mt-3 rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-3"
                                    data-testid="evaluation-result"
                                  >
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                                      Argument Quality
                                    </p>
                                    <dl className="mt-2 grid gap-1 text-sm text-gray-200 sm:grid-cols-2">
                                      <div className="flex justify-between gap-2 rounded bg-gray-800/70 px-2 py-1">
                                        <dt className="text-gray-400">
                                          Logical Soundness
                                        </dt>
                                        <dd
                                          data-testid="evaluation-logical"
                                          className="font-semibold"
                                        >
                                          {scoreDisplay(
                                            evaluation.logical_soundness,
                                          )}
                                          /10
                                        </dd>
                                      </div>
                                      <div className="flex justify-between gap-2 rounded bg-gray-800/70 px-2 py-1">
                                        <dt className="text-gray-400">
                                          Evidence
                                        </dt>
                                        <dd
                                          data-testid="evaluation-evidence"
                                          className="font-semibold"
                                        >
                                          {scoreDisplay(evaluation.evidence_score)}
                                          /10
                                        </dd>
                                      </div>
                                      <div className="flex justify-between gap-2 rounded bg-gray-800/70 px-2 py-1">
                                        <dt className="text-gray-400">
                                          Relevance
                                        </dt>
                                        <dd
                                          data-testid="evaluation-relevance"
                                          className="font-semibold"
                                        >
                                          {scoreDisplay(
                                            evaluation.relevance_score,
                                          )}
                                          /10
                                        </dd>
                                      </div>
                                      <div className="flex justify-between gap-2 rounded bg-gray-800/70 px-2 py-1">
                                        <dt className="text-gray-400">
                                          Effectiveness
                                        </dt>
                                        <dd
                                          data-testid="evaluation-effectiveness"
                                          className="font-semibold"
                                        >
                                          {scoreDisplay(
                                            evaluation.effectiveness_score,
                                          )}
                                          /10
                                        </dd>
                                      </div>
                                    </dl>
                                    <p
                                      className="mt-2 text-sm font-semibold text-teal-300"
                                      data-testid="evaluation-overall"
                                    >
                                      Overall: {scoreDisplay(evaluation.overall_score)}
                                      /10
                                    </p>
                                    <p
                                      className="mt-1 text-sm text-gray-200"
                                      data-testid="evaluation-explanation"
                                    >
                                      {evaluation.explanation}
                                    </p>
                                    <p
                                      className="mt-2 text-xs text-gray-500"
                                      data-testid="evaluation-disclaimer"
                                    >
                                      Argument quality scores measure reasoning
                                      and presentation quality; they do not
                                      determine absolute truth.
                                    </p>
                                  </div>
                                )}
                              </article>
                            )
                          })}
                        </div>
                      </section>
                    )
                  })}
                </div>
              </div>
            )}

            {messages.length > 0 && (
              <div
                className="mt-6 rounded-2xl border border-gray-800 bg-gray-900 p-6"
                data-testid="claims-section"
              >
                <div className="mb-4 flex items-center justify-between gap-3">
                  <h4 className="text-lg font-semibold">Claims</h4>
                  <button
                    onClick={handleExtractClaims}
                    disabled={extracting}
                    data-testid="extract-claims"
                    className={`rounded-lg px-4 py-2 text-sm font-semibold ${
                      extracting
                        ? 'cursor-not-allowed bg-indigo-900/50 text-indigo-300/60'
                        : 'bg-indigo-600 hover:bg-indigo-700'
                    }`}
                  >
                    {extracting ? 'Extracting claims...' : 'Extract Claims'}
                  </button>
                </div>

                {claimsNotice && (
                  <div
                    className="mb-4 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3"
                    data-testid="claims-error"
                  >
                    <p className="text-sm text-red-300">{claimsNotice}</p>
                  </div>
                )}

                {claimsLoading && (
                  <p className="text-sm text-gray-400">Loading claims...</p>
                )}

                {!claimsLoading && claims.length === 0 && !claimsNotice && (
                  <p className="text-sm text-gray-500" data-testid="claims-empty">
                    No claims yet. Select &quot;Extract Claims&quot; to analyse
                    the messages in this debate.
                  </p>
                )}

                {claims.length > 0 && (
                  <ul className="space-y-4">
                    {claims.map((claim) => {
                      const evidenceState = evidenceByClaim[claim.id]
                      const retrieving = !!evidenceLoading[claim.id]
                      const evidenceError = evidenceErrors[claim.id] ?? null
                      const verification = verificationByClaim[claim.id]
                      const verifyLoading = !!verifying[claim.id]
                      const verificationError =
                        verificationErrors[claim.id] ?? null
                      return (
                        <li
                          key={claim.id}
                          data-testid="claim-item"
                          className="rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3"
                        >
                          <div className="flex items-center justify-between gap-3">
                            <p className="text-sm font-semibold text-indigo-300">
                              Agent: {claim.agent_name}
                            </p>
                            <span
                              data-testid="claim-type"
                              className="rounded-full border border-gray-700 px-2 py-0.5 text-xs uppercase tracking-wide text-gray-400"
                            >
                              Type: {claimTypeLabel(claim.claim_type)}
                            </span>
                          </div>
                          <p className="mt-2 text-sm text-gray-200">
                            <span className="text-gray-400">Claim: </span>
                            &quot;{claim.text}&quot;
                          </p>

                          <div className="mt-3 flex flex-wrap gap-2">
                            <button
                              onClick={() => handleRetrieveEvidence(claim.id)}
                              disabled={retrieving}
                              data-testid="retrieve-evidence"
                              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                                retrieving
                                  ? 'cursor-not-allowed bg-gray-700 text-gray-400'
                                  : 'bg-gray-700 hover:bg-gray-600'
                              }`}
                            >
                              {retrieving
                                ? 'Retrieving sources...'
                                : 'Retrieve Evidence'}
                            </button>
                            <button
                              onClick={() => handleVerifyClaim(claim.id)}
                              disabled={verifyLoading}
                              data-testid="verify-claim"
                              className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                                verifyLoading
                                  ? 'cursor-not-allowed bg-indigo-900/50 text-indigo-300/60'
                                  : 'bg-indigo-600 hover:bg-indigo-700'
                              }`}
                            >
                              {verifyLoading
                                ? 'Evaluating evidence...'
                                : 'Verify Claim'}
                            </button>
                          </div>

                          {verificationError && (
                            <div
                              className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2"
                              data-testid="verification-error"
                            >
                              <p className="text-xs text-amber-200">
                                {verificationError}
                              </p>
                            </div>
                          )}

                          {verification && (
                            <div
                              className="mt-3 rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-3"
                              data-testid="verification-result"
                            >
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                                Evidence Evaluation
                              </p>
                              <div className="mt-2 flex flex-wrap items-center gap-2">
                                <span
                                  data-testid="verification-verdict"
                                  className={verdictBadgeClass(
                                    verification.verdict,
                                  )}
                                >
                                  {verdictLabel(verification.verdict)}
                                </span>
                                <span
                                  data-testid="verification-confidence"
                                  className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400"
                                >
                                  Confidence:{' '}
                                  {confidenceLabel(verification.confidence)}
                                </span>
                              </div>
                              <p
                                className="mt-2 text-sm text-gray-200"
                                data-testid="verification-explanation"
                              >
                                {verification.explanation}
                              </p>
                              {verification.evidence_summary && (
                                <p
                                  className="mt-1 text-xs text-gray-400"
                                  data-testid="verification-summary"
                                >
                                  {verification.evidence_summary}
                                </p>
                              )}
                              <p className="mt-2 text-xs text-gray-500">
                                This evaluation reflects what the retrieved
                                sources indicate. It is not an absolute
                                guarantee of truth.
                              </p>
                            </div>
                          )}

                          {evidenceError && (
                            <div
                              className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2"
                              data-testid="evidence-error"
                            >
                              <p className="text-xs text-amber-200">
                                {evidenceError}
                              </p>
                            </div>
                          )}

                          {!retrieving &&
                            !evidenceError &&
                            evidenceState !== undefined &&
                            evidenceState.length === 0 && (
                              <p
                                className="mt-3 text-xs text-gray-500"
                                data-testid="evidence-empty"
                              >
                                No sources found for this claim.
                              </p>
                            )}

                          {evidenceState && evidenceState.length > 0 && (
                            <div className="mt-3" data-testid="evidence-list">
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                                Retrieved sources
                              </p>
                              <ul className="mt-2 space-y-2">
                                {evidenceState.map((item) => (
                                  <li
                                    key={item.id}
                                    data-testid="evidence-item"
                                    className="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-2"
                                  >
                                    <a
                                      href={item.url}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="break-words text-sm font-medium text-indigo-300 hover:text-indigo-200"
                                    >
                                      {item.title}
                                    </a>
                                    <p className="mt-0.5 text-xs text-gray-500">
                                      {item.source_name}{' '}
                                      <span className="break-all">
                                        ({item.url})
                                      </span>
                                    </p>
                                    {item.snippet && (
                                      <p className="mt-1 text-xs text-gray-400">
                                        {item.snippet}
                                      </p>
                                    )}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}

                <p className="mt-4 text-xs text-gray-500">
                  Retrieved sources are search results shown for reference only.
                  They do not indicate whether a claim is true or false.
                </p>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
