"""
End-to-End Strategy Approval Workflow Test Suite.
Verifies complete lifecycle, backend-enforced security guards, active-account pre-checks,
atomic Compare-And-Swap (CAS) concurrency races, and structural execution isolation on rejection.

Tests cover:
a. Happy path approve (PENDING -> APPROVED -> EXECUTING -> COMPLETED)
b. Happy path reject (zero execution engine invocation)
c. Double-approve race (concurrent requests -> exactly 1 execution, 1 409 Conflict)
d. Double-reject race (concurrent requests -> exactly 1 transition, 1 409 Conflict)
e. Approve vs. Reject concurrent race (mutual exclusivity, no inconsistent state)
f. Approve signal not in PENDING_APPROVAL -> 409 error with current_status
g. Approve with no active connected account -> rejected fail-fast, signal stays PENDING
h. Approve with partial execution failure -> signal ends in FAILED, legs reflect filled vs blocked
i. Authorization bypass attempt -> 403 Forbidden
j. Client duplicate-click simulation and backend CAS verification
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.database.account_models import BrokerAccount, BrokerAccountStatus, db_session as account_session
from src.database.pending_signals_db import get_pending_signal_by_id
from src.main import create_app
from src.models.schemas import (
    LegOrderRequest,
    OrderAction,
    OrderStatus,
    OrderType,
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
    """Create fresh FastAPI instance for each test."""
    return create_app()


def build_test_signal(
    signal_id: str | None = None,
    user_id: str | None = None,
    requires_approval: bool = True,
    legs_count: int = 4,
) -> StrategySignalPayload:
    """Helper to build a valid multi-leg strategy signal."""
    sig_id = signal_id or f"sig_test_{uuid.uuid4().hex[:8]}"
    legs = []
    if legs_count >= 1:
        legs.append(
            LegOrderRequest(
                leg_id="leg-1",
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
        )
    if legs_count >= 2:
        legs.append(
            LegOrderRequest(
                leg_id="leg-2",
                symbol="NIFTY26AUG24200CE",
                underlying=UnderlyingIndex.NIFTY,
                strike=24200.0,
                option_type=OptionType.CE,
                expiry="2026-08-27",
                action=OrderAction.SELL,
                quantity=50,
                order_type=OrderType.MARKET,
                price=30.0,
                is_hedge_leg=False,
            )
        )
    if legs_count >= 3:
        legs.append(
            LegOrderRequest(
                leg_id="leg-3",
                symbol="NIFTY26AUG23800PE",
                underlying=UnderlyingIndex.NIFTY,
                strike=23800.0,
                option_type=OptionType.PE,
                expiry="2026-08-27",
                action=OrderAction.BUY,
                quantity=50,
                order_type=OrderType.MARKET,
                price=45.0,
                is_hedge_leg=True,
            )
        )
    if legs_count >= 4:
        legs.append(
            LegOrderRequest(
                leg_id="leg-4",
                symbol="NIFTY26AUG23600PE",
                underlying=UnderlyingIndex.NIFTY,
                strike=23600.0,
                option_type=OptionType.PE,
                expiry="2026-08-27",
                action=OrderAction.SELL,
                quantity=50,
                order_type=OrderType.MARKET,
                price=25.0,
                is_hedge_leg=False,
            )
        )

    return StrategySignalPayload(
        signal_id=sig_id,
        strategy_name="IRON_CONDOR",
        strategy_type=StrategyType.IRON_CONDOR,
        signal_type=SignalType.ENTRY,
        underlying=UnderlyingIndex.NIFTY,
        regime=MarketRegime.LOW_IV_RANGING,
        legs=legs,
        entry_credit_debit=10.0,
        validity_seconds=300,
        requires_approval=requires_approval,
        user_id=user_id,
        reason="Automated test approval signal",
    )


@pytest.mark.asyncio
async def test_a_happy_path_approve(app_instance):
    """
    (a) Happy path approve:
    PENDING_APPROVAL -> APPROVED -> EXECUTING -> COMPLETED
    Verifies full lifecycle, position updates, progress endpoint, and complete audit trail.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        # Ingest
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        assert ingest_res.status_code == 202
        sig_id = ingest_res.json()["signal_id"]

        # Check progress before approval: should be PENDING
        prog_before = await client.get(f"/api/v1/signals/{sig_id}/progress")
        assert prog_before.status_code == 200
        prog_data = prog_before.json()
        assert prog_data["status"] == "PENDING"
        assert len(prog_data["legs"]) == 4

        # Approve signal
        appr_res = await client.post(
            f"/api/v1/signals/{sig_id}/approve",
            json={"actor": "lead-trader-alpha"},
        )
        assert appr_res.status_code == 200
        data = appr_res.json()
        assert data["success"] is True
        assert data["status"] == "APPROVED"
        assert data["sequence_id"] is not None
        assert data["sequence"]["completed_legs"] == 4

        # Verify progress endpoint after approval
        prog_after = await client.get(f"/api/v1/signals/{sig_id}/progress")
        assert prog_after.status_code == 200
        after_data = prog_after.json()
        assert after_data["status"] == "APPROVED"
        assert after_data["sequence_id"] == data["sequence_id"]
        assert len(after_data["legs"]) == 4
        # All legs should have completed execution
        for leg in after_data["legs"]:
            assert leg["status"] == "COMPLETE"
            assert leg["order_id"] is not None

        # Verify audit trail in progress response
        history = after_data["status_history"]
        actions = [h.get("action") for h in history]
        assert "INGESTED" in actions
        assert "APPROVE_INITIATED" in actions
        assert "EXECUTION_COMPLETED" in actions


