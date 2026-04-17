import { useState } from 'react'

export interface Proposal {
  id: string
  proposer_rider_id: string
  parameter: string
  proposed_value: number
  proposed_exclusion_id?: string
  rationale: string
  status: 'active' | 'passed' | 'rejected' | 'expired' | 'executed' | 'blocked'
  votes_for: number
  votes_against: number
  weight_for: number
  weight_against: number
  quorum_reached: boolean
  supermajority_reached: boolean
  voting_ends_at: string
  executed_at?: string
  execution_tx_hash?: string
  guardrail_block_reason?: string
  created_at: string
}

interface Props {
  proposal: Proposal
  riderId: string
  onVote?: (proposalId: string, support: boolean) => Promise<void>
  votedProposals?: Set<string>
}

const PARAM_LABELS: Record<string, string> = {
  payout_percentage:     'Payout Percentage',
  max_disruption_days:   'Max Disruption Days',
  forward_lock_discount: 'Forward Lock Discount',
  exclusion_add:         'Add Exclusion',
  exclusion_remove:      'Remove Exclusion',
  s4_threshold:          'S4 Signal Threshold',
}

const PARAM_UNITS: Record<string, string> = {
  payout_percentage:     '%',
  max_disruption_days:   ' days',
  forward_lock_discount: '%',
  exclusion_add:         '',
  exclusion_remove:      '',
  s4_threshold:          '',
}

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  active:   { label: 'Voting Open',  color: 'text-blue-700',    bg: 'bg-blue-50 border-blue-200'    },
  passed:   { label: 'Passed',       color: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200' },
  rejected: { label: 'Rejected',     color: 'text-red-700',     bg: 'bg-red-50 border-red-200'      },
  expired:  { label: 'Expired',      color: 'text-stone-600',   bg: 'bg-stone-50 border-stone-200'  },
  executed: { label: 'Executed ✓',   color: 'text-violet-700',  bg: 'bg-violet-50 border-violet-200' },
  blocked:  { label: 'Blocked',      color: 'text-orange-700',  bg: 'bg-orange-50 border-orange-200' },
}

export default function ProposalCard({ proposal, riderId: _riderId, onVote, votedProposals }: Props) {
  const [voting, setVoting] = useState(false)
  const [expanded, setExpanded] = useState(false)

  const totalWeight = proposal.weight_for + proposal.weight_against
  const supportPct = totalWeight > 0 ? Math.round((proposal.weight_for / totalWeight) * 100) : 0
  const votesTotal = proposal.votes_for + proposal.votes_against
  const hasVoted = votedProposals?.has(proposal.id)

  const statusCfg = STATUS_CONFIG[proposal.status] || STATUS_CONFIG.expired
  const isActive = proposal.status === 'active'
  const endsAt = new Date(proposal.voting_ends_at)
  const hoursLeft = Math.max(0, Math.ceil((endsAt.getTime() - Date.now()) / 3_600_000))

  const handleVote = async (support: boolean) => {
    if (!onVote || voting || hasVoted) return
    setVoting(true)
    try { await onVote(proposal.id, support) }
    finally { setVoting(false) }
  }

  return (
    <div className="bg-white rounded-2xl border border-amber-100 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="p-4 pb-3">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${statusCfg.bg} ${statusCfg.color}`}>
                {statusCfg.label}
              </span>
              {proposal.quorum_reached && (
                <span className="text-xs text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-full border border-emerald-100">
                  Quorum ✓
                </span>
              )}
              {isActive && hoursLeft > 0 && (
                <span className="text-xs text-stone-400">{hoursLeft}h remaining</span>
              )}
            </div>
            <h3 className="text-stone-800 font-bold text-sm mt-1.5">
              {PARAM_LABELS[proposal.parameter] || proposal.parameter}
            </h3>
            <p className="text-stone-500 text-xs mt-0.5">
              Proposed: <span className="text-amber-700 font-semibold">
                {proposal.proposed_value}{PARAM_UNITS[proposal.parameter] || ''}
              </span>
              <span className="mx-1.5 text-stone-300">·</span>
              By {proposal.proposer_rider_id.slice(-5)}
            </p>
          </div>
        </div>

        {/* Vote progress bar */}
        <div className="mt-3">
          <div className="flex justify-between text-xs text-stone-500 mb-1">
            <span className="text-emerald-600 font-medium">For {supportPct}%</span>
            <span className="text-stone-500">{votesTotal} votes</span>
            <span className="text-red-500 font-medium">Against {100 - supportPct}%</span>
          </div>
          <div className="h-2 bg-stone-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-400 rounded-full transition-all duration-700"
              style={{ width: `${supportPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Expandable rationale */}
      <button
        onClick={() => setExpanded(p => !p)}
        className="w-full px-4 py-2 text-left text-xs text-stone-400 hover:text-amber-600 hover:bg-amber-50 transition-colors border-t border-stone-50 flex items-center justify-between"
      >
        <span>Rationale</span>
        <svg className={`w-3.5 h-3.5 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="px-4 py-3 bg-stone-50 border-t border-stone-100">
          <p className="text-stone-600 text-xs leading-relaxed">{proposal.rationale}</p>
          {proposal.guardrail_block_reason && (
            <div className="mt-2 p-2 bg-orange-50 border border-orange-200 rounded-lg">
              <p className="text-orange-700 text-xs font-medium">⚠ Actuarial Guardrail</p>
              <p className="text-orange-600 text-xs mt-0.5">{proposal.guardrail_block_reason}</p>
            </div>
          )}
          {proposal.execution_tx_hash && (
            <p className="text-stone-400 text-xs mt-2 font-mono truncate">
              TX: {proposal.execution_tx_hash}
            </p>
          )}
        </div>
      )}

      {/* Vote buttons — only show for active proposals rider hasn't voted on */}
      {isActive && !hasVoted && onVote && (
        <div className="flex gap-2 p-3 border-t border-stone-50">
          <button
            onClick={() => handleVote(true)}
            disabled={voting}
            className="flex-1 py-2 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-bold hover:bg-emerald-100 transition-colors disabled:opacity-50"
          >
            {voting ? '...' : '✓ Support'}
          </button>
          <button
            onClick={() => handleVote(false)}
            disabled={voting}
            className="flex-1 py-2 rounded-xl bg-red-50 border border-red-200 text-red-600 text-xs font-bold hover:bg-red-100 transition-colors disabled:opacity-50"
          >
            {voting ? '...' : '✗ Oppose'}
          </button>
        </div>
      )}

      {isActive && hasVoted && (
        <div className="px-4 pb-3">
          <p className="text-center text-emerald-600 text-xs font-medium py-1.5 bg-emerald-50 rounded-xl border border-emerald-100">
            ✓ Voted · +3 ZONE earned
          </p>
        </div>
      )}
    </div>
  )
}
