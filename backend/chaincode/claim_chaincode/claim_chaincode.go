// Package main — ClaimChaincode for ZoneGuard SmartPolicy Contracts (Innovation 02)
//
// Manages the full claim lifecycle on Hyperledger Fabric:
//   - TriggerClaim: initiated by HIGH confidence signal from QuadSignal engine
//   - CalculatePayout: IMMUTABLE on-chain payout formula (55% × rolling earnings × eligible days)
//   - RecordFraudScore: writes FraudShield score with cryptographic timestamp
//   - ApproveClaim: finalises payout, records UPI reference hash
//   - RejectClaim: records rejection reason immutably
//   - ChallengeClaim: rider disputes — resets to pending_review
//
// Payout formula (IMMUTABLE — cannot be changed without DAO governance vote):
//   daily_avg_earnings = seven_day_rolling_earnings / 7
//   recommended_payout = 0.55 × daily_avg_earnings × eligible_days
//   capped at policy max_payout
//
// Fraud gating: FraudShield score > FRAUD_REJECT_THRESHOLD → auto-reject.
// Score is written to chain before any payout decision, making it auditable.
//
// State key format: "CLAIM_{claim_id}"
// Composite key: "POLICY_CLAIM_{policy_id}_{claim_id}"

package main

import (
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

// ─── Constants (governance-updatable via GovernanceChaincode) ─────────────────

const (
	PayoutEarningsMultiplier = 0.55  // 55% of daily average earnings
	FraudRejectThreshold     = 0.75  // FraudShield score above this = auto-reject
	ClaimStatePrefix         = "CLAIM_"
	PolicyClaimIndexPrefix   = "POLICY_CLAIM_"
	MaxEligibleDays          = 7     // cap at 7-day window
)

// ─── Data Structures ─────────────────────────────────────────────────────────

// ClaimState is the on-chain representation of a ZoneGuard claim.
type ClaimState struct {
	ClaimID              string        `json:"claim_id"`
	PolicyID             string        `json:"policy_id"`
	RiderID              string        `json:"rider_id"`
	ZoneID               string        `json:"zone_id"`
	// Signal data that triggered the claim
	ConfidenceLevel      string        `json:"confidence_level"`   // HIGH | MEDIUM | LOW
	SignalsFired         int           `json:"signals_fired"`
	SignalDetails        interface{}   `json:"signal_details"`
	// Oracle consensus snapshot at trigger time
	OracleConsensusRef   string        `json:"oracle_consensus_ref"` // hash of oracle reading
	// Payout calculation (all computed on-chain)
	SevenDayRollingEarnings float64   `json:"seven_day_rolling_earnings"`
	EligibleDays         int           `json:"eligible_days"`
	DailyAvgEarnings     float64       `json:"daily_avg_earnings"`   // rolling / 7
	RecommendedPayout    float64       `json:"recommended_payout"`   // 0.55 × daily_avg × eligible_days
	ActualPayout         float64       `json:"actual_payout,omitempty"`
	PolicyMaxPayout      float64       `json:"policy_max_payout"`
	PayoutCapped         bool          `json:"payout_capped"`        // true if formula result exceeded max_payout
	// Fraud gating
	FraudScore           float64       `json:"fraud_score"`          // 0.0–1.0 from FraudShield
	FraudScoreRecordedAt string        `json:"fraud_score_recorded_at"`
	FraudAutoRejected    bool          `json:"fraud_auto_rejected"`
	// Lifecycle
	Status               string        `json:"status"`      // pending | pending_review | approved | rejected | challenged
	TriggeredAt          string        `json:"triggered_at"`
	ReviewedAt           string        `json:"reviewed_at,omitempty"`
	ReviewedBy           string        `json:"reviewed_by,omitempty"`
	RejectionReason      string        `json:"rejection_reason,omitempty"`
	// UPI settlement
	UPIRefHash           string        `json:"upi_ref_hash,omitempty"` // SHA-256 of UPI transaction ref
	SettledAt            string        `json:"settled_at,omitempty"`
	// Audit trail
	AuditTrail           []ClaimAuditEntry `json:"audit_trail"`
}

// ClaimAuditEntry records each state transition immutably.
type ClaimAuditEntry struct {
	Timestamp   string `json:"timestamp"`
	Event       string `json:"event"`
	Actor       string `json:"actor"`
	TxID        string `json:"tx_id"`
	Detail      string `json:"detail,omitempty"`
}

// ─── SmartContract ────────────────────────────────────────────────────────────

// ClaimChaincode implements the claim lifecycle contract.
type ClaimChaincode struct {
	contractapi.Contract
}

// ─── TriggerClaim ─────────────────────────────────────────────────────────────

// TriggerClaim records a new claim triggered by a HIGH-confidence signal.
// Immediately computes the recommended payout on-chain using the immutable formula.
// If confidence is not HIGH, the claim is written with status = pending_review.
//
// inputJSON fields:
//   claim_id, policy_id, rider_id, zone_id, confidence_level,
//   signals_fired (int), signal_details (JSON object),
//   oracle_consensus_ref (string), seven_day_rolling_earnings (float),
//   eligible_days (int), policy_max_payout (float)
func (cc *ClaimChaincode) TriggerClaim(ctx contractapi.TransactionContextInterface, inputJSON string) (*ClaimState, error) {
	var input struct {
		ClaimID                 string      `json:"claim_id"`
		PolicyID                string      `json:"policy_id"`
		RiderID                 string      `json:"rider_id"`
		ZoneID                  string      `json:"zone_id"`
		ConfidenceLevel         string      `json:"confidence_level"`
		SignalsFired            int         `json:"signals_fired"`
		SignalDetails           interface{} `json:"signal_details"`
		OracleConsensusRef      string      `json:"oracle_consensus_ref"`
		SevenDayRollingEarnings float64     `json:"seven_day_rolling_earnings"`
		EligibleDays            int         `json:"eligible_days"`
		PolicyMaxPayout         float64     `json:"policy_max_payout"`
	}
	if err := json.Unmarshal([]byte(inputJSON), &input); err != nil {
		return nil, fmt.Errorf("TriggerClaim: invalid input JSON: %w", err)
	}

	// Validate
	if input.ClaimID == "" || input.PolicyID == "" || input.RiderID == "" {
		return nil, fmt.Errorf("TriggerClaim: claim_id, policy_id, rider_id are required")
	}

	// Idempotency check
	existing, err := ctx.GetStub().GetState(ClaimStatePrefix + input.ClaimID)
	if err != nil {
		return nil, fmt.Errorf("TriggerClaim: ledger read error: %w", err)
	}
	if existing != nil {
		return nil, fmt.Errorf("TriggerClaim: claim %s already exists on-chain", input.ClaimID)
	}

	// Validate eligible_days
	eligibleDays := input.EligibleDays
	if eligibleDays > MaxEligibleDays {
		eligibleDays = MaxEligibleDays
	}
	if eligibleDays < 1 {
		return nil, fmt.Errorf("TriggerClaim: eligible_days must be ≥ 1, got %d", input.EligibleDays)
	}

	// ── IMMUTABLE PAYOUT FORMULA ──────────────────────────────────────────────
	// daily_avg_earnings = seven_day_rolling_earnings / 7
	// recommended_payout = 0.55 × daily_avg_earnings × eligible_days
	// cap at policy_max_payout
	dailyAvg := input.SevenDayRollingEarnings / 7.0
	rawPayout := PayoutEarningsMultiplier * dailyAvg * float64(eligibleDays)
	rawPayout = math.Round(rawPayout*100) / 100 // round to 2 decimal places

	payoutCapped := false
	finalPayout := rawPayout
	if input.PolicyMaxPayout > 0 && rawPayout > input.PolicyMaxPayout {
		finalPayout = input.PolicyMaxPayout
		payoutCapped = true
	}
	// ─────────────────────────────────────────────────────────────────────────

	// Determine initial status
	status := "pending_review"
	if input.ConfidenceLevel == "HIGH" {
		status = "pending" // pending fraud check → then auto-approve
	}

	now := time.Now().UTC().Format(time.RFC3339)
	claim := ClaimState{
		ClaimID:                 input.ClaimID,
		PolicyID:                input.PolicyID,
		RiderID:                 input.RiderID,
		ZoneID:                  input.ZoneID,
		ConfidenceLevel:         input.ConfidenceLevel,
		SignalsFired:            input.SignalsFired,
		SignalDetails:           input.SignalDetails,
		OracleConsensusRef:      input.OracleConsensusRef,
		SevenDayRollingEarnings: input.SevenDayRollingEarnings,
		EligibleDays:            eligibleDays,
		DailyAvgEarnings:        math.Round(dailyAvg*100) / 100,
		RecommendedPayout:       finalPayout,
		PolicyMaxPayout:         input.PolicyMaxPayout,
		PayoutCapped:            payoutCapped,
		FraudScore:              -1.0, // sentinel: not yet recorded
		Status:                  status,
		TriggeredAt:             now,
		AuditTrail: []ClaimAuditEntry{{
			Timestamp: now,
			Event:     "ClaimTriggered",
			Actor:     "system",
			TxID:      ctx.GetStub().GetTxID(),
			Detail:    fmt.Sprintf("confidence=%s signals=%d payout=%.2f capped=%v", input.ConfidenceLevel, input.SignalsFired, finalPayout, payoutCapped),
		}},
	}

	if err := cc.putClaim(ctx, &claim); err != nil {
		return nil, err
	}

	// Composite key: policy → claim index
	indexKey, _ := ctx.GetStub().CreateCompositeKey(PolicyClaimIndexPrefix, []string{input.PolicyID, input.ClaimID})
	ctx.GetStub().PutState(indexKey, []byte{0x00})

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":              "ClaimTriggered",
		"claim_id":           input.ClaimID,
		"policy_id":          input.PolicyID,
		"recommended_payout": finalPayout,
		"confidence":         input.ConfidenceLevel,
	})
	ctx.GetStub().SetEvent("ClaimTriggered", eventPayload)

	return &claim, nil
}

