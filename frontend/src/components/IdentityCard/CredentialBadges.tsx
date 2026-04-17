// frontend/src/components/IdentityCard/CredentialBadges.tsx
// ─────────────────────────────────────────────────────────────────────────────
// ZoneGuard CrossRider DID Passport — Credential Badge System
//
// Renders visual badges for each Verifiable Credential the rider holds.
// Badges are color-coded by credential type and show verification status.
//
// CREDENTIAL TYPES:
//   🟢 FlexWorkerIdentityCredential  — ZK-proven Flex worker
//   🔵 EShramRegistrationCredential  — Active e-Shram UAN
//   🟣 IncomeBracketCredential       — ZK earnings range proof
//   🟠 PlatformTenureCredential      — Multi-platform career
//   🥇 LoyaltyDiscountCredential     — 12+ weeks loyalty reward
//
// USAGE:
//   <CredentialBadges credentials={passport.credentials} compact={false} />

import { useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CredentialSubject {
  id: string;
  platform?: string;
  zone?: string;
  kyc_method?: string;
  nullifier?: string;
  income_bracket?: "low" | "mid" | "high";
  weeks_proven?: number;
  tenure_weeks?: number;
  multi_platform?: boolean;
  platforms?: string[];
  discount_tier?: "bronze" | "silver" | "gold";
  discount_percent?: number;
  bracket_verified_by?: string;
}

interface VerifiableCredential {
  id: string;
  type: string[];
  issuer: string;
  issuance_date: string;
  expiration_date?: string;
  credential_subject: CredentialSubject;
  proof?: object;
  progressive_disclosure_level: number;
}

interface CredentialBadgesProps {
  credentials: VerifiableCredential[];
  compact?: boolean;
}

// ─── Credential Config ────────────────────────────────────────────────────────

interface BadgeConfig {
  icon: string;
  label: string;
  shortLabel: string;
  bg: string;
  border: string;
  text: string;
  tagBg: string;
  tagText: string;
  getDetail: (subject: CredentialSubject) => string;
  getTag: (subject: CredentialSubject) => string;
  proofMethod: string;
}

const BADGE_CONFIGS: Record<string, BadgeConfig> = {
  FlexWorkerIdentityCredential: {
    icon: "📦",
    label: "Flex Worker Identity",
    shortLabel: "Flex ID",
    bg: "#EFF6FF",
    border: "#BFDBFE",
    text: "#1D4ED8",
    tagBg: "#DBEAFE",
    tagText: "#1E40AF",
    getDetail: (s) => `Zone: ${s.zone?.toUpperCase() || "–"}`,
    getTag: () => "ZK-SNARK Proven",
    proofMethod: "Groth16 zk-SNARK",
  },
  EShramRegistrationCredential: {
    icon: "🏛️",
    label: "e-Shram Registered",
    shortLabel: "e-Shram",
    bg: "#F0FDF4",
    border: "#BBF7D0",
    text: "#15803D",
    tagBg: "#DCFCE7",
    tagText: "#166534",
    getDetail: () => "Active Registration",
    getTag: () => "Gov. Verified",
    proofMethod: "ZK Membership Proof",
  },
  IncomeBracketCredential: {
    icon: "💰",
    label: "Income Bracket",
    shortLabel: "Income",
    bg: "#FAF5FF",
    border: "#DDD6FE",
    text: "#7C3AED",
    tagBg: "#EDE9FE",
    tagText: "#5B21B6",
    getDetail: (s) => {
      const bracketLabels: Record<string, string> = {
        low: "< ₹10K/wk",
        mid: "₹10K–₹20K/wk",
        high: "> ₹20K/wk",
      };
      const bracket = s.income_bracket || "unknown";
      return bracketLabels[bracket] || bracket;
    },
    getTag: (s) => `${s.weeks_proven || 0} weeks proven`,
    proofMethod: "ZK Range Proof",
  },
  PlatformTenureCredential: {
    icon: "🏆",
    label: "Platform Tenure",
    shortLabel: "Tenure",
    bg: "#FFF7ED",
    border: "#FED7AA",
    text: "#C2410C",
    tagBg: "#FFEDD5",
    tagText: "#9A3412",
    getDetail: (s) => {
      if (s.multi_platform && s.platforms && s.platforms.length > 1) {
        return `${s.platforms.length} platforms · ${s.tenure_weeks}w`;
      }
      return `${s.tenure_weeks || 0} weeks active`;
    },
    getTag: (s) => s.multi_platform ? "Multi-platform" : "Single platform",
    proofMethod: "Payout History",
  },
  LoyaltyDiscountCredential: {
    icon: "⭐",
    label: "Loyalty Discount",
    shortLabel: "Loyalty",
    bg: "#FFFBEB",
    border: "#FDE68A",
    text: "#B45309",
    tagBg: "#FEF3C7",
    tagText: "#92400E",
    getDetail: (s) => `${s.discount_percent || 0}% premium discount`,
    getTag: (s) => {
      const tierEmoji: Record<string, string> = { bronze: "🥉", silver: "🥈", gold: "🥇" };
      return `${tierEmoji[s.discount_tier || ""] || ""} ${(s.discount_tier || "").charAt(0).toUpperCase() + (s.discount_tier || "").slice(1)} tier`;
    },
    proofMethod: "Tenure Verified",
  },
};

// Get config for a credential based on its type array
function getCredentialConfig(types: string[]): BadgeConfig | null {
  for (const type of types) {
    if (BADGE_CONFIGS[type]) return BADGE_CONFIGS[type];
  }
  return null;
}

function isExpired(expDate?: string): boolean {
  if (!expDate) return false;
  return new Date(expDate) < new Date();
}

function daysUntilExpiry(expDate?: string): number | null {
  if (!expDate) return null;
  const diff = new Date(expDate).getTime() - Date.now();
  return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

// ─── Single Badge ─────────────────────────────────────────────────────────────

function CredentialBadge({
  credential,
  compact,
  onClick,
}: {
  credential: VerifiableCredential;
  compact: boolean;
  onClick: () => void;
}) {
  const config = getCredentialConfig(credential.type);
  if (!config) return null;

  const expired = isExpired(credential.expiration_date);
  const daysLeft = daysUntilExpiry(credential.expiration_date);
  const expiringSoon = daysLeft !== null && daysLeft <= 7 && !expired;
  const { credential_subject: subject } = credential;

  if (compact) {
    return (
      <button
        onClick={onClick}
        title={config.label}
        style={{
          background: expired ? "#F9FAFB" : config.bg,
          border: `1px solid ${expired ? "#E5E7EB" : config.border}`,
          borderRadius: 8,
          padding: "6px 10px",
          display: "flex",
          alignItems: "center",
          gap: 5,
          cursor: "pointer",
          opacity: expired ? 0.5 : 1,
          transition: "transform 0.1s",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.transform = "scale(1.05)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.transform = "scale(1)"; }}
      >
        <span style={{ fontSize: 14 }}>{config.icon}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: expired ? "#9CA3AF" : config.text }}>
          {config.shortLabel}
        </span>
        {expired && <span style={{ fontSize: 9, color: "#EF4444" }}>EXP</span>}
        {expiringSoon && !expired && <span style={{ fontSize: 9, color: "#F59E0B" }}>⚠</span>}
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      style={{
        background: expired ? "#F9FAFB" : config.bg,
        border: `1px solid ${expired ? "#E5E7EB" : config.border}`,
        borderRadius: 10,
        padding: "10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        opacity: expired ? 0.6 : 1,
        transition: "all 0.15s ease",
        position: "relative",
        overflow: "hidden",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 12px rgba(0,0,0,0.1)";
        (e.currentTarget as HTMLElement).style.transform = "translateY(-1px)";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.boxShadow = "none";
        (e.currentTarget as HTMLElement).style.transform = "translateY(0)";
      }}
    >
      {/* Proof verified ribbon */}
      {credential.proof && !expired && (
        <div style={{
          position: "absolute",
          top: 0,
          right: 0,
          width: 0,
          height: 0,
          borderStyle: "solid",
          borderWidth: "0 20px 20px 0",
          borderColor: `transparent ${config.border} transparent transparent`,
        }} />
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 18 }}>{config.icon}</span>
          <span style={{
            fontSize: 12,
            fontWeight: 700,
            color: expired ? "#9CA3AF" : config.text,
          }}>
            {config.label}
          </span>
        </div>
        {expired ? (
          <span style={{
            fontSize: 10,
            background: "#FEE2E2",
            color: "#DC2626",
            borderRadius: 99,
            padding: "2px 6px",
            fontWeight: 700,
          }}>EXPIRED</span>
        ) : (
          <span style={{
            fontSize: 10,
            background: config.tagBg,
            color: config.tagText,
            borderRadius: 99,
            padding: "2px 7px",
            fontWeight: 600,
          }}>
            {config.getTag(subject)}
          </span>
        )}
      </div>

      <div style={{ fontSize: 12, color: expired ? "#9CA3AF" : config.text, fontWeight: 500, paddingLeft: 25 }}>
        {config.getDetail(subject)}
      </div>

      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        paddingLeft: 25,
      }}>
        <span style={{ fontSize: 10, color: "#94A3B8" }}>
          {config.proofMethod} · {credential.progressive_disclosure_level === 1 ? "L1" : credential.progressive_disclosure_level === 2 ? "L2" : "L3"}
        </span>
        {expiringSoon && !expired && (
          <span style={{ fontSize: 10, color: "#F59E0B", fontWeight: 600 }}>
            ⚠ {daysLeft}d left
          </span>
        )}
      </div>
    </button>
  );
}

// ─── Credential Detail Modal ──────────────────────────────────────────────────

function CredentialModal({
  credential,
  onClose,
}: {
  credential: VerifiableCredential;
  onClose: () => void;
}) {
  const config = getCredentialConfig(credential.type);
  if (!config) return null;

  const { credential_subject: subject } = credential;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 16,
          padding: 24,
          maxWidth: 380,
          width: "100%",
          boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <span style={{ fontSize: 28 }}>{config.icon}</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: "#0F172A" }}>{config.label}</div>
            <div style={{ fontSize: 12, color: "#64748B" }}>W3C Verifiable Credential</div>
          </div>
        </div>

        {/* VC Fields */}
        {[
          ["Issuer", "ZoneGuard · did:key:z6MkZone…"],
          ["Subject DID", subject.id ? subject.id.substring(0, 28) + "…" : "–"],
          ["Issued", new Date(credential.issuance_date).toLocaleDateString("en-IN")],
          ["Expires", credential.expiration_date
            ? new Date(credential.expiration_date).toLocaleDateString("en-IN")
            : "No expiry"],
          ["Proof Method", config.proofMethod],
          ["Disclosure Level", `Level ${credential.progressive_disclosure_level}`],
          ["Signature", credential.proof ? "✅ Ed25519Signature2020" : "⚠️ Unsigned"],
        ].map(([label, value]) => (
          <div key={label} style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "8px 0",
            borderBottom: "1px solid #F1F5F9",
          }}>
            <span style={{ fontSize: 12, color: "#64748B" }}>{label}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#0F172A", textAlign: "right", maxWidth: "55%" }}>
              {value}
            </span>
          </div>
        ))}

        {/* Privacy note */}
        <div style={{
          marginTop: 16,
          background: "#F0FDF4",
          border: "1px solid #BBF7D0",
          borderRadius: 8,
          padding: "10px 12px",
          fontSize: 11,
          color: "#166534",
          lineHeight: 1.5,
        }}>
          🔒 This credential contains zero PII. Your identity is proven
          cryptographically via zk-SNARKs. Only this credential badge
          — not your personal data — is shared when you present it.
        </div>

        <button
          onClick={onClose}
          style={{
            marginTop: 16,
            width: "100%",
            background: "#F1F5F9",
            border: "1px solid #E2E8F0",
            borderRadius: 8,
            padding: "10px",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            color: "#475569",
          }}
        >
          Close
        </button>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function CredentialBadges({ credentials, compact = false }: CredentialBadgesProps) {
  const [selectedVC, setSelectedVC] = useState<VerifiableCredential | null>(null);

  if (!credentials || credentials.length === 0) {
    return (
      <div style={{
        background: "#F8FAFC",
        borderRadius: 10,
        padding: "14px 16px",
        textAlign: "center",
        border: "1px dashed #CBD5E1",
      }}>
        <div style={{ fontSize: 24, marginBottom: 6 }}>🔐</div>
        <div style={{ fontSize: 12, color: "#94A3B8" }}>
          No credentials yet. Complete ZK verification to earn your first badge.
        </div>
      </div>
    );
  }

  return (
    <>
      <div>
        {!compact && (
          <div style={{
            fontSize: 11,
            color: "#94A3B8",
            fontWeight: 600,
            letterSpacing: "0.08em",
            marginBottom: 8,
          }}>
            VERIFIABLE CREDENTIALS ({credentials.length})
          </div>
        )}

        <div style={{
          display: "flex",
          flexDirection: compact ? "row" : "column",
          gap: compact ? 6 : 8,
          flexWrap: compact ? "wrap" : "nowrap",
        }}>
          {credentials.map((vc) => (
            <CredentialBadge
              key={vc.id}
              credential={vc}
              compact={compact}
              onClick={() => setSelectedVC(vc)}
            />
          ))}
        </div>
      </div>

      {selectedVC && (
        <CredentialModal
          credential={selectedVC}
          onClose={() => setSelectedVC(null)}
        />
      )}
    </>
  );
}
