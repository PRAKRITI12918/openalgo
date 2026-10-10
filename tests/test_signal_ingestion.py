"""
Comprehensive Test Suite for Phase 2 Signal Ingestion System.
Verifies strict schema validation, lot size checks, price-trigger directionality,
contiguous sequence ordering, database idempotency deduplication, status state machine
transitions, and simulated mock execution stub.
"""

from __future__ import annotations

import json
import os
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from src.main import create_app
from src.models.signal_schema import SignalStatus


@pytest.fixture
def test_app():
    """Create a fresh FastAPI app instance for testing."""
    return create_app()


@pytest.fixture
def fixtures_data():
    """Load mock signal fixtures from JSON file."""
    fixture_path = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mock_signals.json")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# 1. Valid Signal Ingestion Tests
# =============================================================================

@pytest.mark.asyncio
async def test_valid_single_leg_signal_ingestion(test_app, fixtures_data):
    """
    Test valid single-leg equity BUY order:
    Returns 201 Created, assigns signal_id, and transitions RECEIVED -> VALIDATED.
    """
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["idempotency_key"] = f"test-single-leg-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "signal_id" in data
        assert data["status"] == SignalStatus.VALIDATED.value
        assert data["is_duplicate"] is False
        assert "received_at" in data

        # Query back via GET /api/v1/signals/{signal_id}
        sig_resp = await client.get(f"/api/v1/signals/{data['signal_id']}")
        assert sig_resp.status_code == 200
        sig_data = sig_resp.json()
        assert sig_data["signal_id"] == data["signal_id"]
        assert sig_data["underlying"] == "RELIANCE"
        assert sig_data["quantity"] == 10
        assert sig_data["status"] == "VALIDATED"
        # Check audit history trail contains RECEIVED then VALIDATED
        history = sig_data["status_history"]
        assert len(history) >= 2
        assert history[0]["status"] == "RECEIVED"
        assert history[1]["status"] == "VALIDATED"


@pytest.mark.asyncio
async def test_valid_multi_leg_signal_ingestion(test_app, fixtures_data):
    """
    Test valid multi-leg option spread (Bull Call Spread):
    Returns 201 Created with valid contiguous execution sequences (1, 2).
    """
    payload = fixtures_data["valid_multi_leg_option_spread"].copy()
    payload["idempotency_key"] = f"test-multi-leg-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "VALIDATED"
        assert data["is_duplicate"] is False


@pytest.mark.asyncio
async def test_valid_single_leg_option_limit_sell(test_app, fixtures_data):
    """
    Test valid single-leg option SELL LIMIT order:
    Returns 201 Created and verifies lot size (NIFTY qty 50 is multiple of 25).
    """
    payload = fixtures_data["valid_single_leg_option_sell_limit"].copy()
    payload["idempotency_key"] = f"test-opt-sell-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["status"] == "VALIDATED"


# =============================================================================
# 2. Strict Schema Validation Failure Tests
# =============================================================================

@pytest.mark.asyncio
async def test_missing_required_field_rejected(test_app, fixtures_data):
    """Test payload missing required quantity is rejected with 422 structured error."""
    payload = fixtures_data["invalid_missing_quantity"].copy()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "SCHEMA_VALIDATION_FAILED"
        assert "errors" in data
        assert any("quantity" in err["field"] for err in data["errors"])


@pytest.mark.asyncio
async def test_invalid_enum_value_rejected(test_app, fixtures_data):
    """Test invalid enum values (e.g. instrument='CRYPTO', action='HOLD') are rejected."""
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["instrument"] = "CRYPTO"  # Invalid enum

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["status"] == "error"
        assert any("instrument" in err["field"] for err in data["errors"])


@pytest.mark.asyncio
async def test_limit_order_missing_price_rejected(test_app, fixtures_data):
    """Test LIMIT order without price is rejected with 422."""
    payload = fixtures_data["invalid_limit_order_without_price"].copy()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert data["status"] == "error"
        assert any("price" in err["reason"].lower() for err in data["errors"])


