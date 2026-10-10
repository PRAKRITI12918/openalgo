"""
Emergency "Square-Off All" Risk-Control Feature Test Suite.
Verifies all 10 minimum-bar scenarios required by the Master Specification:

1. No open positions -> completes as a no-op, still produces a durable audit trail.
2. One open position -> closes correctly, position state and audit both updated.
3. Multiple positions -> all get exit orders, independent handling per symbol.
4. Failed exit order -> recorded as failed, position state untouched for that symbol, other orders unaffected.
5. Partial fill -> position quantity reduced (not zeroed), status distinguishable from full success and full failure.
6. Wrong/disconnected account (selected != active) -> blocked before any position fetch or order placement, audited as blocked attempt.
7. Duplicate/concurrent submission (double-click/resubmit) -> second request rejected with 409, never double-executed.
8. LIVE mode requested without explicit configuration -> fails closed (throws LiveTradingNotConfiguredError).
9. LIVE mode with correct configuration -> executes normally, proving legitimate live use is supported.
10. Unknown/garbage mode value -> fails closed rather than defaulting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.adapters.factory import (
    InvalidBrokerModeError,
    LiveTradingNotConfiguredError,
    create_broker_adapter,
)
from src.adapters.openalgo_mock import MockBrokerRouter
from src.core.config import BrokerMode, ExecutionConfig
from src.database.account_models import BrokerAccount, BrokerAccountStatus, db_session as account_session
from src.database.execution_db import get_square_off_audits
from src.main import create_app
from src.models.schemas import (
    LegOrderRequest,
    OrderAction,
    StrategySignalPayload,
)
from src.strategy_engine.models import (
    MarketRegime,
    OptionType,
    SignalType,
    StrategyType,
    UnderlyingIndex,
)


@pytest.fixture
def app_instance():
    """Create fresh FastAPI instance with clean state for each test."""
    return create_app()


def build_signal_for_positions(
    symbol: str,
    action: OrderAction = OrderAction.BUY,
    quantity: int = 50,
    price: float = 120.0,
) -> StrategySignalPayload:
    """Helper to generate a valid signal to seed open positions."""
    return StrategySignalPayload(
        signal_id=f"sig_{uuid.uuid4().hex[:8]}",
        strategy_name="HedgedAOS",
        strategy_type=StrategyType.IRON_CONDOR,
        signal_type=SignalType.ENTRY,
        underlying=UnderlyingIndex.NIFTY,
        regime=MarketRegime.LOW_IV_RANGING,
        timestamp=datetime.utcnow(),
        legs=[
            LegOrderRequest(
                symbol=symbol,
                underlying=UnderlyingIndex.NIFTY,
                strike=24000.0,
                option_type="CE",
                expiry="2026-10-29",
                action=action,
                quantity=quantity,
                price=price,
                is_hedge_leg=(action == OrderAction.BUY),
            )
        ],
        requires_approval=False,
    )


async def connect_test_account(
    client: AsyncClient,
    user_id: str,
    client_id: str = "CLI_101",
    label: str = "Test Account",
    status_str: str = "CONNECTED",
) -> str:
    """Helper to connect and activate an account for the given user."""
    headers = {"X-User-ID": user_id}
    res = await client.post(
        "/api/v1/accounts/connect",
        json={
            "broker_id": "mock",
            "account_label": label,
            "credentials": {"client_id": client_id},
            "make_active": True,
        },
        headers=headers,
    )
    assert res.status_code in (200, 201), f"Account connect failed: {res.text}"
    account_id = res.json().get("account_id") or res.json().get("account", {}).get("id")

    if status_str != "CONNECTED":
        session = account_session()
        try:
            acc = session.query(BrokerAccount).filter_by(id=account_id).first()
            if acc:
                acc.status = status_str
                session.commit()
        finally:
            session.close()

    return account_id


# -----------------------------------------------------------------------------
# Scenario 1: No open positions -> completes as a no-op, still produces audit trail
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_1_no_open_positions_noop_with_audit(app_instance):
    """
    Scenario 1: Account with no open positions executes as clean no-op and records audit trail.
    """
    user_id = f"user_sq1_{uuid.uuid4().hex[:6]}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Zero Pos Account")

        # 1. Step 1: Prepare
        prep_resp = await client.post(
            "/api/v1/positions/square-off/prepare",
            json={"selected_account_id": account_id},
            headers=headers,
        )
        assert prep_resp.status_code == 200
        prep_data = prep_resp.json()
        assert prep_data["status"] == "prepared"
        assert prep_data["total_positions"] == 0
        token = prep_data["confirmation_token"]

        # 2. Step 2: Execute
        exec_resp = await client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token, "confirm_phrase": "CONFIRM", "selected_account_id": account_id},
            headers=headers,
        )
        assert exec_resp.status_code == 200
        exec_data = exec_resp.json()
        assert exec_data["status"] == "no_op"
        assert exec_data["total_positions"] == 0
        assert exec_data["filled_count"] == 0
        assert "No open positions" in exec_data["message"]

        # 3. Verify Durable Audit Trail
        audits = get_square_off_audits(account_id=account_id)
        assert len(audits) >= 2  # 1 prepare, 1 execute no-op
        noop_audit = next(a for a in audits if a.action_type == "EXECUTE")
        assert noop_audit.status == "NO_OP"


# -----------------------------------------------------------------------------
# Scenario 2: One open position -> closes correctly, state and audit both updated
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_2_one_open_position_closes_correctly_and_audited(app_instance):
    """
    Scenario 2: Single open position is liquidated accurately and state + audit are updated.
    """
    user_id = f"user_sq2_{uuid.uuid4().hex[:6]}"
    sym = f"NIFTY_OPT_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Single Pos Acc")

        # Seed 1 open position (BUY 50 units)
        sig = build_signal_for_positions(symbol=sym, action=OrderAction.BUY, quantity=50)
        seed_resp = await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sig.model_dump(mode="json"),
            headers=headers,
        )
        assert seed_resp.status_code == 202

        # Verify open position exists
        pos_check = await client.get("/api/v1/positions", headers=headers)
        assert len(pos_check.json()) > 0

        # Step 1: Prepare
        prep_resp = await client.post(
            "/api/v1/positions/square-off/prepare",
            json={"selected_account_id": account_id},
            headers=headers,
        )
        assert prep_resp.status_code == 200
        prep_data = prep_resp.json()
        assert prep_data["total_positions"] == 1
        assert prep_data["open_positions"][0]["symbol"] == sym
        assert prep_data["open_positions"][0]["exit_action"] == "SELL"
        assert prep_data["open_positions"][0]["exit_quantity"] == 50
        token = prep_data["confirmation_token"]

        # Step 2: Execute
        exec_resp = await client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token, "confirm_phrase": "CONFIRM", "selected_account_id": account_id},
            headers=headers,
        )
        assert exec_resp.status_code == 200
        exec_data = exec_resp.json()
        assert exec_data["status"] == "success"
        assert exec_data["filled_count"] == 1
        assert exec_data["failed_count"] == 0
        assert exec_data["results"][0]["symbol"] == sym
        assert exec_data["results"][0]["status"] == "FILLED"
        assert exec_data["results"][0]["filled_quantity"] == 50

        # Verify Positions are now flat
        pos_after = await client.get("/api/v1/positions", headers=headers)
        assert pos_after.json() == []

        # Verify Audit Record
        audits = get_square_off_audits(account_id=account_id)
        exec_audit = next(a for a in audits if a.action_type == "EXECUTE")
        assert exec_audit.status == "SUCCESS"
        assert exec_audit.filled_positions == 1


# -----------------------------------------------------------------------------
# Scenario 3: Multiple positions -> all get exit orders, independent handling
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_3_multiple_positions_independent_handling(app_instance):
    """
    Scenario 3: Multiple open positions across symbols are processed independently.
    """
    user_id = f"user_sq3_{uuid.uuid4().hex[:6]}"
    sym1 = f"NIFTY_CE_{uuid.uuid4().hex[:4].upper()}"
    sym2 = f"NIFTY_PE_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Multi Pos Acc")

        # Seed 2 positions
        sig1 = build_signal_for_positions(symbol=sym1, action=OrderAction.BUY, quantity=75)
        sig2 = build_signal_for_positions(symbol=sym2, action=OrderAction.SELL, quantity=50)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig1.model_dump(mode="json"), headers=headers)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig2.model_dump(mode="json"), headers=headers)

        # Prepare
        prep = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
        assert prep.status_code == 200
        token = prep.json()["confirmation_token"]
        assert prep.json()["total_positions"] == 2

        # Execute
        exec_resp = await client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token, "confirm_phrase": "CONFIRM"},
            headers=headers,
        )
        assert exec_resp.status_code == 200
        res = exec_resp.json()
        assert res["status"] == "success"
        assert res["total_positions"] == 2
        assert res["filled_count"] == 2

        # Positions are flat
        pos_after = await client.get("/api/v1/positions", headers=headers)
        assert pos_after.json() == []


# -----------------------------------------------------------------------------
# Scenario 4: Failed exit order -> recorded as failed, position untouched, batch continues
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_4_failed_exit_order_safe_handling(app_instance):
    """
    Scenario 4: One exit order failure does NOT crash the batch or corrupt state.
    The failed position remains untouched while others fill.
    """
    user_id = f"user_sq4_{uuid.uuid4().hex[:6]}"
    sym_fail = f"SYM_FAIL_{uuid.uuid4().hex[:4].upper()}"
    sym_ok = f"SYM_OK_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Fail Test Acc")

        # Seed 2 positions
        sig1 = build_signal_for_positions(symbol=sym_fail, action=OrderAction.BUY, quantity=100)
        sig2 = build_signal_for_positions(symbol=sym_ok, action=OrderAction.BUY, quantity=100)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig1.model_dump(mode="json"), headers=headers)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig2.model_dump(mode="json"), headers=headers)

        # Inject failure specifically for sym_fail
        broker: MockBrokerRouter = app_instance.state.broker_adapter
        broker.inject_rejection_for_symbol(sym_fail, "Simulated exchange risk rejection")

        try:
            # Prepare
            prep = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
            token = prep.json()["confirmation_token"]

            # Execute
            exec_resp = await client.post(
                "/api/v1/positions/square-off/execute",
                json={"confirmation_token": token, "confirm_phrase": "CONFIRM"},
                headers=headers,
            )
            assert exec_resp.status_code == 200
            data = exec_resp.json()

            # Status is partial_success
            assert data["status"] == "partial_success"
            assert data["filled_count"] == 1
            assert data["failed_count"] == 1

            # Check individual order outcomes
            fail_order = next(r for r in data["results"] if r["symbol"] == sym_fail)
            ok_order = next(r for r in data["results"] if r["symbol"] == sym_ok)
            assert fail_order["status"] == "FAILED"
            assert "Simulated exchange risk rejection" in fail_order["error"]
            assert ok_order["status"] == "FILLED"

            # Check positions: sym_ok is closed, sym_fail is still untouched (100 units open)
            positions = await client.get("/api/v1/positions", headers=headers)
            active_symbols = [leg["symbol"] for p in positions.json() for leg in p["legs"]]
            assert sym_fail in active_symbols
            assert sym_ok not in active_symbols

        finally:
            broker.clear_injected_rejections()


# -----------------------------------------------------------------------------
# Scenario 5: Partial fill -> position quantity reduced (not zeroed), distinguishable status
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_5_partial_fill_reduces_position(app_instance):
    """
    Scenario 5: Partial fills reduce the position quantity rather than zeroing it.
    Status is distinguishable from full success and full failure.
    """
    user_id = f"user_sq5_{uuid.uuid4().hex[:6]}"
    sym = f"SYM_PARTIAL_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Partial Fill Acc")

        # Seed 100 units position
        sig = build_signal_for_positions(symbol=sym, action=OrderAction.BUY, quantity=100)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig.model_dump(mode="json"), headers=headers)

        broker: MockBrokerRouter = app_instance.state.broker_adapter
        # Inject partial fill of 40 units out of 100
        broker.inject_partial_fill_for_symbol(sym, 40)

        try:
            prep = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
            token = prep.json()["confirmation_token"]

            exec_resp = await client.post(
                "/api/v1/positions/square-off/execute",
                json={"confirmation_token": token, "confirm_phrase": "CONFIRM"},
                headers=headers,
            )
            assert exec_resp.status_code == 200
            data = exec_resp.json()

            # Status is partial_success (distinguishable from success and failed)
            assert data["status"] == "partial_success"
            assert data["partial_count"] == 1
            assert data["filled_count"] == 0

            item = data["results"][0]
            assert item["status"] == "PARTIAL"
            assert item["filled_quantity"] == 40
            assert item["requested_quantity"] == 100

            # Position quantity must be reduced from 100 to 60 (NOT zeroed)
            pos_resp = await client.get("/api/v1/positions", headers=headers)
            legs = [leg for p in pos_resp.json() for leg in p["legs"] if leg["symbol"] == sym]
            assert len(legs) == 1
            assert legs[0]["quantity"] == 60

        finally:
            broker.clear_injected_rejections()


# -----------------------------------------------------------------------------
# Scenario 6: Wrong/disconnected account -> blocked before position fetch, audited
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_6_wrong_or_disconnected_account_blocked(app_instance):
    """
    Scenario 6: Account mismatch is checked FIRST before any I/O or position fetching.
    Operation is blocked, audited as a blocked attempt, and no state changes occur.
    """
    user_id = f"user_sq6_{uuid.uuid4().hex[:6]}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        real_acc_id = await connect_test_account(client, user_id=user_id, label="Real Active Acc")

        # 1. UI passes non-matching account ID
        bad_acc_id = f"acc_wrong_{uuid.uuid4().hex[:6]}"
        prep_resp = await client.post(
            "/api/v1/positions/square-off/prepare",
            json={"selected_account_id": bad_acc_id},
            headers=headers,
        )
        assert prep_resp.status_code == 400
        assert "ACCOUNT_MISMATCH" in prep_resp.json()["detail"]

        # Verify blocked attempt is audited
        audits = get_square_off_audits(account_id=bad_acc_id)
        assert any(a.action_type == "BLOCKED" and a.status == "BLOCKED" for a in audits)

        # 2. Account disconnected / token expired
        user_dis = f"user_dis_{uuid.uuid4().hex[:6]}"
        dis_headers = {"X-User-ID": user_dis}
        dis_acc_id = await connect_test_account(
            client,
            user_id=user_dis,
            label="Expired Acc",
            status_str=BrokerAccountStatus.TOKEN_EXPIRED.value,
        )

        dis_resp = await client.post(
            "/api/v1/positions/square-off/prepare",
            json={"selected_account_id": dis_acc_id},
            headers=dis_headers,
        )
        assert dis_resp.status_code == 401
        assert "TOKEN_EXPIRED" in dis_resp.json()["detail"]


# -----------------------------------------------------------------------------
# Scenario 7: Duplicate/concurrent submission -> rejected, never double-executed
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_7_duplicate_and_concurrent_submission_guard(app_instance):
    """
    Scenario 7: Prevents duplicate execution via single-use token and in-flight lock.
    """
    user_id = f"user_sq7_{uuid.uuid4().hex[:6]}"
    sym = f"SYM_DUP_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Dup Test Acc")

        # Seed 1 position
        sig = build_signal_for_positions(symbol=sym, action=OrderAction.BUY, quantity=50)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig.model_dump(mode="json"), headers=headers)

        # Prepare
        prep = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
        token = prep.json()["confirmation_token"]

        # Execution 1: Succeeds
        res1 = await client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token, "confirm_phrase": "CONFIRM"},
            headers=headers,
        )
        assert res1.status_code == 200
        assert res1.json()["status"] == "success"

        # Execution 2: Resubmission with same single-use token -> 409 Conflict
        res2 = await client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token, "confirm_phrase": "CONFIRM"},
            headers=headers,
        )
        assert res2.status_code == 409
        assert "TOKEN_ALREADY_USED" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_scenario_7b_in_flight_concurrent_race_protection(app_instance):
    """
    Scenario 7b: Two concurrent square-off executions for the same account race.
    Exactly one acquires the in-flight lock, while the other is rejected with 409 Conflict (SQUARE_OFF_IN_PROGRESS).
    """
    user_id = f"user_sq7b_{uuid.uuid4().hex[:6]}"
    sym = f"SYM_RACE_{uuid.uuid4().hex[:4].upper()}"
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        headers = {"X-User-ID": user_id}
        account_id = await connect_test_account(client, user_id=user_id, label="Race Acc")

        # Seed 1 position
        sig = build_signal_for_positions(symbol=sym, action=OrderAction.BUY, quantity=100)
        await client.post("/api/v1/signals/ingest?sync=true", json=sig.model_dump(mode="json"), headers=headers)

        # Prepare two tokens for the account
        prep1 = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
        token1 = prep1.json()["confirmation_token"]
        prep2 = await client.post("/api/v1/positions/square-off/prepare", headers=headers)
        token2 = prep2.json()["confirmation_token"]

        # Send simultaneous execute requests
        task1 = client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token1, "confirm_phrase": "CONFIRM"},
            headers=headers,
        )
        task2 = client.post(
            "/api/v1/positions/square-off/execute",
            json={"confirmation_token": token2, "confirm_phrase": "CONFIRM"},
            headers=headers,
        )
        r1, r2 = await asyncio.gather(task1, task2)

        statuses = {r1.status_code, r2.status_code}
        assert 200 in statuses
        assert 409 in statuses

        conflict_res = r1 if r1.status_code == 409 else r2
        detail = conflict_res.json()["detail"]
        assert "SQUARE_OFF_IN_PROGRESS" in detail or "TOKEN_ALREADY_USED" in detail


# -----------------------------------------------------------------------------
# Scenario 8: LIVE mode without explicit configuration -> fails closed
# -----------------------------------------------------------------------------
def test_scenario_8_live_mode_without_explicit_config_fails_closed():
    """
    Scenario 8: Constructing the LIVE execution path without explicit configuration throws.
    Proves no silent fallback or unconfigured real-money path can be created.
    """
    cfg = ExecutionConfig(
        broker_mode="LIVE",
        live_trading_enabled=False,  # Default or unconfigured
    )

    with pytest.raises(LiveTradingNotConfiguredError) as exc_info:
        create_broker_adapter(mode="LIVE", config=cfg)

    assert "live_trading_enabled=True" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Scenario 9: LIVE mode with correct configuration -> executes normally
# -----------------------------------------------------------------------------
def test_scenario_9_live_mode_with_correct_configuration_allowed():
    """
    Scenario 9: Constructing the LIVE execution path with explicit live_trading_enabled=True
    and validated credentials succeeds, proving legitimate live trading is unblocked.
    """
    cfg = ExecutionConfig(
        broker_mode="LIVE",
        live_trading_enabled=True,
        openalgo_api_key="valid_production_api_key",
    )

    mock_client = MagicMock()
    adapter = create_broker_adapter(mode="LIVE", config=cfg, openalgo_client=mock_client)
    assert adapter is not None
    assert adapter.mode == "LIVE"


# -----------------------------------------------------------------------------
# Scenario 10: Unknown/garbage mode value -> fails closed rather than defaulting
# -----------------------------------------------------------------------------
def test_scenario_10_unknown_garbage_mode_fails_closed():
    """
    Scenario 10: Any unrecognized mode string fails closed immediately.
    Never silently defaults to MOCK, LIVE, or any other mode.
    """
    # Test factory directly with garbage string
    with pytest.raises(InvalidBrokerModeError) as exc_info:
        create_broker_adapter(mode="SUPER_UNKNOWN_BROKER_MODE_XYZ")

    assert "Invalid broker execution mode" in str(exc_info.value)

    # Test configuration normalization directly
    with pytest.raises(ValueError) as cfg_exc:
        ExecutionConfig(broker_mode="GARBAGE_MODE")

    assert "Unrecognized broker mode" in str(cfg_exc.value)
