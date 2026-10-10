"""
Feed Provider Abstraction, Distinct Mode Implementations, and Central Factory.
Ensures zero silent fallback to LIVE, explicit gating, and strict provenance tagging.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Union

from .mock_tick_generator import MockTickGenerator
from .types import (
    FeedMode,
    FeedSource,
    InvalidFeedModeError,
    LiveFeedNotConfiguredError,
    RealtimeEnvelope,
)


class BaseFeedProvider(ABC):
    """
    Abstract base provider for real-time market data streaming.
    Concrete implementations exist for MOCK, SANDBOX, and LIVE modes.
    """

    def __init__(self, mode: FeedMode, source: FeedSource):
        self.mode = mode
        self.source = source
        self._listeners: Set[Callable[[RealtimeEnvelope], Coroutine[Any, Any, None]]] = set()
        self._subscribed_symbols: Set[str] = set()
        self._running = False

    @property
    def is_mock(self) -> bool:
        return self.source == FeedSource.MOCK

    def add_listener(self, callback: Callable[[RealtimeEnvelope], Coroutine[Any, Any, None]]) -> None:
        """Register an async callback listener for emitted envelopes."""
        self._listeners.add(callback)

    def remove_listener(self, callback: Callable[[RealtimeEnvelope], Coroutine[Any, Any, None]]) -> None:
        """Unregister an async callback listener."""
        self._listeners.discard(callback)

    async def _emit(self, envelope: RealtimeEnvelope) -> None:
        """Dispatch envelope to all registered provider listeners."""
        for cb in list(self._listeners):
            try:
                await cb(envelope)
            except Exception:
                # Listener errors must not crash provider loop
                pass

    @abstractmethod
    async def start(self) -> None:
        """Start streaming ticks/events."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop streaming ticks/events."""
        pass

    @abstractmethod
    async def subscribe_symbols(self, symbols: List[str]) -> None:
        """Add symbols to monitor."""
        pass

    @abstractmethod
    async def unsubscribe_symbols(self, symbols: List[str]) -> None:
        """Remove symbols from monitor."""
        pass


class MockFeedProvider(BaseFeedProvider):
    """
    Simulated feed provider using MockTickGenerator.
    All events carry source=FeedSource.MOCK. Zero network or exchange connections.
    """

    def __init__(
        self,
        interval_seconds: float = 0.5,
        base_prices: Optional[Dict[str, float]] = None,
        generator: Optional[MockTickGenerator] = None,
    ):
        super().__init__(FeedMode.MOCK, FeedSource.MOCK)
        self.generator = generator or MockTickGenerator(base_prices=base_prices)
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        # Default monitored indices
        self._subscribed_symbols = set(self.generator.get_supported_symbols())

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            for sym in list(self._subscribed_symbols):
                if not self._running:
                    break
                tick = self.generator.generate_tick(sym)
                await self._emit(tick)
            await asyncio.sleep(self.interval_seconds)

    async def subscribe_symbols(self, symbols: List[str]) -> None:
        for s in symbols:
            self._subscribed_symbols.add(s)

    async def unsubscribe_symbols(self, symbols: List[str]) -> None:
        for s in symbols:
            self._subscribed_symbols.discard(s)

    def emit_custom_tick(self, symbol: str, price: float, apply_drift: bool = False) -> RealtimeEnvelope:
        """Manually trigger a tick for test assertion."""
        self.generator.set_price(symbol, price)
        tick = self.generator.generate_tick(symbol, apply_drift=apply_drift)
        return tick


class SandboxFeedProvider(BaseFeedProvider):
    """
    Routes to broker's paper/sandbox WebSocket or simulated gateway via injected client.
    All events carry source=FeedSource.SANDBOX.
    """

    def __init__(self, sandbox_client: Any = None):
        super().__init__(FeedMode.SANDBOX, FeedSource.SANDBOX)
        self.client = sandbox_client

    async def start(self) -> None:
        self._running = True
        if self.client and hasattr(self.client, "start"):
            await self.client.start()

    async def stop(self) -> None:
        self._running = False
        if self.client and hasattr(self.client, "stop"):
            await self.client.stop()

    async def subscribe_symbols(self, symbols: List[str]) -> None:
        self._subscribed_symbols.update(symbols)
        if self.client and hasattr(self.client, "subscribe"):
            await self.client.subscribe(symbols)

    async def unsubscribe_symbols(self, symbols: List[str]) -> None:
        self._subscribed_symbols.difference_update(symbols)
        if self.client and hasattr(self.client, "unsubscribe"):
            await self.client.unsubscribe(symbols)


