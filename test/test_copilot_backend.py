"""
test/test_copilot_backend.py - Unit and Integration Tests for Quantitative Copilot Module.
"""

import json
import pytest
from flask import Flask

from backend.copilot.dhan_client import DhanMarketDataClient, TokenBucketRateLimiter
from backend.copilot.openalgo_trader import OpenAlgoTrader
from backend.copilot.copilot_engine import QuantitativeCopilotEngine
from backend.copilot.routes import copilot_bp


@pytest.fixture
def copilot_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(copilot_bp)
    app.config["TESTING"] = True
    return app


# =============================================================================
# 1. Dhan Client & Rate Limiter Tests
# =============================================================================

def test_token_bucket_rate_limiter():
    limiter = TokenBucketRateLimiter(rate=5.0, capacity=5.0)
    # Immediate acquires should succeed up to capacity
    assert limiter.acquire(tokens=1.0) is True
    assert limiter.acquire(tokens=1.0) is True
    assert limiter.acquire(tokens=1.0) is True


def test_dhan_client_symbol_search_and_quote():
    client = DhanMarketDataClient(client_id="1113284554", access_token="mock-token")
    
    # Test Symbol Resolution
    res = client.search_security("BHEL")
    assert res["symbol"] == "BHEL"
    assert "exchange_segment" in res

    # Test Quote Retrieval
    quote = client.get_quote("BHEL", "NSE_EQ")
    assert quote["symbol"] == "BHEL"
    assert "ltp" in quote
    assert quote["ltp"] > 0

    # Test Market Depth
    depth = client.get_market_depth("BHEL", "NSE_EQ")
    assert "bids" in depth
    assert "asks" in depth
    assert len(depth["bids"]) == 5

    # Test Historical OHLC
    candles = client.get_historical_ohlc("BHEL", "NSE_EQ", interval="5", limit=10)
    assert len(candles) > 0
    assert "open" in candles[0]
    assert "close" in candles[0]


# =============================================================================
# 2. OpenAlgo Trader & 2-Step Order Safety Tests
# =============================================================================

def test_trader_funds_and_risk_validation():
    trader = OpenAlgoTrader()
    funds = trader.get_funds()
    assert funds["status"] == "success"
    assert "available_balance" in funds

    # Valid Order Risk Check
    passed, msg = trader.validate_order_risk(symbol="BHEL", action="BUY", quantity=10, price=430.0, product_type="MIS")
    assert passed is True

    # Invalid Quantity Check
    failed_qty, _ = trader.validate_order_risk(symbol="BHEL", action="BUY", quantity=0, price=430.0)
    assert failed_qty is False

    # Exceeding Safety Threshold Check
    failed_excess, _ = trader.validate_order_risk(symbol="BHEL", action="BUY", quantity=999999, price=430.0)
    assert failed_excess is False


def test_2_step_order_confirmation_and_execution():
    trader = OpenAlgoTrader()
    
    # 1. Prepare Order Intent (Dry-Run Confirmation Payload)
    confirmation = trader.prepare_order_confirmation(
        symbol="BHEL",
        action="BUY",
        quantity=25,
        order_type="MARKET",
        price=430.85,
        product_type="MIS",
        exchange="NSE",
    )
    assert "token" in confirmation
    assert confirmation["quantity"] == 25
    assert confirmation["risk_check_passed"] is True
    token = confirmation["token"]

    # 2. Execute with Invalid Token -> Should Fail
    invalid_res = trader.execute_confirmed_order("invalid-token-12345")
    assert invalid_res["status"] == "FAILED"

    # 3. Execute with Valid Confirmation Token -> Should Succeed
    valid_res = trader.execute_confirmed_order(token)
    assert valid_res["status"] == "SUCCESS"
    assert "order_id" in valid_res

    # 4. Replay Attack Prevention (Second execution with same token must fail)
    replay_res = trader.execute_confirmed_order(token)
    assert replay_res["status"] == "FAILED"


# =============================================================================
# 3. Copilot Engine Reasoning & Multi-Turn Memory Tests
# =============================================================================

def test_copilot_engine_chat_and_tools():
    engine = QuantitativeCopilotEngine()
    session_id = "test-session-unit-1"

    # 1. Query Market Data
    res_market = engine.chat(
        session_id=session_id,
        message="What is the current price and support levels for BHEL?",
        active_symbol="BHEL",
        active_timeframe="5m",
    )
    assert res_market["status"] == "success"
    assert "BHEL" in res_market["response_text"]
    assert res_market["action_required"] is False

    # 2. Query Available Margin
    res_funds = engine.chat(
        session_id=session_id,
        message="How much margin and funds are available?",
        active_symbol="BHEL",
    )
    assert res_funds["status"] == "success"
    assert "Margin & Funds" in res_funds["response_text"]

    # 3. Request Order Placement -> MUST Require Confirmation
    res_order = engine.chat(
        session_id=session_id,
        message="Buy 50 shares of BHEL at market price",
        active_symbol="BHEL",
    )
    assert res_order["status"] == "success"
    assert res_order["action_required"] is True
    assert res_order["order_confirmation"] is not None
    assert res_order["order_confirmation"]["quantity"] == 50
    assert res_order["order_confirmation"]["action"] == "BUY"

    # 4. Verify Session History
    history = engine.get_history(session_id)
    assert len(history) >= 6  # 3 turns (user + assistant each)


# =============================================================================
# 4. API Endpoints Integration Tests
# =============================================================================

def test_copilot_api_routes(copilot_app):
    client = copilot_app.test_client()

    # Test /api/copilot/status
    res_status = client.get("/api/copilot/status")
    assert res_status.status_code == 200
    status_json = res_status.get_json()
    assert status_json["status"] == "success"
    assert "dhan_client_id" in status_json

    # Test /api/copilot/chat
    res_chat = client.post(
        "/api/copilot/chat",
        json={
            "session_id": "api-test-session",
            "message": "Buy 10 shares of BHEL",
            "active_symbol": "BHEL",
            "active_timeframe": "5m",
        },
    )
    assert res_chat.status_code == 200
    chat_json = res_chat.get_json()
    assert chat_json["status"] == "success"
    assert chat_json["action_required"] is True
    assert "order_confirmation" in chat_json
    token = chat_json["order_confirmation"]["token"]

    # Test /api/copilot/execute-confirmed-order
    res_exec = client.post(
        "/api/copilot/execute-confirmed-order",
        json={"token": token},
    )
    assert res_exec.status_code == 200
    exec_json = res_exec.get_json()
    assert exec_json["status"] == "SUCCESS"
    assert "order_id" in exec_json

    # Test /api/copilot/history/<session_id>
    res_hist = client.get("/api/copilot/history/api-test-session")
    assert res_hist.status_code == 200
    hist_json = res_hist.get_json()
    assert len(hist_json["history"]) >= 2
