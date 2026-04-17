// Package main — GovernanceChaincode for ZoneGuard DAO parameter governance (Innovation 02)
//
// Enables DAO-governed updates to critical system parameters without redeploying chaincode.
// Parameters like payout multipliers, fraud thresholds, and signal thresholds can be updated
// via on-chain votes requiring multi-org supermajority endorsement.
//
// Governance flow:
//   1. ProposeParameterChange: any org member submits a proposal
//   2. VoteOnProposal: InsurerMSP, RegulatorMSP, TechMSP each cast votes
//   3. FinaliseProposal: if votes >= VoteThreshold, parameter is updated on-chain
//   4. GetParameter: chaincode consumers read current parameter values from here
//
// Supported parameters (governed on-chain):
//   - payout_earnings_multiplier   (default: 0.55)
//   - fraud_reject_threshold        (default: 0.75)
//   - forward_lock_discount_pct     (default: 0.92)
//   - forward_lock_min_weeks        (default: 4)
//   - oracle_s1_consensus_threshold (default: 3, out of 4)
//   - oracle_s2_consensus_threshold (default: 2, out of 3)
//   - oracle_s3_consensus_threshold (default: 2, out of 3)
//   - signal_rainfall_threshold_mm  (default: 65)
//   - signal_aqi_threshold          (default: 300)
//   - signal_temp_threshold_c       (default: 43)
//   - signal_mobility_drop_pct      (default: 75)
//   - signal_order_drop_pct         (default: 70)
//   - signal_inactivity_pct         (default: 40)
//
// State keys:
//   "PARAM_{name}" — current parameter value
//   "PROPOSAL_{proposal_id}" — proposal state
//   "ORG_VOTE_{proposal_id}_{org_id}" — prevents double-voting

package main

