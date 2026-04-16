import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getPolicies, getPolicyExclusions, calculatePremium, renewPolicy, cancelPolicy, activateForwardLock } from '../services/api'
import PolicyCard from '../components/Policy/PolicyCard'
import ExclusionsList from '../components/Policy/ExclusionsList'
import PremiumBreakdown from '../components/Policy/PremiumBreakdown'
import type { PolicyData, Exclusion, PremiumBreakdown as PremiumBreakdownType } from '../types'

const FALLBACK_EXCLUSIONS: Exclusion[] = [
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

export default function PolicyPage() {
  const navigate = useNavigate()
  const [policy, setPolicy] = useState<PolicyData | null>(null)
  const [exclusions, setExclusions] = useState<Exclusion[]>(FALLBACK_EXCLUSIONS)
  const [premiumData, setPremiumData] = useState<PremiumBreakdownType | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [lockResult, setLockResult] = useState<{ savings_per_week: number; total_savings: number } | null>(null)

  useEffect(() => {
    const init = async () => {
      try {
        const policies = await getPolicies('AMZFLEX-BLR-04821')
        if (policies.length > 0) {
          setPolicy(policies[0])

          try {
            const excl = await getPolicyExclusions(policies[0].id)
            if (excl.length > 0) setExclusions(excl)
          } catch { /* use fallback */ }

          try {
            const pd = await calculatePremium(policies[0].zone_id, policies[0].rider_id)
            setPremiumData(pd)
          } catch { /* ignore */ }
        }
      } catch {
        // Fallback: show demo policy
        setPolicy({
          id: 'POL-DEMO0001',
          rider_id: 'AMZFLEX-BLR-04821',
          zone_id: 'hsr',
          status: 'active',
          weekly_premium: 49,
          max_payout: 2200,
          coverage_start: new Date(Date.now() - 2 * 86400000).toISOString(),
          coverage_end: new Date(Date.now() + 5 * 86400000).toISOString(),
          is_forward_locked: false,
          forward_lock_weeks: 0,
          created_at: new Date().toISOString(),
        })
      } finally {
        setLoading(false)
      }
    }
    init()
  }, [])

  const handleRenew = async () => {
    if (!policy) return
    setActionLoading(true)
    try {
      const result = await renewPolicy(policy.id)
      if (result.new_policy) setPolicy(result.new_policy)
    } catch { /* ignore */ }
    setActionLoading(false)
  }

  const handleCancel = async () => {
    if (!policy) return
    setActionLoading(true)
    try {
      await cancelPolicy(policy.id)
      setPolicy(prev => prev ? { ...prev, status: 'cancelled' } : null)
    } catch { /* ignore */ }
    setActionLoading(false)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-[#FFFBF3] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-amber-200 border-t-amber-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#FFFBF3]">
      <header className="bg-white border-b border-amber-100 px-4 py-3 flex items-center gap-3 sticky top-0 z-[1000] shadow-sm">
        <button aria-label="Go back" onClick={() => navigate('/rider')} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-amber-50 text-amber-600 transition-colors">
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
        </button>
        <div>
          <h1 className="text-stone-800 font-bold text-base">Policy Details</h1>
          <p className="text-stone-500 text-xs">{policy?.id}</p>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4 sm:space-y-5">
        {/* Policy Card */}
        {policy && (
          <PolicyCard
            policy={policy}
            zoneName="HSR Layout"
            onRenew={policy.status === 'active' ? handleRenew : undefined}
            onCancel={policy.status === 'active' ? handleCancel : undefined}
          />
        )}

        {actionLoading && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-center">
            <p className="text-amber-700 text-sm">Processing...</p>
          </div>
        )}

        {/* Coverage terms */}
        <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
          <h2 className="text-stone-800 font-bold text-base sm:text-lg mb-3 sm:mb-4">Coverage Terms</h2>
          <div className="space-y-2 sm:space-y-3">
            {[
              ['Payout calculation', '55% of 7-day average daily earnings'],
              ['Max consecutive days', '3 disruption days per week'],
              ['Minimum disruption', '4 continuous hours (6am–10pm window)'],
              ['Environmental triggers', 'No waiting period'],
              ['Social triggers', '24-hour waiting period'],
              ['NDMA flood alerts', 'Pre-validated Signal 1 — no further confirmation needed'],
              ['Income cap', '7-day rolling average baseline (never theoretical max)'],
            ].map(([label, value]) => (
              <div key={label} className="flex flex-col sm:flex-row sm:justify-between py-2 border-b border-stone-50 last:border-0 gap-0.5 sm:gap-2">
                <span className="text-stone-500 text-sm">{label}</span>
                <span className="text-stone-800 font-medium text-sm sm:text-right sm:max-w-[60%]">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Premium Breakdown */}
        {premiumData && <PremiumBreakdown data={premiumData} />}

        {/* Forward Premium Lock */}
        <div className="bg-gradient-to-br from-blue-50 to-indigo-50 border border-blue-200 rounded-2xl p-4 sm:p-6">
          <div className="flex items-center gap-3 mb-3">
            <span className="text-2xl">🔒</span>
            <div>
              <h3 className="text-stone-800 font-bold text-sm sm:text-base">Forward Premium Lock</h3>
              <p className="text-stone-500 text-xs">Commit to 4 weeks, save 8% on every premium</p>
            </div>
          </div>
          <div className="bg-white/60 rounded-xl p-3 mb-3">
            <div className="flex justify-between text-sm">
              <span className="text-stone-500">Regular weekly</span>
              <span className="text-stone-800 font-medium">₹{policy?.weekly_premium || 49}</span>
            </div>
            <div className="flex justify-between text-sm mt-1">
              <span className="text-stone-500">With Forward Lock</span>
              <span className="text-emerald-700 font-bold">₹{Math.round((policy?.weekly_premium || 49) * 0.92)}/wk</span>
            </div>
            <div className="flex justify-between text-sm mt-1">
              <span className="text-stone-500">4-week savings</span>
              <span className="text-emerald-600 font-medium">₹{Math.round((policy?.weekly_premium || 49) * 0.08 * 4)}</span>
            </div>
          </div>
          {policy?.is_forward_locked ? (
            <div className="flex items-center gap-2 mt-2">
              <span className="inline-flex items-center gap-1 bg-emerald-100 text-emerald-700 text-xs font-bold px-3 py-1 rounded-full">
                <span>&#10003;</span> Locked — {policy.forward_lock_weeks} weeks remaining
              </span>
            </div>
          ) : (
            <button
              onClick={async () => {
                if (!policy) return
                setActionLoading(true)
                try {
                  const res = await activateForwardLock(policy.id)
                  setLockResult({ savings_per_week: res.savings_per_week, total_savings: res.total_savings })
                  setPolicy({ ...policy, is_forward_locked: true, forward_lock_weeks: 4, weekly_premium: res.weekly_premium })
                } catch { /* ignore */ }
                setActionLoading(false)
              }}
              disabled={actionLoading || policy?.status !== 'active'}
              className="mt-2 w-full bg-blue-600 hover:bg-blue-500 disabled:bg-blue-300 text-white font-bold py-2.5 rounded-xl text-sm transition-colors"
            >
              {actionLoading ? 'Locking...' : 'Activate Forward Lock — Save 8%'}
            </button>
          )}
          {lockResult && (
            <p className="text-emerald-600 text-xs mt-2 font-medium">
              Saved ₹{lockResult.savings_per_week}/week · ₹{lockResult.total_savings} total over 4 weeks
            </p>
          )}
          <p className="text-stone-400 text-xs mt-2">Actuarial innovation: predictable premium pool reduces loss ratio volatility</p>
        </div>

        {/* Exclusions */}
        <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4 sm:p-6">
          <h2 className="text-stone-800 font-bold text-base sm:text-lg mb-1">Coverage Exclusions</h2>
          <p className="text-stone-500 text-xs mb-3 sm:mb-4">10 standard exclusions attached to every policy</p>
          <ExclusionsList exclusions={exclusions} />
        </div>

        <div className="text-center pb-4">
          <p className="text-stone-400 text-xs">
            ZoneGuard v2.0 · Guidewire DEVTrails 2026 · IRDAI parametric sandbox
          </p>
        </div>
      </main>
    </div>
  )
}
