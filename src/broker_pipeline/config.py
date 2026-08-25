"""
Broker Pipeline Configuration Module.
Loads environment variables and OpenAlgo connection settings using Pydantic Settings.
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineConfig(BaseSettings):
    """Configuration settings for OpenAlgo live execution pipeline."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAlgo Host & Authentication
    openalgo_host: str = Field(default="http://127.0.0.1:5000", alias="OPENALGO_HOST")
    openalgo_api_key: str = Field(default="", alias="OPENALGO_API_KEY")

    # Strategy & Execution Metadata
    strategy_tag: str = Field(default="HedgedAOS", alias="STRATEGY_TAG")
    trading_mode: str = Field(default="LIVE", alias="TRADING_MODE")  # LIVE, PAPER, ANALYZER
    default_product: str = Field(default="MIS", alias="DEFAULT_PRODUCT")  # MIS, NRML, CNC
    default_exchange: str = Field(default="NFO", alias="DEFAULT_EXCHANGE")
    default_index_exchange: str = Field(default="NSE_INDEX", alias="DEFAULT_INDEX_EXCHANGE")

    # Polling & Connection Tolerances
    feed_poll_interval_seconds: float = Field(default=1.0, alias="FEED_POLL_INTERVAL")
    request_timeout_seconds: float = Field(default=6.0, alias="REQUEST_TIMEOUT")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    retry_backoff_seconds: float = Field(default=0.5, alias="RETRY_BACKOFF")

    # Risk Controls
    max_capital_allocation: float = Field(default=500000.0, alias="MAX_CAPITAL_ALLOCATION")
    enforce_margin_safety_sequence: bool = Field(default=True, alias="ENFORCE_MARGIN_SAFETY")

    @classmethod
    def load_from_env(cls, env_path: Optional[str] = None) -> "PipelineConfig":
        """Load configuration with fallback resolution from active .env file."""
        if env_path and os.path.exists(env_path):
            return cls(_env_file=env_path)
        return cls()