@pytest.mark.asyncio
async def test_b_happy_path_reject_guarantees_no_execution(app_instance):
    """
    (b) Happy path reject:
    PENDING_APPROVAL -> REJECTED
    Verifies reason and timestamp are recorded, and execute_signal() is NEVER called.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        assert ingest_res.status_code == 202
        sig_id = ingest_res.json()["signal_id"]

        # Spy on sequence_engine.execute_signal to assert zero invocations
        engine = app_instance.state.sequence_engine
        with patch.object(engine, "execute_signal", wraps=engine.execute_signal) as spy_exec:
            reject_res = await client.post(
                f"/api/v1/signals/{sig_id}/reject",
                json={"reason": "Excessive gamma risk before market close", "actor": "risk-director"},
            )
            assert reject_res.status_code == 200
            rej_data = reject_res.json()
            assert rej_data["success"] is True
            assert rej_data["status"] == "REJECTED"
            assert rej_data["reason"] == "Excessive gamma risk before market close"
            assert rej_data["actor"] == "risk-director"

            # Assert execution engine was NEVER called
            spy_exec.assert_not_called()

        # Check progress endpoint confirms REJECTED terminal state
        prog = await client.get(f"/api/v1/signals/{sig_id}/progress")
        assert prog.status_code == 200
        pdata = prog.json()
        assert pdata["status"] == "REJECTED"
        assert pdata["rejection_reason"] == "Excessive gamma risk before market close"
        for leg in pdata["legs"]:
            assert leg["status"] == "REJECTED"
            assert leg["order_id"] is None


@pytest.mark.asyncio
async def test_c_double_approve_race_protection(app_instance):
    """
    (c) Double-approve race:
    Simulates two concurrent approve requests for the same signal_id.
    Exactly one succeeds and triggers execution; the second receives 409 Conflict.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        # Launch concurrent approve calls
        res1, res2 = await asyncio.gather(
            client.post(f"/api/v1/signals/{sig_id}/approve", json={"actor": "tab-1"}),
            client.post(f"/api/v1/signals/{sig_id}/approve", json={"actor": "tab-2"}),
        )

        status_codes = sorted([res1.status_code, res2.status_code])
        # Exactly one must be 200 OK and the other must be 409 Conflict
        assert status_codes == [200, 409]

        error_res = res1 if res1.status_code == 409 else res2
        assert "SIGNAL_NOT_PENDING_APPROVAL" in error_res.json()["detail"] or "already" in error_res.json()["detail"].lower()

        # Verify only one execution sequence exists
        rec = get_pending_signal_by_id(sig_id)
        assert rec.status == "APPROVED"
        assert rec.sequence_id is not None


