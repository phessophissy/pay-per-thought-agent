#!/usr/bin/env python3
"""
Pay-Per-Thought Agent — Real Workflow Execution (Gemini Edition)
════════════════════════════════════════════════════════════════

Executes the complete 3-phase pipeline with REAL API calls:
  Phase 1: Planning    — Gemini 2.0 Flash
  Phase 2: Execution   — Tavily Search + Gemini Analysis + RPC
  Phase 3: Synthesis   — Gemini 2.0 Flash

Payment Mode: SIMULATED (X402_LIVE=false)
  - Grants authorization automatically
  - Tracks "spent" budget based on estimated costs
  - Does NOT require a funded crypto wallet
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
import dotenv

# Load environment variables
dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import agent modules (REAL logic)
from agent.planning import generate_plan
from agent.executor import execute_plan
from agent.synthesizer import synthesize_results

# We default to false here to ensure the script runs out-of-the-box for new users,
# but if the user has configured X402_LIVE=true in .env, we respect it.
if os.environ.get("X402_LIVE", "").lower() != "true":
    os.environ["X402_LIVE"] = "false"

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
    # Allow query via command line arg
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "What is the current TVL of Aave v3 on Ethereum mainnet?"

    max_budget = 0.50
    session_id = f"real_run_{int(time.time())}"

    banner("PAY-PER-THOUGHT AGENT — REAL WORKFLOW EXECUTION")
    print(f"  Timestamp : {datetime.now(timezone.utc).isoformat()}")
    print(f"  x402 Mode : {os.environ.get('X402_LIVE', 'false').upper()} (Payments)")
    print(f"  LLM Model : {os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')}")
    print(f"  Query     : '{query}'")
    print(f"  Budget    : ${max_budget:.2f} USD")
    print()

    # ═══════════════════════════════════════════════════════
    # PHASE 1: PLANNING
    # ═══════════════════════════════════════════════════════
    phase_header(1, "PLANNING — Decompose Query into Metered Steps")
    
    try:
        plan = generate_plan(query, max_budget, session_id)
        
        print(f"  ✓ Plan generated: {len(plan['steps'])} steps")
        print(f"  ✓ Total estimated cost: ${plan['total_estimated_cost']:.3f}")
        print(f"  ✓ Session ID: {plan['session_id']}")
        print()
        for s in plan["steps"]:
            print(f"    [{s['index']}] {s['tool']:>15} | ${s['estimated_cost_usd']:.3f} | {s['description'][:60]}...")
        print()
    except Exception as e:
        print(f"  ✗ Planning failed: {e}")
        return

    # ═══════════════════════════════════════════════════════
    # PHASE 2: EXECUTION — x402 Gated + Real Tools
    # ═══════════════════════════════════════════════════════
    phase_header(2, "EXECUTION — Real Tool Calls (Tavily/Gemini/RPC)")
    
    try:
        execution_result = execute_plan(plan)
        
        print()
        for sr in execution_result["step_results"]:
            status_icon = "✓" if sr["status"] == "completed" else "✗"
            tx = sr.get("payment_tx_hash", "N/A")
            if tx and len(tx) > 10: tx = tx[:10] + "..."
            
            output_preview = str(sr.get("output", ""))[:50].replace("\n", " ") + "..."
            
            print(f"    [{sr['index']}] {status_icon} {sr['status']:>10} | {sr['tool']:>15} | ${sr['actual_cost_usd']:.3f} | {output_preview}")

        print(f"\n  ✓ Total spent: ${execution_result['total_spent_usd']:.3f}")
        print(f"  ✓ Halted: {execution_result['was_halted']}")
        print(f"  ✓ Steps completed: {sum(1 for s in execution_result['step_results'] if s['status'] == 'completed')}/{len(execution_result['step_results'])}")

    except Exception as e:
        print(f"  ✗ Execution failed: {e}")
        return

    # ═══════════════════════════════════════════════════════
    # PHASE 3: SYNTHESIS
    # ═══════════════════════════════════════════════════════
    phase_header(3, "SYNTHESIS — Aggregate Evidence into Final Answer")

    try:
        synthesis = synthesize_results(
            query=query,
            step_results=execution_result["step_results"],
            total_spent_usd=execution_result["total_spent_usd"],
            was_halted=execution_result["was_halted"],
        )

        print(f"  ✓ Confidence: {synthesis.get('confidence', 'N/A')}")
        print(f"  ✓ Sources used: {len(synthesis.get('sources_used', []))}")
        print(f"  ✓ Key findings: {len(synthesis.get('key_findings', []))}")
        print()
        print("  Answer:")
        answer = synthesis.get("answer", "")
        # Word wrap the answer for better terminal reading
        import textwrap
        print(textwrap.fill(answer, width=80, initial_indent="    ", subsequent_indent="    "))

    except Exception as e:
        print(f"  ✗ Synthesis failed: {e}")
        return

    # ═══════════════════════════════════════════════════════
    # FINAL OUTPUT
    # ═══════════════════════════════════════════════════════
    banner("WORKFLOW COMPLETE")

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

    # Save to examples/
    output_dir = os.path.join(os.path.dirname(__file__), "..", "examples", "real-run-gemini")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"full_response_{session_id}.json")
    
    with open(output_path, "w") as f:
        json.dump(full_response, f, indent=2, default=str)

    print(f"  ✓ Saved full JSON trace to: {output_path}")
    print()


if __name__ == "__main__":
    main()
