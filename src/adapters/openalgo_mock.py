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
        self._positions: Dict[str, Dict[str, Any]] = {}  # symbol -> position data (legacy/global)
        self._account_positions: Dict[str, Dict[str, Dict[str, Any]]] = {}  # account_id -> {symbol -> position data}
        self._total_funds: float = 1_000_000.0  # 10 Lakhs standard demo capital
        self._available_funds: float = 1_000_000.0
        self._utilized_margin: float = 0.0

        # Failure Injection hooks for circuit-breaker testing
        self._rejected_symbols: Dict[str, str] = {}  # symbol -> rejection reason
        self._partial_fill_symbols: Dict[str, int] = {}  # symbol -> partial fill quantity
        self._reject_next_order_msg: Optional[str] = None
        self._simulated_network_error: bool = False

    # -------------------------------------------------------------------------
    # Test Failure Injection Utilities
    # -------------------------------------------------------------------------

    def inject_rejection_for_symbol(self, symbol: str, reason: str = "Simulated broker margin rejection") -> None:
        """Force the mock broker to reject orders for a specific symbol."""
        self._rejected_symbols[symbol] = reason

    def inject_partial_fill_for_symbol(self, symbol: str, fill_qty: int) -> None:
        """Force the mock broker to partially fill orders for a specific symbol."""
        self._partial_fill_symbols[symbol] = fill_qty

    def inject_rejection_for_next_order(self, reason: str = "Simulated immediate order rejection") -> None:
        """Force the mock broker to reject the very next placed order."""
        self._reject_next_order_msg = reason

    def inject_network_error(self, enable: bool = True) -> None:
        """Force the mock broker to raise a simulated network connection timeout."""
        self._simulated_network_error = enable

    def clear_injected_rejections(self) -> None:
        """Reset all failure injection rules."""
        self._rejected_symbols.clear()
        self._partial_fill_symbols.clear()
        self._reject_next_order_msg = None
        self._simulated_network_error = False

    # -------------------------------------------------------------------------
    # Execution Methods
    # -------------------------------------------------------------------------

    async def place_order(
        self,
        leg: LegOrderRequest,
        correlation_id: str = "",
        account_id: Optional[str] = None,
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
            account_id=account_id,
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
                broker_response={"order_id": order_id, "status": "OPEN", "account_id": account_id},
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

            # 4. State: OPEN -> COMPLETE / PARTIALLY_FILLED
            fill_qty = leg.quantity
            is_partial = False
            if leg.symbol in self._partial_fill_symbols:
                injected_fill = self._partial_fill_symbols[leg.symbol]
                if 0 < injected_fill < leg.quantity:
                    fill_qty = injected_fill
                    is_partial = True

            state.status = OrderStatus.PARTIALLY_FILLED if is_partial else OrderStatus.COMPLETE
            state.filled_quantity = fill_qty
            state.execution_price = execution_price
            state.slippage = slippage
            state.broker_response["status"] = "PARTIAL" if is_partial else "COMPLETE"
            state.broker_response["fill_price"] = execution_price
            state.broker_response["filled_qty"] = fill_qty

            # Update Positions & Margin with confirmed fill quantity
            filled_leg = leg.model_copy(update={"quantity": fill_qty})
            self._update_position(filled_leg, execution_price, account_id=account_id)

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
        account_id: Optional[str] = None,
    ) -> List[LegExecutionState]:
        """Place multiple legs concurrently in mock environment."""
        tasks = [self.place_order(leg, correlation_id=correlation_id, account_id=account_id) for leg in legs]
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

    async def get_positions(self, account_id: Optional[str] = None) -> List[PositionStateModel]:
        """Fetch consolidated open positions, optionally scoped to an account_id."""
        async with self._lock:
            result: List[PositionStateModel] = []
            positions_source = (
                self._account_positions.get(account_id, {})
                if account_id
                else self._positions
            )
            if not positions_source:
                return result

            # Group active legs
            active_legs: List[LegOrderRequest] = []
            for sym, pos in positions_source.items():
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
                total_unrealized = sum(p.get("unrealized_pnl", 0.0) for p in positions_source.values())
                total_realized = sum(p.get("realized_pnl", 0.0) for p in positions_source.values())
                result.append(
                    PositionStateModel(
                        position_id=f"MOCK_PORTFOLIO_{account_id or 'GLOBAL'}",
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

    async def get_positions_for_account(self, account_id: str) -> List[PositionStateModel]:
        """Convenience method for account switching confirmation checks."""
        return await self.get_positions(account_id=account_id)

    async def get_funds(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve simulated margin and cash balance."""
        async with self._lock:
            return {
                "status": "success",
                "account_id": account_id,
                "total_funds": self._total_funds,
                "available_funds": self._available_funds,
                "utilized_margin": self._utilized_margin,
                "currency": "INR",
            }

    async def health_check(self) -> bool:
        """Mock broker is always operational unless network error injected."""
        return not self._simulated_network_error

    async def square_off_all(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Emergency square-off: liquidate all open positions for account or globally."""
        async with self._lock:
            if self._simulated_network_error:
                raise ConnectionError("Simulated broker network error during square-off")

            closed = []
            targets = []
            if account_id and account_id in self._account_positions:
                targets.append(self._account_positions[account_id])
            if not account_id:
                targets.append(self._positions)
                for acc_map in self._account_positions.values():
                    targets.append(acc_map)

            for pos_map in targets:
                for sym, pos in list(pos_map.items()):
                    net_qty = pos.get("net_quantity", 0)
                    if net_qty != 0:
                        # Check injected rejection
                        if sym in self._rejected_symbols:
                            closed.append({
                                "symbol": sym,
                                "status": "FAILED",
                                "closed_quantity": 0,
                                "requested_quantity": abs(net_qty),
                                "avg_price": 0.0,
                                "error": self._rejected_symbols[sym],
                            })
                            continue

                        # Check injected partial fill
                        close_qty = abs(net_qty)
                        status = "FILLED"
                        if sym in self._partial_fill_symbols:
                            injected_qty = self._partial_fill_symbols[sym]
                            if 0 < injected_qty < abs(net_qty):
                                close_qty = injected_qty
                                status = "PARTIAL"

                        pnl = (pos.get("realized_pnl", 0.0) + pos.get("unrealized_pnl", 0.0)) * (close_qty / abs(net_qty))
                        closed.append({
                            "symbol": sym,
                            "status": status,
                            "closed_quantity": close_qty if net_qty > 0 else -close_qty,
                            "requested_quantity": abs(net_qty),
                            "avg_price": pos.get("avg_price", 100.0),
                            "realized_pnl": round(pnl, 2),
                        })

                        if status == "FILLED":
                            pos["realized_pnl"] = pos.get("realized_pnl", 0.0) + pos.get("unrealized_pnl", 0.0)
                            pos["unrealized_pnl"] = 0.0
                            pos["net_quantity"] = 0
                            pos["avg_price"] = 0.0
                        else:
                            remaining_qty = abs(net_qty) - close_qty
                            pos["net_quantity"] = remaining_qty if net_qty > 0 else -remaining_qty
                            pos["realized_pnl"] += round(pnl, 2)
                            pos["unrealized_pnl"] = round(pos.get("unrealized_pnl", 0.0) * (remaining_qty / abs(net_qty)), 2)

            self._utilized_margin = 0.0
            return closed

    # -------------------------------------------------------------------------
    # Internal Bookkeeping
    # -------------------------------------------------------------------------

    def _update_position(self, leg: LegOrderRequest, fill_price: float, account_id: Optional[str] = None) -> None:
        """Update in-memory position book on order fill (global + per-account)."""
        sym = leg.symbol
        delta_qty = leg.quantity if leg.action == OrderAction.BUY else -leg.quantity

        def _apply_update(target_dict: Dict[str, Any]):
            if sym not in target_dict:
                target_dict[sym] = {
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
            pos = target_dict[sym]
            old_qty = pos["net_quantity"]
            new_qty = old_qty + delta_qty
            if old_qty == 0:
                pos["avg_price"] = fill_price
            elif (old_qty > 0 and delta_qty > 0) or (old_qty < 0 and delta_qty < 0):
                pos["avg_price"] = round((pos["avg_price"] * abs(old_qty) + fill_price * abs(delta_qty)) / abs(new_qty), 2)
            else:
                closed_qty = min(abs(old_qty), abs(delta_qty))
                if old_qty > 0:
                    pnl = (fill_price - pos["avg_price"]) * closed_qty
                else:
                    pnl = (pos["avg_price"] - fill_price) * closed_qty
                pos["realized_pnl"] += round(pnl, 2)
                self._available_funds += round(pnl, 2)
            pos["net_quantity"] = new_qty
            if new_qty == 0:
                pos["avg_price"] = 0.0

        # Always update legacy/global position map
        _apply_update(self._positions)

        # Also update isolated per-account position map if account_id provided
        if account_id:
            if account_id not in self._account_positions:
                self._account_positions[account_id] = {}
            _apply_update(self._account_positions[account_id])

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
