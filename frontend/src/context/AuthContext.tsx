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
      if (!token) {
        setLoading(false)
        return
      }
      try {
        const me = await fetchCurrentUser()
        if (active) setUser(me)
      } catch {
        clearStoredToken()
        if (active) setUser(null)
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
