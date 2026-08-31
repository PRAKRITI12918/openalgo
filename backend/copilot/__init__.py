"""
backend/copilot - Quantitative AI Copilot Module for OpenAlgo.
Integrates Google Gemini LLM, DhanHQ Market Data API v2, and OpenAlgo Execution Engine.
"""

from backend.copilot.dhan_client import DhanMarketDataClient, get_dhan_client
from backend.copilot.openalgo_trader import OpenAlgoTrader, get_openalgo_trader
from backend.copilot.copilot_engine import QuantitativeCopilotEngine, get_copilot_engine
from backend.copilot.routes import copilot_bp

__all__ = [
    "DhanMarketDataClient",
    "get_dhan_client",
    "OpenAlgoTrader",
    "get_openalgo_trader",
    "QuantitativeCopilotEngine",
    "get_copilot_engine",
    "copilot_bp",
]
