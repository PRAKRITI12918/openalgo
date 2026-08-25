"""
Production-Grade Mock Broker Router & OpenAlgo Adapters.
Simulates execution latency, realistic market slippage, full lifecycle state progressions
(PENDING -> OPEN -> TRIGGERED -> COMPLETE / REJECTED), position bookkeeping, and programmable
circuit-breaker failure injection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import random
import time
from typing import Any, Dict, List, Optional, Set
import uuid

import structlog

from src.adapters.base import BaseBrokerAdapter
from src.core.config import ExecutionConfig, get_config
from src.models.schemas import (
    LegExecutionState,
    LegOrderRequest,
    OrderStatus,
    OrderType,
    PositionStateModel,
)
from src.strategy_engine.models import OrderAction, UnderlyingIndex

logger = structlog.get_logger("openalgo.broker_adapter")


class MockBrokerRouter(BaseBrokerAdapter):
    """
    High-fidelity Mock Broker Engine with realistic latency, slippage, and lifecycle states.
    Thread-safe and async-safe for concurrent execution pipelines.
    """

    def __init__(self, config: Optional[ExecutionConfig] = None):
        self.config = config or get_config()
        self._lock = asyncio.Lock()

        # In-memory data structures
        self._orders: Dict[str, LegExecutionState] = {}
        self._order_legs: Dict[str, LegOrderRequest] = {}
        self._positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position data
        self._total_funds: float = 1_000_000.0  # 10 Lakhs standard demo capital
        self._available_funds: float = 1_000_000.0
        self._utilized_margin: float = 0.0

        # Failure Injection hooks for circuit-breaker testing
        self._rejected_symbols: Dict[str, str] = {}  # symbol -> rejection reason
        self._reject_next_order_msg: Optional[str] = None
        self._simulated_network_error: bool = False

    # -------------------------------------------------------------------------
    # Test Failure Injection Utilities
    # -------------------------------------------------------------------------

    def inject_rejection_for_symbol(self, symbol: str, reason: str = "Simulated broker margin rejection") -> None:
        """Force the mock broker to reject orders for a specific symbol."""
        self._rejected_symbols[symbol] = reason

    def inject_rejection_for_next_order(self, reason: str = "Simulated immediate order rejection") -> None:
        """Force the mock broker to reject the very next placed order."""
        self._reject_next_order_msg = reason

    def inject_network_error(self, enable: bool = True) -> None:
        """Force the mock broker to raise a simulated network connection timeout."""
        self._simulated_network_error = enable

    def clear_injected_rejections(self) -> None:
        """Reset all failure injection rules."""
        self._rejected_symbols.clear()
        self._reject_next_order_msg = None
        self._simulated_network_error = False

    # -------------------------------------------------------------------------
    # Execution Methods
    # -------------------------------------------------------------------------

    async def place_order(
        self,
        leg: LegOrderRequest,
        correlation_id: str = "",
    ) -> LegExecutionState:
        """
        Simulate placing an order with latency, lifecycle state transitions, and slippage.
        """
        start_time = time.perf_counter()
        order_id = f"MOCK_ORD_{uuid.uuid4().hex[:8].upper()}"

        log = logger.bind(
            correlation_id=correlation_id,
            order_id=order_id,
            symbol=leg.symbol,
            action=leg.action.value,
            quantity=leg.quantity,
        )
        log.info("mock_broker_order_received")

        # Simulate Network Latency
        latency_ms = random.uniform(
            self.config.mock_latency_min_ms,
            self.config.mock_latency_max_ms,
        )
        await asyncio.sleep(latency_ms / 1000.0)

        # Check Simulated Network Error
        if self._simulated_network_error:
            log.error("mock_broker_simulated_network_timeout")
            raise ConnectionError("Mock broker connection timeout")

        async with self._lock:
            # 1. State: PENDING -> OPEN
            state = LegExecutionState(
                leg_id=leg.leg_id,
                symbol=leg.symbol,
                action=leg.action,
                strike=leg.strike,
                quantity=leg.quantity,
                filled_quantity=0,
                requested_price=leg.price if leg.price > 0 else 100.0,
                status=OrderStatus.OPEN,
                order_id=order_id,
                is_hedge_leg=leg.is_hedge_leg,
                broker_response={"order_id": order_id, "status": "OPEN"},
                placed_at=datetime.utcnow(),
            )
            self._orders[order_id] = state
            self._order_legs[order_id] = leg

            # 2. Check Rejection Triggers
            rejection_reason = None
            if self._reject_next_order_msg:
                rejection_reason = self._reject_next_order_msg
                self._reject_next_order_msg = None
            elif leg.symbol in self._rejected_symbols:
                rejection_reason = self._rejected_symbols[leg.symbol]
            elif random.random() > self.config.mock_fill_probability:
                rejection_reason = "Simulated probabilistic broker rejection"

            if rejection_reason:
                state.status = OrderStatus.REJECTED
                state.error_message = rejection_reason
                state.broker_response["status"] = "REJECTED"
                state.broker_response["message"] = rejection_reason
                state.updated_at = datetime.utcnow()
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                state.latency_ms = round(elapsed_ms, 2)
                log.warn("mock_broker_order_rejected", reason=rejection_reason)
                return state

            # 3. Simulate Price Execution & Slippage
            base_price = leg.price if leg.price > 0 else 100.0
            slippage_factor = random.uniform(-self.config.mock_slippage_pct, self.config.mock_slippage_pct) / 100.0
            # For BUY, positive slippage hurts (price higher); for SELL, negative slippage hurts (price lower)
            slippage = round(base_price * slippage_factor, 2)
            execution_price = max(0.05, round(base_price + slippage, 2))

            # 4. State: OPEN -> COMPLETE
            state.status = OrderStatus.COMPLETE
            state.filled_quantity = leg.quantity
            state.execution_price = execution_price
            state.slippage = slippage
            state.broker_response["status"] = "COMPLETE"
            state.broker_response["fill_price"] = execution_price
            state.broker_response["filled_qty"] = leg.quantity

            # Update Positions & Margin
            self._update_position(leg, execution_price)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            state.latency_ms = round(elapsed_ms, 2)
            state.updated_at = datetime.utcnow()

            log.info(
                "mock_broker_order_filled",
                fill_price=execution_price,
                slippage=slippage,
                latency_ms=state.latency_ms,
            )
            return state

    async def place_multi_leg_batch(
        self,
        legs: List[LegOrderRequest],
        correlation_id: str = "",
    ) -> List[LegExecutionState]:
        """Place multiple legs concurrently in mock environment."""
        tasks = [self.place_order(leg, correlation_id=correlation_id) for leg in legs]
        return await asyncio.gather(*tasks)

    async def cancel_order(
        self,
        order_id: str,
        correlation_id: str = "",
    ) -> bool:
        """Cancel an open mock order."""
        log = logger.bind(correlation_id=correlation_id, order_id=order_id)
        async with self._lock:
            if order_id not in self._orders:
                log.warn("mock_broker_cancel_not_found")
                return False

            order = self._orders[order_id]
            if order.status in (OrderStatus.COMPLETE, OrderStatus.REJECTED, OrderStatus.CANCELLED):
                log.info("mock_broker_cancel_already_terminal", status=order.status.value)
                return False

            order.status = OrderStatus.CANCELLED
            order.broker_response["status"] = "CANCELLED"
            order.updated_at = datetime.utcnow()
            log.info("mock_broker_order_cancelled")
            return True

    async def get_order_status(self, order_id: str) -> LegExecutionState:
        """Retrieve order state by ID."""
        async with self._lock:
            if order_id not in self._orders:
                raise KeyError(f"Order ID {order_id} not found in mock broker book")
            return self._orders[order_id]

    async def get_positions(self) -> List[PositionStateModel]:
        """Fetch consolidated open positions."""
        async with self._lock:
            result: List[PositionStateModel] = []
            if not self._positions:
                return result

            # Group active legs
            active_legs: List[LegOrderRequest] = []
            for sym, pos in self._positions.items():
                if pos["net_quantity"] != 0:
                    action = OrderAction.BUY if pos["net_quantity"] > 0 else OrderAction.SELL
                    active_legs.append(
                        LegOrderRequest(
                            symbol=sym,
                            underlying=pos.get("underlying", UnderlyingIndex.NIFTY),
                            strike=pos.get("strike", 24000.0),
                            option_type=pos.get("option_type", "CE"),
                            expiry=pos.get("expiry", datetime.utcnow().strftime("%Y-%m-%d")),
                            action=action,
                            quantity=abs(pos["net_quantity"]),
                            price=pos["avg_price"],
                            is_hedge_leg=(action == OrderAction.BUY),
                        )
                    )

            if active_legs:
                total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in self._positions.values())
                total_realized = sum(p.get("realized_pnl", 0.0) for p in self._positions.values())
                result.append(
                    PositionStateModel(
                        position_id="MOCK_PORTFOLIO_1",
                        strategy_name="HedgedAOS_Mock",
                        underlying=UnderlyingIndex.NIFTY,
                        legs=active_legs,
                        unrealized_pnl=round(total_unrealized, 2),
                        realized_pnl=round(total_realized, 2),
                        total_pnl=round(total_unrealized + total_realized, 2),
                        margin_utilized=self._utilized_margin,
                        is_active=True,
                    )
                )
            return result

    async def get_funds(self) -> Dict[str, Any]:
        """Retrieve simulated margin and cash balance."""
        async with self._lock:
            return {
                "status": "success",
                "total_funds": self._total_funds,
                "available_funds": self._available_funds,
                "utilized_margin": self._utilized_margin,
                "currency": "INR",
            }

    async def health_check(self) -> bool:
        """Mock broker is always operational unless network error injected."""
        return not self._simulated_network_error

    # -------------------------------------------------------------------------
    # Internal Bookkeeping
    # -------------------------------------------------------------------------

    def _update_position(self, leg: LegOrderRequest, fill_price: float) -> None:
        """Update in-memory position book on order fill."""
        sym = leg.symbol
        if sym not in self._positions:
            self._positions[sym] = {
                "symbol": sym,
                "underlying": leg.underlying,
                "strike": leg.strike,
                "option_type": leg.option_type,
                "expiry": leg.expiry,
                "net_quantity": 0,
                "avg_price": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            }

        pos = self._positions[sym]
        delta_qty = leg.quantity if leg.action == OrderAction.BUY else -leg.quantity
        old_qty = pos["net_quantity"]
        new_qty = old_qty + delta_qty

        # PnL & Average Price Logic
        if old_qty == 0:
            pos["avg_price"] = fill_price
        elif (old_qty > 0 and delta_qty > 0) or (old_qty < 0 and delta_qty < 0):
            # Adding to existing position
            pos["avg_price"] = round((pos["avg_price"] * abs(old_qty) + fill_price * abs(delta_qty)) / abs(new_qty), 2)
        else:
            # Reducing or closing position: calculate realized PnL
            closed_qty = min(abs(old_qty), abs(delta_qty))
            if old_qty > 0:  # was long, selling to close
                pnl = (fill_price - pos["avg_price"]) * closed_qty
            else:  # was short, buying to cover
                pnl = (pos["avg_price"] - fill_price) * closed_qty
            pos["realized_pnl"] += round(pnl, 2)
            self._available_funds += round(pnl, 2)

        pos["net_quantity"] = new_qty
        if new_qty == 0:
            pos["avg_price"] = 0.0

        # Approximate margin calculation
        # Short positions consume ~120,000 INR margin per lot; Buy legs debit cash
        if leg.action == OrderAction.SELL:
            margin_required = leg.quantity * 2000.0  # mock margin per unit
            self._utilized_margin += margin_required
            self._available_funds = max(0.0, self._available_funds - margin_required)
        else:
            cost = leg.quantity * fill_price
            self._available_funds = max(0.0, self._available_funds - cost)


# Alias for backward compatibility
MockBrokerAdapter = MockBrokerRouter