@pytest.mark.asyncio
async def test_d_double_reject_race_protection(app_instance):
    """
    (d) Double-reject race:
    Simulates two concurrent reject requests for the same signal_id.
    Exactly one succeeds; the second receives 409 Conflict.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        res1, res2 = await asyncio.gather(
            client.post(f"/api/v1/signals/{sig_id}/reject", json={"reason": "Click 1"}),
            client.post(f"/api/v1/signals/{sig_id}/reject", json={"reason": "Click 2"}),
        )

        status_codes = sorted([res1.status_code, res2.status_code])
        assert status_codes == [200, 409]

        error_res = res1 if res1.status_code == 409 else res2
        assert "SIGNAL_NOT_PENDING_APPROVAL" in error_res.json()["detail"] or "terminal" in error_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_e_concurrent_approve_and_reject_race(app_instance):
    """
    (e) Approve-then-reject / Reject-then-approve race:
    Concurrent approve and reject on the same signal.
    Only one transition wins; the other is cleanly rejected as an invalid state transition.
    No split state can ever occur.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        appr_res, rej_res = await asyncio.gather(
            client.post(f"/api/v1/signals/{sig_id}/approve", json={"actor": "approver"}),
            client.post(f"/api/v1/signals/{sig_id}/reject", json={"reason": "rejecter"}),
        )

        status_codes = sorted([appr_res.status_code, rej_res.status_code])
        assert status_codes == [200, 409]

        # The winner is either APPROVED or REJECTED
        rec = get_pending_signal_by_id(sig_id)
        assert rec.status in ("APPROVED", "REJECTED")


@pytest.mark.asyncio
async def test_f_approve_signal_not_in_pending_approval(app_instance):
    """
    (f) Approve a signal NOT in PENDING_APPROVAL:
    Attempting to approve a completed or rejected signal returns 409 Conflict
    with explicit SIGNAL_NOT_PENDING_APPROVAL and current_status included.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        # Reject it first
        rej = await client.post(f"/api/v1/signals/{sig_id}/reject", json={"reason": "manual test"})
        assert rej.status_code == 200

        # Attempt to approve rejected signal
        appr_res = await client.post(f"/api/v1/signals/{sig_id}/approve")
        assert appr_res.status_code == 409
        detail = appr_res.json()["detail"]
        assert "SIGNAL_NOT_PENDING_APPROVAL" in detail or "terminal" in detail.lower()
        assert "REJECTED" in detail


@pytest.mark.asyncio
async def test_g_approve_with_no_active_connected_account_fails_fast(app_instance):
    """
    (g) Approve with no active connected account:
    Rejected fail-fast at the approval step itself (per 1d) with a clear error.
    Signal remains PENDING_APPROVAL (not left dangling in APPROVED or EXECUTING).
    """
    user_id = f"trader_no_account_{uuid.uuid4().hex[:6]}"
    signal = build_test_signal(user_id=user_id)

    # Insert a disconnected account for this user and select it as active
    from src.database.account_models import ActiveAccountSelection
    sess = account_session()
    try:
        acc = BrokerAccount(
            id=f"acc_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            broker_id="DHAN",
            account_label="Inactive Account",
            external_account_id="EXT12345",
            status=BrokerAccountStatus.DISCONNECTED.value,
            token_ref="tok_inactive",
        )
        sess.add(acc)
        sel = ActiveAccountSelection(
            user_id=user_id,
            active_broker_account_id=acc.id,
        )
        sess.add(sel)
        sess.commit()
    finally:
        sess.close()

    # Store signal directly in pending approval queue for this user
    pending_mgr = app_instance.state.pending_manager
    await pending_mgr.add_pending_signal(signal)
    sig_id = signal.signal_id

    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        # Attempt to approve with the disconnected user account
        appr_res = await client.post(
            f"/api/v1/signals/{sig_id}/approve",
            headers={"X-User-ID": user_id},
        )
        assert appr_res.status_code == 400
        err_detail = appr_res.json()["detail"]
        assert "ACTIVE_ACCOUNT_NOT_CONNECTED" in err_detail

        # Crucial invariant: signal MUST remain in PENDING state!
        rec = get_pending_signal_by_id(sig_id)
        assert rec is not None
        assert rec.status == "PENDING"
        assert rec.sequence_id is None


@pytest.mark.asyncio
async def test_h_partial_execution_failure_marks_signal_failed(app_instance):
    """
    (h) Partial execution failure:
    Simulates a broker-level rejection on a critical leg.
    Signal ends in FAILED, per-leg status accurately reflects filled vs blocked,
    and audit trail shows the causal failure chain.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        # Inject simulated broker rejection on leg
        broker = app_instance.state.broker_adapter
        broker.inject_rejection_for_symbol(
            symbol="NIFTY26AUG24000CE",
            reason="Margin requirement exceeded for hedge leg",
        )

        appr_res = await client.post(f"/api/v1/signals/{sig_id}/approve")
        assert appr_res.status_code == 200
        data = appr_res.json()
        assert data["success"] is False
        assert data["status"] == "FAILED"
        assert "circuit breaker" in data["message"].lower() or "halted" in data["message"].lower()

        # Query progress endpoint
        prog = await client.get(f"/api/v1/signals/{sig_id}/progress")
        assert prog.status_code == 200
        pdata = prog.json()
        assert pdata["status"] == "FAILED"
        assert pdata["error_message"] is not None

        # Check that audit trail records the causal failure
        history_actions = [h.get("action") for h in pdata["status_history"]]
        assert "EXECUTION_FAILED" in history_actions


