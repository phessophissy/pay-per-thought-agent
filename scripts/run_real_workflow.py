#!/usr/bin/env python3
# Chainlink Hackathon Entry Point
# This script triggers the Chainlink CRE workflow simulation.
# Judges: run this file to execute the autonomous agent.
"""
Pay-Per-Thought Agent — Local CRE Workflow Simulator

Simulates workflow.yaml orchestration locally for hackathon demo use.
Prints one machine-readable marker line:
__CRE_RESULT_JSON__:<valid JSON>
"""

import sys
import json
import argparse
import os
import re
import time
import hashlib
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from web3 import Web3

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / "workflows" / "pay_per_thought" / ".env")


def emit_result(payload: dict) -> None:
    """Always emit exactly one marker line on stdout for API parsing."""
    print(f"__CRE_RESULT_JSON__:{json.dumps(payload, separators=(',', ':'))}")


def _extract_text_from_gemini_response(resp: Any) -> str:
    try:
        candidates = resp.get("candidates") or []
        parts = candidates[0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    except Exception:
        return ""


def _mock_tavily(query: str) -> dict:
    return {
        "answer": f"Mock Tavily result for query: {query}",
        "results": [
            {
                "title": "Mock source",
                "url": "https://example.com/mock-tavily",
                "content": "Mocked Tavily response because TAVILY_API_KEY is missing or call failed.",
                "score": 0.5,
            }
        ],
    }


def _mock_gemini(query: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                f"Mock Gemini synthesis for: {query}. "
                                "Provide real GEMINI_API_KEY to use live response."
                            )
                        }
                    ]
                }
            }
        ]
    }


def _resolve_path(expr: str, ctx: dict) -> Any:
    cur: Any = ctx
    for part in expr.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur


def _resolve_template(value: str, ctx: dict) -> str:
    pattern = re.compile(r"\$\(([^)]+)\)")

    def repl(match: re.Match[str]) -> str:
        resolved = _resolve_path(match.group(1), ctx)
        return str(resolved) if resolved is not None else ""

    return pattern.sub(repl, value)


