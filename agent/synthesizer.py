"""
Pay-Per-Thought Agent — Synthesis Module
═════════════════════════════════════════

Phase 3: Aggregate verified step results into a final structured output.

Uses Gemini to synthesize evidence from completed steps into a
coherent answer with confidence scoring, source attribution,
and explicit labeling of assumptions and limitations.

Entry points:
  - synthesize_results(query, step_results, total_spent_usd, was_halted)
  - handle_halt(error_source, error_message, plan, partial_results, total_spent)
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

from google import genai
from google.genai import types

# ─── System Prompt ────────────────────────────────────────────

SYNTHESIS_SYSTEM = """You are a research synthesis engine. Produce a comprehensive,
factual answer from the step-level evidence provided.

Rules:
1. Only use information from the provided evidence. Do NOT hallucinate.
2. Clearly attribute claims to their sources.
3. If evidence is conflicting, note the discrepancy.
4. If evidence is insufficient, say so explicitly.
5. Return ONLY valid JSON. No markdown, no explanation.

Output format:
{
  "answer": "comprehensive answer to the research query",
  "confidence": "high|medium|low",
  "key_findings": [
    {
      "claim": "specific factual claim",
      "evidence": "supporting evidence from steps",
      "source": "source attribution",
      "confidence": "high|medium|low"
    }
  ],
  "assumptions": ["any assumptions made"],
  "limitations": ["limitations of this analysis"]
}"""


def synthesize_results(
    query: str,
    step_results: list[dict],
    total_spent_usd: float,
    was_halted: bool,
) -> dict:
    """
    Synthesize step results into a final structured research output.

    Args:
        query: Original research question.
        step_results: List of step result dicts from executor.
        total_spent_usd: Total amount spent.
        was_halted: Whether execution was halted early.

    Returns:
        Structured synthesis result dict.
    """
    completed = [r for r in step_results if r["status"] == "completed"]

    if not completed:
        return {
            "answer": "No steps completed successfully. Unable to provide an answer.",
            "confidence": "low",
            "key_findings": [],
            "assumptions": [],
            "limitations": ["No execution steps completed."],
            "sources": [],
            "total_cost_usd": total_spent_usd,
            "steps_executed": 0,
            "steps_total": len(step_results),
            "was_halted": was_halted,
        }

    # ── Build evidence document from step outputs ──
    evidence_parts = []
    all_sources = []

    for r in completed:
        output_str = json.dumps(r["output"], default=str) if r["output"] else "No output"
        sources_str = ", ".join(r.get("sources", []))
        evidence_parts.append(
            f"### Step {r['index']} ({r['tool']}):\n"
            f"{output_str}\n"
            f"Sources: {sources_str}"
        )
        all_sources.extend(r.get("sources", []))

    evidence = "\n\n---\n\n".join(evidence_parts)

    # ── Call Gemini for synthesis ──
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")

    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    
    client = genai.Client(api_key=api_key)

    halted_warning = "⚠️ PARTIAL RESULTS — Execution was halted before all steps completed.\n\n" if was_halted else ""

    prompt = (
        f'Research query: "{query}"\n\n'
        f"{halted_warning}"
        f"Evidence from {len(completed)} completed steps:\n\n"
        f"{evidence}"
    )

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYNTHESIS_SYSTEM
        )
    )
    
    text = response.text
    synthesis = _parse_json(text)

    return {
        "answer": synthesis.get("answer", text),
        "confidence": synthesis.get("confidence", "low"),
        "key_findings": synthesis.get("key_findings", []),
        "assumptions": synthesis.get("assumptions", []),
        "limitations": synthesis.get("limitations", []),
        "sources": list(set(all_sources)),
        "total_cost_usd": total_spent_usd,
        "steps_executed": len(completed),
        "steps_total": len(step_results),
        "was_halted": was_halted,
    }


def handle_halt(
    error_source: Optional[str] = None,
    error_message: Optional[str] = None,
    plan: Optional[dict] = None,
    partial_results: Optional[list[dict]] = None,
    total_spent: float = 0.0,
) -> dict:
    """
    Handle workflow halt/failure. Called by the CRE halt_node.

    Attempts to produce a partial result from whatever data is available,
    and flags the error source for debugging.

    Args:
        error_source: Node ID that caused the error.
        error_message: Error description.
        plan: The execution plan (may be None if planning failed).
        partial_results: Any step results collected before failure.
        total_spent: Amount spent before halt.

    Returns:
        Halt result dict with partial answer and error context.
    """
    partial_results = partial_results or []
    completed = [r for r in partial_results if r.get("status") == "completed"]

    partial_answer = "Execution halted before any results were produced."
    if completed:
        # Try to provide a minimal summary
        summaries = []
        for r in completed:
            output = r.get("output")
            if isinstance(output, dict):
                text = output.get("analysis", output.get("answer", json.dumps(output, default=str)))
            else:
                text = str(output)
            summaries.append(f"Step {r['index']} ({r['tool']}): {text[:200]}")

        partial_answer = (
            f"Partial results from {len(completed)} completed steps:\n"
            + "\n".join(summaries)
        )

    return {
        "status": "halted",
        "error_source": error_source or "unknown",
        "error_message": error_message or "Unknown error",
        "partial_answer": partial_answer,
        "total_spent_usd": total_spent,
        "steps_completed": len(completed),
        "steps_total": len(partial_results),
        "refund_attempted": True,
    }

# ─── Helpers ──────────────────────────────────────────────────

def _parse_json(text: str) -> dict:
    """Extract JSON from LLM output."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    json_str = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"raw_text": text}
