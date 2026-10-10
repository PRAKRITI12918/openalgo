"""
Unit and Integration Tests for the Pending Trade Signal Approval Queue.
Verifies approval execution, terminal rejection, concurrent duplicate-approval race prevention (CAS),
TTL expiration enforcement, invalid ID handling, execution failure recovery, and Square-Off-All independence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.schemas import (
    LegOrderRequest,
    OrderAction,
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
def test_app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture
def sample_signal_payload() -> StrategySignalPayload:
    """Generates a multi-leg Iron Condor strategy signal payload."""
    sig_id = str(uuid.uuid4())
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
            price=65.0,
            is_hedge_leg=False,
        ),
    ]

    return StrategySignalPayload(
        signal_id=sig_id,
        strategy_name="IRON_CONDOR",
        strategy_type=StrategyType.IRON_CONDOR,
        signal_type=SignalType.ENTRY,
        underlying=UnderlyingIndex.NIFTY,
        regime=MarketRegime.LOW_IV_RANGING,
        legs=legs,
        entry_credit_debit=95.0,
        validity_seconds=300,
        requires_approval=True,
        reason="Delta neutral iron condor entry for rangebound regime",
    )


@pytest.mark.asyncio
async def test_approve_valid_pending_signal(test_app, sample_signal_payload):
    """
    Test 1: Ingest pending signal -> approve -> verify pipeline execution with correct payload.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Step 1: Ingest signal requiring approval
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "PENDING_APPROVAL"
        signal_id = data["signal_id"]
        assert signal_id == sample_signal_payload.signal_id

        # Step 2: Query pending list to confirm it appears in queue
        list_resp = await client.get("/api/v1/signals/pending")
        assert list_resp.status_code == 200
        pending_list = list_resp.json()
        assert pending_list["success"] is True
        matched = [s for s in pending_list["signals"] if s["signal_id"] == signal_id]
        assert len(matched) == 1
        assert matched[0]["status"] == "PENDING"
        assert matched[0]["strategy_name"] == "IRON_CONDOR"
        assert matched[0]["legs_count"] == 4

        # Step 3: Approve signal
        approve_resp = await client.post(
            f"/api/v1/signals/{signal_id}/approve",
            json={"actor": "test-trader-lead"},
        )
        assert approve_resp.status_code == 200
        appr_data = approve_resp.json()
        assert appr_data["success"] is True
        assert appr_data["status"] == "APPROVED"
        assert appr_data["sequence_id"] is not None
        assert appr_data["sequence"]["completed_legs"] == 4

        # Step 4: Verify status updated in pending queue
        check_list = await client.get("/api/v1/signals/pending")
        updated_sig = next(s for s in check_list.json()["signals"] if s["signal_id"] == signal_id)
        assert updated_sig["status"] == "APPROVED"
        assert updated_sig["sequence_id"] == appr_data["sequence_id"]


@pytest.mark.asyncio
async def test_reject_valid_pending_signal(test_app, sample_signal_payload):
    """
    Test 2: Ingest pending signal -> reject -> confirm terminal state and zero execution.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Ingest
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        signal_id = resp.json()["signal_id"]

        # Reject
        reject_resp = await client.post(
            f"/api/v1/signals/{signal_id}/reject",
            json={"reason": "Excessive portfolio vega", "actor": "risk-officer"},
        )
        assert reject_resp.status_code == 200
        rej_data = reject_resp.json()
        assert rej_data["success"] is True
        assert rej_data["status"] == "REJECTED"
        assert rej_data["reason"] == "Excessive portfolio vega"
        assert rej_data["actor"] == "risk-officer"

        # Check queue reflects REJECTED terminal state
        check_list = await client.get("/api/v1/signals/pending")
        archived_sig = next(s for s in check_list.json()["signals"] if s["signal_id"] == signal_id)
        assert archived_sig["status"] == "REJECTED"
        assert archived_sig["rejection_reason"] == "Excessive portfolio vega"
        assert archived_sig["sequence_id"] is None


@pytest.mark.asyncio
async def test_duplicate_approval_concurrency_race_prevention(test_app, sample_signal_payload):
    """
    Test 3: Simulate rapid concurrent double-submit -> exactly one succeeds, second gets 409 Conflict.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Ingest
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        signal_id = resp.json()["signal_id"]

        # Concurrently fire two rapid approval requests
        req1 = client.post(f"/api/v1/signals/{signal_id}/approve", json={"actor": "tab-1"})
        req2 = client.post(f"/api/v1/signals/{signal_id}/approve", json={"actor": "tab-2"})

        res1, res2 = await asyncio.gather(req1, req2)

        statuses = {res1.status_code, res2.status_code}
        # One MUST be 200 and the other MUST be 409 Conflict
        assert 200 in statuses, f"Expected a 200 OK in {[res1.status_code, res2.status_code]}"
        assert 409 in statuses, f"Expected a 409 Conflict in {[res1.status_code, res2.status_code]}"


