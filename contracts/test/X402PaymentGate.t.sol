// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../X402PaymentGate.sol";

/**
 * @title MockERC20
 * @notice Minimal ERC-20 for testing. Mints freely.
 */
contract MockERC20 {
    string public name = "MockUSDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 18;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "Insufficient balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "Insufficient balance");
        require(allowance[from][msg.sender] >= amount, "Insufficient allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/**
 * @title X402PaymentGateTest
 * @notice Unit tests for the X402PaymentGate contract.
 */
contract X402PaymentGateTest is Test {
    X402PaymentGate public gate;
    MockERC20 public token;

    address public operator = address(0xBEEF);
    address public payer = address(0xCAFE);

    bytes32 public sessionId = keccak256("test-session-001");
    bytes32 public step0 = keccak256("step_0");
    bytes32 public step1 = keccak256("step_1");
    bytes32 public step2 = keccak256("step_2");

    function setUp() public {
        token = new MockERC20();
        gate = new X402PaymentGate(address(token), operator);

        // Fund payer and approve gate
        token.mint(payer, 10e18);
        vm.prank(payer);
        token.approve(address(gate), 10e18);
    }

    // ─── lockBudget Tests ─────────────────────────────────────

    function test_lockBudget_success() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        (address p, uint256 locked, uint256 spent, uint256 steps, bool settled) = gate.sessions(sessionId);
        assertEq(p, payer);
        assertEq(locked, 1e18);
        assertEq(spent, 0);
        assertEq(steps, 3);
        assertFalse(settled);
    }

    function test_lockBudget_transfersTokens() public {
        uint256 balBefore = token.balanceOf(payer);
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);
        assertEq(token.balanceOf(payer), balBefore - 1e18);
        assertEq(token.balanceOf(address(gate)), 1e18);
    }

    function test_lockBudget_revertDuplicate() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);
        vm.prank(payer);
        vm.expectRevert("X402: session exists");
        gate.lockBudget(sessionId, 1e18, 3);
    }

    function test_lockBudget_revertZeroAmount() public {
        vm.prank(payer);
        vm.expectRevert("X402: zero amount");
        gate.lockBudget(sessionId, 0, 3);
    }

    // ─── authorizePayment (approveStep) Tests ─────────────────

    function test_authorizePayment_success() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);

        assertTrue(gate.isStepAuthorized(sessionId, step0));
    }

    function test_authorizePayment_revertNonOperator() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(payer); // not operator
        vm.expectRevert("X402: caller is not operator");
        gate.authorizePayment(sessionId, step0, 0.3e18);
    }

    function test_authorizePayment_revertExceedsBudget() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        vm.expectRevert("X402: exceeds budget");
        gate.authorizePayment(sessionId, step0, 2e18); // > locked
    }

    // ─── confirmExecution (consumeStep) Tests ─────────────────

    function test_confirmExecution_success() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);

        vm.prank(operator);
        gate.confirmExecution(sessionId, step0);

        assertTrue(gate.isStepConfirmed(sessionId, step0));
    }

    function test_confirmExecution_updatesSpent() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);
        vm.prank(operator);
        gate.confirmExecution(sessionId, step0);

        assertEq(gate.getRemainingBudget(sessionId), 0.7e18);
    }

    function test_confirmExecution_revertNotAuthorized() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        vm.expectRevert("X402: step not authorized");
        gate.confirmExecution(sessionId, step0);
    }

    // ─── refund Tests ─────────────────────────────────────────

    function test_refund_success() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);
        vm.prank(operator);
        gate.refund(sessionId, step0);

        // step is not confirmed, but refunded
        assertFalse(gate.isStepConfirmed(sessionId, step0));
    }

    function test_refund_revertIfConfirmed() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);
        vm.prank(operator);
        gate.confirmExecution(sessionId, step0);

        vm.prank(operator);
        vm.expectRevert("X402: already confirmed");
        gate.refund(sessionId, step0);
    }

    // ─── getRemainingBudget Tests ─────────────────────────────

    function test_remainingBudget_afterMultipleSteps() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        // Step 0: 0.3 tokens
        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);
        vm.prank(operator);
        gate.confirmExecution(sessionId, step0);

        // Step 1: 0.2 tokens
        vm.prank(operator);
        gate.authorizePayment(sessionId, step1, 0.2e18);
        vm.prank(operator);
        gate.confirmExecution(sessionId, step1);

        assertEq(gate.getRemainingBudget(sessionId), 0.5e18);
    }

    // ─── settleBudget Tests ───────────────────────────────────

    function test_settleBudget_refundsUnused() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.authorizePayment(sessionId, step0, 0.4e18);
        vm.prank(operator);
        gate.confirmExecution(sessionId, step0);

        uint256 payerBalBefore = token.balanceOf(payer);
        uint256 operatorBalBefore = token.balanceOf(operator);

        vm.prank(operator);
        gate.settleBudget(sessionId, 0.4e18);

        // Payer gets 0.6 back
        assertEq(token.balanceOf(payer), payerBalBefore + 0.6e18);
        // Operator gets 0.4
        assertEq(token.balanceOf(operator), operatorBalBefore + 0.4e18);
    }

    function test_settleBudget_revertDoubleSettle() public {
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        vm.prank(operator);
        gate.settleBudget(sessionId, 0);

        vm.prank(operator);
        vm.expectRevert("X402: session already settled");
        gate.settleBudget(sessionId, 0);
    }

    // ─── Full Lifecycle Test ─────────────────────────────────

    function test_fullLifecycle() public {
        // 1. Lock budget
        vm.prank(payer);
        gate.lockBudget(sessionId, 1e18, 3);

        // 2. Execute step 0 (success)
        vm.startPrank(operator);
        gate.authorizePayment(sessionId, step0, 0.3e18);
        gate.confirmExecution(sessionId, step0);

        // 3. Execute step 1 (success)
        gate.authorizePayment(sessionId, step1, 0.2e18);
        gate.confirmExecution(sessionId, step1);

        // 4. Step 2 fails (refund)
        gate.authorizePayment(sessionId, step2, 0.1e18);
        gate.refund(sessionId, step2);

        // 5. Settle
        assertEq(gate.getRemainingBudget(sessionId), 0.5e18);
        gate.settleBudget(sessionId, 0.5e18);
        vm.stopPrank();

        // Verify final state
        (, , , , bool settled) = gate.sessions(sessionId);
        assertTrue(settled);
    }
}
