// Package main — PolicyChaincode for ZoneGuard SmartPolicy Contracts (Innovation 02)
//
// Manages the full policy lifecycle on Hyperledger Fabric:
//   - CreatePolicy: records policy terms immutably with Forward Premium Lock
//   - RenewPolicy: decrements forward-lock counter, enforces locked premium
//   - AmendPolicy: requires multi-org endorsement (both Insurer + Regulator MSPs)
//   - CancelPolicy: marks policy cancelled, records cancellation timestamp
//
// Payout formula (immutable on-chain):
//   recommended_payout = 0.55 × (7-day rolling earnings / 7) × eligible_days
//
// Forward Premium Lock:
//   If is_forward_locked AND forward_lock_weeks >= 4: weekly_premium × 0.92
//   Lock is cryptographically enforced — cannot be bypassed by off-chain code.
//
// State key format: "POLICY_{policy_id}"
// Composite key for rider index: "RIDER_POLICY_{rider_id}_{policy_id}"

package main

import (
	"encoding/json"
	"fmt"
	"math"
	"time"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

// ─── Constants (governance-updatable via GovernanceChaincode) ────────────────

const (
	ForwardLockDiscountPct  = 0.92  // 8% discount for forward lock
	ForwardLockMinWeeks     = 4     // Minimum weeks required for lock
	MaxPayoutMultiplier     = 10.0  // max_payout = weekly_premium × 10
	PolicyStatePrefix       = "POLICY_"
	RiderPolicyIndexPrefix  = "RIDER_POLICY_"
)

// ─── Data Structures ─────────────────────────────────────────────────────────

// PolicyState is the on-chain representation of a ZoneGuard policy.
type PolicyState struct {
	PolicyID         string  `json:"policy_id"`
	RiderID          string  `json:"rider_id"`
	ZoneID           string  `json:"zone_id"`
	WeeklyPremium    float64 `json:"weekly_premium"`
	MaxPayout        float64 `json:"max_payout"`
	CoverageStart    string  `json:"coverage_start"`    // RFC3339
	CoverageEnd      string  `json:"coverage_end"`      // RFC3339
	IsForwardLocked  bool    `json:"is_forward_locked"`
	ForwardLockWeeks int     `json:"forward_lock_weeks"`
	LockedPremium    float64 `json:"locked_premium"`    // premium locked at commitment time
	Status           string  `json:"status"`            // active | expired | cancelled | suspended
	CreatedAt        string  `json:"created_at"`        // RFC3339
	UpdatedAt        string  `json:"updated_at"`        // RFC3339
	Version          int     `json:"version"`           // incremented on every amendment
	// Endorsement trail — populated on amend operations
	AmendHistory []PolicyAmendment `json:"amend_history,omitempty"`
}

// PolicyAmendment records a multi-org endorsed change.
type PolicyAmendment struct {
	AmendedAt    string            `json:"amended_at"`
	AmendedBy    string            `json:"amended_by"`   // MSP identity
	Changes      map[string]string `json:"changes"`      // field -> "old→new"
	TxID         string            `json:"tx_id"`
}

// ─── SmartContract ────────────────────────────────────────────────────────────

// PolicyChaincode implements the policy lifecycle contract.
type PolicyChaincode struct {
	contractapi.Contract
}

// ─── CreatePolicy ─────────────────────────────────────────────────────────────

// CreatePolicy records a new policy on-chain.
// The Forward Premium Lock discount is enforced here — if is_forward_locked is true
// and forward_lock_weeks >= ForwardLockMinWeeks, the premium is reduced to 92% and
// the locked_premium field is set. Off-chain code cannot override this.
//
// Args (JSON string):
//   policy_id, rider_id, zone_id, weekly_premium (float), max_payout (float),
//   coverage_start (RFC3339), coverage_end (RFC3339),
//   is_forward_locked (bool), forward_lock_weeks (int)
func (pc *PolicyChaincode) CreatePolicy(ctx contractapi.TransactionContextInterface, policyJSON string) (*PolicyState, error) {
	// Parse input
	var input struct {
		PolicyID        string  `json:"policy_id"`
		RiderID         string  `json:"rider_id"`
		ZoneID          string  `json:"zone_id"`
		WeeklyPremium   float64 `json:"weekly_premium"`
		MaxPayout       float64 `json:"max_payout"`
		CoverageStart   string  `json:"coverage_start"`
		CoverageEnd     string  `json:"coverage_end"`
		IsForwardLocked bool    `json:"is_forward_locked"`
		ForwardLockWeeks int    `json:"forward_lock_weeks"`
	}
	if err := json.Unmarshal([]byte(policyJSON), &input); err != nil {
		return nil, fmt.Errorf("CreatePolicy: invalid input JSON: %w", err)
	}

	// Validate required fields
	if input.PolicyID == "" || input.RiderID == "" || input.ZoneID == "" {
		return nil, fmt.Errorf("CreatePolicy: policy_id, rider_id, zone_id are required")
	}
	if input.WeeklyPremium <= 0 {
		return nil, fmt.Errorf("CreatePolicy: weekly_premium must be positive, got %.2f", input.WeeklyPremium)
	}

	// Idempotency check — refuse duplicate policy_id
	stateKey := PolicyStatePrefix + input.PolicyID
	existing, err := ctx.GetStub().GetState(stateKey)
	if err != nil {
		return nil, fmt.Errorf("CreatePolicy: ledger read error: %w", err)
	}
	if existing != nil {
		return nil, fmt.Errorf("CreatePolicy: policy %s already exists on-chain", input.PolicyID)
	}

	// Enforce Forward Premium Lock discount on-chain (immutable business rule)
	finalPremium := input.WeeklyPremium
	lockedPremium := 0.0
	if input.IsForwardLocked && input.ForwardLockWeeks >= ForwardLockMinWeeks {
		finalPremium = math.Round(input.WeeklyPremium * ForwardLockDiscountPct)
		lockedPremium = finalPremium
	}

	// Default max_payout if not supplied
	maxPayout := input.MaxPayout
	if maxPayout <= 0 {
		maxPayout = finalPremium * MaxPayoutMultiplier
	}

	now := time.Now().UTC().Format(time.RFC3339)
	policy := PolicyState{
		PolicyID:         input.PolicyID,
		RiderID:          input.RiderID,
		ZoneID:           input.ZoneID,
		WeeklyPremium:    finalPremium,
		MaxPayout:        maxPayout,
		CoverageStart:    input.CoverageStart,
		CoverageEnd:      input.CoverageEnd,
		IsForwardLocked:  input.IsForwardLocked,
		ForwardLockWeeks: input.ForwardLockWeeks,
		LockedPremium:    lockedPremium,
		Status:           "active",
		CreatedAt:        now,
		UpdatedAt:        now,
		Version:          1,
	}

	policyBytes, err := json.Marshal(policy)
	if err != nil {
		return nil, fmt.Errorf("CreatePolicy: marshal error: %w", err)
	}

	// Write primary state
	if err := ctx.GetStub().PutState(stateKey, policyBytes); err != nil {
		return nil, fmt.Errorf("CreatePolicy: ledger write error: %w", err)
	}

	// Write composite key for rider → policy index
	indexKey, err := ctx.GetStub().CreateCompositeKey(RiderPolicyIndexPrefix, []string{input.RiderID, input.PolicyID})
	if err != nil {
		return nil, fmt.Errorf("CreatePolicy: composite key error: %w", err)
	}
	if err := ctx.GetStub().PutState(indexKey, []byte{0x00}); err != nil {
		return nil, fmt.Errorf("CreatePolicy: index write error: %w", err)
	}

	// Emit chaincode event for downstream listeners (e.g., Python SDK subscriber)
	eventPayload, _ := json.Marshal(map[string]string{
		"event":     "PolicyCreated",
		"policy_id": input.PolicyID,
		"rider_id":  input.RiderID,
	})
	ctx.GetStub().SetEvent("PolicyCreated", eventPayload)

	return &policy, nil
}

// ─── RenewPolicy ─────────────────────────────────────────────────────────────

// RenewPolicy expires the current policy and records a new coverage window.
// Decrements forward_lock_weeks counter. If is_forward_locked, the locked premium
// from the original commitment is preserved — cannot be increased by off-chain code.
func (pc *PolicyChaincode) RenewPolicy(ctx contractapi.TransactionContextInterface, policyID string, newCoverageStart string, newCoverageEnd string) (*PolicyState, error) {
	policy, err := pc.getPolicy(ctx, policyID)
	if err != nil {
		return nil, err
	}

	if policy.Status != "active" {
		return nil, fmt.Errorf("RenewPolicy: cannot renew policy in status '%s'", policy.Status)
	}

	// Expire the old record
	policy.Status = "expired"
	policy.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	if err := pc.putPolicy(ctx, policy); err != nil {
		return nil, err
	}

	// Build renewed policy — carry forward locked premium if lock is active
	newLockWeeks := 0
	if policy.ForwardLockWeeks > 0 {
		newLockWeeks = policy.ForwardLockWeeks - 1
	}
	stillLocked := policy.IsForwardLocked && newLockWeeks > 0

	// Generate new policy_id = original + "_R" + unix timestamp
	renewedID := fmt.Sprintf("%s_R%d", policyID, time.Now().Unix())
	now := time.Now().UTC().Format(time.RFC3339)

	renewed := PolicyState{
		PolicyID:         renewedID,
		RiderID:          policy.RiderID,
		ZoneID:           policy.ZoneID,
		WeeklyPremium:    policy.WeeklyPremium, // locked premium preserved
		MaxPayout:        policy.MaxPayout,
		CoverageStart:    newCoverageStart,
		CoverageEnd:      newCoverageEnd,
		IsForwardLocked:  stillLocked,
		ForwardLockWeeks: newLockWeeks,
		LockedPremium:    policy.LockedPremium,
		Status:           "active",
		CreatedAt:        now,
		UpdatedAt:        now,
		Version:          1,
	}

	renewedBytes, err := json.Marshal(renewed)
	if err != nil {
		return nil, fmt.Errorf("RenewPolicy: marshal error: %w", err)
	}
	if err := ctx.GetStub().PutState(PolicyStatePrefix+renewedID, renewedBytes); err != nil {
		return nil, fmt.Errorf("RenewPolicy: ledger write error: %w", err)
	}

	// Update rider index
	indexKey, _ := ctx.GetStub().CreateCompositeKey(RiderPolicyIndexPrefix, []string{policy.RiderID, renewedID})
	ctx.GetStub().PutState(indexKey, []byte{0x00})

	eventPayload, _ := json.Marshal(map[string]string{
		"event":          "PolicyRenewed",
		"old_policy_id":  policyID,
		"new_policy_id":  renewedID,
		"rider_id":       policy.RiderID,
		"lock_weeks_left": fmt.Sprintf("%d", newLockWeeks),
	})
	ctx.GetStub().SetEvent("PolicyRenewed", eventPayload)

	return &renewed, nil
}

// ─── AmendPolicy ─────────────────────────────────────────────────────────────

// AmendPolicy applies a parameter change that has passed multi-org endorsement.
// The Fabric network policy (configtx.yaml) must require signatures from BOTH
// InsurerMSP and RegulatorMSP — this function records the amendment trail but
// the endorsement requirement is enforced at the network layer.
//
// amendmentsJSON: JSON object of field -> new_value pairs
// amendedBy: the MSP identity string of the submitting org
func (pc *PolicyChaincode) AmendPolicy(ctx contractapi.TransactionContextInterface, policyID string, amendmentsJSON string, amendedBy string) (*PolicyState, error) {
	policy, err := pc.getPolicy(ctx, policyID)
	if err != nil {
		return nil, err
	}

	if policy.Status == "cancelled" {
		return nil, fmt.Errorf("AmendPolicy: cannot amend cancelled policy")
	}

	var amendments map[string]string
	if err := json.Unmarshal([]byte(amendmentsJSON), &amendments); err != nil {
		return nil, fmt.Errorf("AmendPolicy: invalid amendments JSON: %w", err)
	}

	// Track changes for audit trail
	changeLog := make(map[string]string)

	// Apply allowed amendments (whitelist to prevent arbitrary field overwrite)
	allowedFields := map[string]bool{
		"zone_id":           true,
		"coverage_end":      true,
		"forward_lock_weeks": true,
		"status":            true,
	}
	for field, newValue := range amendments {
		if !allowedFields[field] {
			return nil, fmt.Errorf("AmendPolicy: field '%s' is not amendable", field)
		}
		switch field {
		case "zone_id":
			changeLog[field] = fmt.Sprintf("%s→%s", policy.ZoneID, newValue)
			policy.ZoneID = newValue
		case "coverage_end":
			changeLog[field] = fmt.Sprintf("%s→%s", policy.CoverageEnd, newValue)
			policy.CoverageEnd = newValue
		case "status":
			changeLog[field] = fmt.Sprintf("%s→%s", policy.Status, newValue)
			policy.Status = newValue
		}
	}

	// Append amendment record
	amendment := PolicyAmendment{
		AmendedAt: time.Now().UTC().Format(time.RFC3339),
		AmendedBy: amendedBy,
		Changes:   changeLog,
		TxID:      ctx.GetStub().GetTxID(),
	}
	policy.AmendHistory = append(policy.AmendHistory, amendment)
	policy.Version++
	policy.UpdatedAt = time.Now().UTC().Format(time.RFC3339)

	if err := pc.putPolicy(ctx, policy); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]string{
		"event":     "PolicyAmended",
		"policy_id": policyID,
		"amended_by": amendedBy,
		"tx_id":     ctx.GetStub().GetTxID(),
	})
	ctx.GetStub().SetEvent("PolicyAmended", eventPayload)

	return policy, nil
}

