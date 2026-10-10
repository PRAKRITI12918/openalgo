"""
Multi-Leg Order Sequence Parser & Risk Circuit-Breaker Engine.
Enforces institutional margin-safety sequencing:
- Phase 1 (Entry): Long protection/hedge wings MUST execute and confirm BEFORE short credit legs.
- Phase 2 (Exit): Short legs are squared off FIRST to eliminate naked risk, then long wings are closed.
- Circuit-Breaker: Immediately halts downstream legs and triggers rollback upon any hedge fill failure.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple
import uuid

import structlog

from src.adapters.base import BaseBrokerAdapter
from src.core.config import ExecutionConfig, get_config
from src.models.schemas import (
    ExecutionEventMessage,
    LegExecutionState,
    LegOrderRequest,
    OrderExecutionSequence,
    OrderStatus,
    RollbackReport,
    StrategySignalPayload,
    WebSocketEventType,
)
from src.strategy_engine.models import OrderAction, SignalType

logger = structlog.get_logger("openalgo.sequence_engine")


class StrategySequenceParser:
    """
    Parses and sequences multi-leg options strategies into strictly ordered execution tiers.
    """

    @staticmethod
    def parse_entry_sequence(legs: List[LegOrderRequest]) -> Tuple[List[LegOrderRequest], List[LegOrderRequest]]:
        """
        Split entry legs into:
        Tier 0: Long Protection / Buy Wings (placed FIRST to secure margin discount and cap risk)
        Tier 1: Short Credit / Sell Legs (placed SECOND only after hedge confirmation)
        """
        hedge_legs: List[LegOrderRequest] = []
        short_legs: List[LegOrderRequest] = []

        for leg in legs:
            if leg.action == OrderAction.BUY or leg.is_hedge_leg:
                hedge_legs.append(leg)
            else:
                short_legs.append(leg)

        return hedge_legs, short_legs

    @staticmethod
    def parse_exit_sequence(legs: List[LegOrderRequest]) -> Tuple[List[LegOrderRequest], List[LegOrderRequest]]:
        """
        Split exit legs into:
        Tier 0: Short Legs being bought to close (placed FIRST to eliminate risk exposure)
        Tier 1: Long Legs being sold to close (placed SECOND after short exposure is closed)
        """
        short_close_legs: List[LegOrderRequest] = []
        long_close_legs: List[LegOrderRequest] = []

        for leg in legs:
            # If original action was SELL, closing requires BUY -> Close first
            # If original action was BUY, closing requires SELL -> Close second
            if leg.action == OrderAction.SELL:
                # Leg provided is the original leg; closing action is BUY
                closing_leg = leg.model_copy(update={"action": OrderAction.BUY, "is_hedge_leg": False})
                short_close_legs.append(closing_leg)
            else:
                closing_leg = leg.model_copy(update={"action": OrderAction.SELL, "is_hedge_leg": False})
                long_close_legs.append(closing_leg)

        return short_close_legs, long_close_legs


class ExecutionSequenceEngine:
    """
    Stateful Execution Sequencing Engine with Built-in Circuit-Breakers.
    Orchestrates multi-leg order progression against the active broker adapter.
    """

    def __init__(
        self,
        broker_adapter: BaseBrokerAdapter,
        config: Optional[ExecutionConfig] = None,
        event_broadcaster: Optional[Callable[[ExecutionEventMessage], Coroutine[Any, Any, None]]] = None,
    ):
        self.broker = broker_adapter
        self.config = config or get_config()
        self.event_broadcaster = event_broadcaster
        self._history: Dict[str, OrderExecutionSequence] = {}
        self._rollbacks: Dict[str, RollbackReport] = {}
        self._lock = asyncio.Lock()

    async def _emit_event(self, event_type: WebSocketEventType, correlation_id: str, data: Dict[str, Any]) -> None:
        """Helper to broadcast events downstream to Phase 3 consumers."""
        if self.event_broadcaster:
            try:
                msg = ExecutionEventMessage(
                    event_type=event_type,
                    correlation_id=correlation_id,
                    data=data,
                )
                await self.event_broadcaster(msg)
            except Exception as e:
                logger.warn("event_broadcast_failed", error=str(e))

    async def execute_signal(self, signal: StrategySignalPayload, account_id: Optional[str] = None) -> OrderExecutionSequence:
        """
        Execute a full StrategySignalPayload enforcing margin safety sequencing and circuit breakers.
        """
        effective_account_id = account_id or getattr(signal, "account_id", None)
        log = logger.bind(
            signal_id=signal.signal_id,
            correlation_id=signal.correlation_id,
            strategy=signal.strategy_name,
            signal_type=signal.signal_type.value,
            underlying=signal.underlying.value,
            account_id=effective_account_id,
        )
        log.info("sequence_execution_started", total_legs=len(signal.legs))

        sequence = OrderExecutionSequence(
            signal_id=signal.signal_id,
            correlation_id=signal.correlation_id,
            strategy_name=signal.strategy_name,
            underlying=signal.underlying,
            account_id=effective_account_id,
            user_id=getattr(signal, "user_id", None),
            status="IN_PROGRESS",
            total_legs=len(signal.legs),
            execution_start_time=datetime.utcnow(),
        )

        async with self._lock:
            self._history[sequence.sequence_id] = sequence

        await self._emit_event(
            WebSocketEventType.SEQUENCE_UPDATE,
            signal.correlation_id,
            sequence.model_dump(mode="json"),
        )

        # Determine Execution Tiers based on Signal Intent
        is_exit = signal.signal_type in (
            SignalType.EXIT,
            SignalType.STOP_LOSS,
            SignalType.TARGET,
            SignalType.TRAILING_STOP,
        )

        if is_exit:
            tier0_legs, tier1_legs = StrategySequenceParser.parse_exit_sequence(signal.legs)
            tier0_name, tier1_name = "SHORT_RISK_CLOSE", "LONG_WING_CLOSE"
        else:
            if self.config.enforce_margin_safety:
                tier0_legs, tier1_legs = StrategySequenceParser.parse_entry_sequence(signal.legs)
                tier0_name, tier1_name = "HEDGE_PROTECTION_WINGS", "SHORT_CREDIT_LEGS"
            else:
                tier0_legs, tier1_legs = signal.legs, []
                tier0_name, tier1_name = "ALL_LEGS_UNSEQUENCED", ""

        # ---------------------------------------------------------------------
        # PHASE 1 / TIER 0 EXECUTION (Hedge Wings or Short Risk Closes)
        # ---------------------------------------------------------------------
        log.info("executing_tier_0_legs", tier=tier0_name, count=len(tier0_legs))
        tier0_states: List[LegExecutionState] = []

        for leg in tier0_legs:
            state = await self.broker.place_order(leg, correlation_id=signal.correlation_id, account_id=effective_account_id)
            sequence.leg_states.append(state)
            tier0_states.append(state)

            await self._emit_event(
                WebSocketEventType.ORDER_UPDATE,
                signal.correlation_id,
                state.model_dump(mode="json"),
            )

            if state.status == OrderStatus.COMPLETE:
                sequence.completed_legs += 1
            else:
                # TIER 0 FAILURE TRIGGER: Immediate Circuit-Breaker!
                sequence.failed_legs += 1
                sequence.circuit_breaker_triggered = True
                sequence.status = "ABORTED_CIRCUIT_BREAKER"
                sequence.error_summary = (
                    f"Tier 0 ({tier0_name}) leg {leg.symbol} failed with status={state.status.value}: "
                    f"{state.error_message}. Halting all downstream {tier1_name} to prevent naked exposure."
                )
                sequence.execution_end_time = datetime.utcnow()

                log.critical(
                    "circuit_breaker_tripped",
                    failed_symbol=leg.symbol,
                    reason=state.error_message,
                    action="ABORTING_DOWNSTREAM_LEGS",
                )

                # Broadcast Circuit Breaker Event
                await self._emit_event(
                    WebSocketEventType.CIRCUIT_BREAKER,
                    signal.correlation_id,
                    {
                        "sequence_id": sequence.sequence_id,
                        "signal_id": signal.signal_id,
                        "failed_leg": leg.symbol,
                        "error": state.error_message,
                        "action": "DOWNSTREAM_ABORTED",
                    },
                )

                # Execute Rollback on any filled Tier 0 legs if necessary
                await self._handle_rollback(sequence, tier0_states, signal.correlation_id)
                return sequence

            if self.config.delay_between_legs_seconds > 0 and len(tier0_legs) > 1:
                await asyncio.sleep(self.config.delay_between_legs_seconds)

        # ---------------------------------------------------------------------
        # PHASE 2 / TIER 1 EXECUTION (Short Credit Legs or Long Closes)
        # ---------------------------------------------------------------------
        if tier1_legs:
            log.info("tier_0_confirmed_executing_tier_1", tier=tier1_name, count=len(tier1_legs))

            for leg in tier1_legs:
                state = await self.broker.place_order(leg, correlation_id=signal.correlation_id, account_id=effective_account_id)
                sequence.leg_states.append(state)

                await self._emit_event(
                    WebSocketEventType.ORDER_UPDATE,
                    signal.correlation_id,
                    state.model_dump(mode="json"),
                )

                if state.status == OrderStatus.COMPLETE:
                    sequence.completed_legs += 1
                else:
                    sequence.failed_legs += 1
                    log.error("tier_1_leg_failed", symbol=leg.symbol, error=state.error_message)

                if self.config.delay_between_legs_seconds > 0 and len(tier1_legs) > 1:
                    await asyncio.sleep(self.config.delay_between_legs_seconds)

        # ---------------------------------------------------------------------
        # SEQUENCE COMPLETION AUDIT
        # ---------------------------------------------------------------------
        sequence.execution_end_time = datetime.utcnow()
        if sequence.completed_legs == sequence.total_legs:
            sequence.status = "FULLY_FILLED"
        elif sequence.completed_legs > 0:
            sequence.status = "PARTIALLY_FILLED"
            sequence.error_summary = f"Partial fill: {sequence.completed_legs}/{sequence.total_legs} legs completed."
        else:
            sequence.status = "FAILED"
            sequence.error_summary = "All legs failed to execute."

        log.info(
            "sequence_execution_finished",
            status=sequence.status,
            completed=sequence.completed_legs,
            total=sequence.total_legs,
        )

        await self._emit_event(
            WebSocketEventType.SEQUENCE_UPDATE,
            signal.correlation_id,
            sequence.model_dump(mode="json"),
        )

        return sequence

    async def _handle_rollback(
        self,
        sequence: OrderExecutionSequence,
        filled_tier0_states: List[LegExecutionState],
        correlation_id: str,
    ) -> None:
        """
        Rollback handler triggered when a circuit-breaker trips during sequence execution.
        Identifies any orphan filled protection legs and attempts to square them off or log an audit report.
        """
        filled_legs_to_close = [s for s in filled_tier0_states if s.status == OrderStatus.COMPLETE]
        if not filled_legs_to_close:
            return

        logger.warn(
            "initiating_circuit_breaker_rollback",
            correlation_id=correlation_id,
            legs_count=len(filled_legs_to_close),
        )

        rolled_back_states: List[LegExecutionState] = []
        for state in filled_legs_to_close:
            # Reversal action: BUY -> SELL, SELL -> BUY
            reverse_action = OrderAction.SELL if state.action == OrderAction.BUY else OrderAction.BUY
            rollback_leg = LegOrderRequest(
                symbol=state.symbol,
                underlying=sequence.underlying,
                strike=state.strike,
                option_type="CE",  # Resolved by symbol
                expiry=datetime.utcnow().strftime("%Y-%m-%d"),
                action=reverse_action,
                quantity=state.filled_quantity,
                is_hedge_leg=False,
            )
            rb_state = await self.broker.place_order(rollback_leg, correlation_id=correlation_id, account_id=sequence.account_id)
            rolled_back_states.append(rb_state)

        report = RollbackReport(
            sequence_id=sequence.sequence_id,
            signal_id=sequence.signal_id,
            correlation_id=correlation_id,
            reason=sequence.error_summary or "Circuit-breaker rollback triggered",
            rolled_back_legs=rolled_back_states,
            status="ROLLED_BACK",
        )

        async with self._lock:
            self._rollbacks[sequence.sequence_id] = report
            sequence.status = "ROLLED_BACK"

        await self._emit_event(
            WebSocketEventType.ROLLBACK_TRIGGERED,
            correlation_id,
            report.model_dump(mode="json"),
        )

    async def get_sequence(self, sequence_id: str, account_id: Optional[str] = None) -> Optional[OrderExecutionSequence]:
        """Retrieve historical sequence by ID, optionally validating account ownership."""
        async with self._lock:
            seq = self._history.get(sequence_id)
            if seq and account_id and seq.account_id and seq.account_id != account_id:
                return None
            return seq

    async def get_all_sequences(self, account_id: Optional[str] = None) -> List[OrderExecutionSequence]:
        """Retrieve recorded execution sequences, optionally scoped by active account_id."""
        async with self._lock:
            all_seqs = list(self._history.values())
            if account_id:
                return [s for s in all_seqs if s.account_id == account_id]
            return all_seqs


class AsyncOrderQueueManager:
    """
    Thread-safe & Async-safe Order Ingestion Queue.
    Serializes signal processing to prevent concurrent margin race conditions.
    """

    def __init__(self, engine: ExecutionSequenceEngine):
        self.engine = engine
        self.queue: asyncio.Queue[StrategySignalPayload] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running: bool = False

    async def start(self) -> None:
        """Start the background queue worker."""
        if not self._is_running:
            self._is_running = True
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("order_queue_worker_started")

    async def stop(self) -> None:
        """Stop background worker gracefully."""
        if self._is_running:
            self._is_running = False
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            logger.info("order_queue_worker_stopped")

    async def enqueue_signal(self, signal: StrategySignalPayload) -> str:
        """Enqueue signal for asynchronous processing."""
        await self.queue.put(signal)
        logger.info(
            "signal_enqueued_in_worker",
            signal_id=signal.signal_id,
            queue_size=self.queue.qsize(),
        )
        return signal.signal_id

    async def _worker_loop(self) -> None:
        """Continuous consumer loop processing queued signals."""
        while self._is_running:
            try:
                signal = await self.queue.get()
                try:
                    await self.engine.execute_signal(signal)
                except Exception as e:
                    logger.error("error_processing_queued_signal", error=str(e), signal_id=signal.signal_id)
                finally:
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("worker_loop_unexpected_error", error=str(e))
                await asyncio.sleep(0.1)