import (
	"encoding/json"
	"fmt"
	"strconv"
	"time"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

// ─── Constants ────────────────────────────────────────────────────────────────

const (
	ParamPrefix      = "PARAM_"
	ProposalPrefix   = "PROPOSAL_"
	OrgVotePrefix    = "ORG_VOTE_"
	VoteThreshold    = 2 // of 3 orgs must vote YES to pass (2/3 supermajority)
	ProposalTTLHours = 72
)

// Allowed orgs that can vote. Expand as new MSPs are added to the network.
var AllowedVoterOrgs = map[string]bool{
	"InsurerMSP":   true,
	"RegulatorMSP": true,
	"TechMSP":      true,
}

// Allowed parameter names — whitelist prevents arbitrary state key injection.
var AllowedParameters = map[string]bool{
	"payout_earnings_multiplier":   true,
	"fraud_reject_threshold":        true,
	"forward_lock_discount_pct":     true,
	"forward_lock_min_weeks":        true,
	"oracle_s1_consensus_threshold": true,
	"oracle_s2_consensus_threshold": true,
	"oracle_s3_consensus_threshold": true,
	"signal_rainfall_threshold_mm":  true,
	"signal_aqi_threshold":          true,
	"signal_temp_threshold_c":       true,
	"signal_mobility_drop_pct":      true,
	"signal_order_drop_pct":         true,
	"signal_inactivity_pct":         true,
}

// Default parameter values — written to ledger on Init if not present.
var DefaultParameters = map[string]string{
	"payout_earnings_multiplier":   "0.55",
	"fraud_reject_threshold":        "0.75",
	"forward_lock_discount_pct":     "0.92",
	"forward_lock_min_weeks":        "4",
	"oracle_s1_consensus_threshold": "3",
	"oracle_s2_consensus_threshold": "2",
	"oracle_s3_consensus_threshold": "2",
	"signal_rainfall_threshold_mm":  "65",
	"signal_aqi_threshold":          "300",
	"signal_temp_threshold_c":       "43",
	"signal_mobility_drop_pct":      "75",
	"signal_order_drop_pct":         "70",
	"signal_inactivity_pct":         "40",
}

// ─── Data Structures ─────────────────────────────────────────────────────────

// ProposalState represents a pending parameter change proposal.
type ProposalState struct {
	ProposalID    string            `json:"proposal_id"`
	ParameterName string            `json:"parameter_name"`
	CurrentValue  string            `json:"current_value"`
	ProposedValue string            `json:"proposed_value"`
	Rationale     string            `json:"rationale"`
	ProposedBy    string            `json:"proposed_by"`   // org MSP ID
	ProposedAt    string            `json:"proposed_at"`
	ExpiresAt     string            `json:"expires_at"`
	Votes         map[string]string `json:"votes"`          // orgID → "YES" | "NO"
	YesCount      int               `json:"yes_count"`
	NoCount       int               `json:"no_count"`
	Status        string            `json:"status"`         // open | passed | rejected | expired
	FinalizedAt   string            `json:"finalized_at,omitempty"`
	FinalizedBy   string            `json:"finalized_by,omitempty"`
}

// ─── SmartContract ────────────────────────────────────────────────────────────

// GovernanceChaincode implements DAO-governed parameter management.
type GovernanceChaincode struct {
	contractapi.Contract
}

// ─── InitLedger ──────────────────────────────────────────────────────────────

// InitLedger writes all default parameter values to the ledger on first deploy.
// Safe to call multiple times — only writes parameters not already present.
func (gc *GovernanceChaincode) InitLedger(ctx contractapi.TransactionContextInterface) error {
	for name, defaultValue := range DefaultParameters {
		key := ParamPrefix + name
		existing, err := ctx.GetStub().GetState(key)
		if err != nil {
			return fmt.Errorf("InitLedger: read error for %s: %w", name, err)
		}
		if existing == nil {
			if err := ctx.GetStub().PutState(key, []byte(defaultValue)); err != nil {
				return fmt.Errorf("InitLedger: write error for %s: %w", name, err)
			}
		}
	}
	return nil
}

// ─── GetParameter ─────────────────────────────────────────────────────────────

// GetParameter reads the current value of a governed parameter.
// Other chaincodes and the Python SDK call this to get live thresholds.
func (gc *GovernanceChaincode) GetParameter(ctx contractapi.TransactionContextInterface, paramName string) (string, error) {
	if !AllowedParameters[paramName] {
		return "", fmt.Errorf("GetParameter: unknown parameter '%s'", paramName)
	}
	valBytes, err := ctx.GetStub().GetState(ParamPrefix + paramName)
	if err != nil {
		return "", fmt.Errorf("GetParameter: ledger read error: %w", err)
	}
	if valBytes == nil {
		// Return default if ledger not yet initialised
		if def, ok := DefaultParameters[paramName]; ok {
			return def, nil
		}
		return "", fmt.Errorf("GetParameter: parameter '%s' not found", paramName)
	}
	return string(valBytes), nil
}

// GetAllParameters returns all current governed parameter values as JSON.
func (gc *GovernanceChaincode) GetAllParameters(ctx contractapi.TransactionContextInterface) (map[string]string, error) {
	result := make(map[string]string)
	for name := range AllowedParameters {
		val, err := gc.GetParameter(ctx, name)
		if err != nil {
			return nil, err
		}
		result[name] = val
	}
	return result, nil
}

// ─── ProposeParameterChange ───────────────────────────────────────────────────

// ProposeParameterChange opens a new governance proposal.
// Any allowed org may propose; the proposer's vote is NOT automatically cast.
func (gc *GovernanceChaincode) ProposeParameterChange(
	ctx contractapi.TransactionContextInterface,
	proposalID string,
	paramName string,
	proposedValue string,
	rationale string,
	proposedBy string,
) (*ProposalState, error) {
	// Validate org
	if !AllowedVoterOrgs[proposedBy] {
		return nil, fmt.Errorf("ProposeParameterChange: org '%s' is not an authorised voter", proposedBy)
	}
	// Validate parameter
	if !AllowedParameters[paramName] {
		return nil, fmt.Errorf("ProposeParameterChange: unknown parameter '%s'", paramName)
	}
	// Validate proposed value is a valid float/int
	if _, err := strconv.ParseFloat(proposedValue, 64); err != nil {
		return nil, fmt.Errorf("ProposeParameterChange: proposed_value '%s' must be numeric", proposedValue)
	}

	// Check for duplicate proposal ID
	existing, err := ctx.GetStub().GetState(ProposalPrefix + proposalID)
	if err != nil {
		return nil, fmt.Errorf("ProposeParameterChange: ledger read error: %w", err)
	}
	if existing != nil {
		return nil, fmt.Errorf("ProposeParameterChange: proposal %s already exists", proposalID)
	}

	// Read current value for change record
	currentValue, _ := gc.GetParameter(ctx, paramName)

	now := time.Now().UTC()
	proposal := ProposalState{
		ProposalID:    proposalID,
		ParameterName: paramName,
		CurrentValue:  currentValue,
		ProposedValue: proposedValue,
		Rationale:     rationale,
		ProposedBy:    proposedBy,
		ProposedAt:    now.Format(time.RFC3339),
		ExpiresAt:     now.Add(ProposalTTLHours * time.Hour).Format(time.RFC3339),
		Votes:         make(map[string]string),
		YesCount:      0,
		NoCount:       0,
		Status:        "open",
	}

	if err := gc.putProposal(ctx, &proposal); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]string{
		"event":          "ProposalCreated",
		"proposal_id":    proposalID,
		"parameter_name": paramName,
		"current_value":  currentValue,
		"proposed_value": proposedValue,
		"proposed_by":    proposedBy,
	})
	ctx.GetStub().SetEvent("ProposalCreated", eventPayload)

	return &proposal, nil
}

