"""
backend/copilot/routes.py - Flask API Routes for Quantitative Copilot.

Endpoints:
- POST /api/copilot/chat
- POST /api/copilot/execute-confirmed-order
- GET  /api/copilot/history/<session_id>
- GET  /api/copilot/status
"""

import logging
from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from backend.copilot.copilot_engine import get_copilot_engine
from backend.copilot.openalgo_trader import get_openalgo_trader
from backend.copilot.dhan_client import get_dhan_client

logger = logging.getLogger("copilot.routes")

copilot_bp = Blueprint("copilot_bp", __name__, url_prefix="/api/copilot")


@copilot_bp.route("/chat", methods=["POST"])
@cross_origin()
def copilot_chat():
    """
    Handle natural language query, execute Gemini reasoning & tools, return structured response.
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "default-session")
        message = data.get("message", "").strip()
        active_symbol = data.get("active_symbol", "BHEL").strip()
        active_timeframe = str(data.get("active_timeframe", "5m")).strip()

        if not message:
            return jsonify({"status": "error", "message": "Query message cannot be empty."}), 400

        engine = get_copilot_engine()
        result = engine.chat(
            session_id=session_id,
            message=message,
            active_symbol=active_symbol,
            active_timeframe=active_timeframe,
        )

        return jsonify(result), 200

    except Exception as e:
        logger.exception(f"Error in /api/copilot/chat: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@copilot_bp.route("/execute-confirmed-order", methods=["POST"])
@cross_origin()
def execute_confirmed_order():
    """
    Execute an order intent ONLY after explicit user confirmation token verification.
    """
    try:
        data = request.get_json(silent=True) or {}
        token = data.get("token") or data.get("confirmation_token")

        if not token:
            return jsonify({"status": "FAILED", "message": "Confirmation token is required."}), 400

        trader = get_openalgo_trader()
        result = trader.execute_confirmed_order(token)

        status_code = 200 if result.get("status") == "SUCCESS" else 400
        return jsonify(result), status_code

    except Exception as e:
        logger.exception(f"Error in /api/copilot/execute-confirmed-order: {e}")
        return jsonify({"status": "FAILED", "message": str(e)}), 500


@copilot_bp.route("/history/<session_id>", methods=["GET"])
@cross_origin()
def get_session_history(session_id: str):
    """
    Retrieve full multi-turn conversation history for a session.
    """
    try:
        engine = get_copilot_engine()
        history = engine.get_history(session_id)
        return jsonify({"status": "success", "session_id": session_id, "history": history}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@copilot_bp.route("/status", methods=["GET"])
@cross_origin()
def get_copilot_status():
    """
    Report connectivity and health of Gemini LLM and DhanHQ Data APIs.
    """
    try:
        engine = get_copilot_engine()
        dhan = get_dhan_client()
        return jsonify({
            "status": "success",
            "gemini_configured": engine.is_configured(),
            "model_name": engine.model_name,
            "dhan_client_id": dhan.client_id,
            "dhan_ready": bool(dhan.client_id),
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
