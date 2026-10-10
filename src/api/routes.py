"""
FastAPI REST & WebSocket Route Controllers for Phase 2 Execution Engine.
Provides signal ingestion, execution state auditing, position queries, circuit-breaker
resets, and real-time market data streaming.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import structlog

from services.execution.mock_execution_engine import (
    FaultInjector,
    MockExecutionEngine,
    SimulatedBrokerClient,
)
from src.adapters.base import BaseBrokerAdapter
from src.core.config import ExecutionConfig, get_config
from src.database.execution_db import get_all_positions, get_events_for_signal
from src.database.signals_db import (
    get_signal_by_id,
    get_signal_by_idempotency_key,
    insert_signal_record,
    list_signals,
    transition_signal_status,
)
from src.engine.pending_signals import PendingSignalManager
from src.engine.sequence_parser import AsyncOrderQueueManager, ExecutionSequenceEngine
from src.engine.signal_state_machine import (
    InvalidStateTransitionError,
    build_audit_entry,
    execute_signal_mock,
)
from src.engine.tick_replay import SyntheticTickGenerator, WebSocketConnectionManager
from src.realtime import RealtimeWebSocketManager
from src.models.schemas import (
    ExecutionEventMessage,
    HealthLivenessResponse,
    LegProgressState,
    OrderExecutionSequence,
    PendingSignalListResponse,
    PendingSignalStatus,
    PendingSignalSummary,
    PositionStateModel,
    SignalApprovalRequest,
    SignalApprovalResponse,
    SignalProgressResponse,
    SignalRejectionRequest,
    SignalRejectionResponse,
    StrategyDefinitionModel,
    StrategyListResponse,
    StrategySignalPayload,
    SyntheticTickPayload,
    WebSocketEventType,
)
from src.models.signal_schema import (
    SignalIngestPayload,
    SignalStatus,
    SignalTransitionRequest,
)
from src.strategy_engine.models import UnderlyingIndex
from src.strategy_engine.service import get_supported_strategies
from src.models.square_off_models import (
    SquareOffAuditItem,
    SquareOffExecuteRequest,
    SquareOffExecuteResponse,
    SquareOffPrepareRequest,
    SquareOffPrepareResponse,
)
from src.services.square_off_service import SquareOffService

logger = structlog.get_logger("openalgo.api")

router = APIRouter(prefix="/api/v1", tags=["Execution Pipeline"])
root_router = APIRouter(tags=["Core API Foundation"])


# -----------------------------------------------------------------------------
# Dependency Injections (resolved from app.state)
# -----------------------------------------------------------------------------

def get_sequence_engine(request: Request) -> ExecutionSequenceEngine:
    return request.app.state.sequence_engine


def get_queue_manager(request: Request) -> AsyncOrderQueueManager:
    return request.app.state.queue_manager


def get_broker_adapter(request: Request) -> BaseBrokerAdapter:
    return request.app.state.broker_adapter


def get_ws_manager(request: Request) -> WebSocketConnectionManager:
    return request.app.state.ws_manager


def get_realtime_ws_manager(request: Request) -> RealtimeWebSocketManager:
    if hasattr(request.app.state, "realtime_ws_manager"):
        return request.app.state.realtime_ws_manager
    if not hasattr(request.app.state, "_default_realtime_ws_mgr"):
        from src.realtime import RealtimeWebSocketManager as RWSMgr
        request.app.state._default_realtime_ws_mgr = RWSMgr()
    return request.app.state._default_realtime_ws_mgr


def get_tick_generator(request: Request) -> SyntheticTickGenerator:
    return request.app.state.tick_generator


def get_pending_manager(request: Request) -> PendingSignalManager:
    return request.app.state.pending_manager


def get_square_off_service(request: Request) -> SquareOffService:
    if hasattr(request.app.state, "square_off_service"):
        return request.app.state.square_off_service
    return SquareOffService(broker_adapter=get_broker_adapter(request))


# -----------------------------------------------------------------------------
# REST Signal Ingestion & Order Execution Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/signals/ingest",
    response_model=Dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Strategy Signal Webhook",
    description="Ingests JSON trade signals from Phase 1 Strategy Engine, validates Pydantic contracts, and executes with hedge-first sequencing or queues for approval.",
)
async def ingest_strategy_signal(
    payload: StrategySignalPayload,
    request: Request,
    sync: bool = Query(default=False, description="If true, executes synchronously and awaits full fulfillment"),
    requires_approval: Optional[bool] = Query(default=None, description="If true, routes to pending approval queue"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
    queue_mgr: AsyncOrderQueueManager = Depends(get_queue_manager),
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    ws_mgr: WebSocketConnectionManager = Depends(get_ws_manager),
) -> Dict[str, Any]:
    """
    Ingest a validated strategy signal from the Strategy Engine.
    """
    effective_requires_approval = (
        requires_approval if requires_approval is not None else payload.requires_approval
    )

    # -------------------------------------------------------------------------
    # Server-Side Active Account Resolution & Safety Guard
    # -------------------------------------------------------------------------
    from src.database.account_models import BrokerAccount, BrokerAccountStatus
    from src.services.account_service import get_active_account_selection, resolve_authenticated_user

    user_id = resolve_authenticated_user(request) if request else "default_user"
    active_account = get_active_account_selection(user_id) if user_id else None

    has_user_header = bool(request.headers.get("X-User-ID")) if request else False
    has_payload_account = bool(getattr(payload, "account_id", None) or (request.headers.get("X-Account-ID") if request else None))
    has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None

    if has_user_header or has_payload_account or has_accounts:
        if not active_account:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"NO_ACTIVE_ACCOUNT: No active broker account configured for user '{user_id}'.",
            )
        if active_account.status == BrokerAccountStatus.TOKEN_EXPIRED.value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOKEN_EXPIRED: Active broker account token has expired. Reconnection required.",
            )
        if active_account.status != BrokerAccountStatus.CONNECTED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ACTIVE_ACCOUNT_NOT_CONNECTED: Active account is in status '{active_account.status}'.",
            )
        if has_payload_account:
            req_acc = getattr(payload, "account_id", None) or (request.headers.get("X-Account-ID") if request else None)
            if req_acc != active_account.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"ACCOUNT_MISMATCH: Requested account '{req_acc}' does not match active account '{active_account.id}'.",
                )

    effective_account_id = active_account.id if active_account else None

    log = logger.bind(
        correlation_id=payload.correlation_id,
        signal_id=payload.signal_id,
        strategy=payload.strategy_name,
        signal_type=payload.signal_type.value,
        underlying=payload.underlying.value,
        legs_count=len(payload.legs),
        account_id=effective_account_id,
        sync=sync,
        requires_approval=effective_requires_approval,
    )
    log.info("signal_ingestion_received")

    if effective_requires_approval:
        # Route to pending approval queue
        summary = await pending_mgr.add_pending_signal(payload)
        await ws_mgr.broadcast_execution_event(
            ExecutionEventMessage(
                event_type=WebSocketEventType.ORDER_UPDATE,
                correlation_id=payload.correlation_id,
                data={
                    "event": "PENDING_SIGNAL_CREATED",
                    "signal": summary.model_dump(mode="json"),
                },
            )
        )
        return {
            "status": "PENDING_APPROVAL",
            "signal_id": payload.signal_id,
            "correlation_id": payload.correlation_id,
            "message": "Signal accepted and enqueued for manual trader approval",
            "summary": summary.model_dump(mode="json"),
        }

    if sync:
        # Synchronous execution mode
        import inspect
        sig = inspect.signature(engine.execute_signal)
        if "account_id" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            sequence: OrderExecutionSequence = await engine.execute_signal(payload, account_id=effective_account_id)
        else:
            sequence: OrderExecutionSequence = await engine.execute_signal(payload)

        return {
            "status": "COMPLETED",
            "sequence_id": sequence.sequence_id,
            "signal_id": payload.signal_id,
            "correlation_id": payload.correlation_id,
            "execution_status": sequence.status,
            "completed_legs": sequence.completed_legs,
            "total_legs": sequence.total_legs,
            "sequence": sequence.model_dump(mode="json"),
        }
    else:
        # Asynchronous queued mode (default)
        await queue_mgr.enqueue_signal(payload)
        return {
            "status": "QUEUED",
            "signal_id": payload.signal_id,
            "correlation_id": payload.correlation_id,
            "message": "Signal accepted and enqueued for sequential execution",
        }


@router.post(
    "/signals",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
    summary="Ingest Strategy Signal",
    description="Strictly validates, persists, and deduplicates strategy signals. Returns 201 on success or 200 on duplicate.",
)
async def ingest_signals_endpoint(
    request: Request,
    sync: bool = Query(default=False, description="Legacy sync execution flag"),
    requires_approval: Optional[bool] = Query(default=None, description="Legacy approval queue flag"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
    queue_mgr: AsyncOrderQueueManager = Depends(get_queue_manager),
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    ws_mgr: WebSocketConnectionManager = Depends(get_ws_manager),
) -> Any:
    try:
        raw_body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "INVALID_JSON",
                "message": "Malformed JSON in request body",
                "errors": [{"field": "body", "reason": "Malformed JSON body", "rejected_value": None}],
            },
        )

    # Backward compatibility with Phase 1 / API Foundation test suites using StrategySignalPayload
    if sync or (isinstance(raw_body, dict) and "regime" in raw_body and "instrument" not in raw_body and "idempotency_key" not in raw_body and "client_signal_id" not in raw_body):
        try:
            legacy_payload = StrategySignalPayload.model_validate(raw_body)
            legacy_res = await ingest_strategy_signal(
                payload=legacy_payload,
                request=request,
                sync=sync,
                requires_approval=requires_approval,
                engine=engine,
                queue_mgr=queue_mgr,
                pending_mgr=pending_mgr,
                ws_mgr=ws_mgr,
            )
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=legacy_res)
        except ValidationError:
            pass

    # Strict Validation against Phase 2 SignalIngestPayload
    try:
        payload = SignalIngestPayload.model_validate(raw_body)
    except ValidationError as e:
        structured_errors = []
        safe_log_errors = []
        for err in e.errors():
            loc = err.get("loc", ())
            field_parts = [str(x) for x in loc if x != "body"]
            field_name = ".".join(field_parts) if field_parts else "payload"
            reason = err.get("msg", "Validation error")
            rejected_val = err.get("input")

            # Redact secrets or sensitive fields
            if any(k in field_name.lower() for k in ("secret", "token", "password", "key", "auth", "credential")):
                rejected_val = "***REDACTED***"

            structured_errors.append({
                "field": field_name,
                "reason": reason,
                "rejected_value": rejected_val,
            })
            safe_log_errors.append({
                "field": field_name,
                "reason": reason,
            })

        logger.warn(
            "signal_validation_failed",
            error_count=len(structured_errors),
            errors=safe_log_errors,
        )

        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            content={
                "status": "error",
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "message": "Signal schema validation failed",
                "errors": structured_errors,
                "validation_errors": structured_errors,
            },
        )

    # Duplicate Prevention (Idempotency Check)
    existing = get_signal_by_idempotency_key(payload.idempotency_key)
    if existing:
        logger.info(
            "duplicate_signal_hit",
            signal_id=existing.signal_id,
            idempotency_key=payload.idempotency_key,
            strategy_name=payload.strategy_name,
            current_status=existing.status,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "signal_id": existing.signal_id,
                "status": existing.status,
                "received_at": existing.created_at.isoformat(),
                "is_duplicate": True,
                "message": "Duplicate signal detected; returned existing record idempotently",
            },
        )

    # Assign unique ID & log receipt
    signal_id = f"sig_{uuid.uuid4().hex}"

    logger.info(
        "signal_received",
        signal_id=signal_id,
        strategy_name=payload.strategy_name,
        underlying=payload.underlying,
        instrument=payload.instrument.value,
        action=payload.action.value,
        quantity=payload.quantity,
        execution_sequence=payload.execution_sequence,
    )

    now = datetime.utcnow()
    status_history = [
        build_audit_entry(SignalStatus.RECEIVED, actor="system", reason="Signal received by ingestion endpoint", timestamp=now),
        build_audit_entry(SignalStatus.VALIDATED, actor="system", reason="Signal schema validation passed", timestamp=now),
    ]

    record_data = {
        "signal_id": signal_id,
        "idempotency_key": payload.idempotency_key,
        "strategy_name": payload.strategy_name,
        "underlying": payload.underlying,
        "instrument": payload.instrument.value,
        "action": payload.action.value,
        "quantity": payload.quantity,
        "order_type": payload.order_type.value,
        "price": payload.price,
        "trigger_price": payload.trigger_price,
        "execution_sequence": payload.execution_sequence,
        "status": SignalStatus.VALIDATED.value,
        "strike": payload.strike,
        "expiry": payload.expiry,
        "option_type": payload.option_type.value if payload.option_type else None,
        "legs_json": json.dumps([leg.model_dump(mode="json") for leg in payload.legs]) if payload.legs else None,
        "metadata_json": json.dumps(payload.metadata) if payload.metadata else None,
        "payload_json": payload.model_dump_json(),
        "status_history_json": json.dumps(status_history),
        "created_at": now,
        "updated_at": now,
    }

    record, is_created = insert_signal_record(record_data)
    if not is_created:
        logger.info(
            "duplicate_signal_race_condition",
            signal_id=record.signal_id,
            idempotency_key=payload.idempotency_key,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "signal_id": record.signal_id,
                "status": record.status,
                "received_at": record.created_at.isoformat(),
                "is_duplicate": True,
                "message": "Duplicate signal detected; returned existing record idempotently",
            },
        )

    logger.info(
        "signal_status_transitioned",
        signal_id=signal_id,
        from_status=SignalStatus.RECEIVED.value,
        to_status=SignalStatus.VALIDATED.value,
        actor="system",
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={
            "signal_id": signal_id,
            "status": SignalStatus.VALIDATED.value,
            "received_at": record.created_at.isoformat(),
            "is_duplicate": False,
        },
    )


@router.get(
    "/signals",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="List and Filter Signals",
    description="Lists ingested signals with optional filtering by status, underlying, and strategy_name.",
)
async def list_signals_endpoint(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (RECEIVED, VALIDATED, APPROVED, etc.)"),
    underlying: Optional[str] = Query(default=None, description="Filter by underlying (NIFTY, BANKNIFTY, etc.)"),
    strategy_name: Optional[str] = Query(default=None, description="Filter by strategy_name"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> Dict[str, Any]:
    records, total_count = list_signals(
        status=status_filter,
        underlying=underlying,
        strategy_name=strategy_name,
        limit=limit,
        offset=offset,
    )
    return {
        "success": True,
        "count": total_count,
        "returned": len(records),
        "signals": records,
    }


@router.get(
    "/signals/pending",
    response_model=PendingSignalListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Pending Trade Signals",
    description="Retrieves active and recent signals in the approval queue with computed TTL and risk metadata.",
)
async def list_pending_signals(
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by status (PENDING, APPROVED, REJECTED, EXPIRED, FAILED)"),
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
) -> PendingSignalListResponse:
    signals = await pending_mgr.get_all_signals(status=status_filter)
    return PendingSignalListResponse(
        success=True,
        count=len(signals),
        signals=signals,
        timestamp=datetime.utcnow(),
    )


@router.post(
    "/signals/{signal_id}/approve",
    response_model=SignalApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve and Execute Pending Trade Signal",
    description="Atomically transitions signal state and dispatches it through the validated execution pipeline.",
)
async def approve_pending_signal(
    signal_id: str,
    request: Request,
    request_data: Optional[SignalApprovalRequest] = None,
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> SignalApprovalResponse:
    actor = request_data.actor if request_data and request_data.actor else "dashboard-trader"

    # Step a: Load signal and Authorization check
    from src.database.pending_signals_db import get_pending_signal_by_id, update_signal_record
    rec = get_pending_signal_by_id(signal_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending signal {signal_id} not found",
        )

    from src.services.account_service import get_active_account_selection, resolve_authenticated_user
    user_id = resolve_authenticated_user(request) if request else "default_user"

    if rec.user_id and rec.user_id != user_id:
        logger.warn(
            "unauthorized_approval_attempt",
            signal_id=signal_id,
            requesting_user=user_id,
            owner_user=rec.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"FORBIDDEN_USER: User '{user_id}' is not authorized to approve signal '{signal_id}' owned by '{rec.user_id}'.",
        )

    # Step b: Pre-transition State Check (fail-fast)
    now = datetime.utcnow()
    if pending_mgr._is_record_expired(rec, now):
        update_signal_record(signal_id, status=PendingSignalStatus.EXPIRED.value)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SIGNAL_EXPIRED: Signal {signal_id} has expired and cannot be approved (current_status='EXPIRED').",
        )

    if rec.status in (
        PendingSignalStatus.APPROVED.value,
        PendingSignalStatus.REJECTED.value,
        PendingSignalStatus.FAILED.value,
        PendingSignalStatus.EXPIRED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is already in a terminal state ('{rec.status}'), expected 'PENDING_APPROVAL'.",
        )

    if rec.status not in (PendingSignalStatus.PENDING.value, "PENDING_APPROVAL"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is in status '{rec.status}', expected 'PENDING_APPROVAL'.",
        )

    # Step c: Active Account Check BEFORE transitioning state (fail-fast)
    effective_account_id = None
    if request:
        from src.database.account_models import BrokerAccount, BrokerAccountStatus

        active_account = get_active_account_selection(user_id)
        has_user_header = bool(request.headers.get("X-User-ID"))
        has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None

        if has_user_header or has_accounts:
            if not active_account:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"NO_ACTIVE_ACCOUNT: No active broker account configured for user '{user_id}'.",
                )
            if active_account.status == BrokerAccountStatus.TOKEN_EXPIRED.value:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="TOKEN_EXPIRED: Active broker account token has expired. Reconnection required.",
                )
            if active_account.status != BrokerAccountStatus.CONNECTED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"ACTIVE_ACCOUNT_NOT_CONNECTED: Active account is in status '{active_account.status}'.",
                )
        if active_account:
            effective_account_id = active_account.id

    # Step d: Atomic CAS state transition & Race Protection
    success, reason, payload = await pending_mgr.prepare_for_approval(
        signal_id=signal_id, actor=actor, user_id=user_id
    )

    if not success:
        if reason == "NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pending signal {signal_id} not found")
        elif reason == "SIGNAL_EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SIGNAL_EXPIRED: Signal {signal_id} has expired and cannot be approved (current_status='EXPIRED')",
            )
        elif reason in ("CONFLICT", "ALREADY_TERMINAL", "SIGNAL_NOT_PENDING_APPROVAL"):
            latest_rec = get_pending_signal_by_id(signal_id)
            current_status = latest_rec.status if latest_rec else "UNKNOWN"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is in status '{current_status}', expected 'PENDING_APPROVAL' (already processed or concurrent race prevented)",
            )
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot approve signal: {reason}")

    # Step e: Execute through canonical pipeline
    try:
        import inspect
        sig = inspect.signature(engine.execute_signal)
        if "account_id" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            sequence: OrderExecutionSequence = await engine.execute_signal(payload, account_id=effective_account_id)
        else:
            sequence: OrderExecutionSequence = await engine.execute_signal(payload)

        if sequence.status in ("ABORTED_CIRCUIT_BREAKER", "FAILED") or sequence.circuit_breaker_triggered:
            err_msg = sequence.error_summary or f"Execution halted with status {sequence.status}"
            await pending_mgr.finalize_failure(
                signal_id=signal_id,
                error_message=err_msg,
                sequence_id=sequence.sequence_id,
                user_id=user_id,
            )
            return SignalApprovalResponse(
                success=False,
                signal_id=signal_id,
                status="FAILED",
                sequence_id=sequence.sequence_id,
                approved_at=now,
                approved_by=user_id,
                message=f"Signal approved but execution aborted by circuit breaker: {err_msg}",
                sequence=sequence.model_dump(mode="json"),
                timestamp=datetime.utcnow(),
            )
        else:
            await pending_mgr.finalize_approval(
                signal_id=signal_id,
                sequence_id=sequence.sequence_id,
                user_id=user_id,
            )
            return SignalApprovalResponse(
                success=True,
                signal_id=signal_id,
                status="APPROVED",
                sequence_id=sequence.sequence_id,
                approved_at=now,
                approved_by=user_id,
                message="Signal successfully approved and executed through sequential pipeline",
                sequence=sequence.model_dump(mode="json"),
                timestamp=datetime.utcnow(),
            )
    except Exception as e:
        logger.error("execution_failed_on_approved_signal", signal_id=signal_id, error=str(e))
        await pending_mgr.finalize_failure(
            signal_id=signal_id,
            error_message=str(e),
            user_id=user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Execution pipeline failed during order placement: {str(e)}",
        )


@router.post(
    "/signals/{signal_id}/reject",
    response_model=SignalRejectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject Pending Trade Signal",
    description="Transitions signal to terminal REJECTED state for audit without sending orders to broker.",
)
async def reject_pending_signal(
    signal_id: str,
    request: Request,
    request_data: Optional[SignalRejectionRequest] = None,
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
) -> SignalRejectionResponse:
    reason = request_data.reason if request_data and request_data.reason else "Manual rejection from trader dashboard"
    actor = request_data.actor if request_data and request_data.actor else "dashboard-trader"

    # Step a: Load signal and Authorization check
    from src.database.pending_signals_db import get_pending_signal_by_id, update_signal_record
    rec = get_pending_signal_by_id(signal_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Pending signal {signal_id} not found",
        )

    from src.services.account_service import resolve_authenticated_user
    user_id = resolve_authenticated_user(request) if request else "default_user"

    if rec.user_id and rec.user_id != user_id:
        logger.warn(
            "unauthorized_rejection_attempt",
            signal_id=signal_id,
            requesting_user=user_id,
            owner_user=rec.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"FORBIDDEN_USER: User '{user_id}' is not authorized to reject signal '{signal_id}' owned by '{rec.user_id}'.",
        )

    # Step b: Pre-transition State Check (fail-fast)
    now = datetime.utcnow()
    if pending_mgr._is_record_expired(rec, now):
        update_signal_record(signal_id, status=PendingSignalStatus.EXPIRED.value)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signal {signal_id} has expired",
        )

    if rec.status in (
        PendingSignalStatus.APPROVED.value,
        PendingSignalStatus.REJECTED.value,
        PendingSignalStatus.FAILED.value,
        PendingSignalStatus.EXPIRED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is already in a terminal state ('{rec.status}'), expected 'PENDING_APPROVAL'",
        )

    if rec.status not in (PendingSignalStatus.PENDING.value, "PENDING_APPROVAL", "VALIDATED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is in status '{rec.status}', expected 'PENDING_APPROVAL'",
        )

    # Step c: Atomic CAS transition & duplicate-click race protection
    sanitized_reason = reason[:500] if reason else "Manual rejection from trader dashboard"
    success, res_code = await pending_mgr.reject_signal(
        signal_id=signal_id,
        reason=sanitized_reason,
        actor=actor,
        user_id=user_id,
    )

    if not success:
        if res_code == "NOT_FOUND":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pending signal {signal_id} not found")
        elif res_code == "SIGNAL_EXPIRED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Signal {signal_id} has expired")
        elif res_code in ("CONFLICT", "ALREADY_TERMINAL", "SIGNAL_NOT_PENDING_APPROVAL"):
            latest_rec = get_pending_signal_by_id(signal_id)
            current_status = latest_rec.status if latest_rec else "UNKNOWN"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"SIGNAL_NOT_PENDING_APPROVAL: Signal {signal_id} is in status '{current_status}', expected 'PENDING_APPROVAL' (already processed or race prevented)",
            )
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Cannot reject signal: {res_code}")

    # Step d: Structural isolation — NO call to engine.execute_signal
    return SignalRejectionResponse(
        success=True,
        signal_id=signal_id,
        status="REJECTED",
        reason=sanitized_reason,
        actor=actor,
        rejected_by=user_id,
        rejected_at=datetime.utcnow(),
        message="Signal rejected and archived without execution",
    )


@router.get(
    "/signals/{signal_id}/progress",
    response_model=SignalProgressResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Signal Execution Progress",
    description="Returns overall signal status, per-leg execution progress, timestamps, and full event audit trail.",
)
async def get_signal_progress(
    signal_id: str,
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> SignalProgressResponse:
    from src.database.pending_signals_db import get_pending_signal_by_id
    rec = get_pending_signal_by_id(signal_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal {signal_id} not found",
        )

    seq = None
    if rec.sequence_id:
        seq = await engine.get_sequence(rec.sequence_id)
    if not seq:
        async with engine._lock:
            for s in engine._history.values():
                if s.signal_id == signal_id:
                    seq = s
                    break

    legs: List[LegProgressState] = []
    if seq and seq.leg_states:
        for st in seq.leg_states:
            action_val = st.action.value if hasattr(st.action, "value") else str(st.action)
            status_val = st.status.value if hasattr(st.status, "value") else str(st.status)
            legs.append(
                LegProgressState(
                    leg_id=st.leg_id,
                    symbol=st.symbol,
                    action=action_val,
                    status=status_val,
                    order_id=st.order_id,
                    strike=st.strike,
                    quantity=st.quantity,
                    filled_quantity=st.filled_quantity,
                    requested_price=st.requested_price,
                    execution_price=st.execution_price,
                    placed_at=st.placed_at.isoformat() if st.placed_at else None,
                    updated_at=st.updated_at.isoformat() if st.updated_at else None,
                    error_message=st.error_message,
                )
            )
    elif rec.payload_json:
        try:
            raw_payload = json.loads(rec.payload_json)
            raw_legs = raw_payload.get("legs", [])
            for idx, rleg in enumerate(raw_legs):
                l_action = rleg.get("action", "BUY")
                if hasattr(l_action, "value"):
                    l_action = l_action.value
                l_status = "PENDING"
                if rec.status == "REJECTED":
                    l_status = "REJECTED"
                elif rec.status == "FAILED":
                    l_status = "FAILED"
                elif rec.status == "APPROVED":
                    l_status = "FILLED"
                legs.append(
                    LegProgressState(
                        leg_id=str(rleg.get("leg_id", idx + 1)),
                        symbol=rleg.get("symbol", f"{rec.underlying}-LEG-{idx+1}"),
                        action=str(l_action),
                        status=l_status,
                        order_id=None,
                        strike=float(rleg.get("strike", 0.0)),
                        quantity=int(rleg.get("quantity", 0)),
                        filled_quantity=int(rleg.get("quantity", 0)) if rec.status == "APPROVED" else 0,
                        requested_price=float(rleg.get("price", 0.0)),
                        execution_price=float(rleg.get("price", 0.0)) if rec.status == "APPROVED" else 0.0,
                        placed_at=rec.created_at.isoformat() if rec.created_at else None,
                        updated_at=rec.created_at.isoformat() if rec.created_at else None,
                        error_message=rec.error_message,
                    )
                )
        except Exception:
            pass

    history = json.loads(rec.status_history_json) if rec.status_history_json else []
    events_records = get_events_for_signal(signal_id)
    events = [e.to_dict() for e in events_records]

    return SignalProgressResponse(
        signal_id=signal_id,
        status=rec.status,
        sequence_id=rec.sequence_id,
        strategy_name=rec.strategy_name,
        underlying=rec.underlying,
        user_id=rec.user_id,
        approved_at=rec.approved_at.isoformat() if rec.approved_at else None,
        approved_by=rec.approved_by,
        rejected_at=rec.rejected_at.isoformat() if rec.rejected_at else None,
        rejected_by=rec.rejected_by,
        rejection_reason=rec.rejection_reason,
        error_message=rec.error_message,
        legs=legs,
        status_history=history,
        events=events,
        timestamp=datetime.utcnow(),
    )


# Root router aliases for transparent path resolution
root_router.add_api_route(
    "/signals/{signal_id}/approve",
    approve_pending_signal,
    methods=["POST"],
    response_model=SignalApprovalResponse,
    include_in_schema=False,
)
root_router.add_api_route(
    "/signals/{signal_id}/reject",
    reject_pending_signal,
    methods=["POST"],
    response_model=SignalRejectionResponse,
    include_in_schema=False,
)
root_router.add_api_route(
    "/signals/{signal_id}/progress",
    get_signal_progress,
    methods=["GET"],
    response_model=SignalProgressResponse,
    include_in_schema=False,
)



@router.get(
    "/signals/{signal_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get Strategy Signal Details",
    description="Retrieves a signal record, its current status, and full transition history audit trail.",
)
async def get_signal_endpoint(signal_id: str) -> Dict[str, Any]:
    record = get_signal_by_id(signal_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    return record.to_dict()


@router.post(
    "/signals/{signal_id}/transition",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Transition Signal Status",
    description="Explicitly transitions signal status according to the state machine rules.",
)
async def transition_signal_endpoint(
    signal_id: str,
    body: SignalTransitionRequest,
) -> Dict[str, Any]:
    record = get_signal_by_id(signal_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )
    try:
        prev_status = record.status
        updated = transition_signal_status(
            signal_id=signal_id,
            target_status=body.target_status,
            actor=body.actor or "system",
            reason=body.reason or "Status transition requested",
        )
        logger.info(
            "signal_status_transitioned",
            signal_id=signal_id,
            from_status=prev_status,
            to_status=body.target_status.value,
            actor=body.actor,
            reason=body.reason,
        )
        return updated.to_dict()
    except InvalidStateTransitionError as e:
        logger.warn(
            "illegal_state_transition_attempted",
            signal_id=signal_id,
            current_status=record.status,
            target_status=body.target_status.value,
            error=str(e),
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "ILLEGAL_STATUS_TRANSITION",
                "message": str(e),
            },
        )


@router.post(
    "/signals/{signal_id}/execute",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Execute Signal via Mock Execution Engine",
    description="Consumes an APPROVED/VALIDATED signal and executes it leg-by-leg through the MockExecutionEngine.",
)
async def execute_signal_endpoint(
    signal_id: str,
    force_failure_leg: Optional[str] = Query(default=None, description="Optional leg_id to inject failure on"),
    reject_leg: Optional[str] = Query(default=None, description="Optional leg_id to inject rejection on"),
) -> Dict[str, Any]:
    record = get_signal_by_id(signal_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )

    faults = None
    if force_failure_leg or reject_leg:
        fail_set = {force_failure_leg} if force_failure_leg else set()
        reject_dict = {reject_leg: "Simulated broker rejection"} if reject_leg else {}
        faults = FaultInjector(fail_legs=fail_set, reject_legs=reject_dict)

    engine = MockExecutionEngine()
    try:
        result = await engine.execute_signal(signal=record, fault_injector=faults)
        return result.model_dump(mode="json")
    except InvalidStateTransitionError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "ILLEGAL_STATUS_TRANSITION",
                "message": str(e),
            },
        )


@router.post(
    "/signals/{signal_id}/execute-mock",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Simulate Signal Execution (Stub / Mock Only)",
    description="Simulates downstream execution and transitions signal through EXECUTING to COMPLETED/FAILED. (NO REAL MONEY)",
)
async def execute_mock_signal_endpoint(
    signal_id: str,
    force_failure: bool = Query(default=False, description="Simulate execution failure"),
    delay_seconds: float = Query(default=0.01, description="Simulated execution delay in seconds"),
) -> Dict[str, Any]:
    record = get_signal_by_id(signal_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Signal '{signal_id}' not found",
        )

    faults = None
    if force_failure:
        raw = json.loads(record.payload_json) if record.payload_json else {}
        legs = raw.get("legs", [])
        fail_id = legs[0]["leg_id"] if legs else raw.get("leg_id", "leg_1")
        faults = FaultInjector(fail_legs={fail_id})

    broker_client = SimulatedBrokerClient(delay_seconds=delay_seconds)
    engine = MockExecutionEngine(broker_client=broker_client)
    try:
        result = await engine.execute_signal(signal=record, fault_injector=faults)
        refreshed_rec = get_signal_by_id(signal_id)
        return {
            "success": result.status == SignalStatus.COMPLETED,
            "signal_id": signal_id,
            "status": result.status.value,
            "execution_result": result.model_dump(mode="json"),
            "signal": refreshed_rec.to_dict() if refreshed_rec else record.to_dict(),
        }
    except InvalidStateTransitionError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "status": "error",
                "error_code": "ILLEGAL_STATUS_TRANSITION",
                "message": f"Cannot execute signal from status {record.status}: {str(e)}",
            },
        )


@router.get(
    "/signals/{signal_id}/events",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Get Signal Execution Events",
    description="Chronological audit log of all order lifecycle events and position changes for a signal.",
)
async def get_signal_events_endpoint(signal_id: str) -> Dict[str, Any]:
    events = get_events_for_signal(signal_id)
    return {
        "signal_id": signal_id,
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.get(
    "/mock/positions",
    response_model=List[Dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="List Mock Simulated Positions",
    description="Retrieves all simulated portfolio positions tracked by the MockExecutionEngine.",
)
async def get_mock_positions_endpoint(
    strategy_name: Optional[str] = Query(default=None, description="Filter by strategy_name"),
    underlying: Optional[str] = Query(default=None, description="Filter by underlying"),
) -> List[Dict[str, Any]]:
    positions = get_all_positions(strategy_name=strategy_name, underlying=underlying)
    return [p.to_dict() for p in positions]


@router.get(
    "/orders/{sequence_id}",
    response_model=Dict[str, Any],
    summary="Get Order Sequence Status",
)
async def get_order_sequence(
    sequence_id: str,
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> Dict[str, Any]:
    """Fetch status and leg details for a specific execution sequence."""
    seq = await engine.get_sequence(sequence_id)
    if not seq:
        logger.warn("order_sequence_not_found", sequence_id=sequence_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution sequence {sequence_id} not found",
        )
    return seq.model_dump(mode="json")


@router.get(
    "/orders",
    response_model=List[Dict[str, Any]],
    summary="List All Order Sequences",
)
async def list_all_order_sequences(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Optional account_id for explicit view"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> List[Dict[str, Any]]:
    """Retrieve full audit history of all execution sequences, scoped by active account."""
    from src.database.account_models import BrokerAccount
    from src.services.account_service import get_active_account_selection, resolve_authenticated_user, verify_account_ownership

    user_id = resolve_authenticated_user(request)
    target_account_id = None

    if account_id:
        # Explicit non-active view: verify ownership server-side!
        account = verify_account_ownership(user_id, account_id)
        target_account_id = account.id
    else:
        active_account = get_active_account_selection(user_id)
        has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None
        if (has_accounts or bool(request.headers.get("X-User-ID"))) and not active_account:
            return []
        target_account_id = active_account.id if active_account else None

    sequences = await engine.get_all_sequences(account_id=target_account_id)
    return [s.model_dump(mode="json") for s in sequences]


# -----------------------------------------------------------------------------
# Portfolio, Positions & Funds Endpoints
# -----------------------------------------------------------------------------

@router.get(
    "/positions",
    response_model=List[Dict[str, Any]],
    summary="Get Live Broker Positions & Greeks",
)
async def get_portfolio_positions(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Optional account_id for explicit view"),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> List[Dict[str, Any]]:
    """Retrieve open active positions and aggregate portfolio Greeks, scoped by active account."""
    from src.database.account_models import BrokerAccount
    from src.services.account_service import get_active_account_selection, resolve_authenticated_user, verify_account_ownership

    user_id = resolve_authenticated_user(request)
    target_account_id = None

    if account_id:
        account = verify_account_ownership(user_id, account_id)
        target_account_id = account.id
    else:
        active_account = get_active_account_selection(user_id)
        has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None
        if (has_accounts or bool(request.headers.get("X-User-ID"))) and not active_account:
            return []
        target_account_id = active_account.id if active_account else None

    positions = await broker.get_positions(account_id=target_account_id)
    return [p.model_dump(mode="json") for p in positions]


@router.post(
    "/positions/square-off/prepare",
    response_model=SquareOffPrepareResponse,
    summary="Prepare Emergency Square-Off",
    description="Step 1: Validates account match, checks connection, fetches live open positions, and generates single-use confirmation token (TTL 60s).",
)
async def prepare_emergency_square_off(
    request: Request,
    payload: Optional[SquareOffPrepareRequest] = None,
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    from src.services.account_service import resolve_authenticated_user
    user_id = resolve_authenticated_user(request)
    selected_account_id = payload.selected_account_id if payload else None
    return await square_off_svc.prepare_square_off(
        user_id=user_id,
        selected_account_id=selected_account_id,
        broker_adapter=broker,
    )


@router.post(
    "/positions/square-off/execute",
    response_model=SquareOffExecuteResponse,
    summary="Execute Emergency Square-Off",
    description="Step 2: Consumes confirmation token, verifies confirm phrase ('CONFIRM' or 'CLOSE ALL'), acquires in-flight lock, and executes exit orders independently.",
)
async def execute_emergency_square_off(
    request: Request,
    payload: SquareOffExecuteRequest,
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    from src.services.account_service import resolve_authenticated_user
    user_id = resolve_authenticated_user(request)
    return await square_off_svc.execute_square_off(
        user_id=user_id,
        confirmation_token=payload.confirmation_token,
        confirm_phrase=payload.confirm_phrase,
        selected_account_id=payload.selected_account_id,
        broker_adapter=broker,
    )


@router.get(
    "/positions/square-off/audit",
    response_model=List[Dict[str, Any]],
    summary="Get Square-Off Audit Trail",
    description="Retrieve durable audit logs for emergency square-off requests, blocked attempts, and execution outcomes.",
)
async def get_square_off_audit_trail(
    request: Request,
    account_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    square_off_svc: SquareOffService = Depends(get_square_off_service),
) -> List[Dict[str, Any]]:
    from src.services.account_service import resolve_authenticated_user
    user_id = resolve_authenticated_user(request)
    return square_off_svc.get_audit_trail(account_id=account_id, user_id=user_id, limit=limit)


@router.get(
    "/positions/square-off/{square_off_id}/progress",
    response_model=Dict[str, Any],
    summary="Get Emergency Square-Off Progress",
    description="Poll per-order execution progress for an ongoing or recently completed square-off batch.",
)
async def get_square_off_execution_progress(
    square_off_id: str,
    square_off_svc: SquareOffService = Depends(get_square_off_service),
) -> Dict[str, Any]:
    prog = square_off_svc.get_progress(square_off_id)
    if not prog:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Square-off session '{square_off_id}' not found.",
        )
    return prog


@router.post(
    "/positions/square-off-all",
    response_model=Dict[str, Any],
    summary="Square Off All Open Positions (Direct/Legacy)",
    description="Emergency liquidation of all open positions for the active account with full safety and audit.",
)
async def square_off_all_positions(
    request: Request,
    selected_account_id: Optional[str] = Query(default=None),
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    from src.services.account_service import resolve_authenticated_user
    user_id = resolve_authenticated_user(request)
    res = await square_off_svc.execute_direct(
        user_id=user_id,
        selected_account_id=selected_account_id,
        broker_adapter=broker,
    )
    return {
        "status": res["status"],
        "message": res["message"],
        "account_id": res["account_id"],
        "closed_count": res["filled_count"],
        "closed_positions": res["results"],
        "square_off_id": res["square_off_id"],
        "audit_id": res["audit_id"],
    }


@router.get(
    "/funds",
    response_model=Dict[str, Any],
    summary="Get Account Funds & Margin Status",
)
async def get_account_funds(
    request: Request = None,
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    """Retrieve account margin, cash balance, and leverage utilization."""
    target_account_id = None
    if request:
        from src.services.account_service import get_active_account_selection, resolve_authenticated_user
        user_id = resolve_authenticated_user(request)
        active_account = get_active_account_selection(user_id)
        if active_account:
            target_account_id = active_account.id

    return await broker.get_funds(account_id=target_account_id)


@router.post(
    "/circuit-breaker/reset",
    response_model=Dict[str, Any],
    summary="Reset Circuit Breaker & Clear Rejection States",
)
async def reset_circuit_breaker(
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    """Reset broker failure injection and re-arm the execution circuit breaker."""
    if hasattr(broker, "clear_injected_rejections"):
        broker.clear_injected_rejections()
    logger.info("circuit_breaker_reset_invoked")
    return {"status": "SUCCESS", "message": "Circuit breaker and broker failure states reset successfully"}


@router.post(
    "/ticks/single",
    response_model=Dict[str, Any],
    summary="Generate Single Synthetic Tick",
)
async def trigger_single_synthetic_tick(
    underlying: UnderlyingIndex = Query(default=UnderlyingIndex.NIFTY),
    tick_gen: SyntheticTickGenerator = Depends(get_tick_generator),
) -> Dict[str, Any]:
    """Manually trigger a synthetic tick generation and WebSocket broadcast."""
    tick = await tick_gen.generate_single_tick(underlying)
    return tick.model_dump(mode="json")


@router.get(
    "/health",
    response_model=Dict[str, Any],
    summary="Execution Engine Health Check",
)
async def health_check(
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
    config: ExecutionConfig = Depends(get_config),
) -> Dict[str, Any]:
    """Check API operational health and broker connectivity."""
    broker_healthy = await broker.health_check()
    return {
        "status": "healthy" if broker_healthy else "degraded",
        "broker_mode": config.broker_mode.value,
        "broker_connected": broker_healthy,
        "environment": config.environment,
    }


@router.get(
    "/health/liveness",
    response_model=HealthLivenessResponse,
    summary="Execution Engine Liveness Probe",
    description="Dependency-free HTTP worker health probe. Confirms process liveness without checking external broker/DB.",
)
async def liveness_check(
    config: ExecutionConfig = Depends(get_config),
) -> HealthLivenessResponse:
    """Dependency-free liveness probe for container orchestrators and monitoring."""
    return HealthLivenessResponse(
        status="healthy",
        service="openalgo-execution-engine",
        version="2.0.0",
        environment=config.environment,
    )


@router.get(
    "/strategies",
    response_model=StrategyListResponse,
    summary="List Supported Quantitative Options Strategies",
    description="Returns the full catalog of supported multi-leg options strategy structures with parameter metadata.",
)
async def list_supported_strategies() -> StrategyListResponse:
    """Retrieve supported quantitative strategies catalog."""
    logger.info("strategies_catalog_requested")
    return get_supported_strategies()


# -----------------------------------------------------------------------------
# WebSocket Endpoints (Phase 3 Dashboard Feeds)
# -----------------------------------------------------------------------------

@router.websocket("/ws/market-feed")
async def ws_market_feed(
    websocket: WebSocket,
    ws_mgr: WebSocketConnectionManager = Depends(get_ws_manager),
):
    """
    WebSocket endpoint streaming live/synthetic market ticks and option quotes to Phase 3 dashboard.
    """
    await ws_mgr.connect_market(websocket)
    try:
        while True:
            # Keep-alive receive loop
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_mgr.disconnect_market(websocket)
    except Exception as e:
        logger.warn("ws_market_feed_error", error=str(e))
        await ws_mgr.disconnect_market(websocket)


@router.websocket("/ws/executions")
async def ws_executions_feed(
    websocket: WebSocket,
    ws_mgr: WebSocketConnectionManager = Depends(get_ws_manager),
):
    """
    WebSocket endpoint streaming order executions, lifecycle states, position updates, and MTM alerts.
    """
    await ws_mgr.connect_execution(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_mgr.disconnect_execution(websocket)
    except Exception as e:
        logger.warn("ws_executions_feed_error", error=str(e))
        await ws_mgr.disconnect_execution(websocket)


@router.websocket("/ws/realtime")
@root_router.websocket("/ws/realtime")
async def ws_realtime_stream(
    websocket: WebSocket,
    manager: RealtimeWebSocketManager = Depends(get_realtime_ws_manager),
):
    """
    Unified Real-time WebSocket endpoint.
    Supports client subscriptions (market_tick, positions, pnl, orders, strategies)
    and delivers standardized { type, timestamp, source, payload } envelopes.
    """
    await websocket.accept()
    await manager.register(websocket)
    try:
        while True:
            text = await websocket.receive_text()
            await manager.handle_client_message(websocket, text)
    except WebSocketDisconnect:
        await manager.unregister(websocket)
    except Exception as e:
        logger.warn("ws_realtime_stream_error", error=str(e))
        await manager.unregister(websocket)


# -----------------------------------------------------------------------------
# Root Router Endpoints (Direct Path Aliases for Health, Signals, Orders, Positions, Strategies)
# -----------------------------------------------------------------------------

@root_router.get(
    "/health",
    response_model=HealthLivenessResponse,
    summary="Root Liveness Probe",
    description="Dependency-free system liveness probe returning service status, timestamp, and version.",
)
async def root_health_liveness(
    config: ExecutionConfig = Depends(get_config),
) -> HealthLivenessResponse:
    return HealthLivenessResponse(
        status="healthy",
        service="openalgo-execution-engine",
        version="2.0.0",
        environment=config.environment,
    )


@root_router.post(
    "/signals",
    response_model=Dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Root Signal Ingestion Webhook",
    description="Root alias for trade signal ingestion with hedge-first execution sequencing.",
)
async def root_signals_ingest(
    payload: StrategySignalPayload,
    request: Request,
    sync: bool = Query(default=False, description="If true, executes synchronously and awaits full fulfillment"),
    requires_approval: Optional[bool] = Query(default=None, description="If true, routes to pending approval queue"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
    queue_mgr: AsyncOrderQueueManager = Depends(get_queue_manager),
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    ws_mgr: WebSocketConnectionManager = Depends(get_ws_manager),
) -> Dict[str, Any]:
    return await ingest_strategy_signal(
        payload=payload,
        request=request,
        sync=sync,
        requires_approval=requires_approval,
        engine=engine,
        queue_mgr=queue_mgr,
        pending_mgr=pending_mgr,
        ws_mgr=ws_mgr,
    )


@root_router.get(
    "/signals/pending",
    response_model=PendingSignalListResponse,
    summary="Root List Pending Signals",
)
async def root_list_pending_signals(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
) -> PendingSignalListResponse:
    return await list_pending_signals(status_filter=status_filter, pending_mgr=pending_mgr)


@root_router.post(
    "/signals/{signal_id}/approve",
    response_model=SignalApprovalResponse,
    summary="Root Approve Pending Signal",
)
async def root_approve_pending_signal(
    signal_id: str,
    request: Request,
    request_data: Optional[SignalApprovalRequest] = None,
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> SignalApprovalResponse:
    return await approve_pending_signal(
        signal_id=signal_id,
        request=request,
        request_data=request_data,
        pending_mgr=pending_mgr,
        engine=engine,
    )


@root_router.post(
    "/signals/{signal_id}/reject",
    response_model=SignalRejectionResponse,
    summary="Root Reject Pending Signal",
)
async def root_reject_pending_signal(
    signal_id: str,
    request_data: Optional[SignalRejectionRequest] = None,
    pending_mgr: PendingSignalManager = Depends(get_pending_manager),
) -> SignalRejectionResponse:
    return await reject_pending_signal(
        signal_id=signal_id,
        request_data=request_data,
        pending_mgr=pending_mgr,
    )


@root_router.get(
    "/orders",
    response_model=List[Dict[str, Any]],
    summary="Root List All Orders",
    description="Root alias to retrieve full audit history of all execution sequences.",
)
async def root_list_orders(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Optional account_id for explicit view"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> List[Dict[str, Any]]:
    return await list_all_order_sequences(request=request, account_id=account_id, engine=engine)


@root_router.get(
    "/orders/{sequence_id}",
    response_model=Dict[str, Any],
    summary="Root Get Order Sequence Status",
    description="Root alias to fetch status and leg details for a specific execution sequence.",
)
async def root_get_order(
    sequence_id: str,
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> Dict[str, Any]:
    return await get_order_sequence(sequence_id=sequence_id, engine=engine)


@root_router.get(
    "/positions",
    response_model=List[Dict[str, Any]],
    summary="Root Get Live Positions",
    description="Root alias to retrieve open active positions and aggregate portfolio Greeks.",
)
async def root_get_positions(
    request: Request,
    account_id: Optional[str] = Query(default=None, description="Optional account_id for explicit view"),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> List[Dict[str, Any]]:
    return await get_portfolio_positions(request=request, account_id=account_id, broker=broker)


@root_router.post(
    "/positions/square-off/prepare",
    response_model=SquareOffPrepareResponse,
    summary="Root Prepare Emergency Square-Off",
)
async def root_prepare_square_off(
    request: Request,
    payload: Optional[SquareOffPrepareRequest] = None,
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    return await prepare_emergency_square_off(request=request, payload=payload, square_off_svc=square_off_svc, broker=broker)


@root_router.post(
    "/positions/square-off/execute",
    response_model=SquareOffExecuteResponse,
    summary="Root Execute Emergency Square-Off",
)
async def root_execute_square_off(
    request: Request,
    payload: SquareOffExecuteRequest,
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    return await execute_emergency_square_off(request=request, payload=payload, square_off_svc=square_off_svc, broker=broker)


@root_router.post(
    "/positions/square-off-all",
    response_model=Dict[str, Any],
    summary="Root Square Off All Open Positions",
)
async def root_square_off_all(
    request: Request,
    selected_account_id: Optional[str] = Query(default=None),
    square_off_svc: SquareOffService = Depends(get_square_off_service),
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    return await square_off_all_positions(request=request, selected_account_id=selected_account_id, square_off_svc=square_off_svc, broker=broker)


@root_router.get(
    "/strategies",
    response_model=StrategyListResponse,
    summary="Root List Quantitative Strategies",
    description="Root alias to retrieve the catalog of supported quantitative strategies.",
)
async def root_get_strategies() -> StrategyListResponse:
    return get_supported_strategies()
