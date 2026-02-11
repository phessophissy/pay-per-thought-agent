"""
Pay-Per-Thought Agent — FastAPI Server
═══════════════════════════════════════

Exposes the autonomous research agent as an HTTP API.
Each research request flows through:
  1. Planning   → decompose query into metered steps
  2. Execution  → x402-gated sequential tool invocation
  3. Synthesis  → aggregate into structured JSON

Endpoints:
  POST /research          — Submit a research query
  GET  /research/{id}     — Get result by session ID
  GET  /health            — Health check
"""

import uuid
import time
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import anthropic
import httpx

from config import config

# ─── App Setup ────────────────────────────────────────────────

app = FastAPI(
    title="Pay-Per-Thought Agent",
    description="Autonomous research agent with x402 micropayment enforcement",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── In-Memory Store ─────────────────────────────────────────

sessions: dict[str, dict] = {}

# ─── Request / Response Models ────────────────────────────────


class ResearchRequest(BaseModel):
    query: str = Field(..., description="The research question to investigate")
    max_budget: float = Field(
        0.50, description="Maximum budget in USD", ge=0.01, le=100.0
    )


class StepSchema(BaseModel):
    id: str
    index: int
    description: str
    tool: str
    estimated_cost_usd: float


class PlanResponse(BaseModel):
    session_id: str
    steps: list[StepSchema]
    total_estimated_cost: float
    max_budget: float


class StepResultSchema(BaseModel):
    step_id: str
    index: int
    status: str
    tool: str
    output: Optional[dict | str | list] = None
    actual_cost_usd: float
    duration_ms: int
    payment_tx_hash: Optional[str] = None
    error: Optional[str] = None
    sources: list[str] = []
    timestamp: str


class SynthesisResultSchema(BaseModel):
    answer: str
    confidence: str
    key_findings: list[dict] = []
    assumptions: list[str] = []
    limitations: list[str] = []
    total_cost_usd: float
    steps_executed: int
    steps_total: int
    was_halted: bool


class AgentResponseSchema(BaseModel):
    status: str
    session_id: str
    query: str
    current_step: str
    estimated_remaining_budget: float
    plan: Optional[PlanResponse] = None
    actions: list[StepResultSchema] = []
    results: Optional[SynthesisResultSchema] = None
    sources: list[str] = []
    notes: str
    timestamp: str


# ─── Cost Table ───────────────────────────────────────────────

COST_MAP = {
    "anthropic": config.COST_ANTHROPIC,
    "tavily": config.COST_TAVILY,
    "blockchain_rpc": config.COST_BLOCKCHAIN_RPC,
    "reasoning": config.COST_REASONING,
}

PLANNING_SYSTEM = """You are a research planning engine. Decompose a research query into minimal atomic steps.

Each step must specify:
- description: what to do
- tool: "anthropic" | "tavily" | "blockchain_rpc"

Rules:
1. Minimize steps. 3-7 steps is ideal.
2. "tavily" for web factual data retrieval.
3. "blockchain_rpc" for on-chain data.
4. "anthropic" for reasoning/analysis.
5. Return ONLY valid JSON.

Output:
{"steps": [{"description": "...", "tool": "anthropic|tavily|blockchain_rpc"}]}"""


# ─── Core Pipeline ────────────────────────────────────────────


async def run_planning(query: str, max_budget: float) -> dict:
    """Phase 1: Generate execution plan via Claude."""
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=PLANNING_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f'Research query: "{query}"\n\nDecompose into atomic steps. Return JSON only.',
            }
        ],
    )

    text = response.content[0].text if response.content[0].type == "text" else ""
    raw_plan = _parse_json(text)

    steps = []
    total_cost = 0.0
    for i, raw in enumerate(raw_plan.get("steps", [])):
        tool = raw.get("tool", "anthropic")
        if tool not in COST_MAP:
            tool = "anthropic"
        cost = COST_MAP[tool]

        if total_cost + cost > max_budget:
            break

        total_cost += cost
        steps.append(
            {
                "id": f"step_{i}_{uuid.uuid4().hex[:8]}",
                "index": i,
                "description": raw.get("description", ""),
                "tool": tool,
                "estimated_cost_usd": cost,
            }
        )

    session_id = uuid.uuid4().hex
    plan = {
        "session_id": session_id,
        "query": query,
        "steps": steps,
        "step_count": len(steps),
        "total_estimated_cost": total_cost,
        "max_budget": max_budget,
        "created_at": datetime.utcnow().isoformat(),
    }
    return plan


