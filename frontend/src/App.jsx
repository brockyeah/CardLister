import { Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom'
import { getToken, getUsername, clearToken } from './api'
import Login from './pages/Login.jsx'
import Scanner from './pages/Scanner.jsx'
import Inventory from './pages/Inventory.jsx'
import Analytics from './pages/Analytics.jsx'

function RequireAuth({ children }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return children
}

function NavBar() {
  const navigate = useNavigate()
  const logout = () => {
    clearToken()
    navigate('/login')
  }

  const linkClass = ({ isActive }) =>
    `px-4 py-2 rounded-lg font-semibold transition ${
      isActive ? 'bg-emerald-600 text-white' : 'text-gray-300 hover:bg-ink-700'
    }`

  return (
    <header className="bg-ink-800 border-b border-ink-700 sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl font-black tracking-tight text-emerald-400">CardLister</span>
        </div>
        <nav className="flex items-center gap-2">
          <NavLink to="/" end className={linkClass}>Scan</NavLink>
          <NavLink to="/inventory" className={linkClass}>Inventory</NavLink>
          <NavLink to="/analytics" className={linkClass}>Analytics</NavLink>
          {getUsername() && (
            <span className="text-sm text-gray-500 ml-2 hidden sm:inline">{getUsername()}</span>
          )}
          <button onClick={logout} className="text-sm text-gray-400 hover:text-gray-200 ml-1 px-2">
            Log out
          </button>
        </nav>
      </div>
    </header>
  )
}

function Shell({ children }) {
  return (
    <div className="min-h-full">
      <NavBar />
      <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Shell><Scanner /></Shell>
          </RequireAuth>
        }
      />
      <Route
        path="/inventory"
        element={
          <RequireAuth>
            <Shell><Inventory /></Shell>
          </RequireAuth>
        }
      />
      <Route
        path="/analytics"
        element={
          <RequireAuth>
            <Shell><Analytics /></Shell>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
