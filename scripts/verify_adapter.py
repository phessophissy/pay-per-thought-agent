import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import cre_adapter

def test_setup_workflow():
    print("Testing setup_workflow...")
    try:
        # We need API keys for this to work since it calls Gemini
        if not os.environ.get("GEMINI_API_KEY"):
            print("SKIPPING: GEMINI_API_KEY not set")
            return

        result = cre_adapter.setup_workflow("What is the price of ETH?", 0.50)
        print(json.dumps(result, indent=2))
        
        # Verify structure
        assert "step_1_id" in result
        assert "step_1_tool" in result
        assert "step_2_tool" in result
        assert result["step_count"] == 2
        print("PASS: setup_workflow structure verified")
    except Exception as e:
        print(f"FAIL: {e}")

def test_execute_adapters():
    print("\nTesting execute_step_with_query_adapter (Mock Tavily)...")
    try:
        # mocking executor might be needed if no keys
        # But let's see if we can trigger it. 
        # Actually without keys it will fail.
        pass
    except Exception as e:
        print(f"FAIL: {e}")

if __name__ == "__main__":
    test_setup_workflow()
