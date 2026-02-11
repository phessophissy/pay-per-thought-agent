"""
Integration test for the Pay-Per-Thought Agent pipeline.

Tests the full 3-phase flow:
  1. Planning  — generate execution plan
  2. Execution — execute steps with simulated x402
  3. Synthesis — aggregate results

Run:
  pytest tests/test_agent_pipeline.py -v

Requirements:
  - ANTHROPIC_API_KEY must be set for live tests
  - Or run with mocks (default for CI)
"""

import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.planning import generate_plan, COST_TABLE
from agent.executor import execute_plan
from agent.synthesizer import synthesize_results, handle_halt


# ─── Mock Fixtures ────────────────────────────────────────────


def mock_anthropic_response(text: str):
    """Create a mock Anthropic API response."""
    mock = MagicMock()
    content_block = MagicMock()
    content_block.type = "text"
    content_block.text = text
    mock.content = [content_block]
    return mock


# ─── Planning Tests ───────────────────────────────────────────


class TestPlanning:
    """Test the planning module."""

    @patch("agent.planning.anthropic.Anthropic")
    def test_generate_plan_basic(self, mock_client_class):
        """Plan generation produces valid structure."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create.return_value = mock_anthropic_response(
            json.dumps({
                "steps": [
                    {"description": "Search for current Aave TVL", "tool": "tavily"},
                    {"description": "Analyze TVL data", "tool": "anthropic"},
                ]
            })
        )

        plan = generate_plan("What is Aave TVL?", max_budget_usd=0.50)

        assert "session_id" in plan
        assert "steps" in plan
        assert len(plan["steps"]) == 2
        assert plan["steps"][0]["tool"] == "tavily"
        assert plan["steps"][1]["tool"] == "anthropic"
        assert plan["total_estimated_cost"] <= 0.50

    @patch("agent.planning.anthropic.Anthropic")
    def test_generate_plan_budget_cutoff(self, mock_client_class):
        """Plan respects budget ceiling."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create.return_value = mock_anthropic_response(
            json.dumps({
                "steps": [
                    {"description": "Step 1", "tool": "anthropic"},  # $0.08
                    {"description": "Step 2", "tool": "anthropic"},  # $0.08
                    {"description": "Step 3", "tool": "anthropic"},  # $0.08 → total $0.24 > $0.15
                ]
            })
        )

        plan = generate_plan("Test", max_budget_usd=0.15)

        # Only 1 step fits in $0.15 budget (each anthropic is $0.08)
        assert len(plan["steps"]) == 1
        assert plan["total_estimated_cost"] <= 0.15

    @patch("agent.planning.anthropic.Anthropic")
    def test_generate_plan_custom_session_id(self, mock_client_class):
        """Custom session ID is preserved."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create.return_value = mock_anthropic_response(
            json.dumps({"steps": [{"description": "Step 1", "tool": "tavily"}]})
        )

        plan = generate_plan("Test", max_budget_usd=1.0, session_id="custom-123")
        assert plan["session_id"] == "custom-123"

    @patch("agent.planning.anthropic.Anthropic")
    def test_generate_plan_invalid_tool_defaults(self, mock_client_class):
        """Invalid tool names default to anthropic."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create.return_value = mock_anthropic_response(
            json.dumps({
                "steps": [{"description": "Step 1", "tool": "unknown_tool"}]
            })
        )

        plan = generate_plan("Test", max_budget_usd=1.0)
        assert plan["steps"][0]["tool"] == "anthropic"


# ─── Executor Tests ───────────────────────────────────────────


