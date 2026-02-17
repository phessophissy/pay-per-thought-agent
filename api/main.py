"""
Pay-Per-Thought Agent — FastAPI Server
═══════════════════════════════════════

Production-ready HTTP API for the autonomous research agent.
Orchestrates the pipeline via Chainlink CRE (Simulation).

Endpoints:
  POST /research   — Submit a research query (triggers CRE simulation)
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
import json
import re
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Add project root to path so agent modules are importable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

try:
    from api.config import config
except ImportError:
    from config import config

# ─── App Setup ────────────────────────────────────────────────

app = FastAPI(
    title="Pay-Per-Thought Agent",
    description="Autonomous research agent orchestrated by Chainlink CRE",
    version="2.1.0",
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


# ─── Helpers ──────────────────────────────────────────────────

def _default_plan(session_id: str, max_budget: float) -> PlanResponse:
    return PlanResponse(
        session_id=session_id,
        steps=[
            StepSchema(
                id="step_1",
                index=1,
                description="Execute Tavily search",
                tool="tavily",
                estimated_cost_usd=0.01,
            ),
            StepSchema(
                id="step_2",
                index=2,
                description="Execute Gemini analysis",
                tool="gemini",
                estimated_cost_usd=0.005,
            ),
        ],
        total_estimated_cost=0.015,
        max_budget=max_budget,
    )


def _normalize_cre_result(data: Dict[str, Any], max_budget: float) -> Dict[str, Any]:
    total_cost = float(data.get("total_cost_usd", 0.0) or 0.0)
    if total_cost < 0:
        total_cost = 0.0
    total_cost = min(total_cost, max_budget)

    steps_executed = int(data.get("steps_executed", 0) or 0)
    steps_total = int(data.get("steps_total", 2) or 2)
    if steps_total < 0:
        steps_total = 0
    steps_executed = max(0, min(steps_executed, steps_total if steps_total else steps_executed))

    confidence = str(data.get("confidence", "low")).lower()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    key_findings = data.get("key_findings", [])
    if not isinstance(key_findings, list):
        key_findings = []
    assumptions = data.get("assumptions", [])
    if not isinstance(assumptions, list):
        assumptions = []
    limitations = data.get("limitations", [])
    if not isinstance(limitations, list):
        limitations = []
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        sources = []

    return {
        "answer": str(data.get("answer", "Workflow completed without a synthesized answer.")),
        "confidence": confidence,
        "key_findings": key_findings,
        "assumptions": assumptions,
        "limitations": limitations,
        "sources": sources,
        "total_cost_usd": total_cost,
        "steps_executed": steps_executed,
        "steps_total": steps_total,
        "was_halted": bool(data.get("was_halted", steps_executed < steps_total)),
    }


def _build_actions(results: Dict[str, Any], now_iso: str) -> list[StepResultSchema]:
    # Prefer step actions from runner output if present.
    raw_actions = results.get("actions")
    if isinstance(raw_actions, list):
        actions: list[StepResultSchema] = []
        for item in raw_actions:
            try:
                actions.append(StepResultSchema(**item))
            except Exception:
                continue
        if actions:
            return actions

    steps_executed = int(results.get("steps_executed", 0) or 0)
    if steps_executed <= 0:
        return [
            StepResultSchema(
                step_id="workflow",
                index=0,
                status="failed",
                tool="cre_workflow",
                actual_cost_usd=0.0,
                duration_ms=0,
                error="Workflow execution failed before completing any steps.",
                timestamp=now_iso,
            )
        ]

    actions: list[StepResultSchema] = [
        StepResultSchema(
            step_id="step_1",
            index=1,
            status="completed" if steps_executed >= 1 else "failed",
            tool="tavily",
            actual_cost_usd=0.01 if steps_executed >= 1 else 0.0,
            duration_ms=1000,
            timestamp=now_iso,
        )
    ]
    if steps_executed >= 2:
        actions.append(
            StepResultSchema(
                step_id="step_2",
                index=2,
                status="completed",
                tool="gemini",
                actual_cost_usd=0.005,
                duration_ms=1000,
                timestamp=now_iso,
            )
        )
    return actions


def _parse_cre_marker(stdout: str) -> Optional[Dict[str, Any]]:
    # Marker format expected from scripts/run_real_workflow.py
    matches = re.findall(r"__CRE_RESULT_JSON__:(\{.*\})", stdout)
    if not matches:
        return None
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return None


def _build_failure_response(
    *,
    session_id: str,
    query: str,
    max_budget: float,
    note: str,
) -> AgentResponseSchema:
    now_iso = datetime.now(timezone.utc).isoformat()
    results = SynthesisResultSchema(
        answer="Workflow execution failed before a complete answer was produced.",
        confidence="low",
        key_findings=[],
        assumptions=[],
        limitations=[note],
        total_cost_usd=0.0,
        steps_executed=0,
        steps_total=2,
        was_halted=True,
    )
    return AgentResponseSchema(
        status="halted",
        session_id=session_id,
        query=query,
        current_step="pipeline_error",
        estimated_remaining_budget=max_budget,
        plan=_default_plan(session_id, max_budget),
        actions=[
            StepResultSchema(
                step_id="workflow",
                index=0,
                status="failed",
                tool="cre_workflow",
                actual_cost_usd=0.0,
                duration_ms=0,
                error=note,
                timestamp=now_iso,
            )
        ],
        results=results,
        sources=[],
        notes=f"Pipeline error: {note}",
        timestamp=now_iso,
    )


# ─── Endpoints ────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check with configuration validation."""
    missing = config.validate()
    return {
        "status": "healthy" if not missing else "degraded",
        "missing_config": missing,
        "version": "2.1.0 (CRE Orchestration)",
        "endpoints": {
            "research": "POST /research",
            "get_result": "GET /research/{session_id}",
        },
    }


