import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Home() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">AI Debate Arena</h1>
        <button
          onClick={handleLogout}
          className="bg-red-600 hover:bg-red-700 rounded-lg px-4 py-2 text-sm font-semibold"
        >
          Logout
        </button>
      </header>

<main className="max-w-3xl mx-auto px-6 py-10">
          <h2 className="text-2xl font-semibold mb-2">
            Welcome, {user?.email}
          </h2>
          <p className="text-gray-400 mb-8">
            The debate interface is coming in a later module.
          </p>

          <Link
            to="/agents"
            className="inline-block bg-indigo-600 hover:bg-indigo-700 rounded-lg px-4 py-2 text-sm font-semibold mb-8"
          >
            Test Role-Based Agents
          </Link>

        <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6">
          <h3 className="text-lg font-semibold mb-4">Account</h3>
          <div className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
            <span className="text-gray-300">Authentication Status</span>
            <span className="flex items-center text-green-400">
              <span className="inline-block w-3 h-3 rounded-full mr-2 bg-green-500" />
              Authenticated
            </span>
          </div>
          <div className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3 mt-3">
            <span className="text-gray-300">Email</span>
            <span>{user?.email}</span>
          </div>
          <div className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3 mt-3">
            <span className="text-gray-300">User ID</span>
            <span className="font-mono text-sm text-gray-400">{user?.id}</span>
          </div>
        </div>
      </main>
    </div>
  )
}
