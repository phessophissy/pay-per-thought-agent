"""
Pay-Per-Thought Agent — Planning Module
═══════════════════════════════════════

Phase 1: Decompose a research query into atomic, metered execution steps.

Each step specifies:
  - tool to invoke (gemini | tavily | blockchain_rpc)
  - description of what the step does
  - estimated cost in USD

The planner uses Gemini to reason about optimal decomposition,
then truncates the plan to fit within the user's max budget.

Entry point: generate_plan(query, max_budget_usd, session_id?)
"""

import json
import re
import uuid
import os
from datetime import datetime, timezone
from typing import Optional

from google import genai
from google.genai import types

# ─── Cost Table ───────────────────────────────────────────────
# Per-invocation cost estimates for each tool.

COST_TABLE = {
    "gemini": 0.005,         # ~$0.005 per Gemini Flash call
    "tavily": 0.01,          # ~$0.01 per Tavily search
    "blockchain_rpc": 0.001, # ~$0.001 per RPC call
}

VALID_TOOLS = set(COST_TABLE.keys())

# ─── System Prompt ────────────────────────────────────────────
PLANNING_SYSTEM = """You are a research planning engine. Your job is to decompose
a research query into the minimum number of atomic steps required to produce
a factual, verifiable answer.

Each step must specify:
  - "description": what this step does (one sentence)
  - "tool": exactly one of "gemini", "tavily", or "blockchain_rpc"

Rules:
1. Use 3-7 steps total. Minimize steps to reduce cost.
2. Use "tavily" for web-based factual data retrieval.
3. Use "blockchain_rpc" for on-chain data (balances, block numbers, contract state).
4. Use "gemini" for reasoning, analysis, or synthesis of prior step outputs.
5. Order steps logically — data retrieval before analysis.
6. Do NOT hallucinate data. Each step must produce real, verifiable output.
7. Return ONLY valid JSON. No markdown, no explanation, no code blocks.

Output format:
{"steps": [{"description": "...", "tool": "gemini|tavily|blockchain_rpc"}]}"""


def generate_plan(
    query: str,
    max_budget_usd: float,
    session_id: Optional[str] = None,
) -> dict:
    """
    Generate an execution plan for a research query.

    Args:
        query: The research question to investigate.
        max_budget_usd: Maximum budget in USD.
        session_id: Optional session ID (auto-generated if omitted).

    Returns:
        ExecutionPlan dict with steps, costs, and session metadata.
    """
    if not session_id:
        session_id = uuid.uuid4().hex

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
    
    # Initialize new client
    client = genai.Client(api_key=api_key)

    # ── Call Gemini for plan decomposition ──
    prompt = (
        f'Research query: "{query}"\n\n'
        f"Budget: ${max_budget_usd:.2f}\n\n"
        "Decompose into atomic steps. Return JSON only."
    )
    
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=PLANNING_SYSTEM
        )
    )
    
    text = response.text
    raw_plan = _parse_json(text)

    # ── Build steps with cost enforcement ──
    steps = []
    total_cost = 0.0

    for i, raw_step in enumerate(raw_plan.get("steps", [])):
        tool = raw_step.get("tool", "gemini")
        if tool not in VALID_TOOLS:
            tool = "gemini"

        cost = COST_TABLE[tool]

        # Budget guard: stop adding steps if budget would be exceeded
        if total_cost + cost > max_budget_usd:
            break

        total_cost += cost
        steps.append({
            "id": f"step_{i}_{uuid.uuid4().hex[:8]}",
            "index": i,
            "description": raw_step.get("description", f"Step {i}"),
            "tool": tool,
            "estimated_cost_usd": cost,
        })

    plan = {
        "session_id": session_id,
        "query": query,
        "steps": steps,
        "step_count": len(steps),
        "total_estimated_cost": round(total_cost, 6),
        "max_budget_usd": max_budget_usd,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return plan


def _parse_json(text: str) -> dict:
    """Extract JSON from LLM output, handling markdown code blocks."""
    # Try extracting from code block first
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_str = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"steps": []}