class TestExecutor:
    """Test the executor module."""

    @patch("agent.executor._execute_anthropic")
    @patch("agent.executor._approve_step_onchain")
    @patch("agent.executor._consume_step_onchain")
    def test_execute_plan_success(self, mock_consume, mock_approve, mock_exec):
        """Successful execution of all steps."""
        mock_approve.return_value = {
            "authorized": True,
            "tx_hash": "sim_auth_001",
            "error": None,
        }
        mock_consume.return_value = {
            "confirmed": True,
            "tx_hash": "sim_confirm_001",
        }
        mock_exec.return_value = {
            "data": {"analysis": "Test result", "confidence": "high"},
            "sources": ["anthropic:claude"],
        }

        plan = {
            "session_id": "test-session",
            "query": "Test query",
            "steps": [
                {"id": "step_0", "index": 0, "description": "Analyze", "tool": "anthropic", "estimated_cost_usd": 0.08},
            ],
        }

        result = execute_plan(plan)

        assert len(result["step_results"]) == 1
        assert result["step_results"][0]["status"] == "completed"
        assert result["total_spent_usd"] == 0.08
        assert result["was_halted"] is False

    @patch("agent.executor._approve_step_onchain")
    def test_execute_plan_payment_denied(self, mock_approve):
        """Execution halts on payment denial."""
        mock_approve.return_value = {
            "authorized": False,
            "tx_hash": None,
            "error": "x402: exceeds budget",
        }

        plan = {
            "session_id": "test-session",
            "query": "Test query",
            "steps": [
                {"id": "step_0", "index": 0, "description": "Step 0", "tool": "anthropic", "estimated_cost_usd": 0.08},
                {"id": "step_1", "index": 1, "description": "Step 1", "tool": "tavily", "estimated_cost_usd": 0.01},
            ],
        }

        result = execute_plan(plan)

        assert result["was_halted"] is True
        assert result["step_results"][0]["status"] == "payment_denied"
        assert len(result["step_results"]) == 1  # stopped after first step

    @patch("agent.executor._execute_anthropic")
    @patch("agent.executor._approve_step_onchain")
    @patch("agent.executor._consume_step_onchain")
    def test_execute_plan_tool_failure_continues(self, mock_consume, mock_approve, mock_exec):
        """Tool failure doesn't halt execution — continues to next step."""
        mock_approve.return_value = {
            "authorized": True,
            "tx_hash": "sim",
            "error": None,
        }
        mock_consume.return_value = {"confirmed": True, "tx_hash": "sim"}
        mock_exec.side_effect = [
            Exception("API timeout"),
            {"data": {"analysis": "OK"}, "sources": []},
        ]

        plan = {
            "session_id": "test-session",
            "query": "Test",
            "steps": [
                {"id": "step_0", "index": 0, "description": "Fail", "tool": "anthropic", "estimated_cost_usd": 0.08},
                {"id": "step_1", "index": 1, "description": "Pass", "tool": "anthropic", "estimated_cost_usd": 0.08},
            ],
        }

        result = execute_plan(plan)

        assert len(result["step_results"]) == 2
        assert result["step_results"][0]["status"] == "failed"
        assert result["step_results"][1]["status"] == "completed"
        assert result["was_halted"] is False


# ─── Synthesizer Tests ────────────────────────────────────────


class TestSynthesizer:
    """Test the synthesis module."""

    @patch("agent.synthesizer.anthropic.Anthropic")
    def test_synthesize_results_success(self, mock_client_class):
        """Successful synthesis produces structured output."""
        os.environ["ANTHROPIC_API_KEY"] = "test-key"

        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.messages.create.return_value = mock_anthropic_response(
            json.dumps({
                "answer": "Aave v3 TVL is approximately $10B.",
                "confidence": "high",
                "key_findings": [{"claim": "TVL is $10B", "evidence": "From DeFiLlama", "source": "tavily", "confidence": "high"}],
                "assumptions": ["Data is current as of today"],
                "limitations": ["Only covers Ethereum mainnet"],
            })
        )

        step_results = [
            {
                "step_id": "step_0",
                "index": 0,
                "status": "completed",
                "tool": "tavily",
                "output": {"answer": "Aave TVL: $10B"},
                "sources": ["https://defillama.com"],
            },
        ]

        result = synthesize_results("What is Aave TVL?", step_results, 0.01, False)

        assert result["answer"] == "Aave v3 TVL is approximately $10B."
        assert result["confidence"] == "high"
        assert result["steps_executed"] == 1
        assert result["was_halted"] is False

    def test_synthesize_no_completed_steps(self):
        """Synthesis with no completed steps returns empty result."""
        step_results = [
            {"step_id": "step_0", "index": 0, "status": "failed", "tool": "anthropic", "output": None, "sources": []},
        ]

        result = synthesize_results("Test", step_results, 0.0, True)

        assert result["confidence"] == "low"
        assert result["steps_executed"] == 0
        assert result["was_halted"] is True

    def test_handle_halt_with_partial_results(self):
        """Halt handler produces partial result from completed steps."""
        partial = [
            {"step_id": "s0", "index": 0, "status": "completed", "tool": "tavily", "output": {"answer": "Some data"}},
            {"step_id": "s1", "index": 1, "status": "failed", "tool": "anthropic", "output": None},
        ]

        result = handle_halt(
            error_source="execution_node",
            error_message="Budget exceeded",
            plan={"session_id": "test"},
            partial_results=partial,
            total_spent=0.01,
        )

        assert result["status"] == "halted"
        assert result["error_source"] == "execution_node"
        assert result["steps_completed"] == 1
        assert result["refund_attempted"] is True

    def test_handle_halt_no_results(self):
        """Halt handler with no results."""
        result = handle_halt(error_source="planning_node", error_message="API error")

        assert result["status"] == "halted"
        assert result["steps_completed"] == 0
