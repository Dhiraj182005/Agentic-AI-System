import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError, apiErrorMessage } from '../services/api'
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
import {
  DIMENSION_KEYS,
  DIMENSION_LABELS,
  dimensionDisplay,
  generateJudgment,
  getJudgment,
  overallDisplay,
  outcomeLabel,
  type Judgment,
} from '../services/judge'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

const BADGE_BASE =
  'rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide'

function verdictBadgeClass(verdict: string): string {
  if (verdict === 'supported')
    return `${BADGE_BASE} border-emerald-700 bg-emerald-950/70 text-emerald-300`
  if (verdict === 'contradicted')
    return `${BADGE_BASE} border-red-700 bg-red-950/70 text-red-300`
  return `${BADGE_BASE} border-slate-600 bg-slate-800 text-slate-300`
}

function fallacyBadgeClass(fallacyType: string): string {
  if (fallacyType === 'no_fallacy')
    return `${BADGE_BASE} border-emerald-700 bg-emerald-950/70 text-emerald-300`
  return `${BADGE_BASE} border-amber-700 bg-amber-950/70 text-amber-300`
}

function severityBadgeClass(severity: string): string {
  if (severity === 'high')
    return `${BADGE_BASE} border-red-700 bg-red-950/70 text-red-300`
  if (severity === 'medium')
    return `${BADGE_BASE} border-amber-700 bg-amber-950/70 text-amber-300`
  return `${BADGE_BASE} border-slate-600 bg-slate-800 text-slate-300`
}

function judgeOutcomeBadgeClass(outcome: string): string {
  if (outcome === 'winner')
    return `${BADGE_BASE} border-emerald-700 bg-emerald-950/70 text-emerald-300`
  if (outcome === 'tie')
    return `${BADGE_BASE} border-sky-700 bg-sky-950/70 text-sky-300`
  return `${BADGE_BASE} border-amber-700 bg-amber-950/70 text-amber-300`
}

function roundStatusLabel(status: string): string {
  switch (status) {
    case 'pending':
      return 'Waiting to start'
    case 'running':
      return 'Running'
    case 'completed':
      return 'Completed'
    default:
      return status
  }
}

// Only http(s) links are opened; anything else renders as plain text so a
// malformed source URL can never run script in the page.
function safeExternalUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null
}

function mergeMessages(
  fetched: TranscriptMessage[],
  current: TranscriptMessage[],
): TranscriptMessage[] {
  const byId = new Map<string, TranscriptMessage>()
  for (const message of fetched) byId.set(message.id, message)
  for (const message of current) {
    if (!byId.has(message.id)) byId.set(message.id, message)
  }
  return [...byId.values()].sort(
    (a, b) =>
      a.round_number - b.round_number ||
      a.turn_number - b.turn_number ||
      a.created_at.localeCompare(b.created_at),
  )
}

function mergeRounds(
  fetched: DebateRound[],
  current: DebateRound[],
): DebateRound[] {
  const byNumber = new Map<number, DebateRound>()
  for (const round of fetched) byNumber.set(round.round_number, round)
  for (const round of current) {
    if (!byNumber.has(round.round_number)) byNumber.set(round.round_number, round)
  }
  return [...byNumber.values()].sort(
    (a, b) => a.round_number - b.round_number,
  )
}

