/**
 * ZoneChainExplorer/index.tsx
 * ============================
 * Innovation 01 + 10: Read-only claim audit trail viewer.
 *
 * Shows riders their claim's full immutable history from ZoneChain (Fabric)
 * and the TemporalSig proof anchors from Polygon. Designed for:
 *   - RiderDashboard — "Why was my claim paid/rejected?"
 *   - Insurer dispute portal — audit trail with blockchain proof links
 *   - IRDAI regulatory viewer — anonymized parameter change log
 *
 * Props:
 *   claimId   — UUID of the claim to explore
 *   compact   — compact mode for dashboard card vs full page
 */

import { useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// Types (mirroring backend/blockchain/models.py)
// ---------------------------------------------------------------------------

type ChainEventType =
  | "CLAIM_CREATED"
  | "CLAIM_APPROVED"
  | "CLAIM_REJECTED"
  | "CLAIM_AUDITED"
  | "POLICY_CREATED"
  | "POLICY_RENEWED"
  | "PAYOUT_TRIGGERED"
  | "PAYOUT_COMPLETED"
  | "PARAMETER_CHANGED"
  | "SIGNAL_ANCHORED";

type ConfidenceTier = "HIGH" | "MEDIUM" | "LOW" | "NOISE";

interface ClaimEventPayload {
  claim_id: string;
  rider_id: string;
  policy_id: string;
  zone_id: string;
  event_type: ChainEventType;
  confidence_tier: ConfidenceTier;
  composite_score: number;
  payout_amount_inr?: number;
  rejection_reason?: string;
  claude_audit_summary?: string;
  signal_batch_ids: string[];
  temporalsig_polygon_tx?: string;
  temporalsig_block_number?: number;
  temporalsig_block_timestamp?: string;
}

interface ZoneChainEvent {
  event_id: string;
  event_type: ChainEventType;
  written_by: string;
  written_at: string;
  schema_version: string;
  claim_payload?: ClaimEventPayload;
}

interface TemporalSigAnchor {
  anchor_id: string;
  batch_id: string;
  zone_id: string;
  keccak256_hash: string;
  polygon_tx_hash?: string;
  polygon_block_number?: number;
  polygon_block_timestamp?: string;
  polygon_network: string;
  estimated_cost_usd?: number;
  status: "pending" | "confirmed" | "failed";
  dispute_proof_url?: string;
}

interface AuditTrail {
  claim_id: string;
  fabric_events: ZoneChainEvent[];
  temporalsig_anchors: TemporalSigAnchor[];
  dispute_proof_available: boolean;
  earliest_signal_timestamp?: string;
  latest_signal_timestamp?: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EVENT_CONFIG: Record<
  ChainEventType,
  { label: string; color: string; icon: string; bgColor: string }
> = {
  CLAIM_CREATED:    { label: "Claim Created",     color: "#3B82F6", icon: "📋", bgColor: "#EFF6FF" },
  CLAIM_APPROVED:   { label: "Claim Approved",    color: "#10B981", icon: "✅", bgColor: "#ECFDF5" },
  CLAIM_REJECTED:   { label: "Claim Rejected",    color: "#EF4444", icon: "❌", bgColor: "#FEF2F2" },
  CLAIM_AUDITED:    { label: "AI Audit Complete", color: "#8B5CF6", icon: "🤖", bgColor: "#F5F3FF" },
  POLICY_CREATED:   { label: "Policy Created",    color: "#F59E0B", icon: "📄", bgColor: "#FFFBEB" },
  POLICY_RENEWED:   { label: "Policy Renewed",    color: "#F59E0B", icon: "🔄", bgColor: "#FFFBEB" },
  PAYOUT_TRIGGERED: { label: "Payout Triggered",  color: "#10B981", icon: "💸", bgColor: "#ECFDF5" },
  PAYOUT_COMPLETED: { label: "Payout Sent",       color: "#059669", icon: "✔️", bgColor: "#ECFDF5" },
  PARAMETER_CHANGED:{ label: "Parameter Changed", color: "#6B7280", icon: "⚙️", bgColor: "#F9FAFB" },
  SIGNAL_ANCHORED:  { label: "Signal Anchored",   color: "#7C3AED", icon: "⛓️", bgColor: "#F5F3FF" },
};

const TIER_CONFIG: Record<ConfidenceTier, { label: string; color: string }> = {
  HIGH:   { label: "HIGH",   color: "#10B981" },
  MEDIUM: { label: "MEDIUM", color: "#F59E0B" },
  LOW:    { label: "LOW",    color: "#EF4444" },
  NOISE:  { label: "NOISE",  color: "#9CA3AF" },
};

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function HashBadge({ hash, label }: { hash: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const short = hash.slice(0, 10) + "…" + hash.slice(-6);

  const handleCopy = () => {
    navigator.clipboard.writeText(hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <span
      onClick={handleCopy}
      title={hash}
      style={{
        fontFamily: "monospace",
        fontSize: "11px",
        background: "#1E1E2E",
        color: "#A78BFA",
        padding: "2px 8px",
        borderRadius: "4px",
        cursor: "pointer",
        userSelect: "none",
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
      }}
    >
      {label && <span style={{ color: "#6B7280", fontFamily: "sans-serif" }}>{label}:</span>}
      {copied ? "✓ Copied" : short}
    </span>
  );
}

function PolygonLink({ url, label }: { url: string; label?: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "4px",
        fontSize: "11px",
        color: "#8B5CF6",
        textDecoration: "none",
        padding: "2px 8px",
        background: "#F5F3FF",
        borderRadius: "4px",
        border: "1px solid #DDD6FE",
        fontWeight: 500,
      }}
    >
      ⛓️ {label ?? "PolygonScan ↗"}
    </a>
  );
}

function TemporalProofBanner({
  earliestTs,
  anchors,
}: {
  earliestTs?: string;
  anchors: TemporalSigAnchor[];
}) {
  if (!earliestTs || anchors.length === 0) return null;
  const confirmedAnchors = anchors.filter((a) => a.status === "confirmed");
  if (confirmedAnchors.length === 0) return null;

  return (
    <div
      style={{
        background: "linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%)",
        borderRadius: "12px",
        padding: "16px 20px",
        color: "white",
        marginBottom: "20px",
        boxShadow: "0 4px 12px rgba(79,70,229,0.3)",
      }}
    >
      <div style={{ fontSize: "12px", opacity: 0.85, marginBottom: "4px", fontWeight: 600 }}>
        ⛓️ TEMPORALSIG PROOF — DISRUPTION DETECTED AT
      </div>
      <div style={{ fontSize: "20px", fontWeight: 700, letterSpacing: "-0.5px", marginBottom: "8px" }}>
        {new Date(earliestTs).toLocaleString("en-IN", {
          timeZone: "Asia/Kolkata",
          dateStyle: "medium",
          timeStyle: "medium",
        })}{" "}
        IST
      </div>
      <div style={{ fontSize: "11px", opacity: 0.8 }}>
        Certified by Polygon consensus • Cannot be retroactively altered by any party
        • {confirmedAnchors.length} anchor(s) on-chain
      </div>
    </div>
  );
}

function EventCard({ event }: { event: ZoneChainEvent }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = EVENT_CONFIG[event.event_type] ?? {
    label: event.event_type,
    color: "#6B7280",
    icon: "📌",
    bgColor: "#F9FAFB",
  };
  const cp = event.claim_payload;

  return (
    <div
      style={{
        border: `1px solid ${cfg.color}30`,
        borderLeft: `4px solid ${cfg.color}`,
        borderRadius: "8px",
        background: cfg.bgColor,
        padding: "12px 16px",
        marginBottom: "10px",
        cursor: "pointer",
        transition: "box-shadow 0.15s",
      }}
      onClick={() => setExpanded((e) => !e)}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ fontSize: "18px" }}>{cfg.icon}</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: "14px", color: cfg.color }}>
              {cfg.label}
            </div>
            <div style={{ fontSize: "11px", color: "#6B7280", marginTop: "2px" }}>
              {new Date(event.written_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {cp && (
            <span
              style={{
                fontSize: "11px",
                fontWeight: 700,
                color: TIER_CONFIG[cp.confidence_tier]?.color ?? "#6B7280",
                background: "white",
                padding: "2px 8px",
                borderRadius: "10px",
                border: `1px solid ${TIER_CONFIG[cp.confidence_tier]?.color ?? "#6B7280"}40`,
              }}
            >
              {cp.confidence_tier}
            </span>
          )}
          <span style={{ color: "#9CA3AF", fontSize: "12px" }}>{expanded ? "▲" : "▼"}</span>
        </div>
      </div>

      {expanded && (
        <div
          style={{
            marginTop: "12px",
            paddingTop: "12px",
            borderTop: `1px solid ${cfg.color}20`,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Fabric event metadata */}
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "10px" }}>
            <HashBadge hash={event.event_id} label="event_id" />
            <span
              style={{
                fontSize: "10px",
                color: "#6B7280",
                padding: "2px 8px",
                background: "#F3F4F6",
                borderRadius: "4px",
              }}
            >
              Hyperledger Fabric • {event.written_by} • v{event.schema_version}
            </span>
          </div>

          {/* Claim-specific fields */}
          {cp && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
              <div>
                <span style={{ color: "#6B7280" }}>Composite Score: </span>
                <strong>{(cp.composite_score * 100).toFixed(1)}%</strong>
              </div>
              {cp.payout_amount_inr && (
                <div>
                  <span style={{ color: "#6B7280" }}>Payout: </span>
                  <strong style={{ color: "#10B981" }}>
                    ₹{cp.payout_amount_inr.toLocaleString("en-IN")}
                  </strong>
                </div>
              )}
              {cp.rejection_reason && (
                <div style={{ gridColumn: "1 / -1" }}>
                  <span style={{ color: "#6B7280" }}>Rejection Reason: </span>
                  <span style={{ color: "#EF4444" }}>{cp.rejection_reason}</span>
                </div>
              )}
              {cp.claude_audit_summary && (
                <div
                  style={{
                    gridColumn: "1 / -1",
                    background: "#F5F3FF",
                    borderRadius: "6px",
                    padding: "8px 10px",
                    fontSize: "12px",
                    borderLeft: "3px solid #8B5CF6",
                  }}
                >
                  <div style={{ fontWeight: 600, color: "#7C3AED", marginBottom: "4px" }}>
                    🤖 Claude AI Audit
                  </div>
                  {cp.claude_audit_summary}
                </div>
              )}
              {cp.temporalsig_polygon_tx && (
                <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "center", gap: "8px" }}>
                  <PolygonLink
                    url={`https://amoy.polygonscan.com/tx/${cp.temporalsig_polygon_tx}`}
                    label="TemporalSig Proof"
                  />
                  {cp.temporalsig_block_timestamp && (
                    <span style={{ fontSize: "11px", color: "#6B7280" }}>
                      Block timestamp:{" "}
                      {new Date(cp.temporalsig_block_timestamp).toLocaleString("en-IN", {
                        timeZone: "Asia/Kolkata",
                      })}{" "}
                      IST
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AnchorCard({ anchor }: { anchor: TemporalSigAnchor }) {
  return (
    <div
      style={{
        border: "1px solid #DDD6FE",
        borderRadius: "8px",
        padding: "10px 14px",
        marginBottom: "8px",
        background: "#FAFAFA",
        fontSize: "12px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background:
                anchor.status === "confirmed"
                  ? "#10B981"
                  : anchor.status === "failed"
                  ? "#EF4444"
                  : "#F59E0B",
              display: "inline-block",
              flexShrink: 0,
            }}
          />
          <div>
            <div style={{ fontWeight: 600, color: "#374151" }}>
              Batch {anchor.batch_id.slice(0, 8)}…
            </div>
            <div style={{ color: "#6B7280", marginTop: "2px" }}>
              {anchor.polygon_block_timestamp
                ? new Date(anchor.polygon_block_timestamp).toLocaleString("en-IN", {
                    timeZone: "Asia/Kolkata",
                  }) + " IST"
                : "Pending"}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          {anchor.estimated_cost_usd && (
            <span style={{ color: "#6B7280", fontSize: "10px" }}>
              ${anchor.estimated_cost_usd.toFixed(5)}
            </span>
          )}
          {anchor.dispute_proof_url && (
            <PolygonLink url={anchor.dispute_proof_url} />
          )}
        </div>
      </div>
      <div style={{ marginTop: "6px" }}>
        <HashBadge hash={anchor.keccak256_hash} label="keccak256" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface ZoneChainExplorerProps {
  claimId: string;
  compact?: boolean;
}

export default function ZoneChainExplorer({
  claimId,
  compact = false,
}: ZoneChainExplorerProps) {
  const [trail, setTrail] = useState<AuditTrail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"events" | "anchors">("events");

  useEffect(() => {
    if (!claimId) return;
    setLoading(true);
    setError(null);

    fetch(`${API_BASE}/api/v1/blockchain/claims/${claimId}/audit-trail`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: AuditTrail) => setTrail(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [claimId]);

  // ------ Loading State ------
  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px",
          gap: "12px",
          color: "#6B7280",
        }}
      >
        <div style={{ fontSize: "28px", animation: "spin 1s linear infinite" }}>⛓️</div>
        <div style={{ fontSize: "14px" }}>Loading ZoneChain audit trail…</div>
        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  // ------ Error State ------
  if (error) {
    return (
      <div
        style={{
          padding: "20px",
          background: "#FEF2F2",
          borderRadius: "8px",
          border: "1px solid #FECACA",
          color: "#DC2626",
          fontSize: "13px",
        }}
      >
        <strong>Failed to load blockchain audit trail</strong>
        <br />
        <span style={{ color: "#6B7280" }}>{error}</span>
      </div>
    );
  }

  if (!trail) return null;

  const containerStyle: React.CSSProperties = compact
    ? { fontSize: "13px" }
    : {
        maxWidth: "760px",
        margin: "0 auto",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      };

  return (
    <div style={containerStyle}>
      {/* Header */}
      {!compact && (
        <div style={{ marginBottom: "20px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "6px" }}>
            <span style={{ fontSize: "22px" }}>⛓️</span>
            <h2 style={{ margin: 0, fontSize: "20px", fontWeight: 700, color: "#111827" }}>
              ZoneChain Audit Trail
            </h2>
          </div>
          <div style={{ fontSize: "12px", color: "#6B7280" }}>
            Claim ID:{" "}
            <code
              style={{
                background: "#F3F4F6",
                padding: "2px 6px",
                borderRadius: "4px",
                fontSize: "11px",
              }}
            >
              {claimId}
            </code>{" "}
            • Immutable record on Hyperledger Fabric + Polygon L2
          </div>
        </div>
      )}

      {/* TemporalSig Banner — shows if disruption timestamp is proven */}
      <TemporalProofBanner
        earliestTs={trail.earliest_signal_timestamp}
        anchors={trail.temporalsig_anchors}
      />

      {/* Dispute proof available badge */}
      {trail.dispute_proof_available && !compact && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            background: "#ECFDF5",
            border: "1px solid #A7F3D0",
            borderRadius: "8px",
            padding: "10px 14px",
            marginBottom: "16px",
            fontSize: "12px",
            color: "#065F46",
          }}
        >
          <span style={{ fontSize: "16px" }}>🔒</span>
          <div>
            <strong>Blockchain proof available.</strong> This claim has{" "}
            {trail.temporalsig_anchors.length} TemporalSig anchor(s) on Polygon.
            Any dispute can be resolved by verifying the on-chain hash.
          </div>
        </div>
      )}

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: "4px",
          marginBottom: "16px",
          background: "#F3F4F6",
          borderRadius: "8px",
          padding: "4px",
        }}
      >
        {(["events", "anchors"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              padding: "6px 12px",
              border: "none",
              borderRadius: "6px",
              cursor: "pointer",
              fontSize: "13px",
              fontWeight: 600,
              background: activeTab === tab ? "white" : "transparent",
              color: activeTab === tab ? "#4F46E5" : "#6B7280",
              boxShadow: activeTab === tab ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              transition: "all 0.15s",
            }}
          >
            {tab === "events"
              ? `📋 Fabric Events (${trail.fabric_events.length})`
              : `⛓️ Polygon Anchors (${trail.temporalsig_anchors.length})`}
          </button>
        ))}
      </div>

      {/* Events Tab */}
      {activeTab === "events" && (
        <div>
          {trail.fabric_events.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "32px",
                color: "#9CA3AF",
                fontSize: "13px",
              }}
            >
              No Fabric events found for this claim.
              <br />
              <span style={{ fontSize: "11px" }}>
                (Fabric may be in stub mode — check /api/v1/blockchain/status)
              </span>
            </div>
          ) : (
            trail.fabric_events.map((event) => (
              <EventCard key={event.event_id} event={event} />
            ))
          )}
        </div>
      )}

      {/* Anchors Tab */}
      {activeTab === "anchors" && (
        <div>
          {trail.temporalsig_anchors.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "32px",
                color: "#9CA3AF",
                fontSize: "13px",
              }}
            >
              No TemporalSig anchors linked to this claim.
              <br />
              <span style={{ fontSize: "11px" }}>
                Anchors are linked when a claim is created from a signal batch.
              </span>
            </div>
          ) : (
            trail.temporalsig_anchors.map((anchor) => (
              <AnchorCard key={anchor.anchor_id} anchor={anchor} />
            ))
          )}

          {!compact && (
            <div
              style={{
                marginTop: "12px",
                padding: "12px",
                background: "#F5F3FF",
                borderRadius: "8px",
                fontSize: "11px",
                color: "#6B7280",
              }}
            >
              <strong style={{ color: "#7C3AED" }}>How TemporalSig works: </strong>
              Every 15 minutes, ZoneGuard hashes all 4 signal readings (Environmental,
              Mobility, Economic, Crowd) using keccak256 and anchors the hash to
              Polygon. The Polygon block.timestamp — set by network consensus, not
              ZoneGuard — becomes the certified proof of when a disruption was detected.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
