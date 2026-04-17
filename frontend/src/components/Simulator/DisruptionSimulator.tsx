import { useState, useEffect } from 'react'
import { triggerSimulation, getScenarios } from '../../services/api'
import type { SimulationResult } from '../../types'

interface Props {
  zones: { id: string; name: string }[]
  onSimulationTriggered?: (result: SimulationResult) => void
}

const FALLBACK_SCENARIOS = [
  { id: 'flash_flood', name: 'Flash Flood', icon: '🌊', desc: 'Heavy rainfall >82mm/hr, flooding' },
  { id: 'severe_aqi', name: 'Severe AQI', icon: '🏭', desc: 'AQI >420, hazardous air quality' },
  { id: 'transport_strike', name: 'Transport Strike', icon: '🚫', desc: 'Zone-wide transport shutdown' },
  { id: 'heat_wave', name: 'Heat Wave', icon: '🔥', desc: 'Temperature >46°C, heat advisory' },
]

const SCENARIO_ICONS: Record<string, string> = {
  flash_flood: '🌊', severe_aqi: '🏭', transport_strike: '🚫', heat_wave: '🔥',
}

export default function DisruptionSimulator({ zones, onSimulationTriggered }: Props) {
  const [zoneId, setZoneId] = useState(zones[0]?.id || '')
  const [scenario, setScenario] = useState('flash_flood')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SimulationResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scenarios, setScenarios] = useState(FALLBACK_SCENARIOS)

  // Update zoneId when zones prop loads asynchronously
  useEffect(() => {
    if (zones.length > 0 && !zoneId) setZoneId(zones[0].id)
  }, [zones])

  useEffect(() => {
    getScenarios()
      .then((data) => {
        const mapped = Object.entries(data).map(([id, s]) => ({
          id,
          name: s.name,
          icon: SCENARIO_ICONS[id] || '⚡',
          desc: s.description,
        }))
        if (mapped.length > 0) setScenarios(mapped)
      })
      .catch(() => { /* keep fallback */ })
  }, [])

  const handleTrigger = async () => {
    if (!zoneId) { setError('Select a zone first'); return }
    setLoading(true)
    setResult(null)
    setError(null)
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 30000)
      const res = await triggerSimulation(zoneId, scenario)
      clearTimeout(timeout)
      setResult(res)
      onSimulationTriggered?.(res)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Simulation failed'
      setError(msg.includes('abort') ? 'Request timed out — Railway may be slow. Try again.' : msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3 sm:mb-4">
        <div>
          <h2 className="text-white font-bold text-base sm:text-lg">Disruption Simulator</h2>
          <p className="text-slate-400 text-xs">Trigger a simulated disruption to demo the full pipeline</p>
        </div>
        <span className="text-xl sm:text-2xl">🎯</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
        {/* Zone selector */}
        <div>
          <label className="text-slate-400 text-xs block mb-1">Zone</label>
          <select
            value={zoneId}
            onChange={e => setZoneId(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
          >
            {zones.map(z => (
              <option key={z.id} value={z.id}>{z.name}</option>
            ))}
          </select>
        </div>

        {/* Scenario selector */}
        <div>
          <label className="text-slate-400 text-xs block mb-1">Scenario</label>
          <select
            value={scenario}
            onChange={e => setScenario(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
          >
            {scenarios.map(s => (
              <option key={s.id} value={s.id}>{s.icon} {s.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Scenario description */}
      <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 mb-4">
        <p className="text-slate-300 text-xs">
          {scenarios.find(s => s.id === scenario)?.icon}{' '}
          {scenarios.find(s => s.id === scenario)?.desc}
        </p>
      </div>

      {/* Trigger button */}
      <button
        onClick={handleTrigger}
        disabled={loading}
        className="w-full bg-red-600 hover:bg-red-500 disabled:bg-red-800 disabled:cursor-wait text-white font-bold py-3 rounded-xl transition-colors shadow-lg shadow-red-500/20"
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Triggering disruption...
          </span>
        ) : (
          '⚡ TRIGGER DISRUPTION'
        )}
      </button>

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-3">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="mt-4 space-y-3">
          <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-xl p-3 sm:p-4">
            <p className="text-emerald-400 font-bold text-sm mb-2">
              Disruption triggered in {result.zone.name}
            </p>
            <div className="grid grid-cols-3 gap-1.5 sm:gap-2 text-xs">
              <div className="bg-slate-900 rounded-lg p-2 text-center">
                <p className="text-white font-bold">{result.fusion.signals_fired}/4</p>
                <p className="text-slate-400">Signals</p>
              </div>
              <div className="bg-slate-900 rounded-lg p-2 text-center">
                <p className="text-white font-bold">{result.claims_created}</p>
                <p className="text-slate-400">Claims</p>
              </div>
              <div className="bg-slate-900 rounded-lg p-2 text-center">
                <p className="text-white font-bold">{result.payouts_created}</p>
                <p className="text-slate-400">Payouts</p>
              </div>
            </div>
            <p className="text-emerald-300 text-xs mt-2">
              Confidence: {result.fusion.confidence} · {result.scenario}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