// ─── RecordFraudScore ─────────────────────────────────────────────────────────

// RecordFraudScore writes the FraudShield ML score to the chain before any payout decision.
// If score exceeds FraudRejectThreshold, the claim is automatically rejected on-chain.
// This makes fraud decisions immutable and auditable — the score cannot be changed
// after writing.
func (cc *ClaimChaincode) RecordFraudScore(ctx contractapi.TransactionContextInterface, claimID string, fraudScore float64, recordedBy string) (*ClaimState, error) {
	claim, err := cc.getClaim(ctx, claimID)
	if err != nil {
		return nil, err
	}

	if claim.FraudScore >= 0 {
		// Score already recorded — idempotent, no overwrite allowed
		return nil, fmt.Errorf("RecordFraudScore: fraud score for claim %s already recorded at %s", claimID, claim.FraudScoreRecordedAt)
	}

	if fraudScore < 0.0 || fraudScore > 1.0 {
		return nil, fmt.Errorf("RecordFraudScore: score must be 0.0–1.0, got %.4f", fraudScore)
	}

	now := time.Now().UTC().Format(time.RFC3339)
	claim.FraudScore = fraudScore
	claim.FraudScoreRecordedAt = now

	auditEntry := ClaimAuditEntry{
		Timestamp: now,
		Event:     "FraudScoreRecorded",
		Actor:     recordedBy,
		TxID:      ctx.GetStub().GetTxID(),
		Detail:    fmt.Sprintf("fraud_score=%.4f threshold=%.2f", fraudScore, FraudRejectThreshold),
	}
	claim.AuditTrail = append(claim.AuditTrail, auditEntry)

	// Auto-reject if fraud threshold exceeded
	if fraudScore > FraudRejectThreshold {
		claim.Status = "rejected"
		claim.FraudAutoRejected = true
		claim.RejectionReason = fmt.Sprintf("FraudShield auto-reject: score %.4f > threshold %.2f", fraudScore, FraudRejectThreshold)
		claim.ReviewedAt = now
		claim.ReviewedBy = "FraudShield-AutoReject"
		claim.AuditTrail = append(claim.AuditTrail, ClaimAuditEntry{
			Timestamp: now,
			Event:     "ClaimAutoRejected",
			Actor:     "FraudShield",
			TxID:      ctx.GetStub().GetTxID(),
			Detail:    claim.RejectionReason,
		})
	}

	if err := cc.putClaim(ctx, claim); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":               "FraudScoreRecorded",
		"claim_id":            claimID,
		"fraud_score":         fraudScore,
		"auto_rejected":       claim.FraudAutoRejected,
	})
	ctx.GetStub().SetEvent("FraudScoreRecorded", eventPayload)

	return claim, nil
}

