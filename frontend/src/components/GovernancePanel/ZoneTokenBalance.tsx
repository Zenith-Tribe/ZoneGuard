import { useState, useEffect } from 'react'

interface TokenTransaction {
  id: string
  event_type: string
  delta: number
  balance_after: number
  created_at: string
  notes?: string
}

interface TokenBalance {
  rider_id: string
  balance: number
  lifetime_earned: number
  lifetime_burned: number
  governance_weight: number
  updated_at: string
}

interface Props {
  riderId: string
  apiAvailable: boolean
}

const EVENT_LABELS: Record<string, { label: string; color: string }> = {
  weekly_coverage:    { label: 'Weekly Coverage',      color: 'text-emerald-600' },
  claim_free_4weeks:  { label: '4-Week Claim-Free',    color: 'text-emerald-600' },
  s4_checkin:         { label: 'S4 Check-in',          color: 'text-blue-600'   },
  referral_active:    { label: 'Active Referral',       color: 'text-violet-600' },
  appeal_successful:  { label: 'Successful Appeal',     color: 'text-emerald-600' },
  appeal_false:       { label: 'False Appeal',          color: 'text-red-600'    },
  governance_vote:    { label: 'Governance Vote',       color: 'text-amber-600'  },
  admin_adjustment:   { label: 'Admin Adjustment',      color: 'text-stone-500'  },
}

// Mock data for when API is unavailable
const MOCK_BALANCE: TokenBalance = {
  rider_id: 'AMZFLEX-BLR-04821',
  balance: 185,
  lifetime_earned: 235,
  lifetime_burned: 50,
  governance_weight: 13.6,
  updated_at: new Date().toISOString(),
}

const MOCK_HISTORY: TokenTransaction[] = [
  { id: 'ZTX-001', event_type: 'weekly_coverage',   delta: +10, balance_after: 185, created_at: '2025-01-20T00:00:00Z' },
  { id: 'ZTX-002', event_type: 'governance_vote',    delta: +3,  balance_after: 175, created_at: '2025-01-18T00:00:00Z' },
  { id: 'ZTX-003', event_type: 's4_checkin',         delta: +5,  balance_after: 172, created_at: '2025-01-15T00:00:00Z' },
  { id: 'ZTX-004', event_type: 'claim_free_4weeks',  delta: +25, balance_after: 167, created_at: '2025-01-13T00:00:00Z' },
  { id: 'ZTX-005', event_type: 'appeal_false',       delta: -50, balance_after: 142, created_at: '2025-01-05T00:00:00Z' },
]

// Visual arc for token balance (0-500 benchmark)
function BalanceArc({ balance }: { balance: number }) {
  const pct = Math.min(balance / 500, 1)
  const radius = 44
  const circumference = 2 * Math.PI * radius
  const strokeDash = circumference * pct
  const gap = circumference - strokeDash

  return (
    <svg width="120" height="120" viewBox="0 0 120 120" className="mx-auto">
      {/* Track */}
      <circle cx="60" cy="60" r={radius} fill="none" stroke="#fef3c7" strokeWidth="10" />
      {/* Progress */}
      <circle
        cx="60" cy="60" r={radius}
        fill="none"
        stroke="#d97706"
        strokeWidth="10"
        strokeLinecap="round"
        strokeDasharray={`${strokeDash} ${gap}`}
        strokeDashoffset={circumference * 0.25}
        transform="rotate(-90 60 60)"
        style={{ transition: 'stroke-dasharray 1s ease' }}
      />
      {/* Center text */}
      <text x="60" y="55" textAnchor="middle" className="font-bold" fontSize="22" fill="#1c1917" fontWeight="700">
        {balance}
      </text>
      <text x="60" y="72" textAnchor="middle" fontSize="9" fill="#78716c" fontWeight="500">
        ZONE
      </text>
    </svg>
  )
}

