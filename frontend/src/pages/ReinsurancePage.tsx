import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_URL, getPoolState, getPoolTranches, getProviderPositions, getYieldHistory } from '../services/api'

type Tab = 'overview' | 'stake' | 'positions' | 'stress'

interface PoolState {
  total_pool_inr: number
  senior_pool_inr: number
  mezzanine_pool_inr: number
  junior_pool_inr: number
  loss_ratio_ltm: number
  active_positions: number
  utilization_pct: number
  tranches: Tranche[]
}

interface Tranche {
  name: string
  allocation_pct: number
  current_amount: number
  target_yield_min: number
  target_yield_max: number
  lock_days?: number
}

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

interface YieldEntry {
  date: string
  tranche: string
  yield_amount: number
  pool_size: number
  apy: number
}

interface StressResult {
  scenario: string
  loss_pct: number
  junior_wiped: boolean
  mezzanine_impaired: boolean
  senior_impaired: boolean
  residual_pool_inr: number
}

const MOCK_POOL: PoolState = {
  total_pool_inr: 4_200_000,
  senior_pool_inr: 2_940_000,
  mezzanine_pool_inr: 840_000,
  junior_pool_inr: 420_000,
  loss_ratio_ltm: 42.3,
  active_positions: 7,
  utilization_pct: 31.5,
  tranches: [
    { name: 'Senior', allocation_pct: 70, current_amount: 2_940_000, target_yield_min: 9, target_yield_max: 11, lock_days: 180 },
    { name: 'Mezzanine', allocation_pct: 20, current_amount: 840_000, target_yield_min: 14, target_yield_max: 18, lock_days: 90 },
    { name: 'Junior', allocation_pct: 10, current_amount: 420_000, target_yield_min: 25, target_yield_max: 30, lock_days: 30 },
  ],
}

const MOCK_POSITIONS: Position[] = [
  { position_id: 'POS-001', tranche: 'Senior', amount: 500_000, expected_yield: 10.2, accrued_yield: 12_500, staked_at: '2025-01-01T00:00:00Z', unlock_date: '2025-07-01T00:00:00Z', is_locked: true },
  { position_id: 'POS-002', tranche: 'Mezzanine', amount: 200_000, expected_yield: 16.1, accrued_yield: 8_200, staked_at: '2025-01-15T00:00:00Z', unlock_date: '2025-04-15T00:00:00Z', is_locked: false },
]

const MOCK_YIELD: YieldEntry[] = [
  { date: '2025-01-20', tranche: 'Senior', yield_amount: 5500, pool_size: 2_940_000, apy: 10.2 },
  { date: '2025-01-20', tranche: 'Mezzanine', yield_amount: 3200, pool_size: 840_000, apy: 16.1 },
  { date: '2025-01-20', tranche: 'Junior', yield_amount: 2100, pool_size: 420_000, apy: 27.4 },
  { date: '2025-01-13', tranche: 'Senior', yield_amount: 5200, pool_size: 2_900_000, apy: 9.8 },
  { date: '2025-01-13', tranche: 'Mezzanine', yield_amount: 3100, pool_size: 830_000, apy: 15.9 },
]

const MOCK_STRESS: StressResult[] = [
  { scenario: 'Category 5 Cyclone (all zones)', loss_pct: 85, junior_wiped: true, mezzanine_impaired: true, senior_impaired: false, residual_pool_inr: 2_520_000 },
  { scenario: 'Monsoon + AQI Crisis (3 zones)', loss_pct: 45, junior_wiped: true, mezzanine_impaired: false, senior_impaired: false, residual_pool_inr: 3_360_000 },
  { scenario: 'Flash Flood (1 zone)', loss_pct: 15, junior_wiped: false, mezzanine_impaired: false, senior_impaired: false, residual_pool_inr: 3_990_000 },
]