// ─── ApproveClaim ─────────────────────────────────────────────────────────────

// ApproveClaim finalises the claim, records actual payout, and stores UPI ref hash.
// The UPI reference itself is NOT stored on-chain (PII/financial data) — only its
// SHA-256 hash is written, enabling off-chain verification without data exposure.
func (cc *ClaimChaincode) ApproveClaim(ctx contractapi.TransactionContextInterface, claimID string, reviewedBy string, upiRefHash string) (*ClaimState, error) {
	claim, err := cc.getClaim(ctx, claimID)
	if err != nil {
		return nil, err
	}

	if claim.Status == "approved" {
		return nil, fmt.Errorf("ApproveClaim: claim %s already approved", claimID)
	}
	if claim.Status == "rejected" {
		return nil, fmt.Errorf("ApproveClaim: claim %s is rejected, cannot approve", claimID)
	}
	if claim.FraudScore < 0 {
		return nil, fmt.Errorf("ApproveClaim: fraud score must be recorded before approval for claim %s", claimID)
	}
	if claim.FraudAutoRejected {
		return nil, fmt.Errorf("ApproveClaim: claim %s was auto-rejected by FraudShield", claimID)
	}

	now := time.Now().UTC().Format(time.RFC3339)
	claim.Status = "approved"
	claim.ActualPayout = claim.RecommendedPayout
	claim.ReviewedAt = now
	claim.ReviewedBy = reviewedBy
	claim.UPIRefHash = upiRefHash
	claim.SettledAt = now

	claim.AuditTrail = append(claim.AuditTrail, ClaimAuditEntry{
		Timestamp: now,
		Event:     "ClaimApproved",
		Actor:     reviewedBy,
		TxID:      ctx.GetStub().GetTxID(),
		Detail:    fmt.Sprintf("actual_payout=%.2f upi_hash=%s", claim.ActualPayout, upiRefHash),
	})

	if err := cc.putClaim(ctx, claim); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":        "ClaimApproved",
		"claim_id":     claimID,
		"rider_id":     claim.RiderID,
		"actual_payout": claim.ActualPayout,
		"upi_ref_hash": upiRefHash,
	})
	ctx.GetStub().SetEvent("ClaimApproved", eventPayload)

	return claim, nil
}

