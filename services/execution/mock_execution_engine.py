"""
Mock Execution Engine for Quantitative Trading Strategy Backend.
Consumes VALIDATED / APPROVED trade signals, simulates leg-by-leg execution,
manages order lifecycles (PENDING -> OPEN -> FILLED/REJECTED/CANCELLED/FAILED),
enforces hedge-before-short ordering, updates simulated positions, and computes P&L.

================================================================================
CRITICAL ARCHITECTURAL NOTICE:
MOCK_MODE = True
This module is a 100% SIMULATED EXECUTION LAYER.
NO REAL-MONEY BROKER APIS ARE INVOKED. NO LIVE ORDERS ARE SENT TO ANY EXCHANGE.
ALL PRICES, FILLS, LATENCIES, AND POSITIONS ARE VIRTUAL SIMULATIONS.
================================================================================
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

import structlog

from src.database.execution_db import (
    MockExecutionEventRecord,
    MockPositionRecord,
    db_session,
    init_execution_db,
    record_execution_event,
    update_position_on_fill,
)
from src.database.signals_db import (
    SignalRecord,
    get_signal_by_id,
    transition_signal_status,
)
from src.engine.signal_state_machine import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransitionError,
    validate_transition,
)
from src.models.signal_schema import (
    KNOWN_LOT_SIZES,
    MockLegExecutionResult,
    MockOrderStatus,
    MockSignalExecutionResult,
    PositionSnapshot,
    SignalAction,
    SignalIngestPayload,
    SignalInstrumentType,
    SignalLegPayload,
    SignalOrderType,
    SignalStatus,
)

logger = structlog.get_logger("openalgo.mock_execution_engine")

# Global Flag Confirming Simulated Environment
MOCK_MODE: bool = True


# =============================================================================
# Helper Symbol Resolver
# =============================================================================

def format_simulated_symbol(
    underlying: str,
    instrument: str,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
    option_type: Optional[str] = None,
) -> str:
    """Constructs a standardized simulated contract symbol."""
    u = underlying.strip().upper()
    inst = instrument.strip().upper()
    if inst == "EQUITY":
        return u
    elif inst == "FUTURE":
        return f"{u}-FUT"
    elif inst == "OPTION":
        stk_str = str(int(strike)) if strike is not None and float(strike).is_integer() else str(strike or 0)
        exp_str = expiry or "CURRENT"
        ot = (option_type or "CE").upper()
        return f"{u}-{exp_str}-{stk_str}-{ot}"
    return f"{u}-{inst}"


# =============================================================================
# Mock Price Provider Interface & Implementation
# =============================================================================

class BasePriceProvider:
    """Abstract interface for price simulation and reference pricing."""

    def get_fill_price(
        self,
        instrument: str,
        order_type: str,
        action: str,
        limit_price: Optional[float],
        trigger_price: Optional[float],
        reference_price: Optional[float] = None,
    ) -> float:
        raise NotImplementedError

    def get_mark_price(
        self,
        symbol: str,
        underlying: str,
        last_fill_price: Optional[float] = None,
    ) -> float:
        raise NotImplementedError


class MockPriceProvider(BasePriceProvider):
    """
    Pluggable, deterministic mock price generator.
    - MARKET: reference price with deterministic slippage.
    - LIMIT: executed at limit price or better, never violating limit constraint.
    - SL / SL-M: executed at trigger price or limit price.
    """

    def __init__(
        self,
        reference_prices: Optional[Dict[str, float]] = None,
        default_slippage_bps: float = 0.0,
        fixed_seed: Optional[int] = None,
    ):
        self.reference_prices: Dict[str, float] = reference_prices or {}
        self.default_slippage_bps: float = default_slippage_bps
        self.fixed_seed: Optional[int] = fixed_seed

    def get_fill_price(
        self,
        instrument: str,
        order_type: str,
        action: str,
        limit_price: Optional[float],
        trigger_price: Optional[float],
        reference_price: Optional[float] = None,
    ) -> float:
        """Determines simulated fill price respecting order constraints."""
        ot = order_type.upper()
        act = action.upper()

        if ot == "LIMIT":
            if limit_price is None or limit_price <= 0:
                raise ValueError("LIMIT order must specify price > 0")
            # In simulation, filled exactly at requested limit price (never violates limit)
            return float(limit_price)

        if ot == "SL":
            # Stop-Loss Limit: fill price is the limit price
            if limit_price is None or limit_price <= 0:
                raise ValueError("SL order must specify price > 0")
            return float(limit_price)

        if ot == "SL-M":
            # Stop-Loss Market: fill price is triggered at trigger_price
            if trigger_price is None or trigger_price <= 0:
                raise ValueError("SL-M order must specify trigger_price > 0")
            return float(trigger_price)

        # MARKET Order
        base = reference_price or limit_price or 100.0
        # Deterministic slippage factor (positive slippage for BUY pays slightly more, SELL slightly less)
        slippage_pct = self.default_slippage_bps / 10000.0
        if act == "BUY":
            fill_price = base * (1.0 + slippage_pct)
        else:
            fill_price = base * (1.0 - slippage_pct)
        return round(fill_price, 2)

    def get_mark_price(
        self,
        symbol: str,
        underlying: str,
        last_fill_price: Optional[float] = None,
    ) -> float:
        """Returns reference mark price for unrealized PnL valuation."""
        if symbol in self.reference_prices:
            return self.reference_prices[symbol]
        if underlying in self.reference_prices:
            return self.reference_prices[underlying]
        if last_fill_price is not None and last_fill_price > 0:
            return last_fill_price
        return 100.0


# =============================================================================
# Fault Injector for Deterministic Unit Testing
# =============================================================================

class FaultInjector:
    """
    Test harness to inject deterministic failures, rejections, and partial fills.
    """

    def __init__(
        self,
        fail_legs: Optional[Set[str]] = None,
        reject_legs: Optional[Dict[str, str]] = None,
        partial_fills: Optional[Dict[str, int]] = None,
        simulate_network_timeout: bool = False,
    ):
        self.fail_legs: Set[str] = fail_legs or set()
        self.reject_legs: Dict[str, str] = reject_legs or {}
        self.partial_fills: Dict[str, int] = partial_fills or {}
        self.simulate_network_timeout: bool = simulate_network_timeout

    def should_fail(self, leg_id: str) -> bool:
        return leg_id in self.fail_legs

    def get_rejection_reason(self, leg_id: str) -> Optional[str]:
        return self.reject_legs.get(leg_id)

    def get_partial_fill_qty(self, leg_id: str) -> Optional[int]:
        return self.partial_fills.get(leg_id)


# =============================================================================
# Mock Broker Client Interface & Implementation
# =============================================================================

class BaseMockBrokerClient:
    """Abstract contract for broker execution interactions."""

    async def send_order(
        self,
        signal_id: str,
        leg_data: Dict[str, Any],
        price_provider: BasePriceProvider,
        fault_injector: Optional[FaultInjector] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError


class SimulatedBrokerClient(BaseMockBrokerClient):
    """
    Simulates asynchronous broker order routing and execution matching.
    """

    def __init__(self, delay_seconds: float = 0.0):
        self.delay_seconds = delay_seconds
        self._active_orders: Dict[str, Dict[str, Any]] = {}

    async def send_order(
        self,
        signal_id: str,
        leg_data: Dict[str, Any],
        price_provider: BasePriceProvider,
        fault_injector: Optional[FaultInjector] = None,
    ) -> Dict[str, Any]:
        """
        Simulates order progression:
        PENDING -> OPEN -> FILLED | REJECTED | FAILED
        """
        leg_id = leg_data["leg_id"]
        order_id = f"MOCK-ORD-{uuid.uuid4().hex[:12].upper()}"

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        # 1. Check for Fault Injector failures (infrastructure error / timeout)
        if fault_injector and fault_injector.should_fail(leg_id):
            logger.warn(
                "simulated_order_failed_injected",
                signal_id=signal_id,
                leg_id=leg_id,
                order_id=order_id,
                note="SIMULATED MOCK ENGINE",
            )
            return {
                "order_id": order_id,
                "leg_id": leg_id,
                "status": MockOrderStatus.FAILED,
                "filled_qty": 0,
                "fill_price": 0.0,
                "reason": "Simulated broker infrastructure failure / timeout",
            }

        # 2. Check for Fault Injector rejections
        injected_rejection = fault_injector.get_rejection_reason(leg_id) if fault_injector else None
        if injected_rejection:
            logger.warn(
                "simulated_order_rejected_injected",
                signal_id=signal_id,
                leg_id=leg_id,
                order_id=order_id,
                reason=injected_rejection,
                note="SIMULATED MOCK ENGINE",
            )
            return {
                "order_id": order_id,
                "leg_id": leg_id,
                "status": MockOrderStatus.REJECTED,
                "filled_qty": 0,
                "fill_price": 0.0,
                "reason": injected_rejection,
            }

        # 3. Defense-in-depth domain validation at engine level
        qty = leg_data.get("quantity", 0)
        if qty <= 0:
            return {
                "order_id": order_id,
                "leg_id": leg_id,
                "status": MockOrderStatus.REJECTED,
                "filled_qty": 0,
                "fill_price": 0.0,
                "reason": f"Invalid order quantity: {qty} <= 0",
            }

        underlying = leg_data.get("underlying", "")
        instrument = leg_data.get("instrument", "")
        if instrument not in ("FUTURE", "OPTION", "EQUITY"):
            return {
                "order_id": order_id,
                "leg_id": leg_id,
                "status": MockOrderStatus.REJECTED,
                "filled_qty": 0,
                "fill_price": 0.0,
                "reason": f"Invalid instrument type: '{instrument}'",
            }

        # Validate lot size multiple for derivatives
        if instrument in ("FUTURE", "OPTION") and underlying.upper() in KNOWN_LOT_SIZES:
            lot = KNOWN_LOT_SIZES[underlying.upper()]
            if qty % lot != 0:
                return {
                    "order_id": order_id,
                    "leg_id": leg_id,
                    "status": MockOrderStatus.REJECTED,
                    "filled_qty": 0,
                    "fill_price": 0.0,
                    "reason": f"Quantity {qty} is not a multiple of lot size {lot} for {underlying}",
                }

        # 4. Generate simulated fill price
        order_type = leg_data.get("order_type", "MARKET")
        action = leg_data.get("action", "BUY")
        limit_price = leg_data.get("price")
        trigger_price = leg_data.get("trigger_price")

        fill_price = price_provider.get_fill_price(
            instrument=instrument,
            order_type=order_type,
            action=action,
            limit_price=limit_price,
            trigger_price=trigger_price,
        )

        # 5. Check partial fill injection
        requested_qty = qty
        partial_qty = fault_injector.get_partial_fill_qty(leg_id) if fault_injector else None
        filled_qty = partial_qty if partial_qty is not None else requested_qty

        self._active_orders[order_id] = {
            "order_id": order_id,
            "leg_id": leg_id,
            "status": MockOrderStatus.FILLED,
            "filled_qty": filled_qty,
            "fill_price": fill_price,
            "reason": "Simulated match successful",
        }

        return {
            "order_id": order_id,
            "leg_id": leg_id,
            "status": MockOrderStatus.FILLED,
            "filled_qty": filled_qty,
            "fill_price": fill_price,
            "reason": "Simulated fill executed",
        }

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self._active_orders:
            self._active_orders[order_id]["status"] = MockOrderStatus.CANCELLED
            return True
        return False


# =============================================================================
# Mock Execution Engine
# =============================================================================

class MockExecutionEngine:
    """
    Core Execution Service coordinating leg-by-leg simulated execution.
    - Zero HTTP/UI knowledge.
    - Pure data in -> pure data out.
    - Deterministic, atomic position updates and P&L calculations.
    """

    def __init__(
        self,
        broker_client: Optional[BaseMockBrokerClient] = None,
        price_provider: Optional[BasePriceProvider] = None,
        partial_fill_behavior: str = "CANCEL_REMAINDER",
    ):
        self.broker_client = broker_client or SimulatedBrokerClient()
        self.price_provider = price_provider or MockPriceProvider()
        self.partial_fill_behavior = partial_fill_behavior
        # Initialize execution database tables
        init_execution_db()

    async def execute_signal(
        self,
        signal: SignalRecord | SignalIngestPayload | Dict[str, Any] | str,
        fault_injector: Optional[FaultInjector] = None,
    ) -> MockSignalExecutionResult:
        """
        Executes a validated strategy signal through simulated leg sequencing.

        Args:
            signal: SignalRecord instance, SignalIngestPayload, dictionary, or signal_id string.
            fault_injector: Optional fault injector for testing.

        Returns:
            MockSignalExecutionResult with complete execution and position state.
        """
        # 1. Resolve signal record from database if signal_id was passed
        if isinstance(signal, str):
            signal_rec = get_signal_by_id(signal)
            if not signal_rec:
                raise KeyError(f"Signal '{signal}' not found in database")
            signal = signal_rec

        # Extract signal attributes
        if isinstance(signal, SignalRecord):
            signal_id = signal.signal_id
            strategy_name = signal.strategy_name
            current_status = signal.status
            raw_payload = json.loads(signal.payload_json) if signal.payload_json else {}
        elif isinstance(signal, SignalIngestPayload):
            raw_payload = signal.model_dump(mode="json")
            signal_id = raw_payload.get("signal_id", f"sig_{uuid.uuid4().hex}")
            strategy_name = signal.strategy_name
            current_status = SignalStatus.VALIDATED.value
        elif isinstance(signal, dict):
            raw_payload = signal
            signal_id = signal.get("signal_id", f"sig_{uuid.uuid4().hex}")
            strategy_name = signal.get("strategy_name", "UNKNOWN_STRATEGY")
            current_status = signal.get("status", SignalStatus.VALIDATED.value)
        else:
            raise ValueError(f"Unsupported signal type: {type(signal)}")

        # 2. State Machine Guard: Prevent double-execution or execution of terminal signals
        curr_enum = SignalStatus(current_status)
        if curr_enum in (SignalStatus.EXECUTING, SignalStatus.COMPLETED, SignalStatus.FAILED, SignalStatus.REJECTED):
            raise InvalidStateTransitionError(current_status, SignalStatus.EXECUTING.value)

        # Transition signal to EXECUTING in database
        session = db_session()
        try:
            # If in VALIDATED, transition to APPROVED first, then EXECUTING
            if curr_enum == SignalStatus.VALIDATED:
                transition_signal_status(signal_id, SignalStatus.APPROVED, actor="mock_engine", reason="Signal approved for simulated execution")
            transition_signal_status(signal_id, SignalStatus.EXECUTING, actor="mock_engine", reason="Simulated execution started")

            record_execution_event(
                session=session,
                signal_id=signal_id,
                event_type="SIGNAL_EXECUTING",
                from_state=current_status,
                to_state=SignalStatus.EXECUTING.value,
                details={"strategy_name": strategy_name, "is_mock": True},
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        logger.info(
            "mock_signal_execution_started",
            signal_id=signal_id,
            strategy_name=strategy_name,
            note="MOCK EXECUTION ENGINE - NOT REAL MONEY",
        )

        # 3. Parse Legs
        legs = self._extract_legs(raw_payload)
        leg_results: List[MockLegExecutionResult] = []
        leg_status_map: Dict[str, MockOrderStatus] = {}
        total_realized_pnl: float = 0.0
        total_unrealized_pnl: float = 0.0

        # 4. Group Legs by execution_sequence ascending
        sorted_legs = sorted(legs, key=lambda l: (l.get("execution_sequence", 1), l.get("leg_id", "")))
        sequence_groups: Dict[int, List[Dict[str, Any]]] = {}
        for leg in sorted_legs:
            seq = leg.get("execution_sequence", 1)
            sequence_groups.setdefault(seq, []).append(leg)

        has_upstream_failure: bool = False
        upstream_failure_reason: str = ""

        # 5. Process Sequence Groups
        for seq in sorted(sequence_groups.keys()):
            batch_legs = sequence_groups[seq]

            # If an earlier sequence group suffered a critical failure, cancel all remaining legs
            if has_upstream_failure:
                for leg in batch_legs:
                    cancelled_res = self._cancel_leg_due_to_dependency(
                        signal_id=signal_id,
                        leg_data=leg,
                        reason=f"Cancelled due to upstream sequence failure: {upstream_failure_reason}",
                    )
                    leg_results.append(cancelled_res)
                    leg_status_map[leg["leg_id"]] = MockOrderStatus.CANCELLED
                continue

            # Deterministic sorting within batch:
            # HEDGE legs must be evaluated before PRIMARY/SELL legs
            ordered_batch = self._order_batch_hedges_first(batch_legs)

            # Process each leg in batch
            for leg in ordered_batch:
                leg_id = leg["leg_id"]

                # A. Check Hedge-Before-Short Dependency
                dep_id = leg.get("depends_on_leg_id")
                if not dep_id and leg.get("action") == "SELL" and leg.get("leg_role") != "HEDGE":
                    # Auto-detect hedge leg in same batch if not explicitly wired
                    for peer in batch_legs:
                        if peer.get("leg_role") == "HEDGE" and peer["leg_id"] != leg_id:
                            dep_id = peer["leg_id"]
                            break

                if dep_id:
                    prereq_status = leg_status_map.get(dep_id)
                    if prereq_status != MockOrderStatus.FILLED:
                        # Hedge leg did NOT fill! Cancel this dependent leg immediately (NEVER SEND IT)
                        cancel_reason = (
                            f"Hedge prerequisite leg '{dep_id}' is not FILLED (current status: {prereq_status or 'UNEXECUTED'}); "
                            f"skipping dependent SELL leg to prevent naked short exposure."
                        )
                        cancelled_res = self._cancel_leg_due_to_dependency(
                            signal_id=signal_id,
                            leg_data=leg,
                            reason=cancel_reason,
                        )
                        leg_results.append(cancelled_res)
                        leg_status_map[leg_id] = MockOrderStatus.CANCELLED
                        if not leg.get("is_optional", False):
                            has_upstream_failure = True
                            upstream_failure_reason = cancel_reason
                        continue

                # B. Execute Leg through Mock Broker Client
                leg_res, delta_pnl, un_pnl = await self._execute_single_leg(
                    signal_id=signal_id,
                    strategy_name=strategy_name,
                    leg_data=leg,
                    fault_injector=fault_injector,
                )
                leg_results.append(leg_res)
                leg_status_map[leg_id] = leg_res.status
                total_realized_pnl += delta_pnl
                total_unrealized_pnl += un_pnl

                # If a required leg failed or rejected, halt downstream sequence
                if leg_res.status in (MockOrderStatus.FAILED, MockOrderStatus.REJECTED):
                    if not leg.get("is_optional", False):
                        has_upstream_failure = True
                        upstream_failure_reason = f"Leg '{leg_id}' {leg_res.status.value}: {leg_res.failure_reason}"

        # 6. Determine Signal Outcome
        failed_count = sum(1 for r in leg_results if r.status in (MockOrderStatus.FAILED, MockOrderStatus.REJECTED))
        cancelled_count = sum(1 for r in leg_results if r.status == MockOrderStatus.CANCELLED)
        filled_count = sum(1 for r in leg_results if r.status == MockOrderStatus.FILLED)

        final_signal_status = (
            SignalStatus.FAILED if (failed_count > 0 or cancelled_count > 0) else SignalStatus.COMPLETED
        )

        # 7. Persist Final State and Record Events
        session = db_session()
        try:
            transition_signal_status(
                signal_id=signal_id,
                target_status=final_signal_status,
                actor="mock_engine",
                reason=f"Execution finished with status {final_signal_status.value} ({filled_count}/{len(legs)} legs filled)",
            )

            record_execution_event(
                session=session,
                signal_id=signal_id,
                event_type=f"SIGNAL_{final_signal_status.value}",
                from_state=SignalStatus.EXECUTING.value,
                to_state=final_signal_status.value,
                details={
                    "total_legs": len(legs),
                    "filled_legs": filled_count,
                    "failed_legs": failed_count,
                    "cancelled_legs": cancelled_count,
                    "total_realized_pnl": round(total_realized_pnl, 4),
                    "total_unrealized_pnl": round(total_unrealized_pnl, 4),
                    "is_mock": True,
                },
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        # 8. Query final positions snapshot
        positions_snapshot = [
            PositionSnapshot(
                symbol=p.symbol,
                underlying=p.underlying,
                instrument=p.instrument,
                net_quantity=p.quantity,
                average_price=round(p.average_price, 4),
                realized_pnl=round(p.realized_pnl, 4),
                unrealized_pnl=round(p.unrealized_pnl, 4),
                mark_price=round(p.current_mark_price, 4),
                is_open=p.is_open,
                updated_at=p.updated_at.isoformat(),
            )
            for p in self._get_positions_for_strategy(strategy_name)
        ]

        logger.info(
            "mock_signal_execution_finished",
            signal_id=signal_id,
            status=final_signal_status.value,
            filled=filled_count,
            failed=failed_count,
            cancelled=cancelled_count,
            realized_pnl=round(total_realized_pnl, 4),
            note="MOCK EXECUTION ENGINE - NOT REAL MONEY",
        )

        return MockSignalExecutionResult(
            signal_id=signal_id,
            strategy_name=strategy_name,
            status=final_signal_status,
            total_legs=len(legs),
            filled_legs=filled_count,
            failed_legs=failed_count,
            cancelled_legs=cancelled_count,
            total_realized_pnl=round(total_realized_pnl, 4),
            total_unrealized_pnl=round(total_unrealized_pnl, 4),
            leg_executions=leg_results,
            positions=positions_snapshot,
            is_mock=True,
            executed_at=datetime.utcnow().isoformat(),
        )

    # -------------------------------------------------------------------------
    # Internal Execution Helpers
    # -------------------------------------------------------------------------

    def _extract_legs(self, raw_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extracts legs list or synthesizes single-leg payload into list of 1 leg."""
        raw_legs = raw_payload.get("legs")
        if raw_legs and len(raw_legs) > 0:
            return [l.copy() for l in raw_legs]

        # Single-leg signal: wrap root parameters into leg 1
        return [
            {
                "leg_id": raw_payload.get("leg_id", f"leg_{uuid.uuid4().hex[:8]}"),
                "underlying": raw_payload.get("underlying"),
                "instrument": raw_payload.get("instrument"),
                "action": raw_payload.get("action"),
                "quantity": raw_payload.get("quantity"),
                "order_type": raw_payload.get("order_type", "MARKET"),
                "price": raw_payload.get("price"),
                "trigger_price": raw_payload.get("trigger_price"),
                "execution_sequence": raw_payload.get("execution_sequence", 1),
                "strike": raw_payload.get("strike"),
                "expiry": raw_payload.get("expiry"),
                "option_type": raw_payload.get("option_type"),
                "leg_role": raw_payload.get("leg_role"),
                "depends_on_leg_id": raw_payload.get("depends_on_leg_id"),
                "is_optional": raw_payload.get("is_optional", False),
            }
        ]

    def _order_batch_hedges_first(self, batch_legs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sorts batch legs deterministically so that HEDGE / prerequisite legs
        are ordered first before dependent SELL legs.
        """
        def sort_priority(l: Dict[str, Any]) -> Tuple[int, str]:
            # Priority 0: Explicit HEDGE legs
            if l.get("leg_role") == "HEDGE":
                return (0, l.get("leg_id", ""))
            # Priority 1: BUY legs without dependencies
            if l.get("action") == "BUY" and not l.get("depends_on_leg_id"):
                return (1, l.get("leg_id", ""))
            # Priority 2: Primary / dependent legs
            return (2, l.get("leg_id", ""))

        return sorted(batch_legs, key=sort_priority)

    def _cancel_leg_due_to_dependency(
        self,
        signal_id: str,
        leg_data: Dict[str, Any],
        reason: str,
    ) -> MockLegExecutionResult:
        """Records a cancelled leg that was never sent due to dependency failure."""
        leg_id = leg_data["leg_id"]
        order_id = f"MOCK-ORD-{uuid.uuid4().hex[:12].upper()}"
        now_str = datetime.utcnow().isoformat()

        session = db_session()
        try:
            record_execution_event(
                session=session,
                signal_id=signal_id,
                leg_id=leg_id,
                order_id=order_id,
                event_type="ORDER_CANCELLED",
                from_state=MockOrderStatus.PENDING.value,
                to_state=MockOrderStatus.CANCELLED.value,
                details={"reason": reason, "is_mock": True},
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        logger.warn(
            "simulated_leg_cancelled_dependency_failed",
            signal_id=signal_id,
            leg_id=leg_id,
            order_id=order_id,
            reason=reason,
            note="MOCK EXECUTION ENGINE",
        )

        return MockLegExecutionResult(
            leg_id=leg_id,
            order_id=order_id,
            execution_sequence=leg_data.get("execution_sequence", 1),
            status=MockOrderStatus.CANCELLED,
            action=SignalAction(leg_data.get("action", "BUY")),
            requested_quantity=leg_data.get("quantity", 0),
            filled_quantity=0,
            requested_price=leg_data.get("price"),
            fill_price=0.0,
            realized_pnl=0.0,
            failure_reason=reason,
            is_mock=True,
            created_at=now_str,
            executed_at=now_str,
        )

    async def _execute_single_leg(
        self,
        signal_id: str,
        strategy_name: str,
        leg_data: Dict[str, Any],
        fault_injector: Optional[FaultInjector] = None,
    ) -> Tuple[MockLegExecutionResult, float, float]:
        """
        Drives a single leg through order lifecycle:
        PENDING -> OPEN -> FILLED | REJECTED | FAILED
        Updates position & computes PnL if filled.
        """
        leg_id = leg_data["leg_id"]
        order_id = f"MOCK-ORD-{uuid.uuid4().hex[:12].upper()}"
        start_ts = datetime.utcnow().isoformat()
        session = db_session()

        # 1. State: PENDING (Order constructed)
        try:
            record_execution_event(
                session=session,
                signal_id=signal_id,
                leg_id=leg_id,
                order_id=order_id,
                event_type="ORDER_CREATED",
                from_state=None,
                to_state=MockOrderStatus.PENDING.value,
                details={"leg_data": leg_data, "is_mock": True},
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        # 2. State: OPEN (Order sent to mock broker client)
        session = db_session()
        try:
            record_execution_event(
                session=session,
                signal_id=signal_id,
                leg_id=leg_id,
                order_id=order_id,
                event_type="ORDER_OPENED",
                from_state=MockOrderStatus.PENDING.value,
                to_state=MockOrderStatus.OPEN.value,
                details={"is_mock": True},
            )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

        # 3. Simulate broker matching & outcome
        broker_res = await self.broker_client.send_order(
            signal_id=signal_id,
            leg_data=leg_data,
            price_provider=self.price_provider,
            fault_injector=fault_injector,
        )

        outcome_status: MockOrderStatus = broker_res["status"]
        filled_qty = broker_res.get("filled_qty", 0)
        fill_price = broker_res.get("fill_price", 0.0)
        reason = broker_res.get("reason", "")
        end_ts = datetime.utcnow().isoformat()
        delta_realized_pnl = 0.0
        total_unrealized_pnl = 0.0

        session = db_session()
        try:
            if outcome_status == MockOrderStatus.FILLED:
                # 4. State: FILLED -> Atomically update position and compute P&L
                symbol = format_simulated_symbol(
                    underlying=leg_data["underlying"],
                    instrument=leg_data["instrument"],
                    strike=leg_data.get("strike"),
                    expiry=leg_data.get("expiry"),
                    option_type=leg_data.get("option_type"),
                )

                mark_price = self.price_provider.get_mark_price(
                    symbol=symbol,
                    underlying=leg_data["underlying"],
                    last_fill_price=fill_price,
                )

                pos_rec, delta_realized_pnl, total_unrealized_pnl = update_position_on_fill(
                    session=session,
                    symbol=symbol,
                    underlying=leg_data["underlying"],
                    strategy_name=strategy_name,
                    instrument=leg_data["instrument"],
                    action=leg_data["action"],
                    fill_qty=filled_qty,
                    fill_price=fill_price,
                    mark_price=mark_price,
                    signal_id=signal_id,
                )

                record_execution_event(
                    session=session,
                    signal_id=signal_id,
                    leg_id=leg_id,
                    order_id=order_id,
                    event_type="ORDER_FILLED",
                    from_state=MockOrderStatus.OPEN.value,
                    to_state=MockOrderStatus.FILLED.value,
                    details={
                        "symbol": symbol,
                        "fill_price": fill_price,
                        "filled_qty": filled_qty,
                        "realized_pnl": delta_realized_pnl,
                        "is_mock": True,
                    },
                )

                # Record Position update event
                record_execution_event(
                    session=session,
                    signal_id=signal_id,
                    leg_id=leg_id,
                    order_id=order_id,
                    event_type="POSITION_UPDATED",
                    from_state=None,
                    to_state=None,
                    details=pos_rec.to_dict(),
                )

            elif outcome_status == MockOrderStatus.REJECTED:
                record_execution_event(
                    session=session,
                    signal_id=signal_id,
                    leg_id=leg_id,
                    order_id=order_id,
                    event_type="ORDER_REJECTED",
                    from_state=MockOrderStatus.OPEN.value,
                    to_state=MockOrderStatus.REJECTED.value,
                    details={"reason": reason, "is_mock": True},
                )
            else:
                record_execution_event(
                    session=session,
                    signal_id=signal_id,
                    leg_id=leg_id,
                    order_id=order_id,
                    event_type="ORDER_FAILED",
                    from_state=MockOrderStatus.OPEN.value,
                    to_state=MockOrderStatus.FAILED.value,
                    details={"reason": reason, "is_mock": True},
                )

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        result = MockLegExecutionResult(
            leg_id=leg_id,
            order_id=order_id,
            execution_sequence=leg_data.get("execution_sequence", 1),
            status=outcome_status,
            action=SignalAction(leg_data.get("action", "BUY")),
            requested_quantity=leg_data.get("quantity", 0),
            filled_quantity=filled_qty,
            requested_price=leg_data.get("price"),
            fill_price=fill_price if outcome_status == MockOrderStatus.FILLED else None,
            realized_pnl=round(delta_realized_pnl, 4),
            failure_reason=reason if outcome_status != MockOrderStatus.FILLED else None,
            is_mock=True,
            created_at=start_ts,
            executed_at=end_ts,
        )
        return result, delta_realized_pnl, total_unrealized_pnl

    def _get_positions_for_strategy(self, strategy_name: str) -> List[MockPositionRecord]:
        """Queries positions table for positions matching strategy."""
        session = db_session()
        try:
            return (
                session.query(MockPositionRecord)
                .filter_by(strategy_name=strategy_name)
                .all()
            )
        finally:
            session.close()
