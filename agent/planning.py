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
    force_steps_count: Optional[int] = None,
) -> dict:
    """
    Generate an execution plan for a research query.

    Args:
        query: The research question to investigate.
        max_budget_usd: Maximum budget in USD.
        session_id: Optional session ID (auto-generated if omitted).
        force_steps_count: If set, forces the planner to generate exactly this many steps.

    Returns:
        ExecutionPlan dict with steps, costs, and session metadata.
    """
    if not session_id:
        session_id = uuid.uuid4().hex

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    
    # Initialize new client
    client = genai.Client(api_key=api_key)

    # ── Call Gemini for plan decomposition ──
    if force_steps_count:
        step_instruction = f"Decompose into exactly {force_steps_count} atomic steps."
    else:
        step_instruction = "Decompose into atomic steps."

    prompt = (
        f'Research query: "{query}"\n\n'
        f"Budget: ${max_budget_usd:.2f}\n\n"
        f"{step_instruction} Return JSON only."
    )
    
    # Adjust system prompt if forcing steps
    system_prompt = PLANNING_SYSTEM
    if force_steps_count:
        system_prompt = system_prompt.replace(
            "1. Use 3-7 steps total. Minimize steps to reduce cost.",
            f"1. You MUST generate EXACTLY {force_steps_count} steps."
        )

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt
        )
    )
    
    text = response.text
    raw_plan = _parse_json(text)

    # ── Build steps with cost enforcement ──
    steps = []
    total_cost = 0.0

    raw_steps = raw_plan.get("steps", [])
    
    # If generic failure to get right count, pad or truncate (though prompt should handle it)
    if force_steps_count:
        # Pad if too few
        while len(raw_steps) < force_steps_count:
            raw_steps.append({
                "description": "Analyze previous findings",
                "tool": "gemini"
            })
        # Truncate if too many
        raw_steps = raw_steps[:force_steps_count]

    for i, raw_step in enumerate(raw_steps):
        tool = raw_step.get("tool", "gemini")
        if tool not in VALID_TOOLS:
            tool = "gemini"

        cost = COST_TABLE[tool]

        # Budget guard: halt planning when the next step exceeds budget.
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
