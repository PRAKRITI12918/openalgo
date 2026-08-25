"""
Comprehensive Pytest Suite for Phase 2: Execution Engine & Backend Pipeline.
Validates:
1. Pydantic v2 strict payload validation and explicit 422 rejections.
2. Hedge-first margin safety execution sequencing (Buys before Sells).
3. Exit sequencing (Short risk closed before Long wings).
4. Circuit-breaker tripping and rollback on hedge leg failure.
5. Mock Broker simulated latency, slippage, lifecycle states, and position bookkeeping.
6. Synthetic tick generation, Greeks computation, and WebSocket broadcasting.
7. FastAPI REST signal ingestion webhook (sync & async queueing) and query endpoints.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from src.adapters.openalgo_mock import MockBrokerRouter
from src.core.config import BrokerMode, ExecutionConfig, LogFormat, get_config, setup_logger
from src.engine.sequence_parser import (
    AsyncOrderQueueManager,
    ExecutionSequenceEngine,
    StrategySequenceParser,
)
from src.engine.tick_replay import (
    HistoricalTickReplayer,
    SyntheticTickGenerator,
    WebSocketConnectionManager,
)
from src.main import create_app
from src.models.schemas import (
    ExecutionEventMessage,
    LegExecutionState,
    LegOrderRequest,
    OrderExecutionSequence,
    OrderStatus,
    OrderType,
    StrategySignalPayload,
    SyntheticTickPayload,
    WebSocketEventType,
)
from src.strategy_engine.models import (
    MarketRegime,
    OptionType,
    OrderAction,
    SignalType,
    StrategyType,
    UnderlyingIndex,
)


@pytest.fixture
def test_config() -> ExecutionConfig:
    """Provides isolated test execution configuration."""
    return ExecutionConfig(
        environment="test",
        broker_mode=BrokerMode.MOCK,
        mock_latency_min_ms=1.0,
        mock_latency_max_ms=5.0,
        mock_slippage_pct=0.05,
        mock_fill_probability=1.0,
        enforce_margin_safety=True,
        delay_between_legs_seconds=0.001,
        synthetic_tick_interval_seconds=0.1,
    )


@pytest.fixture
def mock_broker(test_config: ExecutionConfig) -> MockBrokerRouter:
    """Provides a fresh mock broker router instance."""
    return MockBrokerRouter(config=test_config)


@pytest.fixture
def sample_iron_condor_payload() -> StrategySignalPayload:
    """Generates a standard 4-leg Iron Condor entry signal payload."""
    legs = [
        # Hedge Wings (Buy)
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
        # Short Credit Legs (Sell)
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
            price=70.0,
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
        entry_credit_debit=100.0,
        max_profit=5000.0,
        max_loss=5000.0,
        stop_loss_threshold=3000.0,
        target_threshold=3500.0,
        reason="Low volatility ranging regime optimal for Iron Condor entry",
    )


# =============================================================================
# 1. Config & Logging Tests
# =============================================================================

def test_execution_config_instantiation(test_config: ExecutionConfig):
    assert test_config.environment == "test"
    assert test_config.broker_mode == BrokerMode.MOCK
    assert test_config.enforce_margin_safety is True
    assert test_config.mock_fill_probability == 1.0


def test_structured_logging_initialization(test_config: ExecutionConfig):
    logger = setup_logger(test_config)
    assert logger is not None


# =============================================================================
# 2. Pydantic v2 Schema & Payload Validation Tests
# =============================================================================

def test_valid_payload_parsing(sample_iron_condor_payload: StrategySignalPayload):
    assert sample_iron_condor_payload.strategy_name == "IRON_CONDOR"
    assert len(sample_iron_condor_payload.legs) == 4
    assert sample_iron_condor_payload.underlying == UnderlyingIndex.NIFTY

    # Check auto-assigned sequence groups
    buy_legs = [l for l in sample_iron_condor_payload.legs if l.action == OrderAction.BUY]
    sell_legs = [l for l in sample_iron_condor_payload.legs if l.action == OrderAction.SELL]
    assert all(l.sequence_group == 0 for l in buy_legs)
    assert all(l.sequence_group == 1 for l in sell_legs)


def test_limit_order_validation():
    # Valid limit order
    leg = LegOrderRequest(
        symbol="NIFTY26AUG24200CE",
        underlying=UnderlyingIndex.NIFTY,
        strike=24200.0,
        option_type=OptionType.CE,
        expiry="2026-08-27",
        action=OrderAction.BUY,
        quantity=25,
        order_type=OrderType.LIMIT,
        price=110.0,
    )
    assert leg.price == 110.0

    # Invalid limit order with price <= 0
    with pytest.raises(ValidationError):
        LegOrderRequest(
            symbol="NIFTY26AUG24200CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24200.0,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=25,
            order_type=OrderType.LIMIT,
            price=0.0,
        )


def test_malformed_payload_rejection():
    # Missing legs list
    with pytest.raises(ValidationError):
        StrategySignalPayload(
            strategy_name="IRON_CONDOR",
            underlying=UnderlyingIndex.NIFTY,
            regime=MarketRegime.LOW_IV_RANGING,
            legs=[],
        )

    # Invalid quantity (<= 0)
    with pytest.raises(ValidationError):
        LegOrderRequest(
            symbol="NIFTY26AUG24200CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24200.0,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=-10,
        )


# =============================================================================
# 3. Mock Broker Router Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mock_broker_order_lifecycle(mock_broker: MockBrokerRouter):
    leg = LegOrderRequest(
        symbol="NIFTY26AUG24200CE",
        underlying=UnderlyingIndex.NIFTY,
        strike=24200.0,
        option_type=OptionType.CE,
        expiry="2026-08-27",
        action=OrderAction.BUY,
        quantity=50,
        price=100.0,
    )

    state = await mock_broker.place_order(leg, correlation_id="test_corr_1")
    assert state.status == OrderStatus.COMPLETE
    assert state.filled_quantity == 50
    assert state.order_id is not None
    assert state.execution_price > 0
    assert state.latency_ms > 0

    # Query status
    queried = await mock_broker.get_order_status(state.order_id)
    assert queried.status == OrderStatus.COMPLETE


@pytest.mark.asyncio
async def test_mock_broker_positions_and_funds(mock_broker: MockBrokerRouter):
    # Place BUY order
    buy_leg = LegOrderRequest(
        symbol="NIFTY26AUG24000CE",
        underlying=UnderlyingIndex.NIFTY,
        strike=24000.0,
        option_type=OptionType.CE,
        expiry="2026-08-27",
        action=OrderAction.BUY,
        quantity=50,
        price=100.0,
    )
    await mock_broker.place_order(buy_leg)

    positions = await mock_broker.get_positions()
    assert len(positions) == 1
    assert len(positions[0].legs) == 1
    assert positions[0].legs[0].quantity == 50

    funds = await mock_broker.get_funds()
    assert funds["status"] == "success"
    assert funds["available_funds"] < funds["total_funds"]


@pytest.mark.asyncio
async def test_mock_broker_injected_rejection(mock_broker: MockBrokerRouter):
    mock_broker.inject_rejection_for_symbol("NIFTY26AUG24200CE", "Margin limit breached")

    leg = LegOrderRequest(
        symbol="NIFTY26AUG24200CE",
        underlying=UnderlyingIndex.NIFTY,
        strike=24200.0,
        option_type=OptionType.CE,
        expiry="2026-08-27",
        action=OrderAction.SELL,
        quantity=25,
        price=50.0,
    )

    state = await mock_broker.place_order(leg)
    assert state.status == OrderStatus.REJECTED
    assert state.error_message == "Margin limit breached"
    mock_broker.clear_injected_rejections()


# =============================================================================
# 4. Sequence Parser & Execution Engine (Hedge-First Sequencing)
# =============================================================================

@pytest.mark.asyncio
async def test_hedge_first_margin_safety_execution(
    mock_broker: MockBrokerRouter,
    sample_iron_condor_payload: StrategySignalPayload,
):
    events_received: List[ExecutionEventMessage] = []

    async def event_collector(msg: ExecutionEventMessage):
        events_received.append(msg)

    engine = ExecutionSequenceEngine(
        broker_adapter=mock_broker,
        config=mock_broker.config,
        event_broadcaster=event_collector,
    )

    sequence = await engine.execute_signal(sample_iron_condor_payload)
    assert sequence.status == "FULLY_FILLED"
    assert sequence.completed_legs == 4
    assert sequence.failed_legs == 0
    assert sequence.circuit_breaker_triggered is False

    # Verify BUY wings executed before SELL legs
    leg_states = sequence.leg_states
    assert len(leg_states) == 4
    assert leg_states[0].action == OrderAction.BUY
    assert leg_states[1].action == OrderAction.BUY
    assert leg_states[2].action == OrderAction.SELL
    assert leg_states[3].action == OrderAction.SELL

    assert len(events_received) > 0


@pytest.mark.asyncio
async def test_exit_sequencing_closes_short_legs_first(
    mock_broker: MockBrokerRouter,
    sample_iron_condor_payload: StrategySignalPayload,
):
    # Change signal type to EXIT
    exit_payload = sample_iron_condor_payload.model_copy(
        update={"signal_type": SignalType.EXIT, "strategy_name": "EXIT_IRON_CONDOR"}
    )

    engine = ExecutionSequenceEngine(
        broker_adapter=mock_broker,
        config=mock_broker.config,
    )

    sequence = await engine.execute_signal(exit_payload)
    assert sequence.status == "FULLY_FILLED"
    assert len(sequence.leg_states) == 4

    # In exit mode: Original SELL legs bought back FIRST, original BUY legs sold SECOND
    assert sequence.leg_states[0].action == OrderAction.BUY  # Closing original short leg
    assert sequence.leg_states[1].action == OrderAction.BUY  # Closing original short leg
    assert sequence.leg_states[2].action == OrderAction.SELL  # Closing original long wing
    assert sequence.leg_states[3].action == OrderAction.SELL  # Closing original long wing


# =============================================================================
# 5. Circuit-Breaker & Rollback Tests
# =============================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_trips_on_hedge_leg_failure(
    mock_broker: MockBrokerRouter,
    sample_iron_condor_payload: StrategySignalPayload,
):
    # Inject rejection on the very first BUY hedge leg
    mock_broker.inject_rejection_for_symbol(
        sample_iron_condor_payload.legs[0].symbol,
        "Exchange margin rejection on hedge wing",
    )

    events_received: List[ExecutionEventMessage] = []

    async def event_collector(msg: ExecutionEventMessage):
        events_received.append(msg)

    engine = ExecutionSequenceEngine(
        broker_adapter=mock_broker,
        config=mock_broker.config,
        event_broadcaster=event_collector,
    )

    sequence = await engine.execute_signal(sample_iron_condor_payload)
    assert sequence.status in ("ABORTED_CIRCUIT_BREAKER", "ROLLED_BACK")
    assert sequence.circuit_breaker_triggered is True
    assert sequence.completed_legs == 0
    assert sequence.failed_legs == 1

    # Verify downstream short legs were NEVER placed
    assert len(sequence.leg_states) == 1
    assert sequence.leg_states[0].status == OrderStatus.REJECTED

    # Verify Circuit Breaker event was broadcast
    cb_events = [e for e in events_received if e.event_type == WebSocketEventType.CIRCUIT_BREAKER]
    assert len(cb_events) == 1
    assert cb_events[0].data["action"] == "DOWNSTREAM_ABORTED"


@pytest.mark.asyncio
async def test_circuit_breaker_rollback_on_partial_hedge_failure(
    mock_broker: MockBrokerRouter,
    sample_iron_condor_payload: StrategySignalPayload,
):
    # First BUY wing succeeds, second BUY wing fails
    second_buy_symbol = sample_iron_condor_payload.legs[1].symbol
    mock_broker.inject_rejection_for_symbol(second_buy_symbol, "Simulated partial hedge wing failure")

    engine = ExecutionSequenceEngine(
        broker_adapter=mock_broker,
        config=mock_broker.config,
    )

    sequence = await engine.execute_signal(sample_iron_condor_payload)
    assert sequence.status in ("ABORTED_CIRCUIT_BREAKER", "ROLLED_BACK")
    assert sequence.circuit_breaker_triggered is True

    # 2 legs attempted (leg 1 filled, leg 2 failed, downstream short legs aborted)
    assert len(sequence.leg_states) == 2
    assert sequence.leg_states[0].status == OrderStatus.COMPLETE
    assert sequence.leg_states[1].status == OrderStatus.REJECTED


# =============================================================================
# 6. Async Order Queue Manager Tests
# =============================================================================

@pytest.mark.asyncio
async def test_async_order_queue_worker(
    mock_broker: MockBrokerRouter,
    sample_iron_condor_payload: StrategySignalPayload,
):
    engine = ExecutionSequenceEngine(
        broker_adapter=mock_broker,
        config=mock_broker.config,
    )
    queue_mgr = AsyncOrderQueueManager(engine=engine)
    await queue_mgr.start()

    # Enqueue signal
    signal_id = await queue_mgr.enqueue_signal(sample_iron_condor_payload)
    assert signal_id == sample_iron_condor_payload.signal_id

    # Wait for queue worker to finish processing
    await queue_mgr.queue.join()
    await queue_mgr.stop()

    sequences = await engine.get_all_sequences()
    assert len(sequences) == 1
    assert sequences[0].status == "FULLY_FILLED"


# =============================================================================
# 7. Synthetic Tick & WebSocket Engine Tests
# =============================================================================

@pytest.mark.asyncio
async def test_synthetic_tick_generation():
    ws_manager = WebSocketConnectionManager()
    tick_gen = SyntheticTickGenerator(ws_manager=ws_manager)

    tick = await tick_gen.generate_single_tick(UnderlyingIndex.NIFTY)
    assert tick.underlying == UnderlyingIndex.NIFTY
    assert tick.spot_price > 20000.0
    assert tick.greeks is not None
    assert tick.greeks.delta > 0
    assert tick.iv > 0


@pytest.mark.asyncio
async def test_historical_tick_replay():
    replayer = HistoricalTickReplayer(speed_multiplier=5.0)
    mock_records = [
        {"symbol": "NIFTY_SPOT", "underlying": "NIFTY", "spot_price": 24200.0, "ltp": 24200.0, "iv": 0.15},
        {"symbol": "NIFTY_SPOT", "underlying": "NIFTY", "spot_price": 24210.0, "ltp": 24210.0, "iv": 0.15},
    ]
    replayed = await replayer.replay_records(mock_records)
    assert replayed == 2


# =============================================================================
# 8. FastAPI Endpoints & Ingestion Webhook Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_api_health_endpoint():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["broker_connected"] is True


@pytest.mark.asyncio
async def test_api_signal_ingest_sync_webhook(sample_iron_condor_payload: StrategySignalPayload):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload_dict = sample_iron_condor_payload.model_dump(mode="json")
        resp = await client.post("/api/v1/signals/ingest?sync=true", json=payload_dict)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert data["execution_status"] == "FULLY_FILLED"
        assert data["completed_legs"] == 4


@pytest.mark.asyncio
async def test_api_signal_ingest_async_queue_webhook(sample_iron_condor_payload: StrategySignalPayload):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload_dict = sample_iron_condor_payload.model_dump(mode="json")
        resp = await client.post("/api/v1/signals/ingest?sync=false", json=payload_dict)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "QUEUED"
        assert data["signal_id"] == sample_iron_condor_payload.signal_id


@pytest.mark.asyncio
async def test_api_signal_ingest_422_malformed_rejection():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        malformed_payload = {
            "strategy_name": "INVALID_STRATEGY",
            "underlying": "INVALID_UNDERLYING",
            "legs": [],  # Empty legs should fail validation
        }
        resp = await client.post("/api/v1/signals/ingest", json=malformed_payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "SCHEMA_VALIDATION_FAILED"
        assert "validation_errors" in data


@pytest.mark.asyncio
async def test_api_positions_funds_and_circuit_breaker_reset():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Funds
        funds_resp = await client.get("/api/v1/funds")
        assert funds_resp.status_code == 200
        assert "available_funds" in funds_resp.json()

        # Positions
        pos_resp = await client.get("/api/v1/positions")
        assert pos_resp.status_code == 200
        assert isinstance(pos_resp.json(), list)

        # Circuit Breaker Reset
        reset_resp = await client.post("/api/v1/circuit-breaker/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "SUCCESS"