class LiveFeedProvider(BaseFeedProvider):
    """
    Real market data feed provider connecting to live exchange/broker streaming endpoints.
    HARD SAFETY REQUIREMENT: Refuses construction unless live_feed_enabled is True AND live_client is supplied.
    """

    def __init__(self, live_client: Any, live_feed_enabled: bool = False):
        if not live_feed_enabled:
            raise LiveFeedNotConfiguredError(
                "LIVE feed requested, but live_feed_enabled is False. "
                "Construction of the live feed path is blocked."
            )
        if live_client is None:
            raise LiveFeedNotConfiguredError(
                "LIVE feed requested with live_feed_enabled=True, but no live_client instance was provided."
            )

        super().__init__(FeedMode.LIVE, FeedSource.LIVE)
        self.client = live_client

    async def start(self) -> None:
        self._running = True
        if hasattr(self.client, "start"):
            await self.client.start()

    async def stop(self) -> None:
        self._running = False
        if hasattr(self.client, "stop"):
            await self.client.stop()

    async def subscribe_symbols(self, symbols: List[str]) -> None:
        self._subscribed_symbols.update(symbols)
        if hasattr(self.client, "subscribe"):
            await self.client.subscribe(symbols)

    async def unsubscribe_symbols(self, symbols: List[str]) -> None:
        self._subscribed_symbols.difference_update(symbols)
        if hasattr(self.client, "unsubscribe"):
            await self.client.unsubscribe(symbols)


def normalize_feed_mode(mode: Union[str, FeedMode]) -> FeedMode:
    """
    Strict, case-insensitive normalization of feed mode string.
    Fails closed on unrecognized strings rather than falling back to MOCK or LIVE.
    """
    if isinstance(mode, FeedMode):
        return mode

    if isinstance(mode, str):
        cleaned = mode.strip().upper()
        if cleaned in ("MOCK", "SIMULATED", "SYNTHETIC"):
            return FeedMode.MOCK
        if cleaned in ("SANDBOX", "PAPER", "DEMO"):
            return FeedMode.SANDBOX
        if cleaned == "LIVE":
            return FeedMode.LIVE

        raise InvalidFeedModeError(
            f"Unrecognized feed mode: '{mode}'. "
            f"Expected one of {[m.value for m in FeedMode]}. Mode fails closed."
        )

    raise InvalidFeedModeError(f"Invalid mode type: {type(mode)}. Expected str or FeedMode.")


def create_feed_provider(
    mode: Union[str, FeedMode] = FeedMode.MOCK,
    config: Optional[Dict[str, Any]] = None,
    live_client: Any = None,
    sandbox_client: Any = None,
) -> BaseFeedProvider:
    """
    THE SINGLE CENTRAL FACTORY mapping a mode string to a feed provider implementation.
    Rules:
      1. Unknown mode string -> throws InvalidFeedModeError.
      2. LIVE mode without explicit live_feed_enabled=True -> throws LiveFeedNotConfiguredError.
      3. LIVE mode without real client instance -> throws LiveFeedNotConfiguredError.
      4. Never silently fall back to LIVE or any default from an error state.
    """
    cfg = config or {}
    norm_mode = normalize_feed_mode(mode)

    if norm_mode == FeedMode.MOCK:
        interval = float(cfg.get("tick_interval_seconds", 0.5))
        base_prices = cfg.get("base_prices")
        return MockFeedProvider(interval_seconds=interval, base_prices=base_prices)

    if norm_mode in (FeedMode.SANDBOX, FeedMode.PAPER):
        return SandboxFeedProvider(sandbox_client=sandbox_client)

    if norm_mode == FeedMode.LIVE:
        live_enabled = bool(cfg.get("live_feed_enabled", False))
        return LiveFeedProvider(live_client=live_client, live_feed_enabled=live_enabled)

    raise InvalidFeedModeError(f"Unhandled validated mode: {norm_mode}")
