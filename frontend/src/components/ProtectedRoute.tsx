import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/AuthContext'
import LoadingState from './ui/LoadingState'

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { authenticated, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
        <LoadingState label="Checking your session..." />
      </div>
    )
  }

  if (!authenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
