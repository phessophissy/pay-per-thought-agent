// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./IX402PaymentGate.sol";

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

    /**
     * @notice Lock total budget for a research session.
     *         Transfers ERC-20 tokens from payer to this contract.
     */
    function lockBudget(
        bytes32 sessionId,
        uint256 totalAmount,
        uint256 stepCount
    ) external override {
        require(sessions[sessionId].payer == address(0), "X402: session exists");
        require(totalAmount > 0, "X402: zero amount");
        require(stepCount > 0, "X402: zero steps");

        // Transfer payment tokens to contract
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

    /**
     * @notice Authorize payment for a specific step.
     *         Can only be called by the operator (CRE workflow).
     */
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
        require(
            session.totalSpent + amount <= session.totalLocked,
            "X402: exceeds budget"
        );
        require(
            !stepPayments[sessionId][stepId].authorized,
            "X402: step already authorized"
        );

        stepPayments[sessionId][stepId] = StepPayment({
            amount: amount,
            authorized: true,
            confirmed: false,
            refunded: false
        });

        emit PaymentAuthorized(sessionId, stepId, amount);
    }

    /**
     * @notice Confirm a step executed successfully.
     *         Finalizes the spend for that step.
     */
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

    /**
     * @notice Refund a step that failed.
     *         Returns the step's amount to the available budget.
     */
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

    /**
     * @notice Settle the session. Releases unused budget back to payer.
     */
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
        require(
            totalSpent <= session.totalLocked,
            "X402: spent exceeds locked"
        );

        session.totalSpent = totalSpent;
        session.settled = true;

        uint256 refundAmount = session.totalLocked - totalSpent;
        if (refundAmount > 0) {
            require(
                paymentToken.transfer(session.payer, refundAmount),
                "X402: refund transfer failed"
            );
        }

        // Transfer spent amount to operator
        if (totalSpent > 0) {
            require(
                paymentToken.transfer(operator, totalSpent),
                "X402: operator transfer failed"
            );
        }

        emit BudgetSettled(sessionId, totalSpent, refundAmount);
    }

    // ─── View Functions ──────────────────────────────────────

    function getRemainingBudget(
        bytes32 sessionId
    ) external view override returns (uint256) {
        Session storage session = sessions[sessionId];
        return session.totalLocked - session.totalSpent;
    }

    function isStepAuthorized(
        bytes32 sessionId,
        bytes32 stepId
    ) external view override returns (bool) {
        return stepPayments[sessionId][stepId].authorized;
    }

    function isStepConfirmed(
        bytes32 sessionId,
        bytes32 stepId
    ) external view override returns (bool) {
        return stepPayments[sessionId][stepId].confirmed;
    }
}

// ─── Minimal ERC-20 Interface ────────────────────────────────

interface IERC20 {
    function transferFrom(
        address from,
        address to,
        uint256 amount
    ) external returns (bool);

    function transfer(
        address to,
        uint256 amount
    ) external returns (bool);

    function balanceOf(address account) external view returns (uint256);
}
