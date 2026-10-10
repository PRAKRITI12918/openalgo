"""
Event Formatter and Dispatcher for Real-time Trading Updates.
Constructs consistent { type, timestamp, source, payload } envelopes for all 5 core trading domain streams:
1. LTP (market_tick)
2. Positions (position_update)
3. P&L (pnl_update)
4. Order Status (order_status)
5. Strategy Status (strategy_status)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .types import (
    FeedSource,
    MarketTickPayload,
    OrderStatusPayload,
    PnlUpdatePayload,
    PositionUpdatePayload,
    RealtimeEnvelope,
    RealtimeEventType,
    StrategyStatusPayload,
    current_iso_timestamp,
)


class EventDispatcher:
    """
    Constructs and validates strongly typed event envelopes.
    Ensures structural integrity and correct source tagging across all event types.
    """

    def __init__(self, source: FeedSource = FeedSource.MOCK):
        self.source = source

    def set_source(self, source: FeedSource) -> None:
        """Update current active feed source provenance."""
        self.source = source

    def format_market_tick(
        self,
        symbol: str,
        ltp: float,
        change: float = 0.0,
        change_pct: float = 0.0,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        open_price: Optional[float] = None,
        high: Optional[float] = None,
        low: Optional[float] = None,
        volume: Optional[int] = None,
        source: Optional[FeedSource] = None,
    ) -> RealtimeEnvelope:
        """Format an LTP / market tick event."""
        payload = MarketTickPayload(
            symbol=symbol,
            ltp=ltp,
            change=change,
            change_pct=change_pct,
            bid=bid,
            ask=ask,
            open=open_price,
            high=high,
            low=low,
            volume=volume,
        )
        return RealtimeEnvelope(
            type=RealtimeEventType.MARKET_TICK.value,
            timestamp=current_iso_timestamp(),
            source=source or self.source,
            symbol=symbol,
            ltp=ltp,
            payload=payload.model_dump(),
        )

    def format_position_update(
        self,
        account_id: str,
        symbol: str,
        quantity: int,
        average_price: float,
        current_price: float,
        unrealized_pnl: float,
        realized_pnl: float = 0.0,
        source: Optional[FeedSource] = None,
    ) -> RealtimeEnvelope:
        """Format a position change or mark-to-market update event."""
        payload = PositionUpdatePayload(
            account_id=account_id,
            symbol=symbol,
            quantity=quantity,
            average_price=average_price,
            current_price=current_price,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
        )
        return RealtimeEnvelope(
            type=RealtimeEventType.POSITION_UPDATE.value,
            timestamp=current_iso_timestamp(),
            source=source or self.source,
            payload=payload.model_dump(),
        )

    def format_pnl_update(
        self,
        account_id: str,
        total_unrealized_pnl: float,
        total_realized_pnl: float,
        net_pnl: float,
        currency: str = "INR",
        strategies: Optional[Dict[str, float]] = None,
        source: Optional[FeedSource] = None,
    ) -> RealtimeEnvelope:
        """Format an aggregate account or strategy P&L update event."""
        payload = PnlUpdatePayload(
            account_id=account_id,
            total_unrealized_pnl=total_unrealized_pnl,
            total_realized_pnl=total_realized_pnl,
            net_pnl=net_pnl,
            currency=currency,
            strategies=strategies or {},
        )
        return RealtimeEnvelope(
            type=RealtimeEventType.PNL_UPDATE.value,
            timestamp=current_iso_timestamp(),
            source=source or self.source,
            payload=payload.model_dump(),
        )

    def format_order_status(
        self,
        order_id: str,
        account_id: str,
        symbol: str,
        side: str,
        status: str,
        quantity: int,
        filled_quantity: int,
        price: float,
        order_type: str = "MARKET",
        error_message: Optional[str] = None,
        source: Optional[FeedSource] = None,
    ) -> RealtimeEnvelope:
        """Format an order lifecycle event (placed, filled, partial, rejected, cancelled)."""
        payload = OrderStatusPayload(
            order_id=order_id,
            account_id=account_id,
            symbol=symbol,
            side=side,
            status=status,
            quantity=quantity,
            filled_quantity=filled_quantity,
            price=price,
            order_type=order_type,
            error_message=error_message,
        )
        return RealtimeEnvelope(
            type=RealtimeEventType.ORDER_STATUS.value,
            timestamp=current_iso_timestamp(),
            source=source or self.source,
            payload=payload.model_dump(),
        )

    def format_strategy_status(
        self,
        strategy_id: str,
        strategy_name: str,
        status: str,
        pnl: float = 0.0,
        details: Optional[str] = None,
        source: Optional[FeedSource] = None,
    ) -> RealtimeEnvelope:
        """Format a strategy state transition (RUNNING, PAUSED, STOPPED, ERROR)."""
        payload = StrategyStatusPayload(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            status=status,
            pnl=pnl,
            details=details,
        )
        return RealtimeEnvelope(
            type=RealtimeEventType.STRATEGY_STATUS.value,
            timestamp=current_iso_timestamp(),
            source=source or self.source,
            payload=payload.model_dump(),
        )
