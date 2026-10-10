"""
Real-time Feed Type Definitions, Enums, Envelope Schemas, and Typed Errors.
Enforces structural distinction between MOCK, SANDBOX, and LIVE data feeds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class FeedMode(str, Enum):
    """
    Operation mode for market and trading data feeds.
    Strictly fail-closed: unrecognized modes throw InvalidFeedModeError.
    """
    MOCK = "MOCK"
    SANDBOX = "SANDBOX"
    PAPER = "PAPER"
    LIVE = "LIVE"


class FeedSource(str, Enum):
    """
    Structural provenance tag stamped on every outgoing event.
    MOCK data is NEVER labeled, displayed, or logged as real market data.
    """
    MOCK = "mock"
    SANDBOX = "sandbox"
    LIVE = "live"


class RealtimeEventType(str, Enum):
    """Structured event categories emitted over the WebSocket stream."""
    MARKET_TICK = "market_tick"
    POSITION_UPDATE = "position_update"
    PNL_UPDATE = "pnl_update"
    ORDER_STATUS = "order_status"
    STRATEGY_STATUS = "strategy_status"
    SUBSCRIPTION_ACK = "subscription_ack"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class ClientActionType(str, Enum):
    """Inbound client command actions."""
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"


# ---------------------------------------------------------------------------
# Typed Errors (Safety & Gating)
# ---------------------------------------------------------------------------

class InvalidFeedModeError(ValueError):
    """Raised when an unknown or invalid feed mode is requested."""
    pass


class LiveFeedNotConfiguredError(RuntimeError):
    """Raised when LIVE feed mode is requested without explicit required configuration."""
    pass


class DuplicateSubscriptionError(ValueError):
    """Raised when duplicate subscription handling encounters a fatal conflict."""
    pass


# ---------------------------------------------------------------------------
# Standard Event Envelope & Structured Payloads
# ---------------------------------------------------------------------------

def current_iso_timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class RealtimeEnvelope(BaseModel):
    """
    Universal envelope for all real-time WebSocket events.
    Ensures the frontend can reliably dispatch on 'type' without special casing.
    """
    type: str = Field(..., description="Stable event type string")
    timestamp: str = Field(default_factory=current_iso_timestamp, description="UTC ISO 8601 timestamp")
    source: FeedSource = Field(..., description="Structural provenance: mock | sandbox | live")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-specific typed data")
    
    # Direct convenience fields for high-frequency tick consumers
    symbol: Optional[str] = Field(default=None, description="Optional symbol shorthand for tick events")
    ltp: Optional[float] = Field(default=None, description="Optional LTP shorthand for tick events")


class MarketTickPayload(BaseModel):
    """LTP & Quote update for a specific market instrument."""
    symbol: str
    ltp: float
    change: float = 0.0
    change_pct: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    volume: Optional[int] = None


class PositionUpdatePayload(BaseModel):
    """Quantity, average price, and unrealized P&L change for a position."""
    account_id: str
    symbol: str
    quantity: int
    average_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0


class PnlUpdatePayload(BaseModel):
    """Account- or strategy-level P&L updates."""
    account_id: str
    total_unrealized_pnl: float
    total_realized_pnl: float
    net_pnl: float
    currency: str = "INR"
    strategies: Dict[str, float] = Field(default_factory=dict)


class OrderStatusPayload(BaseModel):
    """Lifecycle updates for orders (placed, filled, partial, rejected, cancelled)."""
    order_id: str
    account_id: str
    symbol: str
    side: str
    status: str
    quantity: int
    filled_quantity: int
    price: float
    order_type: str = "MARKET"
    error_message: Optional[str] = None


class StrategyStatusPayload(BaseModel):
    """Operational status of a trading strategy container."""
    strategy_id: str
    strategy_name: str
    status: str  # RUNNING | PAUSED | STOPPED | ERROR
    pnl: float = 0.0
    details: Optional[str] = None


class SubscriptionMessage(BaseModel):
    """Inbound subscription request from WebSocket client."""
    action: ClientActionType = Field(default=ClientActionType.SUBSCRIBE)
    channel: str = Field(..., description="Target channel: market_tick | positions | pnl | orders | strategies")
    symbols: List[str] = Field(default_factory=list, description="Optional symbols filter for market_tick")
