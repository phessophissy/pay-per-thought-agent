"""
Chainlink CRE Adapter for Pay-Per-Thought Agent
Specially designed to expose atomic functions for the fixed CRE workflow.
"""

import os
import time
import json
from datetime import datetime, timezone
from web3 import Web3
from agent import executor, synthesizer, planning

def setup_workflow(query: str, max_budget_usd: float) -> dict:
    """
    Prepare all necessary data for the workflow nodes.
    - Generates Session ID
    - Calculates hashes for x402 (session_id, step_ids)
    - Estimates costs for fixed steps
    """
    timestamp = int(time.time())
    session_id = f"cre_run_{timestamp}"
    
    # ─── Dynamic Planning with Fixed Structure ───
    # We force the planner to generate exactly 2 steps to match the workflow.yaml
    plan = planning.generate_plan(
        query=query,
        max_budget_usd=max_budget_usd,
        session_id=session_id,
        force_steps_count=2
    )
    
    steps = plan["steps"]
    total_cost = plan["total_estimated_cost"]
    
    w3 = Web3()
    
    # Pre-calculate hashes/bytes for EVM writes
    session_bytes = w3.keccak(text=session_id).hex()
    
    step_data = {}
    for i, s in enumerate(steps):
        s_id = s["id"]
        s_bytes = w3.keccak(text=s_id).hex()
        s_cost_wei = int(s["estimated_cost_usd"] * 1e18)
        step_data[f"step_{i+1}_id"] = s_id
        step_data[f"step_{i+1}_bytes"] = s_bytes
        step_data[f"step_{i+1}_cost_wei"] = str(s_cost_wei) # JSON implies string for big ints 
        step_data[f"step_{i+1}_description"] = s["description"]
        step_data[f"step_{i+1}_tool"] = s["tool"]

    return {
        "session_id": session_id,
        "session_bytes": session_bytes,
        "total_cost_usd": total_cost,
        "total_cost_wei": str(int(total_cost * 1e18)),
        "step_count": len(steps),
        **step_data
    }

def execute_step_adapter(step_tool: str, step_description: str, prior_result: dict = None) -> dict:
    """
    Generic adapter to execute a step based on the tool decided by the planner.
    This replaces the specific execute_tavily/execute_gemini adapters.
    """
    
    # Construct prior results context if it exists
    prior_results = []
    if prior_result and prior_result.get("status") == "completed":
        # We assume the prior result came from index 1 (generic assumption for 2-step flow)
        prior_results.append({
            "index": 1,
            "tool": prior_result.get("tool", "unknown"), # Pass tool if available, else unknown
            "status": "completed",
            "output": prior_result.get("output")
        })
        
    step_mock = {
        "description": step_description,
        "tool": step_tool
    }

    try:
        executor_fn = executor._get_tool_executor(step_tool)
        if not executor_fn:
            return {"status": "failed", "error": f"Unknown tool: {step_tool}"}
            
        if step_tool == "gemini":
            # Need query? The adapter signature didn't have it passed in explicitly in workflow originally
            # But execute_gemini needs 'query'.
            # We must pass 'query' in from workflow inputs if possible.
            # Wait, `execute_gemini` signature is `(step, query, prior_results)`.
            # I need `query` in this function.
            # I will update the function signature.
            raise ValueError("Missing query for Gemini tool — workflow must pass it.")
            
        elif step_tool == "tavily":
            result = executor_fn(step_mock)
        elif step_tool == "blockchain_rpc":
             result = executor_fn(step_mock)
        else:
            return {"status": "failed", "error": f"Tool {step_tool} not supported in adapter"}

        return {
            "status": "completed",
            "tool": step_tool,
            "output": result["data"],
            "sources": result.get("sources", [])
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}

def execute_step_with_query_adapter(query: str, step_tool: str, step_description: str, prior_result: dict = None) -> dict:
    """
    Generic adapter with Query - used for all steps to be safe.
    """
    
    # Construct prior results context if it exists
    prior_results = []
    if prior_result and prior_result.get("status") == "completed":
        prior_results.append({
            "index": 1,
            "tool": prior_result.get("tool", "unknown"),
            "status": "completed",
            "output": prior_result.get("output")
        })
        
    step_mock = {
        "description": step_description,
        "tool": step_tool,
        "index": 1 if not prior_result else 2 # Guess index based on prior result existence
    }

    try:
        executor_fn = executor._get_tool_executor(step_tool)
        if not executor_fn:
            return {"status": "failed", "error": f"Unknown tool: {step_tool}"}
            
        if step_tool == "gemini":
            result = executor_fn(step_mock, query, prior_results)
        elif step_tool == "tavily":
            result = executor_fn(step_mock)
        elif step_tool == "blockchain_rpc":
             result = executor_fn(step_mock)
        else:
            return {"status": "failed", "error": f"Tool {step_tool} not supported in adapter"}

        return {
            "status": "completed",
            "tool": step_tool,
            "output": result["data"],
            "sources": result.get("sources", [])
        }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def synthesize_adapter(query: str, step_1_result: dict, step_2_result: dict, total_cost: float) -> dict:
    """Adapter for Synthesis"""
    step_results = []
    if step_1_result: 
        step_results.append({"index": 1, **step_1_result})
    if step_2_result: 
        step_results.append({"index": 2, **step_2_result})
    
    # If generic execution, we might not have hardcoded 'tavily'/'gemini' keys anymore
    # but the generic adapter returns 'tool' in the result dict, effectively fixing it.
    
    result = synthesizer.synthesize_results(
        query=query,
        step_results=step_results,
        total_spent_usd=total_cost,
        was_halted=False
    )
    
    # ─── CHAINLINK HACKATHON OUTPUT ─────────────────────────────
    print(f"__CRE_RESULT_JSON__:{json.dumps(result)}")
    # ────────────────────────────────────────────────────────────
    
    return result
