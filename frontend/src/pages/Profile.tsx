import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import PageShell from '../components/ui/PageShell'
import PageHeader from '../components/ui/PageHeader'

export default function Profile() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const rows: [string, string][] = user
    ? [
        ['Email', user.email],
        ['Account type', user.is_demo ? 'Shared demo account' : 'Personal account'],
        ['Member since', new Date(user.created_at).toLocaleDateString()],
        ['User ID', user.id],
      ]
    : []

  return (
    <PageShell maxWidth="sm">
      <PageHeader title="Profile" description="Your account details." />

      {user?.is_demo && (
        <p role="note" className="alert-info mb-6" data-testid="demo-account-note">
          You are signed in to the shared demo account. Debates created here are
          visible to anyone who uses the demo login - do not enter private
          information.
        </p>
      )}

      <section className="card" aria-labelledby="account-heading">
        <div className="mb-5 flex items-center gap-4">
          <span
            aria-hidden="true"
            className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-600 text-lg font-semibold uppercase text-white"
          >
            {user?.email.charAt(0) ?? '?'}
          </span>
          <div className="min-w-0">
            <h2 id="account-heading" className="truncate font-semibold text-white">
              {user?.email}
            </h2>
            <p className="text-sm text-gray-400">Signed in with email and password</p>
          </div>
        </div>
        <dl className="divide-y divide-gray-800 rounded-xl border border-gray-800">
          {rows.map(([label, value]) => (
            <div key={label} className="flex flex-wrap justify-between gap-2 px-4 py-3 text-sm">
              <dt className="text-gray-400">{label}</dt>
              <dd className="break-all text-right text-gray-100">{value}</dd>
            </div>
          ))}
        </dl>
        <button type="button" onClick={handleLogout} className="btn-danger mt-6">
          Sign out
        </button>
      </section>
    </PageShell>
  )
}
