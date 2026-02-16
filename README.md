# Pay-Per-Thought  
### A Workflow-Governed AI Research Oracle using Chainlink CRE + x402 Micropayments

> An AI agent that cannot think unless a payment authorization exists.

Pay-Per-Thought is a Chainlink-style oracle service that provides autonomous research to users and other agents. Each reasoning step (search, analysis, synthesis) is gated by a payment authorization enforced by a Chainlink CRE workflow.

Instead of paying per API call, users — or other AI agents — pay **per reasoning step**.

---

## The Problem

AI agents today have no economic accountability.

When an LLM performs research:

- computation cost is opaque  
- tool usage is uncontrolled  
- autonomous agents cannot safely hire other agents  
- there is no verifiable metering of cognition  

Current APIs bill per token, not per decision.

This creates a missing primitive in decentralized systems:

> There is no reliable way for one autonomous agent to purchase verifiable reasoning from another.

---

## Our Solution

Pay-Per-Thought introduces **payment-gated cognition**.

Before the AI can execute a reasoning step, a payment authorization must exist.

### The workflow enforces:

authorize payment → execute tool → confirm → next step → settlement



This is implemented using a Chainlink CRE workflow with `evm_write` authorization gates.

The AI literally cannot continue thinking unless payment conditions are satisfied.

---

## Why Chainlink CRE

Chainlink CRE enables verifiable off-chain computation coordinated by on-chain state.

We use CRE to orchestrate:

- Payment authorization
- Tool execution (Tavily search)
- LLM reasoning (Gemini)
- Result synthesis
- Final settlement

The workflow acts as a deterministic controller over an otherwise nondeterministic AI.

This transforms an LLM into:

> a programmable economic service.

---

## Architecture

User / Agent
->
HTTP API (FastAPI)
->
CRE Workflow Runner
->
Payment Authorization (x402 model)
->
Tools + AI Execution
->
Structured Research Output



### Workflow Steps

1. Lock research budget
2. Authorize Tavily search
3. Execute search
4. Confirm execution
5. Authorize AI analysis
6. Execute LLM reasoning
7. Confirm execution
8. Settle payment

---

## What Makes This Novel

This project does **not** meter API usage.

It meters **cognition**.

The AI must economically justify each reasoning action.

This enables:

- agent-to-agent services
- DAO research oracles
- automated due-diligence systems
- programmable knowledge markets

Think of it as:

> Stripe for autonomous AI agents.

---

## Chainlink Features Used

- Chainlink CRE workflow orchestration
- EVM transaction authorization (`evm_write` nodes)
- Oracle-style off-chain computation
- Deterministic workflow-controlled execution
- On-chain settlement model (x402 micropayment concept)

---

## Quick Start (Judge Mode) ⭐

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/pay-per-thought-agent
cd pay-per-thought-agent
```

### 2. Setup Python Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install fastapi uvicorn python-dotenv requests pydantic google-genai tavily-python web3 eth-account pyyaml
```

### 4. Run the CRE Workflow Simulation
```bash
python3 scripts/run_real_workflow.py "What is Aave TVL?" --budget 0.5
```

You should see:
```yaml
Executing node: budget_lock
Executing node: step1_auth
Executing node: tavily
Executing node: step1_confirm
Executing node: step2_auth
Executing node: gemini
Executing node: step2_confirm
Executing node: settle
__CRE_RESULT_JSON__:{...}
```
This demonstrates a payment-gated AI reasoning workflow.

---

## Optional: Run the Web Interface
Start Backend API
```bash
uvicorn api.main:app --reload
```

Start Frontend
```bash
cd frontend
python3 -m http.server 3000
```


Open your browser:
```bash
http://localhost:3000
```

## Example Output
The system returns structured machine-readable research:
```bash
{
  "answer": "...",
  "confidence": "high",
  "steps_executed": 8,
  "total_cost_usd": 0.015
}
```

This output can be consumed by other agents or smart contracts.
---

### Demo Video

Add your video here:
```arduino
https://youtube.com/your-demo-video
```

## How This Fits Web3

Blockchains enabled trustless value transfer.

AI enables autonomous decision-making.

But Web3 still lacks:

trustless cognition markets

Pay-Per-Thought introduces a primitive where:

* agents can buy reasoning

* workflows enforce payment authorization

* results are structured and reproducible

This is a building block for decentralized autonomous economies.

## Team
Name : Sheriff (aka Phessophissy)

## License

MIT


---
