# Pay-Per-Thought Autonomous Research Agent

A Chainlink CRE-orchestrated research agent with x402 micropayment enforcement. Every reasoning step is metered, authorized, and verifiable.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Server (/research)                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐    ┌───────────────┐    ┌──────────────┐         │
│  │  Phase 1  │───▶│    Phase 2     │───▶│   Phase 3    │        │
│  │ Planning  │    │   Execution   │    │  Synthesis   │        │
│  │           │    │               │    │              │        │
│  │ - Decompose│    │ For each step:│    │ - Aggregate  │        │
│  │ - Estimate │    │ - x402 auth   │    │ - Source     │        │
│  │ - Budget   │    │ - Execute     │    │ - Confidence │        │
│  └──────────┘    │ - Persist     │    └──────────────┘        │
│                  └───────────────┘                              │
│                         │                                       │
│          ┌──────────────┼──────────────┐                       │
│          ▼              ▼              ▼                       │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐              │
│  │ Claude Opus  │ │  Tavily  │ │ Blockchain   │              │
│  │ (Reasoning)  │ │ (Search) │ │ (RPC Calls)  │              │
│  └──────────────┘ └──────────┘ └──────────────┘              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│              CRE Workflow Orchestration Layer                   │
├─────────────────────────────────────────────────────────────────┤
│         x402 Payment Gate Contract (ERC-20 Based)              │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
pay-per-thought-agent/
├── agent/          # Core agent logic (TypeScript)
│   ├── types.ts
│   ├── planner.ts
│   ├── executor.ts
│   └── synthesizer.ts
├── api/            # FastAPI server (Python)
│   ├── main.py
│   ├── config.py
│   └── requirements.txt
├── contracts/      # x402 payment contract (Solidity)
│   ├── IX402PaymentGate.sol
│   └── X402PaymentGate.sol
├── cre/            # CRE workflow definition
│   └── workflow.yaml
├── frontend/       # Demo UI
│   └── index.html
├── .env.example
└── README.md
```

## Setup

1. Install dependencies:
   ```bash
   cd api && pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your keys:
   ```bash
   cp .env.example .env
   ```

3. Start the API server:
   ```bash
   cd api && uvicorn main:app --reload --port 8000
   ```

4. Send a research request:
   ```bash
   curl -X POST http://localhost:8000/research \
     -H "Content-Type: application/json" \
     -d '{"query": "What is the current TVL of Aave?", "max_budget": 0.50}'
   ```

## CRE Deployment

```bash
cre login
cre init -p pay-per-thought-agent
cre workflow deploy
cre workflow activate
```

## License

MIT