async def authorize_x402(step: dict, session_id: str) -> dict:
    """Simulate x402 payment authorization for a step."""
    # In production: call X402PaymentGate.authorizePayment on-chain
    return {
        "step_id": step["id"],
        "amount_usd": step["estimated_cost_usd"],
        "authorized": True,
        "tx_hash": f"sim_{int(time.time())}_{step['id']}",
        "error": None,
    }


async def execute_step(step: dict, query: str, prior_results: list[dict]) -> dict:
    """Execute a single step using the appropriate tool."""
    start = time.time()
    tool = step["tool"]

    try:
        if tool in ("anthropic", "reasoning"):
            result = await _execute_anthropic(step, query, prior_results)
        elif tool == "tavily":
            result = await _execute_tavily(step)
        elif tool == "blockchain_rpc":
            result = await _execute_rpc(step)
        else:
            raise ValueError(f"Unknown tool: {tool}")

        duration_ms = int((time.time() - start) * 1000)
        return {
            "step_id": step["id"],
            "index": step["index"],
            "status": "completed",
            "tool": tool,
            "output": result["data"],
            "actual_cost_usd": step["estimated_cost_usd"],
            "duration_ms": duration_ms,
            "payment_tx_hash": f"sim_{step['id']}",
            "error": None,
            "sources": result.get("sources", []),
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "step_id": step["id"],
            "index": step["index"],
            "status": "failed",
            "tool": tool,
            "output": None,
            "actual_cost_usd": 0,
            "duration_ms": duration_ms,
            "payment_tx_hash": None,
            "error": str(e),
            "sources": [],
            "timestamp": datetime.utcnow().isoformat(),
        }


async def run_synthesis(
    query: str, step_results: list[dict], total_spent: float, was_halted: bool
) -> dict:
    """Phase 3: Synthesize results via Claude."""
    completed = [r for r in step_results if r["status"] == "completed"]
    evidence = "\n\n---\n\n".join(
        f"### Step {r['index']} ({r['tool']}):\n{r['output']}\nSources: {', '.join(r.get('sources', []))}"
        for r in completed
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system="""You are a research synthesis engine. Produce a comprehensive answer from step evidence.
Output ONLY valid JSON:
{
  "answer": "...",
  "confidence": "high|medium|low",
  "key_findings": [{"claim": "...", "evidence": "...", "source": "...", "confidence": "high|medium|low"}],
  "assumptions": ["..."],
  "limitations": ["..."]
}""",
        messages=[
            {
                "role": "user",
                "content": f'Query: "{query}"\n\n{"⚠️ PARTIAL RESULTS (budget halted)\n\n" if was_halted else ""}Evidence:\n\n{evidence}',
            }
        ],
    )

    text = response.content[0].text if response.content[0].type == "text" else ""
    synthesis = _parse_json(text)

    all_sources = []
    for r in completed:
        all_sources.extend(r.get("sources", []))

    return {
        "answer": synthesis.get("answer", text),
        "confidence": synthesis.get("confidence", "low"),
        "key_findings": synthesis.get("key_findings", []),
        "assumptions": synthesis.get("assumptions", []),
        "limitations": synthesis.get("limitations", []),
        "sources": list(set(all_sources)),
        "total_cost_usd": total_spent,
        "steps_executed": len(completed),
        "steps_total": len(step_results),
        "was_halted": was_halted,
    }


# ─── Tool Implementations ────────────────────────────────────


async def _execute_anthropic(
    step: dict, query: str, prior_results: list[dict]
) -> dict:
    context = "\n".join(
        f"[Step {r['index']}]: {r['output']}"
        for r in prior_results
        if r["status"] == "completed"
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system="You are a research analyst. Provide factual, concise answers. Respond with JSON: { \"analysis\": \"...\", \"confidence\": \"high|medium|low\", \"key_points\": [\"...\"] }",
        messages=[
            {
                "role": "user",
                "content": f'Query: "{query}"\nTask: {step["description"]}\n\n{f"Prior context:\n{context}" if context else "No prior context."}',
            }
        ],
    )

    text = response.content[0].text if response.content[0].type == "text" else ""
    data = _parse_json(text) or {"raw_text": text}
    return {"data": data, "sources": [f"anthropic:{config.ANTHROPIC_MODEL}"]}


