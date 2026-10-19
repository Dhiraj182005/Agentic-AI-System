import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../services/api'
import {
  ACTIVITY_RANGE_OPTIONS,
  countLabel,
  dimensionLabel,
  getAgentPerformance,
  getArgumentQuality,
  getClaimVerification,
  getDebateActivity,
  getRecentDebates,
  getSummary,
  percent,
  statusLabel,
  verdictLabel,
  type ActivityBucket,
  type AgentPerformanceStats,
  type ArgumentQualityStats,
  type ClaimVerificationStats,
  type DashboardSummary,
  type DebateActivity,
  type NamedCount,
  type RecentDebates,
} from '../services/analytics'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

function KpiCard({
  label,
  value,
  hint,
  testId,
}: {
  label: string
  value: string | number
  hint?: string
  testId: string
}) {
  return (
    <div
      className="rounded-2xl border border-gray-800 bg-gray-900 p-4"
      data-testid={testId}
    >
      <p className="text-xs uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-2xl font-bold text-gray-100">{value}</p>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  )
}

function CountBar({
  label,
  count,
  max,
  testId,
}: {
  label: string
  count: number
  max: number
  testId?: string
}) {
  const width = max > 0 ? Math.round((count / max) * 100) : 0
  return (
    <div className="flex items-center gap-3" data-testid={testId}>
      <span className="w-28 shrink-0 text-sm text-gray-300 sm:w-40">
        {label}
      </span>
      <div className="h-3 min-w-0 flex-1 rounded bg-gray-800" aria-hidden="true">
        <div
          className="h-3 rounded bg-indigo-500"
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-12 shrink-0 text-right text-sm font-medium text-gray-200 sm:w-16">
        {count}
      </span>
    </div>
  )
}

function ActivityChart({ buckets }: { buckets: ActivityBucket[] }) {
  const max = Math.max(1, ...buckets.map((bucket) => bucket.count))
  const width = 700
  const height = 160
  const padding = 28
  const barSlot = (width - padding * 2) / Math.max(buckets.length, 1)
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Bar chart of debates created per day"
      className="h-40 w-full"
      data-testid="activity-chart"
    >
      <title>Debates created per day</title>
      <line
        x1={padding}
        y1={height - padding}
        x2={width - padding}
        y2={height - padding}
        stroke="#374151"
      />
      {buckets.map((bucket, index) => {
        const barHeight =
          (bucket.count / max) * (height - padding * 2)
        return (
          <g key={bucket.date}>
            <rect
              x={padding + index * barSlot + 1}
              y={height - padding - barHeight}
              width={Math.max(barSlot - 2, 1)}
              height={Math.max(barHeight, bucket.count > 0 ? 2 : 0)}
              fill="#6366f1"
            >
              <title>{`${bucket.date}: ${bucket.count} debate(s)`}</title>
            </rect>
          </g>
        )
      })}
      <text x={padding} y={height - 8} fill="#9ca3af" fontSize="11">
        {buckets[0]?.date ?? ''}
      </text>
      <text
        x={width - padding}
        y={height - 8}
        fill="#9ca3af"
        fontSize="11"
        textAnchor="end"
      >
        {buckets[buckets.length - 1]?.date ?? ''}
      </text>
      <text x={padding - 6} y={padding - 8} fill="#9ca3af" fontSize="11" textAnchor="start">
        max {max}
      </text>
    </svg>
  )
}

function SectionError({ message }: { message: string }) {
  return <ErrorBanner message={message} />
}

