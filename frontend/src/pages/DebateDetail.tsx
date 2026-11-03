import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ApiClientError, apiErrorMessage } from '../services/api'
import {
  DEBATE_MODES,
  countLabel,
  getDebate,
  getRounds,
  getTranscript,
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
  type FactCheckStatus,
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
import { useReportDownload } from '../hooks/useReportDownload'
import {
  getAnalysisStatus,
  startAnalysis,
  getVerdict,
  type AnalysisStatus,
  positionLabel,
  positionTone,
  type Verdict,
} from '../services/verdict'
import { beginDebate } from '../services/execution'
import useExecution from '../hooks/useExecution'
import ExecutionDashboard from '../components/ExecutionDashboard'
import EvidenceSources from '../components/EvidenceSources'
import VerdictPanel from '../components/VerdictPanel'
import AgentArguments from '../components/AgentArguments'
import DebateTurn from '../components/DebateTurn'
import PageShell from '../components/ui/PageShell'
import PageHeader from '../components/ui/PageHeader'
import StatusBadge from '../components/ui/StatusBadge'
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

// Debates that finished running (successfully or not) can produce a report;
// the PDF itself marks anything without a stored judgment as partial.
const REPORTABLE_STATUSES = new Set(['completed', 'failed', 'cancelled'])

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
  const location = useLocation()
  const navigate = useNavigate()

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
  const { execution, refresh: refreshExecution, notify: notifyExecution, error: executionError } = useExecution(debateId, wsState)
  const navRef = useRef<HTMLElement | null>(null)
  const [, setLiveRound] = useState<number | null>(null)
  const [, setCurrentSpeaker] = useState<string | null>(null)
  const [liveNotice, setLiveNotice] = useState<string | null>(null)

  const [claims, setClaims] = useState<Claim[]>([])
  const [claimsLoading, setClaimsLoading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [claimsNotice, setClaimsNotice] = useState<string | null>(null)
  const [factCheckByClaim, setFactCheckByClaim] = useState<
    Record<string, FactCheckStatus | null | undefined>
  >({})
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

  const [analysisLoading, setAnalysisLoading] = useState(false)
  const [analysisReadFailed, setAnalysisReadFailed] = useState(false)
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

  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [verdictLoading, setVerdictLoading] = useState(false)
  const [verdictGenerating, setVerdictGenerating] = useState(false)
  const [verdictError, setVerdictError] = useState<string | null>(null)
  const [verdictNotice, setVerdictNotice] = useState<string | null>(null)
  const [analysisStarting, setAnalysisStarting] = useState(false)
  const [analysisStatus, setAnalysisStatus] = useState<AnalysisStatus | null>(null)
  const [verdictInfo, setVerdictInfo] = useState<string | null>(null)
  const autoStartRef = useRef(false)

  const {
    download: downloadReport,
    downloadingId: reportDownloadingId,
    error: reportDownloadError,
  } = useReportDownload()
  const reportDownloading = reportDownloadingId !== null
  // Errors are keyed by debate id, so navigating to another debate never
  // shows a stale failure.
  const reportError =
    reportDownloadError && reportDownloadError.id === debateId
      ? reportDownloadError.message
      : null

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
          return [claim.id, response.evidence, response.fact_check_status] as const
        } catch (err) {
          if (!(err instanceof ApiClientError && err.status === 404)) {
            failed = true
          }
          return [claim.id, undefined, undefined] as const
        }
      }),
    )
    const record: Record<string, EvidenceItem[]> = {}
    const factChecks: Record<string, FactCheckStatus | null | undefined> = {}
    for (const [claimId, items, factCheck] of entries) {
      if (items && items.length > 0) record[claimId] = items
      factChecks[claimId] = factCheck
    }
    setEvidenceByClaim((prev) => ({ ...prev, ...record }))
    setFactCheckByClaim((prev) => ({ ...prev, ...factChecks }))
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
    if (!debateId || !debate?.status || debate.status === 'pending') return
    void loadClaims(debateId)
  }, [debateId, debate?.status, loadClaims])

  // Read stored fallacy analyses and argument evaluations (database only,
  // never the LLM) so results survive a page refresh. Failures are surfaced:
  // an unreachable backend must not look like "nothing was analyzed".
  const analysisLoadSeqRef = useRef(0)

  const loadAnalysis = useCallback(async (id: string) => {
    const seq = ++analysisLoadSeqRef.current
    setAnalysisLoading(true)
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
    setAnalysisLoading(false)
    setAnalysisReadFailed(failed)
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
    if (!debateId || !debate?.status || debate.status === 'pending') return
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
    if (!debateId || debate?.status !== 'completed') return
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

  // Read the stored final verdict (database only). 404 = not generated yet.
  useEffect(() => {
    if (!debateId || debate?.status !== 'completed') return
    let cancelled = false
    setVerdictLoading(true)
    getVerdict(debateId)
      .then((stored) => {
        if (cancelled) return
        setVerdict(stored)
        setVerdictNotice(null)
      })
      .catch((err) => {
        if (cancelled) return
        setVerdict(null)
        setVerdictNotice(
          err instanceof ApiClientError && err.status === 404
            ? 'Generate the verdict to get a reasoned answer to the debate question. Factual claims are extracted and checked against web sources automatically first.'
            : 'The stored verdict could not be loaded.',
        )
      })
      .finally(() => {
        if (!cancelled) setVerdictLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debateId, debate?.status])

  const loadAnalysisStatus = useCallback(async (id: string) => {
    try {
      setAnalysisStatus(await getAnalysisStatus(id))
    } catch {
      setStoredNotice('Analysis progress and methodology could not be refreshed from the server.')
    }
  }, [])

  // Analysis status for completed debates; poll while a run is in progress
  // and reload the verdict when it finishes.
  useEffect(() => {
    if (!debateId || debate?.status !== 'completed') return
    void loadAnalysisStatus(debateId)
  }, [debateId, debate?.status, loadAnalysisStatus])

  useEffect(() => {
    if (!debateId || analysisStatus?.state !== 'running' || wsState === 'connected') return
    const timer = window.setInterval(async () => {
      try {
        const latest = await getAnalysisStatus(debateId)
        setAnalysisStatus(latest)
        await Promise.all([loadAnalysis(debateId), loadClaims(debateId)])
        if (latest.state !== 'running') {
          setVerdict(await getVerdict(debateId))
          setVerdictNotice(null)
        }
      } catch {
        /* next tick retries */
      }
    }, 5000)
    return () => window.clearInterval(timer)
  }, [debateId, analysisStatus?.state, wsState, loadAnalysis, loadClaims])

  const handleAnalyzeAll = async () => {
    if (!debateId || analysisStarting) return
    setAnalysisStarting(true)
    setStoredNotice(null)
    try {
      const job = await startAnalysis(debateId)
      setAnalysisStatus(job)
      setVerdictInfo(job.message ?? null)
      await refreshExecution()
    } catch (err) {
      setStoredNotice(apiErrorMessage(err, 'Unable to start analysis.'))
    } finally { setAnalysisStarting(false) }
  }

  const handleGenerateVerdict = async (regenerate: boolean) => {
    if (!debateId || verdictGenerating) return
    setVerdictGenerating(true)
    setVerdictError(null)
    try {
      const job = await startAnalysis(debateId, regenerate)
      setAnalysisStatus(job)
      setVerdictInfo(job.message ?? 'Analysis already in progress — showing live progress.')
      await refreshExecution()
    } catch (err) {
      setVerdictError(apiErrorMessage(err, 'The verdict workflow could not be started.'))
    } finally { setVerdictGenerating(false) }
  }

  const handleJudge = async (regenerate = false) => {
    if (!debateId || judging) return
    setJudging(true)
    setJudgeError(null)
    try {
      const result = await generateJudgment(debateId, regenerate)
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
      notifyExecution()
      if (debateId && ['claim_extraction_completed', 'evidence_retrieval_completed', 'claim_verification_completed'].includes(event.type)) void loadClaims(debateId)
      if (debateId && ['fallacy_analysis_completed', 'argument_evaluation_completed'].includes(event.type)) void loadAnalysis(debateId)
      if (debateId && event.type === 'performance_completed') getJudgment(debateId).then(setJudgment).catch(() => {})
      if (debateId && event.type === 'verdict_generated') getVerdict(debateId).then(value => { setVerdict(value); setVerdictNotice(null) }).catch(() => {})
      if (debateId && ['analysis_completed', 'analysis_failed'].includes(event.type)) {
        void loadClaims(debateId)
        void loadAnalysis(debateId)
        getJudgment(debateId).then(setJudgment).catch(() => {})
        getVerdict(debateId).then(value => { setVerdict(value); setVerdictNotice(null) }).catch(() => {})
      }
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
                structured: data.structured ?? null,
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
    [debateId, reconcileAfterFinish, notifyExecution, loadClaims, loadAnalysis],
  )

  const handleLiveEventRef = useRef(handleLiveEvent)
  handleLiveEventRef.current = handleLiveEvent

  const handleWsState = useCallback(
    (state: WebSocketState) => {
      setWsState(state)
      if (state === 'connected') {
        // Every connection recovers persisted state, including events missed
        // between loading the page and establishing the live channel.
        if (debateId) {
          void loadExecutionState(debateId)
          void refreshExecution()
          void loadAnalysisStatus(debateId)
          void loadClaims(debateId)
          void loadAnalysis(debateId)
          getVerdict(debateId).then(setVerdict).catch(() => {})
        }
      }
    },
    [debateId, loadExecutionState, refreshExecution, loadAnalysisStatus, loadClaims, loadAnalysis],
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
    if (!debateId || !debate?.status) return
    if (starting || debate.status !== 'pending') {
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
    setFactCheckByClaim({})
    setVerificationByClaim({})
    setFallacyByMessage({})
    setEvaluationByMessage({})
    setJudgment(null)
    setJudgmentNotice(null)
    setVerdict(null)
    setVerdictNotice(null)
    setVerdictError(null)
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

  async function handleStart(resume = false) {
    if (!debate || starting) return
    setStarting(true)
    setError(null)
    setErrorTitle(null)
    setTranscriptNotice(null)
    setLiveNotice(null)
    // Subscribe before submitting; the HTTP response acknowledges the claim
    // while execution continues on its independent session.
    ensureClient(debate.id).connect()
    try {
      const snapshot = await beginDebate(debate.id, resume)
      setDebate(prev => prev ? { ...prev, status: snapshot.transcript_status, execution_state: snapshot.execution_state } : prev)
      await Promise.all([refreshExecution(), loadExecutionState(debate.id)])
      window.requestAnimationFrame(() => document.getElementById('execution-progress')?.scrollIntoView({ block: 'start', behavior: 'auto' }))
    } catch (err) {
      setError(
        apiErrorMessage(
          err,
          resume ? 'The debate could not be resumed.' : 'The debate could not be started.',
        ),
      )
      setErrorTitle(resume ? 'Debate could not be resumed' : 'Debate could not be started')
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
      setFactCheckByClaim((prev) => ({ ...prev, [claimId]: response.fact_check_status }))
    } catch (err) {
      // Published fact-checks may have been stored before the web search
      // failed: show whatever is stored (best effort).
      getEvidence(claimId)
        .then((stored) => {
          if (stored.evidence.length > 0) {
            setEvidenceByClaim((prev) => ({ ...prev, [claimId]: stored.evidence }))
          }
          setFactCheckByClaim((prev) => ({ ...prev, [claimId]: stored.fact_check_status }))
        })
        .catch(() => undefined)
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
      if (debateId) { void loadAnalysisStatus(debateId); getVerdict(debateId).then(setVerdict).catch(() => {}) }
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
      if (debateId) { void loadAnalysisStatus(debateId); getVerdict(debateId).then(setVerdict).catch(() => {}) }
    } catch (err) {
      setEvaluationErrors((prev) => ({
        ...prev,
        [messageId]: apiErrorMessage(err, 'Argument evaluation failed.'),
      }))
    } finally {
      setEvaluatingArgument((prev) => ({ ...prev, [messageId]: false }))
    }
  }

  useEffect(() => {
    if (!execution) return
    setDebate(prev => prev ? { ...prev, status: execution.transcript_status, execution_state: execution.execution_state } : prev)
    setAnalysisStatus(prev => ({ ...prev, ...execution.analysis }))
  }, [execution])
  useEffect(() => {
    if (debateId && execution?.completed_turns !== undefined) void loadExecutionState(debateId)
  }, [debateId, execution?.completed_turns, loadExecutionState])

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

  // The transcript section also shows the round summary for any debate that
  // has produced rounds but no messages yet.
  const hasTranscriptSection =
    !!debate && (messages.length > 0 || debate.status !== 'pending')

  const completed = debate?.status === 'completed'
  const hasMessages = messages.length > 0
  const sectionItems: { id: string; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    ...(completed ? [{ id: 'verdict', label: 'Final Verdict' }] : []),
    ...(hasMessages ? [{ id: 'arguments', label: 'Agent Arguments' }] : []),
    ...(hasMessages
      ? [
          { id: 'claims', label: 'Claims & Verification' },
          { id: 'evidence', label: 'Evidence' },
          { id: 'fallacies', label: 'Fallacy Detection' },
          { id: 'quality', label: 'Argument Quality' },
        ]
      : []),
    ...(completed ? [{ id: 'performance', label: 'Agent Performance' }] : []),
    ...(hasTranscriptSection ? [{ id: 'transcript', label: 'Transcript' }] : []),
    ...(completed ? [{ id: 'limitations', label: 'Methodology' }] : []),
  ]
  // Older links used per-section anchors; map them onto the tabs.
  const TAB_ALIASES: Record<string, string> = {
    conclusion: 'performance',
    comparison: 'performance',
    analysis: 'fallacies',
  }
  const requestedTab = location.hash.slice(1)
  const activeTab = sectionItems.some(
    (item) => item.id === (TAB_ALIASES[requestedTab] ?? requestedTab),
  )
    ? (TAB_ALIASES[requestedTab] ?? requestedTab)
    : 'overview'
  useEffect(() => {
    const selected = navRef.current?.querySelector<HTMLElement>('[aria-selected="true"]')
    selected?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }, [activeTab])
  const selectTab = (id: string) => {
    navigate({ hash: id === 'overview' ? '' : `#${id}` }, { replace: true, state: location.state })
  }

  // Evidence groups only render for claims that are being retrieved, already
  // have stored results or carry an explicit error - exactly the states that
  // used to be drawn inside each claim card.
  const evidenceGroups = claims
    .map((claim) => ({
      claim,
      items: evidenceByClaim[claim.id],
      error: evidenceErrors[claim.id] ?? null,
      retrieving: !!evidenceLoading[claim.id],
    }))
    .filter(
      (group) =>
        group.retrieving || group.error !== null || group.items !== undefined,
    )

  const storedFallacies = Object.entries(fallacyByMessage)
    .map(([messageId, fallacy]) => ({
      message: messages.find((item) => item.id === messageId),
      fallacy,
    }))
    .filter(
      (row): row is { message: TranscriptMessage; fallacy: Fallacy } =>
        row.message !== undefined,
    )
    .sort(
      (a, b) =>
        a.message.round_number - b.message.round_number ||
        a.message.turn_number - b.message.turn_number,
    )

  const storedEvaluations = Object.entries(evaluationByMessage)
    .map(([messageId, evaluation]) => ({
      message: messages.find((item) => item.id === messageId),
      evaluation,
    }))
    .filter(
      (
        row,
      ): row is {
        message: TranscriptMessage
        evaluation: ArgumentEvaluation
      } => row.message !== undefined,
    )
    .sort(
      (a, b) =>
        a.message.round_number - b.message.round_number ||
        a.message.turn_number - b.message.turn_number,
    )

  // "Start Debate" on the New Debate page lands here with autoStart: start
  // once, then drop the flag so a refresh never starts it twice.
  useEffect(() => {
    const wantsStart = (location.state as { autoStart?: boolean } | null)?.autoStart
    if (!wantsStart || autoStartRef.current || !debate || debate.status !== 'pending') return
    autoStartRef.current = true
    navigate({ hash: location.hash }, { replace: true, state: null })
    void handleStart()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debate?.id, debate?.status, location.state])

  return (
    <PageShell>
      <PageHeader
        eyebrow={
          <Link
            to="/debates"
            className="inline-flex items-center gap-1 rounded text-sm text-gray-400 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          >
            <span aria-hidden="true">&larr;</span> My Debates
          </Link>
        }
        title={debate ? debate.topic : 'Debate'}
        description={
          debate ? (
            <span className="inline-flex flex-wrap items-center gap-2">
              <span data-testid="debate-status">
                <StatusBadge status={starting ? 'starting' : execution?.execution_state ?? debate.execution_state ?? debate.status} />
              </span>
              <span>
                {countLabel(debate.agents.length, 'agent')} ·{' '}
                {countLabel(debate.total_rounds, 'round')} ·{' '}
                {modeLabel}
              </span>
            </span>
          ) : undefined
        }
        actions={
          debate && REPORTABLE_STATUSES.has(debate.status) ? (
            <button
              type="button"
              onClick={() => debateId && void downloadReport(debateId)}
              disabled={reportDownloading}
              aria-busy={reportDownloading}
              data-testid="download-report"
              className="btn-primary"
            >
              {reportDownloading
                ? 'Preparing PDF...'
                : debate.status === 'completed'
                  ? 'Download PDF Report'
                  : 'Download Partial Report'}
            </button>
          ) : debate && (debate.status === 'pending' || debate.status === 'running') ? (
            <span className="flex flex-col items-end gap-1">
              <button type="button" disabled className="btn-secondary" aria-describedby="report-hint">
                Download PDF Report
              </button>
              <span id="report-hint" className="text-[11px] text-gray-500">
                Available once the debate finishes
              </span>
            </span>
          ) : undefined
        }
      />

      {reportError && (
        <div className="mb-6" data-testid="report-error">
          <ErrorBanner
            title="Report download failed"
            message={reportError}
            onRetry={() => debateId && void downloadReport(debateId)}
          />
        </div>
      )}

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
            <nav
              ref={navRef}
              aria-label="Debate sections"
              role="tablist"
              data-testid="section-nav"
              className="debate-tabs sticky top-16 z-20 -mx-1 mb-6 flex gap-1 overflow-x-auto rounded-xl border border-gray-800 bg-gray-900/95 p-1.5 backdrop-blur lg:top-4"
            >
              {sectionItems.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === item.id}
                  aria-controls={item.id}
                  tabIndex={activeTab === item.id ? 0 : -1}
                  onKeyDown={event => {
                    const index = sectionItems.findIndex(tab => tab.id === item.id)
                    const next = event.key === 'ArrowRight' ? (index + 1) % sectionItems.length : event.key === 'ArrowLeft' ? (index - 1 + sectionItems.length) % sectionItems.length : event.key === 'Home' ? 0 : event.key === 'End' ? sectionItems.length - 1 : null
                    if (next === null) return
                    event.preventDefault()
                    selectTab(sectionItems[next].id)
                    navRef.current?.querySelector<HTMLButtonElement>(`[data-testid="nav-${sectionItems[next].id}"]`)?.focus()
                  }}
                  onClick={() => selectTab(item.id)}
                  data-testid={`nav-${item.id}`}
                  className={`shrink-0 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    activeTab === item.id
                      ? 'bg-indigo-600 font-medium text-white'
                      : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </nav>

            <section
              id="overview"
              role="tabpanel"
              hidden={activeTab !== 'overview'}
              data-testid="section-overview"
              className="card scroll-mt-32"
            >
              <h2 className="section-title text-gray-100">Overview</h2>

              {completed && (
                <button
                  type="button"
                  onClick={() => selectTab('verdict')}
                  className={`mt-4 block w-full rounded-xl border p-4 text-left transition-colors hover:brightness-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    verdict ? positionTone(verdict.position) : 'border-dashed border-gray-700 text-gray-300'
                  }`}
                  data-testid="verdict-glance"
                >
                  <span className="text-xs font-semibold uppercase tracking-wider">
                    Final verdict{verdict ? ` · ${positionLabel(verdict.position)}` : ''}
                  </span>
                  <span className="mt-1 block text-base font-medium text-white">
                    {verdict
                      ? verdict.answer
                      : verdictLoading
                        ? 'Loading the stored verdict...'
                        : 'Not generated yet - open the Final Verdict tab to generate it.'}
                  </span>
                </button>
              )}

              {execution && !(starting && execution.execution_state === 'created') && <ExecutionDashboard execution={execution} connection={wsState} onRound={number => {
                selectTab('transcript')
                window.requestAnimationFrame(() => {
                  const round = document.getElementById(`transcript-round-${number}`)
                  round?.scrollIntoView?.({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
                  round?.focus()
                })
              }} />}
              {executionError && <p role="status" className="my-3 text-sm text-amber-300">{executionError}</p>}
              {liveNotice && <p role="status" className="my-2 text-xs text-amber-300">{liveNotice}</p>}
              <dl className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Selection mode</dt>
                  <dd className="capitalize">{debate.expert_selection_mode}</dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Debate mode</dt>
                  <dd>{modeLabel}</dd>
                </div>
                <div className="flex justify-between gap-3 rounded-lg bg-gray-800 px-4 py-3">
                  <dt className="text-gray-400">Rounds completed</dt>
                  <dd data-testid="rounds-completed">
                    {rounds.filter((r) => r.status === 'completed').length} of{' '}
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
                    onClick={() => void handleStart()}
                    disabled={!canStart}
                    data-testid="start-debate"
                    className="btn-primary px-5 py-2.5"
                  >
                    {starting ? 'Starting debate...' : 'Start debate'}
                  </button>
                  <p className="mt-2 text-xs text-gray-400">
                    Start the debate to begin live execution. Saved progress is restored after refresh.
                  </p>
                </div>
              )}

              {debate.status === 'failed' && (
                <div
                  className="mt-6 rounded-xl border border-red-900/60 bg-red-950/40 px-4 py-4"
                  data-testid="failure-panel"
                >
                  <p className="text-sm font-semibold text-red-200">
                    This debate did not finish
                  </p>
                  <p className="mt-1 text-sm text-red-300" data-testid="failure-reason">
                    {debate.failure_reason ??
                      'The debate failed while it was running.'}
                  </p>
                  <p className="mt-2 text-xs text-red-300/80">
                    {rounds.filter((r) => r.status === 'completed').length} of{' '}
                    {debate.total_rounds} rounds completed
                    {rounds.find((r) => r.status === 'failed')
                      ? `; round ${rounds.find((r) => r.status === 'failed')!.round_number} was interrupted`
                      : ''}
                    . {messages.length} stored{' '}
                    {messages.length === 1 ? 'message is' : 'messages are'} kept in the
                    Transcript tab. A failed debate has no final verdict.
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={() => void handleStart(true)}
                      disabled={starting}
                      aria-busy={starting}
                      className="btn-primary"
                      data-testid="resume-debate"
                    >
                      {starting ? 'Resuming debate...' : 'Resume from failed turn'}
                    </button>
                    <span className="text-xs text-gray-400">
                      Completed rounds and stored messages are kept; only the
                      missing turns are generated.
                    </span>
                  </div>
                </div>
              )}

              <h3 className="card-title mb-4 mt-6">
                Participating agents ({debate.agents.length})
              </h3>
              <ul className="grid gap-3 sm:grid-cols-2">
                {debate.agents.map((agent) => (
                  <li
                    key={agent.id}
                    className="rounded-lg border border-gray-800 bg-gray-800/60 px-4 py-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold">{agent.name}</p>
                      {agent.source === 'dynamic' && (
                        <span className="rounded-full border border-violet-500/40 bg-violet-500/10 px-2 py-0.5 text-[11px] font-medium text-violet-300">
                          AI specialist role
                        </span>
                      )}
                      {agent.source !== 'dynamic' && agent.role.replace(/_/g, ' ').toLowerCase() !==
                        agent.name.toLowerCase() && (
                        <span className="rounded-full bg-gray-700/70 px-2 py-0.5 text-[11px] font-medium capitalize text-gray-300">
                          {agent.role.replace(/_/g, ' ')}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-gray-400">{agent.description}</p>
                  </li>
                ))}
              </ul>
            </section>

            {completed && (
              <section
                id="verdict"
                role="tabpanel"
                hidden={activeTab !== 'verdict'}
                className="card scroll-mt-32"
                data-testid="section-verdict"
              >
                <h2 className="section-title mb-3 text-gray-100">Final Debate Verdict</h2>
                <VerdictPanel
                  status={debate.status}
                  verdict={verdict}
                  loading={verdictLoading}
                  generating={verdictGenerating}
                  error={verdictError}
                  notice={verdictNotice}
                  onGenerate={(regenerate) => void handleGenerateVerdict(regenerate)}
                  onNavigate={selectTab}
                  onDownload={() => debateId && void downloadReport(debateId)}
                  downloading={reportDownloading}
                  analysis={analysisStatus}
                  info={verdictInfo}
                />
              </section>
            )}

            {hasMessages && (
              <section
                id="arguments"
                role="tabpanel"
                hidden={activeTab !== 'arguments'}
                className="card scroll-mt-32"
                data-testid="section-arguments"
              >
                <h2 className="section-title mb-3 text-gray-100">Agent Arguments</h2>
                <AgentArguments agents={debate.agents} messages={messages} />
              </section>
            )}

            {debate.status === 'completed' && (
              <section
                id="conclusion"
                role="tabpanel"
                hidden={activeTab !== 'performance'}
                className="card scroll-mt-32"
                data-testid="judge-section"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="section-title text-gray-100">
                      Agent Performance
                    </h2>
                    <p className="mt-1 text-xs text-amber-300/90">
                      Ranks how well each agent argued. This is not the
                      debate&apos;s answer - see Final Verdict.
                    </p>
                    <p className="text-xs text-gray-400">
                      Scores every agent on its own turns with a fixed rubric
                      (logical soundness, evidence quality, factual support,
                      responsiveness, relevance, clarity, completeness, fallacy
                      risk) and names a best performer only when the gap is
                      decisive.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleJudge(judgment !== null)}
                    disabled={judging}
                    data-testid="judge-debate"
                    className={judgment ? 'btn-secondary' : 'btn-primary'}
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
                    <ErrorBanner
                      title="Judging failed - no scores were stored"
                      message={judgeError}
                      onRetry={() => void handleJudge(judgment !== null)}
                    />
                  </div>
                )}

                {judgment?.stale && (
                  <p
                    role="status"
                    className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200"
                    data-testid="judgment-stale"
                  >
                    New claims, verifications or analyses were stored after
                    these scores. Select Re-run judgment to include them.
                  </p>
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
                          No ranking: see the limitations below. This
                          concerns agent comparison only, not the debate&apos;s
                          answer.
                        </span>
                      )}
                    </div>

                    <p
                      className="text-sm leading-relaxed text-gray-300"
                      data-testid="judgment-summary"
                    >
                      {judgment.summary}
                    </p>

                    {judgment.agent_scores.length > 0 && (
                      <ul className="space-y-2.5" data-testid="score-bars">
                        {[...judgment.agent_scores]
                          .sort((a, b) => b.final_score - a.final_score)
                          .map((card, index) => (
                            <li key={card.agent_id} className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-3 text-sm">
                              <span className="truncate text-gray-200">{card.agent_name}</span>
                              <span className="h-2.5 overflow-hidden rounded-full bg-gray-800">
                                <span
                                  className={`block h-full rounded-full ${
                                    ['bg-indigo-500', 'bg-emerald-500', 'bg-violet-500', 'bg-rose-500', 'bg-sky-500', 'bg-amber-500'][index % 6]
                                  }`}
                                  style={{ width: `${Math.max(0, Math.min(100, card.final_score * 10))}%` }}
                                />
                              </span>
                              <span className="text-right tabular-nums text-gray-300">
                                {overallDisplay(card.final_score)}
                              </span>
                            </li>
                          ))}
                      </ul>
                    )}
                  </div>
                )}
              </section>
            )}

            {debate.status === 'completed' && judgment && (
              <section
                id="comparison"
                role="tabpanel"
                hidden={activeTab !== 'performance'}
                className="card scroll-mt-32"
                data-testid="section-comparison"
              >
                <h2 className="section-title mb-1 text-gray-100">
                  Agent Comparison
                </h2>
                <p className="mb-4 text-xs text-gray-400">
                  Per-agent rubric scores and qualitative assessments from the
                  stored judgment.
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
              </section>
            )}

            {messages.length > 0 && (
              <section
                id="claims"
                role="tabpanel"
                hidden={activeTab !== 'claims'}
                className="card scroll-mt-32"
                data-testid="claims-section"
              >
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 className="section-title text-gray-100">
                      Claims and Verification
                    </h2>
                    <p className="text-xs text-gray-400">
                      Extracted claims with their stored verification results.
                      Verify a claim to score the retrieved sources against it.
                    </p>
                  </div>
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
                      const retrieving = !!evidenceLoading[claim.id]
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
                              disabled={verifyLoading || claim.claim_type !== 'factual'}
                              data-testid="verify-claim"
                              className="btn-primary px-3 py-1.5 text-xs"
                            >
                              {verifyLoading
                                ? 'Evaluating evidence...'
                                : 'Verify Claim'}
                            </button>
                          </div>

                          {(evidenceByClaim[claim.id] || factCheckByClaim[claim.id]) && (
                            <details className="mt-3 text-xs text-gray-400">
                              <summary>Evidence and published fact-checks</summary>
                              <EvidenceSources items={evidenceByClaim[claim.id] ?? []}
                                factCheckStatus={factCheckByClaim[claim.id]} verification={verification} />
                            </details>
                          )}

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
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            )}

            {messages.length > 0 && (
              <section
                id="evidence"
                role="tabpanel"
                hidden={activeTab !== 'evidence'}
                className="card scroll-mt-32"
                data-testid="section-evidence"
              >
                <h2 className="section-title mb-1 text-gray-100">
                  Evidence Sources
                </h2>
                <p className="mb-4 text-xs text-gray-400">
                  Published fact-checks (Google Fact Check) and web search
                  results (Tavily) retrieved for the claims in this debate.
                  Open a source to check a claim yourself.
                </p>

                {evidenceGroups.length === 0 && !claimsLoading && (
                  <p
                    className="text-sm text-gray-400"
                    data-testid="evidence-none"
                  >
                    No evidence retrieved yet. Select &quot;Retrieve
                    Evidence&quot; on a claim in the section above to fetch
                    sources for it.
                  </p>
                )}

                {evidenceGroups.length > 0 && (
                  <div className="space-y-4">
                    {evidenceGroups.map(
                      ({ claim, items, error, retrieving }) => (
                        <div
                          key={claim.id}
                          className="rounded-lg border border-gray-800 bg-gray-900/60 px-4 py-3"
                          data-testid="evidence-group"
                        >
                          <p className="text-sm font-semibold text-indigo-300">
                            <span className="text-gray-400">Claim: </span>
                            &quot;{claim.text}&quot;
                          </p>

                          {retrieving && (
                            <p
                              className="mt-2 text-xs text-gray-400"
                              data-testid="evidence-loading"
                            >
                              Retrieving sources...
                            </p>
                          )}

                          {error && (
                            <div
                              className="mt-3 rounded-lg border border-amber-900/60 bg-amber-950/40 px-3 py-2"
                              data-testid="evidence-error"
                            >
                              <p className="text-xs text-amber-200">{error}</p>
                            </div>
                          )}

                          {!retrieving && items !== undefined && (
                            <EvidenceSources
                              items={items}
                              factCheckStatus={factCheckByClaim[claim.id]}
                              verification={verificationByClaim[claim.id]}
                            />
                          )}
                        </div>
                      ),
                    )}
                  </div>
                )}

                <p className="mt-4 text-xs text-gray-400">
                  Retrieved sources are search results shown for reference
                  only. They do not indicate whether a claim is true or false.
                </p>
              </section>
            )}

            {messages.length > 0 && (
              <section
                id="fallacies"
                role="tabpanel"
                hidden={activeTab !== 'fallacies'}
                className="card scroll-mt-32"
                data-testid="section-analysis"
              >
                <h2 className="section-title mb-1 text-gray-100">
                  Fallacy Detection
                </h2>
                <div className="my-4 space-y-2" aria-live="polite">
                  <button className="btn-primary px-4 py-2 text-sm" onClick={handleAnalyzeAll}
                    disabled={debate.status !== 'completed' || analysisStarting || analysisStatus?.state === 'running'}>
                    {analysisStarting || analysisStatus?.state === 'running' ? 'Analysis in progress...' : 'Analyze all arguments / retry failed'}
                  </button>
                  <p className="text-xs text-gray-400">Runs missing fallacy checks, quality evaluations and evidence verification; preserves successful results.</p>
                  {analysisStatus?.fallacy && <p className="text-xs text-gray-400">Fallacy: {analysisStatus.fallacy.completed}/{analysisStatus.fallacy.total} completed, {analysisStatus.fallacy.failed} failed</p>}
                  {analysisStatus?.evaluation && <p className="text-xs text-gray-400">Quality: {analysisStatus.evaluation.completed}/{analysisStatus.evaluation.total} completed, {analysisStatus.evaluation.failed} failed</p>}
                  {storedNotice && <ErrorBanner title="Analysis unavailable" message={storedNotice} />}
                </div>
                <p className="mb-4 text-xs text-gray-400">
                  Persisted checks for every participant. Clean results are stored too.
                  Individual checks remain available in Transcript.
                </p>
                {storedFallacies.length === 0 ? (
                  <p className="text-sm text-gray-400" data-testid="analysis-empty">
                    {analysisLoading ? 'Loading saved fallacy analyses...' : analysisReadFailed ? 'Stored fallacy results are unavailable.' : 'No fallacy analysis stored yet.'}
                  </p>
                ) : (
                  <div className="space-y-4">
                    {storedFallacies.map(({ message, fallacy }) => (
                      <div
                        key={`fallacy-${message.id}`}
                        className="rounded-lg border border-gray-700 bg-gray-900/60 px-4 py-3"
                        data-testid="analysis-fallacy-item"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-indigo-300">
                            {message.agent.name}
                          </p>
                          <span className="text-xs uppercase text-gray-400">
                            Round {message.round_number} -{' '}
                            {message.message_type}
                          </span>
                        </div>
                        <details className="mt-2 text-xs text-gray-400"><summary>Original argument</summary><p className="mt-2 whitespace-pre-wrap">{message.content}</p></details>
                        {fallacy.fallacy_type === 'no_fallacy' ? (
                          <p
                            className="mt-2 text-sm text-emerald-300"
                            data-testid="analysis-fallacy-none"
                          >
                            No clear fallacy detected.
                          </p>
                        ) : (
                          <>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              <span
                                data-testid="analysis-fallacy-type"
                                className={fallacyBadgeClass(
                                  fallacy.fallacy_type,
                                )}
                              >
                                {fallacyLabel(fallacy.fallacy_type)}
                              </span>
                              <span
                                data-testid="analysis-fallacy-severity"
                                className={severityBadgeClass(fallacy.severity)}
                              >
                                Severity: {severityLabel(fallacy.severity)}
                              </span>
                              <span
                                data-testid="analysis-fallacy-confidence"
                                className="rounded-full border border-gray-700 px-2.5 py-1 text-xs text-gray-400"
                              >
                                Confidence:{' '}
                                {confidencePercent(fallacy.confidence)}
                              </span>
                            </div>
                            <p
                              className="mt-2 text-sm text-gray-200"
                              data-testid="analysis-fallacy-explanation"
                            >
                              {fallacy.explanation}
                            </p>
                            {fallacy.evidence_span && (
                              <p
                                className="mt-1 text-xs text-gray-400"
                                data-testid="analysis-fallacy-span"
                              >
                                &quot;{fallacy.evidence_span}&quot;
                              </p>
                            )}
                          </>
                        )}
                      </div>
                    ))}

                  </div>
                )}
                <p className="mt-4 text-xs text-gray-400" data-testid="analysis-disclaimer">
                  A fallacy marks a flaw in an argument&apos;s reasoning only -
                  it does not decide whether a claim is true.
                </p>
              </section>
            )}

            {messages.length > 0 && (
              <section
                id="quality"
                role="tabpanel"
                hidden={activeTab !== 'quality'}
                className="card scroll-mt-32"
                data-testid="section-quality"
              >
                <h2 className="section-title mb-1 text-gray-100">
                  Argument Quality
                </h2>
                <div className="my-4 space-y-2" aria-live="polite">
                  <button className="btn-primary px-4 py-2 text-sm" onClick={handleAnalyzeAll}
                    disabled={debate.status !== 'completed' || analysisStarting || analysisStatus?.state === 'running'}>
                    {analysisStarting || analysisStatus?.state === 'running' ? 'Analysis in progress...' : 'Evaluate all arguments / retry failed'}
                  </button>
                  <p className="text-xs text-gray-400">Runs missing fallacy checks, quality evaluations and evidence verification; preserves successful results.</p>
                  {analysisStatus?.fallacy && <p className="text-xs text-gray-400">Fallacy: {analysisStatus.fallacy.completed}/{analysisStatus.fallacy.total} completed, {analysisStatus.fallacy.failed} failed</p>}
                  {analysisStatus?.evaluation && <p className="text-xs text-gray-400">Quality: {analysisStatus.evaluation.completed}/{analysisStatus.evaluation.total} completed, {analysisStatus.evaluation.failed} failed</p>}
                  {storedNotice && <ErrorBanner title="Analysis unavailable" message={storedNotice} />}
                </div>
                <p className="mb-4 text-xs text-gray-400">
                  Per-message quality uses the published v2 rubric. Missing dimensions
                  remain unavailable and remaining weights are renormalized.
                </p>
                {analysisStatus?.coverage && <div className="mb-4 grid gap-2 sm:grid-cols-2">
                  {analysisStatus.coverage.agent_comparisons.map((agent) => <div key={agent.agent_id} className="rounded border border-gray-700 p-3 text-sm">
                    {agent.agent_name}: {agent.average_score == null ? 'Not evaluated' : `${scoreDisplay(agent.average_score)}/10 average`} ({agent.evaluations}/{agent.messages} messages)
                  </div>)}
                </div>}
                {storedEvaluations.length === 0 ? (
                  <p className="text-sm text-gray-400" data-testid="quality-empty">
                    {analysisLoading ? 'Loading saved quality evaluations...' : analysisReadFailed ? 'Stored quality results are unavailable.' : 'No argument quality evaluations stored yet.'}
                  </p>
                ) : (
                  <div className="space-y-4">
                    {storedEvaluations.map(({ message, evaluation }) => (
                      <div
                        key={`evaluation-${message.id}`}
                        className="rounded-lg border border-gray-700 bg-gray-900/60 px-4 py-3"
                        data-testid="analysis-evaluation-item"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-semibold text-indigo-300">
                            {message.agent.name}
                          </p>
                          <span className="text-xs uppercase text-gray-400">
                            Round {message.round_number} -{' '}
                            {message.message_type}
                          </span>
                        </div>
                        <p
                          className="mt-2 text-sm font-semibold text-teal-300"
                          data-testid="analysis-evaluation-overall"
                        >
                          Overall: {scoreDisplay(evaluation.overall_score)}/10
                        </p>
                        <p className="mt-1 text-xs text-gray-400">Rubric: {evaluation.rubric_version ?? 'legacy (unversioned)'}</p>
                        {evaluation.criterion_scores && <div className="mt-2 grid grid-cols-2 gap-1 text-xs text-gray-400">
                          {Object.entries(evaluation.criterion_scores).map(([key, value]) => <p key={key}>{key.replace(/_/g, ' ')}: {value == null ? 'Unavailable' : `${scoreDisplay(value)}/10`}</p>)}
                        </div>}
                        {!!evaluation.strengths?.length && <p className="mt-2 text-xs text-emerald-300">Strengths: {evaluation.strengths.join('; ')}</p>}
                        {!!evaluation.weaknesses?.length && <p className="mt-2 text-xs text-amber-300">Weaknesses: {evaluation.weaknesses.join('; ')}</p>}
                        <p className="mt-1 text-xs text-gray-400">{new Date(evaluation.evaluated_at ?? evaluation.created_at).toLocaleString()}</p>
                        <p
                          className="mt-2 text-sm text-gray-200"
                          data-testid="analysis-evaluation-explanation"
                        >
                          {evaluation.explanation}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
                <p className="mt-4 text-xs text-gray-400">
                  Quality scores measure reasoning and presentation, not truth.
                </p>
              </section>
            )}

            {hasTranscriptSection && (
              <section
                id="transcript"
                role="tabpanel"
                hidden={activeTab !== 'transcript'}
                data-testid="section-transcript"
                className="card scroll-mt-32"
              >
                <h2 className="section-title mb-4 text-gray-100">Transcript</h2>
                {debate.status !== 'pending' && (
                  <div className="mb-6">
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
                  <div>
                    <div className="space-y-6" aria-live="polite">
                  {displayRounds.map((round) => {
                    const roundMessages = messagesForRound(round.round_number)
                    if (roundMessages.length === 0) return null
                    return (
                      <section key={round.round_number} id={`transcript-round-${round.round_number}`} tabIndex={-1}>
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
                                id={`msg-${message.id}`}
                                tabIndex={-1}
                                className="scroll-mt-32 rounded-xl border border-gray-800 bg-gray-900/70 px-4 py-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                              >
                                <DebateTurn
                                  message={message}
                                  agentRole={(() => {
                                    const known = debate.agents.find((a) => a.id === message.agent.id)
                                    return known?.source === 'dynamic' ? 'AI specialist role' : known?.role
                                  })()}
                                />

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
                                      : fallacy ? 'Re-analyze Argument' : 'Analyze Argument'}
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
                                      : evaluation ? 'Re-evaluate Argument' : 'Evaluate Argument'}
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
                                    <details className="mt-2 text-xs text-gray-400"><summary>Original argument</summary><p className="mt-2 whitespace-pre-wrap">{message.content}</p></details>
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
              </section>
            )}

            {debate.status === 'completed' && (
              <section
                id="limitations"
                role="tabpanel"
                hidden={activeTab !== 'limitations'}
                className="card scroll-mt-32"
                data-testid="section-limitations"
              >
                <h2 className="section-title mb-4 text-gray-100">
                  Limitations and Methodology
                </h2>
                <div className="mb-6 grid gap-4 md:grid-cols-2">
                  <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
                    <h3 className="text-sm font-semibold text-gray-200">Final verdict</h3>
                    <p className="mt-1 text-xs leading-relaxed text-gray-400">
                      Answers the debate question. The language model sees the
                      question, the transcript and the stored claim
                      verifications - never the agent scores. MAVES keeps only
                      citations that match stored claims, returns an
                      inconclusive verdict when no claim is supported or
                      contradicted by evidence, and caps confidence by how much
                      of the debate the evidence covers.
                    </p>
                  </div>
                  <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-4">
                    <h3 className="text-sm font-semibold text-gray-200">Agent performance</h3>
                    <p className="mt-1 text-xs leading-relaxed text-gray-400">
                      Ranks how well each agent argued using a fixed rubric. A
                      best-performing agent is not evidence that its position
                      is correct, so the ranking never decides the verdict.
                    </p>
                  </div>
                </div>
                {analysisStatus?.coverage && (
                  <div className="mb-5 space-y-3" data-testid="analysis-coverage">
                    <p className="text-sm text-gray-300">Current persisted coverage (historical judgment limitations below describe when it was generated).</p>
                    <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
                      {Object.entries(analysisStatus.coverage).filter(([, value]) => typeof value === 'number' || typeof value === 'string').map(([key, value]) => (
                        <div key={key} className="rounded border border-gray-800 p-2 text-xs text-gray-300">
                          {key.replace(/_/g, ' ')}: {String(value).replace(/_/g, ' ')}
                        </div>
                      ))}
                    </div>
                    <p className="text-xs text-gray-400">Rubric v{analysisStatus.coverage.rubric.version}: {analysisStatus.coverage.rubric.formula}</p>
                    <p className="text-xs text-gray-400">The previous UI showed v1 weights. Current v2 includes responsiveness (0.15), evidence quality (0.15), relevance (0.10) and completeness (0.05).</p>
                  </div>
                )}
                {judgment ? (
                  <>
                    {judgment.limitations &&
                      judgment.limitations.length > 0 && (
                        <div data-testid="judgment-limitations">
                          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                            Judgment limitations
                          </p>
                          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-gray-400">
                            {[...new Set(judgment.limitations)].map((item, index) => (
                              <li key={index}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                    <p
                      className="mt-4 text-xs text-gray-400"
                      data-testid="judgment-disclaimer"
                    >
                      Scores measure argument quality against the published
                      versioned rubric displayed above. Historical judgments retain
                      their original rubric snapshot. A
                      declared winner is a rubric recommendation for this
                      debate, not proof that its claims are objectively true.
                    </p>
                  </>
                ) : (
                  <p className="text-sm text-gray-400">
                    This debate has not been judged yet, so no judgment summary
                    is stored. Judge the debate to store a scored conclusion;
                    scores are always computed with the fixed rubric and remain
                    a rubric recommendation, not proof of objective truth.
                  </p>
                )}
              </section>
            )}
          </>
        )}
    </PageShell>
  )
}
