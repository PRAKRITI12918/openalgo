"""
Real-Time Position Tracker & Greek Aggregator.
Syncs live Dhan broker positions from OpenAlgo /api/v1/positionbook, maps them into
typed PositionState models, and coordinates dynamic hedging with HedgeManager.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.broker_pipeline.openalgo_client import OpenAlgoClient
from src.strategy_engine.hedge_manager import HedgeManager
from src.strategy_engine.models import (
    Greeks,
    HedgeAdjustmentSignal,
    MarketRegime,
    OptionChainSnapshot,
    OptionLeg,
    OptionType,
    OrderAction,
    PositionState,
    StrategyType,
    UnderlyingIndex,
)

logger = logging.getLogger("broker_pipeline.tracker")


class PositionTracker:
    """
    Tracks live broker positions and aggregates Greeks for dynamic risk management.
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        hedge_manager: Optional[HedgeManager] = None,
    ):
        self.client = client
        self.hedge_manager = hedge_manager or HedgeManager()
        self._active_positions: Dict[str, PositionState] = {}
        self._last_funds: Dict[str, Any] = {}

    @property
    def active_positions(self) -> Dict[str, PositionState]:
        """Return currently tracked active positions."""
        return self._active_positions

    async def sync_positions(self, chain_snapshots: Optional[Dict[UnderlyingIndex, OptionChainSnapshot]] = None) -> List[PositionState]:
        """
        Poll /api/v1/positionbook, parse open derivative legs, and construct PositionState objects.
        """
        try:
            book_res = await self.client.get_position_book()
            raw_positions = book_res.get("data", []) if isinstance(book_res, dict) else []
            if isinstance(raw_positions, dict):
                raw_positions = raw_positions.get("positions", [])

            open_legs: List[OptionLeg] = []

            for p in raw_positions:
                qty = int(p.get("quantity", p.get("net_qty", 0)))
                if qty == 0:
                    continue  # Ignore flat/closed positions

                symbol = p.get("symbol", "")
                exchange = p.get("exchange", "NFO")
                buy_price = float(p.get("buy_price", p.get("buy_avg", 0.0)))
                sell_price = float(p.get("sell_price", p.get("sell_avg", 0.0)))
                ltp = float(p.get("ltp", p.get("current_price", 0.0)))

                action = OrderAction.BUY if qty > 0 else OrderAction.SELL
                abs_qty = abs(qty)
                entry_price = buy_price if action == OrderAction.BUY else sell_price

                # Parse option attributes from symbol (e.g. NIFTY26AUG24000CE or NIFTY_24000_CE)
                underlying, strike, opt_type, expiry = self._parse_symbol_metadata(symbol)

                leg = OptionLeg(
                    symbol=symbol,
                    underlying=underlying,
                    strike=strike,
                    option_type=opt_type,
                    expiry=expiry,
                    action=action,
                    quantity=abs_qty,
                    entry_price=entry_price,
                    current_price=ltp,
                )

                # Enrich with Greeks if chain snapshot is provided
                if chain_snapshots and underlying in chain_snapshots:
                    chain = chain_snapshots[underlying]
                    strike_data = chain.get_strike(strike, opt_type)
                    if strike_data and strike_data.greeks:
                        leg.greeks = strike_data.greeks
                        leg.actual_delta = strike_data.greeks.delta
                        leg.current_price = strike_data.ltp

                open_legs.append(leg)

            # Group legs by underlying and create/update PositionStates
            synced_states = self._group_legs_into_strategies(open_legs)
            self._active_positions = {p.position_id: p for p in synced_states}
            return synced_states

        except Exception as e:
            logger.error(f"Error syncing position book: {e}")
            return list(self._active_positions.values())

    async def sync_funds(self) -> Dict[str, Any]:
        """Fetch latest margin and cash balances."""
        try:
            res = await self.client.get_funds()
            data = res.get("data", res)
            self._last_funds = data
            return data
        except Exception as e:
            logger.error(f"Error syncing funds: {e}")
            return self._last_funds

    def evaluate_hedges(
        self,
        chain_snapshots: Dict[UnderlyingIndex, OptionChainSnapshot],
    ) -> List[Tuple[PositionState, HedgeAdjustmentSignal]]:
        """
        Evaluate active positions against HedgeManager triggers.
        Returns a list of (PositionState, HedgeAdjustmentSignal) pairs where adjustments are needed.
        """
        adjustments: List[Tuple[PositionState, HedgeAdjustmentSignal]] = []

        for pos in self._active_positions.values():
            if pos.underlying not in chain_snapshots:
                continue

            chain = chain_snapshots[pos.underlying]
            signal = self.hedge_manager.evaluate_hedge_requirement(pos, chain)
            if signal.hedge_action != HedgeActionType.NO_HEDGE_NEEDED:
                logger.warning(
                    f"Hedge required for {pos.strategy_type.value} [{pos.position_id}]: "
                    f"{signal.hedge_action.value} -> {signal.trigger_reason}"
                )
                adjustments.append((pos, signal))

        return adjustments

    def _group_legs_into_strategies(self, legs: List[OptionLeg]) -> List[PositionState]:
        """Group option legs into composite PositionState structures."""
        if not legs:
            return []

        # Simple grouping by underlying index
        grouped: Dict[UnderlyingIndex, List[OptionLeg]] = {}
        for leg in legs:
            grouped.setdefault(leg.underlying, []).append(leg)

        states: List[PositionState] = []
        for underlying, u_legs in grouped.items():
            # Classify strategy structure from legs count
            strat_type = StrategyType.IRON_CONDOR
            if len(u_legs) == 4:
                strat_type = StrategyType.IRON_CONDOR
            elif len(u_legs) == 2:
                ce_legs = [l for l in u_legs if l.option_type == OptionType.CE]
                pe_legs = [l for l in u_legs if l.option_type == OptionType.PE]
                if len(ce_legs) == 1 and len(pe_legs) == 1:
                    strat_type = StrategyType.SHORT_STRANGLE
                elif len(ce_legs) == 2:
                    strat_type = StrategyType.BULL_CALL_SPREAD
                elif len(pe_legs) == 2:
                    strat_type = StrategyType.BEAR_PUT_SPREAD

            pos = PositionState(
                strategy_type=strat_type,
                underlying=underlying,
                entry_regime=MarketRegime.LOW_IV_RANGING,
                legs=u_legs,
            )
            pos.recalculate_greeks()
            states.append(pos)

        return states

    def _parse_symbol_metadata(self, symbol: str) -> Tuple[UnderlyingIndex, float, OptionType, str]:
        """Parse underlying, strike, option type, and expiry from Indian option symbol string."""
        symbol_upper = symbol.upper()

        # Identify index
        if "BANKNIFTY" in symbol_upper:
            underlying = UnderlyingIndex.BANKNIFTY
        elif "SENSEX" in symbol_upper:
            underlying = UnderlyingIndex.SENSEX
        else:
            underlying = UnderlyingIndex.NIFTY

        # Option type
        opt_type = OptionType.PE if symbol_upper.endswith("PE") or "_PE" in symbol_upper else OptionType.CE

        # Strike extraction
        strike_match = re.findall(r"(\d{5})", symbol_upper)
        if strike_match:
            strike = float(strike_match[-1])
        else:
            strike_match_short = re.findall(r"(\d{4,6})", symbol_upper)
            strike = float(strike_match_short[-1]) if strike_match_short else 24000.0

        expiry = "NEAR"
        return underlying, strike, opt_type, expiry
