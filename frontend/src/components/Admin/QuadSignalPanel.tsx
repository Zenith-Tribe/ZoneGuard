import { useState, useEffect, useRef } from 'react'
import type { Signal, ConfidenceLevel } from '../../types'
import { QUAD_SIGNALS } from '../../data/mock'

const DEMO_STEPS = [
  { idx: 0, value: 'Rainfall: 71mm/hr ⚡', delay: 0 },
  { idx: 1, value: 'Mobility: 18% of baseline ⚡', delay: 1800 },
  { idx: 2, value: 'AI: Acoustic rainfall verified (Voice Note) 🎤', delay: 3400 },
  { idx: 3, value: 'H3 Hex: Hyper-local match (Res 8) ✅', delay: 5000 },
]

const getConfidence = (fired: number): ConfidenceLevel =>
  fired === 4 ? 'HIGH' : fired === 3 ? 'MEDIUM' : fired === 2 ? 'LOW' : 'NOISE'

const confidenceConfig: Record<ConfidenceLevel, { bg: string; border: string; text: string; label: string }> = {
  HIGH:   { bg: 'bg-emerald-500/10', border: 'border-emerald-500/50', text: 'text-emerald-400', label: 'Automatic payout initiating: H3 Hex Verified' },
  MEDIUM: { bg: 'bg-amber-500/10',   border: 'border-amber-500/50',   text: 'text-amber-400',   label: '1-hour recheck scheduled' },
  LOW:    { bg: 'bg-orange-500/10',  border: 'border-orange-500/50',  text: 'text-orange-400',  label: 'Flagged for human review' },
  NOISE:  { bg: 'bg-slate-700/50',   border: 'border-slate-600',      text: 'text-slate-400',   label: 'Monitoring — no action' },
}

export default function QuadSignalPanel() {
  const [signals, setSignals] = useState<Signal[]>(() => QUAD_SIGNALS.map(s => ({ ...s })))
  const [isDemoRunning, setIsDemoRunning] = useState(false)
  const [payoutFired, setPayoutFired] = useState(false)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  const firedCount = signals.filter(s => s.status === 'firing').length
  const confidence = getConfidence(firedCount)
  const cfg = confidenceConfig[confidence]

  const runDemo = () => {
    if (isDemoRunning) return
    timers.current.forEach(clearTimeout)
    timers.current = []
    setSignals(QUAD_SIGNALS.map(s => ({ ...s, status: 'inactive' as const })))
    setPayoutFired(false)
    setIsDemoRunning(true)

    DEMO_STEPS.forEach(({ idx, value, delay }) => {
      const t = setTimeout(() => {
        setSignals(prev => prev.map((s, i) =>
          i === idx ? { ...s, status: 'firing' as const, value } : s
        ))
      }, delay)
      timers.current.push(t)
    })

    const payoutTimer = setTimeout(() => {
      setPayoutFired(true)
      setIsDemoRunning(false)
    }, 7000)
    timers.current.push(payoutTimer)
  }

  const reset = () => {
    timers.current.forEach(clearTimeout)
    timers.current = []
    setSignals(QUAD_SIGNALS.map(s => ({ ...s })))
    setPayoutFired(false)
    setIsDemoRunning(false)
  }

  useEffect(() => () => { timers.current.forEach(clearTimeout) }, [])

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3 sm:gap-0 mb-4 sm:mb-5">
        <div>
          <h2 className="text-white font-bold text-base sm:text-lg">QuadSignal Fusion (Phase 3)</h2>
          <p className="text-slate-400 text-xs">HSR Layout · H3 Res-8 Hyper-local Grids Active</p>
        </div>
        <div className="flex gap-2">
          {!isDemoRunning && !payoutFired && (
            <button
              onClick={runDemo}
              className="bg-amber-500 hover:bg-amber-400 text-white font-bold text-xs px-3 sm:px-4 py-2 rounded-lg transition-colors shadow-lg shadow-amber-500/20"
            >
              ▶ TRIGGER DEMO
            </button>
          )}
          {(isDemoRunning || payoutFired) && (
            <button
              onClick={reset}
              className="bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs px-3 sm:px-4 py-2 rounded-lg transition-colors"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      {/* Signal cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 mb-4">
        {signals.map((sig) => (
          <div
            key={sig.id}
            className={`rounded-xl border p-3 transition-all duration-700 ${
              sig.status === 'firing'
                ? 'bg-amber-500/10 border-amber-500/60 shadow-lg shadow-amber-500/10'
                : 'bg-slate-900 border-slate-700'
            }`}
          >
            <div className="flex items-center justify-between mb-1.5 sm:mb-2">
              <span className="text-slate-400 text-xs font-bold tracking-wide">{sig.id}</span>
              <div className={`w-2.5 h-2.5 rounded-full transition-colors duration-500 ${
                sig.status === 'firing' ? 'bg-amber-400 animate-pulse' : 'bg-slate-600'
              }`} />
            </div>
            <p className={`font-semibold text-sm mb-0.5 transition-colors duration-500 ${
              sig.status === 'firing' ? 'text-amber-300' : 'text-white'
            }`}>
              {sig.name}
            </p>
            <p className="text-slate-500 text-xs mb-1.5 sm:mb-2 line-clamp-2">{sig.description}</p>
            <div className="border-t border-slate-700/50 pt-1.5 sm:pt-2">
              <p className={`text-xs transition-colors duration-500 truncate ${
                sig.status === 'firing' ? 'text-amber-400 font-medium' : 'text-slate-400'
              }`}>
                {sig.value}
              </p>
              <p className="text-slate-600 text-xs truncate">Threshold: {sig.threshold}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Confidence indicator */}
      <div className={`border rounded-xl px-3 sm:px-4 py-2.5 sm:py-3 flex items-center justify-between transition-all duration-700 ${cfg.bg} ${cfg.border}`}>
        <div className="min-w-0 flex-1">
          <p className={`font-bold text-sm ${cfg.text}`}>
            {firedCount}/4 signals · Confidence: {confidence}
          </p>
          <p className={`text-xs mt-0.5 opacity-70 ${cfg.text} truncate`}>{cfg.label}</p>
        </div>
        <span className="text-xl sm:text-2xl flex-shrink-0 ml-2">
          {firedCount === 4 ? '⚡' : firedCount >= 3 ? '⚠️' : firedCount >= 2 ? '🔍' : '📡'}
        </span>
      </div>

      {/* AUTO-PAYOUT banner */}
      {payoutFired && (
        <div className="mt-4 bg-emerald-500/15 border border-emerald-400/60 rounded-xl p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-0">
          <div className="min-w-0">
            <p className="text-emerald-400 font-bold text-sm">⚡ AUTO-PAYOUT TRIGGERED (HSR HEX MATCH)</p>
            <p className="text-emerald-300 text-xs mt-1 line-clamp-2 sm:line-clamp-none">
              142 riders · HSR Layout · ₹1,430 each · Total: ₹2,03,060 · Disbursing via UPI...
            </p>
          </div>
          <div className="text-left sm:text-right flex-shrink-0">
            <p className="text-emerald-400 font-bold text-lg">₹2.03L</p>
            <p className="text-emerald-500 text-xs">Phase 3: Disbursed</p>
          </div>
        </div>
      )}

      {/* Demo running indicator */}
      {isDemoRunning && (
        <div className="mt-3 flex items-center gap-2 text-amber-400 text-xs">
          <div className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
          Phase 3 Analysis: Signals firing & AI Evidence converging...
        </div>
      )}
    </div>
  )
}
