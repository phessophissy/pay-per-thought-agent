// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ═══════════════════════════════════════════════════════════════
// FLATTENED FOR REMIX — All contracts in a single file.
// Deploy order:
//   1. SimpleERC20 (payment token)
//   2. X402PaymentGate (payment gate)
// ═══════════════════════════════════════════════════════════════

// ─── Minimal ERC-20 Interface ────────────────────────────────

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

// ─── IX402PaymentGate Interface ──────────────────────────────

interface IX402PaymentGate {
    event BudgetLocked(bytes32 indexed sessionId, address indexed payer, uint256 totalAmount, uint256 stepCount);
    event PaymentAuthorized(bytes32 indexed sessionId, bytes32 indexed stepId, uint256 amount);
    event ExecutionConfirmed(bytes32 indexed sessionId, bytes32 indexed stepId);
    event PaymentRefunded(bytes32 indexed sessionId, bytes32 indexed stepId, uint256 amount);
    event BudgetSettled(bytes32 indexed sessionId, uint256 totalSpent, uint256 refunded);

    function lockBudget(bytes32 sessionId, uint256 totalAmount, uint256 stepCount) external;
    function authorizePayment(bytes32 sessionId, bytes32 stepId, uint256 amount) external;
    function confirmExecution(bytes32 sessionId, bytes32 stepId) external;
    function refund(bytes32 sessionId, bytes32 stepId) external;
    function settleBudget(bytes32 sessionId, uint256 totalSpent) external;
    function getRemainingBudget(bytes32 sessionId) external view returns (uint256);
    function isStepAuthorized(bytes32 sessionId, bytes32 stepId) external view returns (bool);
    function isStepConfirmed(bytes32 sessionId, bytes32 stepId) external view returns (bool);
}

// ─── X402PaymentGate Contract ────────────────────────────────

/**
 * @title X402PaymentGate
 * @notice Minimal ERC-20 based payment gate for the Pay-Per-Thought
 *         Autonomous Research Agent. Enforces per-step micropayment
 *         authorization for metered cognition.
 *
 * Flow:
 *   1. lockBudget()        — Payer locks total estimated budget
 *   2. authorizePayment()  — Agent authorizes payment per step
 *   3. confirmExecution()  — Agent confirms step completed
 *      OR refund()         — Agent refunds if step failed
 *   4. settleBudget()      — Release unused funds back to payer
 *
 * Remix Deploy:
 *   Compiler: 0.8.24+
 *   Constructor: (paymentTokenAddress, operatorAddress)
 */
contract X402PaymentGate is IX402PaymentGate {
    // ─── State ───────────────────────────────────────────────

    IERC20 public immutable paymentToken;
    address public immutable operator;

    struct Session {
        address payer;
        uint256 totalLocked;
        uint256 totalSpent;
        uint256 stepCount;
        bool settled;
    }

    struct StepPayment {
        uint256 amount;
        bool authorized;
        bool confirmed;
        bool refunded;
    }

    mapping(bytes32 => Session) public sessions;
    mapping(bytes32 => mapping(bytes32 => StepPayment)) public stepPayments;

    // ─── Modifiers ───────────────────────────────────────────

    modifier onlyOperator() {
        require(msg.sender == operator, "X402: caller is not operator");
        _;
    }

    modifier sessionExists(bytes32 sessionId) {
        require(sessions[sessionId].payer != address(0), "X402: session not found");
        _;
    }

    modifier sessionNotSettled(bytes32 sessionId) {
        require(!sessions[sessionId].settled, "X402: session already settled");
        _;
    }

    // ─── Constructor ─────────────────────────────────────────

    constructor(address _paymentToken, address _operator) {
        paymentToken = IERC20(_paymentToken);
        operator = _operator;
    }

    // ─── Core Functions ──────────────────────────────────────

    function lockBudget(
        bytes32 sessionId,
        uint256 totalAmount,
        uint256 stepCount
    ) external override {
        require(sessions[sessionId].payer == address(0), "X402: session exists");
        require(totalAmount > 0, "X402: zero amount");
        require(stepCount > 0, "X402: zero steps");

        require(
            paymentToken.transferFrom(msg.sender, address(this), totalAmount),
            "X402: transfer failed"
        );

        sessions[sessionId] = Session({
            payer: msg.sender,
            totalLocked: totalAmount,
            totalSpent: 0,
            stepCount: stepCount,
            settled: false
        });

        emit BudgetLocked(sessionId, msg.sender, totalAmount, stepCount);
    }

    function authorizePayment(
        bytes32 sessionId,
        bytes32 stepId,
        uint256 amount
    )
        external
        override
        onlyOperator
        sessionExists(sessionId)
        sessionNotSettled(sessionId)
    {
        Session storage session = sessions[sessionId];
        require(session.totalSpent + amount <= session.totalLocked, "X402: exceeds budget");
        require(!stepPayments[sessionId][stepId].authorized, "X402: step already authorized");

        stepPayments[sessionId][stepId] = StepPayment({
            amount: amount,
            authorized: true,
            confirmed: false,
            refunded: false
        });

        emit PaymentAuthorized(sessionId, stepId, amount);
    }

    function confirmExecution(
        bytes32 sessionId,
        bytes32 stepId
    )
        external
        override
        onlyOperator
        sessionExists(sessionId)
        sessionNotSettled(sessionId)
    {
        StepPayment storage step = stepPayments[sessionId][stepId];
        require(step.authorized, "X402: step not authorized");
        require(!step.confirmed, "X402: already confirmed");
        require(!step.refunded, "X402: already refunded");

        step.confirmed = true;
        sessions[sessionId].totalSpent += step.amount;

        emit ExecutionConfirmed(sessionId, stepId);
    }

    function refund(
        bytes32 sessionId,
        bytes32 stepId
    )
        external
        override
        onlyOperator
        sessionExists(sessionId)
        sessionNotSettled(sessionId)
    {
        StepPayment storage step = stepPayments[sessionId][stepId];
        require(step.authorized, "X402: step not authorized");
        require(!step.confirmed, "X402: already confirmed");
        require(!step.refunded, "X402: already refunded");

        step.refunded = true;

        emit PaymentRefunded(sessionId, stepId, step.amount);
    }

    function settleBudget(
        bytes32 sessionId,
        uint256 totalSpent
    )
        external
        override
        onlyOperator
        sessionExists(sessionId)
        sessionNotSettled(sessionId)
    {
        Session storage session = sessions[sessionId];
        require(totalSpent <= session.totalLocked, "X402: spent exceeds locked");

        session.totalSpent = totalSpent;
        session.settled = true;

        uint256 refundAmount = session.totalLocked - totalSpent;
        if (refundAmount > 0) {
            require(paymentToken.transfer(session.payer, refundAmount), "X402: refund transfer failed");
        }

        if (totalSpent > 0) {
            require(paymentToken.transfer(operator, totalSpent), "X402: operator transfer failed");
        }

        emit BudgetSettled(sessionId, totalSpent, refundAmount);
    }

    // ─── View Functions ──────────────────────────────────────

    function getRemainingBudget(bytes32 sessionId) external view override returns (uint256) {
        Session storage session = sessions[sessionId];
        return session.totalLocked - session.totalSpent;
    }

    function isStepAuthorized(bytes32 sessionId, bytes32 stepId) external view override returns (bool) {
        return stepPayments[sessionId][stepId].authorized;
    }

    function isStepConfirmed(bytes32 sessionId, bytes32 stepId) external view override returns (bool) {
        return stepPayments[sessionId][stepId].confirmed;
    }
}
