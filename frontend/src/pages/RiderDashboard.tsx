import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { RIDER, RAVI_WEEK, PAYOUTS, ZONES } from '../data/mock'
import { getRider, getPolicies, getPayouts, getZoneSignals, getZones } from '../services/api'
import WeekTimeline from '../components/Rider/WeekTimeline'
import PolicyCard from '../components/Policy/PolicyCard'
import CoverageCard from '../components/Rider/CoverageCard'
import BengaluruZoneMap from '../components/Map/BengaluruZoneMap'
import { QuadSignalWidget } from '../components/Signals'
import NotificationBell from '../components/Notifications/NotificationBell'
import { useNotifications } from '../hooks/useNotifications'
import type { PolicyData, ZoneSignalData, RawApiZone, RawApiPayout } from '../types'

export default function RiderDashboard() {
  const navigate = useNavigate()
  const [rider, setRider] = useState<typeof RIDER>(RIDER)
  const [policy, setPolicy] = useState<PolicyData | null>(null)
  const [payouts, setPayouts] = useState(PAYOUTS)
  const [signalData, setSignalData] = useState<ZoneSignalData | null>(null)
  const [zones, setZones] = useState<RawApiZone[]>([])
  const [currentZoneId, setCurrentZoneId] = useState<string>('hsr')
  const [loading, setLoading] = useState(true)
  const { fetchNotifications } = useNotifications()

  useEffect(() => {
    const storedRiderId = localStorage.getItem('zoneguard_rider_id') || 'AMZFLEX-BLR-04821'

    const init = async () => {
      try {
        const r = await getRider(storedRiderId)
        const zoneId = r.zone_id || 'hsr'
        setCurrentZoneId(zoneId)
        setRider({ ...RIDER, name: r.name, riderId: r.id, zone: ZONES[0], weeklyEarningsBaseline: r.weekly_earnings_baseline ?? RIDER.weeklyEarningsBaseline, tenureWeeks: r.tenure_weeks ?? RIDER.tenureWeeks })

        const policies = await getPolicies(r.id)
        if (policies.length > 0) {
          setPolicy(policies[0])
        }

        const p = await getPayouts(r.id)
        if (p.length > 0) {
          setPayouts(p.map((pay: RawApiPayout) => ({
            id: pay.id, date: pay.created_at?.split('T')[0] || '', amount: pay.amount,
            zone: 'HSR Layout', trigger: 'Auto-payout', confidence: 'HIGH' as const, upiRef: pay.upi_ref || '',
          })))
        }

        const z = await getZones()
        setZones(z)

        const signals = await getZoneSignals(r.zone_id || 'hsr')
        setSignalData(signals)

        fetchNotifications(storedRiderId)
      } catch {
        // Fallback to mock data
      } finally {
        setLoading(false)
      }
    }
    init()

    // Poll notifications every 15s for live demo updates
    const interval = setInterval(() => fetchNotifications(storedRiderId), 15000)
    return () => clearInterval(interval)
  }, [])

  const totalEarned = RAVI_WEEK.reduce((s, d) => s + d.earnings, 0)
  const totalPayout = RAVI_WEEK.reduce((s, d) => s + (d.payoutAmount ?? 0), 0)

  const mapZones = (zones.length > 0 ? zones : ZONES as RawApiZone[]).map((z) => ({
    id: z.id, name: z.name, lat: z.lat || 12.9716, lng: z.lng || 77.5946,
    riskScore: z.risk_score ?? z.riskScore ?? 50, riskTier: z.risk_tier || z.riskTier || 'medium',
    activeRiders: z.active_riders ?? z.activeRiders ?? 0, weeklyPremium: z.weekly_premium ?? z.weeklyPremium ?? 49,
  }))

  return (
    <div className="min-h-screen bg-[#FFFBF3]">
      <header className="bg-white border-b border-amber-100 px-4 py-3 flex items-center justify-between sticky top-0 z-[1000] shadow-sm">
        <div className="flex items-center gap-3">
          <button aria-label="Go back" onClick={() => navigate('/')} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-amber-50 text-amber-600 transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
          </button>
          <div>
            <h1 className="text-stone-800 font-bold text-base leading-tight">{rider.name}</h1>
            <p className="text-stone-500 text-xs">{rider.riderId}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <NotificationBell />
          <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-emerald-700 text-xs font-semibold">Covered</span>
          </div>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4">
        {/* Policy card (API) or Coverage card (mock) */}
        {loading ? (
          <div className="bg-white rounded-2xl border border-amber-100 p-6 animate-pulse">
            <div className="h-4 bg-amber-100 rounded w-1/3 mb-3" />
            <div className="h-3 bg-amber-50 rounded w-2/3 mb-2" />
            <div className="h-3 bg-amber-50 rounded w-1/2" />
          </div>
        ) : policy ? (
          <PolicyCard policy={policy} zoneName={rider.zone?.name || 'HSR Layout'} />
        ) : (
          <CoverageCard zone={rider.zone} premiumPaid={rider.zone.weeklyPremium} maxPayout={rider.zone.maxWeeklyPayout} isActive={rider.coverageActive} />
        )}

        {/* Summary strip */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            { label: 'Earned this week', value: `₹${totalEarned.toLocaleString()}`, highlight: false },
            { label: 'ZG paid out', value: `₹${totalPayout.toLocaleString()}`, highlight: true },
            { label: 'Total income', value: `₹${(totalEarned + totalPayout).toLocaleString()}`, highlight: false },
          ].map(({ label, value, highlight }) => (
            <div key={label} className={`rounded-xl p-3 text-center border ${highlight ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-amber-100'}`}>
              <p className={`font-bold text-sm ${highlight ? 'text-emerald-700' : 'text-stone-800'}`}>{value}</p>
              <p className="text-stone-500 text-xs mt-0.5 leading-tight">{label}</p>
            </div>
          ))}
        </div>

        {/* Mini zone map */}
        <div className="bg-white rounded-2xl border border-amber-100 shadow-sm overflow-hidden">
          <div className="px-4 pt-4 pb-2">
            <h2 className="text-stone-800 font-bold text-sm">Your Zone</h2>
            <p className="text-stone-500 text-xs">{rider.zone?.name || 'HSR Layout'}</p>
          </div>
          <BengaluruZoneMap
            zones={mapZones}
            selectedZoneId={rider.zone?.id || 'hsr'}
            height="180px"
            mobileHeight="160px"
            showPopups={false}
          />
        </div>

        {/* QuadSignal Widget - Live signal status visualization */}
        <QuadSignalWidget
          zoneId={currentZoneId}
          initialData={signalData}
          refreshInterval={30000}
        />

        {/* Week timeline */}
        <WeekTimeline week={RAVI_WEEK} />

        {/* Payout history */}
        <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
          <h2 className="text-stone-800 font-bold text-base sm:text-lg mb-3 sm:mb-4">Payout History</h2>
          <div className="space-y-2.5">
            {payouts.map((p, i) => (
              <div key={p.id} className={`flex items-center justify-between p-3 sm:p-3.5 rounded-xl border ${i === 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-stone-50 border-stone-100'}`}>
                <div className="min-w-0 flex-1">
                  <p className="text-stone-800 font-semibold text-sm truncate">{p.trigger}</p>
                  <p className="text-stone-500 text-xs mt-0.5 truncate">{p.date} · Ref: {p.upiRef}</p>
                </div>
                <div className="text-right ml-3 flex-shrink-0">
                  <p className={`font-bold text-sm ${i === 0 ? 'text-emerald-600' : 'text-stone-700'}`}>+₹{p.amount.toLocaleString()}</p>
                  <span className={`text-xs px-1.5 py-0.5 rounded-full ${p.confidence === 'HIGH' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{p.confidence}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="text-center pb-4">
          <p className="text-stone-400 text-xs">
            Member for {rider.tenureWeeks} weeks · {rider.zone?.name || 'HSR Layout'} zone · ZoneGuard v2.0 · Guidewire DEVTrails 2026
          </p>
        </div>
      </main>
    </div>
  )
}
