"""
API Foundation & Route Hardening Test Suite.
Verifies health probes, signal ingestion aliases, order and position query endpoints,
strategy cataloging, and centralized error handling (404, 422, 500).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.schemas import LegOrderRequest, OrderAction, OrderType, StrategySignalPayload
from src.strategy_engine.models import MarketRegime, OptionType, SignalType, StrategyType, UnderlyingIndex


@pytest.fixture
def test_app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture
def sample_iron_condor_payload() -> StrategySignalPayload:
    """Generates a standard 4-leg Iron Condor entry signal payload."""
    legs = [
        LegOrderRequest(
            symbol="NIFTY26AUG23800PE",
            underlying=UnderlyingIndex.NIFTY,
            strike=23800.0,
            option_type=OptionType.PE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
            price=25.0,
            is_hedge_leg=True,
        ),
        LegOrderRequest(
            symbol="NIFTY26AUG24600CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24600.0,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
            price=20.0,
            is_hedge_leg=True,
        ),
        LegOrderRequest(
            symbol="NIFTY26AUG24000PE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000.0,
            option_type=OptionType.PE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=50,
            order_type=OrderType.MARKET,
            price=75.0,
            is_hedge_leg=False,
        ),
        LegOrderRequest(
            symbol="NIFTY26AUG24400CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24400.0,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=50,
            order_type=OrderType.MARKET,
            price=60.0,
            is_hedge_leg=False,
        ),
    ]
    return StrategySignalPayload(
        strategy_name="IRON_CONDOR",
        strategy_type=StrategyType.IRON_CONDOR,
        signal_type=SignalType.ENTRY,
        underlying=UnderlyingIndex.NIFTY,
        regime=MarketRegime.LOW_IV_RANGING,
        legs=legs,
        entry_credit_debit=90.0,
        max_profit=4500.0,
        max_loss=5500.0,
    )


# =============================================================================
# 1. Health & Liveness Probe Tests
# =============================================================================

@pytest.mark.asyncio
async def test_root_liveness_health_check(test_app):
    """Test dependency-free root /health liveness probe."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "openalgo-execution-engine"
        assert data["version"] == "2.0.0"
        assert "timestamp" in data
        assert "environment" in data


@pytest.mark.asyncio
async def test_api_v1_liveness_health_check(test_app):
    """Test /api/v1/health/liveness endpoint."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health/liveness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "openalgo-execution-engine"


@pytest.mark.asyncio
async def test_broker_readiness_health_check(test_app):
    """Test /api/v1/health broker readiness check remains backward-compatible."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["broker_connected"] is True
        assert data["broker_mode"] == "MOCK"


# =============================================================================
# 2. Strategy Signal Ingestion Tests (Standard Route & Aliases)
# =============================================================================

@pytest.mark.asyncio
async def test_signals_ingest_standard_route_async(test_app, sample_iron_condor_payload: StrategySignalPayload):
    """Test POST /signals standard ingestion endpoint."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        payload_dict = sample_iron_condor_payload.model_dump(mode="json")
        resp = await client.post("/signals?sync=false", json=payload_dict)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "QUEUED"
        assert data["signal_id"] == sample_iron_condor_payload.signal_id


@pytest.mark.asyncio
async def test_api_v1_signals_ingest_sync(test_app, sample_iron_condor_payload: StrategySignalPayload):
    """Test POST /api/v1/signals sync execution."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        payload_dict = sample_iron_condor_payload.model_dump(mode="json")
        resp = await client.post("/api/v1/signals?sync=true", json=payload_dict)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["execution_status"] == "FULLY_FILLED"
        assert data["completed_legs"] == 4


