/**
 * GovernancePanel — Innovation 06 + 07 + 08 UI
 * Renders within RiderDashboard as a new "Governance" tab.
 *
 * Sections:
 *   1. ZONE Token Balance + earning history
 *   2. Active governance proposals + voting
 *   3. SoulboundNFT gallery + Coverage Continuity Score
 *   4. Reinsurance pool summary (read-only for riders)
 */

import { useState, useEffect, useCallback } from 'react'
import ZoneTokenBalance from './ZoneTokenBalance'
import ProposalCard, { type Proposal } from './ProposalCard'

interface NFT {
  token_id: string
  week_number: number
  year: number
  coverage_tier: string
  zone_id: string
  premium_paid: number
  was_disrupted: boolean
  payout_received: number
  minted_at: string
  chain_tx_hash?: string
}

interface ContinuityScore {
  total_nfts: number
  consecutive_weeks: number
  score: number
  score_label: string
  eligible_for_microloan: boolean
  eligible_for_credit_delegation: boolean
  total_payout_received: number
  avg_premium_paid: number
  nbfc_report_uri?: string
}

interface PoolState {
  total_pool_inr: number
  senior_pool_inr: number
  mezzanine_pool_inr: number
  junior_pool_inr: number
  loss_ratio_ltm: number
  active_positions: number
}

interface Props {
  riderId: string
  apiAvailable: boolean
}

// ── Mock data ──────────────────────────────────────────────────────────────

const MOCK_PROPOSALS: Proposal[] = [
  {
    id: 'PROP-001A2B3C',
    proposer_rider_id: 'AMZFLEX-BLR-01199',
    parameter: 'payout_percentage',
    proposed_value: 62,
    rationale: 'Monsoon season disruptions have been consistently above threshold. A 62% payout rate better reflects actual income loss experienced by HSR Layout riders this season.',
    status: 'active',
    votes_for: 47,
    votes_against: 12,
    weight_for: 142.3,
    weight_against: 38.1,
    quorum_reached: true,
    supermajority_reached: false,
    voting_ends_at: new Date(Date.now() + 3 * 86400000).toISOString(),
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
  },
  {
    id: 'PROP-002D4E5F',
    proposer_rider_id: 'AMZFLEX-BLR-03344',
    parameter: 'max_disruption_days',
    proposed_value: 3,
    rationale: 'With improving signal accuracy from ZoneTwin, we can safely extend max disruption coverage from 2 to 3 days without significant loss ratio impact.',
    status: 'executed',
    votes_for: 89,
    votes_against: 11,
    weight_for: 267.4,
    weight_against: 33.2,
    quorum_reached: true,
    supermajority_reached: true,
    voting_ends_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    executed_at: new Date(Date.now() - 4 * 86400000).toISOString(),
    execution_tx_hash: 'FABRIC-A3B7C9D1E5F2',
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
  },
]

const MOCK_NFTS: NFT[] = Array.from({ length: 8 }, (_, i) => ({
  token_id: `SNFT-${String(i).padStart(4, '0')}`,
  week_number: 20 - i,
  year: 2025,
  coverage_tier: 'standard',
  zone_id: 'hsr',
  premium_paid: 89,
  was_disrupted: i === 2 || i === 5,
  payout_received: i === 2 ? 1200 : i === 5 ? 800 : 0,
  minted_at: new Date(Date.now() - i * 7 * 86400000).toISOString(),
  chain_tx_hash: `FABRIC-SNFT-${Math.random().toString(16).slice(2, 14).toUpperCase()}`,
}))

const MOCK_SCORE: ContinuityScore = {
  total_nfts: 8,
  consecutive_weeks: 8,
  score: 38.5,
  score_label: 'Building',
  eligible_for_microloan: false,
  eligible_for_credit_delegation: false,
  total_payout_received: 2000,
  avg_premium_paid: 89,
}

