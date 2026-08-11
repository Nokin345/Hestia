import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogIn } from 'lucide-react'
import { apiPost } from '../api/client'
import { useAuth } from '../store/auth'
import { Button, Input } from '../components/ui'

export default function Login() {
  const navigate = useNavigate()
  const setAuth = useAuth((s) => s.setAuth)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await apiPost<{ authenticated: boolean; username: string }>('/auth/login', {
        username,
        password,
      })
      setAuth(res.authenticated, res.username)
      navigate('/')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex h-dvh items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <img src="/favicon.svg" className="size-16" alt="" />
          <h1 className="text-xl font-semibold text-zinc-100">Hestia</h1>
          <p className="text-sm text-zinc-500">Sign in to continue</p>
        </div>
        <form onSubmit={submit} className="space-y-3">
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoComplete="username"
            required
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            required
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          <Button type="submit" loading={loading} className="w-full">
            <LogIn className="size-4" /> Sign in
          </Button>
        </form>
      </div>
    </div>
  )
}
