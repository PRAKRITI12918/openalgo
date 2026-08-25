"""
Safe Multi-Leg Order Router.
Converts Phase 1 TradeSignals and HedgeAdjustmentSignals into OpenAlgo order payloads.
Enforces institutional margin-safety sequencing (buys long protection wings before short credit legs).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.broker_pipeline.openalgo_client import OpenAlgoClient, OpenAlgoError
from src.strategy_engine.models import (
    HedgeActionType,
    HedgeAdjustmentSignal,
    OptionLeg,
    OrderAction,
    SignalType,
    TradeSignal,
    UnderlyingIndex,
)

logger = logging.getLogger("broker_pipeline.router")


@dataclass
class LegExecutionResult:
    """Status result for an individual option leg order."""
    leg_symbol: str
    action: OrderAction
    strike: float
    quantity: int
    order_id: Optional[str] = None
    status: str = "PENDING"  # SUCCESS, REJECTED, FAILED
    error_message: Optional[str] = None
    placed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ExecutionReport:
    """Consolidated execution report for a multi-leg strategy signal."""
    signal_id: str
    strategy_name: str
    underlying: UnderlyingIndex
    status: str  # FULLY_FILLED, PARTIALLY_FILLED, FAILED, REJECTED
    leg_results: List[LegExecutionResult] = field(default_factory=list)
    total_legs: int = 0
    filled_legs: int = 0
    executed_at: datetime = field(default_factory=datetime.utcnow)
    error_summary: Optional[str] = None


class OrderRouter:
    """
    Intelligent Order Routing Engine.
    Executes entry, exit, and dynamic hedge adjustment orders with margin-safety sequencing.
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        enforce_margin_safety: bool = True,
        delay_between_legs_seconds: float = 0.1,
    ):
        self.client = client
        self.enforce_margin_safety = enforce_margin_safety
        self.delay_between_legs = delay_between_legs_seconds

    async def route_signal(
        self,
        signal: TradeSignal,
        use_atomic_multiorder: bool = False,
    ) -> ExecutionReport:
        """
        Route an entry or exit TradeSignal.
        """
        if signal.signal_type in (SignalType.TARGET, SignalType.STOP_LOSS, SignalType.TIME_EXIT, SignalType.REGIME_SHIFT):
            return await self.route_exit_signal(signal)
        else:
            return await self.route_entry_signal(signal, use_atomic_multiorder=use_atomic_multiorder)

    async def route_entry_signal(
        self,
        signal: TradeSignal,
        use_atomic_multiorder: bool = False,
    ) -> ExecutionReport:
        """
        Route a multi-leg entry strategy signal.
        Sequences BUY wings before SELL legs to prevent naked-margin spike rejections.
        """
        report = ExecutionReport(
            signal_id=signal.signal_id,
            strategy_name=signal.strategy_type.value,
            underlying=signal.underlying,
            status="PENDING",
            total_legs=len(signal.legs),
        )

        if not signal.legs:
            report.status = "FAILED"
            report.error_summary = "Signal contains no option legs"
            return report

        # Optional: Atomic multi-order if requested and supported
        if use_atomic_multiorder:
            return await self._execute_atomic_multiorder(signal, report)

        # Margin Safety Sequence:
        # Group 1: BUY legs (long protection wings) placed FIRST
        # Group 2: SELL legs (short credit legs) placed SECOND
        if self.enforce_margin_safety:
            ordered_legs = sorted(signal.legs, key=lambda l: 0 if l.action == OrderAction.BUY else 1)
        else:
            ordered_legs = signal.legs

        logger.info(f"Routing {len(ordered_legs)} legs for {signal.strategy_type.value} with margin safety sequencing")

        for leg in ordered_legs:
            leg_res = await self._execute_single_leg(leg, strategy_tag=signal.strategy_type.value)
            report.leg_results.append(leg_res)

            if leg_res.status == "SUCCESS":
                report.filled_legs += 1
            else:
                logger.error(f"Failed to place {leg.action.value} {leg.symbol}: {leg_res.error_message}")
                # If a long protection leg fails in margin safety mode, abort short legs to prevent naked exposure!
                if self.enforce_margin_safety and leg.action == OrderAction.BUY:
                    report.status = "FAILED"
                    report.error_summary = f"Protection leg {leg.symbol} failed: {leg_res.error_message}. Aborting short legs to prevent naked risk."
                    return report

            if self.delay_between_legs > 0:
                await asyncio.sleep(self.delay_between_legs)

        if report.filled_legs == report.total_legs:
            report.status = "FULLY_FILLED"
        elif report.filled_legs > 0:
            report.status = "PARTIALLY_FILLED"
        else:
            report.status = "FAILED"

        return report

    async def route_exit_signal(self, signal: TradeSignal) -> ExecutionReport:
        """
        Route an exit signal.
        Short legs are closed FIRST (removing risk), then long wings are closed.
        """
        report = ExecutionReport(
            signal_id=signal.signal_id,
            strategy_name=f"EXIT_{signal.strategy_type.value}",
            underlying=signal.underlying,
            status="PENDING",
            total_legs=len(signal.legs),
        )

        # For exits, we reverse actions:
        # Original SELL legs need to BUY to close -> do FIRST
        # Original BUY legs need to SELL to close -> do SECOND
        ordered_legs = sorted(signal.legs, key=lambda l: 0 if l.action == OrderAction.SELL else 1)

        for leg in ordered_legs:
            # Closing action is opposite of original entry action
            close_action = OrderAction.BUY if leg.action == OrderAction.SELL else OrderAction.SELL
            closing_leg = leg.model_copy(update={"action": close_action})

            leg_res = await self._execute_single_leg(closing_leg, strategy_tag=f"EXIT_{signal.strategy_type.value}")
            report.leg_results.append(leg_res)
            if leg_res.status == "SUCCESS":
                report.filled_legs += 1

            if self.delay_between_legs > 0:
                await asyncio.sleep(self.delay_between_legs)

        report.status = "FULLY_FILLED" if report.filled_legs == report.total_legs else "PARTIALLY_FILLED"
        return report

    async def route_hedge_adjustment(self, hedge_signal: HedgeAdjustmentSignal) -> ExecutionReport:
        """
        Route dynamic hedge adjustment actions (Roll Untested Side, Delta Neutralize, Wing Protection).
        """
        report = ExecutionReport(
            signal_id=hedge_signal.adjustment_id,
            strategy_name=f"HEDGE_{hedge_signal.hedge_action.value}",
            underlying=UnderlyingIndex.NIFTY,  # fallback resolved from legs
            status="PENDING",
            total_legs=len(hedge_signal.legs_to_close) + len(hedge_signal.legs_to_open),
        )

        if hedge_signal.hedge_action == HedgeActionType.NO_HEDGE_NEEDED:
            report.status = "NO_ACTION_REQUIRED"
            return report

        # Step 1: Close legs that need adjustment (e.g. decayed untested put)
        for leg in hedge_signal.legs_to_close:
            close_action = OrderAction.BUY if leg.action == OrderAction.SELL else OrderAction.SELL
            closing_leg = leg.model_copy(update={"action": close_action})
            res = await self._execute_single_leg(closing_leg, strategy_tag="HEDGE_CLOSE")
            report.leg_results.append(res)
            if res.status == "SUCCESS":
                report.filled_legs += 1

        # Step 2: Open replacement/protection legs
        # Follow margin safety: BUY legs before SELL legs
        open_legs = sorted(hedge_signal.legs_to_open, key=lambda l: 0 if l.action == OrderAction.BUY else 1)
        for leg in open_legs:
            res = await self._execute_single_leg(leg, strategy_tag="HEDGE_OPEN")
            report.leg_results.append(res)
            if res.status == "SUCCESS":
                report.filled_legs += 1

        report.status = "FULLY_FILLED" if report.filled_legs == report.total_legs else "PARTIALLY_FILLED"
        return report

    async def _execute_single_leg(self, leg: OptionLeg, strategy_tag: str) -> LegExecutionResult:
        """Execute an individual leg order via OpenAlgo place_order."""
        exchange = "BFO" if leg.underlying == UnderlyingIndex.SENSEX else "NFO"
        symbol = leg.symbol or f"{leg.underlying.value}_{int(leg.strike)}_{leg.option_type.value}"

        res = LegExecutionResult(
            leg_symbol=symbol,
            action=leg.action,
            strike=leg.strike,
            quantity=leg.quantity,
        )

        try:
            order_res = await self.client.place_order(
                symbol=symbol,
                action=leg.action.value,
                quantity=leg.quantity,
                exchange=exchange,
                pricetype="MARKET",
                product=self.client.config.default_product,
                strategy=strategy_tag,
            )

            res.status = "SUCCESS"
            res.order_id = order_res.get("orderid", order_res.get("data", {}).get("orderid", "ORD_OK"))
            return res

        except OpenAlgoError as e:
            res.status = "FAILED"
            res.error_message = str(e)
            return res
        except Exception as ex:
            res.status = "FAILED"
            res.error_message = f"Unexpected execution error: {ex}"
            return res

    async def _execute_atomic_multiorder(self, signal: TradeSignal, report: ExecutionReport) -> ExecutionReport:
        """Place multi-leg order atomically using OpenAlgo optionsmultiorder endpoint."""
        exchange = "BSE_INDEX" if signal.underlying == UnderlyingIndex.SENSEX else "NSE_INDEX"
        legs_payload = []

        for leg in signal.legs:
            legs_payload.append({
                "symbol": leg.symbol,
                "option_type": leg.option_type.value,
                "action": leg.action.value,
                "quantity": leg.quantity,
            })

        try:
            res = await self.client.place_options_multiorder(
                underlying=signal.underlying.value,
                legs=legs_payload,
                exchange=exchange,
                strategy=signal.strategy_type.value,
            )
            report.status = "FULLY_FILLED"
            report.filled_legs = len(signal.legs)
            for leg in signal.legs:
                report.leg_results.append(
                    LegExecutionResult(
                        leg_symbol=leg.symbol,
                        action=leg.action,
                        strike=leg.strike,
                        quantity=leg.quantity,
                        status="SUCCESS",
                        order_id=res.get("orderid", "MULTI_OK"),
                    )
                )
            return report
        except Exception as e:
            report.status = "FAILED"
            report.error_summary = str(e)
            return report
