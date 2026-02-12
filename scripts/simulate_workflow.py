#!/usr/bin/env python3
"""
Pay-Per-Thought Agent — Full Workflow Simulation (Gemini Edition - google-genai)
════════════════════════════════════════════════════════════════════════════════

Demonstrates the complete 3-phase pipeline:
  Phase 1: Planning    — decomposed by Gemini
  Phase 2: Execution   — x402 authorize → execute → confirm
  Phase 3: Synthesis   — aggregated by Gemini

Uses simulated x402 payments (no live contract) and mocked tool
outputs so the demo runs fully offline without API keys.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force simulation mode
os.environ["X402_LIVE"] = "false"
if not os.environ.get("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = "sim_key"


def banner(text: str):
    width = 60
    print(f"\n{'═' * width}")
    print(f"  {text}")
    print(f"{'═' * width}\n")


def phase_header(num: int, name: str):
    print(f"\n{'─' * 50}")
    print(f"  Phase {num}: {name}")
    print(f"{'─' * 50}")


def main():
    banner("PAY-PER-THOUGHT AGENT — WORKFLOW SIMULATION (GEMINI)")
    print(f"  Timestamp : {datetime.now(timezone.utc).isoformat()}")
    print(f"  x402 Mode : SIMULATION (no live contract)")
    print(f"  Query     : 'What is the current TVL of Aave v3?'")
    print(f"  Budget    : $0.50 USD")
    print()

    query = "What is the current TVL of Aave v3 on Ethereum mainnet?"
    max_budget = 0.50
    session_id = "sim_session_001"

    # ═══════════════════════════════════════════════════════
    # PHASE 1: PLANNING
    # ═══════════════════════════════════════════════════════
    phase_header(1, "PLANNING — Decompose Query into Metered Steps")

    # Mock the Gemini call to return a realistic plan
    mock_plan_text = json.dumps({
        "steps": [
            {"description": "Search for current Aave v3 TVL data across DeFi aggregators", "tool": "tavily", "estimated_cost_usd": 0.01},
            {"description": "Query Ethereum blockchain for Aave v3 pool contract balances", "tool": "blockchain_rpc", "estimated_cost_usd": 0.001},
            {"description": "Analyze TVL trends and cross-reference multiple data sources", "tool": "gemini", "estimated_cost_usd": 0.005},
            {"description": "Search for recent Aave governance proposals affecting TVL", "tool": "tavily", "estimated_cost_usd": 0.01},
            {"description": "Synthesize findings into structured research output", "tool": "gemini", "estimated_cost_usd": 0.005},
        ]
    })

    with patch("google.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value.text = mock_plan_text
        from agent.planning import generate_plan
        plan = generate_plan(query, max_budget, session_id)

    print(f"  ✓ Plan generated: {len(plan['steps'])} steps")
    print(f"  ✓ Total estimated cost: ${plan['total_estimated_cost']:.3f} (using Gemini pricing)")
    print(f"  ✓ Session ID: {plan['session_id']}")
    print()
    for s in plan["steps"]:
        print(f"    [{s['index']}] {s['tool']:>15} | ${s['estimated_cost_usd']:.3f} | {s['description'][:50]}...")
    print()

    # ═══════════════════════════════════════════════════════
    # PHASE 2: EXECUTION — x402 Gated
    # ═══════════════════════════════════════════════════════
    phase_header(2, "EXECUTION — x402 Authorize → Execute → Confirm")

    # Mock all tool executors with realistic outputs
    mock_tavily_1 = {
        "data": {
            "answer": "Aave v3 TVL on Ethereum is approximately $12.8 billion as of Feb 2026",
            "results": [
                {"title": "DeFiLlama - Aave v3", "url": "https://defillama.com/protocol/aave-v3", "snippet": "Current TVL: $12.8B", "score": 0.95},
                {"title": "Aave Analytics", "url": "https://aave.com/analytics", "snippet": "Protocol deposits exceed $12B", "score": 0.88},
            ],
        },
        "sources": ["https://defillama.com/protocol/aave-v3", "https://aave.com/analytics"],
    }

    mock_rpc = {
        "data": {"block_number": "0x13A2F4B"},
        "sources": ["rpc:https://ethereum-sepolia-rpc.publicnode.com"],
    }

    mock_gemini_1 = {
        "data": {
            "analysis": "Cross-referencing DeFiLlama, Aave's own analytics, and on-chain data confirms Aave v3 TVL on Ethereum mainnet is approximately $12.8B. This represents ~18% of total DeFi TVL.",
            "confidence": "high",
            "key_points": [
                "Aave v3 Ethereum TVL: ~$12.8B",
                "Largest single-chain deployment",
                "WETH and USDC are top collateral assets",
            ],
        },
        "sources": ["gemini:gemini-2.0-flash-exp"],
    }

    mock_tavily_2 = {
        "data": {
            "answer": "Recent proposal AIP-378 approved new risk parameters, expected to increase TVL",
            "results": [
                {"title": "Aave Governance Forum", "url": "https://governance.aave.com", "snippet": "AIP-378 passed", "score": 0.82},
            ],
        },
        "sources": ["https://governance.aave.com"],
    }

    mock_gemini_2 = {
        "data": {
            "analysis": "Final synthesis: Aave v3 on Ethereum has $12.8B TVL. Growth trajectory positive with recent governance proposals. High confidence in reported figures.",
            "confidence": "high",
            "key_points": ["Confirmed $12.8B TVL", "Growing trend", "Governance active"],
        },
        "sources": ["gemini:gemini-2.0-flash-exp"],
    }

    tool_responses = [mock_tavily_1, mock_rpc, mock_gemini_1, mock_tavily_2, mock_gemini_2]
    call_index = [0]

    def mock_tool_executor(tool):
        """Return a mock executor that serves pre-defined responses."""
        def executor(*args, **kwargs):
            idx = call_index[0]
            call_index[0] += 1
            time.sleep(0.3)  # Simulate latency
            return tool_responses[min(idx, len(tool_responses)-1)]
        return executor

    with patch("agent.executor._get_tool_executor", side_effect=mock_tool_executor):
        from agent.executor import execute_plan
        execution_result = execute_plan(plan)

    print()
    for sr in execution_result["step_results"]:
        status_icon = "✓" if sr["status"] == "completed" else "✗"
        tx = sr.get("payment_tx_hash", "N/A")[:30]
        print(f"    [{sr['index']}] {status_icon} {sr['status']:>10} | {sr['tool']:>15} | ${sr['actual_cost_usd']:.3f} | tx: {tx}...")

    print(f"\n  ✓ Total spent: ${execution_result['total_spent_usd']:.3f}")
    print(f"  ✓ Halted: {execution_result['was_halted']}")
    print(f"  ✓ Steps completed: {sum(1 for s in execution_result['step_results'] if s['status'] == 'completed')}/{len(execution_result['step_results'])}")

    # ═══════════════════════════════════════════════════════
    # PHASE 3: SYNTHESIS
    # ═══════════════════════════════════════════════════════
    phase_header(3, "SYNTHESIS — Aggregate Evidence into Final Answer")

    mock_synthesis_text = json.dumps({
        "answer": "Aave v3 on Ethereum mainnet currently holds approximately $12.8 billion in Total Value Locked (TVL), making it the largest single-chain DeFi lending deployment. Key collateral assets include WETH (~$5.2B), USDC (~$3.1B), and WBTC (~$1.8B). Recent governance proposal AIP-378 is expected to attract additional deposits through updated risk parameters.",
        "confidence": "high",
        "key_findings": [
            "Aave v3 Ethereum TVL: ~$12.8 billion",
            "Represents approximately 18% of total DeFi TVL",
            "Top collateral: WETH ($5.2B), USDC ($3.1B), WBTC ($1.8B)",
            "Active governance with AIP-378 recently approved",
            "Growth trajectory positive over last 90 days",
        ],
        "sources_used": [
            "https://defillama.com/protocol/aave-v3",
            "https://aave.com/analytics",
            "https://governance.aave.com",
            "rpc:ethereum-mainnet",
        ],
        "assumptions": [
            "TVL figures are denominated in USD at current market prices",
            "Data reflects the latest available snapshots from aggregators",
        ],
        "limitations": [
            "TVL fluctuates with asset prices — reported value is a point-in-time snapshot",
            "Some smaller collateral types not individually enumerated",
        ],
    })

    with patch("google.genai.Client") as MockClient:
        MockClient.return_value.models.generate_content.return_value.text = mock_synthesis_text
        from agent.synthesizer import synthesize_results
        synthesis = synthesize_results(
            query=query,
            step_results=execution_result["step_results"],
            total_spent_usd=execution_result["total_spent_usd"],
            was_halted=execution_result["was_halted"],
        )

    print(f"  ✓ Confidence: {synthesis['confidence']}")
    print(f"  ✓ Sources used: {len(synthesis.get('sources', []))}")
    print(f"  ✓ Key findings: {len(synthesis.get('key_findings', []))}")
    print()
    print("  Answer (truncated):")
    answer = synthesis.get("answer", "")
    print(f"    {answer[:200]}...")

    # ═══════════════════════════════════════════════════════
    # FINAL OUTPUT
    # ═══════════════════════════════════════════════════════
    banner("WORKFLOW COMPLETE — FULL JSON OUTPUT")

    full_response = {
        "status": "completed",
        "session_id": plan["session_id"],
        "query": query,
        "plan": {
            "steps": plan["steps"],
            "total_estimated_cost": plan["total_estimated_cost"],
            "step_count": len(plan["steps"]),
        },
        "actions": execution_result["step_results"],
        "results": synthesis,
        "settlement": {
            "total_locked_usd": max_budget,
            "total_spent_usd": execution_result["total_spent_usd"],
            "refund_usd": round(max_budget - execution_result["total_spent_usd"], 6),
            "settlement_tx_hash": f"sim_settle_{int(time.time())}",
            "status": "settled",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    output_json = json.dumps(full_response, indent=2, default=str)
    print(output_json)

    # Save to examples/
    output_dir = os.path.join(os.path.dirname(__file__), "..", "examples", "simulation-run-gemini")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "full_response.json")
    with open(output_path, "w") as f:
        f.write(output_json)

    print(f"\n  ✓ Saved to: {output_path}")

    banner("SIMULATION COMPLETE")
    print(f"  Pipeline:   planning (Gemini) → x402 auth → execution → synthesis (Gemini) → settlement")
    print(f"  Steps:      {len(plan['steps'])} executed, {sum(1 for s in execution_result['step_results'] if s['status'] == 'completed')} completed")
    print(f"  Budget:     ${max_budget:.2f} locked → ${execution_result['total_spent_usd']:.3f} spent → ${max_budget - execution_result['total_spent_usd']:.3f} refunded")
    print(f"  x402 Mode:  SIMULATION (all payments simulated)")
    print()


if __name__ == "__main__":
    main()