@pytest.mark.asyncio
async def test_sl_order_missing_trigger_price_rejected(test_app):
    """Test SL order missing trigger_price is rejected with 422."""
    payload = {
        "strategy_name": "SL_TEST",
        "underlying": "RELIANCE",
        "instrument": "EQUITY",
        "action": "BUY",
        "quantity": 10,
        "order_type": "SL",
        "price": 2500.0,
        # missing trigger_price
        "execution_sequence": 1,
        "signal_timestamp": "2026-09-24T10:00:00Z",
        "idempotency_key": f"test-sl-no-trigger-{uuid.uuid4().hex[:8]}",
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert any("trigger" in err["reason"].lower() for err in data["errors"])


@pytest.mark.asyncio
async def test_non_positive_quantity_rejected(test_app, fixtures_data):
    """Test quantity <= 0 is rejected with 422."""
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["quantity"] = 0

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert any("quantity" in err["field"] for err in data["errors"])


@pytest.mark.asyncio
async def test_execution_sequence_collision_within_legs_rejected(test_app, fixtures_data):
    """Test duplicated execution sequences across legs are rejected with 422."""
    payload = fixtures_data["invalid_execution_sequence_duplicated_across_legs"].copy()

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        data = resp.json()
        assert any("unique" in err["reason"].lower() or "sequence" in err["reason"].lower() for err in data["errors"])


# =============================================================================
# 3. Domain Logic Validations (Lot Size, Directionality, Metadata Cap)
# =============================================================================

@pytest.mark.asyncio
async def test_lot_size_multiple_validation(test_app):
    """
    Test lot size enforcement for known Indian derivatives:
    - NIFTY lot size is 25: quantity=26 must fail, quantity=25 must pass.
    """
    # 1. Invalid lot size (26)
    invalid_payload = {
        "strategy_name": "LOT_SIZE_TEST",
        "underlying": "NIFTY",
        "instrument": "FUTURE",
        "action": "BUY",
        "quantity": 26,  # Not a multiple of 25
        "order_type": "MARKET",
        "execution_sequence": 1,
        "signal_timestamp": "2026-09-24T10:00:00Z",
        "idempotency_key": f"test-lot-invalid-{uuid.uuid4().hex[:8]}",
    }

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=invalid_payload)
        assert resp.status_code == 422
        assert "lot size" in resp.text.lower()

        # 2. Valid lot size (50 = 2 * 25)
        valid_payload = invalid_payload.copy()
        valid_payload["quantity"] = 50
        valid_payload["idempotency_key"] = f"test-lot-valid-{uuid.uuid4().hex[:8]}"
        resp_valid = await client.post("/api/v1/signals", json=valid_payload)
        assert resp_valid.status_code == 201


@pytest.mark.asyncio
async def test_sl_trigger_price_direction_logic(test_app):
    """
    Test Stop-Loss direction consistency:
    - For BUY SL: price must be >= trigger_price. If price < trigger_price, must reject.
    - For SELL SL: price must be <= trigger_price. If price > trigger_price, must reject.
    """
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # BUY SL with price (100) < trigger_price (105) -> Invalid!
        bad_buy_sl = {
            "strategy_name": "SL_DIR_TEST",
            "underlying": "RELIANCE",
            "instrument": "EQUITY",
            "action": "BUY",
            "quantity": 10,
            "order_type": "SL",
            "price": 100.0,
            "trigger_price": 105.0,  # Invalid: trigger > limit on BUY
            "execution_sequence": 1,
            "signal_timestamp": "2026-09-24T10:00:00Z",
            "idempotency_key": f"test-sl-dir-buy-{uuid.uuid4().hex[:8]}",
        }
        resp = await client.post("/api/v1/signals", json=bad_buy_sl)
        assert resp.status_code == 422
        assert "direction" in resp.text.lower() or "trigger" in resp.text.lower()

        # SELL SL with price (105) > trigger_price (100) -> Invalid!
        bad_sell_sl = {
            "strategy_name": "SL_DIR_TEST",
            "underlying": "RELIANCE",
            "instrument": "EQUITY",
            "action": "SELL",
            "quantity": 10,
            "order_type": "SL",
            "price": 105.0,
            "trigger_price": 100.0,  # Invalid: price > trigger on SELL
            "execution_sequence": 1,
            "signal_timestamp": "2026-09-24T10:00:00Z",
            "idempotency_key": f"test-sl-dir-sell-{uuid.uuid4().hex[:8]}",
        }
        resp_sell = await client.post("/api/v1/signals", json=bad_sell_sl)
        assert resp_sell.status_code == 422
        assert "direction" in resp_sell.text.lower() or "trigger" in resp_sell.text.lower()


@pytest.mark.asyncio
async def test_metadata_size_cap_enforcement(test_app, fixtures_data):
    """Test that metadata exceeding 5KB serialized is rejected."""
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["idempotency_key"] = f"test-meta-cap-{uuid.uuid4().hex[:8]}"
    # Inject large string exceeding 5KB
    payload["metadata"] = {"huge_blob": "X" * 6000}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        resp = await client.post("/api/v1/signals", json=payload)
        assert resp.status_code == 422
        assert "5kb" in resp.text.lower() or "metadata" in resp.text.lower()


# =============================================================================
# 4. Duplicate Prevention (Idempotency Key) Tests
# =============================================================================

