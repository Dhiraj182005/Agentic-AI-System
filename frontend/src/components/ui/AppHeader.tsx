import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import BrandMark from './BrandMark'

type NavItem = { to: string; label: string; end?: boolean; icon: string }

// Heroicons-style outline paths (24x24) so the nav needs no icon dependency.
const NAV_ITEMS: NavItem[] = [
  {
    to: '/',
    label: 'Dashboard',
    end: true,
    icon: 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  },
  { to: '/debates/new', label: 'New Debate', icon: 'M12 5v14M5 12h14' },
  {
    to: '/debates',
    label: 'My Debates',
    end: true,
    icon: 'M4 6h16M4 12h16M4 18h10',
  },
  {
    to: '/reports',
    label: 'Reports',
    end: true,
    icon: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  },
  {
    to: '/analytics',
    label: 'Analytics',
    end: true,
    icon: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  },
  {
    to: '/agents',
    label: 'Agent Playground',
    end: true,
    icon: 'M9 3h6v4l4 9a3 3 0 01-3 4H8a3 3 0 01-3-4l4-9V3z',
  },
  {
    to: '/profile',
    label: 'Profile',
    end: true,
    icon: 'M12 3a4 4 0 110 8 4 4 0 010-8zM4 21a8 8 0 0116 0',
  },
]

function NavIcon({ path }: { path: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4 shrink-0"
    >
      <path d={path} />
    </svg>
  )
}

function Brand() {
  return (
    <Link
      to="/"
      className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
    >
      <BrandMark />
    </Link>
  )
}

/**
 * Application navigation: a fixed sidebar on large screens and a top bar with
 * a toggleable menu on small screens. Both render the same NAV_ITEMS.
 */
export default function AppHeader() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)

  // Close the mobile menu after navigating.
  useEffect(() => {
    setMenuOpen(false)
  }, [location.pathname])

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  const links = (
    <nav aria-label="Primary" className="flex flex-col gap-0.5">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            [
              'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500',
              isActive
                ? 'bg-gray-800 font-medium text-white'
                : 'text-gray-400 hover:bg-gray-800/60 hover:text-white',
            ].join(' ')
          }
        >
          <NavIcon path={item.icon} />
          {item.label}
        </NavLink>
      ))}
    </nav>
  )

  const account = (
    <div className="border-t border-gray-800 pt-4">
      {user && (
        <p className="truncate px-3 text-xs text-gray-400" title={user.email}>
          {user.email}
        </p>
      )}
      {user?.is_demo && (
        <p className="mx-3 mt-2 inline-block rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-300">
          Demo account
        </p>
      )}
      <button
        type="button"
        onClick={handleLogout}
        className="btn-ghost mt-2 w-full justify-start px-3 py-2 font-medium"
      >
        Sign out
      </button>
    </div>
  )

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-gray-800 bg-gray-900 px-3 py-5 lg:flex">
        <div className="px-2">
          <Brand />
        </div>
        <div className="mt-8 flex-1 overflow-y-auto">{links}</div>
        {account}
      </aside>

      {/* Mobile / tablet top bar */}
      <header className="sticky top-0 z-30 border-b border-gray-800 bg-gray-900/95 px-4 py-3 backdrop-blur lg:hidden">
        <div className="flex items-center justify-between gap-3">
          <Brand />
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            className="btn-ghost px-3 py-2"
          >
            <span className="sr-only">{menuOpen ? 'Close menu' : 'Open menu'}</span>
            <NavIcon path={menuOpen ? 'M6 6l12 12M18 6L6 18' : 'M4 7h16M4 12h16M4 17h16'} />
          </button>
        </div>
        {menuOpen && (
          <div id="mobile-nav" className="mt-3 space-y-3 pb-1">
            {links}
            {account}
          </div>
        )}
      </header>
    </>
  )
}
