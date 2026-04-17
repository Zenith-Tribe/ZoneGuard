import { useState } from 'react'
import { getPoolState } from '../../services/api'

interface TrancheState { name: string; initial: number; absorbed: number; remaining: number; wipedOut: boolean; color: string; barColor: string }

const SCENARIOS = [
  { key: 'MONSOON',    name: 'Monsoon Flash Floods', description: 'Multi-day flooding across 4 zones, 72-hour disruption', maxPayout: 1_500_000 },
  { key: 'CYCLONE',    name: 'Cyclone Landfall',     description: 'Category 3 cyclone — all zones, 5-day disruption',      maxPayout: 3_000_000 },
  { key: 'MULTI_ZONE', name: 'Multi-Zone Heat Wave',  description: 'Extreme heat (>45C) across 6 of 10 zones',             maxPayout: 800_000 },
]

const DEFAULT_POOL = { senior: 2_940_000, mezzanine: 840_000, junior: 420_000 }
const TRANCHE_META = [
  { key: 'junior',    name: 'Junior',    color: 'text-red-400',     barColor: 'bg-red-500' },
  { key: 'mezzanine', name: 'Mezzanine', color: 'text-amber-400',   barColor: 'bg-amber-500' },
  { key: 'senior',    name: 'Senior',    color: 'text-emerald-400', barColor: 'bg-emerald-500' },
] as const

export default function StressTest() {
  const [scenario, setScenario] = useState(SCENARIOS[0].key)
  const [payoutAmount, setPayoutAmount] = useState(500_000)
  const [pool, setPool] = useState(DEFAULT_POOL)
  const [waterfall, setWaterfall] = useState<TrancheState[] | null>(null)
  const [loading, setLoading] = useState(false)

  const selectedScenario = SCENARIOS.find(s => s.key === scenario)!

  const runStressTest = async () => {
    setLoading(true)
    // Try to get real pool state first
    let currentPool = { ...pool }
    try {
      const data = await getPoolState()
      currentPool = {
        senior: data.senior_pool_inr,
        mezzanine: data.mezzanine_pool_inr,
        junior: data.junior_pool_inr,
      }
      setPool(currentPool)
    } catch {
      /* use default pool */
    }

    // Compute loss waterfall: Junior -> Mezzanine -> Senior
    let loss = payoutAmount
    const tranches: TrancheState[] = TRANCHE_META.map(m => {
      const initial = currentPool[m.key as keyof typeof currentPool]
      const absorbed = Math.min(loss, initial)
      loss -= absorbed
      return { name: m.name, initial, absorbed, remaining: initial - absorbed, wipedOut: absorbed >= initial, color: m.color, barColor: m.barColor }
    })
    setWaterfall(tranches)
    setLoading(false)
  }

  const totalPool = pool.senior + pool.mezzanine + pool.junior
  const formatLakh = (v: number) => `${(v / 100_000).toFixed(1)}L`

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      <div className="mb-4">
        <h2 className="text-white font-bold text-base sm:text-lg">Catastrophe Stress Test</h2>
        <p className="text-slate-400 text-xs mt-0.5">Simulate loss events to visualize the tranche waterfall absorption</p>
      </div>

      <div className="mb-4">
        <label className="text-slate-400 text-xs font-medium mb-2 block uppercase tracking-wider">Scenario</label>
        <select
          value={scenario}
          onChange={(e) => { setScenario(e.target.value); setWaterfall(null) }}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2.5 text-white text-sm focus:outline-none focus:border-blue-500 transition-colors"
        >
          {SCENARIOS.map(s => (
            <option key={s.key} value={s.key}>{s.name}</option>
          ))}
        </select>
        <p className="text-slate-500 text-xs mt-1.5">{selectedScenario.description}</p>
      </div>

      <div className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <label className="text-slate-400 text-xs font-medium uppercase tracking-wider">Payout Amount</label>
          <span className="text-white font-bold text-sm">₹{payoutAmount.toLocaleString()}</span>
        </div>
        <input
          type="range"
          min={100_000}
          max={selectedScenario.maxPayout}
          step={50_000}
          value={payoutAmount}
          onChange={(e) => { setPayoutAmount(parseInt(e.target.value)); setWaterfall(null) }}
          className="w-full h-2 bg-slate-700 rounded-full appearance-none cursor-pointer accent-blue-500"
        />
        <div className="flex justify-between text-[10px] text-slate-600 mt-1">
          <span>₹1L</span>
          <span className="text-slate-500">{((payoutAmount / totalPool) * 100).toFixed(1)}% of pool</span>
          <span>₹{formatLakh(selectedScenario.maxPayout)}</span>
        </div>
      </div>

      <button
        onClick={runStressTest}
        disabled={loading}
        className="w-full bg-red-600 hover:bg-red-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-bold py-3 rounded-lg transition-colors mb-4"
      >
        {loading ? 'Simulating...' : 'Run Stress Test'}
      </button>

      {waterfall && (
        <div className="space-y-3">
          <p className="text-slate-400 text-xs font-semibold uppercase tracking-wider">Loss Waterfall: Junior → Mezzanine → Senior</p>

          {waterfall.map((t) => {
            const pctRemaining = t.initial > 0 ? (t.remaining / t.initial) * 100 : 0
            return (
              <div key={t.name} className={`bg-slate-900 border border-slate-700 rounded-xl p-3 ${t.wipedOut ? 'opacity-60' : ''}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={`font-semibold text-sm ${t.color}`}>{t.name}</span>
                    {t.wipedOut && (
                      <span className="text-[10px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded-full font-bold border border-red-500/30">WIPED OUT</span>
                    )}
                  </div>
                  <span className="text-slate-400 text-xs">₹{t.absorbed.toLocaleString()} absorbed</span>
                </div>
                <div className="h-3 bg-slate-700 rounded-full overflow-hidden mb-1.5">
                  <div className={`h-full ${t.barColor} rounded-full transition-all duration-700`} style={{ width: `${pctRemaining}%` }} />
                </div>
                <div className="flex justify-between text-[10px] text-slate-500">
                  <span>Remaining: ₹{t.remaining.toLocaleString()}</span>
                  <span>Initial: ₹{t.initial.toLocaleString()}</span>
                </div>
              </div>
            )
          })}
          {(() => {
            const totalAbsorbed = waterfall.reduce((s, t) => s + t.absorbed, 0)
            const unabsorbed = payoutAmount - totalAbsorbed
            return (
              <div className={`rounded-xl p-3 border ${
                unabsorbed > 0
                  ? 'bg-red-500/10 border-red-500/30'
                  : 'bg-emerald-500/10 border-emerald-500/30'
              }`}>
                <div className="flex items-center justify-between text-xs">
                  <span className={unabsorbed > 0 ? 'text-red-400 font-bold' : 'text-emerald-400 font-bold'}>
                    {unabsorbed > 0
                      ? `Pool shortfall: ₹${unabsorbed.toLocaleString()} — requires external capital`
                      : 'Pool fully absorbs the loss event'
                    }
                  </span>
                  <span className="text-slate-500">
                    {((totalAbsorbed / (pool.senior + pool.mezzanine + pool.junior)) * 100).toFixed(1)}% pool impact
                  </span>
                </div>
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