@pytest.mark.asyncio
async def test_duplicate_idempotency_key_returns_existing_record(test_app, fixtures_data):
    """
    Test duplicate idempotency_key submitted twice:
    - 1st call creates record -> 201 Created
    - 2nd call with identical key -> 200 OK with same signal_id and is_duplicate=True
    - Does NOT create a new row in database.
    """
    pair = fixtures_data["invalid_duplicate_idempotency_pair"]
    signal_a = pair["signal_a"].copy()
    shared_key = f"test-dedup-{uuid.uuid4().hex[:10]}"
    signal_a["idempotency_key"] = shared_key

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # First submission
        resp_1 = await client.post("/api/v1/signals", json=signal_a)
        assert resp_1.status_code == 201
        data_1 = resp_1.json()
        signal_id_1 = data_1["signal_id"]
        assert data_1["is_duplicate"] is False

        # Second submission with same idempotency key
        signal_a_prime = pair["signal_a_prime"].copy()
        signal_a_prime["idempotency_key"] = shared_key
        resp_2 = await client.post("/api/v1/signals", json=signal_a_prime)
        assert resp_2.status_code == 200
        data_2 = resp_2.json()
        assert data_2["signal_id"] == signal_id_1
        assert data_2["is_duplicate"] is True

        # Verify listing shows only 1 signal with this key
        list_resp = await client.get("/api/v1/signals", params={"strategy_name": signal_a["strategy_name"]})
        assert list_resp.status_code == 200
        matching = [s for s in list_resp.json()["signals"] if s["idempotency_key"] == shared_key]
        assert len(matching) == 1


# =============================================================================
# 5. Status State Machine & Direct Mutation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_illegal_status_transition_rejected(test_app, fixtures_data):
    """
    Test that directly attempting an illegal state transition is rejected with 400.
    e.g. A VALIDATED signal cannot directly transition to COMPLETED.
    """
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["idempotency_key"] = f"test-illegal-trans-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Create signal (status -> VALIDATED)
        create_resp = await client.post("/api/v1/signals", json=payload)
        assert create_resp.status_code == 201
        signal_id = create_resp.json()["signal_id"]

        # Attempt illegal transition directly from VALIDATED to COMPLETED
        illegal_mutation = {
            "target_status": "COMPLETED",
            "reason": "Direct jump bypass attempt",
            "actor": "attacker",
        }
        trans_resp = await client.post(f"/api/v1/signals/{signal_id}/transition", json=illegal_mutation)
        assert trans_resp.status_code == 400
        data = trans_resp.json()
        assert data["status"] == "error"
        assert data["error_code"] == "ILLEGAL_STATUS_TRANSITION"
        assert "Illegal state transition" in data["message"]


@pytest.mark.asyncio
async def test_legal_status_transition_sequence(test_app, fixtures_data):
    """
    Test legitimate lifecycle progression through state machine:
    VALIDATED -> PENDING_APPROVAL -> APPROVED -> REJECTED (terminal)
    """
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["idempotency_key"] = f"test-legal-trans-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # 1. Ingest -> VALIDATED
        create_resp = await client.post("/api/v1/signals", json=payload)
        assert create_resp.status_code == 201
        signal_id = create_resp.json()["signal_id"]

        # 2. VALIDATED -> PENDING_APPROVAL
        step1 = await client.post(
            f"/api/v1/signals/{signal_id}/transition",
            json={"target_status": "PENDING_APPROVAL", "reason": "Requires risk review"},
        )
        assert step1.status_code == 200
        assert step1.json()["status"] == "PENDING_APPROVAL"

        # 3. PENDING_APPROVAL -> APPROVED
        step2 = await client.post(
            f"/api/v1/signals/{signal_id}/transition",
            json={"target_status": "APPROVED", "reason": "Risk officer sign-off", "actor": "risk_officer"},
        )
        assert step2.status_code == 200
        assert step2.json()["status"] == "APPROVED"

        # 4. APPROVED -> REJECTED
        step3 = await client.post(
            f"/api/v1/signals/{signal_id}/transition",
            json={"target_status": "REJECTED", "reason": "Market condition changed"},
        )
        assert step3.status_code == 200
        assert step3.json()["status"] == "REJECTED"


# =============================================================================
# 6. Simulated Mock Execution Tests
# =============================================================================

@pytest.mark.asyncio
async def test_simulated_mock_execution_lifecycle(test_app, fixtures_data):
    """
    Test Phase 2 simulated mock execution stub:
    Progresses signal through EXECUTING -> COMPLETED (Mock only, no real money).
    """
    payload = fixtures_data["valid_single_leg_equity_buy_market"].copy()
    payload["idempotency_key"] = f"test-mock-exec-{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as client:
        # Ingest
        create_resp = await client.post("/api/v1/signals", json=payload)
        signal_id = create_resp.json()["signal_id"]

        # Run mock executor
        exec_resp = await client.post(f"/api/v1/signals/{signal_id}/execute-mock?delay_seconds=0.01")
        assert exec_resp.status_code == 200
        res = exec_resp.json()
        assert res["success"] is True
        assert res["status"] == "COMPLETED"
        assert res["execution_result"]["is_mock"] is True

        # Verify audit trail contains full history
        sig_resp = await client.get(f"/api/v1/signals/{signal_id}")
        sig_data = sig_resp.json()
        statuses = [entry["status"] for entry in sig_data["status_history"]]
        assert "RECEIVED" in statuses
        assert "VALIDATED" in statuses
        assert "EXECUTING" in statuses
        assert "COMPLETED" in statuses
