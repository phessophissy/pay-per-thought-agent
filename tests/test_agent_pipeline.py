"""
Tests for the Pay-Per-Thought Agent Pipeline (Gemini Edition - google-genai SDK).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from agent.planning import generate_plan
from agent.executor import execute_plan
from agent.synthesizer import synthesize_results, handle_halt


# ─── Mock Data ────────────────────────────────────────────────

MOCK_GEMINI_PLAN_RESPONSE = json.dumps({
    "steps": [
        {"description": "Step 1", "tool": "gemini"},
        {"description": "Step 2", "tool": "tavily"},
    ]
})

MOCK_GEMINI_EXEC_RESPONSE = json.dumps({
    "analysis": "Test result",
    "confidence": "high",
    "key_points": ["Point 1"]
})

MOCK_GEMINI_SYNTHESIS_RESPONSE = json.dumps({
    "answer": "Final answer",
    "confidence": "high",
    "key_findings": [],
    "assumptions": [],
    "limitations": []
})


# ─── Tests: Planning ──────────────────────────────────────────

class TestPlanning:
    @patch("google.genai.Client")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"})
    def test_generate_plan_basic(self, MockClient):
        """Test basic plan generation with Gemini mock."""
        # Setup mock
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value.text = MOCK_GEMINI_PLAN_RESPONSE

        plan = generate_plan("Test query", 1.0)

        assert plan["query"] == "Test query"
        assert len(plan["steps"]) == 2
        assert plan["steps"][0]["tool"] == "gemini"
        assert plan["total_estimated_cost"] > 0

    @patch("google.genai.Client")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"})
    def test_generate_plan_budget_cutoff(self, MockClient):
        """Test that steps are truncated if budget is exceeded."""
        # Create a plan with many expensive steps
        expensive_steps = {"steps": [{"description": "Exp", "tool": "gemini"}] * 50}
        
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value.text = json.dumps(expensive_steps)

        # Budget allows only a few steps (0.005 per step)
        plan = generate_plan("Test", 0.02)
        
        assert len(plan["steps"]) < 50
        assert plan["total_estimated_cost"] <= 0.02

    @patch("google.genai.Client")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"})
    def test_generate_plan_custom_session_id(self, MockClient):
        """Test that custom session ID is preserved."""
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value.text = MOCK_GEMINI_PLAN_RESPONSE

        plan = generate_plan("Test", 1.0, session_id="custom-123")
        assert plan["session_id"] == "custom-123"

    @patch("google.genai.Client")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"})
    def test_generate_plan_invalid_tool_defaults(self, MockClient):
        """Test that invalid tools default to gemini."""
        bad_tool_plan = json.dumps({"steps": [{"description": "X", "tool": "bad_tool"}]})
        
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value.text = bad_tool_plan

        plan = generate_plan("Test", 1.0)
        assert plan["steps"][0]["tool"] == "gemini"


# ─── Tests: Executor ──────────────────────────────────────────

class TestExecutor:
    @patch("agent.executor._get_tool_executor") # Mock the dynamic lookup
    @patch("agent.executor._approve_step_onchain")
    @patch("agent.executor._consume_step_onchain")
    def test_execute_plan_success(self, mock_consume, mock_approve, mock_get_executor):
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
        
        # Mock the tool executor function itself
        mock_tool_fn = MagicMock()
        mock_tool_fn.return_value = {
            "data": {"analysis": "Test result", "confidence": "high"},
            "sources": ["gemini:flash"],
        }
        mock_get_executor.return_value = mock_tool_fn

        plan = {
            "session_id": "test-session",
            "query": "Test query",
            "steps": [
                {"id": "step_0", "index": 0, "description": "Analyze", "tool": "gemini", "estimated_cost_usd": 0.005},
            ],
        }

        result = execute_plan(plan)

        assert len(result["step_results"]) == 1
        assert result["step_results"][0]["status"] == "completed"
        assert result["total_spent_usd"] == 0.005
        assert result["was_halted"] is False

    @patch("agent.executor._approve_step_onchain")
    def test_execute_plan_payment_denied(self, mock_approve):
        """Execution halts if payment is denied."""
        mock_approve.return_value = {
            "authorized": False,
            "error": "Budget exceeded",
        }

        plan = {
            "session_id": "test",
            "query": "Test",
            "steps": [{"id": "s1", "index": 0, "description": "X", "tool": "gemini", "estimated_cost_usd": 0.01}],
        }

        result = execute_plan(plan)

        assert result["was_halted"] is True
        assert result["step_results"][0]["status"] == "payment_denied"

    @patch("agent.executor._get_tool_executor")
    @patch("agent.executor._approve_step_onchain")
    @patch("agent.executor._consume_step_onchain")
    def test_execute_plan_tool_failure_continues(self, mock_consume, mock_approve, mock_get_executor):
        """Tool failure doesn't halt execution — continues to next step."""
        mock_approve.return_value = {"authorized": True, "tx_hash": "sim", "error": None}
        mock_consume.return_value = {"confirmed": True, "tx_hash": "sim"}

        # First tool fails, second succeeds
        mock_fail = MagicMock(side_effect=Exception("API timeout"))
        mock_success = MagicMock(return_value={"data": {"analysis": "OK"}, "sources": []})
        
        # side_effect for _get_tool_executor not ideal because it's called per step with same tool name
        # easier to just mock the executor function returned
        mock_get_executor.side_effect = [mock_fail, mock_success]

        plan = {
            "session_id": "test-session",
            "query": "Test",
            "steps": [
                {"id": "step_0", "index": 0, "description": "Fail", "tool": "gemini", "estimated_cost_usd": 0.01},
                {"id": "step_1", "index": 1, "description": "Pass", "tool": "gemini", "estimated_cost_usd": 0.01},
            ],
        }

        result = execute_plan(plan)

        assert len(result["step_results"]) == 2
        assert result["step_results"][0]["status"] == "failed"
        assert result["step_results"][1]["status"] == "completed"


# ─── Tests: Synthesizer ───────────────────────────────────────

class TestSynthesizer:
    @patch("google.genai.Client")
    @patch.dict("os.environ", {"GEMINI_API_KEY": "test_key"})
    def test_synthesize_results_success(self, MockClient):
        """Test synthesis with completed steps."""
        mock_instance = MockClient.return_value
        mock_instance.models.generate_content.return_value.text = MOCK_GEMINI_SYNTHESIS_RESPONSE

        step_results = [
            {"status": "completed", "tool": "gemini", "output": {"data": "foo"}, "index": 0},
            {"status": "failed", "tool": "tavily", "output": None, "index": 1},
        ]

        result = synthesize_results("Query", step_results, 0.50, False)

        assert result["answer"] == "Final answer"
        assert result["steps_executed"] == 1
        assert result["steps_total"] == 2

    def test_synthesize_no_completed_steps(self):
        """Test synthesis when all steps failed."""
        step_results = [{"status": "failed"}]
        result = synthesize_results("Query", step_results, 0.0, False)
        
        assert "No steps completed" in result["answer"]
        assert result["confidence"] == "low"

    def test_handle_halt_with_partial_results(self):
        """Test halt handler with some valid data."""
        partial = [
            {"status": "completed", "tool": "gemini", "output": {"analysis": "Partial data"}, "index": 0}
        ]
        result = handle_halt("node_1", "Fatal error", {}, partial, 0.10)
        
        assert result["status"] == "halted"
        assert "Partial data" in result["partial_answer"]

    def test_handle_halt_no_results(self):
        """Test halt handler with no data."""
        result = handle_halt("node_1", "Error", {}, [], 0.0)
        assert "halted before any results" in result["partial_answer"]
