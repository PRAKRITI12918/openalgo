"""
Comprehensive Unit & Integration Test Suite for Mock Execution Engine.
Tests simulated order lifecycles, hedge-before-short dependency gating,
deterministic fault injection, position tracking, P&L calculations,
defense-in-depth domain rejection, and duplicate execution guards.
"""

from __future__ import annotations

from datetime import datetime
import json
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from services.execution.mock_execution_engine import (
    FaultInjector,
    MockExecutionEngine,
    MockPriceProvider,
    SimulatedBrokerClient,
)
from src.database.execution_db import (
    MockExecutionEventRecord,
    MockPositionRecord,
    db_session,
    get_all_positions,
    get_events_for_signal,
    init_execution_db,
)
from src.database.signals_db import (
    get_signal_by_id,
    init_signals_db,
    insert_signal_record,
)
from src.engine.signal_state_machine import InvalidStateTransitionError
from src.main import create_app
from src.models.signal_schema import (
    MockOrderStatus,
    SignalAction,
    SignalIngestPayload,
    SignalInstrumentType,
    SignalOrderType,
    SignalStatus,
)


@pytest.fixture(autouse=True)
def init_db():
    """Ensure DB tables are initialized and cleaned before each test."""
    init_signals_db()
    init_execution_db()
    session = db_session()
    try:
        session.query(MockPositionRecord).delete()
        session.query(MockExecutionEventRecord).delete()
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def test_app():
    return create_app()


def build_test_signal_record(
    strategy_name: str = "TEST_STRATEGY",
    underlying: str = "RELIANCE",
    instrument: str = "EQUITY",
    action: str = "BUY",
    quantity: int = 10,
    order_type: str = "MARKET",
    price: float = 2500.0,
    legs: list | None = None,
) -> dict:
    """Helper to construct and insert a validated SignalRecord for testing."""
    signal_id = f"sig_{uuid.uuid4().hex}"
    idemp_key = f"idemp_{uuid.uuid4().hex}"
    now = datetime.utcnow()

    payload_dict = {
        "signal_id": signal_id,
        "strategy_name": strategy_name,
        "underlying": underlying,
        "instrument": instrument,
        "action": action,
        "quantity": quantity,
        "order_type": order_type,
        "price": price,
        "execution_sequence": 1,
        "signal_timestamp": now.isoformat(),
        "idempotency_key": idemp_key,
    }
    if legs:
        payload_dict["legs"] = legs

    record_data = {
        "signal_id": signal_id,
        "idempotency_key": idemp_key,
        "strategy_name": strategy_name,
        "underlying": underlying,
        "instrument": instrument,
        "action": action,
        "quantity": quantity,
        "order_type": order_type,
        "price": price,
        "trigger_price": None,
        "execution_sequence": 1,
        "status": SignalStatus.VALIDATED.value,
        "strike": None,
        "expiry": None,
        "option_type": None,
        "legs_json": json.dumps(legs) if legs else None,
        "metadata_json": None,
        "payload_json": json.dumps(payload_dict),
        "status_history_json": json.dumps([{"status": "VALIDATED", "timestamp": now.isoformat(), "actor": "system", "reason": "Init"}]),
        "created_at": now,
        "updated_at": now,
    }
    rec, _ = insert_signal_record(record_data)
    return rec


# =============================================================================
# 14.a Single-Leg Order Lifecycle, Position & PnL
# =============================================================================

@pytest.mark.asyncio
async def test_single_leg_order_lifecycle_position_pnl():
    """
    Test 14.a: Single-leg order progresses PENDING -> OPEN -> FILLED.
    Verifies simulated position creation and P&L computation.
    """
    strat = f"EQUITY_MOM_{uuid.uuid4().hex[:8]}"
    record = build_test_signal_record(
        strategy_name=strat,
        underlying="RELIANCE",
        instrument="EQUITY",
        action="BUY",
        quantity=10,
        order_type="MARKET",
        price=2500.0,
    )

    price_provider = MockPriceProvider(reference_prices={"RELIANCE": 2500.0})
    engine = MockExecutionEngine(price_provider=price_provider)

    result = await engine.execute_signal(signal=record)

    assert result.status == SignalStatus.COMPLETED
    assert result.total_legs == 1
    assert result.filled_legs == 1
    assert result.failed_legs == 0

    leg_res = result.leg_executions[0]
    assert leg_res.status == MockOrderStatus.FILLED
    assert leg_res.filled_quantity == 10
    assert leg_res.fill_price == 2500.0
    assert leg_res.order_id.startswith("MOCK-ORD-")
    assert leg_res.is_mock is True

    # Verify events recorded
    events = get_events_for_signal(record.signal_id)
    event_types = [e.event_type for e in events]
    assert "SIGNAL_EXECUTING" in event_types
    assert "ORDER_CREATED" in event_types
    assert "ORDER_OPENED" in event_types
    assert "ORDER_FILLED" in event_types
    assert "POSITION_UPDATED" in event_types
    assert "SIGNAL_COMPLETED" in event_types

    # Verify simulated position
    positions = get_all_positions(strategy_name=strat)
    matching = [p for p in positions if p.symbol == "RELIANCE"]
    assert len(matching) == 1
    pos = matching[0]
    assert pos.quantity == 10
    assert pos.average_price == 2500.0
    assert pos.is_open is True


