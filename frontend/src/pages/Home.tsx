import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/ui/PageShell'

export default function Home() {
  const { user } = useAuth()

  return (
    <PageShell>
      <div className="mb-8">
        <h1 className="page-title">
          Welcome{user?.email ? `, ${user.email}` : ''}
        </h1>
        <p className="mt-2 text-gray-400">
          Create a debate, choose the participating agents, run it live, review
          claims and evidence, analyze argument quality, generate an overall
          judgment and track your results in the dashboard.
        </p>
      </div>

      <div className="mb-8 flex flex-wrap gap-3">
        <Link to="/debates/new" className="btn-primary">
          New Debate
        </Link>
        <Link to="/debates" className="btn-secondary">
          My Debates
        </Link>
        <Link to="/dashboard" className="btn-secondary">
          Dashboard
        </Link>
        <Link to="/agents" className="btn-secondary">
          Agents
        </Link>
      </div>

      <section className="card" aria-labelledby="account-heading">
        <h2 id="account-heading" className="card-title mb-4">
          Account
        </h2>
        <div className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
          <span className="text-gray-300">Authentication Status</span>
          <span className="flex items-center text-emerald-400">
            <span
              aria-hidden="true"
              className="inline-block w-3 h-3 rounded-full mr-2 bg-emerald-500"
            />
            Authenticated
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 bg-gray-800 rounded-lg px-4 py-3 mt-3">
          <span className="text-gray-300">Email</span>
          <span className="break-all text-right">{user?.email}</span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 bg-gray-800 rounded-lg px-4 py-3 mt-3">
          <span className="text-gray-300">User ID</span>
          <span className="font-mono text-sm text-gray-400 break-all text-right">
            {user?.id}
          </span>
        </div>
      </section>
    </PageShell>
  )
}