export default function Dashboard() {
  const { user } = useAuth()

  const [loading, setLoading] = useState(true)
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [activity, setActivity] = useState<DebateActivity | null>(null)
  const [verification, setVerification] =
    useState<ClaimVerificationStats | null>(null)
  const [agentStats, setAgentStats] = useState<AgentPerformanceStats | null>(null)
  const [quality, setQuality] = useState<ArgumentQualityStats | null>(null)
  const [recent, setRecent] = useState<RecentDebates | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [rangeDays, setRangeDays] = useState<number>(30)
  const [page, setPage] = useState(1)

  const loadActivity = useCallback(async (days: number) => {
    try {
      const data = await getDebateActivity(days)
      setActivity(data)
      setErrors((prev) => ({ ...prev, activity: '' }))
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        activity: apiErrorMessage(err, 'Debate activity could not be loaded.'),
      }))
    }
  }, [])

  const loadRecent = useCallback(async (currentPage: number) => {
    try {
      const data = await getRecentDebates(currentPage, 10)
      setRecent(data)
      setErrors((prev) => ({ ...prev, recent: '' }))
    } catch (err) {
      setErrors((prev) => ({
        ...prev,
        recent: apiErrorMessage(err, 'Recent debates could not be loaded.'),
      }))
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      const results = await Promise.allSettled([
        getSummary(),
        getClaimVerification(),
        getAgentPerformance(),
        getArgumentQuality(),
      ])
      if (cancelled) return
      const [summaryRes, verificationRes, agentsRes, qualityRes] = results
      const nextErrors: Record<string, string> = {}
      if (summaryRes.status === 'fulfilled') setSummary(summaryRes.value)
      else
        nextErrors.summary = apiErrorMessage(
          summaryRes.reason,
          'Summary metrics could not be loaded.',
        )
      if (verificationRes.status === 'fulfilled')
        setVerification(verificationRes.value)
      else
        nextErrors.verification = apiErrorMessage(
          verificationRes.reason,
          'Claim verification statistics could not be loaded.',
        )
      if (agentsRes.status === 'fulfilled') setAgentStats(agentsRes.value)
      else
        nextErrors.agents = apiErrorMessage(
          agentsRes.reason,
          'Agent performance could not be loaded.',
        )
      if (qualityRes.status === 'fulfilled') setQuality(qualityRes.value)
      else
        nextErrors.quality = apiErrorMessage(
          qualityRes.reason,
          'Argument quality statistics could not be loaded.',
        )
      setErrors(nextErrors)
      setLoading(false)
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    void loadActivity(rangeDays)
  }, [rangeDays, loadActivity])

  useEffect(() => {
    void loadRecent(page)
  }, [page, loadRecent])

  const emptyAccount = summary !== null && summary.total_debates === 0
  const maxStatusCount = Math.max(
    1,
    ...(summary?.status_distribution ?? []).map((item) => item.count),
  )
  const maxVerdictCount = Math.max(
    1,
    ...(verification?.verdict_counts ?? []).map((item) => item.count),
  )
  const maxFallacyCount = Math.max(
    1,
    ...(quality?.fallacy_type_counts ?? []).map((item) => item.count),
  )

  return (
    <div className="min-h-screen" data-testid="dashboard">
      <PageShell maxWidth="md">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="page-title">Dashboard</h1>
            <p className="text-sm text-gray-400">
              Analytics computed from your stored debates, claims, analyses and
              judgments. Welcome, {user?.email}.
            </p>
          </div>
          <Link to="/debates" className="btn-secondary">
            My Debates
          </Link>
        </div>

        {loading && (
          <div
            className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-6"
            data-testid="dashboard-loading"
            aria-busy="true"
          >
            <LoadingState
              label="Loading dashboard…"
              className="text-sm text-gray-300"
            />
          </div>
        )}

        {!loading && errors.summary && (
          <div data-testid="dashboard-error">
            <SectionError message={errors.summary} />
          </div>
        )}

        {!loading && emptyAccount && !errors.summary && (
          <p
            className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-6 text-sm text-gray-400"
            data-testid="dashboard-empty"
          >
            You have no debates yet. Create a debate to see analytics here.
          </p>
        )}

        {!loading && summary && (
          <>
            {/* A. Key performance indicators */}
            <section
              className="mb-8 grid grid-cols-2 gap-3 md:grid-cols-4"
              data-testid="kpi-section"
              aria-label="Key performance indicators"
            >
              <KpiCard
                label="Total debates"
                value={summary.total_debates}
                testId="kpi-total-debates"
                hint={
                  summary.completion_rate !== null
                    ? `Completion rate ${Math.round(summary.completion_rate * 100)}%`
                    : 'Completion rate unavailable'
                }
              />
              <KpiCard
                label="Completed"
                value={summary.completed_debates}
                testId="kpi-completed-debates"
              />
              <KpiCard
                label="Running"
                value={summary.running_debates}
                testId="kpi-running-debates"
              />
              <KpiCard
                label="Failed"
                value={summary.failed_debates}
                testId="kpi-failed-debates"
              />
              <KpiCard
                label="Total messages"
                value={summary.total_messages}
                testId="kpi-messages"
              />
              <KpiCard
                label="Extracted claims"
                value={summary.total_claims}
                testId="kpi-claims"
              />
              <KpiCard
                label="Verified claims"
                value={summary.verified_claims}
                testId="kpi-verified-claims"
                hint={`${summary.unverified_claims} unverified`}
              />
              <KpiCard
                label="Debates judged"
                value={summary.debates_with_judgment}
                testId="kpi-judged-debates"
              />
            </section>

            {/* B. Debate activity */}
            <section
              className="card mb-8"
              data-testid="activity-section"
              aria-label="Debate activity"
            >
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <h2 className="section-title">Debate activity</h2>
                <label className="flex items-center gap-2 text-sm text-gray-400">
                  Time range
                  <select
                    value={rangeDays}
                    onChange={(event) => setRangeDays(Number(event.target.value))}
                    className="rounded-lg border border-gray-700 bg-gray-800 px-2 py-1 text-sm text-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950"
                    data-testid="activity-range-select"
                  >
                    {ACTIVITY_RANGE_OPTIONS.map((days) => (
                      <option key={days} value={days}>
                        Last {days} days
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {errors.activity && <SectionError message={errors.activity} />}
              {!errors.activity && activity && (
                <>
                  <p className="mb-2 text-xs text-gray-400">
                    Debates created per day (UTC), {activity.start_date} to{' '}
                    {activity.end_date}. Total in range:{' '}
                    {activity.total_debates_in_range}.
                  </p>
                  <ActivityChart buckets={activity.buckets} />
                  {activity.total_debates_in_range === 0 ? (
                    <p
                      className="mt-2 text-sm text-gray-400"
                      data-testid="activity-empty"
                    >
                      No debates were created in this period.
                    </p>
                  ) : (
                    <ul
                      className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-400"
                      data-testid="activity-nonzero-list"
                    >
                      {activity.buckets
                        .filter((bucket) => bucket.count > 0)
                        .map((bucket) => (
                          <li key={bucket.date}>
                            {bucket.date}: {bucket.count}
                          </li>
                        ))}
                    </ul>
                  )}
                </>
              )}
            </section>

            {/* C. Debate status distribution */}
            <section
              className="card mb-8"
              data-testid="status-section"
              aria-label="Debate status distribution"
            >
              <h2 className="section-title mb-3">
                Debate status distribution
              </h2>
              {summary.status_distribution.map((item) => (
                <div key={item.status} className="mb-2">
                  <CountBar
                    label={statusLabel(item.status)}
                    count={item.count}
                    max={maxStatusCount}
                    testId={`status-row-${item.status}`}
                  />
                </div>
              ))}
              <p className="mt-2 text-xs text-gray-400">
                Statuses come from the stored debate lifecycle: pending,
                running, completed, failed, cancelled. Total:{' '}
                {summary.total_debates}.
              </p>
            </section>

            {/* D. Claim verification analytics */}
            <section
              className="card mb-8"
              data-testid="verification-section"
              aria-label="Claim verification analytics"
            >
              <h2 className="section-title mb-3">
                Claim verification analytics
              </h2>
              {errors.verification && (
                <SectionError message={errors.verification} />
              )}
              {verification && (
                <>
                  <p className="mb-3 text-sm text-gray-300">
                    {verification.total_verifications} claim(s) with stored
                    verification results; {verification.unverified_claims}{' '}
                    claim(s) not yet verified.
                  </p>
                  <p
                    className="mb-3 text-xs text-amber-300"
                    data-testid="unverified-note"
                  >
                    Unverified claims are not counted as insufficient evidence.
                  </p>
                  {verification.verdict_counts.map((item) => (
                    <div
                      key={item.name}
                      className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1"
                    >
                      <div className="min-w-0 flex-1">
                        <CountBar
                          label={verdictLabel(item.name)}
                          count={item.count}
                          max={maxVerdictCount}
                          testId={`verdict-row-${item.name}`}
                        />
                      </div>
                      <span className="w-full text-left text-xs text-gray-400 sm:w-32 sm:shrink-0 sm:text-right">
                        {percent(item.count, verification.total_verifications)}{' '}
                        of verified
                      </span>
                    </div>
                  ))}
                  <h3 className="mb-2 mt-4 text-sm font-semibold text-gray-200">
                    Confidence levels
                  </h3>
                  {verification.confidence_counts.map((item) => (
                    <CountBar
                      key={item.name}
                      label={countLabel(item.name)}
                      count={item.count}
                      max={Math.max(
                        1,
                        ...verification.confidence_counts.map((c) => c.count),
                      )}
                      testId={`confidence-row-${item.name}`}
                    />
                  ))}
                  <p
                    className="mt-3 text-xs text-gray-400"
                    data-testid="verification-scope"
                  >
                    {verification.scope}
                  </p>
                </>
              )}
            </section>

            {/* E. Agent performance comparison */}
            <section
              className="card mb-8"
              data-testid="agent-performance-section"
              aria-label="Agent performance comparison"
            >
              <h2 className="section-title mb-1">
                Agent performance (judge scores)
              </h2>
              <p className="mb-3 text-xs text-gray-400">
                Averages use stored Module 11 judgment scores (the same rubric,
                no second formula). Agents without judged appearances show as
                unavailable, never as zero.
              </p>
              {errors.agents && <SectionError message={errors.agents} />}
              {agentStats && !agentStats.available && (
                <p
                  className="text-sm text-gray-400"
                  data-testid="agent-performance-empty"
                >
                  No debate judgments have been generated yet, so agent
                  performance is unavailable. Judge a completed debate to populate
                  this section.
                </p>
              )}
              {agentStats?.available && (
                <>
                  <p className="mb-3 text-xs text-gray-400">
                    Based on {agentStats.judgments_analyzed} stored judgment(s).
                  </p>
                  <div className="grid gap-4 md:grid-cols-2">
                    {agentStats.agents.map((agent) => (
                      <div
                        key={agent.agent_id}
                        className="rounded-xl border border-gray-800 bg-gray-800/50 p-4"
                        data-testid="agent-card"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div>
                            <p
                              className="text-sm font-semibold text-gray-100"
                              data-testid="agent-card-name"
                            >
                              {agent.agent_name}
                            </p>
                            <p className="text-xs text-gray-400">
                              {agent.agent_role}
                            </p>
                          </div>
                          <div className="text-right">
                            <p
                              className="text-lg font-bold text-indigo-300"
                              data-testid="agent-average"
                            >
                              {agent.average_score !== null
                                ? `${agent.average_score}/10`
                                : 'Unavailable'}
                            </p>
                            <p className="text-xs text-gray-400">
                              {agent.appearances} judged appearance
                              {agent.appearances === 1 ? '' : 's'}
                            </p>
                          </div>
                        </div>
                        <dl className="mt-3 space-y-1">
                          {agent.dimension_averages.map((dim) => (
                            <div
                              key={dim.dimension}
                              className="flex items-center justify-between text-xs"
                              data-testid="agent-dimension-row"
                            >
                              <dt className="text-gray-400">
                                {dimensionLabel(dim.dimension)}
                              </dt>
                              <dd
                                className={
                                  dim.average === null
                                    ? 'text-gray-400 italic'
                                    : 'font-medium text-gray-200'
                                }
                              >
                                {dim.average === null
                                  ? 'Unavailable'
                                  : `${dim.average}/10`}
                              </dd>
                            </div>
                          ))}
                        </dl>
                        {agent.strengths.length > 0 && (
                          <ul className="mt-3 list-disc space-y-0.5 pl-4 text-xs text-emerald-300">
                            {agent.strengths.map((item, index) => (
                              <li key={index}>{item}</li>
                            ))}
                          </ul>
                        )}
                        {agent.weaknesses.length > 0 && (
                          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-amber-300">
                            {agent.weaknesses.map((item, index) => (
                              <li key={index}>{item}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </section>

            {/* F. Argument quality and fallacy analytics */}
            <section
              className="card mb-8"
              data-testid="argument-quality-section"
              aria-label="Argument quality and fallacy analytics"
            >
              <h2 className="section-title mb-1">
                Argument quality and fallacies
              </h2>
              <p className="mb-3 text-xs text-gray-400">
                Stored Module 10 results only. A detected fallacy concerns an
                argument's reasoning; it never means a claim is false.
              </p>
              {errors.quality && <SectionError message={errors.quality} />}
              {quality && !quality.available && (
                <p
                  className="text-sm text-gray-400"
                  data-testid="argument-quality-empty"
                >
                  No fallacy analyses or argument evaluations are stored for
                  your debates yet.
                </p>
              )}
              {quality?.available && (
                <>
                  {quality.fallacy_available ? (
                    <>
                      <p className="mb-2 text-sm text-gray-300">
                        {quality.fallacy_total} fallacy detection(s) across{' '}
                        {quality.fallacy_analyzed_message_count} message(s).
                      </p>
                      {quality.fallacy_type_counts.map((item: NamedCount) => (
                        <div key={item.name} className="mb-2">
                          <CountBar
                            label={countLabel(item.name)}
                            count={item.count}
                            max={maxFallacyCount}
                            testId={`fallacy-type-row-${item.name}`}
                          />
                        </div>
                      ))}
                      <h3 className="mb-2 mt-3 text-sm font-semibold text-gray-200">
                        Severity distribution
                      </h3>
                      {quality.severity_counts.map((item) => (
                        <CountBar
                          key={item.name}
                          label={countLabel(item.name)}
                          count={item.count}
                          max={Math.max(
                            1,
                            ...quality.severity_counts.map((s) => s.count),
                          )}
                          testId={`severity-row-${item.name}`}
                        />
                      ))}
                    </>
                  ) : (
                    <p className="mb-3 text-sm text-gray-400">
                      No stored fallacy analyses yet.
                    </p>
                  )}

                  {quality.evaluation_available && (
                    <>
                      <h3 className="mb-2 mt-4 text-sm font-semibold text-gray-200">
                        Argument evaluation averages
                      </h3>
                      <p className="mb-2 text-xs text-gray-400">
                        {quality.evaluation_total} evaluation(s) over{' '}
                        {quality.evaluated_message_count} message(s)
                        {quality.unevaluated_message_count !== null
                          ? `; ${quality.unevaluated_message_count} message(s) not yet analyzed.`
                          : '.'}
                      </p>
                      {quality.dimension_averages.map((dim) => (
                        <div
                          key={dim.dimension}
                          className="mb-1 flex items-center justify-between text-xs"
                          data-testid="evaluation-dimension-row"
                        >
                          <span className="text-gray-400">
                            {dimensionLabel(dim.dimension)}
                          </span>
                          <span
                            className={
                              dim.average === null
                                ? 'text-gray-400 italic'
                                : 'font-medium text-gray-200'
                            }
                          >
                            {dim.average === null
                              ? 'Unavailable'
                              : `${dim.average}/10`}
                          </span>
                        </div>
                      ))}
                    </>
                  )}

                  <ul
                    className="mt-4 list-disc space-y-1 pl-4 text-xs text-gray-400"
                    data-testid="quality-notes"
                  >
                    {quality.notes.map((note, index) => (
                      <li key={index}>{note}</li>
                    ))}
                  </ul>
                </>
              )}
            </section>

            {/* G. Recent debates */}
            <section
              className="card mb-8"
              data-testid="recent-debates"
              aria-label="Recent debates"
            >
              <h2 className="section-title mb-3">Recent debates</h2>
              {errors.recent && <SectionError message={errors.recent} />}
              {recent && recent.debates.length === 0 && (
                <p className="text-sm text-gray-400" data-testid="recent-empty">
                  No debates yet.
                </p>
              )}
              {recent && recent.debates.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-400">
                        <th scope="col" className="py-2 pr-4">Topic</th>
                        <th scope="col" className="py-2 pr-4">Created</th>
                        <th scope="col" className="py-2 pr-4">Status</th>
                        <th scope="col" className="py-2 pr-4">Agents</th>
                        <th scope="col" className="py-2 pr-4">Rounds</th>
                        <th scope="col" className="py-2 pr-4">Messages</th>
                        <th scope="col" className="py-2 pr-4">Verified</th>
                        <th scope="col" className="py-2 pr-4">Judged</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recent.debates.map((item) => (
                        <tr
                          key={item.id}
                          className="border-b border-gray-800/60"
                          data-testid="recent-debate-row"
                        >
                          <td className="py-2 pr-4">
                            <Link
                              to={`/debates/${item.id}`}
                              className="font-medium text-indigo-300 hover:text-indigo-200"
                            >
                              {item.topic}
                            </Link>
                            {item.has_judgment && (
                              <Link
                                to={`/debates/${item.id}`}
                                className="ml-2 text-xs text-emerald-300 hover:text-emerald-200"
                                data-testid="results-link"
                              >
                                View results
                              </Link>
                            )}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {new Date(item.created_at).toLocaleDateString()}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {statusLabel(item.status)}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {item.agent_count}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {item.round_count}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {item.message_count}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {item.has_verification ? 'Yes' : 'No'}
                          </td>
                          <td className="py-2 pr-4 text-gray-300">
                            {item.has_judgment ? 'Yes' : 'No'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {recent && recent.debates.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setPage((prev) => Math.max(prev - 1, 1))}
                    disabled={recent.page <= 1}
                    data-testid="pagination-prev"
                    className="btn-secondary px-3 py-1.5"
                  >
                    Previous
                  </button>
                  <span
                    className="text-sm text-gray-400"
                    data-testid="pagination-label"
                  >
                    Page {recent.page} of {recent.total_pages} ({recent.total}{' '}
                    debate(s))
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      setPage((prev) => Math.min(prev + 1, recent.total_pages))
                    }
                    disabled={recent.page >= recent.total_pages}
                    data-testid="pagination-next"
                    className="btn-secondary px-3 py-1.5"
                  >
                    Next
                  </button>
                </div>
              )}
            </section>

            {/* H. Results detail lives on the existing debate detail page. */}
            <p className="text-xs text-gray-400">
              Debate results (judge summary, winner or tie, rubric breakdown
              and limitations) open from each debate's detail page via
              &quot;View results&quot;. Verdict distributions above are stored
              evidence-check outcomes — they are not independently measured
              factual accuracy.
            </p>
          </>
        )}
      </PageShell>
    </div>
  )
}
