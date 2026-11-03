import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../services/api'
import { getDemoLogin, type DemoLogin } from '../services/auth'
import AuthLayout from '../components/ui/AuthLayout'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // Demo credentials live only in component state; never in browser storage.
  const [demo, setDemo] = useState<DemoLogin | null>(null)
  const [demoState, setDemoState] = useState<'loading' | 'ready' | 'off'>('loading')
  const [demoFilled, setDemoFilled] = useState(false)

  const registeredNotice =
    (location.state as { registered?: boolean } | null)?.registered === true

  useEffect(() => {
    let cancelled = false
    getDemoLogin()
      .then((info) => {
        if (cancelled) return
        setDemo(info)
        setDemoState(info.enabled && info.email && info.password ? 'ready' : 'off')
      })
      .catch(() => {
        if (!cancelled) setDemoState('off')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function signIn(nextEmail: string, nextPassword: string) {
    if (submitting) return
    setError(null)
    setSubmitting(true)
    try {
      await login(nextEmail, nextPassword)
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to log in. Please try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    void signIn(email, password)
  }

  function fillDemo() {
    if (!demo?.email || !demo.password) return
    setEmail(demo.email)
    setPassword(demo.password)
    setDemoFilled(true)
    setError(null)
  }

  function loginWithDemo() {
    if (!demo?.email || !demo.password) return
    fillDemo()
    void signIn(demo.email, demo.password)
  }

  return (
    <AuthLayout title="Sign in" subtitle="Welcome back to your debate workspace.">
      {registeredNotice && (
        <p
          role="status"
          className="mb-4 rounded-lg border border-emerald-900/60 bg-emerald-950/50 px-4 py-2 text-center text-sm text-emerald-300"
        >
          Account created. Sign in to continue.
        </p>
      )}

      {error && (
        <p role="alert" className="alert-error mb-4 text-center">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="login-email" className="label">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              setDemoFilled(false)
            }}
            required
            className="input"
          />
        </div>
        <div>
          <label htmlFor="login-password" className="label">
            Password
          </label>
          <input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              setDemoFilled(false)
            }}
            required
            className="input"
          />
        </div>
        {demoFilled && (
          <p role="status" className="text-xs text-indigo-300" data-testid="demo-filled">
            Demo account credentials filled in. Review them, then select Login.
          </p>
        )}
        <button type="submit" disabled={submitting} className="btn-primary w-full">
          {submitting ? 'Signing in...' : 'Login'}
        </button>
      </form>

      <div className="mt-6 border-t border-gray-800 pt-5" data-testid="demo-login">
        {demoState === 'ready' && demo && (
          <>
            <p className="mb-3 text-center text-xs text-gray-400">
              Presenting MAVES? Use the shared{' '}
              <span className="font-semibold text-gray-200">demo account</span>.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={fillDemo}
                disabled={submitting}
                className="btn-secondary"
                data-testid="fill-demo"
              >
                Fill Demo Credentials
              </button>
              <button
                type="button"
                onClick={loginWithDemo}
                disabled={submitting}
                className="btn-ghost border border-gray-700"
                data-testid="login-demo"
              >
                Login with Demo Account
              </button>
            </div>
          </>
        )}
        {demoState === 'off' && (
          <p className="text-center text-xs text-gray-500" data-testid="demo-unavailable">
            Demo login is not configured on this server.
          </p>
        )}
        {demoState === 'loading' && (
          <p className="text-center text-xs text-gray-500">Checking demo access...</p>
        )}
      </div>

      <p className="mt-5 text-center text-sm text-gray-400">
        Don't have an account?{' '}
        <Link
          to="/register"
          className="rounded text-indigo-400 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
        >
          Register
        </Link>
      </p>
    </AuthLayout>
  )
}
