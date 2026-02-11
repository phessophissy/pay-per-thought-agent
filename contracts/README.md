# X402PaymentGate — Smart Contract

Minimal ERC-20 payment gate for metered cognition. Enforces per-step micropayment authorization for the Pay-Per-Thought autonomous research agent.

## Architecture

```
┌──────────┐    lockBudget()     ┌───────────────────┐
│   Payer   │ ──────────────────→ │  X402PaymentGate  │
│  (User)   │ ←──── refund ────── │                   │
└──────────┘    settleBudget()   │  ERC-20 escrow    │
                                  │                   │
┌──────────┐  authorizePayment() │                   │
│ Operator  │ ──────────────────→ │  Per-step auth    │
│  (Agent)  │  confirmExecution()│  + confirmation   │
│           │  refund()          │                   │
└──────────┘  settleBudget()     └───────────────────┘
```

## Contract Interface

| Function | Caller | Description |
|----------|--------|-------------|
| `lockBudget(sessionId, totalAmount, stepCount)` | Payer | Lock ERC-20 tokens for a research session |
| `authorizePayment(sessionId, stepId, amount)` | Operator | Authorize payment for a specific step |
| `confirmExecution(sessionId, stepId)` | Operator | Confirm step completed, finalize spend |
| `refund(sessionId, stepId)` | Operator | Refund a failed/skipped step |
| `settleBudget(sessionId, totalSpent)` | Operator | Settle session, refund unused budget |
| `getRemainingBudget(sessionId)` | Any | Returns remaining locked tokens |
| `isStepAuthorized(sessionId, stepId)` | Any | Check if step is authorized |
| `isStepConfirmed(sessionId, stepId)` | Any | Check if step is confirmed |

### Aliases used by agent executor

The Python agent executor (`agent/executor.py`) uses these contract methods:

- **`approveStep()`** → maps to `authorizePayment()`
- **`consumeStep()`** → maps to `confirmExecution()`
- **`remainingBudget()`** → maps to `getRemainingBudget()`

## Deploy with Foundry

### Prerequisites

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Install forge-std
forge install foundry-rs/forge-std --no-commit
```

### Deploy to Sepolia

```bash
# Set environment
export RPC_URL="https://ethereum-sepolia-rpc.publicnode.com"
export PRIVATE_KEY="0x..."
export PAYMENT_TOKEN_ADDRESS="0x..."   # ERC-20 token address
export OPERATOR_ADDRESS="0x..."         # Agent operator address
export ETHERSCAN_API_KEY="..."

# Deploy
forge script contracts/script/Deploy.s.sol:DeployPaymentGate \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast \
  --verify \
  --etherscan-api-key $ETHERSCAN_API_KEY

# Dry run (no broadcast)
forge script contracts/script/Deploy.s.sol:DeployPaymentGate \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY
```

### Run Example Usage

```bash
export X402_CONTRACT_ADDRESS="0x..."  # From deploy output

forge script contracts/script/ExampleUsage.s.sol:ExampleUsage \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY \
  --broadcast
```

## Run Tests

```bash
forge test --match-contract X402PaymentGateTest -vvv
```

## Payment Flow

```
1. User submits research query with budget
2. Agent calls lockBudget() — escrows total budget
3. For each execution step:
   a. Agent calls authorizePayment() — reserves step cost
   b. Agent executes tool (Claude/Tavily/RPC)
   c. On success: agent calls confirmExecution()
   d. On failure: agent calls refund()
4. Agent calls settleBudget() — returns unused funds to user
```

## Security

- Only the designated **operator** can authorize, confirm, refund, or settle payments
- Budget is locked upfront — payer cannot withdraw mid-session
- Each step can only be confirmed OR refunded, never both
- Settlement is idempotent — cannot settle twice
- Remaining budget is always refunded to the original payer
