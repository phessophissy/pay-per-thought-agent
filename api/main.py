"""
Pay-Per-Thought Agent — FastAPI Server
═══════════════════════════════════════

Production-ready HTTP API for the autonomous research agent.
Orchestrates the 3-phase pipeline via the agent/ modules.

Endpoints:
  POST /research   — Submit a research query
  GET  /research/{id} — Get result by session ID
  GET  /health     — Health check

Input:
  {
    "task": "research question here",
    "max_budget": "0.50"
  }

Output:
  Full AgentResponse JSON schema.
"""

import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Add project root to path so agent modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.planning import generate_plan
from agent.executor import execute_plan
from agent.synthesizer import synthesize_results

from config import config

# ─── App Setup ────────────────────────────────────────────────

app = FastAPI(
    title="Pay-Per-Thought Agent",
    description="Autonomous research agent with x402 micropayment enforcement",
    version="2.0.0",
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
    task: str = Field(..., description="The research question to investigate")
    max_budget: str = Field(
        "0.50", description="Maximum budget in USD (as string)"
    )

    @property
    def budget_float(self) -> float:
        try:
            val = float(self.max_budget)
            return max(0.01, min(val, 100.0))
        except ValueError:
            return 0.50


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


# ─── Endpoints ────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check with configuration validation."""
    missing = config.validate()
    return {
        "status": "healthy" if not missing else "degraded",
        "missing_config": missing,
        "version": "2.0.0",
        "endpoints": {
            "research": "POST /research",
            "get_result": "GET /research/{session_id}",
        },
    }


@app.post("/research", response_model=AgentResponseSchema)
async def research(req: ResearchRequest):
    """
    Full research pipeline: plan → execute (x402-gated) → synthesize.

    Input:
      {
        "task": "What is the current TVL of Aave v3 on Ethereum?",
        "max_budget": "0.50"
      }

    Output:
      Full AgentResponse JSON with plan, step results, synthesis, and cost breakdown.
    """
    missing = config.validate()
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing configuration: {', '.join(missing)}",
        )

    query = req.task
    max_budget = req.budget_float
    session_id = None

    try:
        # ── Phase 1: Planning ──
        plan = generate_plan(query, max_budget)
        session_id = plan["session_id"]

        if not plan["steps"]:
            return AgentResponseSchema(
                status="error",
                session_id=session_id,
                query=query,
                current_step="planning",
                estimated_remaining_budget=max_budget,
                plan=None,
                actions=[],
                results=None,
                sources=[],
                notes="Planning produced no executable steps within budget.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # ── Phase 2: Metered Execution ──
        exec_result = execute_plan(plan)

        step_results = exec_result["step_results"]
        total_spent = exec_result["total_spent_usd"]
        was_halted = exec_result["was_halted"]

        # ── Phase 3: Synthesis ──
        synthesis = synthesize_results(
            query, step_results, total_spent, was_halted
        )

        # Build response
        response = AgentResponseSchema(
            status="halted" if was_halted else "completed",
            session_id=session_id,
            query=query,
            current_step="synthesis_complete" if not was_halted else f"halted_at_step_{len(step_results)}",
            estimated_remaining_budget=max_budget - total_spent,
            plan=PlanResponse(
                session_id=session_id,
                steps=[StepSchema(**s) for s in plan["steps"]],
                total_estimated_cost=plan["total_estimated_cost"],
                max_budget=max_budget,
            ),
            actions=[StepResultSchema(**r) for r in step_results],
            results=SynthesisResultSchema(**synthesis),
            sources=synthesis.get("sources", []),
            notes=(
                f"{'Halted due to budget.' if was_halted else 'Completed.'} "
                f"{len([r for r in step_results if r['status'] == 'completed'])} steps executed. "
                f"Total cost: ${total_spent:.4f}"
            ),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        sessions[session_id] = response.model_dump()
        return response

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "session_id": session_id or "unknown",
                "query": query,
                "current_step": "pipeline_error",
                "estimated_remaining_budget": max_budget,
                "actions": [],
                "results": None,
                "sources": [],
                "notes": f"Pipeline error: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )


@app.get("/research/{session_id}")
async def get_research(session_id: str):
    """Retrieve a completed research result by session ID."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


# ─── Run Server ───────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