# =============================================================================
# 14.b Multi-Leg Sequential Order Execution
# =============================================================================

@pytest.mark.asyncio
async def test_multi_leg_sequential_execution_and_positions():
    """
    Test 14.b: Multi-leg order across sequential execution_sequence values (1, 2)
    Verifies all legs processed in correct sequence, final positions correct across legs.
    """
    strat = f"BULL_CALL_{uuid.uuid4().hex[:8]}"
    legs = [
        {
            "leg_id": "leg_1_call_buy",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "BUY",
            "quantity": 25,
            "order_type": "LIMIT",
            "price": 120.0,
            "strike": 24000.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 1,
        },
        {
            "leg_id": "leg_2_call_sell",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "SELL",
            "quantity": 25,
            "order_type": "LIMIT",
            "price": 45.0,
            "strike": 24300.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 2,
        },
    ]

    record = build_test_signal_record(
        strategy_name=strat,
        underlying="NIFTY",
        instrument="OPTION",
        action="BUY",
        quantity=25,
        legs=legs,
    )

    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record)

    assert result.status == SignalStatus.COMPLETED
    assert result.total_legs == 2
    assert result.filled_legs == 2

    # Check order of execution matches execution_sequence
    assert result.leg_executions[0].leg_id == "leg_1_call_buy"
    assert result.leg_executions[0].execution_sequence == 1
    assert result.leg_executions[0].fill_price == 120.0

    assert result.leg_executions[1].leg_id == "leg_2_call_sell"
    assert result.leg_executions[1].execution_sequence == 2
    assert result.leg_executions[1].fill_price == 45.0

    # Verify positions
    positions = get_all_positions(strategy_name=strat)
    pos_map = {p.symbol: p for p in positions}

    long_call = pos_map["NIFTY-2026-09-25-24000-CE"]
    assert long_call.quantity == 25
    assert long_call.average_price == 120.0

    short_call = pos_map["NIFTY-2026-09-25-24300-CE"]
    assert short_call.quantity == -25
    assert short_call.average_price == 45.0


# =============================================================================
# 14.c Hedge-Before-Short Ordering
# =============================================================================

@pytest.mark.asyncio
async def test_hedge_before_short_ordering_success():
    """
    Test 14.c (Happy path):
    Hedge leg must reach FILLED before the dependent short SELL leg is sent.
    """
    legs = [
        # Dependent SELL leg listed first in raw list
        {
            "leg_id": "short_leg_sell",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "SELL",
            "quantity": 25,
            "order_type": "MARKET",
            "price": 80.0,
            "strike": 24200.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 1,
            "leg_role": "PRIMARY",
            "depends_on_leg_id": "hedge_leg_buy",
        },
        # Hedge BUY leg
        {
            "leg_id": "hedge_leg_buy",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "BUY",
            "quantity": 25,
            "order_type": "MARKET",
            "price": 20.0,
            "strike": 24500.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 1,
            "leg_role": "HEDGE",
        },
    ]

    record = build_test_signal_record(
        strategy_name="HEDGED_SHORT_CALL",
        underlying="NIFTY",
        instrument="OPTION",
        action="SELL",
        quantity=25,
        legs=legs,
    )

    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record)

    assert result.status == SignalStatus.COMPLETED
    assert result.filled_legs == 2

    # Verify hedge executed first
    exec_order = [l.leg_id for l in result.leg_executions]
    assert exec_order == ["hedge_leg_buy", "short_leg_sell"]


