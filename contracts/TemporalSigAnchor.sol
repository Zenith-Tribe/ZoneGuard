// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title TemporalSigAnchor
 * @author ZoneGuard Engineering
 * @notice Innovation 10: TemporalSig Archive
 *
 * @dev Stores keccak256 hashes of ZoneGuard's 15-minute QuadSignal polling
 *      batches on Polygon L2. The block.timestamp of the anchoring transaction
 *      becomes the immutable, consensus-certified proof of WHEN a signal
 *      reading occurred.
 *
 *      This eliminates the entire class of parametric insurance disputes about
 *      "when did the disruption actually begin" — the blockchain timestamp
 *      cannot be manipulated by any single party (ZoneGuard, insurer, or rider).
 *
 * Deployment target: Polygon PoS (Amoy testnet → Polygon mainnet)
 * Estimated cost per anchor: ~$0.0001 USD (calldata ~100 bytes @ 30 gwei)
 *
 * Usage pattern (called by TemporalSigClient every 15 minutes per zone):
 *   bytes32 hash = keccak256(abi.encodePacked(canonicalBatchJson));
 *   temporalSig.anchor(hash);
 *
 * Dispute resolution flow:
 *   1. Recompute hash from stored signal data
 *   2. Call getAnchor(hash) → returns block number + block.timestamp
 *   3. block.timestamp is the certified disruption detection time
 *   4. Share polygonscan link as immutable proof
 */
contract TemporalSigAnchor {

    // -----------------------------------------------------------------------
    // Structs
    // -----------------------------------------------------------------------

    struct AnchorRecord {
        uint256 blockNumber;        // Polygon block number when anchored
        uint256 blockTimestamp;     // block.timestamp — the proof timestamp
        address anchorer;           // ZoneGuard wallet that submitted the tx
        bool exists;                // Guard against zero-value confusion
    }

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------

    /// @notice Owner address — can update authorized anchorer list
    address public owner;

    /// @notice Mapping from signal batch hash → anchor record
    mapping(bytes32 => AnchorRecord) private _anchors;

    /// @notice Authorized addresses allowed to call anchor()
    /// Only ZoneGuard's backend wallet(s) should be in this set
    mapping(address => bool) public authorizedAnchorer;

    /// @notice Total number of anchors ever submitted
    uint256 public totalAnchors;

    // -----------------------------------------------------------------------
    // Events
    // -----------------------------------------------------------------------

    /**
     * @notice Emitted on every successful anchor operation.
     * @param hash              keccak256 of the signal batch canonical JSON
     * @param blockTimestamp    block.timestamp — the immutable proof time
     * @param blockNumber       block number for PolygonScan link
     * @param anchorer          wallet that submitted this anchor
     */
    event Anchored(
        bytes32 indexed hash,
        uint256 blockTimestamp,
        uint256 indexed blockNumber,
        address indexed anchorer
    );

    /**
     * @notice Emitted when an authorized anchorer is added or removed.
     */
    event AnchorerUpdated(address indexed anchorer, bool authorized);

    // -----------------------------------------------------------------------
    // Modifiers
    // -----------------------------------------------------------------------

    modifier onlyOwner() {
        require(msg.sender == owner, "TemporalSig: caller is not owner");
        _;
    }

    modifier onlyAuthorized() {
        require(
            authorizedAnchorer[msg.sender] || msg.sender == owner,
            "TemporalSig: caller not authorized to anchor"
        );
        _;
    }

    // -----------------------------------------------------------------------
    // Constructor
    // -----------------------------------------------------------------------

    /**
     * @param initialAnchorer   ZoneGuard backend wallet address
     */
    constructor(address initialAnchorer) {
        owner = msg.sender;
        authorizedAnchorer[initialAnchorer] = true;
        emit AnchorerUpdated(initialAnchorer, true);
    }

    // -----------------------------------------------------------------------
    // Core: Anchor a signal batch hash
    // -----------------------------------------------------------------------

    /**
     * @notice Anchor a keccak256 hash to the Polygon blockchain.
     *
     * @dev Called by ZoneGuard backend every 15 minutes per zone.
     *      The block.timestamp of this transaction is the canonical proof of
     *      when the signal batch was observed.
     *
     *      IMPORTANT: Each hash can only be anchored once. Duplicate anchors
     *      are rejected to prevent timestamp manipulation (e.g., re-anchoring
     *      an old hash to a newer block).
     *
     * @param hash  keccak256(canonicalBatchJson) from Python backend
     */
    function anchor(bytes32 hash) external onlyAuthorized {
        require(hash != bytes32(0), "TemporalSig: hash cannot be zero");
        require(!_anchors[hash].exists, "TemporalSig: hash already anchored");

        _anchors[hash] = AnchorRecord({
            blockNumber:    block.number,
            blockTimestamp: block.timestamp,   // consensus-set by Polygon validators
            anchorer:       msg.sender,
            exists:         true
        });

        totalAnchors++;

        emit Anchored(hash, block.timestamp, block.number, msg.sender);
    }

    // -----------------------------------------------------------------------
    // Read: Query an anchor
    // -----------------------------------------------------------------------

    /**
     * @notice Get the anchor record for a hash.
     *
     * @param hash  keccak256 of the signal batch
     * @return blockNumber      Block when anchored
     * @return blockTimestamp   Unix timestamp (UTC) — the immutable proof time
     * @return anchorer         Address that submitted the anchor
     *
     * Returns (0, 0, address(0)) if hash was never anchored.
     */
    function getAnchor(bytes32 hash)
        external
        view
        returns (
            uint256 blockNumber,
            uint256 blockTimestamp,
            address anchorer
        )
    {
        AnchorRecord storage record = _anchors[hash];
        return (record.blockNumber, record.blockTimestamp, record.anchorer);
    }

    /**
     * @notice Check if a hash has been anchored.
     * @param hash  keccak256 of the signal batch
     * @return true if anchored, false otherwise
     */
    function exists(bytes32 hash) external view returns (bool) {
        return _anchors[hash].exists;
    }

    /**
     * @notice Get the consensus timestamp for a hash (convenience function).
     *         Returns 0 if not anchored.
     * @param hash  keccak256 of the signal batch
     * @return Unix timestamp when this signal batch was anchored
     */
    function getTimestamp(bytes32 hash) external view returns (uint256) {
        return _anchors[hash].blockTimestamp;
    }

    // -----------------------------------------------------------------------
    // Admin: Manage authorized anchorer wallets
    // -----------------------------------------------------------------------

    /**
     * @notice Add or remove an authorized anchorer wallet.
     *         Used when rotating ZoneGuard's backend wallet keys.
     * @param anchorer      Wallet address to update
     * @param authorized    true to add, false to remove
     */
    function setAuthorizedAnchorer(
        address anchorer,
        bool authorized
    ) external onlyOwner {
        require(anchorer != address(0), "TemporalSig: zero address");
        authorizedAnchorer[anchorer] = authorized;
        emit AnchorerUpdated(anchorer, authorized);
    }

    /**
     * @notice Transfer contract ownership.
     * @param newOwner  New owner address (e.g., a multisig for production)
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "TemporalSig: zero address");
        owner = newOwner;
    }
}
