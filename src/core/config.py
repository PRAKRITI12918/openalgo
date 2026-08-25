"""
Configuration and Environment Settings Module.
Provides centralized, validated, and zero-Git credential management using Pydantic Settings.
Includes high-performance structured JSON logging with correlation ID support.
"""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, List, Optional
import structlog
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BrokerMode(str, Enum):
    """Supported broker execution modes."""
    MOCK = "MOCK"
    OPENALGO_SANDBOX = "OPENALGO_SANDBOX"
    OPENALGO_LIVE = "OPENALGO_LIVE"
    ZERODHA = "ZERODHA"
    DHAN = "DHAN"


class LogFormat(str, Enum):
    """Structured log formats."""
    JSON = "JSON"
    CONSOLE = "CONSOLE"


class ExecutionConfig(BaseSettings):
    """
    Core runtime settings for the Execution Engine & Backend Pipeline.
    Loads from system environment variables or .env file with zero hardcoded credentials.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # Service Metadata
    app_name: str = Field(default="OpenAlgo-Execution-Engine", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")  # development, staging, production, test
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default=LogFormat.JSON, alias="EXECUTION_LOG_FORMAT")

    @field_validator("log_format", mode="before")
    @classmethod
    def normalize_log_format(cls, v: Any) -> LogFormat:
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("JSON", "CONSOLE"):
                return LogFormat(clean)
        return LogFormat.JSON

    @field_validator("broker_mode", mode="before")
    @classmethod
    def normalize_broker_mode(cls, v: Any) -> BrokerMode:
        if isinstance(v, str):
            clean = v.strip().upper()
            for mode in BrokerMode:
                if mode.value == clean:
                    return mode
        return BrokerMode.MOCK

    # Broker & Execution Mode
    broker_mode: BrokerMode = Field(default=BrokerMode.MOCK, alias="BROKER_MODE")
    openalgo_host: str = Field(default="http://127.0.0.1:5000", alias="OPENALGO_HOST")
    openalgo_api_key: str = Field(default="", alias="OPENALGO_API_KEY")
    strategy_tag: str = Field(default="HedgedAOS", alias="STRATEGY_TAG")
    default_product: str = Field(default="MIS", alias="DEFAULT_PRODUCT")  # MIS, NRML, CNC
    default_exchange: str = Field(default="NFO", alias="DEFAULT_EXCHANGE")
    default_index_exchange: str = Field(default="NSE_INDEX", alias="DEFAULT_INDEX_EXCHANGE")

    # Mock Broker Simulation Parameters
    mock_latency_min_ms: float = Field(default=5.0, alias="MOCK_LATENCY_MIN_MS")
    mock_latency_max_ms: float = Field(default=25.0, alias="MOCK_LATENCY_MAX_MS")
    mock_slippage_pct: float = Field(default=0.05, alias="MOCK_SLIPPAGE_PCT")  # 0.05% slippage on market fills
    mock_fill_probability: float = Field(default=1.0, alias="MOCK_FILL_PROBABILITY")  # 1.0 = 100% success

    # Margin Safety & Execution Sequencing
    enforce_margin_safety: bool = Field(default=True, alias="ENFORCE_MARGIN_SAFETY")
    delay_between_legs_seconds: float = Field(default=0.02, alias="DELAY_BETWEEN_LEGS_SECONDS")
    circuit_breaker_max_retries: int = Field(default=2, alias="CIRCUIT_BREAKER_MAX_RETRIES")
    order_timeout_seconds: float = Field(default=5.0, alias="ORDER_TIMEOUT_SECONDS")

    # Synthetic Tick & WebSocket Engine
    synthetic_tick_interval_seconds: float = Field(default=0.5, alias="SYNTHETIC_TICK_INTERVAL_SECONDS")
    replay_speed_multiplier: float = Field(default=1.0, alias="REPLAY_SPEED_MULTIPLIER")

    # Security & API Ingestion
    webhook_auth_token: Optional[str] = Field(default=None, alias="WEBHOOK_AUTH_TOKEN")
    cors_origins: List[str] = Field(default=["*"], alias="CORS_ORIGINS")

    # Risk Controls
    max_capital_allocation: float = Field(default=500000.0, alias="MAX_CAPITAL_ALLOCATION")
    max_order_quantity_per_leg: int = Field(default=1800, alias="MAX_ORDER_QUANTITY_PER_LEG")


@lru_cache(maxsize=1)
def get_config() -> ExecutionConfig:
    """Singleton getter for execution configuration."""
    return ExecutionConfig()


def setup_logger(config: Optional[ExecutionConfig] = None) -> structlog.BoundLogger:
    """
    Configures structlog for structured logging with JSON formatting and correlation IDs.
    Integrates seamlessly with Python's standard logging module.
    """
    cfg = config or get_config()
    log_level = getattr(logging, cfg.log_level.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if cfg.log_format == LogFormat.JSON:
        formatter = structlog.processors.JSONRenderer()
    else:
        formatter = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.processors.format_exc_info,
            formatter,
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
        force=True,
    )

    logger = structlog.get_logger("openalgo.execution_engine")
    return logger