@pytest.mark.asyncio
async def test_hedge_before_short_aborts_short_if_hedge_fails():
    """
    Test 14.c (Failure path):
    If the hedge leg fails or is rejected, the dependent short leg must NEVER be sent
    and must be recorded as CANCELLED with a causal reason.
    """
    legs = [
        {
            "leg_id": "short_leg_sell",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "SELL",
            "quantity": 25,
            "order_type": "MARKET",
            "price": 80.0,
            "strike": 24200.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 1,
            "leg_role": "PRIMARY",
            "depends_on_leg_id": "hedge_leg_buy",
        },
        {
            "leg_id": "hedge_leg_buy",
            "underlying": "NIFTY",
            "instrument": "OPTION",
            "action": "BUY",
            "quantity": 25,
            "order_type": "MARKET",
            "price": 20.0,
            "strike": 24500.0,
            "expiry": "2026-09-25",
            "option_type": "CE",
            "execution_sequence": 1,
            "leg_role": "HEDGE",
        },
    ]

    record = build_test_signal_record(
        strategy_name="HEDGED_SHORT_FAIL_SAFE",
        underlying="NIFTY",
        instrument="OPTION",
        action="SELL",
        quantity=25,
        legs=legs,
    )

    # Inject failure into the hedge leg
    faults = FaultInjector(fail_legs={"hedge_leg_buy"})
    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record, fault_injector=faults)

    assert result.status == SignalStatus.FAILED
    assert result.filled_legs == 0
    assert result.failed_legs == 1
    assert result.cancelled_legs == 1

    # Check that short leg was cancelled, never sent
    short_res = next(l for l in result.leg_executions if l.leg_id == "short_leg_sell")
    assert short_res.status == MockOrderStatus.CANCELLED
    assert "Hedge prerequisite" in short_res.failure_reason
    assert "skipping dependent SELL leg" in short_res.failure_reason

    # Verify no naked short position was created
    positions = get_all_positions(strategy_name="HEDGED_SHORT_FAIL_SAFE")
    assert len(positions) == 0


# =============================================================================
# 14.d Failed Leg via Fault Injector
# =============================================================================

@pytest.mark.asyncio
async def test_failed_leg_cancels_downstream_sequence():
    """
    Test 14.d:
    Force one leg to FAILED via fault injector;
    verify dependent downstream legs are CANCELLED (not sent),
    signal status becomes FAILED, and execution events show the causal reason.
    """
    legs = [
        {
            "leg_id": "leg_1_ok",
            "underlying": "NIFTY",
            "instrument": "FUTURE",
            "action": "BUY",
            "quantity": 25,
            "order_type": "MARKET",
            "execution_sequence": 1,
        },
        {
            "leg_id": "leg_2_fault",
            "underlying": "NIFTY",
            "instrument": "FUTURE",
            "action": "BUY",
            "quantity": 25,
            "order_type": "MARKET",
            "execution_sequence": 1,
        },
        {
            "leg_id": "leg_3_downstream",
            "underlying": "NIFTY",
            "instrument": "FUTURE",
            "action": "SELL",
            "quantity": 50,
            "order_type": "MARKET",
            "execution_sequence": 2,
        },
    ]

    record = build_test_signal_record(
        strategy_name="DOWNSTREAM_HALT_TEST",
        underlying="NIFTY",
        instrument="FUTURE",
        action="BUY",
        quantity=25,
        legs=legs,
    )

    # Force leg_2_fault to fail
    faults = FaultInjector(fail_legs={"leg_2_fault"})
    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record, fault_injector=faults)

    assert result.status == SignalStatus.FAILED
    assert result.filled_legs == 1
    assert result.failed_legs == 1
    assert result.cancelled_legs == 1

    leg_map = {l.leg_id: l for l in result.leg_executions}
    assert leg_map["leg_1_ok"].status == MockOrderStatus.FILLED
    assert leg_map["leg_2_fault"].status == MockOrderStatus.FAILED
    assert leg_map["leg_3_downstream"].status == MockOrderStatus.CANCELLED
    assert "upstream sequence failure" in leg_map["leg_3_downstream"].failure_reason


# =============================================================================
# 14.e Duplicate Signal Execution Guard
# =============================================================================

