"""
Synthetic Market Tick Engine & WebSocket Replay Broadcaster.
Generates realistic multi-index price oscillations (NIFTY, BANKNIFTY, SENSEX) and dynamic
option chain pricing with Black-Scholes Greeks, supporting both live synthetic generation
and historical CSV/JSON dataset playback for Phase 3 dashboard consumers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import math
import random
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from fastapi import WebSocket
import structlog

from src.core.config import ExecutionConfig, get_config
from src.models.schemas import (
    ExecutionEventMessage,
    SyntheticTickPayload,
    WebSocketEventType,
)
from src.strategy_engine.greeks import calculate_greeks
from src.strategy_engine.models import OptionType, UnderlyingIndex

logger = structlog.get_logger("openalgo.tick_replay")


class WebSocketConnectionManager:
    """
    Thread-safe connection manager for WebSocket clients.
    Supports segregated channels for market ticks and execution audit events.
    """

    def __init__(self):
        self._market_clients: Set[WebSocket] = set()
        self._execution_clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_market(self, websocket: WebSocket) -> None:
        """Register a client for the market feed stream."""
        await websocket.accept()
        async with self._lock:
            self._market_clients.add(websocket)
        logger.info("ws_market_client_connected", total_clients=len(self._market_clients))

    async def disconnect_market(self, websocket: WebSocket) -> None:
        """Unregister a market feed client."""
        async with self._lock:
            self._market_clients.discard(websocket)
        logger.info("ws_market_client_disconnected", total_clients=len(self._market_clients))

    async def connect_execution(self, websocket: WebSocket) -> None:
        """Register a client for the execution events stream."""
        await websocket.accept()
        async with self._lock:
            self._execution_clients.add(websocket)
        logger.info("ws_execution_client_connected", total_clients=len(self._execution_clients))

    async def disconnect_execution(self, websocket: WebSocket) -> None:
        """Unregister an execution client."""
        async with self._lock:
            self._execution_clients.discard(websocket)
        logger.info("ws_execution_client_disconnected", total_clients=len(self._execution_clients))

    async def broadcast_market_tick(self, tick: SyntheticTickPayload) -> None:
        """Broadcast a market tick event to all subscribed market WebSocket clients."""
        if not self._market_clients:
            return

        payload_json = json.dumps({
            "event_type": WebSocketEventType.TICK.value,
            "timestamp": tick.timestamp.isoformat(),
            "data": tick.model_dump(mode="json"),
        })

        async with self._lock:
            dead_clients: List[WebSocket] = []
            for ws in list(self._market_clients):
                try:
                    await ws.send_text(payload_json)
                except Exception:
                    dead_clients.append(ws)
            for ws in dead_clients:
                self._market_clients.discard(ws)

    async def broadcast_execution_event(self, message: ExecutionEventMessage) -> None:
        """Broadcast order execution, sequence, and MTM events to dashboard clients."""
        if not self._execution_clients:
            return

        payload_json = json.dumps(message.model_dump(mode="json"))

        async with self._lock:
            dead_clients: List[WebSocket] = []
            for ws in list(self._execution_clients):
                try:
                    await ws.send_text(payload_json)
                except Exception:
                    dead_clients.append(ws)
            for ws in dead_clients:
                self._execution_clients.discard(ws)


class SyntheticTickGenerator:
    """
    Generates realistic, continuous synthetic tick streams with dynamic options chains.
    Simulates spot price drift, mean-reverting volatility, and real-time Greek computations.
    """

    def __init__(
        self,
        ws_manager: Optional[WebSocketConnectionManager] = None,
        config: Optional[ExecutionConfig] = None,
    ):
        self.ws_manager = ws_manager
        self.config = config or get_config()
        self._is_running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._tick_listeners: List[Callable[[SyntheticTickPayload], Coroutine[Any, Any, None]]] = []

        # State tracking for indices
        self._spot_prices: Dict[UnderlyingIndex, float] = {
            UnderlyingIndex.NIFTY: 24250.0,
            UnderlyingIndex.BANKNIFTY: 51200.0,
            UnderlyingIndex.SENSEX: 79800.0,
        }
        self._step_counters: Dict[UnderlyingIndex, int] = {
            UnderlyingIndex.NIFTY: 0,
            UnderlyingIndex.BANKNIFTY: 0,
            UnderlyingIndex.SENSEX: 0,
        }

    def add_tick_listener(self, listener: Callable[[SyntheticTickPayload], Coroutine[Any, Any, None]]) -> None:
        """Register an async callback for every generated tick."""
        self._tick_listeners.append(listener)

    async def start(self) -> None:
        """Start the async tick generation loop."""
        if not self._is_running:
            self._is_running = True
            self._task = asyncio.create_task(self._generator_loop())
            logger.info("synthetic_tick_generator_started")

    async def stop(self) -> None:
        """Stop tick generation gracefully."""
        if self._is_running:
            self._is_running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            logger.info("synthetic_tick_generator_stopped")

    async def generate_single_tick(self, underlying: UnderlyingIndex = UnderlyingIndex.NIFTY) -> SyntheticTickPayload:
        """Generate one synthetic spot tick with computed options prices and Greeks."""
        step = self._step_counters[underlying]
        self._step_counters[underlying] += 1

        # Smooth sine-wave + random walk oscillation
        drift = math.sin(step * 0.1) * 3.0 + random.uniform(-2.5, 2.5)
        current_spot = round(self._spot_prices[underlying] + drift, 2)
        self._spot_prices[underlying] = current_spot

        atm_strike = round(current_spot / underlying.strike_step) * underlying.strike_step
        expiry_str = datetime.utcnow().strftime("%Y-%m-%d")

        # Compute synthetic ATM CE Greeks
        iv = 0.15 + (math.sin(step * 0.05) * 0.02)
        greeks = calculate_greeks(
            spot=current_spot,
            strike=atm_strike,
            dte_years=4.0 / 365.0,
            volatility=iv,
            option_type=OptionType.CE,
        )

        bid = max(0.05, round(current_spot * 0.9998, 2))
        ask = round(current_spot * 1.0002, 2)

        tick = SyntheticTickPayload(
            symbol=f"{underlying.value}_SPOT",
            underlying=underlying,
            spot_price=current_spot,
            ltp=current_spot,
            bid=bid,
            ask=ask,
            open_interest=int(2500000 + random.randint(-5000, 5000)),
            volume=int(850000 + step * 100),
            iv=round(iv, 4),
            greeks=greeks,
            timestamp=datetime.utcnow(),
        )

        # Broadcast tick
        if self.ws_manager:
            await self.ws_manager.broadcast_market_tick(tick)

        for listener in self._tick_listeners:
            try:
                await listener(tick)
            except Exception as e:
                logger.warn("tick_listener_error", error=str(e))

        return tick

    async def _generator_loop(self) -> None:
        """Continuous background tick broadcast loop."""
        while self._is_running:
            try:
                for idx in [UnderlyingIndex.NIFTY, UnderlyingIndex.BANKNIFTY]:
                    await self.generate_single_tick(idx)
                await asyncio.sleep(self.config.synthetic_tick_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("synthetic_tick_generator_error", error=str(e))
                await asyncio.sleep(0.5)


class HistoricalTickReplayer:
    """
    Replays recorded historical ticks from structured CSV or JSON files.
    """

    def __init__(
        self,
        ws_manager: Optional[WebSocketConnectionManager] = None,
        speed_multiplier: float = 1.0,
    ):
        self.ws_manager = ws_manager
        self.speed_multiplier = max(0.1, speed_multiplier)
        self._is_replaying: bool = False

    async def replay_records(self, records: List[Dict[str, Any]]) -> int:
        """
        Sequentially broadcast a list of historical tick dictionaries.
        """
        self._is_replaying = True
        count = 0

        for row in records:
            if not self._is_replaying:
                break

            underlying = UnderlyingIndex(row.get("underlying", "NIFTY"))
            tick = SyntheticTickPayload(
                symbol=row.get("symbol", f"{underlying.value}_SPOT"),
                underlying=underlying,
                spot_price=float(row.get("spot_price", row.get("ltp", 24000.0))),
                ltp=float(row.get("ltp", 24000.0)),
                bid=float(row.get("bid", 0.0)),
                ask=float(row.get("ask", 0.0)),
                open_interest=int(row.get("open_interest", 0)),
                volume=int(row.get("volume", 0)),
                iv=float(row.get("iv", 0.15)),
                timestamp=datetime.utcnow(),
            )

            if self.ws_manager:
                await self.ws_manager.broadcast_market_tick(tick)

            count += 1
            delay = (1.0 / self.speed_multiplier) * 0.1
            await asyncio.sleep(delay)

        self._is_replaying = False
        return count

    def stop(self) -> None:
        """Abort active replay."""
        self._is_replaying = False
