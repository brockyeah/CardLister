import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, setToken, setUsername } from '../api'

export default function Login() {
  const [username, setUser] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const resp = await login(username.trim(), password)
      setToken(resp.token)
      setUsername(resp.username)
      navigate('/')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="card-panel w-full max-w-sm">
        <h1 className="text-3xl font-black text-emerald-400 mb-1">CardLister</h1>
        <p className="text-sm text-gray-400 mb-6">Sign in to continue.</p>
        <label className="label">Username</label>
        <input
          type="text"
          autoFocus
          autoCapitalize="none"
          autoCorrect="off"
          value={username}
          onChange={(e) => setUser(e.target.value)}
          className="input mb-4"
          placeholder="username"
        />
        <label className="label">Password</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="input mb-4"
          placeholder="••••••••"
        />
        {error && (
          <div className="bg-red-900/40 border border-red-700 text-red-200 text-sm rounded-lg px-3 py-2 mb-4">
            {error}
          </div>
        )}
        <button type="submit" disabled={loading || !password} className="btn-primary w-full">
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
