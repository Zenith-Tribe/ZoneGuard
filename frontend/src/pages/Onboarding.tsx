import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { ZONES } from '../data/mock'
import type { Zone, Exclusion, PremiumBreakdown, RawApiZone } from '../types'
import { getZones, registerRider, createPolicy, calculatePremium } from '../services/api'
import BengaluruZoneMap from '../components/Map/BengaluruZoneMap'
import ExclusionsList from '../components/Policy/ExclusionsList'
import PremiumBreakdownComponent from '../components/Policy/PremiumBreakdown'

type Step = 1 | 2 | 3 | 4

const STANDARD_EXCLUSIONS: Exclusion[] = [
  { id: 'WAR', name: 'War & Armed Conflict', description: 'Disruptions caused by declared war, armed conflict, military action, or invasion.', category: 'standard', check_phase: 'claim_trigger' },
  { id: 'PANDEMIC', name: 'Pandemic / Epidemic', description: 'Zone disruptions attributed to WHO-declared pandemics or government lockdowns.', category: 'standard', check_phase: 'claim_trigger' },
  { id: 'TERRORISM', name: 'Terrorism', description: 'Income loss from disruptions caused by designated terrorist acts.', category: 'standard', check_phase: 'claim_trigger' },
  { id: 'RIDER_MISCONDUCT', name: 'Rider Misconduct', description: 'Deliberately caused disruption or falsified data.', category: 'behavioral', check_phase: 'claim_review' },
  { id: 'VEHICLE_DEFECT', name: 'Vehicle / Equipment Defect', description: 'Income loss due to vehicle breakdown or equipment failure.', category: 'standard', check_phase: 'claim_review' },
  { id: 'PRE_EXISTING_ZONE', name: 'Pre-existing Zone Condition', description: 'Disruptions already active when policy was purchased.', category: 'operational', check_phase: 'claim_trigger' },
  { id: 'SCHEDULED_MAINTENANCE', name: 'Scheduled Maintenance', description: 'Planned infrastructure work announced >48 hours in advance.', category: 'operational', check_phase: 'claim_trigger' },
  { id: 'GRACE_PERIOD_LAPSE', name: 'Grace Period Lapse', description: 'Claims filed during 24-hour grace period after renewal lapse.', category: 'operational', check_phase: 'claim_trigger' },
  { id: 'FRAUD_DETECTED', name: 'Fraud Detected', description: 'Claims flagged by FraudShield with score >0.85.', category: 'behavioral', check_phase: 'claim_review' },
  { id: 'MAX_DAYS_EXCEEDED', name: 'Max Days Exceeded', description: 'Maximum 3 consecutive disruption days per week.', category: 'operational', check_phase: 'claim_trigger' },
]

const tierBadge: Record<string, string> = {
  'low': 'bg-emerald-100 text-emerald-700',
  'medium': 'bg-amber-100 text-amber-700',
  'high': 'bg-orange-100 text-orange-700',
  'flood-prone': 'bg-red-100 text-red-700',
}
const tierLabel: Record<string, string> = {
  'low': 'Low Risk', 'medium': 'Medium Risk', 'high': 'High Risk', 'flood-prone': 'Flood-Prone',
}

