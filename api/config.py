"""
Pay-Per-Thought Agent — Configuration
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Environment-based configuration."""

    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

    # Tavily
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")

    # Blockchain
    RPC_URL: str = os.getenv("RPC_URL", "https://eth-sepolia.g.alchemy.com/v2/demo")

    # x402 Payment
    X402_CONTRACT_ADDRESS: str = os.getenv(
        "X402_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000000"
    )
    PAYMENT_TOKEN_ADDRESS: str = os.getenv(
        "PAYMENT_TOKEN_ADDRESS", "0x0000000000000000000000000000000000000000"
    )
    PRIVATE_KEY: str = os.getenv("PRIVATE_KEY", "")

    # Costs (USD)
    COST_GEMINI: float = 0.005
    COST_TAVILY: float = 0.01
    COST_BLOCKCHAIN_RPC: float = 0.001
    COST_REASONING: float = 0.02

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing required config keys."""
        missing = []
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not cls.TAVILY_API_KEY:
            missing.append("TAVILY_API_KEY")
        return missing


config = Config()
