"""
Real-time WebSocket Updates & Feed Streaming Module.
Provides centralized connection management, strictly gated mode providers (MOCK vs LIVE),
and standardized event envelopes for LTP, positions, P&L, order status, and strategy state.
"""

from .connection_manager import RealtimeWebSocketManager, WebSocketClientProtocol
from .event_dispatcher import EventDispatcher
from .feed_provider import (
    BaseFeedProvider,
    LiveFeedProvider,
    MockFeedProvider,
    SandboxFeedProvider,
    create_feed_provider,
    normalize_feed_mode,
)
from .mock_tick_generator import MockTickGenerator
from .types import (
    ClientActionType,
    DuplicateSubscriptionError,
    FeedMode,
    FeedSource,
    InvalidFeedModeError,
    LiveFeedNotConfiguredError,
    MarketTickPayload,
    OrderStatusPayload,
    PnlUpdatePayload,
    PositionUpdatePayload,
    RealtimeEnvelope,
    RealtimeEventType,
    StrategyStatusPayload,
    SubscriptionMessage,
    current_iso_timestamp,
)

__all__ = [
    "BaseFeedProvider",
    "ClientActionType",
    "DuplicateSubscriptionError",
    "EventDispatcher",
    "FeedMode",
    "FeedSource",
    "InvalidFeedModeError",
    "LiveFeedNotConfiguredError",
    "LiveFeedProvider",
    "MarketTickPayload",
    "MockFeedProvider",
    "MockTickGenerator",
    "OrderStatusPayload",
    "PnlUpdatePayload",
    "PositionUpdatePayload",
    "RealtimeEnvelope",
    "RealtimeEventType",
    "RealtimeWebSocketManager",
    "SandboxFeedProvider",
    "StrategyStatusPayload",
    "SubscriptionMessage",
    "WebSocketClientProtocol",
    "create_feed_provider",
    "current_iso_timestamp",
    "normalize_feed_mode",
]
