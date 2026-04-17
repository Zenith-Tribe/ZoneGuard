import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import GovernancePanel from '../components/GovernancePanel'
import { API_URL } from '../services/api'

interface TokenBalance {
  rider_id: string
  balance: number
  governance_weight: number
}

interface TokenTransaction {
  id: string
  event_type: string
  delta: number
  balance_after: number
  created_at: string
}

const GOVERNANCE_PARAMS = [
  { value: 'payout_percentage', label: 'Payout Percentage' },
  { value: 'max_disruption_days', label: 'Max Disruption Days' },
  { value: 'forward_lock_discount', label: 'Forward Lock Discount' },
  { value: 's4_threshold', label: 'S4 Signal Threshold' },
  { value: 'exclusion_add', label: 'Add Exclusion' },
  { value: 'exclusion_remove', label: 'Remove Exclusion' },
]

const MOCK_BALANCE: TokenBalance = {
  rider_id: 'AMZFLEX-BLR-04821',
  balance: 185,
  governance_weight: 13.6,
}

const MOCK_HISTORY: TokenTransaction[] = [
  { id: 'ZTX-001', event_type: 'weekly_coverage', delta: +10, balance_after: 185, created_at: '2025-01-20T00:00:00Z' },
  { id: 'ZTX-002', event_type: 'governance_vote', delta: +3, balance_after: 175, created_at: '2025-01-18T00:00:00Z' },
  { id: 'ZTX-003', event_type: 's4_checkin', delta: +5, balance_after: 172, created_at: '2025-01-15T00:00:00Z' },
  { id: 'ZTX-004', event_type: 'claim_free_4weeks', delta: +25, balance_after: 167, created_at: '2025-01-13T00:00:00Z' },
]

const EVENT_LABELS: Record<string, string> = {
  weekly_coverage: 'Weekly Coverage',
  claim_free_4weeks: '4-Week Claim-Free',
  s4_checkin: 'S4 Check-in',
  referral_active: 'Active Referral',
  governance_vote: 'Governance Vote',
  appeal_successful: 'Successful Appeal',
  appeal_false: 'False Appeal',
}