// ─── VoteOnProposal ───────────────────────────────────────────────────────────

// VoteOnProposal casts a YES or NO vote from an authorised org.
// Each org can vote exactly once per proposal. Votes are recorded on-chain.
func (gc *GovernanceChaincode) VoteOnProposal(
	ctx contractapi.TransactionContextInterface,
	proposalID string,
	voterOrg string,
	vote string,
) (*ProposalState, error) {
	// Validate org
	if !AllowedVoterOrgs[voterOrg] {
		return nil, fmt.Errorf("VoteOnProposal: org '%s' is not an authorised voter", voterOrg)
	}
	// Validate vote value
	if vote != "YES" && vote != "NO" {
		return nil, fmt.Errorf("VoteOnProposal: vote must be 'YES' or 'NO', got '%s'", vote)
	}

	proposal, err := gc.getProposal(ctx, proposalID)
	if err != nil {
		return nil, err
	}

	if proposal.Status != "open" {
		return nil, fmt.Errorf("VoteOnProposal: proposal %s is not open (status: %s)", proposalID, proposal.Status)
	}

	// Check expiry
	expiresAt, _ := time.Parse(time.RFC3339, proposal.ExpiresAt)
	if time.Now().UTC().After(expiresAt) {
		proposal.Status = "expired"
		gc.putProposal(ctx, proposal)
		return nil, fmt.Errorf("VoteOnProposal: proposal %s has expired", proposalID)
	}

	// Check duplicate vote
	voteKey := OrgVotePrefix + proposalID + "_" + voterOrg
	existingVote, err := ctx.GetStub().GetState(voteKey)
	if err != nil {
		return nil, fmt.Errorf("VoteOnProposal: vote check error: %w", err)
	}
	if existingVote != nil {
		return nil, fmt.Errorf("VoteOnProposal: org %s has already voted on proposal %s", voterOrg, proposalID)
	}

	// Record the vote
	proposal.Votes[voterOrg] = vote
	if vote == "YES" {
		proposal.YesCount++
	} else {
		proposal.NoCount++
	}

	// Write idempotency guard
	ctx.GetStub().PutState(voteKey, []byte(vote))

	if err := gc.putProposal(ctx, proposal); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":       "VoteCast",
		"proposal_id": proposalID,
		"voter_org":   voterOrg,
		"vote":        vote,
		"yes_count":   proposal.YesCount,
		"no_count":    proposal.NoCount,
	})
	ctx.GetStub().SetEvent("VoteCast", eventPayload)

	return proposal, nil
}

