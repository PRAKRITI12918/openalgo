"""
Centralized Broker Adapter Factory and Mode Gatekeeper.
Strictly maps execution modes (MOCK, SANDBOX/PAPER, LIVE) to broker adapter implementations.

HARD CONSTRAINTS:
- No silent fallback to LIVE, ever.
- Exactly one place in the code maps "mode" to "execution implementation."
- Unrecognized mode strings fail closed (throw InvalidBrokerModeError) rather than defaulting.
- LIVE mode requires explicit non-default configuration (live_trading_enabled: True).
  Constructing LIVE mode without this explicit flag must throw LiveTradingNotConfiguredError.
"""

from __future__ import annotations

from typing import Any, Optional, Union
import httpx
import structlog

from src.adapters.base import BaseBrokerAdapter
from src.adapters.openalgo_adapter import OpenAlgoBrokerAdapter
from src.adapters.openalgo_mock import MockBrokerRouter
from src.core.config import BrokerMode, ExecutionConfig, get_config

logger = structlog.get_logger("openalgo.broker_factory")


class InvalidBrokerModeError(ValueError):
    """Raised when an unrecognized, illegal, or malformed broker mode string is encountered."""
    pass


class LiveTradingNotConfiguredError(ValueError):
    """Raised when LIVE real-money execution is requested without explicit safety configuration."""
    pass


def create_broker_adapter(
    mode: Optional[Union[str, BrokerMode]] = None,
    config: Optional[ExecutionConfig] = None,
    http_client: Optional[httpx.AsyncClient] = None,
    openalgo_client: Optional[Any] = None,
    live_trading_enabled: Optional[bool] = None,
) -> BaseBrokerAdapter:
    """
    Factory creating the appropriate BaseBrokerAdapter implementation for the configured mode.

    Enforces non-negotiable safety rules:
    - Mode must be recognized. Any unknown string raises InvalidBrokerModeError (fails closed).
    - MOCK: returns MockBrokerRouter.
    - SANDBOX / PAPER / OPENALGO_SANDBOX: returns OpenAlgoBrokerAdapter configured for sandbox.
    - LIVE / OPENALGO_LIVE / DHAN / ZERODHA: requires live_trading_enabled=True AND valid credentials.
      Otherwise raises LiveTradingNotConfiguredError immediately.
    """
    cfg = config or get_config()

    # 1. Resolve & normalize mode string
    raw_mode = mode if mode is not None else cfg.broker_mode
    if isinstance(raw_mode, BrokerMode):
        mode_str = raw_mode.value.upper()
    elif isinstance(raw_mode, str):
        mode_str = raw_mode.strip().upper()
    else:
        raise InvalidBrokerModeError(f"Invalid broker mode type: {type(raw_mode)}. Fails closed.")

    valid_modes = {m.value.upper() for m in BrokerMode}
    if mode_str not in valid_modes:
        logger.critical("broker_factory_invalid_mode_rejected", mode=mode_str)
        raise InvalidBrokerModeError(
            f"Invalid broker execution mode: '{raw_mode}'. "
            f"Allowed modes: {sorted(valid_modes)}. Fails closed."
        )

    # 2. MOCK Execution Mode
    if mode_str == BrokerMode.MOCK.value:
        logger.info("broker_adapter_initialized", mode="MOCK", adapter="MockBrokerRouter")
        return MockBrokerRouter(config=cfg)

    # 3. SANDBOX / PAPER Execution Mode
    if mode_str in (
        BrokerMode.SANDBOX.value,
        BrokerMode.PAPER.value,
        BrokerMode.OPENALGO_SANDBOX.value,
    ):
        logger.info("broker_adapter_initialized", mode=mode_str, adapter="OpenAlgoBrokerAdapter (SANDBOX)")
        return OpenAlgoBrokerAdapter(
            mode="SANDBOX",
            config=cfg,
            client=openalgo_client,
            http_client=http_client,
        )

    # 4. LIVE Real-Money Execution Mode (Strictly Gated)
    if mode_str in (
        BrokerMode.LIVE.value,
        BrokerMode.OPENALGO_LIVE.value,
        BrokerMode.DHAN.value,
        BrokerMode.ZERODHA.value,
    ):
        # Resolve explicit flag: parameter override takes precedence, then config
        is_live_enabled = (
            live_trading_enabled
            if live_trading_enabled is not None
            else getattr(cfg, "live_trading_enabled", False)
        )

        if not is_live_enabled:
            logger.critical(
                "live_mode_rejected_missing_explicit_flag",
                mode=mode_str,
                live_trading_enabled=is_live_enabled,
            )
            raise LiveTradingNotConfiguredError(
                f"LIVE trading mode '{mode_str}' requested without explicit configuration. "
                "Must explicitly set 'live_trading_enabled=True' (LIVE_TRADING_ENABLED=true) "
                "to construct the live execution path. Refusing to initialize."
            )

        # Check credentials
        has_credentials = bool(cfg.openalgo_api_key or openalgo_client)
        if not has_credentials:
            logger.critical("live_mode_rejected_missing_credentials", mode=mode_str)
            raise LiveTradingNotConfiguredError(
                f"LIVE trading mode '{mode_str}' requires validated broker API credentials or client instance."
            )

        logger.warn(
            "broker_adapter_initialized_LIVE",
            mode=mode_str,
            adapter="OpenAlgoBrokerAdapter (LIVE)",
            live_trading_enabled=True,
        )
        return OpenAlgoBrokerAdapter(
            mode="LIVE",
            config=cfg,
            client=openalgo_client,
            http_client=http_client,
        )

    # Fall-through safety (unreachable under normal enum check, but fail closed regardless)
    raise InvalidBrokerModeError(f"Unhandled broker mode: '{mode_str}'. Fails closed.")