export default function OnboardingPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>(1)
  const [riderId, setRiderId] = useState('')
  const [riderName, setRiderName] = useState('')
  const [selectedZoneId, setSelectedZoneId] = useState('')
  const [earnings, setEarnings] = useState('')
  const [zones, setZones] = useState<RawApiZone[]>([])
  const [premiumData, setPremiumData] = useState<PremiumBreakdown | null>(null)
  const [loading, setLoading] = useState(false)
  const [apiAvailable, setApiAvailable] = useState(true)
  const [forwardLock, setForwardLock] = useState(false)
  const [eshramId, setEshramId] = useState('')

  useEffect(() => {
    getZones()
      .then(z => setZones(z))
      .catch(() => {
        setApiAvailable(false)
        setZones(ZONES.map(z => ({
          ...z, pin_code: z.pinCode, risk_tier: z.riskTier, risk_score: z.riskScore,
          weekly_premium: z.weeklyPremium, max_weekly_payout: z.maxWeeklyPayout,
          active_riders: z.activeRiders, historical_disruptions: z.disruptions,
          lat: 0, lng: 0,
        })))
      })
  }, [])

  const normalizedZones = zones.map(z => ({
    id: z.id,
    name: z.name,
    pinCode: z.pin_code || z.pinCode,
    riskTier: (z.risk_tier || z.riskTier) as Zone['riskTier'],
    riskScore: z.risk_score ?? z.riskScore,
    weeklyPremium: z.weekly_premium ?? z.weeklyPremium,
    maxWeeklyPayout: z.max_weekly_payout ?? z.maxWeeklyPayout,
    activeRiders: z.active_riders ?? z.activeRiders,
    disruptions: z.historical_disruptions ?? z.disruptions,
    lat: z.lat || 0,
    lng: z.lng || 0,
  }))

  const selectedZone = normalizedZones.find(z => z.id === selectedZoneId)
  const earningsNum = parseInt(earnings, 10)
  const dailyAvg = earnings && !isNaN(earningsNum) ? Math.round((earningsNum / 7) * 100) / 100 : 0
  const perDayPayout = Math.round(dailyAvg * 0.55 * 100) / 100

  const goBack = () => {
    if (step === 1) navigate('/')
    else setStep((step - 1) as Step)
  }

  const handleZoneSelect = async (zoneId: string) => {
    setSelectedZoneId(zoneId)
    if (apiAvailable) {
      try {
        const pd = await calculatePremium(zoneId)
        setPremiumData(pd)
      } catch { /* fallback to static */ }
    }
  }

  const handleConfirm = async () => {
    setLoading(true)
    try {
      if (apiAvailable) {
        await registerRider({
          rider_id: riderId, name: riderName || 'Rider',
          zone_id: selectedZoneId, weekly_earnings: earningsNum,
          ...(eshramId.length === 12 ? { eshram_id: eshramId } : {}),
        })
        await createPolicy({
          rider_id: riderId, zone_id: selectedZoneId,
          ...(forwardLock ? { is_forward_locked: true, forward_lock_weeks: 4 } : {}),
        })
      }
      localStorage.setItem('zoneguard_rider_id', riderId)
      setStep(4)
    } catch (err: unknown) {
      // If rider already exists, still proceed
      if (err instanceof Error && err.message?.includes('already registered')) {
        try { await createPolicy({ rider_id: riderId, zone_id: selectedZoneId }) } catch { /* ignore duplicate */ }
      }
      localStorage.setItem('zoneguard_rider_id', riderId)
      setStep(4)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#FFFBF3] flex flex-col">
      <header className="bg-white border-b border-amber-100 px-4 py-3 flex items-center gap-3 sticky top-0 z-[1000]">
        <button aria-label="Go back" onClick={goBack} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-amber-50 text-amber-600 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
        </button>
        <div>
          <h1 className="text-stone-800 font-bold text-base">Get Covered in 90 Seconds</h1>
          {step <= 3 && <p className="text-stone-500 text-xs">Step {step} of 3</p>}
        </div>
      </header>

      {step <= 3 && (
        <div className="h-1 bg-amber-100">
          <div className="h-1 bg-amber-500 transition-all duration-500 ease-out" style={{ width: `${(step / 3) * 100}%` }} />
        </div>
      )}

      <main className="flex-1 flex flex-col items-center justify-start px-3 sm:px-4 py-6 sm:py-8">
        <div className="w-full max-w-lg">

          {/* Step 1: Rider ID + Name */}
          {step === 1 && (
            <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
              <div className="text-4xl mb-4">🪪</div>
              <h2 className="text-stone-800 font-bold text-xl mb-1">What's your Rider ID?</h2>
              <p className="text-stone-500 text-sm mb-6 leading-relaxed">
                Find it in your Amazon Flex app under <span className="font-medium text-stone-700">Account → Partner ID</span>
              </p>
              <input type="text" value={riderId} onChange={e => setRiderId(e.target.value.toUpperCase())} placeholder="AMZFLEX-BLR-XXXXX"
                className="w-full border border-amber-200 rounded-xl px-4 py-3 text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-400 font-mono text-sm mb-3" />
              <input type="text" value={riderName} onChange={e => setRiderName(e.target.value)} placeholder="Your Name"
                className="w-full border border-amber-200 rounded-xl px-4 py-3 text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-400 text-sm mb-3" />
              <input type="text" value={eshramId} onChange={e => setEshramId(e.target.value.replace(/\D/g, '').slice(0, 12))} placeholder="e-Shram UAN (optional, 12 digits)"
                className="w-full border border-amber-200 rounded-xl px-4 py-3 text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-400 text-sm font-mono" />
              {eshramId.length > 0 && eshramId.length < 12 && (
                <p className="text-amber-500 text-xs mt-1">{12 - eshramId.length} more digits needed</p>
              )}
              {eshramId.length === 12 && (
                <p className="text-emerald-600 text-xs mt-1 flex items-center gap-1">
                  <span className="inline-block w-3 h-3 bg-emerald-100 rounded-full text-center leading-3 text-emerald-600 text-[8px] font-bold">&#10003;</span>
                  Valid e-Shram UAN format — will verify on confirmation
                </p>
              )}
              <button onClick={() => riderId.trim().length >= 5 && setStep(2)} disabled={riderId.trim().length < 5}
                className="w-full mt-5 bg-amber-500 hover:bg-amber-400 disabled:bg-amber-200 disabled:cursor-not-allowed text-white font-bold py-3 rounded-xl transition-colors">
                Continue
              </button>
            </div>
          )}

          {/* Step 2: Zone selector with Leaflet map */}
          {step === 2 && (
            <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
              <div className="text-4xl mb-4">📍</div>
              <h2 className="text-stone-800 font-bold text-xl mb-1">Select your delivery zone</h2>
              <p className="text-stone-500 text-sm mb-4">Tap a zone on the map or select from the list below</p>

              {/* Leaflet map */}
              <div className="rounded-xl overflow-hidden mb-4 border border-stone-200">
                <BengaluruZoneMap
                  zones={normalizedZones.map(z => ({
                    id: z.id, name: z.name, lat: z.lat, lng: z.lng,
                    riskScore: z.riskScore ?? 0, riskTier: z.riskTier,
                    activeRiders: z.activeRiders ?? 0, weeklyPremium: z.weeklyPremium ?? 0,
                  }))}
                  selectedZoneId={selectedZoneId}
                  onZoneClick={handleZoneSelect}
                  height="200px"
                  mobileHeight="180px"
                />
              </div>

              <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                {normalizedZones.map(zone => (
                  <button key={zone.id} onClick={() => handleZoneSelect(zone.id)}
                    className={`w-full text-left px-4 py-3 rounded-xl border transition-all ${
                      selectedZoneId === zone.id ? 'border-amber-400 bg-amber-50 shadow-sm' : 'border-stone-100 hover:border-amber-200'
                    }`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        {selectedZoneId === zone.id && <div className="w-2 h-2 rounded-full bg-amber-500" />}
                        <span className="text-stone-800 font-medium text-sm">{zone.name}</span>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${tierBadge[zone.riskTier]}`}>₹{zone.weeklyPremium}/wk</span>
                    </div>
                    <p className="text-stone-400 text-xs mt-1 pl-4">{zone.pinCode} · {tierLabel[zone.riskTier]}</p>
                  </button>
                ))}
              </div>

              <button onClick={() => selectedZoneId && setStep(3)} disabled={!selectedZoneId}
                className="w-full mt-5 bg-amber-500 hover:bg-amber-400 disabled:bg-amber-200 disabled:cursor-not-allowed text-white font-bold py-3 rounded-xl transition-colors">
                Continue
              </button>
            </div>
          )}

          {/* Step 3: Earnings + Premium Breakdown + Exclusions */}
          {step === 3 && selectedZone && (
            <div className="space-y-4">
              <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
                <div className="text-4xl mb-4">💰</div>
                <h2 className="text-stone-800 font-bold text-xl mb-1">Your weekly earnings?</h2>
                <p className="text-stone-500 text-sm mb-5">Used to calculate your disruption day payout</p>

                <div className="relative mb-5">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-stone-500 font-medium text-sm">₹</span>
                  <input type="number" value={earnings} onChange={e => setEarnings(e.target.value)} placeholder="15000" min="0"
                    className="w-full border border-amber-200 rounded-xl pl-8 pr-4 py-3 text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-400" />
                </div>

                {/* Quick quote */}
                <div className="bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200 rounded-xl p-4">
                  <p className="text-stone-500 text-xs font-semibold uppercase tracking-wide mb-3">Your Coverage Quote</p>
                  {([
                    ['Zone', selectedZone.name],
                    ['Risk tier', tierLabel[selectedZone.riskTier]],
                    ['Weekly premium', `₹${selectedZone.weeklyPremium}`],
                    ['Max payout/week', `₹${(selectedZone.maxWeeklyPayout ?? 0).toLocaleString()}`],
                    ['Per-day payout', earnings && earningsNum > 0
                      ? `₹${perDayPayout.toLocaleString('en-IN', { maximumFractionDigits: 0 })} (55% of ₹${dailyAvg.toLocaleString('en-IN', { maximumFractionDigits: 0 })} daily avg)`
                      : '— Enter earnings above'],
                  ] as [string, string][]).map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1.5 border-b border-amber-100 last:border-0">
                      <span className="text-stone-500 text-sm">{k}</span>
                      <span className="text-stone-800 font-semibold text-sm">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Forward Premium Lock toggle */}
              <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-stone-800 font-bold text-sm flex items-center gap-2">
                      Forward Premium Lock
                      <span className="text-xs bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-semibold">Save 8%</span>
                    </h3>
                    <p className="text-stone-500 text-xs mt-1">Commit to 4 weeks upfront and save ₹{Math.round((selectedZone.weeklyPremium || 0) * 0.08)}/week</p>
                  </div>
                  <button
                    onClick={() => setForwardLock(!forwardLock)}
                    className={`relative w-12 h-6 rounded-full transition-colors ${forwardLock ? 'bg-emerald-500' : 'bg-stone-200'}`}
                  >
                    <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${forwardLock ? 'translate-x-6' : 'translate-x-0.5'}`} />
                  </button>
                </div>
                {forwardLock && (
                  <div className="mt-3 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
                    <div className="flex justify-between text-sm">
                      <span className="text-stone-500">Regular</span>
                      <span className="text-stone-400 line-through">₹{selectedZone.weeklyPremium}/wk</span>
                    </div>
                    <div className="flex justify-between text-sm font-bold">
                      <span className="text-emerald-700">Locked price</span>
                      <span className="text-emerald-700">₹{Math.round((selectedZone.weeklyPremium || 0) * 0.92)}/wk</span>
                    </div>
                    <p className="text-emerald-600 text-xs mt-1">Total savings: ₹{Math.round((selectedZone.weeklyPremium || 0) * 0.08) * 4} over 4 weeks</p>
                  </div>
                )}
              </div>

              {/* Premium Breakdown (if API available) */}
              {premiumData && <PremiumBreakdownComponent data={premiumData} />}

              {/* Exclusions - "What's NOT covered" */}
              <ExclusionsList exclusions={STANDARD_EXCLUSIONS} compact />

              <button onClick={handleConfirm} disabled={loading}
                className="w-full bg-amber-500 hover:bg-amber-400 disabled:bg-amber-300 text-white font-bold py-3 rounded-xl transition-colors">
                {loading ? 'Activating coverage...' : 'Confirm & Activate Coverage →'}
              </button>
            </div>
          )}

          {/* Step 4: Success */}
          {step === 4 && !selectedZone && (
            <div className="bg-white rounded-2xl border border-amber-200 shadow-sm p-6 sm:p-8 text-center">
              <p className="text-stone-600 mb-4">No zone selected. Please complete onboarding from Step 1.</p>
              <button onClick={() => setStep(1)} className="px-6 py-2 bg-stone-800 text-white rounded-full text-sm font-semibold hover:bg-stone-700 transition-colors">
                Start Over
              </button>
            </div>
          )}
          {step === 4 && selectedZone && (
            <div className="bg-white rounded-2xl border border-emerald-200 shadow-sm p-6 sm:p-8 text-center">
              <div className="w-16 h-16 bg-emerald-100 rounded-full flex items-center justify-center mx-auto mb-5">
                <svg className="w-8 h-8 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <h2 className="text-stone-800 font-bold text-2xl mb-1">You're covered!</h2>
              <p className="text-stone-500 text-sm mb-1">{selectedZone.name} · ₹{selectedZone.weeklyPremium}/week</p>
              <div className="inline-flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1 mb-6">
                <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-emerald-700 text-xs font-semibold">Active now</span>
              </div>

              <p className="text-stone-500 text-sm leading-relaxed mb-2">If all 4 signals converge in your zone,</p>
              <p className="text-stone-800 font-bold text-lg mb-1">₹{(selectedZone.maxWeeklyPayout ?? 0).toLocaleString()} lands in your UPI</p>
              <p className="text-stone-400 text-sm mb-6">automatically — within 2 hours. No claim needed.</p>

              <div className="bg-stone-50 border border-stone-100 rounded-xl p-4 text-left mb-4">
                <p className="text-stone-600 text-xs font-semibold mb-2">What you're protected against</p>
                {['Flash floods & heavy rainfall (>65mm/hr)', 'Severe air pollution (AQI >300)', 'Zone curfews & transport strikes', 'NDMA-declared flood alerts'].map(item => (
                  <div key={item} className="flex items-start gap-2 py-1">
                    <span className="text-emerald-500 text-xs mt-0.5">✓</span>
                    <span className="text-stone-600 text-xs">{item}</span>
                  </div>
                ))}
              </div>

              <ExclusionsList exclusions={STANDARD_EXCLUSIONS} compact />

              <button onClick={() => navigate('/rider')} className="w-full mt-4 bg-amber-500 hover:bg-amber-400 text-white font-bold py-3 rounded-xl transition-colors">
                View My Dashboard
              </button>
              <button onClick={() => navigate('/')} className="w-full mt-2 text-stone-400 hover:text-stone-600 text-sm transition-colors py-2">Back to home</button>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