// ─── RejectClaim ─────────────────────────────────────────────────────────────

// RejectClaim records the rejection reason immutably on-chain.
func (cc *ClaimChaincode) RejectClaim(ctx contractapi.TransactionContextInterface, claimID string, reviewedBy string, reason string) (*ClaimState, error) {
	claim, err := cc.getClaim(ctx, claimID)
	if err != nil {
		return nil, err
	}

	if claim.Status == "approved" {
		return nil, fmt.Errorf("RejectClaim: cannot reject already-approved claim %s", claimID)
	}
	if claim.Status == "rejected" {
		return nil, fmt.Errorf("RejectClaim: claim %s already rejected", claimID)
	}

	now := time.Now().UTC().Format(time.RFC3339)
	claim.Status = "rejected"
	claim.ReviewedAt = now
	claim.ReviewedBy = reviewedBy
	claim.RejectionReason = reason

	claim.AuditTrail = append(claim.AuditTrail, ClaimAuditEntry{
		Timestamp: now,
		Event:     "ClaimRejected",
		Actor:     reviewedBy,
		TxID:      ctx.GetStub().GetTxID(),
		Detail:    reason,
	})

	if err := cc.putClaim(ctx, claim); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]string{
		"event":    "ClaimRejected",
		"claim_id": claimID,
		"reason":   reason,
	})
	ctx.GetStub().SetEvent("ClaimRejected", eventPayload)

	return claim, nil
}

// ─── ChallengeClaim ───────────────────────────────────────────────────────────

