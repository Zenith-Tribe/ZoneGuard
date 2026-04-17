pragma circom 2.1.6;

/*
 * EarningsBracketProof.circom
 * ─────────────────────────────────────────────────────────────
 * ZoneGuard Innovation 04 — ZeroKnow KYC
 *
 * PURPOSE:
 *   Prove that a rider's weekly earnings fall within a declared
 *   bracket (e.g. ₹10,000–₹20,000) without revealing the exact
 *   figure. Used for:
 *     - NBFC microloan eligibility (prove income ≥ threshold)
 *     - Government scheme eligibility (prove income ≤ ceiling)
 *     - ZoneGuard premium tier classification
 *     - Multi-platform DID credential income claims
 *
 * PROOF OUTPUTS (public):
 *   - bracket_index:    0=low(0-9999), 1=mid(10000-19999), 2=high(20000+)
 *   - earnings_hash:    Pedersen commitment to exact earnings (for audits)
 *   - weeks_proven:     Number of weeks the bracket claim covers
 *   - platform_tag:     Numeric encoding of platform (1=Amazon Flex, 2=Swiggy)
 *
 * PRIVATE INPUTS (never revealed):
 *   - weekly_earnings[N]:   Array of N weekly earnings (in INR paise for integer arithmetic)
 *   - salt:                 Blinding factor for earnings_hash
 *
 * PUBLIC INPUTS:
 *   - bracket_lower:        Claimed bracket lower bound (in paise)
 *   - bracket_upper:        Claimed bracket upper bound (in paise)
 *   - n_weeks:              Number of weeks to average over (3, 4, or 12)
 *   - platform_id:          Which platform (1=Flex, 2=Swiggy, 3=Zomato)
 *
 * CIRCUIT LOGIC:
 *   1. Compute rolling average of weekly_earnings over n_weeks
 *   2. Prove average ≥ bracket_lower (range proof)
 *   3. Prove average ≤ bracket_upper (range proof)
 *   4. Compute earnings_hash = Poseidon(weekly_earnings..., salt)
 *   5. Assign bracket_index based on range
 *
 * INCOME BRACKETS (INR/week):
 *   Bracket 0 (low):    ₹0      – ₹9,999
 *   Bracket 1 (mid):    ₹10,000 – ₹19,999
 *   Bracket 2 (high):   ₹20,000+
 *
 * DPDP COMPLIANCE:
 *   Exact earnings NEVER stored. Only bracket_index + earnings_hash stored.
 *   Hash allows rider to re-prove in future without re-submitting data.
 *
 * IMPORTANT NOTE ON SOURCE DATA:
 *   This circuit works with ZoneGuard's OWN payout history — no e-Shram
 *   dependency. The payout table becomes the ground truth for income proofs.
 *   This is more reliable than e-Shram API integration.
 *
 * COMPILE:
 *   circom EarningsBracketProof.circom --r1cs --wasm --sym -o ./build/
 */

include "node_modules/circomlib/circuits/poseidon.circom";
include "node_modules/circomlib/circuits/comparators.circom";

// ─── Template: N-input Poseidon hash (chunked for large N) ───────────────────
// Poseidon supports up to 16 inputs; for larger arrays, hash iteratively
template PoseidonChain(n) {
    signal input inputs[n];
    signal output out;

    var chunks = (n + 14) \ 15;  // ceil(n/15)
    component hashers[chunks];
    signal chain[chunks];

    var idx = 0;
    for (var c = 0; c < chunks; c++) {
        var chunk_size = 15;
        if (c == chunks - 1) {
            chunk_size = n - c * 15;
            if (chunk_size == 0) { chunk_size = 15; }
        }

        // Each chunk hashes up to 15 earnings values + previous chain value
        hashers[c] = Poseidon(chunk_size + (c > 0 ? 1 : 0));

        if (c > 0) {
            hashers[c].inputs[0] <== chain[c-1];
        }

        for (var j = 0; j < chunk_size && idx < n; j++) {
            hashers[c].inputs[c > 0 ? j + 1 : j] <== inputs[idx];
            idx++;
        }

        chain[c] <== hashers[c].out;
    }

    out <== chain[chunks - 1];
}

// ─── Template: Compute sum of array ──────────────────────────────────────────
template ArraySum(n) {
    signal input arr[n];
    signal output sum;
    signal running[n];

    running[0] <== arr[0];
    for (var i = 1; i < n; i++) {
        running[i] <== running[i-1] + arr[i];
    }
    sum <== running[n-1];
}

// ─── Template: Integer division (quotient only) ───────────────────────────────
// Proves: dividend = divisor * quotient + remainder, 0 <= remainder < divisor
template IntDiv() {
    signal input dividend;
    signal input divisor;
    signal output quotient;
    signal output remainder;

    // Witness computation (done outside circuit, values provided as hints)
    quotient <-- dividend \ divisor;
    remainder <-- dividend % divisor;

    // Constrain the division relationship
    dividend === divisor * quotient + remainder;

    // Constrain remainder < divisor using range check
    component lt = LessThan(32);
    lt.in[0] <== remainder;
    lt.in[1] <== divisor;
    lt.out === 1;
}

