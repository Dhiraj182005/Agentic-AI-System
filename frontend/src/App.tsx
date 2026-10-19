import { Routes, Route, Navigate } from 'react-router-dom'
import Login from './pages/Login'
import Register from './pages/Register'
import Home from './pages/Home'
import AgentTest from './pages/AgentTest'
import DebateList from './pages/DebateList'
import DebateNew from './pages/DebateNew'
import DebateDetail from './pages/DebateDetail'
import Dashboard from './pages/Dashboard'
import ProtectedRoute from './components/ProtectedRoute'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Home />
          </ProtectedRoute>
        }
      />
      <Route
        path="/agents"
        element={
          <ProtectedRoute>
            <AgentTest />
          </ProtectedRoute>
        }
      />
      <Route
        path="/debates"
        element={
          <ProtectedRoute>
            <DebateList />
          </ProtectedRoute>
        }
      />
      <Route
        path="/debates/new"
        element={
          <ProtectedRoute>
            <DebateNew />
          </ProtectedRoute>
        }
      />
      <Route
        path="/debates/:debateId"
        element={
          <ProtectedRoute>
            <DebateDetail />
          </ProtectedRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
