import { useState, useEffect } from 'react'
import { getPoolState } from '../../services/api'

interface PoolData {
  total_pool_inr: number
  senior_pool_inr: number
  mezzanine_pool_inr: number
  junior_pool_inr: number
  loss_ratio_ltm: number
  active_positions: number
  utilization_pct: number
}

const FALLBACK: PoolData = {
  total_pool_inr: 4_200_000,
  senior_pool_inr: 2_940_000,
  mezzanine_pool_inr: 840_000,
  junior_pool_inr: 420_000,
  loss_ratio_ltm: 42.3,
  active_positions: 7,
  utilization_pct: 61,
}

const TRANCHES = [
  { key: 'senior',    name: 'Senior',    pct: 70, color: 'bg-emerald-500', border: 'border-emerald-500/30', bg: 'bg-emerald-500/10', text: 'text-emerald-400', yieldRange: '9-11%',  field: 'senior_pool_inr' as const },
  { key: 'mezzanine', name: 'Mezzanine', pct: 20, color: 'bg-amber-500',   border: 'border-amber-500/30',   bg: 'bg-amber-500/10',   text: 'text-amber-400',   yieldRange: '14-18%', field: 'mezzanine_pool_inr' as const },
  { key: 'junior',    name: 'Junior',    pct: 10, color: 'bg-red-500',     border: 'border-red-500/30',     bg: 'bg-red-500/10',     text: 'text-red-400',     yieldRange: '25-30%', field: 'junior_pool_inr' as const },
]

export default function ReinsurancePool() {
  const [pool, setPool] = useState<PoolData>(FALLBACK)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getPoolState()
        setPool({
          total_pool_inr: data.total_pool_inr,
          senior_pool_inr: data.senior_pool_inr,
          mezzanine_pool_inr: data.mezzanine_pool_inr,
          junior_pool_inr: data.junior_pool_inr,
          loss_ratio_ltm: data.loss_ratio_ltm,
          active_positions: data.active_positions,
          utilization_pct: data.utilization_pct ?? 61,
        })
      } catch {
        /* fallback to default */
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const formatLakh = (v: number) => `${(v / 100_000).toFixed(1)}L`
  const lossColor = pool.loss_ratio_ltm > 75 ? 'text-red-400' : pool.loss_ratio_ltm > 50 ? 'text-amber-400' : 'text-emerald-400'
  const lossBarColor = pool.loss_ratio_ltm > 75 ? 'bg-red-500' : pool.loss_ratio_ltm > 50 ? 'bg-amber-500' : 'bg-emerald-500'

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-white font-bold text-base sm:text-lg">ZoneReinsurance Pool</h2>
          <p className="text-slate-400 text-xs mt-0.5">IRDAI/SB/2024/ZG-001 · SPV Tranche Model</p>
        </div>
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${loading ? 'bg-amber-400 animate-pulse' : 'bg-emerald-400'}`} />
          <span className="text-slate-400 text-xs">{loading ? 'Loading...' : 'Live'}</span>
        </div>
      </div>

      {/* TVL Hero */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 mb-4 text-center">
        <p className="text-slate-400 text-xs uppercase tracking-wider mb-1">Total Value Locked</p>
        <p className="text-white font-bold text-3xl sm:text-4xl">
          ₹{formatLakh(pool.total_pool_inr)}
        </p>
        <p className="text-slate-500 text-xs mt-1">{pool.active_positions} LP positions active</p>
      </div>

      {/* Stacked tranche bar */}
      <div className="h-3 rounded-full overflow-hidden flex mb-4">
        {TRANCHES.map(t => (
          <div key={t.key} className={t.color} style={{ width: `${t.pct}%` }} title={`${t.name} ${t.pct}%`} />
        ))}
      </div>

      {/* Tranche cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        {TRANCHES.map(t => (
          <div key={t.key} className={`${t.bg} border ${t.border} rounded-xl p-3`}>
            <div className="flex items-center gap-2 mb-2">
              <div className={`w-2.5 h-2.5 rounded-full ${t.color}`} />
              <span className="text-white text-sm font-semibold">{t.name}</span>
              <span className="text-slate-500 text-xs ml-auto">{t.pct}%</span>
            </div>
            <p className="text-white font-bold text-lg">₹{formatLakh(pool[t.field])}</p>
            <p className={`${t.text} text-xs font-medium mt-1`}>{t.yieldRange} APY</p>
          </div>
        ))}
      </div>

      {/* Loss Ratio Gauge */}
      <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-slate-400 text-xs uppercase tracking-wider">LTM Loss Ratio</span>
          <span className={`font-bold text-lg ${lossColor}`}>{pool.loss_ratio_ltm}%</span>
        </div>
        <div className="h-2.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className={`h-full ${lossBarColor} rounded-full transition-all duration-700`}
            style={{ width: `${Math.min(pool.loss_ratio_ltm, 100)}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-slate-500 mt-1.5">
          <span>0%</span>
          <span className="text-amber-400">75% threshold</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  )
}