// ─── FinaliseProposal ─────────────────────────────────────────────────────────

// FinaliseProposal evaluates the vote tally and applies the parameter change if passed.
// Anyone can call finalise — the result is deterministic based on the on-chain vote record.
// If YES votes >= VoteThreshold: parameter is updated, status = "passed".
// If not enough votes: status = "rejected".
func (gc *GovernanceChaincode) FinaliseProposal(
	ctx contractapi.TransactionContextInterface,
	proposalID string,
	finalisedBy string,
) (*ProposalState, error) {
	proposal, err := gc.getProposal(ctx, proposalID)
	if err != nil {
		return nil, err
	}

	if proposal.Status != "open" {
		return nil, fmt.Errorf("FinaliseProposal: proposal %s is not open (status: %s)", proposalID, proposal.Status)
	}

	now := time.Now().UTC().Format(time.RFC3339)

	if proposal.YesCount >= VoteThreshold {
		// Apply the parameter change
		if err := ctx.GetStub().PutState(ParamPrefix+proposal.ParameterName, []byte(proposal.ProposedValue)); err != nil {
			return nil, fmt.Errorf("FinaliseProposal: parameter write error: %w", err)
		}
		proposal.Status = "passed"
	} else {
		proposal.Status = "rejected"
	}

	proposal.FinalizedAt = now
	proposal.FinalizedBy = finalisedBy

	if err := gc.putProposal(ctx, proposal); err != nil {
		return nil, err
	}

	eventPayload, _ := json.Marshal(map[string]interface{}{
		"event":          "ProposalFinalised",
		"proposal_id":    proposalID,
		"status":         proposal.Status,
		"parameter_name": proposal.ParameterName,
		"new_value":      proposal.ProposedValue,
		"yes_count":      proposal.YesCount,
		"no_count":       proposal.NoCount,
	})
	ctx.GetStub().SetEvent("ProposalFinalised", eventPayload)

	return proposal, nil
}

// ─── QueryProposal ────────────────────────────────────────────────────────────

// QueryProposal reads a proposal by ID.
func (gc *GovernanceChaincode) QueryProposal(ctx contractapi.TransactionContextInterface, proposalID string) (*ProposalState, error) {
	return gc.getProposal(ctx, proposalID)
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

func (gc *GovernanceChaincode) getProposal(ctx contractapi.TransactionContextInterface, proposalID string) (*ProposalState, error) {
	stateBytes, err := ctx.GetStub().GetState(ProposalPrefix + proposalID)
	if err != nil {
		return nil, fmt.Errorf("getProposal: ledger read error: %w", err)
	}
	if stateBytes == nil {
		return nil, fmt.Errorf("getProposal: proposal %s not found", proposalID)
	}
	var proposal ProposalState
	if err := json.Unmarshal(stateBytes, &proposal); err != nil {
		return nil, fmt.Errorf("getProposal: unmarshal error: %w", err)
	}
	return &proposal, nil
}

func (gc *GovernanceChaincode) putProposal(ctx contractapi.TransactionContextInterface, proposal *ProposalState) error {
	proposalBytes, err := json.Marshal(proposal)
	if err != nil {
		return fmt.Errorf("putProposal: marshal error: %w", err)
	}
	return ctx.GetStub().PutState(ProposalPrefix+proposal.ProposalID, proposalBytes)
}

// ─── Main ─────────────────────────────────────────────────────────────────────

func main() {
	chaincode, err := contractapi.NewChaincode(&GovernanceChaincode{})
	if err != nil {
		panic(fmt.Sprintf("GovernanceChaincode: failed to create chaincode: %v", err))
	}
	if err := chaincode.Start(); err != nil {
		panic(fmt.Sprintf("GovernanceChaincode: failed to start chaincode: %v", err))
	}
}
