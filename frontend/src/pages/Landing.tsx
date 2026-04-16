import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_URL } from '../services/api'

export default function LandingPage() {
  const navigate = useNavigate()
  const [showLogin, setShowLogin] = useState(false)
  const [loginTarget, setLoginTarget] = useState<'rider' | 'admin'>('rider')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [loggingIn, setLoggingIn] = useState(false)

  const handlePersonaClick = (target: 'rider' | 'admin') => {
    // If already logged in, navigate directly
    const token = localStorage.getItem('zoneguard_token')
    if (token) {
      navigate(target === 'rider' ? '/rider' : '/admin')
      return
    }
    setLoginTarget(target)
    setUsername(target === 'rider' ? 'rider' : 'admin')
    setPassword(target === 'rider' ? 'rider123' : 'admin123')
    setLoginError('')
    setShowLogin(true)
  }

  const handleLogin = async () => {
    setLoggingIn(true)
    setLoginError('')
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Login failed')
      }
      const data = await res.json()
      localStorage.setItem('zoneguard_token', data.token)
      localStorage.setItem('zoneguard_role', data.role)
      localStorage.setItem('zoneguard_user', data.name)
      setShowLogin(false)
      navigate(loginTarget === 'rider' ? '/rider' : '/admin')
    } catch (_err) {
      // Auth might be disabled — navigate anyway
      setShowLogin(false)
      navigate(loginTarget === 'rider' ? '/rider' : '/admin')
    } finally {
      setLoggingIn(false)
    }
  }

  const handleSkipLogin = () => {
    setShowLogin(false)
    navigate(loginTarget === 'rider' ? '/rider' : '/admin')
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex flex-col items-center justify-center px-4 relative overflow-hidden">
      {/* Ambient grid background */}
      <div
        className="absolute inset-0 pointer-events-none opacity-20"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' xmlns='http://www.w3.org/2000/svg'%3E%3Cpath d='M 60 0 L 0 0 0 60' fill='none' stroke='%23475569' stroke-width='1'/%3E%3C/svg%3E")`,
        }}
      />

      {/* Glow orbs */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-amber-500/5 rounded-full blur-3xl pointer-events-none" />
      <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-blue-500/5 rounded-full blur-3xl pointer-events-none" />

      {/* Header */}
      <div className="relative z-10 text-center mb-8 sm:mb-12 px-2">
        <div className="flex items-center justify-center gap-3 mb-4 sm:mb-6">
          <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-amber-500 flex items-center justify-center shadow-lg shadow-amber-500/30">
            <svg className="w-6 h-6 sm:w-7 sm:h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight">ZoneGuard</h1>
        </div>
        <p className="text-slate-300 text-base sm:text-lg max-w-md mx-auto leading-relaxed">
          When the zone goes dark,{' '}
          <span className="text-amber-400 font-semibold">your income doesn't have to.</span>
        </p>
        <p className="text-slate-500 text-xs sm:text-sm mt-2 sm:mt-3">
          AI-powered parametric income protection for Amazon Flex riders · Bengaluru
        </p>
      </div>

      {/* Persona cards */}
      <div className="relative z-10 grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-5 w-full max-w-2xl">
        {/* Rider card */}
        <button
          onClick={() => handlePersonaClick('rider')}
          className="group bg-amber-500/10 border border-amber-500/30 rounded-2xl p-6 sm:p-8 text-left hover:bg-amber-500/20 hover:border-amber-400 transition-all duration-200 hover:shadow-2xl hover:shadow-amber-500/10 hover:-translate-y-1 active:translate-y-0"
        >
          <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center mb-4 group-hover:bg-amber-500/30 transition-colors text-2xl">
            🛵
          </div>
          <h2 className="text-white font-bold text-xl mb-2">I'm a Rider</h2>
          <p className="text-slate-400 text-sm leading-relaxed mb-4">
            View your weekly coverage, track zone signals, and see your payout history
          </p>
          <div className="flex items-center gap-2 text-amber-400 text-sm font-medium">
            <span>Enter Rider Dashboard</span>
            <svg className="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </button>

        {/* Insurer card */}
        <button
          onClick={() => handlePersonaClick('admin')}
          className="group bg-blue-500/10 border border-blue-500/30 rounded-2xl p-6 sm:p-8 text-left hover:bg-blue-500/20 hover:border-blue-400 transition-all duration-200 hover:shadow-2xl hover:shadow-blue-500/10 hover:-translate-y-1 active:translate-y-0"
        >
          <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center mb-4 group-hover:bg-blue-500/30 transition-colors text-2xl">
            📊
          </div>
          <h2 className="text-white font-bold text-xl mb-2">I'm an Insurer</h2>
          <p className="text-slate-400 text-sm leading-relaxed mb-4">
            Monitor zone risk, manage the QuadSignal engine, review claims, and track loss ratios
          </p>
          <div className="flex items-center gap-2 text-blue-400 text-sm font-medium">
            <span>Enter Admin Dashboard</span>
            <svg className="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </div>
        </button>
      </div>

      {/* Stats strip */}
      <div className="relative z-10 mt-10 grid grid-cols-2 sm:flex sm:items-center gap-4 sm:gap-8 text-center w-full max-w-2xl px-4 sm:px-0">
        {[
          ['1,624', 'Active policies'],
          ['10', 'Zones monitored'],
          ['< 2 hrs', 'Avg payout time'],
          ['₹39–₹225', 'Weekly premiums'],
        ].map(([val, label]) => (
          <div key={label} className="bg-white/5 rounded-xl p-3 sm:bg-transparent sm:p-0">
            <p className="text-white font-bold text-lg">{val}</p>
            <p className="text-slate-500 text-xs">{label}</p>
          </div>
        ))}
      </div>

      {/* Onboarding link */}
      <div className="relative z-10 mt-8">
        <button
          onClick={() => navigate('/onboarding')}
          className="text-slate-500 hover:text-amber-400 text-sm transition-colors underline underline-offset-4"
        >
          New rider? Get covered in 90 seconds →
        </button>
      </div>

      {/* Login Modal */}
      {showLogin && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 px-4">
          <div className="bg-slate-800 border border-slate-700 rounded-2xl p-6 w-full max-w-sm">
            <h3 className="text-white font-bold text-lg mb-1">
              {loginTarget === 'rider' ? 'Rider Login' : 'Admin Login'}
            </h3>
            <p className="text-slate-400 text-xs mb-4">Demo credentials are pre-filled</p>

            <div className="space-y-3">
              <div>
                <label className="text-slate-400 text-xs block mb-1">Username</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-slate-400 text-xs block mb-1">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            {loginError && <p className="text-red-400 text-xs mt-2">{loginError}</p>}

            <div className="flex gap-2 mt-5">
              <button
                onClick={handleLogin}
                disabled={loggingIn}
                className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold py-2.5 rounded-lg transition-colors disabled:opacity-50"
              >
                {loggingIn ? 'Signing in...' : 'Sign In'}
              </button>
              <button
                onClick={handleSkipLogin}
                className="px-4 bg-slate-700 hover:bg-slate-600 text-slate-300 text-sm py-2.5 rounded-lg transition-colors"
              >
                Skip
              </button>
            </div>

            <p className="text-slate-500 text-xs text-center mt-3">
              Auth is optional — skip to proceed without login
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