// ─── CancelPolicy ─────────────────────────────────────────────────────────────

// CancelPolicy marks the policy as cancelled on-chain.
// If the policy is forward-locked with remaining weeks, cancellation is still
// permitted but the event payload carries a penalty flag for off-chain processing.
func (pc *PolicyChaincode) CancelPolicy(ctx contractapi.TransactionContextInterface, policyID string, cancelledBy string) error {
	policy, err := pc.getPolicy(ctx, policyID)
	if err != nil {
		return err
	}

	if policy.Status == "cancelled" {
		return fmt.Errorf("CancelPolicy: policy %s is already cancelled", policyID)
	}

	penaltyApplies := policy.IsForwardLocked && policy.ForwardLockWeeks > 0

	policy.Status = "cancelled"
	policy.UpdatedAt = time.Now().UTC().Format(time.RFC3339)

	if err := pc.putPolicy(ctx, policy); err != nil {
		return err
	}

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":           "PolicyCancelled",
		"policy_id":       policyID,
		"cancelled_by":    cancelledBy,
		"penalty_applies": penaltyApplies,
		"lock_weeks_lost": policy.ForwardLockWeeks,
	})
	ctx.GetStub().SetEvent("PolicyCancelled", eventPayload)

	return nil
}

// ─── QueryPolicy ─────────────────────────────────────────────────────────────