const MOCK_POOL: PoolState = {
  total_pool_inr: 4_200_000,
  senior_pool_inr: 2_940_000,
  mezzanine_pool_inr: 840_000,
  junior_pool_inr: 420_000,
  loss_ratio_ltm: 42.3,
  active_positions: 7,
}

// ── Subcomponents ──────────────────────────────────────────────────────────

function NFTGrid({ nfts, score }: { nfts: NFT[]; score: ContinuityScore }) {
  return (
    <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-stone-800 font-bold text-sm">SoulboundPolicy NFTs</h3>
          <p className="text-stone-400 text-xs mt-0.5">Non-transferable · Minted weekly to ZK identity</p>
        </div>
        <div className="text-right">
          <p className="text-stone-800 font-bold text-sm">{nfts.length}</p>
          <p className="text-stone-400 text-xs">minted</p>
        </div>
      </div>

      {/* Continuity Score */}
      <div className={`rounded-xl p-3 mb-3 border ${
        score.eligible_for_credit_delegation
          ? 'bg-violet-50 border-violet-200'
          : score.eligible_for_microloan
          ? 'bg-emerald-50 border-emerald-200'
          : 'bg-amber-50 border-amber-100'
      }`}>
        <div className="flex items-center justify-between">
          <div>
            <p className="text-stone-700 text-xs font-semibold">Coverage Continuity Score</p>
            <p className="text-stone-500 text-xs mt-0.5">{score.consecutive_weeks} consecutive weeks</p>
          </div>
          <div className="text-right">
            <p className="text-stone-800 font-bold text-lg">{score.score.toFixed(0)}</p>
            <span className={`text-xs font-semibold ${
              score.score_label === 'Elite' ? 'text-violet-600' :
              score.score_label === 'Trusted' ? 'text-emerald-600' :
              score.score_label === 'Established' ? 'text-blue-600' :
              'text-amber-600'
            }`}>{score.score_label}</span>
          </div>
        </div>

        {/* DeFi eligibility */}
        <div className="flex gap-2 mt-2 flex-wrap">
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
            score.eligible_for_microloan
              ? 'bg-emerald-100 border-emerald-200 text-emerald-700'
              : 'bg-stone-100 border-stone-200 text-stone-400'
          }`}>
            {score.eligible_for_microloan ? '✓' : '○'} Goldfinch Microloan (13wk)
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
            score.eligible_for_credit_delegation
              ? 'bg-violet-100 border-violet-200 text-violet-700'
              : 'bg-stone-100 border-stone-200 text-stone-400'
          }`}>
            {score.eligible_for_credit_delegation ? '✓' : '○'} Aave Delegation (52wk)
          </span>
        </div>

        {!score.eligible_for_microloan && (
          <p className="text-stone-400 text-xs mt-1.5">
            {13 - score.consecutive_weeks} more consecutive weeks to unlock microloans
          </p>
        )}
      </div>

      {/* NFT grid */}
      <div className="grid grid-cols-8 gap-1">
        {nfts.map((nft) => (
          <div
            key={nft.token_id}
            title={`W${nft.week_number} ${nft.year} — ${nft.was_disrupted ? `Payout: ₹${nft.payout_received}` : 'Claim-free'}`}
            className={`aspect-square rounded-md border flex items-center justify-center text-xs cursor-default transition-transform hover:scale-110 ${
              nft.was_disrupted
                ? 'bg-amber-100 border-amber-300'
                : 'bg-emerald-50 border-emerald-200'
            }`}
          >
            {nft.was_disrupted ? '⚡' : '✓'}
          </div>
        ))}
        {/* Empty slots to show progress toward 52 */}
        {Array.from({ length: Math.max(0, 13 - nfts.length) }).map((_, i) => (
          <div
            key={`empty-${i}`}
            className="aspect-square rounded-md border border-dashed border-stone-200 bg-stone-50"
          />
        ))}
      </div>
      <p className="text-stone-400 text-xs text-center mt-2">
        ✓ Claim-free week &nbsp;·&nbsp; ⚡ Payout issued
      </p>
    </div>
  )
}

