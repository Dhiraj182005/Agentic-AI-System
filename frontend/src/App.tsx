import type { ReactNode } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import AgentTest from './pages/AgentTest'
import DebateList from './pages/DebateList'
import DebateNew from './pages/DebateNew'
import DebateDetail from './pages/DebateDetail'
import Analytics from './pages/Analytics'
import Reports from './pages/Reports'
import Profile from './pages/Profile'
import ProtectedRoute from './components/ProtectedRoute'

function Protected({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<Protected><Dashboard /></Protected>} />
      <Route path="/agents" element={<Protected><AgentTest /></Protected>} />
      <Route path="/debates" element={<Protected><DebateList /></Protected>} />
      <Route path="/debates/new" element={<Protected><DebateNew /></Protected>} />
      <Route
        path="/debates/:debateId"
        element={<Protected><DebateDetail /></Protected>}
      />
      <Route path="/reports" element={<Protected><Reports /></Protected>} />
      <Route path="/analytics" element={<Protected><Analytics /></Protected>} />
      <Route path="/profile" element={<Protected><Profile /></Protected>} />
      {/* The analytics page used to live at /dashboard. */}
      <Route path="/dashboard" element={<Navigate to="/analytics" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
