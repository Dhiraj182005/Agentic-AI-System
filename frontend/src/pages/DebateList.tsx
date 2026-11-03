import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../services/api'
import { countLabel, listDebates, type Debate } from '../services/debates'
import PageShell from '../components/ui/PageShell'
import PageHeader from '../components/ui/PageHeader'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'
import StatusBadge from '../components/ui/StatusBadge'

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'pending', label: 'Not started' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
]

export default function DebateList() {
  const [debates, setDebates] = useState<Debate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await listDebates()
      setDebates(
        [...response.items].sort(
          (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
        ),
      )
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to load debates.'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return debates.filter(
      (debate) =>
        (statusFilter === 'all' || debate.status === statusFilter) &&
        (!needle ||
          debate.topic.toLowerCase().includes(needle) ||
          debate.agents.some((agent) => agent.name.toLowerCase().includes(needle))),
    )
  }, [debates, query, statusFilter])

  return (
    <PageShell>
      <PageHeader
        title="My Debates"
        description="Every debate you have created. Open one to follow it live or review its results."
        actions={
          <Link to="/debates/new" className="btn-primary">
            New Debate
          </Link>
        }
      />

      {error && (
        <div className="mb-6">
          <ErrorBanner
            title="Could not load debates"
            message={error}
            onRetry={() => void load()}
          />
        </div>
      )}

      {loading && <LoadingState label="Loading debates..." />}

      {!loading && !error && debates.length === 0 && (
        <div className="card text-center">
          <p className="font-medium text-gray-200">You have not created a debate yet</p>
          <p className="mt-1 text-sm text-gray-400">
            Pick a topic and let MAVES assemble a panel of expert agents.
          </p>
          <Link to="/debates/new" className="btn-primary mt-5">
            Create your first debate
          </Link>
        </div>
      )}

      {!loading && debates.length > 0 && (
        <>
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="flex-1">
              <span className="sr-only">Search debates</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by topic or agent..."
                className="input"
              />
            </label>
            <label className="sm:w-48">
              <span className="sr-only">Filter by status</span>
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value)}
                className="input"
              >
                {STATUS_FILTERS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <p className="mb-3 text-xs text-gray-500" aria-live="polite">
            Showing {filtered.length} of {debates.length} debates
          </p>

          {filtered.length === 0 ? (
            <div className="card text-center text-sm text-gray-400">
              No debates match your search.
            </div>
          ) : (
            <ul className="space-y-3">
              {filtered.map((debate) => (
                <li key={debate.id}>
                  <Link
                    to={`/debates/${debate.id}`}
                    className="block rounded-xl border border-gray-800 bg-gray-900 px-5 py-4 transition-colors hover:border-gray-700 hover:bg-gray-900/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <h2 className="min-w-0 flex-1 font-medium text-white">
                        {debate.topic}
                      </h2>
                      <StatusBadge status={debate.status} short />
                    </div>
                    <p className="mt-1.5 text-xs text-gray-400">
                      {new Date(debate.created_at).toLocaleString()} ·{' '}
                      {countLabel(debate.total_rounds, 'round')} ·{' '}
                      {debate.agents.map((agent) => agent.name).join(', ')}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PageShell>
  )
}
