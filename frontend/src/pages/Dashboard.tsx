import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../services/api'
import {
  getRecentDebates,
  getSummary,
  type DashboardSummary,
  type RecentDebateItem,
} from '../services/analytics'
import { countLabel } from '../services/debates'
import { positionLabel, positionTone } from '../services/verdict'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'
import StatusBadge from '../components/ui/StatusBadge'

const RECENT_LIMIT = 6

const STAT_ICONS = {
  total: 'M4 6h16M4 12h16M4 18h10',
  completed: 'M5 13l4 4L19 7',
  progress: 'M12 6v6l4 2M12 3a9 9 0 110 18 9 9 0 010-18z',
  verdict: 'M12 3v18M5 7h14M7 7l-3 7a3 3 0 006 0L7 7zM17 7l-3 7a3 3 0 006 0l-3-7z',
}

function StatCard({
  label,
  value,
  hint,
  icon,
  tone,
  to,
}: {
  label: string
  value: number
  hint: string
  icon: string
  tone: string
  to?: string
}) {
  const body = (
    <div className="flex items-center gap-4">
      <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${tone}`}>
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
          <path d={icon} />
        </svg>
      </span>
      <div className="min-w-0">
        <p className="text-2xl font-semibold tabular-nums text-white">{value}</p>
        <p className="text-sm text-gray-300">{label}</p>
        <p className="truncate text-xs text-gray-500">{hint}</p>
      </div>
    </div>
  )
  const className =
    'block rounded-2xl border border-gray-800 bg-gray-900 p-5 shadow-card transition-colors'
  return to ? (
    <Link
      to={to}
      className={`${className} hover:border-gray-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500`}
    >
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [recent, setRecent] = useState<RecentDebateItem[]>([])
  const [loading, setLoading] = useState(true)
  const [summaryError, setSummaryError] = useState<string | null>(null)
  const [recentError, setRecentError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    const [summaryRes, recentRes] = await Promise.allSettled([
      getSummary(),
      getRecentDebates(1, RECENT_LIMIT),
    ])
    if (summaryRes.status === 'fulfilled') {
      setSummary(summaryRes.value)
      setSummaryError(null)
    } else {
      setSummaryError(
        apiErrorMessage(summaryRes.reason, 'Summary statistics could not be loaded.'),
      )
    }
    if (recentRes.status === 'fulfilled') {
      setRecent(recentRes.value.debates)
      setRecentError(null)
    } else {
      setRecentError(
        apiErrorMessage(recentRes.reason, 'Recent debates could not be loaded.'),
      )
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const name = user?.email ? user.email.split('@')[0] : ''
  const verdicts = recent.filter((item) => item.verdict !== null)

  return (
    <PageShell maxWidth="lg">
      <section className="relative mb-8 overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 p-6 shadow-card sm:p-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-indigo-600/20 blur-3xl"
        />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <h1 className="text-2xl font-semibold text-white sm:text-3xl">
              Welcome back{name ? `, ${name}` : ''}
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-gray-300 sm:text-base">
              MAVES brings expert AI agents together to debate a question,
              checks their claims against retrieved evidence and delivers a
              reasoned final verdict you can download as a report.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link to="/debates/new" className="btn-primary px-5 py-2.5">
              Start New Debate
            </Link>
            <Link to="/reports" className="btn-secondary px-5 py-2.5">
              View Reports
            </Link>
          </div>
        </div>
      </section>

      {loading && <LoadingState label="Loading your workspace..." />}

      {!loading && (
        <>
          <section aria-labelledby="stats-heading" className="mb-8">
            <h2 id="stats-heading" className="sr-only">
              Summary
            </h2>
            {summaryError ? (
              <ErrorBanner
                title="Could not load statistics"
                message={summaryError}
                onRetry={() => void load()}
              />
            ) : (
              summary && (
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  <StatCard
                    label="Total debates"
                    value={summary.total_debates}
                    hint="All debates you have created"
                    icon={STAT_ICONS.total}
                    tone="bg-indigo-500/15 text-indigo-300"
                    to="/debates"
                  />
                  <StatCard
                    label="Completed"
                    value={summary.completed_debates}
                    hint="Every round finished"
                    icon={STAT_ICONS.completed}
                    tone="bg-emerald-500/15 text-emerald-300"
                    to="/reports"
                  />
                  <StatCard
                    label="In progress"
                    value={summary.running_debates + summary.pending_debates}
                    hint={`${summary.running_debates} running, ${summary.pending_debates} not started`}
                    icon={STAT_ICONS.progress}
                    tone="bg-amber-500/15 text-amber-300"
                  />
                  <StatCard
                    label="Final verdicts"
                    value={summary.debates_with_verdict}
                    hint="Debates with a reasoned conclusion"
                    icon={STAT_ICONS.verdict}
                    tone="bg-violet-500/15 text-violet-300"
                    to="/reports"
                  />
                </div>
              )
            )}
          </section>

          <div className="grid gap-6 xl:grid-cols-5">
            <section aria-labelledby="recent-heading" className="xl:col-span-3">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 id="recent-heading" className="section-title">
                  Recent debates
                </h2>
                {recent.length > 0 && (
                  <Link
                    to="/debates"
                    className="rounded text-sm text-indigo-300 hover:text-indigo-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    View all
                  </Link>
                )}
              </div>

              {recentError && (
                <ErrorBanner
                  title="Could not load debates"
                  message={recentError}
                  onRetry={() => void load()}
                />
              )}

              {!recentError && recent.length === 0 && (
                <div className="card text-center">
                  <p className="font-medium text-gray-200">No debates yet</p>
                  <p className="mx-auto mt-1 max-w-md text-sm text-gray-400">
                    Enter a question and MAVES picks suitable expert agents for
                    it. Results and the final verdict will show up here.
                  </p>
                  <Link to="/debates/new" className="btn-primary mt-5">
                    Create your first debate
                  </Link>
                </div>
              )}

              {recent.length > 0 && (
                <ul className="divide-y divide-gray-800 overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-card">
                  {recent.map((debate) => (
                    <li key={debate.id}>
                      <Link
                        to={`/debates/${debate.id}`}
                        className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 transition-colors hover:bg-gray-800/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-medium text-white">{debate.topic}</p>
                          <p className="mt-0.5 text-xs text-gray-400">
                            {new Date(debate.created_at).toLocaleDateString()} ·{' '}
                            {countLabel(debate.agent_count, 'agent')} ·{' '}
                            {countLabel(debate.message_count, 'message')}
                          </p>
                        </div>
                        <StatusBadge status={debate.status} short />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="verdicts-heading" className="xl:col-span-2">
              <h2 id="verdicts-heading" className="section-title mb-3">
                Recent verdicts
              </h2>
              {verdicts.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-gray-700 p-6 text-center text-sm text-gray-400">
                  No final verdicts among your recent debates yet. Open a
                  completed debate and generate its verdict.
                </div>
              ) : (
                <ul className="space-y-3">
                  {verdicts.map((debate) => (
                    <li key={debate.id}>
                      <Link
                        to={`/debates/${debate.id}#verdict`}
                        className={`block rounded-2xl border p-4 transition hover:brightness-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${positionTone(debate.verdict!.position)}`}
                      >
                        <p className="text-[11px] font-semibold uppercase tracking-wider">
                          {positionLabel(debate.verdict!.position)} ·{' '}
                          {debate.verdict!.confidence} confidence
                        </p>
                        <p className="mt-1 truncate text-sm font-medium text-white">
                          {debate.topic}
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs text-gray-300">
                          {debate.verdict!.answer}
                        </p>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </PageShell>
  )
}
