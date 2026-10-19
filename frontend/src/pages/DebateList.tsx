import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../services/api'
import {
  debateStatusLabel,
  listDebates,
  type Debate,
} from '../services/debates'
import PageShell from '../components/ui/PageShell'
import ErrorBanner from '../components/ui/ErrorBanner'
import LoadingState from '../components/ui/LoadingState'

export default function DebateList() {
  const { user } = useAuth()
  const [debates, setDebates] = useState<Debate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listDebates()
      .then((response) => {
        if (!cancelled) setDebates(response.items)
      })
      .catch((err) => {
        if (!cancelled) setError(apiErrorMessage(err, 'Unable to load debates.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <PageShell>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Your Debates</h1>
          <p className="mt-1 text-sm text-gray-400">Signed in as {user?.email}</p>
        </div>
        <Link to="/debates/new" className="btn-primary">
          New Debate
        </Link>
      </div>

      {error && (
        <div className="mb-6">
          <ErrorBanner title="Could not load debates" message={error} />
        </div>
      )}

      {loading && <LoadingState label="Loading debates..." />}

      {!loading && !error && debates.length === 0 && (
        <div className="card text-center">
          <p className="text-gray-300">You have not created a debate yet.</p>
          <Link to="/debates/new" className="btn-primary mt-4">
            Create your first debate
          </Link>
        </div>
      )}

      {!loading && debates.length > 0 && (
        <ul className="space-y-4">
          {debates.map((debate) => (
            <li key={debate.id}>
              <Link
                to={`/debates/${debate.id}`}
                className="block rounded-2xl border border-gray-800 bg-gray-900 p-6 transition-colors hover:border-indigo-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <h2 className="card-title">{debate.topic}</h2>
                  <span className="shrink-0 rounded-full border border-gray-700 px-3 py-1 text-xs text-gray-300">
                    {debateStatusLabel(debate.status)}
                  </span>
                </div>
                <p className="mt-2 text-sm text-gray-400">
                  {new Date(debate.created_at).toLocaleString()} ·{' '}
                  {debate.total_rounds} rounds ·{' '}
                  {debate.agents.map((agent) => agent.name).join(', ')}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  )
}