// ChallengeClaim allows a rider to dispute a rejected claim.
// Resets status to pending_review for human re-evaluation.
// Challenge is recorded immutably — riders cannot repeatedly challenge
// without the full history being visible.
func (cc *ClaimChaincode) ChallengeClaim(ctx contractapi.TransactionContextInterface, claimID string, riderID string, challengeReason string) (*ClaimState, error) {
	claim, err := cc.getClaim(ctx, claimID)
	if err != nil {
		return nil, err
	}

	if claim.RiderID != riderID {
		return nil, fmt.Errorf("ChallengeClaim: rider %s does not own claim %s", riderID, claimID)
	}
	if claim.Status != "rejected" {
		return nil, fmt.Errorf("ChallengeClaim: only rejected claims can be challenged, current status: %s", claim.Status)
	}

	now := time.Now().UTC().Format(time.RFC3339)
	claim.Status = "pending_review"
	claim.ReviewedAt = ""
	claim.ReviewedBy = ""

	claim.AuditTrail = append(claim.AuditTrail, ClaimAuditEntry{
		Timestamp: now,
		Event:     "ClaimChallenged",
		Actor:     riderID,
		TxID:      ctx.GetStub().GetTxID(),
		Detail:    challengeReason,
	})

	if err := cc.putClaim(ctx, claim); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]string{
		"event":    "ClaimChallenged",
		"claim_id": claimID,
		"rider_id": riderID,
	})
	ctx.GetStub().SetEvent("ClaimChallenged", eventPayload)

	return claim, nil
}

// ─── QueryClaim ───────────────────────────────────────────────────────────────

// QueryClaim reads a claim by ID.
func (cc *ClaimChaincode) QueryClaim(ctx contractapi.TransactionContextInterface, claimID string) (*ClaimState, error) {
	return cc.getClaim(ctx, claimID)
}

// QueryClaimsByPolicy returns all claim IDs for a given policy.
func (cc *ClaimChaincode) QueryClaimsByPolicy(ctx contractapi.TransactionContextInterface, policyID string) ([]string, error) {
	iter, err := ctx.GetStub().GetStateByPartialCompositeKey(PolicyClaimIndexPrefix, []string{policyID})
	if err != nil {
		return nil, fmt.Errorf("QueryClaimsByPolicy: index read error: %w", err)
	}
	defer iter.Close()

	var claimIDs []string
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return nil, err
		}
		_, parts, err := ctx.GetStub().SplitCompositeKey(kv.Key)
		if err != nil || len(parts) < 2 {
			continue
		}
		claimIDs = append(claimIDs, parts[1])
	}
	return claimIDs, nil
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

func (cc *ClaimChaincode) getClaim(ctx contractapi.TransactionContextInterface, claimID string) (*ClaimState, error) {
	stateBytes, err := ctx.GetStub().GetState(ClaimStatePrefix + claimID)
	if err != nil {
		return nil, fmt.Errorf("getClaim: ledger read error: %w", err)
	}
	if stateBytes == nil {
		return nil, fmt.Errorf("getClaim: claim %s not found on-chain", claimID)
	}
	var claim ClaimState
	if err := json.Unmarshal(stateBytes, &claim); err != nil {
		return nil, fmt.Errorf("getClaim: unmarshal error: %w", err)
	}
	return &claim, nil
}

func (cc *ClaimChaincode) putClaim(ctx contractapi.TransactionContextInterface, claim *ClaimState) error {
	claimBytes, err := json.Marshal(claim)
	if err != nil {
		return fmt.Errorf("putClaim: marshal error: %w", err)
	}
	return ctx.GetStub().PutState(ClaimStatePrefix+claim.ClaimID, claimBytes)
}

// ─── Main ─────────────────────────────────────────────────────────────────────

func main() {
	chaincode, err := contractapi.NewChaincode(&ClaimChaincode{})
	if err != nil {
		panic(fmt.Sprintf("ClaimChaincode: failed to create chaincode: %v", err))
	}
	if err := chaincode.Start(); err != nil {
		panic(fmt.Sprintf("ClaimChaincode: failed to start chaincode: %v", err))
	}
}