export default function ZoneTokenBalance({ riderId, apiAvailable }: Props) {
  const [balance, setBalance] = useState<TokenBalance>(MOCK_BALANCE)
  const [history, setHistory] = useState<TokenTransaction[]>(MOCK_HISTORY)
  const [loading, setLoading] = useState(true)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    if (!apiAvailable) { setLoading(false); return }
    const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'
    const load = async () => {
      try {
        const [balRes, histRes] = await Promise.all([
          fetch(`${BASE}/api/v1/governance/tokens/${riderId}`),
          fetch(`${BASE}/api/v1/governance/tokens/${riderId}/history?limit=10`),
        ])
        if (balRes.ok) setBalance(await balRes.json())
        if (histRes.ok) {
          const data = await histRes.json()
          setHistory(data.transactions || [])
        }
      } catch { /* use mock */ } finally { setLoading(false) }
    }
    load()
  }, [riderId, apiAvailable])

  const displayed = showAll ? history : history.slice(0, 4)

  return (
    <div className="space-y-4">
      {/* Balance arc */}
      <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-stone-800 font-bold text-sm">ZONE Token Balance</h3>
            <p className="text-stone-400 text-xs mt-0.5">Non-transferable governance token</p>
          </div>
          <span className="bg-amber-50 text-amber-700 text-xs font-semibold px-2 py-0.5 rounded-full border border-amber-200">
            Non-transferable
          </span>
        </div>

        {loading ? (
          <div className="h-32 bg-amber-50 rounded-xl animate-pulse" />
        ) : (
          <>
            <BalanceArc balance={balance.balance} />

            <div className="grid grid-cols-3 gap-2 mt-4">
              {[
                { label: 'Voting Weight', value: balance.governance_weight.toFixed(1) },
                { label: 'Lifetime Earned', value: balance.lifetime_earned.toString() },
                { label: 'Lifetime Burned', value: balance.lifetime_burned.toString() },
              ].map(({ label, value }) => (
                <div key={label} className="bg-stone-50 rounded-xl p-2.5 text-center border border-stone-100">
                  <p className="text-stone-800 font-bold text-sm">{value}</p>
                  <p className="text-stone-400 text-xs mt-0.5 leading-tight">{label}</p>
                </div>
              ))}
            </div>

            {/* Quadratic voting note */}
            <p className="text-stone-400 text-xs text-center mt-3">
              Voting power = √{balance.balance} = <span className="text-amber-600 font-semibold">{balance.governance_weight.toFixed(1)}</span> (quadratic)
            </p>
          </>
        )}
      </div>

      {/* Earn more */}
      <div className="bg-amber-50 rounded-xl border border-amber-100 p-4">
        <p className="text-amber-800 font-semibold text-xs mb-2">How to earn ZONE tokens</p>
        <div className="space-y-1">
          {[
            ['+10', 'Every week of coverage'],
            ['+25', '4 consecutive claim-free weeks'],
            ['+5',  'S4 signal check-in (weekly)'],
            ['+50', 'Successful referral (max 3/yr)'],
            ['+100','Winning a governance appeal'],
          ].map(([amt, desc]) => (
            <div key={desc} className="flex items-center justify-between text-xs">
              <span className="text-stone-600">{desc}</span>
              <span className="text-emerald-600 font-bold">{amt}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Transaction history */}
      <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4">
        <h3 className="text-stone-800 font-bold text-sm mb-3">Token History</h3>
        {loading ? (
          <div className="space-y-2">
            {[1, 2, 3].map(i => <div key={i} className="h-10 bg-stone-50 rounded-lg animate-pulse" />)}
          </div>
        ) : history.length === 0 ? (
          <p className="text-stone-400 text-xs text-center py-4">No transactions yet. Coverage tokens are awarded weekly.</p>
        ) : (
          <div className="space-y-2">
            {displayed.map((tx) => {
              const meta = EVENT_LABELS[tx.event_type] || { label: tx.event_type, color: 'text-stone-500' }
              return (
                <div key={tx.id} className="flex items-center justify-between p-2.5 rounded-xl bg-stone-50 border border-stone-100">
                  <div className="min-w-0 flex-1">
                    <p className="text-stone-700 text-xs font-medium truncate">{meta.label}</p>
                    <p className="text-stone-400 text-xs">{new Date(tx.created_at).toLocaleDateString()}</p>
                  </div>
                  <div className="flex items-center gap-2 ml-2 flex-shrink-0">
                    <span className={`text-xs font-bold ${meta.color}`}>
                      {tx.delta > 0 ? '+' : ''}{tx.delta}
                    </span>
                    <span className="text-stone-400 text-xs">{tx.balance_after}</span>
                  </div>
                </div>
              )
            })}
            {history.length > 4 && (
              <button
                onClick={() => setShowAll(p => !p)}
                className="w-full text-amber-600 text-xs font-medium py-1.5 hover:text-amber-700 transition-colors"
              >
                {showAll ? 'Show less' : `Show all ${history.length} transactions`}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
