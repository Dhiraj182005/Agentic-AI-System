import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import {
  clearStoredToken,
  getStoredToken,
  isUsableToken,
  storeToken,
} from '../services/api'
import {
  fetchCurrentUser,
  login as apiLogin,
  type User,
} from '../services/auth'

interface AuthContextValue {
  user: User | null
  loading: boolean
  authenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

// Shared across React StrictMode's double-invoked effect so the app makes
// exactly one GET /auth/me per page load instead of two.
let restoreInFlight: Promise<{ token: string; user: User } | null> | null = null

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const logout = useCallback(() => {
    clearStoredToken()
    setUser(null)
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const token = await apiLogin(email, password)
    storeToken(token.access_token)
    const me = await fetchCurrentUser()
    setUser(me)
  }, [])

  useEffect(() => {
    let active = true
    async function restoreSession() {
      const token = getStoredToken()
      if (!token || !isUsableToken(token)) {
        // Missing or locally dead (expired/corrupt) token: clear it and let
        // ProtectedRoute send the user to /login. No request is made, so a
        // doomed GET /auth/me can no longer answer 401 in the console.
        if (token) clearStoredToken()
        if (active) setLoading(false)
        return
      }

      if (!restoreInFlight) {
        restoreInFlight = fetchCurrentUser()
          .then((user) => ({ token, user }))
          .finally(() => {
            restoreInFlight = null
          })
      }

      try {
        const restored = await restoreInFlight
        // Apply the result only if we are still on the same session: the
        // user may have logged out while this request was in flight.
        if (active && restored && getStoredToken() === restored.token) {
          setUser(restored.user)
        }
      } catch {
        // The backend rejected the token (e.g. wrong secret): drop it so the
        // next load is clean. Only touch state if this is still the session
        // we started with — never clobber a newer login.
        if (getStoredToken() === token) {
          clearStoredToken()
          if (active) setUser(null)
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    restoreSession()

    const onUnauthorized = () => {
      setUser(null)
    }
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => {
      active = false
      window.removeEventListener('auth:unauthorized', onUnauthorized)
    }
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, loading, authenticated: !!user, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
