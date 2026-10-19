import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { register as apiRegister } from '../services/auth'
import { apiErrorMessage } from '../services/api'

export default function Register() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }

    setSubmitting(true)
    try {
      await apiRegister(email, password)
      navigate('/login', { replace: true, state: { registered: true } })
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to register. Please try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center px-4 py-10">
      <div className="max-w-md w-full rounded-2xl border border-gray-800 bg-gray-900 p-8 shadow-xl">
        <h1 className="text-2xl font-bold mb-6 text-center">AI Debate Arena</h1>
        <h2 className="text-lg font-semibold mb-4 text-center text-gray-300">
          Create Account
        </h2>

        {error && (
          <p role="alert" className="alert-error mb-4 text-center">
            {error}
          </p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="register-email" className="label">
              Email
            </label>
            <input
              id="register-email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="input"
            />
          </div>
          <div>
            <label htmlFor="register-password" className="label">
              Password
            </label>
            <input
              id="register-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              aria-describedby="register-password-hint"
              className="input"
            />
            <p id="register-password-hint" className="field-hint">
              At least 8 characters
            </p>
          </div>
          <div>
            <label htmlFor="register-confirm-password" className="label">
              Confirm Password
            </label>
            <input
              id="register-confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              className="input"
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="btn-primary w-full"
          >
            {submitting ? 'Creating account...' : 'Register'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-400">
          Already have an account?{' '}
          <Link to="/login" className="text-indigo-400 hover:underline">
            Login
          </Link>
        </p>
      </div>
    </div>
  )
}
