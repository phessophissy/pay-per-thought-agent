// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IX402PaymentGate
 * @notice Interface for the x402 micropayment gate used by the
 *         Pay-Per-Thought Autonomous Research Agent.
 *
 * Each research session locks a total budget. Individual steps
 * are authorized, executed, and either confirmed or refunded.
 */
interface IX402PaymentGate {
    // ─── Events ──────────────────────────────────────────────

    event BudgetLocked(
        bytes32 indexed sessionId,
        address indexed payer,
        uint256 totalAmount,
        uint256 stepCount
    );

    event PaymentAuthorized(
        bytes32 indexed sessionId,
        bytes32 indexed stepId,
        uint256 amount
    );

    event ExecutionConfirmed(
        bytes32 indexed sessionId,
        bytes32 indexed stepId
    );

    event PaymentRefunded(
        bytes32 indexed sessionId,
        bytes32 indexed stepId,
        uint256 amount
    );

    event BudgetSettled(
        bytes32 indexed sessionId,
        uint256 totalSpent,
        uint256 refunded
    );

    // ─── Core Functions ──────────────────────────────────────

    /**
     * @notice Lock the total estimated budget for a research session.
     * @param sessionId  Unique identifier for the research session.
     * @param totalAmount Total budget to lock (in payment token units).
     * @param stepCount  Number of planned steps.
     */
    function lockBudget(
        bytes32 sessionId,
        uint256 totalAmount,
        uint256 stepCount
    ) external;

    /**
     * @notice Authorize payment for a specific execution step.
     * @param sessionId  Session this step belongs to.
     * @param stepId     Unique identifier for the step.
     * @param amount     Amount to authorize for this step.
     */
    function authorizePayment(
        bytes32 sessionId,
        bytes32 stepId,
        uint256 amount
    ) external;

    /**
     * @notice Confirm that a step executed successfully.
     *         Finalizes the payment for that step.
     * @param sessionId  Session this step belongs to.
     * @param stepId     Step to confirm.
     */
    function confirmExecution(
        bytes32 sessionId,
        bytes32 stepId
    ) external;

    /**
     * @notice Refund a step that failed or was not executed.
     * @param sessionId  Session this step belongs to.
     * @param stepId     Step to refund.
     */
    function refund(
        bytes32 sessionId,
        bytes32 stepId
    ) external;

    /**
     * @notice Settle the session — release unused budget back to payer.
     * @param sessionId  Session to settle.
     * @param totalSpent Total amount actually consumed.
     */
    function settleBudget(
        bytes32 sessionId,
        uint256 totalSpent
    ) external;

    // ─── View Functions ──────────────────────────────────────

    /**
     * @notice Get the remaining budget for a session.
     */
    function getRemainingBudget(
        bytes32 sessionId
    ) external view returns (uint256);

    /**
     * @notice Check if a step has been authorized.
     */
    function isStepAuthorized(
        bytes32 sessionId,
        bytes32 stepId
    ) external view returns (bool);

    /**
     * @notice Check if a step has been confirmed.
     */
    function isStepConfirmed(
        bytes32 sessionId,
        bytes32 stepId
    ) external view returns (bool);
}
