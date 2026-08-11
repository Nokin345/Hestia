import { Routes, Route, Navigate } from 'react-router-dom'
import { useEffect } from 'react'
import { apiFetch } from './api/client'
import { useAuth } from './store/auth'
import Login from './pages/Login'
import ChatPage from './pages/ChatPage'
import SettingsPage from './pages/Settings'
import MemoriesPage from './pages/Memories'
import KnowledgeBasesPage from './pages/KnowledgeBases'
import { McpPage } from './pages/Mcp'

function Root() {
  return <ChatPage />
}

export default function App() {
  const authenticated = useAuth((s) => s.authenticated)
  const ready = useAuth((s) => s.ready)
  const setAuth = useAuth((s) => s.setAuth)

  useEffect(() => {
    apiFetch<{ authenticated: boolean; username: string }>('/auth/me')
      .then((me) => setAuth(me.authenticated, me.username))
      .catch(() => setAuth(false, ''))
    const onUnauthorized = () => setAuth(false, '')
    window.addEventListener('auth:unauthorized', onUnauthorized)
    return () => window.removeEventListener('auth:unauthorized', onUnauthorized)
  }, [setAuth])

  if (!ready) return null

  return (
    <Routes>
      <Route path="/login" element={authenticated ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/" element={authenticated ? <Root /> : <Navigate to="/login" replace />} />
      <Route
        path="/knowledge-bases"
        element={authenticated ? <KnowledgeBasesPage /> : <Navigate to="/login" replace />}
      />
      <Route path="/mcp" element={authenticated ? <McpPage /> : <Navigate to="/login" replace />} />
      <Route
        path="/memories"
        element={authenticated ? <MemoriesPage /> : <Navigate to="/login" replace />}
      />
      <Route
        path="/settings"
        element={authenticated ? <SettingsPage /> : <Navigate to="/login" replace />}
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
