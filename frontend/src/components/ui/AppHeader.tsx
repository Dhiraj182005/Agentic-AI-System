import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const NAV_ITEMS: { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Home', end: true },
  { to: '/debates', label: 'My Debates', end: true },
  { to: '/debates/new', label: 'New Debate' },
  { to: '/agents', label: 'Agents', end: true },
  { to: '/dashboard', label: 'Dashboard', end: true },
]

export default function AppHeader() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <header className="sticky top-0 z-20 border-b border-gray-800 bg-gray-900/95 backdrop-blur px-4 sm:px-6 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <Link
            to="/"
            className="mr-2 shrink-0 text-base sm:text-xl font-bold text-white hover:text-indigo-300"
          >
            AI Debate Arena
          </Link>
          <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  [
                    'rounded-lg px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500',
                    isActive
                      ? 'bg-gray-800 font-semibold text-white'
                      : 'text-gray-400 hover:bg-gray-800/60 hover:text-white',
                  ].join(' ')
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {user && (
            <span
              className="hidden max-w-[14rem] truncate text-xs text-gray-400 md:inline"
              title={user.email}
            >
              {user.email}
            </span>
          )}
          <button type="button" onClick={handleLogout} className="btn-danger">
            Logout
          </button>
        </div>
      </div>
    </header>
  )
}