@pytest.mark.asyncio
async def test_signals_validation_failure_schema_rejection(test_app):
    """Test POST /signals schema validation failure returns 422 with structured error."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        invalid_payload = {
            "strategy_name": "TEST",
            "underlying": "INVALID_INDEX",
            "legs": [],  # Empty legs list violates min_length=1
        }
        resp = await client.post("/signals", json=invalid_payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "SCHEMA_VALIDATION_FAILED"
        assert "validation_errors" in data
        assert "correlation_id" in data


# =============================================================================
# 3. Orders & Sequences Query Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_orders_list_empty_and_populated(test_app, sample_iron_condor_payload: StrategySignalPayload):
    """Test GET /orders and GET /api/v1/orders."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Initially empty
        resp = await client.get("/orders")
        assert resp.status_code == 200
        assert resp.json() == []

        # Ingest a signal synchronously
        payload_dict = sample_iron_condor_payload.model_dump(mode="json")
        post_resp = await client.post("/signals?sync=true", json=payload_dict)
        assert post_resp.status_code == 202
        seq_id = post_resp.json()["sequence_id"]

        # List orders again
        orders_resp = await client.get("/orders")
        assert orders_resp.status_code == 200
        orders_list = orders_resp.json()
        assert len(orders_list) == 1
        assert orders_list[0]["sequence_id"] == seq_id

        # Query single order by ID
        single_resp = await client.get(f"/orders/{seq_id}")
        assert single_resp.status_code == 200
        assert single_resp.json()["sequence_id"] == seq_id


@pytest.mark.asyncio
async def test_get_order_nonexistent_returns_structured_404(test_app):
    """Test GET /orders/{sequence_id} returns structured 404 error envelope."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/orders/nonexistent-sequence-id")
        assert resp.status_code == 404
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "HTTP_ERROR"
        assert "Execution sequence nonexistent-sequence-id not found" in data["message"]
        assert "correlation_id" in data


# =============================================================================
# 4. Positions & Strategies Query Tests
# =============================================================================

@pytest.mark.asyncio
async def test_get_positions_list(test_app):
    """Test GET /positions and GET /api/v1/positions."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.get("/positions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        resp_v1 = await client.get("/api/v1/positions")
        assert resp_v1.status_code == 200
        assert isinstance(resp_v1.json(), list)


@pytest.mark.asyncio
async def test_get_strategies_catalog(test_app):
    """Test GET /strategies and GET /api/v1/strategies returns complete strategy catalog."""
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        for path in ("/strategies", "/api/v1/strategies"):
            resp = await client.get(path)
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["count"] == 7
            assert len(data["strategies"]) == 7

            strategy_types = [s["strategy_type"] for s in data["strategies"]]
            assert "IRON_CONDOR" in strategy_types
            assert "HEDGED_STRADDLE" in strategy_types
            assert "BULL_CALL_SPREAD" in strategy_types
            assert "BEAR_PUT_SPREAD" in strategy_types
            assert "CALENDAR_SPREAD" in strategy_types
            assert "RATIO_SPREAD" in strategy_types
            assert "SHORT_STRANGLE" in strategy_types

            # Verify schema properties
            iron_condor = next(s for s in data["strategies"] if s["strategy_type"] == "IRON_CONDOR")
            assert iron_condor["legs_count"] == 4
            assert iron_condor["directionality"] == "NEUTRAL"
            assert "LOW_IV_RANGING" in iron_condor["favorable_regimes"]


# =============================================================================
# 5. Centralized Exception Handling Tests (500 Server Errors)
# =============================================================================

@pytest.mark.asyncio
async def test_centralized_unhandled_exception_handler(test_app):
    """Test that unhandled server exceptions return structured 500 error envelope without crashing."""
    # Inject a temporary failing route to simulate unexpected server failure
    @test_app.get("/test/trigger-error")
    async def trigger_unexpected_error():
        raise RuntimeError("Simulated unexpected internal database failure")

    async with AsyncClient(transport=ASGITransport(app=test_app, raise_app_exceptions=False), base_url="http://test") as client:
        resp = await client.get("/test/trigger-error")
        assert resp.status_code == 500
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "INTERNAL_SERVER_ERROR"
        assert data["message"] == "An unexpected internal server error occurred"
        assert "correlation_id" in data
        assert "Simulated unexpected" not in data["message"]  # Traceback must not leak to client