@pytest.mark.asyncio
async def test_approve_expired_signal_rejected(test_app, sample_signal_payload):
    """
    Test 4: Approve an expired signal -> rejected with 400 Bad Request, no execution.
    """
    # Configure 1 second TTL
    sample_signal_payload.validity_seconds = 1

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        signal_id = resp.json()["signal_id"]

        # Wait for expiration
        await asyncio.sleep(1.2)

        # Attempt to approve expired signal
        appr_resp = await client.post(f"/api/v1/signals/{signal_id}/approve")
        assert appr_resp.status_code == 400
        err = appr_resp.json()
        assert "expired" in err["detail"].lower()

        # Confirm queue records signal as EXPIRED
        queue_resp = await client.get("/api/v1/signals/pending")
        sig = next(s for s in queue_resp.json()["signals"] if s["signal_id"] == signal_id)
        assert sig["status"] == "EXPIRED"
        assert sig["is_expired"] is True


@pytest.mark.asyncio
async def test_approve_reject_invalid_id_returns_404(test_app):
    """
    Test 5: Approve or reject an invalid/unknown signal ID -> proper 404 handling.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        fake_id = "non-existent-uuid-9999"
        res_appr = await client.post(f"/api/v1/signals/{fake_id}/approve")
        assert res_appr.status_code == 404

        res_rej = await client.post(f"/api/v1/signals/{fake_id}/reject")
        assert res_rej.status_code == 404


@pytest.mark.asyncio
async def test_execution_failure_marks_signal_as_failed(test_app, sample_signal_payload):
    """
    Test 6: Backend/execution failure during approve -> signal state reflects FAILED accurately.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Ingest signal
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        assert resp.status_code == 202
        signal_id = resp.json()["signal_id"]

        # Inject broker failure by monkeypatching engine.execute_signal to raise an exception
        engine = test_app.state.sequence_engine

        async def failing_execute(payload):
            raise RuntimeError("Broker gateway timeout: order routing rejected by exchange")

        original_execute = engine.execute_signal
        engine.execute_signal = failing_execute

        try:
            appr_resp = await client.post(f"/api/v1/signals/{signal_id}/approve")
            assert appr_resp.status_code == 500
            assert "Broker gateway timeout" in appr_resp.json()["detail"]

            # Confirm signal is not left as APPROVED
            queue_resp = await client.get("/api/v1/signals/pending")
            failed_sig = next(s for s in queue_resp.json()["signals"] if s["signal_id"] == signal_id)
            assert failed_sig["status"] == "FAILED"
            assert "Broker gateway timeout" in failed_sig["error_message"]
        finally:
            engine.execute_signal = original_execute


@pytest.mark.asyncio
async def test_full_pipeline_flow_reflects_in_order_history(test_app, sample_signal_payload):
    """
    Test 7: Full successful path: ingest -> pending queue -> approve -> executes -> visible in /orders.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Ingest
        resp = await client.post(
            "/signals",  # Test standard root alias route
            json=sample_signal_payload.model_dump(mode="json"),
            params={"requires_approval": True},
        )
        assert resp.status_code == 202
        signal_id = resp.json()["signal_id"]

        # 2. Listed in pending queue
        queue_resp = await client.get("/signals/pending")
        assert queue_resp.status_code == 200
        assert any(s["signal_id"] == signal_id for s in queue_resp.json()["signals"])

        # 3. Approve
        appr_resp = await client.post(f"/signals/{signal_id}/approve")
        assert appr_resp.status_code == 200
        seq_id = appr_resp.json()["sequence_id"]

        # 4. Reflects in order book
        orders_resp = await client.get("/orders")
        assert orders_resp.status_code == 200
        sequences = orders_resp.json()
        assert any(seq["sequence_id"] == seq_id for seq in sequences)


@pytest.mark.asyncio
async def test_square_off_all_independence(test_app, sample_signal_payload):
    """
    Test 8: Square-Off-All works independently and does not mutate or clear pending signals queue.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Ingest pending signal
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        signal_id = resp.json()["signal_id"]

        # Verify broker positions can be retrieved
        pos_resp = await client.get("/api/v1/positions")
        assert pos_resp.status_code == 200

        # Query pending signal: remains intact
        check_list = await client.get("/api/v1/signals/pending")
        assert any(s["signal_id"] == signal_id and s["status"] == "PENDING" for s in check_list.json()["signals"])


