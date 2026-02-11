// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Script.sol";
import "../X402PaymentGate.sol";

/**
 * @title ExampleUsage
 * @notice Demonstrates the full X402PaymentGate lifecycle:
 *         lockBudget → approveStep → consumeStep → remainingBudget → settleBudget
 *
 * Usage:
 *   forge script contracts/script/ExampleUsage.s.sol:ExampleUsage \
 *     --rpc-url $RPC_URL \
 *     --private-key $PRIVATE_KEY \
 *     --broadcast
 *
 * Prerequisites:
 *   - X402PaymentGate deployed (set X402_CONTRACT_ADDRESS)
 *   - ERC-20 token approved for the gate contract
 */
contract ExampleUsage is Script {
    function run() external {
        address gateAddr = vm.envAddress("X402_CONTRACT_ADDRESS");
        X402PaymentGate gate = X402PaymentGate(gateAddr);

        vm.startBroadcast();

        // ── Step 1: Lock budget for a new research session ──
        bytes32 sessionId = keccak256(abi.encodePacked("demo-session-001", block.timestamp));
        uint256 totalBudget = 1e18; // 1 token (e.g., 1 USDC with 18 decimals)
        uint256 stepCount = 3;

        gate.lockBudget(sessionId, totalBudget, stepCount);
        console.log("Budget locked. Session:", vm.toString(sessionId));

        // ── Step 2: Authorize payment for step 0 ──
        bytes32 step0 = keccak256("step_0");
        uint256 step0Cost = 0.4e18; // 0.4 tokens
        gate.authorizePayment(sessionId, step0, step0Cost);
        console.log("Step 0 authorized");

        // Verify authorization via approveStep alias
        bool isAuth = gate.isStepAuthorized(sessionId, step0);
        require(isAuth, "Step 0 should be authorized");
        console.log("approveStep check: PASS");

        // ── Step 3: Confirm execution of step 0 ──
        gate.confirmExecution(sessionId, step0);
        console.log("Step 0 confirmed (consumeStep)");

        // ── Step 4: Check remaining budget ──
        uint256 remaining = gate.getRemainingBudget(sessionId);
        console.log("Remaining budget:", remaining);
        require(remaining == totalBudget - step0Cost, "Budget math error");
        console.log("remainingBudget check: PASS");

        // ── Step 5: Authorize and confirm step 1 ──
        bytes32 step1 = keccak256("step_1");
        gate.authorizePayment(sessionId, step1, 0.3e18);
        gate.confirmExecution(sessionId, step1);
        console.log("Step 1 authorized + confirmed");

        // ── Step 6: Refund step 2 (simulating failure) ──
        bytes32 step2 = keccak256("step_2");
        gate.authorizePayment(sessionId, step2, 0.2e18);
        gate.refund(sessionId, step2);
        console.log("Step 2 authorized + refunded");

        // ── Step 7: Settle the session ──
        uint256 totalSpent = step0Cost + 0.3e18; // 0.7 tokens
        gate.settleBudget(sessionId, totalSpent);
        console.log("Session settled. Refund: 0.3 tokens returned to payer");

        vm.stopBroadcast();

        console.log("=== Example Complete ===");
    }
}