@pytest.mark.asyncio
async def test_duplicate_signal_execution_guard():
    """
    Test 14.e:
    Attempting to execute the same signal twice (already EXECUTING or COMPLETED)
    must reject/no-op and not double-execute or double-update positions.
    """
    strat = f"DUP_GUARD_{uuid.uuid4().hex[:8]}"
    record = build_test_signal_record(
        strategy_name=strat,
        underlying="RELIANCE",
        instrument="EQUITY",
        action="BUY",
        quantity=10,
    )

    engine = MockExecutionEngine()
    # 1st execution: succeeds
    res1 = await engine.execute_signal(signal=record)
    assert res1.status == SignalStatus.COMPLETED

    # Check position quantity after first run
    pos1 = get_all_positions(strategy_name=strat)
    assert len(pos1) == 1
    assert pos1[0].quantity == 10

    # 2nd execution: state machine guard raises InvalidStateTransitionError
    refreshed_rec = get_signal_by_id(record.signal_id)
    with pytest.raises(InvalidStateTransitionError):
        await engine.execute_signal(signal=refreshed_rec)

    # Verify positions did NOT double to 20!
    pos2 = get_all_positions(strategy_name=strat)
    assert len(pos2) == 1
    assert pos2[0].quantity == 10


# =============================================================================
# 14.f Invalid Quantity Rejected at Engine Level
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_quantity_rejected_at_engine_level():
    """
    Test 14.f:
    A leg with non-positive/lot-size-violating quantity is REJECTED at engine level
    (defense-in-depth) without crashing the batch; sibling independent legs still process.
    """
    legs = [
        {
            "leg_id": "valid_sibling_leg",
            "underlying": "NIFTY",
            "instrument": "FUTURE",
            "action": "BUY",
            "quantity": 25,  # Valid multiple of 25
            "order_type": "MARKET",
            "execution_sequence": 1,
            "is_optional": True,
        },
        {
            "leg_id": "invalid_qty_leg",
            "underlying": "NIFTY",
            "instrument": "FUTURE",
            "action": "BUY",
            "quantity": 13,  # Invalid: not a multiple of 25!
            "order_type": "MARKET",
            "execution_sequence": 1,
            "is_optional": True,
        },
    ]

    record = build_test_signal_record(
        strategy_name="DEFENSE_IN_DEPTH_QTY",
        underlying="NIFTY",
        instrument="FUTURE",
        action="BUY",
        quantity=25,
        legs=legs,
    )

    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record)

    leg_map = {l.leg_id: l for l in result.leg_executions}
    # Sibling valid leg succeeded
    assert leg_map["valid_sibling_leg"].status == MockOrderStatus.FILLED
    assert leg_map["valid_sibling_leg"].filled_quantity == 25

    # Invalid qty leg was cleanly rejected
    assert leg_map["invalid_qty_leg"].status == MockOrderStatus.REJECTED
    assert "multiple of lot size" in leg_map["invalid_qty_leg"].failure_reason


# =============================================================================
# 14.g Invalid Instrument Rejected at Engine Level
# =============================================================================

@pytest.mark.asyncio
async def test_invalid_instrument_rejected_at_engine_level():
    """
    Test 14.g:
    Invalid instrument string is REJECTED cleanly with a clear reason recorded,
    no partial or corrupt state left behind.
    """
    legs = [
        {
            "leg_id": "bad_instrument_leg",
            "underlying": "GOLD",
            "instrument": "COMMODITY_UNSUPPORTED",
            "action": "BUY",
            "quantity": 10,
            "order_type": "MARKET",
            "execution_sequence": 1,
        }
    ]

    record = build_test_signal_record(
        strategy_name="DEFENSE_IN_DEPTH_INST",
        underlying="GOLD",
        instrument="COMMODITY_UNSUPPORTED",
        action="BUY",
        quantity=10,
        legs=legs,
    )

    engine = MockExecutionEngine()
    result = await engine.execute_signal(signal=record)

    assert result.status == SignalStatus.FAILED
    assert result.leg_executions[0].status == MockOrderStatus.REJECTED
    assert "Invalid instrument type" in result.leg_executions[0].failure_reason

    # No corrupt positions created
    positions = get_all_positions(strategy_name="DEFENSE_IN_DEPTH_INST")
    assert len(positions) == 0


# =============================================================================
# P&L Calculation: Closing & Reducing Positions
# =============================================================================