async def _execute_tavily(step: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": config.TAVILY_API_KEY,
                "query": step["description"],
                "search_depth": "advanced",
                "max_results": 5,
                "include_answer": True,
                "include_raw_content": False,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

    sources = [r["url"] for r in data.get("results", [])]
    return {
        "data": {
            "answer": data.get("answer"),
            "results": [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": r.get("content"),
                    "score": r.get("score"),
                }
                for r in data.get("results", [])
            ],
        },
        "sources": sources,
    }


async def _execute_rpc(step: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            config.RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": [],
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

    if "error" in data:
        raise ValueError(f"RPC error: {data['error']}")

    return {
        "data": data.get("result"),
        "sources": [f"rpc:{config.RPC_URL}"],
    }


# ─── Endpoints ────────────────────────────────────────────────


@app.get("/health")
async def health():
    missing = config.validate()
    return {
        "status": "healthy" if not missing else "degraded",
        "missing_config": missing,
        "version": "1.0.0",
    }


@app.post("/research", response_model=AgentResponseSchema)
async def research(req: ResearchRequest):
    """
    Full research pipeline: plan → execute → synthesize.
    Returns structured JSON with all step results and final synthesis.
    """
    missing = config.validate()
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing configuration: {', '.join(missing)}",
        )

    session_id = None
    try:
        # ── Phase 1: Planning ──
        plan = await run_planning(req.query, req.max_budget)
        session_id = plan["session_id"]

        if not plan["steps"]:
            return AgentResponseSchema(
                status="error",
                session_id=session_id,
                query=req.query,
                current_step="planning",
                estimated_remaining_budget=req.max_budget,
                plan=None,
                actions=[],
                results=None,
                sources=[],
                notes="Planning produced no executable steps.",
                timestamp=datetime.utcnow().isoformat(),
            )

        # ── Phase 2: Metered Execution ──
        step_results: list[dict] = []
        total_spent = 0.0
        halted = False

        for step in plan["steps"]:
            # x402 payment gate
            payment = await authorize_x402(step, session_id)
            if not payment["authorized"]:
                step_results.append(
                    {
                        "step_id": step["id"],
                        "index": step["index"],
                        "status": "payment_denied",
                        "tool": step["tool"],
                        "output": None,
                        "actual_cost_usd": 0,
                        "duration_ms": 0,
                        "payment_tx_hash": None,
                        "error": payment.get("error", "x402 denied"),
                        "sources": [],
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                )
                halted = True
                break

            result = await execute_step(step, req.query, step_results)
            step_results.append(result)

            if result["status"] == "completed":
                total_spent += result["actual_cost_usd"]

        # ── Phase 3: Synthesis ──
        synthesis = await run_synthesis(
            req.query, step_results, total_spent, halted
        )

        # Store session
        response = AgentResponseSchema(
            status="halted" if halted else "completed",
            session_id=session_id,
            query=req.query,
            current_step="synthesis_complete" if not halted else f"halted_at_step_{len(step_results)}",
            estimated_remaining_budget=req.max_budget - total_spent,
            plan=PlanResponse(
                session_id=session_id,
                steps=[StepSchema(**s) for s in plan["steps"]],
                total_estimated_cost=plan["total_estimated_cost"],
                max_budget=plan["max_budget"],
            ),
            actions=[StepResultSchema(**r) for r in step_results],
            results=SynthesisResultSchema(**synthesis),
            sources=synthesis.get("sources", []),
            notes=f"{'Halted due to budget.' if halted else 'Completed.'} {len([r for r in step_results if r['status'] == 'completed'])} steps executed. Total cost: ${total_spent:.4f}",
            timestamp=datetime.utcnow().isoformat(),
        )

        sessions[session_id] = response.model_dump()
        return response

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "session_id": session_id or "unknown",
                "query": req.query,
                "current_step": "pipeline_error",
                "estimated_remaining_budget": req.max_budget,
                "actions": [],
                "results": None,
                "sources": [],
                "notes": f"Pipeline error: {str(e)}",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )


@app.get("/research/{session_id}")
async def get_research(session_id: str):
    """Retrieve a completed research result by session ID."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


# ─── Helpers ──────────────────────────────────────────────────


def _parse_json(text: str) -> dict:
    import json
    import re

    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_str = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"raw_text": text}


# ─── Run Server ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
