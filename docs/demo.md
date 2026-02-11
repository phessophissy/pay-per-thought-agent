# Demo Script — Pay-Per-Thought Agent

**Duration:** ~3 minutes  
**Audience:** Chainlink Hackathon judges  
**Goal:** Show metered cognition with x402 micropayments in action

---

## Setup (before demo)

```bash
# Terminal 1: Start API server
cd pay-per-thought-agent/api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2: Start frontend
cd pay-per-thought-agent/frontend
python -m http.server 3000
```

Ensure `.env` has valid `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`.

---

## Demo Flow

### [0:00–0:30] Introduction

> "This is Pay-Per-Thought — an autonomous research agent where every reasoning step costs money. The agent decomposes queries into atomic steps, authorizes each one through an x402 payment contract on-chain, and only executes if payment is approved."

**Show:** Architecture diagram in README.

### [0:30–1:00] Submit a Research Query

1. Open `http://localhost:3000`
2. Enter: **"What is the current TVL of Aave v3 on Ethereum mainnet?"**
3. Set budget: **$0.50**
4. Click **Execute**

**Point out:**
- The budget meter appears immediately
- Status shows "Phase 1: Planning"

### [1:00–2:00] Watch Execution

**As steps appear in the timeline, narrate:**

> "The planner decomposed this into 5 steps. Watch — each step shows an x402 payment badge. The green ✓ means on-chain payment was authorized before the tool was invoked."

**Point out:**
- Each step shows: tool type, cost, duration, tx hash
- Budget meter fills progressively
- Steps use different tools: Tavily for search, Claude for analysis, RPC for chain data

### [2:00–2:30] Review Results

**When synthesis completes:**

> "The synthesizer aggregated all evidence into a structured answer with confidence scoring. Every claim is traced back to its source — no hallucinated data."

**Point out:**
- Confidence badge (HIGH/MEDIUM/LOW)
- Key findings with source attribution
- Assumptions and limitations explicitly listed
- Total cost in stats bar

### [2:30–3:00] Show the Infrastructure

> "Under the hood, this is powered by three layers."

1. **Click "View Raw JSON"** — show the complete response structure
2. **Show the terminal** — API logs showing the 3-phase pipeline
3. **Briefly show `contracts/README.md`** — the x402 payment gate lifecycle

> "The x402 contract enforces budget caps on-chain. If the budget is exceeded, the agent halts and partial results are synthesized. Unused funds are automatically refunded via settleBudget()."

**Final statement:**

> "Every thought costs money. Every payment is verifiable. This is metered cognition."

---

## Demo with Budget Halting

To demonstrate the halt behavior:

1. Set budget to **$0.05**
2. Submit the same query
3. Watch the agent halt after 1-2 steps
4. Note the ⚠ PARTIAL RESULTS warning
5. Budget meter shows consumption stopped

---

## Fallback: CLI Demo

If the frontend has issues, use curl:

```bash
curl -s -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"task": "What is Ethereum current block number?", "max_budget": "0.10"}' \
  | python -m json.tool
```

---

## Key Talking Points

- **x402 micropayments**: every step is gated by on-chain authorization
- **Budget enforcement**: the agent halts if budget is exceeded
- **Source attribution**: no hallucinated data — every claim traced to a source
- **Deterministic pipeline**: plan → authorize → execute → confirm → synthesize
- **Chainlink CRE**: workflow.yaml defines the entire pipeline as a CRE-native workflow
- **Refund mechanism**: unused budget is automatically returned to the payer