@pytest.mark.asyncio
async def test_realized_pnl_on_closing_and_flipping_positions():
    """
    Tests exact position accounting and realized P&L:
    1. BUY 10 @ 2000 -> Long 10 @ 2000
    2. SELL 6 @ 2200 -> Realized PnL = 6 * (2200 - 2000) = +1200.0, Remaining Long 4 @ 2000
    3. SELL 8 @ 2100 -> Closes remaining 4 (Realized = 4 * 100 = +400.0), opens Short 4 @ 2100
    """
    price_provider = MockPriceProvider()
    engine = MockExecutionEngine(price_provider=price_provider)

    strat = f"PNL_ACC_{uuid.uuid4().hex[:8]}"
    # Step 1: Long 10 @ 2000
    rec1 = build_test_signal_record(strategy_name=strat, underlying="TCS", instrument="EQUITY", action="BUY", quantity=10, price=2000.0)
    res1 = await engine.execute_signal(signal=rec1)
    assert res1.total_realized_pnl == 0.0

    pos1 = get_all_positions(strategy_name=strat)[0]
    assert pos1.quantity == 10
    assert pos1.average_price == 2000.0
    assert pos1.realized_pnl == 0.0

    # Step 2: Sell 6 @ 2200
    rec2 = build_test_signal_record(strategy_name=strat, underlying="TCS", instrument="EQUITY", action="SELL", quantity=6, price=2200.0)
    res2 = await engine.execute_signal(signal=rec2)
    assert res2.total_realized_pnl == 1200.0

    pos2 = get_all_positions(strategy_name=strat)[0]
    assert pos2.quantity == 4
    assert pos2.average_price == 2000.0
    assert pos2.realized_pnl == 1200.0

    # Step 3: Sell 8 @ 2100 (Closes 4, Flips to Short 4)
    rec3 = build_test_signal_record(strategy_name=strat, underlying="TCS", instrument="EQUITY", action="SELL", quantity=8, price=2100.0)
    res3 = await engine.execute_signal(signal=rec3)
    assert res3.total_realized_pnl == 400.0  # Realized on this order

    pos3 = get_all_positions(strategy_name=strat)[0]
    assert pos3.quantity == -4
    assert pos3.average_price == 2100.0
    assert pos3.realized_pnl == 1600.0  # Cumulative realized PnL: 1200 + 400


# =============================================================================
# REST API Ingestion-to-Execution Flow Tests
# =============================================================================

@pytest.mark.asyncio
async def test_rest_api_ingest_and_execute_pipeline(test_app):
    """
    Tests end-to-end flow through the REST API:
    POST /api/v1/signals -> 201 Created (VALIDATED)
    POST /api/v1/signals/{signal_id}/execute -> 200 OK (COMPLETED)
    GET /api/v1/signals/{signal_id}/events -> Audit trail of events
    GET /api/v1/mock/positions -> Returns simulated position
    """
    strat = f"API_PIPELINE_{uuid.uuid4().hex[:8]}"
    signal_payload = {
        "strategy_name": strat,
        "underlying": "INFY",
        "instrument": "EQUITY",
        "action": "BUY",
        "quantity": 50,
        "order_type": "MARKET",
        "execution_sequence": 1,
        "signal_timestamp": "2026-09-24T12:00:00Z",
        "idempotency_key": f"test-e2e-exec-{uuid.uuid4().hex[:8]}",
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Ingest signal
        ingest_resp = await client.post("/api/v1/signals", json=signal_payload)
        assert ingest_resp.status_code == 201
        sig_id = ingest_resp.json()["signal_id"]

        # 2. Execute via REST endpoint
        exec_resp = await client.post(f"/api/v1/signals/{sig_id}/execute")
        assert exec_resp.status_code == 200
        exec_data = exec_resp.json()
        assert exec_data["status"] == "COMPLETED"
        assert exec_data["filled_legs"] == 1

        # 3. Query execution events
        events_resp = await client.get(f"/api/v1/signals/{sig_id}/events")
        assert events_resp.status_code == 200
        events_data = events_resp.json()
        assert events_data["count"] >= 5
        event_names = [e["event_type"] for e in events_data["events"]]
        assert "SIGNAL_EXECUTING" in event_names
        assert "ORDER_CREATED" in event_names
        assert "ORDER_OPENED" in event_names
        assert "ORDER_FILLED" in event_names
        assert "SIGNAL_COMPLETED" in event_names

        # 4. Query mock positions endpoint
        pos_resp = await client.get("/api/v1/mock/positions", params={"strategy_name": strat})
        assert pos_resp.status_code == 200
        positions = pos_resp.json()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "INFY"
        assert positions[0]["net_quantity"] == 50