function PoolSummary({ pool }: { pool: PoolState }) {
  const tranches = [
    { name: 'Senior',    amount: pool.senior_pool_inr,    pct: 70, color: 'bg-blue-400',   yield: '9-11%' },
    { name: 'Mezzanine', amount: pool.mezzanine_pool_inr, pct: 20, color: 'bg-amber-400',  yield: '14-18%' },
    { name: 'Junior',    amount: pool.junior_pool_inr,    pct: 10, color: 'bg-red-400',    yield: '25-30%' },
  ]

  return (
    <div className="bg-white rounded-2xl border border-amber-100 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-stone-800 font-bold text-sm">ZoneReinsurance Pool</h3>
          <p className="text-stone-400 text-xs mt-0.5">IRDAI/SB/2024/ZG-001 · SPV Model</p>
        </div>
        <div className="text-right">
          <p className="text-stone-800 font-bold text-sm">₹{(pool.total_pool_inr / 100000).toFixed(1)}L</p>
          <p className="text-stone-400 text-xs">total pool</p>
        </div>
      </div>

      {/* Stacked tranche bar */}
      <div className="h-3 rounded-full overflow-hidden flex mb-3">
        {tranches.map(t => (
          <div key={t.name} className={`${t.color}`} style={{ width: `${t.pct}%` }} />
        ))}
      </div>

      <div className="space-y-1.5">
        {tranches.map(t => (
          <div key={t.name} className="flex items-center justify-between text-xs">
            <div className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${t.color}`} />
              <span className="text-stone-600">{t.name} ({t.pct}%)</span>
            </div>
            <div className="flex items-center gap-2 text-stone-500">
              <span>₹{(t.amount / 100000).toFixed(1)}L</span>
              <span className="text-emerald-600 font-medium">{t.yield} yield</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 pt-3 border-t border-stone-100 flex justify-between text-xs text-stone-500">
        <span>LTM Loss Ratio: <span className={pool.loss_ratio_ltm > 75 ? 'text-red-600 font-bold' : 'text-stone-700 font-semibold'}>{pool.loss_ratio_ltm}%</span></span>
        <span>{pool.active_positions} LP positions</span>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

type Tab = 'tokens' | 'proposals' | 'nfts' | 'pool'

export default function GovernancePanel({ riderId, apiAvailable }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('tokens')
  const [proposals, setProposals] = useState<Proposal[]>(MOCK_PROPOSALS)
  const [nfts, setNfts] = useState<NFT[]>(MOCK_NFTS)
  const [score, setScore] = useState<ContinuityScore>(MOCK_SCORE)
  const [pool, setPool] = useState<PoolState>(MOCK_POOL)
  const [votedProposals, setVotedProposals] = useState<Set<string>>(new Set())
  const [toast, setToast] = useState<string | null>(null)

  const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  useEffect(() => {
    if (!apiAvailable) return
    const load = async () => {
      try {
        const [propRes, nftRes, scoreRes, poolRes] = await Promise.all([
          fetch(`${BASE}/api/v1/governance/proposals?status=active&limit=10`),
          fetch(`${BASE}/api/v1/governance/nfts/${riderId}?limit=20`),
          fetch(`${BASE}/api/v1/governance/nfts/${riderId}/continuity-score`),
          fetch(`${BASE}/api/v1/reinsurance/pool/state`),
        ])
        if (propRes.ok) { const d = await propRes.json(); setProposals(d.proposals || []) }
        if (nftRes.ok) { const d = await nftRes.json(); setNfts(d.nfts || []) }
        if (scoreRes.ok) setScore(await scoreRes.json())
        if (poolRes.ok) setPool(await poolRes.json())
      } catch { /* use mock data */ }
    }
    load()
  }, [riderId, apiAvailable])

  const handleVote = useCallback(async (proposalId: string, support: boolean) => {
    if (!apiAvailable) {
      setVotedProposals(s => new Set([...s, proposalId]))
      showToast(`Vote recorded · +3 ZONE tokens earned`)
      return
    }
    try {
      const res = await fetch(`${BASE}/api/v1/governance/proposals/${proposalId}/vote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rider_id: riderId, support }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Vote failed')
      setVotedProposals(s => new Set([...s, proposalId]))
      showToast(data.message || 'Vote recorded · +3 ZONE earned')
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : 'Vote failed')
    }
  }, [riderId, apiAvailable])

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 3000)
  }

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: 'tokens',    label: 'ZONE' },
    { id: 'proposals', label: 'Proposals', count: proposals.filter(p => p.status === 'active').length },
    { id: 'nfts',      label: 'NFTs', count: nfts.length },
    { id: 'pool',      label: 'Pool' },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-amber-600 to-amber-500 rounded-2xl p-4 text-white">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-6 h-6 rounded-lg bg-white/20 flex items-center justify-center text-xs font-bold">⬡</div>
          <h2 className="font-bold text-base">DAO PremiumGov</h2>
        </div>
        <p className="text-amber-100 text-xs leading-relaxed">
          Shape ZoneGuard's parameters through on-chain governance.
          Earn ZONE tokens, vote on proposals, and build your coverage history.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-stone-100 rounded-xl p-1">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center justify-center gap-1 ${
              activeTab === tab.id
                ? 'bg-white text-amber-700 shadow-sm'
                : 'text-stone-500 hover:text-stone-700'
            }`}
          >
            {tab.label}
            {tab.count != null && tab.count > 0 && (
              <span className={`w-4 h-4 rounded-full text-xs flex items-center justify-center ${
                activeTab === tab.id ? 'bg-amber-100 text-amber-700' : 'bg-stone-200 text-stone-500'
              }`}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'tokens' && (
        <ZoneTokenBalance riderId={riderId} apiAvailable={apiAvailable} />
      )}

      {activeTab === 'proposals' && (
        <div className="space-y-3">
          {proposals.length === 0 ? (
            <div className="bg-white rounded-2xl border border-amber-100 p-8 text-center">
              <p className="text-stone-400 text-sm">No active proposals</p>
              <p className="text-stone-300 text-xs mt-1">Hold ≥50 ZONE tokens to create a proposal</p>
            </div>
          ) : (
            proposals.map(p => (
              <ProposalCard
                key={p.id}
                proposal={p}
                riderId={riderId}
                onVote={handleVote}
                votedProposals={votedProposals}
              />
            ))
          )}
          <div className="bg-amber-50 rounded-xl border border-amber-100 p-3">
            <p className="text-amber-700 text-xs font-semibold mb-1">Actuarial Guardrails Active</p>
            <p className="text-stone-500 text-xs leading-relaxed">
              All executed proposals are validated against actuarial safe bands before on-chain execution.
              If LTM loss ratio &gt;85%, payout % increases are automatically blocked regardless of vote outcome.
            </p>
          </div>
        </div>
      )}

      {activeTab === 'nfts' && (
        <NFTGrid nfts={nfts} score={score} />
      )}

      {activeTab === 'pool' && (
        <div className="space-y-3">
          <PoolSummary pool={pool} />
          <div className="bg-stone-50 rounded-xl border border-stone-100 p-3">
            <p className="text-stone-500 text-xs leading-relaxed">
              The ZoneReinsurance pool provides institutional capital backing for all ZoneGuard payouts.
              Capital providers stake into tranches and earn yield from premium flows.
              Loss waterfall: Junior → Mezzanine → Senior.
            </p>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-stone-800 text-white text-xs font-medium px-4 py-2.5 rounded-xl shadow-lg z-50 max-w-xs text-center">
          {toast}
        </div>
      )}
    </div>
  )
}
