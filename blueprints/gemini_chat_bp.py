"""
blueprints/gemini_chat_bp.py - Gemini AI Trading Analyst Chat API Blueprint.

Provides endpoints for:
- Interactive quantitative chart analysis with Gemini AI
- Real-time Dhan Data API tool execution & indicator synthesis
- Chat status & model discovery
"""

import os

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from services.gemini_analyst import get_gemini_analyst
from utils.logging import get_logger

logger = get_logger(__name__)

gemini_chat_bp = Blueprint("gemini_chat_bp", __name__, url_prefix="/api/chat")


@gemini_chat_bp.route("/trading-assistant", methods=["POST"])
@cross_origin()
def trading_assistant_chat():
    """
    Execute institutional quantitative chart analysis with Gemini AI using live Dhan feeds.
    Payload:
      - message: str (e.g. 'Analyze Trend & Support Resistance')
      - symbol: str (e.g. 'BHEL', 'NIFTY')
      - timeframe: str (e.g. '5', '15', 'D')
      - exchange: str (e.g. 'NSE_EQ')
      - history: list of prior conversation turns (optional)
    """
    try:
        data = request.get_json(silent=True) or {}
        message = data.get("message", "Analyze market structure and momentum.").strip()
        symbol = data.get("symbol", "NIFTY").strip()
        timeframe = str(data.get("timeframe", "5")).strip()
        exchange = data.get("exchange", "NSE_EQ").strip()
        history = data.get("history", [])

        analyst = get_gemini_analyst()
        result = analyst.analyze_chart(
            message=message,
            symbol=symbol,
            timeframe=timeframe,
            exchange=exchange,
            history=history,
        )

        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/chat/trading-assistant: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@gemini_chat_bp.route("/status", methods=["GET"])
@cross_origin()
def get_chat_status():
    """Return status of Gemini AI and Dhan Data API connectivity."""
    try:
        analyst = get_gemini_analyst()
        return jsonify({
            "status": "success",
            "gemini_configured": analyst.is_ready(),
            "model_name": analyst.model_name,
            "dhan_connected": analyst.dhan_feed.is_configured(),
            "client_id": analyst.dhan_feed.client_id,
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
