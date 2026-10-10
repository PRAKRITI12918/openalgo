"""
Unit & Integration Test Suite for Multi-Account Broker Switching & Authorization.
Covers all 10 mandated scenarios (a) through (j):
  (a) Connect account -> BrokerAccount created, CONNECTED, appears in GET /api/v1/accounts.
  (b) Switch account (no open positions) -> succeeds immediately, pointer updated.
  (c) Switch account with open positions -> requires confirmation (409), proceeds only with confirm=true.
  (d) Positions query -> returns only active account positions; second account not included.
  (e) Orders query -> isolated to active account.
  (f) Switch back -> pointer updates and data reflects original account without residue.
  (g) Token expiration -> status transitions to TOKEN_EXPIRED, order placement rejected.
  (h) Disconnected account -> activation rejected; disconnecting active clears active selection.
  (i) Cross-User Authorization Bypass (Security) -> User A accessing User B's account is rejected (404).
  (j) Order-Routing Mismatch -> Request with mismatched account_id is rejected with ACCOUNT_MISMATCH.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.database.account_models import BrokerAccount, BrokerAccountStatus
from src.main import create_app
from src.models.schemas import LegOrderRequest, OrderAction, OrderType, StrategySignalPayload
from src.strategy_engine.models import MarketRegime, OptionType, SignalType, StrategyType, UnderlyingIndex


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def sample_payload() -> StrategySignalPayload:
    legs = [
        LegOrderRequest(
            symbol="NIFTY26AUG24000CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000.0,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=50,
            order_type=OrderType.MARKET,
            price=50.0,
            is_hedge_leg=True,
        )
    ]
    return StrategySignalPayload(
        strategy_name="BULL_CALL_SPREAD",
        strategy_type=StrategyType.BULL_CALL_SPREAD,
        signal_type=SignalType.ENTRY,
        underlying=UnderlyingIndex.NIFTY,
        regime=MarketRegime.LOW_IV_RANGING,
        legs=legs,
        entry_credit_debit=50.0,
        max_profit=2500.0,
        max_loss=2500.0,
    )


# -----------------------------------------------------------------------------
# Scenario (a): Connect Account
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_a_connect_account(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_a"}
        resp = await client.post(
            "/api/v1/accounts/connect",
            json={
                "broker_id": "mock",
                "account_label": "User A Main",
                "credentials": {"client_id": "MOCK_USER_A_1"},
                "make_active": True,
            },
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["account_label"] == "User A Main"
        assert data["status"] == "CONNECTED"
        assert data["is_active"] is True
        assert "account_id" in data

        # Appears in GET /api/v1/accounts
        list_resp = await client.get("/api/v1/accounts", headers=headers)
        assert list_resp.status_code == 200
        accounts = list_resp.json()
        assert len(accounts) >= 1
        matching = [a for a in accounts if a["account_id"] == data["account_id"]]
        assert len(matching) == 1
        assert matching[0]["is_active"] is True


# -----------------------------------------------------------------------------
# Scenario (b): Switch Account with No Open Positions
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_b_switch_account_no_open_positions(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_b_switch"}
        # Connect 1st account (active)
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Account 1", "credentials": {"client_id": "ACC1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Connect 2nd account (inactive)
        r2 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Account 2", "credentials": {"client_id": "ACC2"}, "make_active": False},
            headers=headers,
        )
        acc2_id = r2.json()["account_id"]

        # Switch to acc2 without positions -> succeeds immediately
        switch_resp = await client.post(f"/api/v1/accounts/{acc2_id}/activate", headers=headers)
        assert switch_resp.status_code == 200
        assert switch_resp.json()["status"] == "success"
        assert switch_resp.json()["active_account_id"] == acc2_id

        # Verify active account endpoint reflects switch
        active_resp = await client.get("/api/v1/accounts/active", headers=headers)
        assert active_resp.status_code == 200
        assert active_resp.json()["account_id"] == acc2_id


# -----------------------------------------------------------------------------
# Scenario (c): Switch Account with Open Positions Requires Confirmation
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_c_switch_with_open_positions_requires_confirmation(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_c_pos"}
        # Connect Acc 1
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "ACC_C1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Connect Acc 2
        r2 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 2", "credentials": {"client_id": "ACC_C2"}, "make_active": False},
            headers=headers,
        )
        acc2_id = r2.json()["account_id"]

        # Place synchronous order on Acc 1 to open a position
        order_resp = await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sample_payload.model_dump(mode="json"),
            headers=headers,
        )
        assert order_resp.status_code == 202

        # Verify positions exist on Acc 1
        pos_resp = await client.get("/api/v1/positions", headers=headers)
        assert pos_resp.status_code == 200
        assert len(pos_resp.json()) > 0

        # Attempt to switch to Acc 2 without confirm=true -> 409 Conflict
        attempt_resp = await client.post(f"/api/v1/accounts/{acc2_id}/activate", headers=headers)
        assert attempt_resp.status_code == 409
        conflict_detail = attempt_resp.json()["detail"]
        assert conflict_detail["requires_confirmation"] is True
        assert conflict_detail["open_positions_count"] > 0

        # Switch with confirm=true -> succeeds
        confirm_resp = await client.post(
            f"/api/v1/accounts/{acc2_id}/activate?confirm=true",
            headers=headers,
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["active_account_id"] == acc2_id


# -----------------------------------------------------------------------------
# Scenario (d): Positions Query Returns Only Active Account Positions
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_d_positions_scoped_to_active_account(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_d_iso"}
        # Acc 1
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "D1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Place order on Acc 1
        await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sample_payload.model_dump(mode="json"),
            headers=headers,
        )

        # Acc 2
        r2 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 2", "credentials": {"client_id": "D2"}, "make_active": False},
            headers=headers,
        )
        acc2_id = r2.json()["account_id"]

        # Switch to Acc 2 with confirm=true
        await client.post(f"/api/v1/accounts/{acc2_id}/activate?confirm=true", headers=headers)

        # Query positions -> Acc 2 has NO positions!
        pos_resp = await client.get("/api/v1/positions", headers=headers)
        assert pos_resp.status_code == 200
        assert pos_resp.json() == []


# -----------------------------------------------------------------------------
# Scenario (e): Orders Query Isolated to Active Account
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_e_orders_isolated_to_active_account(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_e_ord"}
        # Acc 1
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "E1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Ingest order on Acc 1
        await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sample_payload.model_dump(mode="json"),
            headers=headers,
        )

        orders_acc1 = (await client.get("/api/v1/orders", headers=headers)).json()
        assert len(orders_acc1) >= 1

        # Acc 2
        r2 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 2", "credentials": {"client_id": "E2"}, "make_active": False},
            headers=headers,
        )
        acc2_id = r2.json()["account_id"]

        # Switch to Acc 2
        await client.post(f"/api/v1/accounts/{acc2_id}/activate?confirm=true", headers=headers)

        # Acc 2 orders should be empty
        orders_acc2 = (await client.get("/api/v1/orders", headers=headers)).json()
        assert orders_acc2 == []


# -----------------------------------------------------------------------------
# Scenario (f): Switch Back Reflects Original Account Without Residue
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_f_switch_back_restores_original_data(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_f_back"}
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "F1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        await client.post("/api/v1/signals/ingest?sync=true", json=sample_payload.model_dump(mode="json"), headers=headers)

        r2 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 2", "credentials": {"client_id": "F2"}, "make_active": False},
            headers=headers,
        )
        acc2_id = r2.json()["account_id"]

        # Switch to Acc 2
        await client.post(f"/api/v1/accounts/{acc2_id}/activate?confirm=true", headers=headers)
        assert (await client.get("/api/v1/positions", headers=headers)).json() == []

        # Switch back to Acc 1
        await client.post(f"/api/v1/accounts/{acc1_id}/activate?confirm=true", headers=headers)

        # Positions are restored exactly
        pos_acc1 = (await client.get("/api/v1/positions", headers=headers)).json()
        assert len(pos_acc1) > 0


# -----------------------------------------------------------------------------
# Scenario (g): Token Expiration Mid-Session Rejects Orders
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_g_token_expiration_blocks_orders(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_g_exp"}
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "G1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Simulate token expiration
        exp_resp = await client.post(f"/api/v1/accounts/{acc1_id}/simulate-token-expiry", headers=headers)
        assert exp_resp.status_code == 200
        assert exp_resp.json()["new_status"] == "TOKEN_EXPIRED"

        # Active account remains acc1, but status is TOKEN_EXPIRED
        active_resp = await client.get("/api/v1/accounts/active", headers=headers)
        assert active_resp.json()["status"] == "TOKEN_EXPIRED"

        # Order placement must be rejected with 401 TOKEN_EXPIRED
        order_resp = await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sample_payload.model_dump(mode="json"),
            headers=headers,
        )
        assert order_resp.status_code == 401
        assert "TOKEN_EXPIRED" in order_resp.json()["detail"]


# -----------------------------------------------------------------------------
# Scenario (h): Disconnected Account Activation Rejected & Clears Active
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_h_disconnected_account_handling(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_h_disc"}
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Acc 1", "credentials": {"client_id": "H1"}, "make_active": True},
            headers=headers,
        )
        acc1_id = r1.json()["account_id"]

        # Disconnect active account
        disc_resp = await client.post(f"/api/v1/accounts/{acc1_id}/disconnect", headers=headers)
        assert disc_resp.status_code == 200
        assert disc_resp.json()["new_status"] == "DISCONNECTED"

        # Active account is now None
        active_resp = await client.get("/api/v1/accounts/active", headers=headers)
        assert active_resp.status_code == 200
        assert active_resp.json() is None

        # Trying to activate a disconnected account fails
        act_resp = await client.post(f"/api/v1/accounts/{acc1_id}/activate", headers=headers)
        assert act_resp.status_code == 400
        assert "DISCONNECTED" in act_resp.json()["detail"]


# -----------------------------------------------------------------------------
# Scenario (i): Cross-User Authorization Bypass Rejected with 404
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_i_cross_user_auth_bypass_rejected(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # User A connects account
        r_a = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "User A Acc", "credentials": {"client_id": "USER_A_SEC"}, "make_active": True},
            headers={"X-User-ID": "victim_user_a"},
        )
        acc_a_id = r_a.json()["account_id"]

        # User B tries to activate User A's account -> 404 Not Found (no enumeration)
        malicious_resp = await client.post(
            f"/api/v1/accounts/{acc_a_id}/activate",
            headers={"X-User-ID": "attacker_user_b"},
        )
        assert malicious_resp.status_code == 404

        # User B tries to disconnect User A's account -> 404 Not Found
        malicious_disc = await client.post(
            f"/api/v1/accounts/{acc_a_id}/disconnect",
            headers={"X-User-ID": "attacker_user_b"},
        )
        assert malicious_disc.status_code == 404


# -----------------------------------------------------------------------------
# Scenario (j): Order-Routing Mismatch Rejected with ACCOUNT_MISMATCH
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scenario_j_order_routing_mismatch_rejected(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_j_mismatch"}
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Active Acc", "credentials": {"client_id": "J1"}, "make_active": True},
            headers=headers,
        )
        active_id = r1.json()["account_id"]

        # Send order with different account_id
        mismatched_payload = sample_payload.model_dump(mode="json")
        mismatched_payload["account_id"] = "some_other_account_id"

        order_resp = await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=mismatched_payload,
            headers=headers,
        )
        assert order_resp.status_code == 400
        assert "ACCOUNT_MISMATCH" in order_resp.json()["detail"]


# -----------------------------------------------------------------------------
# Square-Off All Action Endpoint Test
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_square_off_all_action_endpoint(app, sample_payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = {"X-User-ID": "user_sq_off"}
        # Connect active account
        r1 = await client.post(
            "/api/v1/accounts/connect",
            json={"broker_id": "mock", "account_label": "Square Off Acc", "credentials": {"client_id": "SQ1"}, "make_active": True},
            headers=headers,
        )
        assert r1.status_code == 201

        # Ingest signal to create open position
        order_resp = await client.post(
            "/api/v1/signals/ingest?sync=true",
            json=sample_payload.model_dump(mode="json"),
            headers=headers,
        )
        assert order_resp.status_code == 202

        # Check positions > 0
        pos_resp = await client.get("/api/v1/positions", headers=headers)
        assert pos_resp.status_code == 200
        assert len(pos_resp.json()) > 0

        # Execute square off all
        sq_resp = await client.post("/api/v1/positions/square-off-all", headers=headers)
        assert sq_resp.status_code == 200
        sq_data = sq_resp.json()
        assert sq_data["status"] == "success"
        assert sq_data["closed_count"] > 0

        # Subsequent positions query is empty
        pos_after = await client.get("/api/v1/positions", headers=headers)
        assert pos_after.status_code == 200
        assert pos_after.json() == []