export default function GovernancePage() {
  const navigate = useNavigate()
  const [apiAvailable, setApiAvailable] = useState(false)
  const [balance, setBalance] = useState<TokenBalance>(MOCK_BALANCE)
  const [history, setHistory] = useState<TokenTransaction[]>(MOCK_HISTORY)
  const [proposalParam, setProposalParam] = useState('')
  const [proposalValue, setProposalValue] = useState('')
  const [proposalRationale, setProposalRationale] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  const riderId = localStorage.getItem('zoneguard_rider_id') || 'AMZFLEX-BLR-04821'

  useEffect(() => {
    const load = async () => {
      try {
        const [balRes, histRes] = await Promise.all([
          fetch(`${API_URL}/api/v1/governance/tokens/${riderId}`),
          fetch(`${API_URL}/api/v1/governance/tokens/${riderId}/history?limit=10`),
        ])
        if (balRes.ok) {
          setBalance(await balRes.json())
          setApiAvailable(true)
        }
        if (histRes.ok) {
          const data = await histRes.json()
          setHistory(data.transactions || [])
        }
      } catch {
        /* use mock data */
      }
    }
    load()
  }, [riderId])

  const showToast = useCallback((msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }, [])

  const handleCreateProposal = async () => {
    if (!proposalParam || !proposalValue || !proposalRationale.trim()) return
    setSubmitting(true)
    try {
      if (apiAvailable) {
        const res = await fetch(`${API_URL}/api/v1/governance/proposals`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            rider_id: riderId,
            parameter: proposalParam,
            proposed_value: Number(proposalValue),
            rationale: proposalRationale,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || 'Failed to create proposal')
        }
      }
      showToast('Proposal created successfully')
      setProposalParam('')
      setProposalValue('')
      setProposalRationale('')
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Failed to create proposal')
    } finally {
      setSubmitting(false)
    }
  }

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
            <div className="w-6 h-6 sm:w-7 sm:h-7 bg-amber-500 rounded-lg flex items-center justify-center shadow-lg shadow-amber-500/20 text-sm font-bold">
              ⬡
            </div>
            <div>
              <p className="text-white font-bold text-xs sm:text-sm leading-tight">DAO PremiumGov</p>
              <p className="text-slate-500 text-xs hidden sm:block">On-chain parametric governance</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-3">
          <span className="bg-amber-500/20 text-amber-300 border border-amber-500/30 text-xs font-bold px-2.5 py-1 rounded-full">
            {balance.balance} ZONE
          </span>
          <div className={`w-2 h-2 rounded-full ${apiAvailable ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-5 space-y-4 sm:space-y-5">
        {/* Governance Panel (embedded component) */}
        <GovernancePanel riderId={riderId} apiAvailable={apiAvailable} />

        {/* Create Proposal Section */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
          <div className="mb-4">
            <h2 className="text-white font-bold text-base sm:text-lg">Create Proposal</h2>
            <p className="text-slate-400 text-xs mt-0.5">
              Requires minimum 50 ZONE tokens. Proposals enter 7-day voting period.
            </p>
          </div>

          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="text-slate-400 text-xs font-medium mb-1 block">Parameter</label>
                <select
                  value={proposalParam}
                  onChange={(e) => setProposalParam(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs focus:outline-none focus:border-amber-500"
                >
                  <option value="">Select parameter...</option>
                  {GOVERNANCE_PARAMS.map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-slate-400 text-xs font-medium mb-1 block">Proposed Value</label>
                <input
                  type="number"
                  value={proposalValue}
                  onChange={(e) => setProposalValue(e.target.value)}
                  placeholder="e.g. 62"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs placeholder:text-slate-500 focus:outline-none focus:border-amber-500"
                />
              </div>
            </div>
            <div>
              <label className="text-slate-400 text-xs font-medium mb-1 block">Rationale</label>
              <textarea
                value={proposalRationale}
                onChange={(e) => setProposalRationale(e.target.value)}
                placeholder="Explain why this change would benefit the ZoneGuard ecosystem..."
                rows={3}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs placeholder:text-slate-500 focus:outline-none focus:border-amber-500 resize-none"
              />
            </div>
            <div className="flex items-center justify-between">
              <p className="text-slate-500 text-xs">
                Your voting weight: <span className="text-amber-400 font-semibold">{balance.governance_weight.toFixed(1)}</span>
              </p>
              <button
                onClick={handleCreateProposal}
                disabled={submitting || !proposalParam || !proposalValue || !proposalRationale.trim() || balance.balance < 50}
                className="bg-amber-600 hover:bg-amber-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-bold px-5 py-2 rounded-lg transition-colors"
              >
                {submitting ? 'Submitting...' : 'Submit Proposal'}
              </button>
            </div>
            {balance.balance < 50 && (
              <p className="text-red-400 text-xs">
                You need at least 50 ZONE tokens to create a proposal ({50 - balance.balance} more needed)
              </p>
            )}
          </div>
        </div>

        {/* Token Earning History */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 sm:p-5">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-white font-bold text-base sm:text-lg">Token Earning History</h2>
              <p className="text-slate-400 text-xs">Recent ZONE token transactions</p>
            </div>
            <span className="text-amber-400 text-xs font-bold">
              Balance: {balance.balance} ZONE
            </span>
          </div>
          <div className="space-y-2">
            {history.length === 0 ? (
              <p className="text-slate-500 text-xs text-center py-6">No token transactions yet</p>
            ) : (
              history.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between p-2.5 bg-slate-900 border border-slate-700 rounded-lg">
                  <div className="min-w-0 flex-1">
                    <p className="text-white text-xs font-medium truncate">
                      {EVENT_LABELS[tx.event_type] || tx.event_type}
                    </p>
                    <p className="text-slate-500 text-xs">
                      {new Date(tx.created_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 ml-2 flex-shrink-0">
                    <span className={`text-xs font-bold ${tx.delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {tx.delta > 0 ? '+' : ''}{tx.delta}
                    </span>
                    <span className="text-slate-500 text-xs font-mono">{tx.balance_after}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="text-center pb-4">
          <p className="text-slate-600 text-xs">
            DAO PremiumGov v1.0 · Quadratic voting · Actuarial guardrails active · IRDAI sandbox compliant
          </p>
        </div>
      </main>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-800 text-white text-xs font-medium px-4 py-2.5 rounded-xl shadow-lg z-50 max-w-xs text-center border border-slate-700">
          {toast}
        </div>
      )}
    </div>
  )
}