@app.post("/research", response_model=AgentResponseSchema)
async def research(req: ResearchRequest):
    """
    Triggers Chainlink CRE Simulation to run the fixed 3-step pipeline.
    """
    query = req.task
    max_budget = req.budget_float
    session_id = f"cre_sim_{int(time.time())}"
    now_iso = datetime.now(timezone.utc).isoformat()

    missing = config.validate()
    if missing:
        response = _build_failure_response(
            session_id=session_id,
            query=query,
            max_budget=max_budget,
            note=f"Missing configuration: {', '.join(missing)}",
        )
        sessions[session_id] = response.model_dump()
        return response
    # Invoke helper script for strict CRE execution.
    script_path = os.path.join(PROJECT_ROOT, "scripts", "run_real_workflow.py")
    cmd = [sys.executable, script_path, query, "--budget", str(max_budget)]

    try:
        print(f"Starting CRE Simulation: {cmd}")
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
        stdout = result.stdout
        stderr = result.stderr
        cre_data = _parse_cre_marker(stdout)
        if not cre_data:
            note = "CRE output parsing failed: missing or invalid __CRE_RESULT_JSON__ marker."
            if stderr:
                note = f"{note} stderr={stderr[-200:]}"
            response = _build_failure_response(
                session_id=session_id,
                query=query,
                max_budget=max_budget,
                note=note,
            )
            sessions[session_id] = response.model_dump()
            return response

        normalized = _normalize_cre_result(cre_data, max_budget)
        results_model = SynthesisResultSchema(
            answer=normalized["answer"],
            confidence=normalized["confidence"],
            key_findings=normalized["key_findings"],
            assumptions=normalized["assumptions"],
            limitations=normalized["limitations"],
            total_cost_usd=normalized["total_cost_usd"],
            steps_executed=normalized["steps_executed"],
            steps_total=normalized["steps_total"],
            was_halted=normalized["was_halted"],
        )
        actions = _build_actions(normalized, now_iso)

        status = "completed"
        if result.returncode != 0 or normalized["was_halted"]:
            status = "halted"

        response = AgentResponseSchema(
            status=status,
            session_id=session_id,
            query=query,
            current_step="completed" if status == "completed" else "halted",
            estimated_remaining_budget=max(
                0.0, round(max_budget - normalized["total_cost_usd"], 6)
            ),
            plan=_default_plan(session_id, max_budget),
            actions=actions,
            results=results_model,
            sources=normalized.get("sources", []),
            notes="Executed via Chainlink CRE Simulation."
            if result.returncode == 0
            else f"Workflow execution failed: {stderr[-200:]}",
            timestamp=now_iso,
        )
        sessions[session_id] = response.model_dump()
        return response
    except subprocess.TimeoutExpired:
        response = _build_failure_response(
            session_id=session_id,
            query=query,
            max_budget=max_budget,
            note="CRE workflow timeout after 180 seconds.",
        )
        sessions[session_id] = response.model_dump()
        return response
    except Exception as e:
        response = _build_failure_response(
            session_id=session_id,
            query=query,
            max_budget=max_budget,
            note=str(e),
        )
        sessions[session_id] = response.model_dump()
        return response


# ─── CRE SYNTHESIS ENDPOINT ──────────────────────────────────────

class SynthesisRequest(BaseModel):
    query: str
    tavily_result: Optional[Dict[str, Any]] = None
    gemini_result: Optional[Dict[str, Any]] = None
    total_spent_usd: float = 0.0

@app.post("/api/synthesize")
async def synthesize_for_cre(req: SynthesisRequest):
    """
    Endpoint called by CRE 'synthesis_node' (type: http).
    Aggregates results and returns final JSON.
    """
    print(f"Start synthesis for query: {req.query}")
    
    # Reconstruct step results format expected by synthesizer
    step_results = []
    if req.tavily_result:
        step_results.append({"index": 1, "tool": "tavily", **req.tavily_result})
    if req.gemini_result:
        step_results.append({"index": 2, "tool": "gemini", **req.gemini_result})
        
    try:
        from agent import synthesizer
        result = synthesizer.synthesize_results(
            query=req.query,
            step_results=step_results,
            total_spent_usd=req.total_spent_usd,
            was_halted=False
        )
        return result
    except Exception as e:
        print(f"Synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/research/{session_id}")
async def get_research(session_id: str):
    """Retrieve a completed research result by session ID."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