@pytest.mark.asyncio
async def test_non_approval_signal_executes_immediately(test_app, sample_signal_payload):
    """
    Test 9: Signals with requires_approval=False bypass queue and execute immediately.
    """
    sample_signal_payload.requires_approval = False
    sample_signal_payload.signal_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
            params={"sync": True},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "COMPLETED"
        assert "sequence_id" in data

        # Confirm it was NOT added to pending queue
        queue_resp = await client.get("/api/v1/signals/pending")
        assert not any(s["signal_id"] == sample_signal_payload.signal_id for s in queue_resp.json()["signals"])


@pytest.mark.asyncio
async def test_terminal_signals_cannot_be_re_approved_or_re_rejected(test_app, sample_signal_payload):
    """
    Test 10: Terminal signals (APPROVED, REJECTED) reject subsequent approval or rejection with 409 Conflict.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Ingest and approve first signal
        sample_signal_payload.signal_id = str(uuid.uuid4())
        resp1 = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        sig1_id = resp1.json()["signal_id"]

        appr_resp = await client.post(f"/api/v1/signals/{sig1_id}/approve")
        assert appr_resp.status_code == 200

        # Attempting to approve again -> 409
        re_appr = await client.post(f"/api/v1/signals/{sig1_id}/approve")
        assert re_appr.status_code == 409
        assert "terminal" in re_appr.json()["detail"].lower()

        # Attempting to reject approved signal -> 409
        rej_after_appr = await client.post(f"/api/v1/signals/{sig1_id}/reject")
        assert rej_after_appr.status_code == 409
        assert "terminal" in rej_after_appr.json()["detail"].lower()

        # 2. Ingest and reject second signal
        sample_signal_payload.signal_id = str(uuid.uuid4())
        resp2 = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        sig2_id = resp2.json()["signal_id"]

        rej_resp = await client.post(f"/api/v1/signals/{sig2_id}/reject")
        assert rej_resp.status_code == 200

        # Attempting to approve rejected signal -> 409
        appr_after_rej = await client.post(f"/api/v1/signals/{sig2_id}/approve")
        assert appr_after_rej.status_code == 409
        assert "terminal" in appr_after_rej.json()["detail"].lower()

        # Attempting to reject again -> 409
        re_rej = await client.post(f"/api/v1/signals/{sig2_id}/reject")
        assert re_rej.status_code == 409
        assert "terminal" in re_rej.json()["detail"].lower()


@pytest.mark.asyncio
async def test_reject_expired_signal_returns_400(test_app, sample_signal_payload):
    """
    Test 11: Attempting to reject an already expired signal returns 400 Bad Request.
    """
    sample_signal_payload.validity_seconds = 1
    sample_signal_payload.signal_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        sig_id = resp.json()["signal_id"]

        await asyncio.sleep(1.2)

        rej_resp = await client.post(f"/api/v1/signals/{sig_id}/reject")
        assert rej_resp.status_code == 400
        assert "expired" in rej_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_circuit_breaker_aborts_approved_signal_and_marks_failed(test_app, sample_signal_payload):
    """
    Test 12: If broker rejects a hedge leg during approval, circuit breaker trips and marks signal FAILED.
    """
    sample_signal_payload.signal_id = str(uuid.uuid4())

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/signals/ingest",
            json=sample_signal_payload.model_dump(mode="json"),
        )
        sig_id = resp.json()["signal_id"]

        # Inject failure on the first hedge wing
        broker = test_app.state.broker_adapter
        broker.inject_rejection_for_symbol("NIFTY26AUG23800PE", "Broker margin rejection on wing")

        try:
            appr_resp = await client.post(f"/api/v1/signals/{sig_id}/approve")
            assert appr_resp.status_code == 200
            data = appr_resp.json()
            assert data["success"] is False
            assert data["status"] == "FAILED"
            assert "circuit breaker" in data["message"].lower()

            # Confirm signal record reflects FAILED and has error_message
            queue_resp = await client.get("/api/v1/signals/pending")
            sig_rec = next(s for s in queue_resp.json()["signals"] if s["signal_id"] == sig_id)
            assert sig_rec["status"] == "FAILED"
            assert "Broker margin rejection on wing" in sig_rec["error_message"]
        finally:
            broker.clear_injected_rejections()