export default function DebateDetail() {
  const { debateId } = useParams<{ debateId: string }>()
  const { user } = useAuth()

  const [debate, setDebate] = useState<Debate | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [errorTitle, setErrorTitle] = useState<string | null>(null)
  const [transcriptNotice, setTranscriptNotice] = useState<string | null>(null)
  const [storedNotice, setStoredNotice] = useState<string | null>(null)
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

  const [judgment, setJudgment] = useState<Judgment | null>(null)
  const [judging, setJudging] = useState(false)
  const [judgeError, setJudgeError] = useState<string | null>(null)
  const [judgmentNotice, setJudgmentNotice] = useState<string | null>(null)

  const wsClientRef = useRef<DebateWebSocketClient | null>(null)
  const wsDebateIdRef = useRef<string | null>(null)
  const execLoadSeqRef = useRef(0)

  // Re-read rounds + transcript over HTTP and MERGE them into the current
  // state: a live WebSocket message that arrived while the request was in
  // flight is kept (a blind replace would erase it), and a sequence guard
  // drops responses that belong to a superseded load.
  const loadExecutionState = useCallback(async (id: string) => {
    const seq = ++execLoadSeqRef.current
    try {
      const [roundsResponse, transcriptResponse] = await Promise.all([
        getRounds(id),
        getTranscript(id),
      ])
      if (seq !== execLoadSeqRef.current) return
      setRounds((prev) => mergeRounds(roundsResponse.rounds, prev))
      setMessages((prev) => mergeMessages(transcriptResponse.messages, prev))
      setTranscriptNotice(null)
    } catch {
      if (seq !== execLoadSeqRef.current) return
      // Surface the failure instead of silently pretending the transcript is
      // empty; existing content stays on screen.
      setTranscriptNotice(
        'The transcript could not be refreshed from the server. The data below may be out of date.',
      )
    }
  }, [])

  // Read stored evidence for the given claims (database only, no provider
  // calls). A 404 or empty response means "nothing stored" and is not an
  // error; any other failure is surfaced instead of being hidden as
  // "never analyzed".
  const loadStoredEvidence = useCallback(async (claimList: Claim[]) => {
    let failed = false
    const entries = await Promise.all(
      claimList.map(async (claim) => {
        try {
          const response = await getEvidence(claim.id)
          return [claim.id, response.evidence] as const
        } catch (err) {
          if (!(err instanceof ApiClientError && err.status === 404)) {
            failed = true
          }
          return [claim.id, undefined] as const
        }
      }),
    )
    const record: Record<string, EvidenceItem[]> = {}
    for (const [claimId, items] of entries) {
      if (items && items.length > 0) record[claimId] = items
    }
    setEvidenceByClaim((prev) => ({ ...prev, ...record }))
    if (failed) {
      setStoredNotice(
        'Some stored evidence could not be loaded, so those claims may appear unanalyzed.',
      )
    }
  }, [])

  // Read stored verification results for the given claims (database only,
  // never the LLM). A 404 means "not verified yet" (expected); anything else
  // is a real failure and is surfaced to the user.
  const loadStoredVerifications = useCallback(async (claimList: Claim[]) => {
    let failed = false
    const entries = await Promise.all(
      claimList.map(async (claim) => {
        try {
          const verification = await getVerification(claim.id)
          return [claim.id, verification] as const
        } catch (err) {
          if (!(err instanceof ApiClientError && err.status === 404)) {
            failed = true
          }
          return [claim.id, undefined] as const
        }
      }),
    )
    const record: Record<string, ClaimVerification> = {}
    for (const [claimId, verification] of entries) {
      if (verification) record[claimId] = verification
    }
    setVerificationByClaim((prev) => ({ ...prev, ...record }))
    if (failed) {
      setStoredNotice(
        'Some stored verification results could not be loaded, so those claims may appear unverified.',
      )
    }
  }, [])

  const claimsLoadSeqRef = useRef(0)

  const loadClaims = useCallback(
    async (id: string) => {
      const seq = ++claimsLoadSeqRef.current
      setClaimsLoading(true)
      try {
        const response = await getClaims(id)
        if (seq !== claimsLoadSeqRef.current) return
        setClaims(response.claims)
        setClaimsNotice(null)
        await Promise.all([
          loadStoredEvidence(response.claims),
          loadStoredVerifications(response.claims),
        ])
      } catch (err) {
        if (seq !== claimsLoadSeqRef.current) return
        setClaimsNotice(apiErrorMessage(err, 'Unable to load claims.'))
      } finally {
        if (seq === claimsLoadSeqRef.current) setClaimsLoading(false)
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
  // never the LLM) so results survive a page refresh. Failures are surfaced:
  // an unreachable backend must not look like "nothing was analyzed".
  const analysisLoadSeqRef = useRef(0)

  const loadAnalysis = useCallback(async (id: string) => {
    const seq = ++analysisLoadSeqRef.current
    let failed = false
    const [fallacies, evaluations] = await Promise.all([
      getDebateFallacies(id).catch((err: unknown) => {
        if (!(err instanceof ApiClientError && err.status === 404)) failed = true
        return null
      }),
      getDebateEvaluations(id).catch((err: unknown) => {
        if (!(err instanceof ApiClientError && err.status === 404)) failed = true
        return null
      }),
    ])
    if (seq !== analysisLoadSeqRef.current) return
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
    if (failed) {
      setStoredNotice(
        'Stored fallacy and evaluation results could not be loaded, so messages may appear unanalyzed.',
      )
    }
  }, [])

  useEffect(() => {
    if (!debateId || !debate || debate.status === 'pending') return
    let cancelled = false
    const run = async () => {
      try {
        await loadAnalysis(debateId)
      } catch {
        if (!cancelled) {
          setStoredNotice(
            'Stored argument analysis could not be loaded, so messages may appear unanalyzed.',
          )
        }
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [debateId, debate?.status, loadAnalysis])

  // Read the stored judgment for finished debates (database only, never the
  // LLM). 404 means "not judged yet" and is an expected state.
  useEffect(() => {
    if (!debateId || !debate || debate.status !== 'completed') return
    let cancelled = false
    const load = async () => {
      try {
        const stored = await getJudgment(debateId)
        if (!cancelled) {
          setJudgment(stored)
          setJudgmentNotice(null)
        }
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiClientError && err.status === 404) {
          setJudgmentNotice(
            'This debate has not been judged yet. Select Judge debate to create a judgment.',
          )
        } else {
          setJudgmentNotice('The stored judgment could not be loaded.')
        }
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [debateId, debate?.status])

  const handleJudge = async () => {
    if (!debateId || judging) return
    setJudging(true)
    setJudgeError(null)
    try {
      const result = await generateJudgment(debateId)
      setJudgment(result)
      setJudgmentNotice(null)
    } catch (err) {
      setJudgeError(
        apiErrorMessage(err, 'Judging failed. Please try again later.'),
      )
    } finally {
      setJudging(false)
    }
  }

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
        setTranscriptNotice(
          'The finished debate could not be refreshed from the server. The live view is kept as-is.',
        )
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
      setErrorTitle('Debate not available')
      setLoading(false)
      return
    }
    // A different debate id in the same mounted component must not keep the
    // previous debate's messages, claims or analysis on screen.
    execLoadSeqRef.current += 1
    claimsLoadSeqRef.current += 1
    analysisLoadSeqRef.current += 1
    setDebate(null)
    setRounds([])
    setMessages([])
    setClaims([])
    setEvidenceByClaim({})
    setVerificationByClaim({})
    setFallacyByMessage({})
    setEvaluationByMessage({})
    setJudgment(null)
    setJudgmentNotice(null)
    setError(null)
    setErrorTitle(null)
    setTranscriptNotice(null)
    setStoredNotice(null)
    setLiveNotice(null)
    setLoading(true)
    // Always fetch the current state from the backend on load, so a refresh
    // while a debate is running shows the real status.
    let cancelled = false
    getDebate(debateId)
      .then(async (loaded) => {
        if (cancelled) return
        setDebate(loaded)
        if (loaded.status !== 'pending') {
          await loadExecutionState(loaded.id)
        }
      })
      .catch((err) => {
        if (cancelled) return
        setError(apiErrorMessage(err, 'Unable to load this debate.'))
        setErrorTitle('Debate not available')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debateId, loadExecutionState])

  async function handleStart() {
    if (!debate || starting) return
    setStarting(true)
    setError(null)
    setErrorTitle(null)
    setTranscriptNotice(null)
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
      setError(apiErrorMessage(err, 'The debate could not be started.'))
      setErrorTitle('Debate could not be started')
      try {
        const refreshed = await getDebate(debate.id)
        setDebate(refreshed)
        await loadExecutionState(refreshed.id)
      } catch {
        setTranscriptNotice(
          'The debate state could not be reloaded after the failed start.',
        )
      }
    } finally {
      setStarting(false)
    }
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
      setClaimsNotice(apiErrorMessage(err, 'Claim extraction failed.'))
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
        [claimId]: apiErrorMessage(err, 'Evidence retrieval failed.'),
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
        [claimId]: apiErrorMessage(err, 'Claim verification failed.'),
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

  // Rounds are rendered from the server's round list, plus any round number
  // that only appears in the transcript: dropping those would hide messages.
  const serverRoundNumbers = new Set(rounds.map((round) => round.round_number))
  const messageOnlyRounds = [
    ...new Set(
      messages
        .map((message) => message.round_number)
        .filter((number) => !serverRoundNumbers.has(number)),
    ),
  ].sort((a, b) => a - b)
  const displayRounds: DebateRound[] = [
    ...rounds,
    ...messageOnlyRounds.map(
      (roundNumber): DebateRound => ({
        round_number: roundNumber,
        status: 'pending',
        started_at: null,
        completed_at: null,
      }),
    ),
  ].sort((a, b) => a.round_number - b.round_number)

  const canStart = debate?.status === 'pending' && !starting

  return (
    <PageShell>
      <h1 className="page-title mb-2">Debate Details</h1>
      <p className="mb-6 text-sm text-gray-400">Signed in as {user?.email}</p>

      {loading && <LoadingState label="Loading debate..." />}

      {error && (
        <div role="alert" className="alert-error mb-6">
          <p className="text-sm font-medium text-red-200">
            {errorTitle ?? 'Something went wrong'}
          </p>
          <p className="mt-1 text-sm text-red-300/90">{error}</p>
          {!debate && (
            <Link
              to="/debates"
              className="mt-3 inline-block text-sm text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
            >
              Back to your debates
            </Link>
          )}
        </div>
      )}

      {transcriptNotice && (
        <p role="status" className="alert-info mb-4" data-testid="transcript-notice">
          {transcriptNotice}
        </p>
      )}

      {storedNotice && (
        <p role="status" className="alert-info mb-4" data-testid="stored-notice">
          {storedNotice}
        </p>
      )}

        {!loading && debate && (
          <>
            <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6">
              <div className="flex items-start justify-between gap-4">
                <h2 className="text-xl font-semibold">{debate.topic}</h2>
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
                    className="btn-primary px-5 py-2.5"
                  >
                    {starting ? 'Starting debate...' : 'Start debate'}
                  </button>
                  <p className="mt-2 text-xs text-gray-400">
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
                  aria-live="polite"
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
              <h3 className="card-title mb-4">
                Participating agents ({debate.agents.length})
              </h3>
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
                <h3 className="card-title mb-4">Rounds</h3>
                {rounds.length === 0 ? (
                  <p className="text-sm text-gray-400">
                    No round has been recorded yet.
                  </p>
                ) : (
                  <ul className="space-y-3">
                    {rounds.map((round) => (
                      <li
                        key={round.round_number}
                        className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3 text-sm"
                      >
                        <span className="font-semibold">
                          Round {round.round_number}
                        </span>
                        <span className="text-gray-400">
                          {roundStatusLabel(round.status)}
                        </span>
                        <span className="text-gray-400">
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
                <h3 className="card-title mb-4">Transcript</h3>
                <div className="space-y-6" aria-live="polite">
                  {displayRounds.map((round) => {
                    const roundMessages = messagesForRound(round.round_number)
                    if (roundMessages.length === 0) return null
                    return (
                      <section key={round.round_number}>
                        <h4 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-400">
                          Round {round.round_number}
                        </h4>
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
                                  <span className="text-xs uppercase text-gray-400">
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
                                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-500 disabled:cursor-not-allowed disabled:opacity-50 ${
                                      analyzing
                                        ? 'bg-purple-900/50 text-purple-300/60'
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
                                    className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:cursor-not-allowed disabled:opacity-50 ${
                                      evaluating
                                        ? 'bg-teal-900/50 text-teal-300/60'
                                        : 'bg-teal-700 hover:bg-teal-600'
                                    }`}
                                  >
                                    {evaluating
                                      ? 'Evaluating argument...'
                                      : 'Evaluate Argument'}
                                  </button>
                                </div>

                                {!fallacy && !fallacyError && !analyzing && (
                                  <p
                                    className="mt-2 text-xs text-gray-400"
                                    data-testid="fallacy-not-analyzed"
                                  >
                                    Fallacy analysis: not analyzed yet.
                                  </p>
                                )}
                                {!evaluation && !evaluationError && !evaluating && (
                                  <p
                                    className="mt-2 text-xs text-gray-400"
                                    data-testid="evaluation-not-analyzed"
                                  >
                                    Argument quality: not analyzed yet.
                                  </p>
                                )}

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
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
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
                                    <p className="mt-2 text-xs text-gray-400">
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
                                    <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
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
                                      className="mt-2 text-xs text-gray-400"
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
                  <h3 className="card-title">Claims</h3>
                  <button
                    onClick={handleExtractClaims}
                    disabled={extracting}
                    data-testid="extract-claims"
                    className="btn-primary px-4 py-2 text-sm"
                  >
                    {extracting ? 'Extracting claims...' : 'Extract Claims'}
                  </button>
                </div>

                {claimsNotice && (
                  <div className="mb-4" data-testid="claims-error">
                    <ErrorBanner title="Claims could not be loaded" message={claimsNotice} />
                  </div>
                )}

                {claimsLoading && (
                  <p className="text-sm text-gray-400">Loading claims...</p>
                )}

                {!claimsLoading && claims.length === 0 && !claimsNotice && (
                  <p className="text-sm text-gray-400" data-testid="claims-empty">
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
                              className="btn-secondary px-3 py-1.5 text-xs"
                            >
                              {retrieving
                                ? 'Retrieving sources...'
                                : 'Retrieve Evidence'}
                            </button>
                            <button
                              onClick={() => handleVerifyClaim(claim.id)}
                              disabled={verifyLoading}
                              data-testid="verify-claim"
                              className="btn-primary px-3 py-1.5 text-xs"
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
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
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
                              <p className="mt-2 text-xs text-gray-400">
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
                                className="mt-3 text-xs text-gray-400"
                                data-testid="evidence-empty"
                              >
                                No sources found for this claim.
                              </p>
                            )}

                          {evidenceState && evidenceState.length > 0 && (
                            <div className="mt-3" data-testid="evidence-list">
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                                Retrieved sources
                              </p>
                              <ul className="mt-2 space-y-2">
                                {evidenceState.map((item) => (
                                  <li
                                    key={item.id}
                                    data-testid="evidence-item"
                                    className="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-2"
                                  >
                                    {safeExternalUrl(item.url) ? (
                                      <a
                                        href={safeExternalUrl(item.url) ?? ''}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="break-words text-sm font-medium text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                                      >
                                        {item.title}
                                      </a>
                                    ) : (
                                      <span className="break-words text-sm font-medium text-gray-200">
                                        {item.title}
                                      </span>
                                    )}
                                    <p className="mt-0.5 text-xs text-gray-400">
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

                <p className="mt-4 text-xs text-gray-400">
                  Retrieved sources are search results shown for reference only.
                  They do not indicate whether a claim is true or false.
                </p>
              </div>
            )}

            {debate.status === 'completed' && (
              <div className="card mt-6" data-testid="judge-section">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="section-title text-gray-100">
                      Debate Judge
                    </h3>
                    <p className="text-xs text-gray-400">
                      Scores every participating agent with the fixed rubric
                      (logical soundness, evidence quality, factual support,
                      relevance, effectiveness, completeness, fallacy risk) and
                      declares a winner only when the gap is decisive.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={handleJudge}
                    disabled={judging}
                    data-testid="judge-debate"
                    className="btn-primary"
                  >
                    {judging
                      ? 'Judging…'
                      : judgment
                        ? 'Re-run judgment'
                        : 'Judge debate'}
                  </button>
                </div>

                {judgeError && (
                  <div className="mt-3" data-testid="judge-error">
                    <ErrorBanner title="Judging failed" message={judgeError} />
                  </div>
                )}

                {!judgment && judgmentNotice && (
                  <p
                    className="mt-3 text-sm text-gray-400"
                    data-testid={
                      judgmentNotice.includes('not be loaded')
                        ? 'judgment-error'
                        : 'judgment-empty'
                    }
                  >
                    {judgmentNotice}
                  </p>
                )}

                {judging && (
                  <p className="mt-3 text-sm text-indigo-300" data-testid="judgment-loading">
                    The judge is scoring this debate…
                  </p>
                )}

                {judgment && (
                  <div className="mt-4 space-y-4" data-testid="judgment-section">
                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className="text-lg font-bold text-indigo-300"
                        data-testid="judgment-overall"
                      >
                        Overall {overallDisplay(judgment.overall_score)}
                      </span>
                      <span
                        className={judgeOutcomeBadgeClass(judgment.outcome)}
                        data-testid="judgment-outcome"
                      >
                        {outcomeLabel(judgment.outcome)}
                      </span>
                      {judgment.outcome === 'winner' && judgment.winner_name && (
                        <span
                          className="text-sm font-semibold text-emerald-300"
                          data-testid="judgment-winner"
                        >
                          Winner: {judgment.winner_name}
                        </span>
                      )}
                      {judgment.outcome === 'tie' && (
                        <span
                          className="text-sm font-semibold text-sky-300"
                          data-testid="judgment-tie"
                        >
                          Scores are too close to call a winner.
                        </span>
                      )}
                      {judgment.outcome === 'inconclusive' && (
                        <span
                          className="text-sm font-semibold text-amber-300"
                          data-testid="judgment-inconclusive"
                        >
                          Not enough stored debate data to produce a verdict.
                        </span>
                      )}
                    </div>

                    <p
                      className="text-sm leading-relaxed text-gray-300"
                      data-testid="judgment-summary"
                    >
                      {judgment.summary}
                    </p>

                    <div className="grid gap-4 md:grid-cols-2">
                      {judgment.agent_scores.map((card) => (
                        <div
                          key={card.agent_id}
                          className="rounded-lg border border-gray-800 bg-gray-900/60 p-4"
                          data-testid="agent-judgment"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div>
                              <p
                                className="text-sm font-semibold text-gray-100"
                                data-testid="agent-name"
                              >
                                {card.agent_name}
                              </p>
                              <p className="text-xs text-gray-400">
                                {card.agent_role}
                              </p>
                            </div>
                            <span
                              className="text-lg font-bold text-indigo-300"
                              data-testid="agent-score"
                            >
                              {overallDisplay(card.final_score)}
                            </span>
                          </div>

                          <dl
                            className="mt-3 space-y-1"
                            data-testid="agent-dimensions"
                          >
                            {DIMENSION_KEYS.map((key) => {
                              const value = card.dimensions[key]
                              const unavailable =
                                value === null || value === undefined
                              return (
                                <div
                                  key={key}
                                  className="flex items-center justify-between gap-2 text-xs"
                                  data-testid="dimension-row"
                                >
                                  <dt
                                    className={
                                      unavailable
                                        ? 'text-gray-400'
                                        : 'text-gray-400'
                                    }
                                  >
                                    {DIMENSION_LABELS[key]}
                                  </dt>
                                  <dd
                                    className={
                                      unavailable
                                        ? 'text-gray-400 italic'
                                        : 'font-medium text-gray-200'
                                    }
                                    data-testid={`dimension-${key}`}
                                  >
                                    {dimensionDisplay(value)}
                                  </dd>
                                </div>
                              )
                            })}
                          </dl>

                          {card.strengths.length > 0 && (
                            <div className="mt-3" data-testid="agent-strengths">
                              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-400">
                                Strengths
                              </p>
                              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-300">
                                {card.strengths.map((item, index) => (
                                  <li key={index}>{item}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          {card.weaknesses.length > 0 && (
                            <div className="mt-3" data-testid="agent-weaknesses">
                              <p className="text-xs font-semibold uppercase tracking-wide text-amber-400">
                                Weaknesses
                              </p>
                              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-300">
                                {card.weaknesses.map((item, index) => (
                                  <li key={index}>{item}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          <div className="mt-3 space-y-1 text-xs text-gray-400">
                            {card.reasoning_quality && (
                              <p data-testid="agent-reasoning">
                                Reasoning: {card.reasoning_quality}
                              </p>
                            )}
                            {card.evidence_quality_assessment && (
                              <p data-testid="agent-evidence">
                                Evidence use: {card.evidence_quality_assessment}
                              </p>
                            )}
                            {card.factual_support_assessment && (
                              <p data-testid="agent-factual">
                                Factual support: {card.factual_support_assessment}
                              </p>
                            )}
                            {card.fallacy_impact_assessment && (
                              <p data-testid="agent-fallacy">
                                Fallacy impact: {card.fallacy_impact_assessment}
                              </p>
                            )}
                          </div>

                          {card.limitations.length > 0 && (
                            <div className="mt-3" data-testid="agent-limitations">
                              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                                Limitations
                              </p>
                              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                                {card.limitations.map((item, index) => (
                                  <li key={index}>{item}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          <p className="mt-2 text-xs text-gray-400">
                            Judge confidence: {card.confidence}
                          </p>
                        </div>
                      ))}
                    </div>

                    {judgment.limitations && judgment.limitations.length > 0 && (
                      <div data-testid="judgment-limitations">
                        <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                          Judgment limitations
                        </p>
                        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                          {judgment.limitations.map((item, index) => (
                            <li key={index}>{item}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    <p
                      className="text-xs text-gray-400"
                      data-testid="judgment-disclaimer"
                    >
                      Scores measure argument quality against the published
                      rubric weights (logical soundness 0.20, evidence quality
                      0.20, factual support 0.15, relevance 0.15, effectiveness
                      0.10, completeness 0.10, fallacy risk 0.10 penalty). A
                      declared winner is a rubric recommendation for this
                      debate, not proof that its claims are objectively true.
                    </p>
                  </div>
                )}
              </div>
            )}
          </>
        )}
    </PageShell>
  )
}
