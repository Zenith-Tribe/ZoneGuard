import { useState } from 'react'
import { stakeIntoPool } from '../../services/api'

interface TrancheOption {
  key: string
  name: string
  yieldMin: number
  yieldMax: number
  lockDays: number
  color: string
  bg: string
  border: string
}

const TRANCHES: TrancheOption[] = [
  { key: 'senior',    name: 'Senior',    yieldMin: 9,  yieldMax: 11, lockDays: 90, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30' },
  { key: 'mezzanine', name: 'Mezzanine', yieldMin: 14, yieldMax: 18, lockDays: 60, color: 'text-amber-400',   bg: 'bg-amber-500/10',   border: 'border-amber-500/30' },
  { key: 'junior',    name: 'Junior',    yieldMin: 25, yieldMax: 30, lockDays: 30, color: 'text-red-400',     bg: 'bg-red-500/10',     border: 'border-red-500/30' },
]

interface Props {
  providerId?: string
  onStakeSuccess?: () => void
}

export default function StakePanel({ providerId = 'LP-DEMO-001', onStakeSuccess }: Props) {
  const [selectedTranche, setSelectedTranche] = useState<string>('senior')
  const [amount, setAmount] = useState<string>('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)

  const tranche = TRANCHES.find(t => t.key === selectedTranche)!
  const amountNum = parseFloat(amount) || 0
  const expectedYieldMin = (amountNum * tranche.yieldMin / 100 / 365 * tranche.lockDays)
  const expectedYieldMax = (amountNum * tranche.yieldMax / 100 / 365 * tranche.lockDays)
  const isValid = amountNum >= 1000

  const handleSubmit = async () => {
    if (!isValid) return
    setSubmitting(true)
    setResult(null)
    try {
      const res = await stakeIntoPool({
        provider_id: providerId,
        amount: amountNum,
        tranche: selectedTranche,
      })
      setResult({
        success: true,
        message: `Staked ₹${amountNum.toLocaleString()} into ${tranche.name} tranche. Position: ${res.position_id}`,
      })
      setAmount('')
      onStakeSuccess?.()
    } catch {
      setResult({
        success: false,
        message: 'Stake failed — backend not connected. Try again later.',
      })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      <div className="mb-4">
        <h2 className="text-white font-bold text-base sm:text-lg">Stake Capital</h2>
        <p className="text-slate-400 text-xs mt-0.5">Provide liquidity to the reinsurance pool and earn yield from premium flows</p>
      </div>

      {/* Tranche selector */}
      <div className="mb-4">
        <p className="text-slate-400 text-xs font-medium mb-2 uppercase tracking-wider">Select Tranche</p>
        <div className="grid grid-cols-3 gap-2">
          {TRANCHES.map(t => (
            <button
              key={t.key}
              onClick={() => setSelectedTranche(t.key)}
              className={`rounded-xl p-3 border text-left transition-all ${
                selectedTranche === t.key
                  ? `${t.bg} ${t.border} ring-1 ring-offset-0 ring-offset-slate-800 ring-${t.key === 'senior' ? 'emerald' : t.key === 'mezzanine' ? 'amber' : 'red'}-500/40`
                  : 'bg-slate-900 border-slate-700 hover:border-slate-600'
              }`}
            >
              <p className={`text-sm font-semibold ${selectedTranche === t.key ? t.color : 'text-white'}`}>{t.name}</p>
              <p className="text-slate-500 text-xs mt-0.5">{t.yieldMin}-{t.yieldMax}% APY</p>
              <p className="text-slate-600 text-[10px] mt-0.5">{t.lockDays}d lock</p>
            </button>
          ))}
        </div>
      </div>

      {/* Amount input */}
      <div className="mb-4">
        <label className="text-slate-400 text-xs font-medium mb-2 block uppercase tracking-wider">Amount (INR)</label>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm font-medium">₹</span>
          <input
            type="number"
            min={1000}
            step={1000}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="10,000"
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-7 pr-3 py-2.5 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        {amount && !isValid && (
          <p className="text-red-400 text-xs mt-1.5">Minimum stake: ₹1,000</p>
        )}
      </div>

      {/* Expected yield display */}
      {amountNum > 0 && (
        <div className={`${tranche.bg} border ${tranche.border} rounded-xl p-3 mb-4`}>
          <p className="text-slate-400 text-xs mb-1">Expected Yield ({tranche.lockDays} days)</p>
          <p className={`font-bold text-lg ${tranche.color}`}>
            ₹{expectedYieldMin.toFixed(0)} — ₹{expectedYieldMax.toFixed(0)}
          </p>
          <p className="text-slate-500 text-[10px] mt-1">
            Based on {tranche.yieldMin}-{tranche.yieldMax}% APY for {tranche.lockDays}-day lock period
          </p>
        </div>
      )}

      {/* Lock period warning */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg p-3 mb-4 flex items-start gap-2">
        <svg className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.268 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        <div>
          <p className="text-amber-400 text-xs font-semibold">Lock Period: {tranche.lockDays} Days</p>
          <p className="text-slate-500 text-xs mt-0.5">
            Capital cannot be withdrawn until the lock period expires. Early withdrawal is not supported.
          </p>
        </div>
      </div>

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={!isValid || submitting}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-bold py-3 rounded-lg transition-colors"
      >
        {submitting ? 'Processing...' : `Stake ₹${amountNum > 0 ? amountNum.toLocaleString() : '0'} into ${tranche.name}`}
      </button>

      {/* Result toast */}
      {result && (
        <div className={`mt-3 rounded-lg p-3 text-xs font-medium ${
          result.success
            ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-400'
            : 'bg-red-500/10 border border-red-500/30 text-red-400'
        }`}>
          {result.success ? '✓' : '✗'} {result.message}
        </div>
      )}
    </div>
  )
}
