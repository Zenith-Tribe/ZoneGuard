import type {
  Zone, ZoneSignalData, PremiumBreakdown, PolicyData, Exclusion,
  RawRider, RawApiZone, RawApiClaim, RawApiPayout,
  KPI, SimulationResult,
} from '../types'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const method = options?.method?.toUpperCase() ?? 'GET'
  const needsBody = method !== 'GET' && method !== 'HEAD'
  const token = localStorage.getItem('zoneguard_token')
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(needsBody ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `API error: ${res.status}`)
  }
  return res.json()
}

export interface RegisterRiderPayload {
  rider_id?: string;
  id?: string;
  name: string;
  zone_id: string;
  weekly_earnings?: number;
  weekly_earnings_baseline?: number;
  phone?: string;
  tenure_weeks?: number;
  kyc_verified?: boolean;
  upi_id?: string;
  eshram_id?: string;
}

export interface CreatePolicyPayload {
  rider_id: string;
  zone_id: string;
  weekly_premium?: number;
  max_payout?: number;
  is_forward_locked?: boolean;
  forward_lock_weeks?: number;
}

export interface ClaimsParams {
  status?: string;
  zone_id?: string;
  rider_id?: string;
}

interface KPIResponse { kpis: KPI[] }
interface ScenariosResponse { [key: string]: { name: string; description: string; zone?: string } }

// Zones
export const getZones = () => fetchAPI<RawApiZone[]>('/api/v1/zones')
export const getZone = (id: string) => fetchAPI<RawApiZone>(`/api/v1/zones/${id}`)
export const getZoneSignals = (id: string) => fetchAPI<ZoneSignalData>(`/api/v1/zones/${id}/signals/current`)
export const getZoneRiskScore = (id: string) => fetchAPI<PremiumBreakdown>(`/api/v1/zones/${id}/risk-score`)

// Riders
export const registerRider = (data: RegisterRiderPayload) =>
  fetchAPI<RawRider>('/api/v1/riders/register', { method: 'POST', body: JSON.stringify(data) })
export const getRider = (id: string) => fetchAPI<RawRider>(`/api/v1/riders/${id}`)

// Policies
export const createPolicy = (data: CreatePolicyPayload) =>
  fetchAPI<PolicyData>('/api/v1/policies', { method: 'POST', body: JSON.stringify(data) })
export const getPolicies = (riderId?: string) =>
  fetchAPI<PolicyData[]>(`/api/v1/policies${riderId ? `?rider_id=${riderId}` : ''}`)
export const getPolicy = (id: string) => fetchAPI<PolicyData>(`/api/v1/policies/${id}`)
export const getPolicyExclusions = (id: string) => fetchAPI<Exclusion[]>(`/api/v1/policies/${id}/exclusions`)
export const renewPolicy = (id: string) =>
  fetchAPI<PolicyData & { new_policy?: PolicyData }>(`/api/v1/policies/${id}/renew`, { method: 'POST' })
export const cancelPolicy = (id: string) =>
  fetchAPI<PolicyData>(`/api/v1/policies/${id}/cancel`, { method: 'POST' })

// Premium
export const calculatePremium = (zoneId: string, riderId?: string) =>
  fetchAPI<PremiumBreakdown>(`/api/v1/premium/calculate?zone_id=${zoneId}${riderId ? `&rider_id=${riderId}` : ''}`)

// Claims
export const getClaims = (params?: ClaimsParams) => {
  const qs = params ? new URLSearchParams(params as Record<string, string>).toString() : ''
  return fetchAPI<RawApiClaim[]>(`/api/v1/claims${qs ? `?${qs}` : ''}`)
}
export const getClaim = (id: string) => fetchAPI<RawApiClaim>(`/api/v1/claims/${id}`)
export const reviewClaim = (id: string, action: 'approve' | 'reject') =>
  fetchAPI<RawApiClaim>(`/api/v1/claims/${id}/review`, {
    method: 'POST',
    body: JSON.stringify({ action, reviewed_by: 'admin' }),
  })

// Signals
export const pollSignals = (zoneId: string) =>
  fetchAPI<ZoneSignalData>(`/api/v1/signals/poll/${zoneId}`, { method: 'POST' })
export const getActiveEvents = () => fetchAPI<ZoneSignalData[]>('/api/v1/signals/active-events')

// Payouts
export const getPayouts = (riderId?: string) =>
  fetchAPI<RawApiPayout[]>(`/api/v1/payouts${riderId ? `?rider_id=${riderId}` : ''}`)

// Admin
export const getKPIs = () => fetchAPI<KPIResponse>('/api/v1/admin/kpis')

// Simulator
export const triggerSimulation = (zoneId: string, scenario: string) =>
  fetchAPI<SimulationResult>('/api/v1/simulator/trigger', {
    method: 'POST',
    body: JSON.stringify({ zone_id: zoneId, scenario }),
  })
