"""
WebSocket Connection & Subscription Manager.
Handles client registrations, channel and symbol subscriptions,
duplicate subscription prevention, and memory-safe unmount/disconnect cleanup.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Set, Protocol, runtime_checkable

from .types import (
    ClientActionType,
    FeedSource,
    RealtimeEnvelope,
    RealtimeEventType,
    SubscriptionMessage,
    current_iso_timestamp,
)


@runtime_checkable
class WebSocketClientProtocol(Protocol):
    """Protocol for WebSocket client connections (FastAPI WebSocket or mock in tests)."""
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000) -> None: ...


class RealtimeWebSocketManager:
    """
    Thread-safe connection and subscription manager for real-time WebSocket clients.
    Features:
    - Segregated channel and symbol subscriptions
    - Strict duplicate subscription prevention (idempotent sets)
    - Automatic dead socket pruning
    - Immediate unmount/disconnect cleanup
    """

    def __init__(self, feed_source: FeedSource = FeedSource.MOCK):
        self._feed_source = feed_source
        self._clients: Set[WebSocketClientProtocol] = set()
        self._channel_subscriptions: Dict[WebSocketClientProtocol, Set[str]] = {}
        self._symbol_subscriptions: Dict[WebSocketClientProtocol, Set[str]] = {}
        self._lock = asyncio.Lock()

    @property
    def feed_source(self) -> FeedSource:
        return self._feed_source

    @property
    def total_clients(self) -> int:
        return len(self._clients)

    def set_feed_source(self, source: FeedSource) -> None:
        """Update active provenance tag."""
        self._feed_source = source

    async def register(self, client: WebSocketClientProtocol) -> None:
        """Register a newly connected WebSocket client."""
        async with self._lock:
            self._clients.add(client)
            self._channel_subscriptions[client] = set()
            self._symbol_subscriptions[client] = set()

    async def unregister(self, client: WebSocketClientProtocol) -> None:
        """
        Unregister a disconnected WebSocket client.
        Clean up all subscription tracking immediately to prevent memory leaks.
        """
        async with self._lock:
            self._clients.discard(client)
            self._channel_subscriptions.pop(client, None)
            self._symbol_subscriptions.pop(client, None)

    async def subscribe(
        self,
        client: WebSocketClientProtocol,
        channel: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Subscribe a client to a channel and optional symbols.
        IDEMPOTENCY GUARANTEE: Subscribing to the same channel or symbol multiple times
        is safely merged in Sets and will NEVER cause duplicate event delivery.
        """
        async with self._lock:
            if client not in self._clients:
                self._clients.add(client)
                self._channel_subscriptions[client] = set()
                self._symbol_subscriptions[client] = set()

            clean_channel = channel.strip().lower()
            self._channel_subscriptions[client].add(clean_channel)

            if symbols:
                clean_syms = [s.strip().upper() for s in symbols if s.strip()]
                self._symbol_subscriptions[client].update(clean_syms)

            current_channels = list(self._channel_subscriptions[client])
            current_symbols = list(self._symbol_subscriptions[client])

        ack_payload = {
            "type": RealtimeEventType.SUBSCRIPTION_ACK.value,
            "timestamp": current_iso_timestamp(),
            "source": self._feed_source.value,
            "payload": {
                "subscribed_channel": clean_channel,
                "active_channels": current_channels,
                "active_symbols": current_symbols,
                "is_mock": self._feed_source == FeedSource.MOCK,
            }
        }
        await self._send_safe(client, json.dumps(ack_payload))
        return ack_payload

    async def unsubscribe(
        self,
        client: WebSocketClientProtocol,
        channel: str,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Unsubscribe a client from a channel or specific symbols."""
        async with self._lock:
            if client in self._channel_subscriptions:
                clean_channel = channel.strip().lower()
                if not symbols:
                    self._channel_subscriptions[client].discard(clean_channel)
                else:
                    clean_syms = [s.strip().upper() for s in symbols if s.strip()]
                    self._symbol_subscriptions[client].difference_update(clean_syms)

            current_channels = list(self._channel_subscriptions.get(client, set()))
            current_symbols = list(self._symbol_subscriptions.get(client, set()))

        ack_payload = {
            "type": RealtimeEventType.SUBSCRIPTION_ACK.value,
            "timestamp": current_iso_timestamp(),
            "source": self._feed_source.value,
            "payload": {
                "unsubscribed_channel": channel,
                "active_channels": current_channels,
                "active_symbols": current_symbols,
                "is_mock": self._feed_source == FeedSource.MOCK,
            }
        }
        await self._send_safe(client, json.dumps(ack_payload))
        return ack_payload

    async def handle_client_message(
        self,
        client: WebSocketClientProtocol,
        raw_message: str,
    ) -> None:
        """Parse inbound JSON command from client (e.g. subscribe, unsubscribe, ping)."""
        try:
            data = json.loads(raw_message)
        except Exception:
            err = {
                "type": RealtimeEventType.ERROR.value,
                "timestamp": current_iso_timestamp(),
                "source": self._feed_source.value,
                "payload": {"error": "Invalid JSON message format"},
            }
            await self._send_safe(client, json.dumps(err))
            return

        action = str(data.get("action", "")).strip().lower()
        if action == ClientActionType.PING.value:
            pong = {
                "type": RealtimeEventType.HEARTBEAT.value,
                "timestamp": current_iso_timestamp(),
                "source": self._feed_source.value,
                "payload": {"reply": "pong"},
            }
            await self._send_safe(client, json.dumps(pong))
            return

        channel = str(data.get("channel", "")).strip()
        symbols = data.get("symbols", [])
        if not isinstance(symbols, list):
            symbols = [str(symbols)]

        if action == ClientActionType.SUBSCRIBE.value:
            if not channel:
                channel = "market_tick"
            await self.subscribe(client, channel=channel, symbols=symbols)
        elif action == ClientActionType.UNSUBSCRIBE.value:
            if not channel:
                channel = "market_tick"
            await self.unsubscribe(client, channel=channel, symbols=symbols)
        else:
            err = {
                "type": RealtimeEventType.ERROR.value,
                "timestamp": current_iso_timestamp(),
                "source": self._feed_source.value,
                "payload": {"error": f"Unknown action: '{action}'"},
            }
            await self._send_safe(client, json.dumps(err))

    async def broadcast_envelope(self, envelope: RealtimeEnvelope) -> int:
        """
        Broadcast an envelope to eligible clients based on subscriptions.
        Returns the count of clients the envelope was delivered to.
        """
        event_type = envelope.type
        data_json = envelope.model_dump_json()

        channel_name = self._resolve_channel_name(event_type)
        symbol = envelope.symbol or envelope.payload.get("symbol")

        async with self._lock:
            recipients: List[WebSocketClientProtocol] = []
            for client in list(self._clients):
                channels = self._channel_subscriptions.get(client, set())

                if not channels or channel_name in channels or "*" in channels:
                    if channel_name == "market_tick" and symbol:
                        client_syms = self._symbol_subscriptions.get(client, set())
                        if client_syms and symbol.upper() not in client_syms and "*" not in client_syms:
                            continue
                    recipients.append(client)

        delivered = 0
        dead_clients: List[WebSocketClientProtocol] = []

        for client in recipients:
            success = await self._send_safe(client, data_json)
            if success:
                delivered += 1
            else:
                dead_clients.append(client)

        if dead_clients:
            async with self._lock:
                for dc in dead_clients:
                    self._clients.discard(dc)
                    self._channel_subscriptions.pop(dc, None)
                    self._symbol_subscriptions.pop(dc, None)

        return delivered

    def _resolve_channel_name(self, event_type: str) -> str:
        """Map event type string to subscription channel category."""
        if event_type == RealtimeEventType.MARKET_TICK.value:
            return "market_tick"
        if event_type == RealtimeEventType.POSITION_UPDATE.value:
            return "positions"
        if event_type == RealtimeEventType.PNL_UPDATE.value:
            return "pnl"
        if event_type == RealtimeEventType.ORDER_STATUS.value:
            return "orders"
        if event_type == RealtimeEventType.STRATEGY_STATUS.value:
            return "strategies"
        return event_type

    async def _send_safe(self, client: WebSocketClientProtocol, text: str) -> bool:
        """Send message safely; returns False if client dropped."""
        try:
            await client.send_text(text)
            return True
        except Exception:
            return False

    def get_client_subscriptions(self, client: WebSocketClientProtocol) -> Dict[str, Any]:
        """Inspect active subscriptions for a client (useful in tests)."""
        return {
            "channels": set(self._channel_subscriptions.get(client, set())),
            "symbols": set(self._symbol_subscriptions.get(client, set())),
        }
