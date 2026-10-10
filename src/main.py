"""
Main FastAPI Application Entry Point for Phase 2 Execution Engine.
Configures lifecycle management, structured logging, CORS, custom 422 error logging,
and initializes background queue workers and synthetic market feeds.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
import time
from typing import Any, AsyncGenerator, Dict, Optional
import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import structlog

from src.adapters.factory import create_broker_adapter
from src.api.account_routes import account_router
from src.api.routes import root_router, router
from src.core.config import ExecutionConfig, get_config, setup_logger
from src.database.account_models import init_account_db
from src.database.execution_db import init_execution_db
from src.database.signals_db import init_signals_db
from src.engine.pending_signals import PendingSignalManager
from src.engine.sequence_parser import AsyncOrderQueueManager, ExecutionSequenceEngine
from src.engine.tick_replay import SyntheticTickGenerator, WebSocketConnectionManager
from src.realtime import FeedSource, RealtimeWebSocketManager
from src.services.square_off_service import SquareOffService

logger = structlog.get_logger("openalgo.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager for setup and graceful shutdown of background services.
    """
    config: ExecutionConfig = getattr(app.state, "config", get_config())
    setup_logger(config)
    logger.info("starting_execution_engine_service", env=config.environment, broker_mode=config.broker_mode.value)

    # Start Queue Worker
    if hasattr(app.state, "queue_manager"):
        await app.state.queue_manager.start()

    # Start Synthetic Market Tick Generator (skip automatic loop if in test mode)
    if hasattr(app.state, "tick_generator") and config.environment.lower() != "test":
        await app.state.tick_generator.start()

    logger.info("execution_engine_backend_pipeline_online")

    try:
        yield
    finally:
        logger.info("initiating_execution_engine_graceful_shutdown")
        if hasattr(app.state, "tick_generator"):
            await app.state.tick_generator.stop()
        if hasattr(app.state, "queue_manager"):
            await app.state.queue_manager.stop()
        logger.info("execution_engine_shutdown_complete")


def create_app(config: Optional[ExecutionConfig] = None) -> FastAPI:
    """
    FastAPI Application Factory.
    """
    cfg = config or get_config()

    app = FastAPI(
        title="OpenAlgo Quantitative Execution Engine",
        description="Phase 2 Execution Engine & Backend Pipeline for Multi-Leg Options Trading & Risk Management",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Initialize State Components
    app.state.config = cfg
    broker_adapter = create_broker_adapter(cfg.broker_mode, config=cfg)
    app.state.broker_adapter = broker_adapter

    ws_manager = WebSocketConnectionManager()
    app.state.ws_manager = ws_manager

    realtime_ws_manager = RealtimeWebSocketManager(
        feed_source=FeedSource.MOCK if cfg.broker_mode.value.upper() in ("MOCK", "SIMULATED") else (FeedSource.SANDBOX if "SANDBOX" in cfg.broker_mode.value.upper() or "PAPER" in cfg.broker_mode.value.upper() else FeedSource.LIVE)
    )
    app.state.realtime_ws_manager = realtime_ws_manager

    square_off_service = SquareOffService(
        broker_adapter=broker_adapter,
        event_broadcaster=ws_manager.broadcast_execution_event,
    )
    app.state.square_off_service = square_off_service

    sequence_engine = ExecutionSequenceEngine(
        broker_adapter=broker_adapter,
        config=cfg,
        event_broadcaster=ws_manager.broadcast_execution_event,
    )
    app.state.sequence_engine = sequence_engine

    queue_manager = AsyncOrderQueueManager(engine=sequence_engine)
    app.state.queue_manager = queue_manager

    pending_manager = PendingSignalManager()
    app.state.pending_manager = pending_manager

    tick_generator = SyntheticTickGenerator(ws_manager=ws_manager, config=cfg)
    app.state.tick_generator = tick_generator

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request & Correlation ID Middleware
    @app.middleware("http")
    async def correlation_id_and_audit_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        start_time = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Response-Time-MS"] = f"{elapsed_ms:.2f}"

        logger.info(
            "http_request_processed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(elapsed_ms, 2),
            correlation_id=correlation_id,
        )
        return response

    # Initialize Database Schemas
    init_signals_db()
    init_execution_db()
    init_account_db()

    # Explicit 422 Request Validation Error Handler with Structured Logging
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        error_details = exc.errors()

        structured_errors = []
        safe_log_errors = []
        for err in error_details:
            loc = err.get("loc", ())
            field_parts = [str(x) for x in loc if x != "body"]
            field_name = ".".join(field_parts) if field_parts else "payload"
            reason = err.get("msg", "Validation error")
            rejected_val = err.get("input")

            # Redact secrets or sensitive fields from logging/error representation
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
            "validation_error_422",
            method=request.method,
            path=request.url.path,
            errors=safe_log_errors,
            correlation_id=correlation_id,
        )

        return JSONResponse(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            content={
                "status": "error",
                "error_code": "SCHEMA_VALIDATION_FAILED",
                "message": "Malformed signal payload rejected by validation schema",
                "correlation_id": correlation_id,
                "errors": structured_errors,
                "validation_errors": structured_errors,
            },
            headers={"X-Correlation-ID": correlation_id},
        )

    # Centralized HTTP Exception Handler
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        logger.warn(
            "http_exception_raised",
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            detail=exc.detail,
            correlation_id=correlation_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error_code": "HTTP_ERROR",
                "message": exc.detail,
                "detail": exc.detail,
                "correlation_id": correlation_id,
            },
            headers={"X-Correlation-ID": correlation_id},
        )

    # Centralized Global Unhandled Exception Handler (Catches 500s)
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        logger.error(
            "unhandled_server_error",
            method=request.method,
            path=request.url.path,
            error=str(exc),
            error_type=exc.__class__.__name__,
            correlation_id=correlation_id,
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected internal server error occurred",
                "correlation_id": correlation_id,
            },
            headers={"X-Correlation-ID": correlation_id},
        )

    # Mount REST & WebSocket API Routes
    app.include_router(account_router)
    app.include_router(router)
    app.include_router(root_router)

    # Mount Static Directory and Serve Root Interactive Dashboard
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_root_dashboard():
            index_path = os.path.join(static_dir, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return JSONResponse({"status": "OpenAlgo Quantitative Execution Engine Online"})

    # Mount Built Frontend React Assets if present
    frontend_dist = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
    if os.path.exists(frontend_dist):
        from fastapi.staticfiles import StaticFiles
        app.mount("/app", StaticFiles(directory=frontend_dist, html=True), name="frontend")

    return app


# Default ASGI App Instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
