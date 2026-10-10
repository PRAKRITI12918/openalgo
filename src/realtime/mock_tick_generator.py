"""
Mock Tick Generator for Development & Testing.
Emits synthetic ticks with guaranteed source='mock' and structural separation.
NEVER emits data labeled as live market data.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .types import FeedSource, MarketTickPayload, RealtimeEnvelope, RealtimeEventType, current_iso_timestamp


class MockTickGenerator:
    """
    Generates synthetic market ticks and quotes for development and CI testing.
    All events produced by this generator ALWAYS carry source=FeedSource.MOCK.
    """

    def __init__(
        self,
        base_prices: Optional[Dict[str, float]] = None,
        volatility: float = 0.0015,
        seed: Optional[int] = 42,
    ):
        self._rnd = random.Random(seed)
        self._volatility = volatility
        self._prices: Dict[str, float] = base_prices.copy() if base_prices else {
            "NIFTY": 25120.50,
            "BANKNIFTY": 51400.00,
            "SENSEX": 81500.00,
            "RELIANCE": 2980.00,
            "HDFCBANK": 1640.00,
        }
        self._open_prices = self._prices.copy()
        self._high_prices = self._prices.copy()
        self._low_prices = self._prices.copy()
        self._step_counter = 0

    def set_price(self, symbol: str, price: float) -> None:
        """Manually override or inject a specific price for a symbol."""
        self._prices[symbol] = price
        if symbol not in self._open_prices:
            self._open_prices[symbol] = price
            self._high_prices[symbol] = price
            self._low_prices[symbol] = price

    def get_supported_symbols(self) -> List[str]:
        """Return list of active symbols available in mock generation."""
        return list(self._prices.keys())

    def generate_tick(self, symbol: str, apply_drift: bool = True) -> RealtimeEnvelope:
        """
        Generate a synthetic tick for the requested symbol.
        The returned RealtimeEnvelope ALWAYS contains:
          - source: FeedSource.MOCK ('mock')
          - type: RealtimeEventType.MARKET_TICK ('market_tick')
          - symbol: symbol
          - ltp: synthetic LTP
        """
        self._step_counter += 1
        current_price = self._prices.get(symbol, 100.0)

        if apply_drift:
            # Geometric Brownian drift with mean-reverting bounce
            delta_pct = self._rnd.gauss(0.0, self._volatility)
            new_price = round(current_price * (1.0 + delta_pct), 2)
            new_price = max(0.05, new_price)
        else:
            new_price = current_price

        self._prices[symbol] = new_price

        # Update high/low tracking
        open_price = self._open_prices.get(symbol, current_price)
        high_price = max(self._high_prices.get(symbol, new_price), new_price)
        low_price = min(self._low_prices.get(symbol, new_price), new_price)
        self._high_prices[symbol] = high_price
        self._low_prices[symbol] = low_price

        change = round(new_price - open_price, 2)
        change_pct = round((change / open_price) * 100.0, 2) if open_price > 0 else 0.0

        spread = round(max(0.05, new_price * 0.0002), 2)
        bid = round(new_price - spread / 2, 2)
        ask = round(new_price + spread / 2, 2)
        volume = 1000 + (self._step_counter * 25)

        payload = MarketTickPayload(
            symbol=symbol,
            ltp=new_price,
            change=change,
            change_pct=change_pct,
            bid=bid,
            ask=ask,
            open=open_price,
            high=high_price,
            low=low_price,
            volume=volume,
        )

        return RealtimeEnvelope(
            type=RealtimeEventType.MARKET_TICK.value,
            timestamp=current_iso_timestamp(),
            source=FeedSource.MOCK,  # HARD CONSTRAINT: Never label mock data as live
            symbol=symbol,
            ltp=new_price,
            payload=payload.model_dump(),
        )

    def generate_all_ticks(self) -> List[RealtimeEnvelope]:
        """Generate a snapshot of ticks across all monitored symbols."""
        return [self.generate_tick(sym) for sym in self._prices.keys()]