export const getActiveSimulations = () => fetchAPI<SimulationResult[]>('/api/v1/simulator/active')
export const stopSimulation = (simId: string) =>
  fetchAPI<SimulationResult>(`/api/v1/simulator/stop/${simId}`, { method: 'DELETE' })
export const getScenarios = () => fetchAPI<ScenariosResponse>('/api/v1/simulator/scenarios')

// Chat
export const sendChatMessage = (message: string, riderId?: string) =>
  fetchAPI<{ response: string; source: string }>('/api/v1/chat', {
    method: 'POST',
    body: JSON.stringify({ message, rider_id: riderId }),
  })

// Notifications
export const getNotifications = (riderId: string) =>
  fetchAPI<{ id: string; rider_id: string; type: string; title: string; message: string; data: Record<string, unknown>; is_read: boolean; created_at: string }[]>(
    `/api/v1/notifications?rider_id=${riderId}`
  )
export const getUnreadCount = (riderId: string) =>
  fetchAPI<{ rider_id: string; unread_count: number }>(`/api/v1/notifications/unread-count?rider_id=${riderId}`)

// Admin (expanded)
export const getAdminClaims = (params?: { status?: string; zone_id?: string; page?: number; per_page?: number }) => {
  const qs = params ? new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))
  ).toString() : ''
  return fetchAPI<{ items: RawApiClaim[]; total: number; page: number; per_page: number; pages: number }>(
    `/api/v1/admin/claims${qs ? `?${qs}` : ''}`
  )
}
export const getAdminRiders = (params?: { zone_id?: string; kyc_verified?: boolean; page?: number }) => {
  const qs = params ? new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null).map(([k, v]) => [k, String(v)]))
  ).toString() : ''
  return fetchAPI<{ items: RawRider[]; total: number; page: number; pages: number }>(
    `/api/v1/admin/riders${qs ? `?${qs}` : ''}`
  )
}
export const getClaimAuditReport = (claimId: string) =>
  fetchAPI<{ claim_id: string; content: string; model_used: string; generated_at: string }>(
    `/api/v1/admin/claims/${claimId}/audit-report`
  )
export const getClaimsByZone = () =>
  fetchAPI<{ zone_id: string; zone_name: string; total_claims: number; approved: number; rejected: number; pending: number; total_payout: number }[]>(
    '/api/v1/admin/analytics/claims-by-zone'
  )
export const getPayoutsOverTime = (days?: number) =>
  fetchAPI<{ date: string; count: number; total_amount: number }[]>(
    `/api/v1/admin/analytics/payouts-over-time${days ? `?days=${days}` : ''}`
  )
export const getLossRatioTrend = () =>
  fetchAPI<{ date: string; premiums: number; payouts: number; loss_ratio: number }[]>(
    '/api/v1/admin/analytics/loss-ratio-trend'
  )
export const getPayoutStats = () =>
  fetchAPI<{ total: number; settled: number; failed: number; processing: number; avg_amount: number; total_amount: number; success_rate: number }>(
    '/api/v1/payouts/stats'
  )
export const retryPayout = (payoutId: string) =>
  fetchAPI<{ payout_id: string; status: string; retry_count: number; upi_ref: string }>(
    `/api/v1/payouts/${payoutId}/retry`, { method: 'POST' }
  )

// Forward Premium Lock
export const activateForwardLock = (policyId: string) =>
  fetchAPI<{ policy_id: string; is_forward_locked: boolean; weeks_remaining: number; original_premium: number; weekly_premium: number; discount_pct: number; savings_per_week: number; total_savings: number }>(
    `/api/v1/policies/${policyId}/forward-lock`, { method: 'POST' }
  )

// e-Shram KYC
export const verifyEShram = (riderId: string, eshramId: string) =>
  fetchAPI<{ status: string; eshram_id: string; verified: boolean; worker_name?: string; worker_category?: string; income_band?: string; message?: string }>(
    `/api/v1/riders/${riderId}/verify-eshram`, {
      method: 'POST',
      body: JSON.stringify({ eshram_id: eshramId }),
    }
  )

// FraudShield v2 — Federated Learning
export const trainFederatedModel = () =>
  fetchAPI<{ rounds_completed: number; convergence_history: number[]; per_client_stats: Record<string, unknown> }>(
    '/api/v1/admin/fraudshield/train', { method: 'POST' }
  )
export const getFederatedStatus = () =>
  fetchAPI<{ model_version: string; framework: string; aggregation: string; features: number; dpdp_compliant: boolean }>(
    '/api/v1/admin/fraudshield/status'
  )

// Temporal Clustering
export const getTemporalAnalysis = (zoneId: string) =>
  fetchAPI<{ zone_id: string; zone_name: string; total_claims: number; clustering_analysis: Record<string, unknown> | null; ring_detection: Record<string, unknown> | null }>(
    `/api/v1/admin/fraud/temporal-analysis/${zoneId}`
  )

// Re-export Zone for consumers that used the old `getZones` → Zone[] pattern
export type { Zone }