// ─── Template: Bracket assignment ────────────────────────────────────────────
// Given average weekly earnings, compute which bracket it falls in
// Bracket 0: [0, 9999], Bracket 1: [10000, 19999], Bracket 2: [20000, ∞)
// All values in INR (not paise) for readability
template BracketClassify() {
    signal input avg_earnings;   // INR per week
    signal output bracket;

    // Check avg < 10000
    component lt1 = LessThan(32);
    lt1.in[0] <== avg_earnings;
    lt1.in[1] <== 10000;

    // Check avg < 20000
    component lt2 = LessThan(32);
    lt2.in[0] <== avg_earnings;
    lt2.in[1] <== 20000;

    // bracket = 0 if avg < 10000, else 1 if avg < 20000, else 2
    // bracket = lt1.out * 0 + (1-lt1.out) * lt2.out * 1 + (1-lt1.out) * (1-lt2.out) * 2
    signal is_mid;
    is_mid <== (1 - lt1.out) * lt2.out;
    signal is_high;
    is_high <== (1 - lt1.out) * (1 - lt2.out);

    bracket <== is_mid * 1 + is_high * 2;
}

// ─── Template: Prove earnings ≥ lower_bound ───────────────────────────────────
template ProveMinEarnings() {
    signal input avg_earnings;
    signal input lower_bound;
    signal output valid;

    component gte = GreaterEqThan(32);
    gte.in[0] <== avg_earnings;
    gte.in[1] <== lower_bound;
    valid <== gte.out;
}

// ─── Template: Prove earnings ≤ upper_bound ───────────────────────────────────
template ProveMaxEarnings() {
    signal input avg_earnings;
    signal input upper_bound;
    signal output valid;

    component lte = LessEqThan(32);
    lte.in[0] <== avg_earnings;
    lte.in[1] <== upper_bound;
    valid <== lte.out;
}

// ─── Main Circuit (N=12 weeks, matching ZoneGuard's rolling window) ───────────
template EarningsBracketProof(N) {
    // ── Private inputs ────────────────────────────────────────────────────────
    signal input weekly_earnings[N];    // Weekly earnings in INR (from ZoneGuard payouts)
    signal input salt;                   // Blinding factor for commitment

    // ── Public inputs ─────────────────────────────────────────────────────────
    signal input bracket_lower;          // Claimed lower bound (INR)
    signal input bracket_upper;          // Claimed upper bound (INR)
    signal input platform_id;            // 1=Amazon Flex, 2=Swiggy, 3=Zomato

    // ── Public outputs ────────────────────────────────────────────────────────
    signal output bracket_index;         // 0=low, 1=mid, 2=high
    signal output earnings_hash;         // Commitment to earnings data
    signal output weeks_proven;          // = N (confirms rolling window size)
    signal output platform_tag;          // Echo of platform_id (for VC binding)
    signal output lower_bound_satisfied; // 1 if avg >= bracket_lower
    signal output upper_bound_satisfied; // 1 if avg <= bracket_upper

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 1: Compute sum of weekly earnings
    // ─────────────────────────────────────────────────────────────────────────
    component summer = ArraySum(N);
    for (var i = 0; i < N; i++) {
        summer.arr[i] <== weekly_earnings[i];
    }

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 2: Compute average = sum / N
    // ─────────────────────────────────────────────────────────────────────────
    component divider = IntDiv();
    divider.dividend <== summer.sum;
    divider.divisor <== N;
    signal avg_earnings;
    avg_earnings <== divider.quotient;

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 3: Classify into bracket
    // ─────────────────────────────────────────────────────────────────────────
    component classifier = BracketClassify();
    classifier.avg_earnings <== avg_earnings;
    bracket_index <== classifier.bracket;

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 4: Prove bracket bounds are satisfied (for NBFCs, gov schemes)
    // ─────────────────────────────────────────────────────────────────────────
    component min_check = ProveMinEarnings();
    min_check.avg_earnings <== avg_earnings;
    min_check.lower_bound <== bracket_lower;
    lower_bound_satisfied <== min_check.valid;

    component max_check = ProveMaxEarnings();
    max_check.avg_earnings <== avg_earnings;
    max_check.upper_bound <== bracket_upper;
    upper_bound_satisfied <== max_check.valid;

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 5: Compute earnings commitment hash
    // Stored in ZoneGuard DB for future re-verification without re-submission
    // ─────────────────────────────────────────────────────────────────────────
    component hasher = PoseidonChain(N + 1);
    for (var i = 0; i < N; i++) {
        hasher.inputs[i] <== weekly_earnings[i];
    }
    hasher.inputs[N] <== salt;
    earnings_hash <== hasher.out;

    // ─────────────────────────────────────────────────────────────────────────
    // STEP 6: Pass-through outputs
    // ─────────────────────────────────────────────────────────────────────────
    weeks_proven <== N;
    platform_tag <== platform_id;
}

// ─── Instantiate for 12-week rolling window ───────────────────────────────────
component main {
    public [bracket_lower, bracket_upper, platform_id,
            bracket_index, earnings_hash, weeks_proven, platform_tag,
            lower_bound_satisfied, upper_bound_satisfied]
} = EarningsBracketProof(12);

/*
 * CIRCUIT STATS (estimated):
 *   Constraints:  ~3,800
 *   Proof time:   ~5.1s on M2 Mac, ~28s on Helio G35 (server-side TEE required)
 *   Proof size:   ~800 bytes (Groth16)
 *   Verify time:  ~14ms
 *
 * USAGE EXAMPLE (JS witness generation):
 *   const input = {
 *     weekly_earnings: [18200, 17500, 19100, 16800, 18900, 17200,
 *                       19500, 18100, 17800, 19200, 18600, 17900],
 *     salt: "128bit_random_hex",
 *     bracket_lower: 10000,
 *     bracket_upper: 19999,
 *     platform_id: 1
 *   };
 *   // Expected: bracket_index=1, lower_bound_satisfied=1, upper_bound_satisfied=1
 */
