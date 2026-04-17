import { useState, useEffect, useCallback } from 'react'
import { getProviderPositions, withdrawPosition } from '../../services/api'

interface Position {
  position_id: string
  tranche: string
  amount: number
  expected_yield: number
  accrued_yield: number
  staked_at: string
  unlock_date: string
  is_locked: boolean
}

const FALLBACK_POSITIONS: Position[] = [
  { position_id: 'POS-001', tranche: 'senior',    amount: 200_000, expected_yield: 5_479, accrued_yield: 3_288,  staked_at: '2026-02-15T10:00:00Z', unlock_date: '2026-05-16T10:00:00Z', is_locked: true },
  { position_id: 'POS-002', tranche: 'mezzanine', amount: 50_000,  expected_yield: 2_466, accrued_yield: 1_849,  staked_at: '2026-01-20T10:00:00Z', unlock_date: '2026-03-21T10:00:00Z', is_locked: false },
  { position_id: 'POS-003', tranche: 'junior',    amount: 25_000,  expected_yield: 2_055, accrued_yield: 2_055,  staked_at: '2026-03-01T10:00:00Z', unlock_date: '2026-03-31T10:00:00Z', is_locked: false },
]

const TRANCHE_STYLE: Record<string, { color: string; bg: string; border: string; dot: string }> = {
  senior:    { color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', dot: 'bg-emerald-500' },
  mezzanine: { color: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   dot: 'bg-amber-500' },
  junior:    { color: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/30',     dot: 'bg-red-500' },
}

interface Props {
  providerId?: string
  refreshKey?: number
}

export default function YieldDashboard({ providerId = 'LP-DEMO-001', refreshKey }: Props) {
  const [positions, setPositions] = useState<Position[]>([])
  const [loading, setLoading] = useState(true)
  const [withdrawing, setWithdrawing] = useState<string | null>(null)
  const [toast, setToast] = useState<{ success: boolean; message: string } | null>(null)

  const loadPositions = useCallback(async () => {
    try {
      const data = await getProviderPositions(providerId)
      setPositions(data.positions ?? [])
    } catch {
      setPositions(FALLBACK_POSITIONS)
    } finally {
      setLoading(false)
    }
  }, [providerId])

  useEffect(() => {
    loadPositions()
  }, [loadPositions, refreshKey])

  const handleWithdraw = async (positionId: string) => {
    setWithdrawing(positionId)
    setToast(null)
    try {
      const res = await withdrawPosition(positionId, providerId)
      setToast({
        success: true,
        message: `Withdrawn ₹${res.amount_returned.toLocaleString()} + ₹${res.yield_paid.toLocaleString()} yield`,
      })
      setPositions(prev => prev.filter(p => p.position_id !== positionId))
    } catch {
      setToast({ success: false, message: 'Withdrawal failed — backend not connected.' })
    } finally {
      setWithdrawing(null)
    }
  }

  const totalStaked = positions.reduce((s, p) => s + p.amount, 0)
  const totalAccrued = positions.reduce((s, p) => s + p.accrued_yield, 0)

  const formatDate = (iso: string) => {
    try { return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) }
    catch { return iso }
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-white font-bold text-base sm:text-lg">Your Positions</h2>
          <p className="text-slate-400 text-xs mt-0.5">Provider: {providerId}</p>
        </div>
        <button
          onClick={loadPositions}
          className="text-slate-400 hover:text-white text-xs flex items-center gap-1 transition-colors"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-3 text-center">
          <p className="text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">Total Staked</p>
          <p className="text-white font-bold text-lg">₹{totalStaked.toLocaleString()}</p>
        </div>
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-3 text-center">
          <p className="text-slate-400 text-[10px] uppercase tracking-wider mb-0.5">Accrued Yield</p>
          <p className="text-emerald-400 font-bold text-lg">₹{totalAccrued.toLocaleString()}</p>
        </div>
      </div>

      {/* Positions list */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2].map(i => (
            <div key={i} className="bg-slate-900 border border-slate-700 rounded-xl p-4 animate-pulse">
              <div className="h-4 bg-slate-700 rounded w-1/3 mb-2" />
              <div className="h-3 bg-slate-700 rounded w-2/3" />
            </div>
          ))}
        </div>
      ) : positions.length === 0 ? (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-8 text-center">
          <p className="text-slate-500 text-sm">No active positions</p>
          <p className="text-slate-600 text-xs mt-1">Stake capital into a tranche to start earning yield</p>
        </div>
      ) : (
        <div className="space-y-3">
          {positions.map(pos => {
            const style = TRANCHE_STYLE[pos.tranche] ?? TRANCHE_STYLE.senior
            const yieldPct = pos.expected_yield > 0 ? (pos.accrued_yield / pos.expected_yield * 100) : 0
            return (
              <div key={pos.position_id} className={`${style.bg} border ${style.border} rounded-xl p-4`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={`w-2.5 h-2.5 rounded-full ${style.dot}`} />
                    <span className={`text-sm font-semibold capitalize ${style.color}`}>{pos.tranche}</span>
                    <span className="text-slate-600 text-xs">{pos.position_id}</span>
                  </div>
                  {pos.is_locked ? (
                    <span className="text-xs bg-slate-700/50 text-slate-400 px-2 py-0.5 rounded-full border border-slate-600">
                      Locked until {formatDate(pos.unlock_date)}
                    </span>
                  ) : (
                    <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-500/30">
                      Unlocked
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-3 gap-3 text-xs mb-3">
                  <div>
                    <p className="text-slate-500">Staked</p>
                    <p className="text-white font-bold">₹{pos.amount.toLocaleString()}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">Expected Yield</p>
                    <p className="text-white font-bold">₹{pos.expected_yield.toLocaleString()}</p>
                  </div>
                  <div>
                    <p className="text-slate-500">Accrued</p>
                    <p className="text-emerald-400 font-bold">₹{pos.accrued_yield.toLocaleString()}</p>
                  </div>
                </div>

                {/* Yield progress bar */}
                <div className="mb-3">
                  <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full transition-all" style={{ width: `${Math.min(yieldPct, 100)}%` }} />
                  </div>
                  <p className="text-slate-600 text-[10px] mt-1">{yieldPct.toFixed(0)}% yield accrued</p>
                </div>

                <button
                  onClick={() => handleWithdraw(pos.position_id)}
                  disabled={pos.is_locked || withdrawing === pos.position_id}
                  className={`w-full text-xs font-bold py-2 rounded-lg transition-colors ${
                    pos.is_locked
                      ? 'bg-slate-700/50 text-slate-600 cursor-not-allowed'
                      : 'bg-blue-600 hover:bg-blue-500 text-white'
                  }`}
                >
                  {withdrawing === pos.position_id ? 'Withdrawing...' : pos.is_locked ? 'Locked' : 'Withdraw Capital + Yield'}
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`mt-3 rounded-lg p-3 text-xs font-medium ${
          toast.success
            ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
            : 'bg-red-500/10 border border-red-500/30 text-red-400'
        }`}>
          {toast.success ? '✓' : '✗'} {toast.message}
        </div>
      )}
    </div>
  )
}
