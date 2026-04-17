import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { API_URL } from '../services/api'

interface BlockchainStatus {
  chain_height: number
  total_events_today: number
  total_anchors: number
  last_anchor_time: string
  fabric_status: string
  polygon_status: string
}

interface ParameterChange {
  id: string
  parameter: string
  old_value: string
  new_value: string
  changed_by: string
  timestamp: string
  tx_hash?: string
}

const MOCK_STATUS: BlockchainStatus = {
  chain_height: 14_827,
  total_events_today: 42,
  total_anchors: 1_203,
  last_anchor_time: new Date(Date.now() - 900_000).toISOString(),
  fabric_status: 'operational',
  polygon_status: 'operational',
}

const MOCK_PARAM_CHANGES: ParameterChange[] = [
  { id: 'PC-001', parameter: 'payout_percentage', old_value: '55%', new_value: '62%', changed_by: 'DAO Governance', timestamp: new Date(Date.now() - 4 * 86400000).toISOString(), tx_hash: 'FABRIC-A3B7C9' },
  { id: 'PC-002', parameter: 'max_disruption_days', old_value: '2', new_value: '3', changed_by: 'DAO Governance', timestamp: new Date(Date.now() - 10 * 86400000).toISOString(), tx_hash: 'FABRIC-D1E5F2' },
  { id: 'PC-003', parameter: 's4_threshold', old_value: '40%', new_value: '35%', changed_by: 'IRDAI Override', timestamp: new Date(Date.now() - 18 * 86400000).toISOString() },
  { id: 'PC-004', parameter: 'forward_lock_discount', old_value: '8%', new_value: '10%', changed_by: 'DAO Governance', timestamp: new Date(Date.now() - 25 * 86400000).toISOString(), tx_hash: 'FABRIC-G8H2I4' },
]

