import { useState, useEffect, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ZONES, KPIS, CLAIMS_QUEUE } from '../data/mock'
import { getZones, getKPIs, getAdminClaims, reviewClaim, getZoneSignals, getClaimAuditReport, trainFederatedModel, getTemporalAnalysis } from '../services/api'
import KPIStrip from '../components/Admin/KPIStrip'
import QuadSignalPanel from '../components/Admin/QuadSignalPanel'
import BengaluruZoneMap from '../components/Map/BengaluruZoneMap'
import DisruptionSimulator from '../components/Simulator/DisruptionSimulator'
import ClaimsChart from '../components/Admin/ClaimsChart'
import PayoutChart from '../components/Admin/PayoutChart'
import LossRatioWidget from '../components/Admin/LossRatioWidget'
import { ClaimSkeleton } from '../components/shared/Skeleton'
import DemoTour from '../components/shared/DemoTour'
import type { KPI, ZoneSignalData, SimulationResult, RawApiZone, RawApiClaim } from '../types'

export default function AdminDashboard() {
  const navigate = useNavigate()
  const [zones, setZones] = useState<RawApiZone[]>([])
  const [kpis, setKPIs] = useState<KPI[]>(KPIS)
  const [claims, setClaims] = useState<RawApiClaim[]>(CLAIMS_QUEUE as RawApiClaim[])
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null)
  const [signalData, setSignalData] = useState<Record<string, ZoneSignalData>>({})
  const [apiAvailable, setApiAvailable] = useState(false)
  const [expandedClaim, setExpandedClaim] = useState<string | null>(null)
  const [claimStatuses, setClaimStatuses] = useState<Record<string, string>>({})
  const [claimSearch, setClaimSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [claimsLoading, setClaimsLoading] = useState(true)
  const [auditReports, setAuditReports] = useState<Record<string, string>>({})
  const [flTraining, setFlTraining] = useState(false)
  const [flResult, setFlResult] = useState<{ rounds_completed?: number; convergence_history?: number[]; per_client_stats?: Record<string, { zone_ids: string[]; training_samples: number }>; error?: string } | null>(null)
  const [temporalData, setTemporalData] = useState<Record<string, unknown> | null>(null)
  const [temporalLoading, setTemporalLoading] = useState(false)

  useEffect(() => {
    const init = async () => {
      try {
        const z = await getZones()
        setZones(z)
        setApiAvailable(true)

        try {
          const kpiData = await getKPIs()
          if (kpiData.kpis) setKPIs(kpiData.kpis)
        } catch { /* KPIs fallback to mock */ }

        try {
          const c = await getAdminClaims({ per_page: 50 })
          if (c.items && c.items.length > 0) {
            setClaims(c.items.map((claim) => ({
              id: claim.id, zone: claim.zone_id, zone_id: claim.zone_id, rider_id: claim.rider_id,
              date: claim.created_at?.split('T')[0] || '', confidence: claim.confidence,
              signals: 3, recommendedPayout: claim.recommended_payout, recommended_payout: claim.recommended_payout,
              auditSummary: '', status: claim.status,
              exclusion_check: claim.exclusion_check, fraud_score: claim.fraud_score,
            })))
          }
        } catch { /* Claims fallback to mock */ }
      } catch {
        setApiAvailable(false)
        setZones(ZONES as RawApiZone[])
      } finally {
        setClaimsLoading(false)
      }
    }
    init()
  }, [])

  const normalizedZones = zones.map((z) => ({
    id: z.id, name: z.name, lat: z.lat || 12.9716, lng: z.lng || 77.5946,
    riskScore: z.risk_score ?? z.riskScore ?? 50, riskTier: z.risk_tier || z.riskTier || 'medium',
    activeRiders: z.active_riders ?? z.activeRiders ?? 0, weeklyPremium: z.weekly_premium ?? z.weeklyPremium ?? 49,
  }))

  const selectedZone = normalizedZones.find(z => z.id === selectedZoneId)

  const handleZoneClick = async (zoneId: string) => {
    setSelectedZoneId(zoneId === selectedZoneId ? null : zoneId)
    if (apiAvailable && !signalData[zoneId]) {
      try {
        const signals = await getZoneSignals(zoneId)
        setSignalData(prev => ({ ...prev, [zoneId]: signals }))
      } catch { /* ignore */ }
    }
  }

  const handleSimulation = useCallback(async (result: SimulationResult) => {
    // Refresh signals for the affected zone
    if (result.signals) {
      setSignalData(prev => ({ ...prev, [result.zone.id]: result.signals }))
    }

    // Refresh claims
    if (result.claims?.length > 0) {
      setClaims(prev => [
        ...result.claims.map((c) => ({
          id: c.id, zone: result.zone.name, zone_id: result.zone.id, rider_id: c.rider_id,
          date: new Date().toISOString().split('T')[0], confidence: result.fusion.confidence,
          signals: result.fusion.signals_fired, recommendedPayout: c.recommended_payout,
          auditSummary: `Simulated ${result.scenario} — ${result.fusion.signals_fired}/4 signals fired.`,
          status: c.status, exclusion_check: c.exclusion_check, fraud_score: c.fraud_score,
        })),
        ...prev,
      ])
    }

    // Refresh KPIs
    if (apiAvailable) {
      try {
        const kpiData = await getKPIs()
        if (kpiData.kpis) setKPIs(kpiData.kpis)
      } catch { /* ignore */ }
    }
  }, [apiAvailable])

  const handleReviewClaim = async (claimId: string, action: 'approve' | 'reject') => {
    if (apiAvailable) {
      try { await reviewClaim(claimId, action) } catch { /* fallback */ }
    }
    setClaimStatuses(prev => ({ ...prev, [claimId]: action === 'approve' ? 'approved' : 'rejected' }))
  }

  const handleExpandClaim = async (claimId: string) => {
    const isExpanding = expandedClaim !== claimId
    setExpandedClaim(isExpanding ? claimId : null)
    // Fetch audit report on expand if not cached
    if (isExpanding && !auditReports[claimId] && apiAvailable) {
      try {
        const report = await getClaimAuditReport(claimId)
        setAuditReports(prev => ({ ...prev, [claimId]: report.content }))
      } catch { /* no report available */ }
    }
  }

  const filteredClaims = claims.filter(c => {
    const status = claimStatuses[c.id] || c.status
    const matchesSearch = !claimSearch || (c.zone || c.zone_id || '').toLowerCase().includes(claimSearch.toLowerCase()) || (c.rider_id || '').toLowerCase().includes(claimSearch.toLowerCase()) || c.id.toLowerCase().includes(claimSearch.toLowerCase())
    const matchesStatus = statusFilter === 'all' || status === statusFilter
    return matchesSearch && matchesStatus
  })

  const pendingClaims = claims.filter(c => {
    const status = claimStatuses[c.id] || c.status
    return status === 'pending' || status === 'pending_review'
  })

  return (
    <div className="min-h-screen bg-slate-900">
      <header className="bg-slate-950 border-b border-slate-800 px-3 sm:px-4 lg:px-6 py-3 flex items-center justify-between sticky top-0 z-[1000]">
        <div className="flex items-center gap-2 sm:gap-3">
          <button aria-label="Go back" onClick={() => navigate('/')} className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-slate-800 text-slate-400 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" /></svg>
          </button>
          <div className="flex items-center gap-2 sm:gap-2.5">
            <div className="w-6 h-6 sm:w-7 sm:h-7 bg-blue-500 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/20">
              <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
              </svg>
            </div>
            <div>
              <p className="text-white font-bold text-xs sm:text-sm leading-tight">ZoneGuard Admin</p>
              <p className="text-slate-500 text-xs hidden sm:block">Insurer Operations Dashboard</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-2.5">
          <div className={`w-2 h-2 rounded-full ${apiAvailable ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
          <span className="text-slate-400 text-xs hidden sm:block">
            {apiAvailable ? 'Live' : 'Demo'} · Bengaluru · {normalizedZones.length} zones · {new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })} IST
          </span>
          <span className="text-slate-400 text-xs sm:hidden">
            {apiAvailable ? 'Live' : 'Demo'}
          </span>
        </div>
      </header>

      <DemoTour />
      <main className="max-w-7xl mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-5 space-y-4 sm:space-y-5">
        <div data-tour="kpi-strip"><KPIStrip kpis={kpis} /></div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {/* Leaflet Choropleth Map */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-5" data-tour="zone-map">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 sm:gap-0 mb-3 sm:mb-4">
              <div>
                <h2 className="text-white font-bold text-base sm:text-lg">Bengaluru Zone Risk Map</h2>
                <p className="text-slate-400 text-xs">Interactive Leaflet choropleth · Click zone for details</p>
              </div>
              <div className="flex items-center gap-2 sm:gap-3 text-xs overflow-x-auto pb-1 sm:pb-0">
                {[['#10b981', 'Low'], ['#f59e0b', 'Med'], ['#f97316', 'High'], ['#ef4444', 'Flood']].map(([color, label]) => (
                  <div key={label} className="flex items-center gap-1 flex-shrink-0">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
                    <span className="text-slate-400">{label}</span>
                  </div>
                ))}
              </div>
            </div>

            <BengaluruZoneMap
              zones={normalizedZones}
              selectedZoneId={selectedZoneId || undefined}
              onZoneClick={handleZoneClick}
              height="320px"
              mobileHeight="240px"
              signalData={signalData}
            />

            {/* Selected zone details */}
            {selectedZone && (
              <div className="mt-3 sm:mt-4 bg-slate-900 border border-slate-700 rounded-xl p-3 sm:p-4">
                <h3 className="text-white font-bold text-sm sm:text-base mb-2">{selectedZone.name}</h3>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  <div><span className="text-slate-400">Risk Score</span><p className="text-white font-bold">{selectedZone.riskScore}/100</p></div>
                  <div><span className="text-slate-400">Premium</span><p className="text-white font-bold">₹{selectedZone.weeklyPremium}/wk</p></div>
                  <div><span className="text-slate-400">Riders</span><p className="text-white font-bold">{selectedZone.activeRiders}</p></div>
                </div>
                {signalData[selectedZone.id] && (
                  <div className="mt-3 pt-3 border-t border-slate-700">
                    <p className={`text-xs font-bold ${signalData[selectedZone.id].is_disrupted ? 'text-red-400' : 'text-emerald-400'}`}>
                      {signalData[selectedZone.id].is_disrupted ? `⚠ DISRUPTION — ${signalData[selectedZone.id].confidence}` : '✓ All signals normal'}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* QuadSignal Panel */}
          <div data-tour="signal-panel"><QuadSignalPanel /></div>
        </div>

        {/* Disruption Simulator */}
        <div data-tour="simulator"><DisruptionSimulator
          zones={normalizedZones.map(z => ({ id: z.id, name: z.name }))}
          onSimulationTriggered={handleSimulation}
        /></div>

        {/* Analytics Charts Section */}
        <div className="space-y-5" data-tour="analytics">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-white font-bold text-lg">Analytics</h2>
              <p className="text-slate-400 text-xs">Weekly performance metrics and trends</p>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
              </svg>
              <span>Last 7 days</span>
            </div>
          </div>

          {/* Two-column grid for charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <ClaimsChart />
            <PayoutChart />
          </div>

          {/* Loss Ratio Widget - Full width on mobile, centered on desktop */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="lg:col-start-2">
              <LossRatioWidget />
            </div>
          </div>
        </div>

        {/* Claims Queue */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-5" data-tour="claims-queue">
          <div className="flex items-center justify-between mb-3 sm:mb-4">
            <div>
              <h2 className="text-white font-bold text-base sm:text-lg">Claims Queue</h2>
              <p className="text-slate-400 text-xs">Review claims · Gemini AI audit reports included</p>
            </div>
            {pendingClaims.length > 0 && (
              <span className="bg-amber-500/20 text-amber-400 border border-amber-500/30 text-xs font-bold px-2.5 py-1 rounded-full">
                {pendingClaims.length} pending
              </span>
            )}
          </div>

          {/* Search and Filter Bar */}
          <div className="flex flex-col sm:flex-row gap-2 mb-3">
            <div className="flex-1 relative">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Search by zone, rider ID, or claim ID..."
                value={claimSearch}
                onChange={(e) => setClaimSearch(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-white text-xs placeholder:text-slate-500 focus:outline-none focus:border-blue-500"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs focus:outline-none focus:border-blue-500"
            >
              <option value="all">All Statuses</option>
              <option value="pending_review">Pending Review</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="held">Held</option>
            </select>
          </div>

          <div className="space-y-2.5">
            {claimsLoading ? (
              <>
                <ClaimSkeleton />
                <ClaimSkeleton />
                <ClaimSkeleton />
              </>
            ) : filteredClaims.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-slate-500 text-sm">{claimSearch || statusFilter !== 'all' ? 'No claims match your filters' : 'No claims yet'}</p>
              </div>
            ) : null}
            {!claimsLoading && filteredClaims.map((claim) => {
              const status = claimStatuses[claim.id] || claim.status
              const isPending = status === 'pending' || status === 'pending_review'
              return (
                <div key={claim.id} className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
                  <button
                    className="w-full p-3 sm:p-4 flex items-center justify-between text-left hover:bg-slate-800/50 transition-colors"
                    onClick={() => handleExpandClaim(claim.id)}
                  >
                    <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
                      <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isPending ? 'bg-amber-400 animate-pulse' : status === 'approved' ? 'bg-emerald-400' : 'bg-red-400'}`} />
                      <div className="min-w-0">
                        <p className="text-white font-semibold text-sm truncate">{claim.zone || claim.zone_id}</p>
                        <p className="text-slate-400 text-xs truncate">{claim.date} · {claim.confidence} · ₹{(claim.recommendedPayout || claim.recommended_payout || 0).toLocaleString()}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border capitalize ${
                        isPending ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
                        status === 'approved' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                        'bg-red-500/20 text-red-400 border-red-500/30'
                      }`}>{status}</span>
                      <svg className={`w-4 h-4 text-slate-500 transition-transform ${expandedClaim === claim.id ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </div>
                  </button>

                  {expandedClaim === claim.id && (
                    <div className="px-3 sm:px-4 pb-3 sm:pb-4 border-t border-slate-800">
                      {/* Exclusion check results */}
                      {claim.exclusion_check && (
                        <div className="mt-3 bg-slate-800 rounded-xl p-3">
                          <p className={`text-xs font-bold mb-1 ${claim.exclusion_check.passed ? 'text-emerald-400' : 'text-red-400'}`}>
                            Exclusion Check: {claim.exclusion_check.passed ? 'PASSED' : 'TRIGGERED'}
                          </p>
                          <p className="text-slate-400 text-xs">
                            {claim.exclusion_check.exclusions_evaluated?.length || 10} exclusions evaluated
                            {claim.exclusion_check.exclusions_triggered?.length > 0 && (
                              <span className="text-red-400"> · {claim.exclusion_check.exclusions_triggered.map((e) => e.name).join(', ')}</span>
                            )}
                          </p>
                        </div>
                      )}

                      {/* Fraud score */}
                      {claim.fraud_score !== undefined && (
                        <div className="mt-2 flex items-center gap-2 text-xs">
                          <span className="text-slate-400">FraudShield:</span>
                          <span className={`font-bold ${claim.fraud_score > 0.65 ? 'text-red-400' : 'text-emerald-400'}`}>
                            {(claim.fraud_score * 100).toFixed(0)}% risk
                          </span>
                        </div>
                      )}

                      {/* Audit summary — from API or simulation */}
                      {(auditReports[claim.id] || claim.auditSummary) && (
                        <div className="mt-2 bg-slate-800 rounded-xl p-3">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-xs">🤖</span>
                            <p className="text-slate-300 text-xs font-semibold">Gemini AI Audit Report</p>
                          </div>
                          <p className="text-slate-300 text-xs leading-relaxed whitespace-pre-line">{auditReports[claim.id] || claim.auditSummary}</p>
                        </div>
                      )}

                      {isPending && (
                        <div className="flex flex-col sm:flex-row gap-2 mt-3">
                          <button onClick={() => handleReviewClaim(claim.id, 'approve')}
                            className="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold py-2.5 rounded-lg transition-colors">
                            ✓ Approve Payout
                          </button>
                          <button onClick={() => handleReviewClaim(claim.id, 'reject')}
                            className="flex-1 bg-slate-700 hover:bg-slate-600 text-slate-300 text-xs font-bold py-2.5 rounded-lg transition-colors">
                            ✗ Reject
                          </button>
                        </div>
                      )}
                      {!isPending && (
                        <p className={`mt-3 text-xs text-center ${status === 'approved' ? 'text-emerald-400' : 'text-red-400'}`}>
                          {status === 'approved' ? '✓ Payout approved and disbursed' : '✗ Claim rejected'}
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* FraudShield v2 — Federated Learning */}
        <div className="bg-slate-900 rounded-2xl border border-slate-700 p-4 sm:p-6" data-tour="fraudshield-v2">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-white font-bold text-base flex items-center gap-2">
                FraudShield v2 — Federated Learning
                <span className="text-[10px] bg-purple-500/20 text-purple-300 px-2 py-0.5 rounded-full font-semibold">DPDP Compliant</span>
              </h2>
              <p className="text-slate-400 text-xs mt-1">Privacy-preserving anomaly detection — raw data never leaves city cluster</p>
            </div>
            <button
              onClick={async () => {
                setFlTraining(true)
                try {
                  const res = await trainFederatedModel()
                  setFlResult(res)
                } catch { setFlResult({ error: 'Training unavailable — backend not connected' }) }
                setFlTraining(false)
              }}
              disabled={flTraining}
              className="bg-purple-600 hover:bg-purple-500 disabled:bg-purple-800 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
            >
              {flTraining ? 'Training...' : 'Run Federated Training'}
            </button>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-3">
            {[
              { label: 'Aggregation', value: 'FedAvg' },
              { label: 'City Clients', value: '3' },
              { label: 'Features', value: '8' },
            ].map(({ label, value }) => (
              <div key={label} className="bg-slate-800 rounded-lg p-3 text-center">
                <p className="text-slate-400 text-[10px] uppercase tracking-wide">{label}</p>
                <p className="text-white font-bold text-lg">{value}</p>
              </div>
            ))}
          </div>
          {flResult && !flResult.error ? (
            <div className="space-y-3">
              {/* Training summary */}
              <div className="bg-slate-800 rounded-lg p-3">
                <p className="text-emerald-400 text-xs font-semibold mb-2">
                  ✓ Training complete — {flResult.rounds_completed ?? 5} rounds
                </p>
                {/* Convergence history */}
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-slate-400 text-[10px] uppercase">Convergence per round:</span>
                  <div className="flex gap-1">
                    {(flResult.convergence_history ?? []).map((delta, i) => (
                      <span key={i} className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${delta === 0 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'}`}>
                        R{i + 1}: {delta.toFixed(4)}
                      </span>
                    ))}
                  </div>
                </div>
                <p className="text-slate-500 text-[10px]">
                  Model gradients aggregated via FedAvg across 3 city clusters. Raw rider data never centralized (DPDP Act 2023 compliant).
                </p>
              </div>
              {/* Per-client stats */}
              {flResult.per_client_stats && (
                <div className="grid grid-cols-3 gap-2">
                  {Object.entries(flResult.per_client_stats).map(([cityId, stats]) => (
                    <div key={cityId} className="bg-slate-800 rounded-lg p-2.5 text-center">
                      <p className="text-purple-300 text-[10px] font-semibold uppercase truncate">{cityId.replace(/_/g, ' ')}</p>
                      <p className="text-white font-bold text-sm mt-0.5">{stats.training_samples} samples</p>
                      <p className="text-slate-500 text-[10px]">{stats.zone_ids?.length ?? 0} zones</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : flResult?.error ? (
            <div className="bg-slate-800 rounded-lg p-3">
              <p className="text-amber-400 text-xs font-semibold">⚠ {flResult.error}</p>
            </div>
          ) : null}
        </div>

        {/* Temporal Clustering — Ring Detection */}
        <div className="bg-slate-900 rounded-2xl border border-slate-700 p-4 sm:p-6" data-tour="temporal-clustering">
          <h2 className="text-white font-bold text-base mb-1">Temporal Clustering — Ring Detection</h2>
          <p className="text-slate-400 text-xs mb-4">Analyze claim timestamp graphs per zone. Genuine disruptions show Poisson-distributed patterns; coordinated attacks show dense temporal spikes.</p>
          <div className="flex gap-2 mb-3">
            <select
              className="bg-slate-800 border border-slate-600 text-slate-300 rounded-lg px-3 py-2 text-xs flex-1"
              defaultValue=""
              onChange={async (e) => {
                const zid = e.target.value
                if (!zid) return
                setTemporalLoading(true)
                try {
                  const res = await getTemporalAnalysis(zid)
                  setTemporalData(res as Record<string, unknown>)
                } catch { setTemporalData({ error: 'Analysis unavailable' }) }
                setTemporalLoading(false)
              }}
            >
              <option value="" disabled>Select zone for analysis...</option>
              {normalizedZones.map(z => <option key={z.id} value={z.id}>{z.name}</option>)}
            </select>
          </div>
          {temporalLoading && <p className="text-slate-400 text-xs animate-pulse">Analyzing claim timestamps...</p>}
          {temporalData && !temporalLoading && (
            <div className="bg-slate-800 rounded-lg p-3">
              {(temporalData as Record<string, unknown>).error ? (
                <p className="text-amber-400 text-xs">⚠ {String((temporalData as Record<string, unknown>).error)}</p>
              ) : (temporalData as Record<string, unknown>).message ? (
                <p className="text-slate-400 text-xs">{String((temporalData as Record<string, unknown>).message)}</p>
              ) : (
                <>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-white text-sm font-bold">{String((temporalData as Record<string, unknown>).zone_name)}</span>
                    <span className="text-slate-400 text-xs">{String((temporalData as Record<string, unknown>).total_claims)} claims analyzed</span>
                  </div>
                  {(temporalData as Record<string, unknown>).clustering_analysis && (() => {
                    const ca = (temporalData as Record<string, unknown>).clustering_analysis as Record<string, unknown>
                    const isSuspicious = ca.is_suspicious as boolean
                    return (
                      <div className="flex items-center gap-4">
                        <div>
                          <p className="text-slate-400 text-[10px] uppercase">Clustering Coefficient</p>
                          <p className={`font-bold text-lg ${isSuspicious ? 'text-red-400' : 'text-emerald-400'}`}>
                            {((ca.clustering_coefficient as number) * 100).toFixed(1)}%
                          </p>
                        </div>
                        <div>
                          <p className="text-slate-400 text-[10px] uppercase">Status</p>
                          <span className={`text-xs font-bold px-2 py-1 rounded-full ${isSuspicious ? 'bg-red-500/20 text-red-300' : 'bg-emerald-500/20 text-emerald-300'}`}>
                            {String(ca.recommendation).toUpperCase()}
                          </span>
                        </div>
                      </div>
                    )
                  })()}
                </>
              )}
            </div>
          )}
        </div>

        {/* Blockchain & DeFi Navigation */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
          <h2 className="text-white font-bold text-base mb-1">Blockchain & DeFi</h2>
          <p className="text-slate-400 text-xs mb-3">On-chain infrastructure, governance, and reinsurance</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Link
              to="/blockchain"
              className="flex items-center gap-3 bg-slate-900 border border-slate-700 rounded-xl p-3 hover:border-violet-500/50 hover:bg-slate-900/80 transition-colors group"
            >
              <div className="w-8 h-8 bg-violet-500/20 rounded-lg flex items-center justify-center text-sm flex-shrink-0 group-hover:bg-violet-500/30 transition-colors">
                ⛓️
              </div>
              <div>
                <p className="text-white font-semibold text-sm group-hover:text-violet-300 transition-colors">ZoneChain Explorer</p>
                <p className="text-slate-500 text-xs">Audit trails, anchors, parameter log</p>
              </div>
            </Link>
            <Link
              to="/governance"
              className="flex items-center gap-3 bg-slate-900 border border-slate-700 rounded-xl p-3 hover:border-amber-500/50 hover:bg-slate-900/80 transition-colors group"
            >
              <div className="w-8 h-8 bg-amber-500/20 rounded-lg flex items-center justify-center text-sm flex-shrink-0 group-hover:bg-amber-500/30 transition-colors">
                ⬡
              </div>
              <div>
                <p className="text-white font-semibold text-sm group-hover:text-amber-300 transition-colors">Governance</p>
                <p className="text-slate-500 text-xs">DAO proposals, voting, ZONE tokens</p>
              </div>
            </Link>
            <Link
              to="/reinsurance"
              className="flex items-center gap-3 bg-slate-900 border border-slate-700 rounded-xl p-3 hover:border-emerald-500/50 hover:bg-slate-900/80 transition-colors group"
            >
              <div className="w-8 h-8 bg-emerald-500/20 rounded-lg flex items-center justify-center text-sm flex-shrink-0 group-hover:bg-emerald-500/30 transition-colors">
                🏦
              </div>
              <div>
                <p className="text-white font-semibold text-sm group-hover:text-emerald-300 transition-colors">Reinsurance Pool</p>
                <p className="text-slate-500 text-xs">Tranches, staking, stress tests</p>
              </div>
            </Link>
          </div>
        </div>

        <div className="text-center pb-4">
          <p className="text-slate-600 text-xs">
            ZoneGuard v2.0 · Guidewire DEVTrails 2026 · Bengaluru pilot · {normalizedZones.length} zones · IRDAI parametric sandbox
          </p>
        </div>
      </main>
    </div>
  )
}