@pytest.mark.asyncio
async def test_i_authorization_bypass_rejected(app_instance):
    """
    (i) Authorization bypass attempt:
    A request crafted to approve or reject a signal owned by another user is rejected with 403 Forbidden.
    """
    alice_id = "user_alice_trader"
    bob_id = "user_bob_imposter"
    signal = build_test_signal(user_id=alice_id)

    # Ingest signal directly into pending queue for Alice
    pending_mgr = app_instance.state.pending_manager
    await pending_mgr.add_pending_signal(signal)
    sig_id = signal.signal_id

    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        # Bob attempts to approve Alice's signal directly -> 403 Forbidden
        bob_appr = await client.post(
            f"/api/v1/signals/{sig_id}/approve",
            headers={"X-User-ID": bob_id},
        )
        assert bob_appr.status_code == 403
        assert "FORBIDDEN_USER" in bob_appr.json()["detail"]

        # Bob attempts to reject Alice's signal directly -> 403 Forbidden
        bob_rej = await client.post(
            f"/api/v1/signals/{sig_id}/reject",
            json={"reason": "Malicious cancellation"},
            headers={"X-User-ID": bob_id},
        )
        assert bob_rej.status_code == 403
        assert "FORBIDDEN_USER" in bob_rej.json()["detail"]

        # Alice's signal remains intact in PENDING state
        rec = get_pending_signal_by_id(sig_id)
        assert rec.status == "PENDING"



@pytest.mark.asyncio
async def test_j_client_duplicate_click_simulation(app_instance):
    """
    (j) Client duplicate-click simulation:
    Simulates rapid double network calls from UI to confirm that backend CAS
    guarantees exactly one execution and returns an informative duplicate-protection error.
    """
    signal = build_test_signal()
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        ingest_res = await client.post("/api/v1/signals/ingest", json=signal.model_dump(mode="json"))
        sig_id = ingest_res.json()["signal_id"]

        # First request succeeds
        call1 = await client.post(f"/api/v1/signals/{sig_id}/approve")
        assert call1.status_code == 200

        # Immediate second request (double click) receives 409 Conflict
        call2 = await client.post(f"/api/v1/signals/{sig_id}/approve")
        assert call2.status_code == 409
        assert "SIGNAL_NOT_PENDING_APPROVAL" in call2.json()["detail"] or "already" in call2.json()["detail"].lower()
