"""
blueprints/market_data_feed.py - Market Data Source & Streaming Blueprint.

Provides endpoints for:
- Verifying Dhan Data API credentials & latency
- Fetching historical OHLCV candles
- Live quotes and 20-level market depth
- Real-time Server-Sent Events (SSE) tick streaming for web charts
- Market data source configuration and toggling
"""

import json
import time
from collections.abc import Generator

from flask import Blueprint, Response, jsonify, request, session
from flask_cors import cross_origin

from services.dhan_data_feed import get_dhan_data_feed
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

market_data_bp = Blueprint("market_data_bp", __name__, url_prefix="/api/data")


@market_data_bp.route("/ui", methods=["GET"])
@market_data_bp.route("/panel", methods=["GET"])
def serve_market_data_ui():
    import os

    from flask import send_file
    panel_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "market_data_panel.html")
    if os.path.exists(panel_path):
        return send_file(panel_path)
    return "Market Data Panel not found", 404


@market_data_bp.route("/dhan/verify", methods=["POST"])
@market_data_bp.route("/verify-data", methods=["POST"])
@market_data_bp.route("/dhan/verify-data", methods=["POST"])
@cross_origin()
def verify_dhan_data_api():
    """Verify Dhan Market Data API credentials, access permissions, and latency."""
    try:
        data = request.get_json(silent=True) or {}
        client_id = data.get("client_id")
        access_token = data.get("access_token")

        feed = get_dhan_data_feed()
        if client_id and access_token:
            feed.client_id = client_id
            feed.access_token = access_token

        success, result = feed.verify_credentials()
        status_code = 200 if success else 400
        return jsonify(result), status_code

    except Exception as e:
        logger.exception(f"Error in /api/data/dhan/verify: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@market_data_bp.route("/history", methods=["GET"])
@cross_origin()
def get_historical_data():
    """
    Fetch historical OHLCV candle data formatted as standard OpenAlgo records.
    Query Params:
      - symbol: e.g. 'RELIANCE', 'NIFTY'
      - security_id: e.g. '1330', '13'
      - exchange: 'NSE_EQ', 'NSE_FNO', 'MCX_COMM' (default: 'NSE_EQ')
      - interval: '1', '5', '15', '25', '60', 'D' (default: '5')
      - from_date: 'YYYY-MM-DD'
      - to_date: 'YYYY-MM-DD'
    """
    try:
        security_id = request.args.get("security_id")
        symbol = request.args.get("symbol", "NIFTY")
        exchange = request.args.get("exchange", "NSE_EQ")
        interval = request.args.get("interval", "5")
        from_date = request.args.get("from_date")
        to_date = request.args.get("to_date")

        # Map common symbols to security IDs if not provided
        if not security_id:
            symbol_map = {
                "NIFTY": ("13", "NSE_EQ", "INDEX"),
                "BANKNIFTY": ("25", "NSE_EQ", "INDEX"),
                "FINNIFTY": ("27", "NSE_EQ", "INDEX"),
                "RELIANCE": ("2885", "NSE_EQ", "EQUITY"),
                "TCS": ("11536", "NSE_EQ", "EQUITY"),
                "HDFCBANK": ("1333", "NSE_EQ", "EQUITY"),
                "INFY": ("1594", "NSE_EQ", "EQUITY"),
            }
            mapped = symbol_map.get(symbol.upper().strip())
            if mapped:
                security_id, exchange, inst_type = mapped
            else:
                security_id = "13"
                inst_type = "EQUITY"
        else:
            inst_type = "INDEX" if symbol.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY") else "EQUITY"

        feed = get_dhan_data_feed()
        success, df_or_err = feed.get_historical_candles(
            security_id=security_id,
            exchange_segment=exchange,
            instrument_type=inst_type,
            interval=interval,
            from_date=from_date,
            to_date=to_date,
        )

        if not success:
            return jsonify({"status": "error", "error": df_or_err}), 400

        # Convert DataFrame to JSON serializable candles
        candles = []
        for _, row in df_or_err.iterrows():
            candles.append({
                "time": row["datetime"].strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": int(row["datetime"].timestamp()),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })

        return jsonify({
            "status": "success",
            "symbol": symbol,
            "security_id": security_id,
            "exchange": exchange,
            "interval": interval,
            "count": len(candles),
            "candles": candles,
        })

    except Exception as e:
        logger.exception(f"Error in /api/data/history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@market_data_bp.route("/dhan/quote", methods=["GET"])
@cross_origin()
def get_dhan_quote():
    """Fetch live quote with 5/20-level market depth."""
    try:
        security_id = int(request.args.get("security_id", 13))
        segment = int(request.args.get("segment", 1))

        feed = get_dhan_data_feed()
        success, quote_data = feed.get_quote(security_id=security_id, segment=segment)

        if success:
            return jsonify({"status": "success", "data": quote_data})
        return jsonify({"status": "error", "error": quote_data}), 400

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@market_data_bp.route("/feed/stream", methods=["GET"])
def stream_live_feed():
    """
    Server-Sent Events (SSE) endpoint to stream live real-time ticks to browser charts.
    """
    security_id = request.args.get("security_id", "13")
    symbol = request.args.get("symbol", "NIFTY")

    def event_stream() -> Generator[str, None, None]:
        feed = get_dhan_data_feed()

        # Ensure WebSocket is active
        if not feed.is_connected:
            feed.start_websocket()
            feed.subscribe([{"exchange_segment": "NSE", "security_id": security_id, "symbol": symbol}])

        yield f"data: {json.dumps({'type': 'init', 'status': 'streaming', 'symbol': symbol, 'security_id': security_id})}\n\n"

        while True:
            ltp = feed.last_ltp_cache.get(str(security_id))
            if ltp:
                payload = {
                    "type": "tick",
                    "symbol": symbol,
                    "security_id": security_id,
                    "ltp": ltp,
                    "timestamp": int(time.time()),
                    "time_str": time.strftime("%H:%M:%S"),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(0.5)

    return Response(event_stream(), mimetype="text/event-stream")
