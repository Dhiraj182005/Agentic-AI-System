import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiClientError } from '../services/api'
import {
  debateStatusLabel,
  listDebates,
  type Debate,
} from '../services/debates'

export default function DebateList() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [debates, setDebates] = useState<Debate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listDebates()
      .then((response) => setDebates(response.items))
      .catch((err) =>
        setError(
          err instanceof ApiClientError
            ? err.detail
            : err instanceof Error
              ? err.message
              : 'Unable to load debates.',
        ),
      )
      .finally(() => setLoading(false))
  }, [])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">AI Debate Arena</h1>
        <nav className="flex items-center gap-4">
          <Link to="/" className="text-sm text-gray-400 hover:text-white">
            Home
          </Link>
          <span className="text-sm text-gray-400">Debates</span>
          <Link to="/agents" className="text-sm text-gray-400 hover:text-white">
            Agent Test
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
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-2xl font-semibold">Your Debates</h2>
          <Link
            to="/debates/new"
            className="bg-indigo-600 hover:bg-indigo-700 rounded-lg px-4 py-2 text-sm font-semibold"
          >
            New Debate
          </Link>
        </div>
        <p className="text-gray-400 mb-8">Signed in as {user?.email}</p>

        {error && (
          <div className="mb-6 rounded-lg border border-red-900/60 bg-red-950/40 px-4 py-3">
            <p className="text-sm font-medium text-red-300">Could not load debates</p>
            <p className="mt-1 text-sm text-red-300/80">{error}</p>
          </div>
        )}

        {loading && <p className="text-gray-400">Loading debates...</p>}

        {!loading && !error && debates.length === 0 && (
          <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6 text-center">
            <p className="text-gray-300">You have not created a debate yet.</p>
            <Link
              to="/debates/new"
              className="mt-4 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold hover:bg-indigo-700"
            >
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
                  className="block rounded-2xl border border-gray-800 bg-gray-900 p-6 hover:border-indigo-500"
                >
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-lg font-semibold">{debate.topic}</h3>
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
      </main>
    </div>
  )
}
