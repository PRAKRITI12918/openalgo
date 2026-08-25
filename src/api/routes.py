"""
FastAPI REST & WebSocket Route Controllers for Phase 2 Execution Engine.
Provides signal ingestion, execution state auditing, position queries, circuit-breaker
resets, and real-time market data streaming.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
import structlog

from src.adapters.base import BaseBrokerAdapter
from src.core.config import ExecutionConfig, get_config
from src.engine.sequence_parser import AsyncOrderQueueManager, ExecutionSequenceEngine
from src.engine.tick_replay import SyntheticTickGenerator, WebSocketConnectionManager
from src.models.schemas import (
    OrderExecutionSequence,
    PositionStateModel,
    StrategySignalPayload,
    SyntheticTickPayload,
)
from src.strategy_engine.models import UnderlyingIndex

logger = structlog.get_logger("openalgo.api")

router = APIRouter(prefix="/api/v1", tags=["Execution Pipeline"])


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


def get_tick_generator(request: Request) -> SyntheticTickGenerator:
    return request.app.state.tick_generator


# -----------------------------------------------------------------------------
# REST Signal Ingestion & Order Execution Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/signals/ingest",
    response_model=Dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Strategy Signal Webhook",
    description="Ingests JSON trade signals from Phase 1 Strategy Engine, validates Pydantic contracts, and executes with hedge-first sequencing.",
)
async def ingest_strategy_signal(
    payload: StrategySignalPayload,
    sync: bool = Query(default=False, description="If true, executes synchronously and awaits full fulfillment"),
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
    queue_mgr: AsyncOrderQueueManager = Depends(get_queue_manager),
) -> Dict[str, Any]:
    """
    Ingest a validated strategy signal from the Strategy Engine.
    """
    log = logger.bind(
        correlation_id=payload.correlation_id,
        signal_id=payload.signal_id,
        strategy=payload.strategy_name,
        signal_type=payload.signal_type.value,
        underlying=payload.underlying.value,
        legs_count=len(payload.legs),
        sync=sync,
    )
    log.info("signal_ingestion_received")

    if sync:
        # Synchronous execution mode
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
    engine: ExecutionSequenceEngine = Depends(get_sequence_engine),
) -> List[Dict[str, Any]]:
    """Retrieve full audit history of all execution sequences."""
    sequences = await engine.get_all_sequences()
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
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> List[Dict[str, Any]]:
    """Retrieve open active positions and aggregate portfolio Greeks."""
    positions = await broker.get_positions()
    return [p.model_dump(mode="json") for p in positions]


@router.get(
    "/funds",
    response_model=Dict[str, Any],
    summary="Get Account Funds & Margin Status",
)
async def get_account_funds(
    broker: BaseBrokerAdapter = Depends(get_broker_adapter),
) -> Dict[str, Any]:
    """Retrieve account margin, cash balance, and leverage utilization."""
    return await broker.get_funds()


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
