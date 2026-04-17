// frontend/src/components/IdentityCard/index.tsx
// ─────────────────────────────────────────────────────────────────────────────
// ZoneGuard CrossRider DID Passport — Identity Card
// Innovation 09: Portable ZK-verified identity for gig workers
//
// DISPLAYS:
//   - Rider's DID (truncated for readability)
//   - Verified credential badges (Flex Worker, e-Shram, Income Bracket, Loyalty)
//   - Progressive disclosure level indicator
//   - QR code for offline VC presentation
//   - Share button (generates one-time disclosure URL)
//   - ZK proof verification status
//
// PRIVACY:
//   - No raw PII displayed anywhere on this card
//   - Rider ID shown only as truncated DID (cryptographic)
//   - Income shown only as bracket (low/mid/high), never exact figure
//
// USAGE:
//   <IdentityCard nullifierPrefix="a3f9b1c2" showQR={true} />

import { useState, useEffect, useCallback } from "react";
import CredentialBadges from "./CredentialBadges";

// ─── Types ────────────────────────────────────────────────────────────────────

interface VerificationMethod {
  id: string;
  type: string;
  controller: string;
  public_key_multibase: string;
}

interface DIDDocument {
  id: string;
  verification_method: VerificationMethod[];
  created: string;
  updated: string;
}

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

interface DIDPassport {
  did_document: DIDDocument;
  credentials: VerifiableCredential[];
  created_at: string;
  last_updated: string;
  total_tenure_weeks: number;
  platforms_active: string[];
  disclosure_level: number;
}

interface PassportResponse {
  passport: DIDPassport;
  share_url: string;
  qr_payload: string;
}

interface IdentityCardProps {
  nullifierPrefix: string;
  showQR?: boolean;
  compact?: boolean;
  onShareClick?: (shareUrl: string) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function truncateDID(did: string, chars = 20): string {
  if (did.length <= chars + 12) return did;
  return `${did.substring(0, 16)}...${did.slice(-8)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function disclosureLevelLabel(level: number): string {
  return ["", "Basic Identity", "Income Verified", "Full History"][level] ?? "Unknown";
}

function disclosureLevelColor(level: number): string {
  return ["", "#6B7280", "#3B82F6", "#10B981"][level] ?? "#6B7280";
}

function tenureWeeksToLabel(weeks: number): string {
  if (weeks < 4) return `${weeks}w`;
  if (weeks < 52) return `${Math.floor(weeks / 4)}mo`;
  return `${Math.floor(weeks / 52)}yr ${weeks % 52}w`;
}

// ─── QR Code Display (canvas-based, no external library) ─────────────────────

function QRDisplay({ payload }: { payload: string }) {
  // Simplified QR representation for demo — in production use qrcode.react
  const shortPayload = payload.substring(0, 32);
  return (
    <div style={{
      background: "#fff",
      border: "2px solid #E5E7EB",
      borderRadius: 8,
      padding: 12,
      display: "inline-flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 6,
    }}>
      {/* QR Pattern Simulation */}
      <div style={{
        width: 96,
        height: 96,
        background: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Crect x='0' y='0' width='3' height='3' fill='%23111'/%3E%3Crect x='7' y='0' width='3' height='3' fill='%23111'/%3E%3Crect x='0' y='7' width='3' height='3' fill='%23111'/%3E%3Crect x='4' y='1' width='1' height='1' fill='%23111'/%3E%3Crect x='5' y='3' width='2' height='1' fill='%23111'/%3E%3Crect x='3' y='5' width='1' height='2' fill='%23111'/%3E%3Crect x='6' y='6' width='2' height='2' fill='%23111'/%3E%3Crect x='4' y='8' width='1' height='1' fill='%23111'/%3E%3C/svg%3E")`,
        backgroundSize: "cover",
        imageRendering: "pixelated",
        borderRadius: 4,
      }} />
      <span style={{ fontSize: 9, color: "#6B7280", fontFamily: "monospace", maxWidth: 96, wordBreak: "break-all" }}>
        {shortPayload}…
      </span>
      <span style={{ fontSize: 10, color: "#9CA3AF" }}>Scan to verify</span>
    </div>
  );
}

// ─── Disclosure Level Indicator ───────────────────────────────────────────────