export default function BlockchainDashboard() {
  const navigate = useNavigate()
  const [status, setStatus] = useState<BlockchainStatus>(MOCK_STATUS)
  const [paramChanges, setParamChanges] = useState<ParameterChange[]>(MOCK_PARAM_CHANGES)
  const [apiAvailable, setApiAvailable] = useState(false)
  const [selectedClaimId, setSelectedClaimId] = useState('')
  const [explorerClaimId, setExplorerClaimId] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [statusRes, changesRes] = await Promise.all([
          fetch(`${API_URL}/api/v1/blockchain/status`),
          fetch(`${API_URL}/api/v1/blockchain/irdai/parameter-changes`),
        ])
        if (statusRes.ok) {
          setStatus(await statusRes.json())
          setApiAvailable(true)
        }
        if (changesRes.ok) {
          const data = await changesRes.json()
          setParamChanges(data.changes || data)
        }
      } catch {
        /* graceful degradation — use mock data */
      }
    }
    load()
  }, [])

  const stats = [
    { label: 'Chain Height', value: status.chain_height.toLocaleString(), icon: '🔗' },
    { label: 'Events Today', value: status.total_events_today.toString(), icon: '📋' },
    { label: 'Total Anchors', value: status.total_anchors.toLocaleString(), icon: '⛓️' },
    {
      label: 'Last Anchor',
      value: status.last_anchor_time
        ? new Date(status.last_anchor_time).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) + ' IST'
        : 'N/A',
      icon: '🕐',
    },
  ]

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
            <div className="w-6 h-6 sm:w-7 sm:h-7 bg-violet-500 rounded-lg flex items-center justify-center shadow-lg shadow-violet-500/20 text-sm">
              ⛓️
            </div>
            <div>
              <p className="text-white font-bold text-xs sm:text-sm leading-tight">ZoneChain Explorer</p>
              <p className="text-slate-500 text-xs hidden sm:block">Hyperledger Fabric + Polygon L2</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 sm:gap-2.5">
          <div className={`w-2 h-2 rounded-full ${apiAvailable ? 'bg-emerald-400' : 'bg-amber-400'} animate-pulse`} />
          <span className="text-slate-400 text-xs hidden sm:block">
            {apiAvailable ? 'Connected' : 'Demo Mode'} · Fabric {status.fabric_status} · Polygon {status.polygon_status}
          </span>
          <span className="text-slate-400 text-xs sm:hidden">
            {apiAvailable ? 'Live' : 'Demo'}
          </span>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-5 space-y-4 sm:space-y-5">
        {/* Stats Row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {stats.map(({ label, value, icon }) => (
            <div key={label} className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-4">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-base">{icon}</span>
                <span className="text-slate-400 text-xs uppercase tracking-wide">{label}</span>
              </div>
              <p className="text-white font-bold text-lg sm:text-xl">{value}</p>
            </div>
          ))}
        </div>

        {/* Claim Audit Trail Explorer */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-5">
          <div className="mb-4">
            <h2 className="text-white font-bold text-base sm:text-lg">Claim Audit Trail</h2>
            <p className="text-slate-400 text-xs mt-0.5">
              Enter a claim ID to view its immutable blockchain history
            </p>
          </div>
          <div className="flex gap-2 mb-4">
            <input
              type="text"
              placeholder="Enter claim ID..."
              value={selectedClaimId}
              onChange={(e) => setSelectedClaimId(e.target.value)}
              className="flex-1 bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-xs placeholder:text-slate-500 focus:outline-none focus:border-violet-500"
            />
            <button
              onClick={() => setExplorerClaimId(selectedClaimId || null)}
              disabled={!selectedClaimId.trim()}
              className="bg-violet-600 hover:bg-violet-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-bold px-4 py-2 rounded-lg transition-colors"
            >
              Explore
            </button>
          </div>

          {explorerClaimId && (
            <div className="bg-slate-900 border border-slate-700 rounded-xl p-4">
              <ZoneChainExplorerEmbed claimId={explorerClaimId} />
            </div>
          )}
        </div>

        {/* IRDAI Parameter Change Log */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-3 sm:p-5">
          <div className="flex items-center justify-between mb-3 sm:mb-4">
            <div>
              <h2 className="text-white font-bold text-base sm:text-lg">IRDAI Parameter Change Log</h2>
              <p className="text-slate-400 text-xs">On-chain record of all parametric rule changes</p>
            </div>
            <span className="text-xs text-slate-500 bg-slate-900 px-2.5 py-1 rounded-full border border-slate-700">
              {paramChanges.length} changes
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-700">
                  <th className="text-left text-slate-400 font-semibold py-2 pr-3">Parameter</th>
                  <th className="text-left text-slate-400 font-semibold py-2 pr-3">Old Value</th>
                  <th className="text-left text-slate-400 font-semibold py-2 pr-3">New Value</th>
                  <th className="text-left text-slate-400 font-semibold py-2 pr-3">Changed By</th>
                  <th className="text-left text-slate-400 font-semibold py-2">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {paramChanges.map((change) => (
                  <tr key={change.id} className="border-b border-slate-800 hover:bg-slate-900/50">
                    <td className="py-2.5 pr-3">
                      <span className="text-white font-medium">{change.parameter.replace(/_/g, ' ')}</span>
                    </td>
                    <td className="py-2.5 pr-3 text-red-400 font-mono">{change.old_value}</td>
                    <td className="py-2.5 pr-3 text-emerald-400 font-mono">{change.new_value}</td>
                    <td className="py-2.5 pr-3">
                      <span className={`px-2 py-0.5 rounded-full border text-xs ${
                        change.changed_by.includes('DAO')
                          ? 'bg-violet-500/20 text-violet-300 border-violet-500/30'
                          : 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                      }`}>
                        {change.changed_by}
                      </span>
                    </td>
                    <td className="py-2.5 text-slate-400">
                      <div>{new Date(change.timestamp).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</div>
                      {change.tx_hash && (
                        <span className="text-violet-400 font-mono text-[10px]">{change.tx_hash}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="text-center pb-4">
          <p className="text-slate-600 text-xs">
            ZoneChain v1.0 · Hyperledger Fabric (claim lifecycle) + Polygon Amoy (TemporalSig anchors)
          </p>
        </div>
      </main>
    </div>
  )
}

/**
 * Lazy-loaded ZoneChainExplorer embed wrapper.
 * Dynamically imports the component to avoid bundling it on every page.
 */
function ZoneChainExplorerEmbed({ claimId }: { claimId: string }) {
  const [Explorer, setExplorer] = useState<React.ComponentType<{ claimId: string; compact?: boolean }> | null>(null)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    import('../components/ZoneChainExplorer')
      .then((mod) => setExplorer(() => mod.default))
      .catch(() => setLoadError(true))
  }, [])

  if (loadError) {
    return (
      <div className="text-center py-8">
        <p className="text-slate-500 text-sm">Failed to load ZoneChain Explorer component</p>
      </div>
    )
  }

  if (!Explorer) {
    return (
      <div className="flex items-center justify-center py-8 gap-2 text-slate-400 text-sm">
        <span className="animate-spin">⛓️</span>
        <span>Loading explorer...</span>
      </div>
    )
  }

  return <Explorer claimId={claimId} />
}