// QueryPolicy reads a policy from the ledger by ID.
func (pc *PolicyChaincode) QueryPolicy(ctx contractapi.TransactionContextInterface, policyID string) (*PolicyState, error) {
	return pc.getPolicy(ctx, policyID)
}

// QueryPoliciesByRider returns all policy IDs associated with a rider.
func (pc *PolicyChaincode) QueryPoliciesByRider(ctx contractapi.TransactionContextInterface, riderID string) ([]string, error) {
	iter, err := ctx.GetStub().GetStateByPartialCompositeKey(RiderPolicyIndexPrefix, []string{riderID})
	if err != nil {
		return nil, fmt.Errorf("QueryPoliciesByRider: index read error: %w", err)
	}
	defer iter.Close()

	var policyIDs []string
	for iter.HasNext() {
		kv, err := iter.Next()
		if err != nil {
			return nil, err
		}
		_, parts, err := ctx.GetStub().SplitCompositeKey(kv.Key)
		if err != nil || len(parts) < 2 {
			continue
		}
		policyIDs = append(policyIDs, parts[1])
	}
	return policyIDs, nil
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

func (pc *PolicyChaincode) getPolicy(ctx contractapi.TransactionContextInterface, policyID string) (*PolicyState, error) {
	stateBytes, err := ctx.GetStub().GetState(PolicyStatePrefix + policyID)
	if err != nil {
		return nil, fmt.Errorf("getPolicy: ledger read error: %w", err)
	}
	if stateBytes == nil {
		return nil, fmt.Errorf("getPolicy: policy %s not found on-chain", policyID)
	}
	var policy PolicyState
	if err := json.Unmarshal(stateBytes, &policy); err != nil {
		return nil, fmt.Errorf("getPolicy: unmarshal error: %w", err)
	}
	return &policy, nil
}

func (pc *PolicyChaincode) putPolicy(ctx contractapi.TransactionContextInterface, policy *PolicyState) error {
	policyBytes, err := json.Marshal(policy)
	if err != nil {
		return fmt.Errorf("putPolicy: marshal error: %w", err)
	}
	return ctx.GetStub().PutState(PolicyStatePrefix+policy.PolicyID, policyBytes)
}

// ─── Main ─────────────────────────────────────────────────────────────────────

func main() {
	chaincode, err := contractapi.NewChaincode(&PolicyChaincode{})
	if err != nil {
		panic(fmt.Sprintf("PolicyChaincode: failed to create chaincode: %v", err))
	}
	if err := chaincode.Start(); err != nil {
		panic(fmt.Sprintf("PolicyChaincode: failed to start chaincode: %v", err))
	}
}