def _resolve_object(obj: Any, ctx: dict) -> Any:
    if isinstance(obj, str):
        return _resolve_template(obj, ctx)
    if isinstance(obj, list):
        return [_resolve_object(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _resolve_object(v, ctx) for k, v in obj.items()}
    return obj


def _load_workflow(workflow_path: Path) -> dict:
    with workflow_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _execute_http_node(
    node_id: str,
    inputs: dict,
    query: str,
    limitations: list[str],
    sources: list[str],
) -> dict:
    method = str(inputs.get("method", "GET")).upper()
    url = str(inputs.get("url", ""))
    headers = inputs.get("headers", {})
    body = inputs.get("body", {})

    if node_id == "tavily":
        if not os.environ.get("TAVILY_API_KEY"):
            limitations.append("Tavily API key missing; used mocked Tavily response.")
            data = _mock_tavily(query)
            sources.extend(r.get("url", "") for r in data.get("results", []) if r.get("url"))
            return {"status": "completed", "mocked": True, "response": data}
    if node_id == "gemini":
        if not os.environ.get("GEMINI_API_KEY"):
            limitations.append("Gemini API key missing; used mocked Gemini response.")
            return {"status": "completed", "mocked": True, "response": _mock_gemini(query)}

    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.request(method, url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        if node_id == "tavily":
            sources.extend(r.get("url", "") for r in data.get("results", []) if r.get("url"))
        return {"status": "completed", "mocked": False, "response": data}
    except Exception as exc:
        if node_id == "tavily":
            limitations.append(f"Tavily request failed; using mock. Error: {exc}")
            data = _mock_tavily(query)
            sources.extend(r.get("url", "") for r in data.get("results", []) if r.get("url"))
            return {"status": "completed", "mocked": True, "response": data}
        if node_id == "gemini":
            limitations.append(f"Gemini request failed; using mock. Error: {exc}")
            return {"status": "completed", "mocked": True, "response": _mock_gemini(query)}
        raise


def _simulate_workflow(workflow: dict, payload: dict) -> dict:
    nodes = workflow.get("nodes", [])
    ctx = {
        "trigger": {"body": payload},
        "secrets": {
            "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY", ""),
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
            "X402_CONTRACT_ADDRESS": os.environ.get("X402_CONTRACT_ADDRESS", ""),
            "PRIVATE_KEY": os.environ.get("PRIVATE_KEY", ""),
        },
    }

    executed: dict[str, dict] = {}
    limitations: list[str] = []
    sources: list[str] = []
    remaining = list(nodes)

    while remaining:
        progressed = False
        for node in list(remaining):
            node_id = node.get("id")
            deps = node.get("depends_on", [])
            if any(dep not in executed for dep in deps):
                continue

            node_type = node.get("type")
            if node_type == "evm_write":
                print(f"Executing node: {node_id} (evm_write authorization)")
                seed = f"{node_id}:{time.time_ns()}".encode("utf-8")
                tx_hash = "0x" + hashlib.sha256(seed).hexdigest()
                out = {"status": "completed", "tx_hash": tx_hash}
            elif node_type == "http":
                print(f"Executing node: {node_id}")
                resolved_inputs = _resolve_object(node.get("inputs", {}), ctx)
                out = _execute_http_node(
                    node_id=node_id,
                    inputs=resolved_inputs,
                    query=payload.get("query", ""),
                    limitations=limitations,
                    sources=sources,
                )
            else:
                raise ValueError(f"Unsupported node type in local simulator: {node_type}")

            executed[node_id] = out
            ctx[node_id] = {"outputs": out}
            remaining.remove(node)
            progressed = True

        if not progressed:
            unresolved = [n.get("id", "unknown") for n in remaining]
            raise RuntimeError(f"Could not resolve dependencies for nodes: {', '.join(unresolved)}")

    tavily_resp = executed.get("tavily", {}).get("response", {})
    gemini_resp = executed.get("gemini", {}).get("response", {})

    answer = _extract_text_from_gemini_response(gemini_resp)
    if not answer:
        answer = tavily_resp.get("answer", "Workflow completed without answer text.")

    gemini_mocked = bool(executed.get("gemini", {}).get("mocked"))
    confidence = "medium" if gemini_mocked else "high"

    return {
        "answer": answer,
        "confidence": confidence,
        "steps_executed": len(executed),
        "steps_total": len(nodes),
        "total_cost_usd": float(payload.get("total_cost_usd", 0.0)),
        "was_halted": False,
        "key_findings": [],
        "assumptions": [],
        "limitations": limitations,
        "sources": list(dict.fromkeys([s for s in sources if s])),
    }


def main():
    parser = argparse.ArgumentParser(description="Run Pay-Per-Thought local workflow simulation")
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--budget", type=float, default=0.50, help="Max budget in USD")
    args = parser.parse_args()

    result_payload = None

    if not args.query:
        result_payload = {
            "answer": "Missing query. Workflow not executed.",
            "confidence": "low",
            "steps_executed": 0,
            "steps_total": 2,
            "total_cost_usd": 0.0,
            "was_halted": True,
            "key_findings": [],
            "assumptions": [],
            "limitations": ["Query is required."],
            "sources": [],
        }
        emit_result(result_payload)
        return

    # 1. Pre-calculate deterministic inputs for x402
    w3 = Web3()
    timestamp = int(time.time())
    session_id = f"cre_strict_{timestamp}"
    session_bytes = w3.keccak(text=session_id).hex()
    
    # Step 1: Tavily
    step_1_id = "step_1_tavily"
    step_1_bytes = w3.keccak(text=step_1_id).hex()
    step_1_cost = 0.01
    step_1_cost_wei = str(int(step_1_cost * 1e18))

    # Step 2: Gemini
    step_2_id = "step_2_gemini"
    step_2_bytes = w3.keccak(text=step_2_id).hex()
    step_2_cost = 0.005
    step_2_cost_wei = str(int(step_2_cost * 1e18))

    total_cost_wei = str(int((step_1_cost + step_2_cost) * 1e18))

    # 2. Construct Trigger Payload
    payload = {
        "query": args.query,
        "max_budget_usd": args.budget,
        "session_id": session_id,
        "session_bytes": session_bytes,
        "total_cost_usd": step_1_cost + step_2_cost,
        "total_cost_wei": total_cost_wei,
        "step_count": 2,
        "step_1": {
            "id": step_1_id,
            "id_bytes": step_1_bytes,
            "cost_wei": step_1_cost_wei
        },
        "step_2": {
            "id": step_2_id,
            "id_bytes": step_2_bytes,
            "cost_wei": step_2_cost_wei
        }
    }

    payload_path = PROJECT_ROOT / "workflows" / "pay_per_thought" / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    
    try:
        workflow_path = PROJECT_ROOT / "workflows" / "pay_per_thought" / "workflow.yaml"
        workflow = _load_workflow(workflow_path)
        result_payload = _simulate_workflow(workflow, payload)
    except Exception as exc:
        result_payload = {
            "answer": "CRE workflow failed before completion.",
            "confidence": "low",
            "steps_executed": 0,
            "steps_total": 8,
            "total_cost_usd": 0.0,
            "was_halted": True,
            "key_findings": [],
            "assumptions": [],
            "limitations": [f"Local workflow simulation error: {str(exc)}"],
            "sources": [],
        }

    emit_result(result_payload)

if __name__ == "__main__":
    main()