const TRANCHE_COLORS: Record<string, { bg: string; text: string; bar: string; border: string }> = {
  Senior:    { bg: 'bg-blue-500/10',  text: 'text-blue-400',  bar: 'bg-blue-400',  border: 'border-blue-500/30' },
  Mezzanine: { bg: 'bg-amber-500/10', text: 'text-amber-400', bar: 'bg-amber-400', border: 'border-amber-500/30' },
  Junior:    { bg: 'bg-red-500/10',   text: 'text-red-400',   bar: 'bg-red-400',   border: 'border-red-500/30' },
}

export default function ReinsurancePage() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [pool, setPool] = useState<PoolState>(MOCK_POOL)
  const [positions, setPositions] = useState<Position[]>(MOCK_POSITIONS)
  const [yieldHistory, setYieldHistory] = useState<YieldEntry[]>(MOCK_YIELD)
  const [stressResults] = useState<StressResult[]>(MOCK_STRESS)
  const [apiAvailable, setApiAvailable] = useState(false)

  // Stake form
  const [stakeAmount, setStakeAmount] = useState('')
  const [stakeTranche, setStakeTranche] = useState('Senior')
  const [staking, setStaking] = useState(false)
  const [stakeToast, setStakeToast] = useState<string | null>(null)

  // Stress test
  const [stressTesting, setStressTesting] = useState(false)

  const providerId = 'LP-DEMO-001'

  useEffect(() => {
    const load = async () => {
      try {
        const poolData = await getPoolState()
        setPool(poolData as unknown as PoolState)
        setApiAvailable(true)

        const [trancheData, posData, yieldData] = await Promise.all([
          getPoolTranches(),
          getProviderPositions(providerId),
          getYieldHistory(),
        ])
        if (trancheData) {
          setPool((prev) => ({ ...prev, tranches: trancheData as unknown as Tranche[] }))
        }
        if (posData?.positions) setPositions(posData.positions as unknown as Position[])
        if (yieldData?.distributions) setYieldHistory(yieldData.distributions as unknown as YieldEntry[])
      } catch {
        /* graceful degradation */
      }
    }
    load()
  }, [])

  const handleStake = async () => {
    const amount = Number(stakeAmount)
    if (!amount || amount <= 0) return
    setStaking(true)
    try {
      if (apiAvailable) {
        const res = await fetch(`${API_URL}/api/v1/reinsurance/pool/stake`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider_id: providerId, amount, tranche: stakeTranche.toLowerCase() }),
        })
        if (!res.ok) throw new Error('Stake failed')
      }
      setStakeToast(`Staked ₹${amount.toLocaleString()} into ${stakeTranche} tranche`)
      setStakeAmount('')
      setTimeout(() => setStakeToast(null), 3000)
    } catch {
      setStakeToast('Stake failed — try again')
      setTimeout(() => setStakeToast(null), 3000)
    } finally {
      setStaking(false)
    }
  }

  const handleStressTest = async () => {
    setStressTesting(true)
    try {
      if (apiAvailable) {
        await fetch(`${API_URL}/api/v1/reinsurance/pool/stress-test`, { method: 'POST' })
      }
      // Simulate delay for demo
      await new Promise((r) => setTimeout(r, 1500))
    } catch {
      /* use mock results */
    } finally {
      setStressTesting(false)
    }
  }

  const tvl = pool.total_pool_inr

  const tabs: { id: Tab; label: string }[] = [
    { id: 'overview', label: 'Pool Overview' },
    { id: 'stake', label: 'Stake' },
    { id: 'positions', label: 'My Positions' },
    { id: 'stress', label: 'Stress Test' },
  ]

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Header */}
      <header className="bg-slate-950 border-b border-slate-800 px-3 sm:px-4 lg:px-6 py-3 flex items-center justify-between sticky top-0 z-[1000]">
        <div className="flex items-center gap-2 sm:gap-3">
          <button
            aria-label="Go back"
            onClick={() => navigate('/admin')}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="flex items-center gap-2 sm:gap-2.5">
            <div className="w-6 h-6 sm:w-7 sm:h-7 bg-emerald-500 rounded-lg flex items-center justify-center shadow-lg shadow-emerald-500/20 text-sm">
              🏦
            </div>
            <div>
              <p className="text-white font-bold text-xs sm:text-sm leading-tight">ZoneReinsurance Pool</p>
              <p className="text-slate-500 text-xs hidden sm:block">IRDAI/SB/2024/ZG-001 SPV Model</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <span className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-xs font-bold px-2.5 py-1 rounded-full">
            TVL: ₹{(tvl / 100_000).toFixed(1)}L
          </span>
          <div className={`w-2 h-2 rounded-full ${apiAvailable ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-5 space-y-4 sm:space-y-5">
        {/* Tab Bar */}
        <div className="flex gap-1 bg-slate-800 rounded-xl p-1 border border-slate-700">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 py-2 rounded-lg text-xs font-semibold transition-all ${
                activeTab === tab.id
                  ? 'bg-slate-700 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-300'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Pool Overview Tab */}
        {activeTab === 'overview' && (
          <div className="space-y-4">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {[
                { label: 'Total Pool', value: `₹${(tvl / 100_000).toFixed(1)}L` },
                { label: 'LTM Loss Ratio', value: `${pool.loss_ratio_ltm}%` },
                { label: 'Active Positions', value: pool.active_positions.toString() },
                { label: 'Utilization', value: `${pool.utilization_pct ?? 31.5}%` },
              ].map(({ label, value }) => (
                <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-4">
                  <p className="text-slate-400 text-xs uppercase tracking-wide">{label}</p>
                  <p className="text-white font-bold text-lg sm:text-xl mt-1">{value}</p>
                </div>
              ))}
            </div>

            {/* Tranche Breakdown */}
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
              <h2 className="text-white font-bold text-base mb-4">Tranche Breakdown</h2>

              {/* Stacked bar */}
              <div className="h-4 rounded-full overflow-hidden flex mb-4">
                {pool.tranches.map((t) => {
                  const colors = TRANCHE_COLORS[t.name] || TRANCHE_COLORS.Senior
                  return (
                    <div key={t.name} className={colors.bar} style={{ width: `${t.allocation_pct}%` }} />
                  )
                })}
              </div>

              <div className="space-y-3">
                {pool.tranches.map((t) => {
                  const colors = TRANCHE_COLORS[t.name] || TRANCHE_COLORS.Senior
                  return (
                    <div key={t.name} className={`${colors.bg} border ${colors.border} rounded-xl p-3 flex items-center justify-between`}>
                      <div className="flex items-center gap-2">
                        <div className={`w-3 h-3 rounded-full ${colors.bar}`} />
                        <div>
                          <p className={`${colors.text} font-semibold text-sm`}>{t.name} ({t.allocation_pct}%)</p>
                          <p className="text-slate-500 text-xs">Lock: {t.lock_days ?? '—'} days</p>
                        </div>
                      </div>
                      <div className="text-right">
                        <p className="text-white font-bold text-sm">₹{(t.current_amount / 100_000).toFixed(1)}L</p>
                        <p className={`${colors.text} text-xs font-medium`}>{t.target_yield_min}-{t.target_yield_max}% yield</p>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="mt-4 pt-3 border-t border-slate-700">
                <p className="text-slate-500 text-xs leading-relaxed">
                  Loss waterfall: Junior (first loss) → Mezzanine → Senior (last loss).
                  Capital providers earn yield from premium flows proportional to their tranche risk.
                </p>
              </div>
            </div>

            {/* Yield History */}
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
              <h2 className="text-white font-bold text-base mb-3">Recent Yield Distributions</h2>
              <div className="space-y-2">
                {yieldHistory.slice(0, 6).map((entry, i) => {
                  const colors = TRANCHE_COLORS[entry.tranche] || TRANCHE_COLORS.Senior
                  return (
                    <div key={`${entry.date}-${entry.tranche}-${i}`} className="flex items-center justify-between p-2.5 bg-slate-900 border border-slate-700 rounded-lg text-xs">
                      <div className="flex items-center gap-2">
                        <span className={`${colors.text} font-medium w-20`}>{entry.tranche}</span>
                        <span className="text-slate-500">{new Date(entry.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className="text-emerald-400 font-bold">₹{entry.yield_amount.toLocaleString()}</span>
                        <span className="text-slate-500">{entry.apy}% APY</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {/* Stake Tab */}
        {activeTab === 'stake' && (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
            <h2 className="text-white font-bold text-base mb-1">Stake into Pool</h2>
            <p className="text-slate-400 text-xs mb-4">Provide capital to earn yield from premium flows</p>

            <div className="space-y-3">
              <div>
                <label className="text-slate-400 text-xs font-medium mb-1 block">Tranche</label>
                <div className="grid grid-cols-3 gap-2">
                  {pool.tranches.map((t) => {
                    const colors = TRANCHE_COLORS[t.name] || TRANCHE_COLORS.Senior
                    const isSelected = stakeTranche === t.name
                    return (
                      <button
                        key={t.name}
                        onClick={() => setStakeTranche(t.name)}
                        className={`p-3 rounded-xl border text-left transition-all ${
                          isSelected
                            ? `${colors.bg} ${colors.border} ring-1 ring-offset-1 ring-offset-slate-800 ring-slate-500`
                            : 'bg-slate-900 border-slate-700 hover:border-slate-600'
                        }`}
                      >
                        <p className={`text-sm font-bold ${isSelected ? colors.text : 'text-white'}`}>{t.name}</p>
                        <p className="text-slate-500 text-xs mt-0.5">{t.target_yield_min}-{t.target_yield_max}% yield</p>
                        <p className="text-slate-500 text-xs">{t.lock_days ?? '—'} day lock</p>
                      </button>
                    )
                  })}
                </div>
              </div>

              <div>
                <label className="text-slate-400 text-xs font-medium mb-1 block">Amount (INR)</label>
                <input
                  type="number"
                  value={stakeAmount}
                  onChange={(e) => setStakeAmount(e.target.value)}
                  placeholder="e.g. 100000"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-slate-500 focus:outline-none focus:border-emerald-500"
                />
              </div>

              <button
                onClick={handleStake}
                disabled={staking || !stakeAmount || Number(stakeAmount) <= 0}
                className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-bold py-2.5 rounded-lg transition-colors"
              >
                {staking ? 'Processing...' : `Stake into ${stakeTranche}`}
              </button>

              <div className="bg-slate-900 border border-slate-700 rounded-lg p-3">
                <p className="text-slate-500 text-xs leading-relaxed">
                  By staking, you agree to the lock period and risk profile of your chosen tranche.
                  Junior tranche bears first losses but earns the highest yield.
                  Senior tranche has the lowest risk and moderate returns.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* My Positions Tab */}
        {activeTab === 'positions' && (
          <div className="space-y-3">
            {positions.length === 0 ? (
              <div className="bg-slate-800 border border-slate-700 rounded-xl p-8 text-center">
                <p className="text-slate-400 text-sm">No active positions</p>
                <p className="text-slate-500 text-xs mt-1">Stake into a tranche to start earning yield</p>
              </div>
            ) : (
              positions.map((pos) => {
                const colors = TRANCHE_COLORS[pos.tranche] || TRANCHE_COLORS.Senior
                return (
                  <div key={pos.position_id} className="bg-slate-800 border border-slate-700 rounded-xl p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-semibold border ${colors.bg} ${colors.text} ${colors.border}`}>
                          {pos.tranche}
                        </span>
                        <span className="text-slate-500 text-xs font-mono">{pos.position_id}</span>
                      </div>
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        pos.is_locked
                          ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                          : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      }`}>
                        {pos.is_locked ? 'Locked' : 'Unlocked'}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                      <div>
                        <p className="text-slate-400">Staked</p>
                        <p className="text-white font-bold text-sm">₹{pos.amount.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Expected Yield</p>
                        <p className="text-emerald-400 font-bold text-sm">{pos.expected_yield}% APY</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Accrued Yield</p>
                        <p className="text-emerald-400 font-bold text-sm">₹{pos.accrued_yield.toLocaleString()}</p>
                      </div>
                      <div>
                        <p className="text-slate-400">Unlock Date</p>
                        <p className="text-white font-medium text-sm">
                          {new Date(pos.unlock_date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                        </p>
                      </div>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        )}

        {/* Stress Test Tab */}
        {activeTab === 'stress' && (
          <div className="space-y-4">
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-white font-bold text-base">Catastrophe Stress Test</h2>
                  <p className="text-slate-400 text-xs mt-0.5">Simulate extreme loss scenarios against the current pool</p>
                </div>
                <button
                  onClick={handleStressTest}
                  disabled={stressTesting}
                  className="bg-red-600 hover:bg-red-500 disabled:bg-slate-700 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
                >
                  {stressTesting ? 'Testing...' : 'Run Stress Test'}
                </button>
              </div>

              <div className="space-y-3">
                {stressResults.map((result) => (
                  <div key={result.scenario} className="bg-slate-900 border border-slate-700 rounded-xl p-3 sm:p-4">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-white font-semibold text-sm">{result.scenario}</p>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                        result.loss_pct > 70
                          ? 'bg-red-500/20 text-red-400'
                          : result.loss_pct > 40
                          ? 'bg-amber-500/20 text-amber-400'
                          : 'bg-emerald-500/20 text-emerald-400'
                      }`}>
                        {result.loss_pct}% loss
                      </span>
                    </div>

                    {/* Impact bar */}
                    <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-3">
                      <div
                        className={`h-full rounded-full transition-all duration-700 ${
                          result.loss_pct > 70 ? 'bg-red-500' : result.loss_pct > 40 ? 'bg-amber-500' : 'bg-emerald-500'
                        }`}
                        style={{ width: `${result.loss_pct}%` }}
                      />
                    </div>

                    <div className="grid grid-cols-4 gap-2 text-xs">
                      <div>
                        <p className="text-slate-400">Junior</p>
                        <p className={result.junior_wiped ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'}>
                          {result.junior_wiped ? 'WIPED' : 'OK'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">Mezzanine</p>
                        <p className={result.mezzanine_impaired ? 'text-amber-400 font-bold' : 'text-emerald-400 font-bold'}>
                          {result.mezzanine_impaired ? 'IMPAIRED' : 'OK'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">Senior</p>
                        <p className={result.senior_impaired ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'}>
                          {result.senior_impaired ? 'IMPAIRED' : 'SAFE'}
                        </p>
                      </div>
                      <div>
                        <p className="text-slate-400">Residual</p>
                        <p className="text-white font-bold">₹{(result.residual_pool_inr / 100_000).toFixed(1)}L</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-slate-900 border border-slate-700 rounded-lg p-3">
              <p className="text-slate-500 text-xs leading-relaxed">
                Stress tests model catastrophic loss scenarios against current pool reserves.
                The loss waterfall follows Junior → Mezzanine → Senior order.
                IRDAI requires pools to survive a 1-in-50 year event without senior tranche impairment.
              </p>
            </div>
          </div>
        )}

        <div className="text-center pb-4">
          <p className="text-slate-600 text-xs">
            ZoneReinsurance Pool v1.0 · IRDAI/SB/2024/ZG-001 · SPV Model · Tranche-based capital structure
          </p>
        </div>
      </main>

      {/* Toast */}
      {stakeToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs font-medium px-4 py-2.5 rounded-xl shadow-lg z-50 max-w-xs text-center border border-slate-700">
          {stakeToast}
        </div>
      )}
    </div>
  )
}