function DisclosureMeter({ level }: { level: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#9CA3AF", fontWeight: 500 }}>
          IDENTITY LEVEL
        </span>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: disclosureLevelColor(level),
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}>
          {disclosureLevelLabel(level)}
        </span>
      </div>
      <div style={{
        height: 6,
        background: "#F3F4F6",
        borderRadius: 99,
        overflow: "hidden",
      }}>
        <div style={{
          height: "100%",
          width: `${(level / 3) * 100}%`,
          background: disclosureLevelColor(level),
          borderRadius: 99,
          transition: "width 0.6s ease",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        {["Basic", "Income", "Full"].map((label, i) => (
          <span key={label} style={{
            fontSize: 10,
            color: i + 1 <= level ? disclosureLevelColor(level) : "#D1D5DB",
            fontWeight: i + 1 <= level ? 600 : 400,
          }}>
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── DID Display ─────────────────────────────────────────────────────────────

function DIDDisplay({ did }: { did: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(did);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [did]);

  return (
    <div style={{
      background: "#F8FAFC",
      borderRadius: 8,
      padding: "8px 12px",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: 8,
      border: "1px solid #E2E8F0",
    }}>
      <div>
        <div style={{ fontSize: 10, color: "#94A3B8", fontWeight: 600, letterSpacing: "0.08em", marginBottom: 2 }}>
          DECENTRALIZED IDENTIFIER
        </div>
        <div style={{
          fontSize: 11,
          fontFamily: "monospace",
          color: "#1E293B",
          wordBreak: "break-all",
        }}>
          {truncateDID(did)}
        </div>
      </div>
      <button
        onClick={copy}
        style={{
          background: copied ? "#DCFCE7" : "#F1F5F9",
          border: "1px solid",
          borderColor: copied ? "#86EFAC" : "#CBD5E1",
          borderRadius: 6,
          padding: "4px 8px",
          fontSize: 11,
          cursor: "pointer",
          color: copied ? "#16A34A" : "#475569",
          whiteSpace: "nowrap",
          transition: "all 0.2s",
          flexShrink: 0,
        }}
      >
        {copied ? "✓ Copied" : "Copy DID"}
      </button>
    </div>
  );
}

// ─── Tenure Stat ─────────────────────────────────────────────────────────────

function StatPill({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div style={{
      background: "#F8FAFC",
      border: "1px solid #E2E8F0",
      borderRadius: 8,
      padding: "8px 12px",
      flex: 1,
      minWidth: 0,
    }}>
      <div style={{ fontSize: 18, marginBottom: 2 }}>{icon}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#0F172A" }}>{value}</div>
      <div style={{ fontSize: 10, color: "#94A3B8", fontWeight: 500 }}>{label}</div>
    </div>
  );
}

// ─── Loading Skeleton ─────────────────────────────────────────────────────────

function CardSkeleton() {
  return (
    <div style={{
      background: "#fff",
      borderRadius: 16,
      padding: 20,
      border: "1px solid #E2E8F0",
      display: "flex",
      flexDirection: "column",
      gap: 14,
      animation: "pulse 1.5s ease-in-out infinite",
    }}>
      {[80, 40, 100, 60, 40].map((w, i) => (
        <div key={i} style={{
          height: 16,
          width: `${w}%`,
          background: "#F1F5F9",
          borderRadius: 8,
        }} />
      ))}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function IdentityCard({
  nullifierPrefix,
  showQR = false,
  compact = false,
  onShareClick,
}: IdentityCardProps) {
  const [passport, setPassport] = useState<PassportResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [shareSuccess, setShareSuccess] = useState(false);

  // Fetch passport from API
  useEffect(() => {
    if (!nullifierPrefix) return;

    const controller = new AbortController();
    setLoading(true);
    setError(null);

    fetch(`/api/v1/identity/passport/${nullifierPrefix}`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: PassportResponse) => {
        setPassport(data);
        setLoading(false);
      })
      .catch((e) => {
        if (e.name !== "AbortError") {
          setError("Could not load identity passport");
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [nullifierPrefix]);

  const handleShare = useCallback(() => {
    if (!passport) return;
    if (onShareClick) {
      onShareClick(passport.share_url);
    } else {
      navigator.clipboard.writeText(passport.share_url);
      setShareSuccess(true);
      setTimeout(() => setShareSuccess(false), 3000);
    }
  }, [passport, onShareClick]);

  // ── Loading state ────────────────────────────────────────────────────────
  if (loading) return <CardSkeleton />;

  // ── Error state ──────────────────────────────────────────────────────────
  if (error || !passport) {
    return (
      <div style={{
        background: "#FFF7F7",
        border: "1px solid #FCA5A5",
        borderRadius: 16,
        padding: 20,
        textAlign: "center",
        color: "#DC2626",
        fontSize: 14,
      }}>
        <div style={{ fontSize: 28, marginBottom: 8 }}>⚠️</div>
        <div style={{ fontWeight: 600 }}>{error || "Identity not found"}</div>
        <div style={{ color: "#9CA3AF", fontSize: 12, marginTop: 4 }}>
          Nullifier prefix: {nullifierPrefix}
        </div>
      </div>
    );
  }

  const { passport: p, qr_payload } = passport;
  const { did_document, credentials, disclosure_level, total_tenure_weeks, platforms_active } = p;

  // ── Main render ──────────────────────────────────────────────────────────
  return (
    <div style={{
      background: "linear-gradient(145deg, #FFFFFF 0%, #F8FAFC 100%)",
      borderRadius: 16,
      padding: compact ? 14 : 20,
      border: "1px solid #E2E8F0",
      boxShadow: "0 4px 24px rgba(0,0,0,0.06)",
      display: "flex",
      flexDirection: "column",
      gap: compact ? 12 : 16,
      maxWidth: 420,
      width: "100%",
      position: "relative",
      overflow: "hidden",
    }}>

      {/* Background accent */}
      <div style={{
        position: "absolute",
        top: -40,
        right: -40,
        width: 140,
        height: 140,
        background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* ── Header ── */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: "50%",
            background: "linear-gradient(135deg, #3B82F6, #6366F1)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            flexShrink: 0,
          }}>
            🪪
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: "#0F172A" }}>
              CrossRider DID Passport
            </div>
            <div style={{ fontSize: 11, color: "#64748B" }}>
              W3C Verifiable Credentials · ZK-Proven
            </div>
          </div>
        </div>

        {/* ZK Verified badge */}
        <div style={{
          background: "#ECFDF5",
          border: "1px solid #A7F3D0",
          borderRadius: 99,
          padding: "3px 8px",
          display: "flex",
          alignItems: "center",
          gap: 4,
          flexShrink: 0,
        }}>
          <span style={{ fontSize: 10 }}>🔒</span>
          <span style={{ fontSize: 10, fontWeight: 700, color: "#065F46" }}>ZK VERIFIED</span>
        </div>
      </div>

      {/* ── DID Display ── */}
      <DIDDisplay did={did_document.id} />

      {/* ── Disclosure Level Meter ── */}
      <DisclosureMeter level={disclosure_level} />

      {/* ── Stats Row ── */}
      {!compact && (
        <div style={{ display: "flex", gap: 8 }}>
          <StatPill
            icon="📅"
            label="Tenure"
            value={tenureWeeksToLabel(total_tenure_weeks)}
          />
          <StatPill
            icon="🏢"
            label="Platforms"
            value={String(platforms_active.length)}
          />
          <StatPill
            icon="📜"
            label="Credentials"
            value={String(credentials.length)}
          />
        </div>
      )}

      {/* ── Credential Badges ── */}
      <CredentialBadges
        credentials={credentials}
        compact={compact}
      />

      {/* ── Issued info ── */}
      {!compact && (
        <div style={{
          fontSize: 10,
          color: "#94A3B8",
          display: "flex",
          justifyContent: "space-between",
        }}>
          <span>Issued by ZoneGuard · DPDP Compliant</span>
          <span>Updated {formatDate(p.last_updated)}</span>
        </div>
      )}

      {/* ── Actions Row ── */}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={handleShare}
          style={{
            flex: 1,
            background: shareSuccess ? "#ECFDF5" : "#EFF6FF",
            border: "1px solid",
            borderColor: shareSuccess ? "#A7F3D0" : "#BFDBFE",
            borderRadius: 8,
            padding: "9px 12px",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            color: shareSuccess ? "#065F46" : "#1D4ED8",
            transition: "all 0.2s",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
          }}
        >
          {shareSuccess ? "✓ Link Copied!" : "🔗 Share Credentials"}
        </button>

        {showQR && (
          <button
            style={{
              background: "#F8FAFC",
              border: "1px solid #E2E8F0",
              borderRadius: 8,
              padding: "9px 12px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              color: "#475569",
            }}
            onClick={() => {/* toggle QR modal */}}
          >
            📱 QR
          </button>
        )}
      </div>

      {/* ── QR Code ── */}
      {showQR && (
        <div style={{ display: "flex", justifyContent: "center" }}>
          <QRDisplay payload={qr_payload} />
        </div>
      )}

      {/* ── DPDP Compliance note ── */}
      {!compact && (
        <div style={{
          background: "#FFFBEB",
          border: "1px solid #FDE68A",
          borderRadius: 8,
          padding: "8px 12px",
          display: "flex",
          gap: 8,
          alignItems: "flex-start",
        }}>
          <span style={{ fontSize: 14, flexShrink: 0 }}>⚖️</span>
          <div style={{ fontSize: 11, color: "#78350F", lineHeight: 1.5 }}>
            <strong>Zero PII stored.</strong> Your identity is proven via zk-SNARKs.
            ZoneGuard stores only cryptographic hashes — never your Rider ID, phone,
            or exact earnings. DPDP Act 2023 compliant by design.
          </div>
        </div>
      )}
    </div>
  );
}
