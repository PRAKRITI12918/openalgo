"""
Multi-Leg Strategy Signal Generator.
Generates entry, exit, stop-loss, profit-target, and trailing signals based on regime compatibility.
Handles Iron Condor, Bull Call Spread, Bear Put Spread, Calendar Spread, Ratio Spread, and Hedged Straddle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
import uuid

from src.strategy_engine.models import (
    MarketIndicators,
    MarketRegime,
    OptionChainSnapshot,
    OptionLeg,
    OptionStrikeData,
    OptionType,
    OrderAction,
    PositionState,
    RegimeClassification,
    SignalType,
    StrategyType,
    TradeSignal,
    TrendDirection,
    UnderlyingIndex,
)
from src.strategy_engine.strike_selector import StrikeSelector


class SignalGenerator:
    """
    Quantitative strategy signal generator.
    Translates market regimes and option chain data into deterministic TradeSignals.
    """

    def __init__(self, strike_selector: Optional[StrikeSelector] = None):
        self.strike_selector = strike_selector or StrikeSelector()

    def generate_entry_signal(
        self,
        strategy_type: StrategyType,
        chain: OptionChainSnapshot,
        regime_info: RegimeClassification,
        quantity_lots: int = 1,
        far_chain: Optional[OptionChainSnapshot] = None,
    ) -> Optional[TradeSignal]:
        """
        Generate a multi-leg entry TradeSignal for the requested strategy type.

        Args:
            strategy_type: Desired StrategyType
            chain: Current expiry option chain snapshot
            regime_info: Current classified market regime
            quantity_lots: Lot multiplier
            far_chain: Far-term chain snapshot (required for Calendar Spreads)

        Returns:
            TradeSignal with complete leg details and risk boundaries, or None if conditions not met.
        """
        lot_size = chain.underlying.default_lot_size
        total_quantity = quantity_lots * lot_size

        if strategy_type == StrategyType.IRON_CONDOR:
            return self._build_iron_condor(chain, regime_info, total_quantity)

        elif strategy_type == StrategyType.BULL_CALL_SPREAD:
            return self._build_bull_call_spread(chain, regime_info, total_quantity)

        elif strategy_type == StrategyType.BEAR_PUT_SPREAD:
            return self._build_bear_put_spread(chain, regime_info, total_quantity)

        elif strategy_type == StrategyType.HEDGED_STRADDLE:
            return self._build_hedged_straddle(chain, regime_info, total_quantity)

        elif strategy_type == StrategyType.RATIO_SPREAD:
            return self._build_ratio_spread(chain, regime_info, total_quantity)

        elif strategy_type == StrategyType.CALENDAR_SPREAD:
            if not far_chain:
                raise ValueError("Calendar spread requires far_chain snapshot.")
            return self._build_calendar_spread(chain, far_chain, regime_info, total_quantity)

        return None

    def evaluate_exit_signals(
        self,
        position: PositionState,
        current_chain: OptionChainSnapshot,
        current_pnl: float,
        current_regime: Optional[MarketRegime] = None,
        target_pnl_threshold: Optional[float] = None,
        stop_loss_pnl_threshold: Optional[float] = None,
    ) -> TradeSignal:
        """
        Evaluate active position against target, stop-loss, trailing stops, and regime shifts.

        Args:
            position: Active PositionState
            current_chain: Latest option chain snapshot
            current_pnl: Total position PnL in currency
            current_regime: Latest classified market regime
            target_pnl_threshold: Explicit target PnL (optional override)
            stop_loss_pnl_threshold: Explicit max loss PnL (negative value)

        Returns:
            TradeSignal indicating EXIT, STOP_LOSS, TARGET, or NO_ACTION.
        """
        # Create exit legs (mirror actions: BUY -> SELL, SELL -> BUY)
        exit_legs: List[OptionLeg] = []
        for leg in position.legs:
            exit_action = OrderAction.SELL if leg.action == OrderAction.BUY else OrderAction.BUY
            current_strike_data = current_chain.get_strike(leg.strike, leg.option_type)
            current_px = current_strike_data.ltp if current_strike_data else leg.current_price
            exit_legs.append(
                OptionLeg(
                    symbol=leg.symbol,
                    underlying=leg.underlying,
                    strike=leg.strike,
                    option_type=leg.option_type,
                    expiry=leg.expiry,
                    action=exit_action,
                    quantity=leg.quantity,
                    entry_price=leg.entry_price,
                    current_price=current_px,
                    greeks=current_strike_data.greeks if current_strike_data else leg.greeks,
                    is_hedge_leg=leg.is_hedge_leg,
                )
            )

        # 1. Profit Target Check
        if target_pnl_threshold is not None and current_pnl >= target_pnl_threshold:
            return TradeSignal(
                strategy_type=position.strategy_type,
                signal_type=SignalType.TARGET,
                underlying=position.underlying,
                regime=current_regime or position.entry_regime,
                legs=exit_legs,
                reason=f"Target PnL reached: {current_pnl:.2f} >= {target_pnl_threshold:.2f}",
                timestamp=datetime.utcnow(),
            )

        # 2. Stop Loss Check
        if stop_loss_pnl_threshold is not None and current_pnl <= stop_loss_pnl_threshold:
            return TradeSignal(
                strategy_type=position.strategy_type,
                signal_type=SignalType.STOP_LOSS,
                underlying=position.underlying,
                regime=current_regime or position.entry_regime,
                legs=exit_legs,
                reason=f"Stop Loss breached: {current_pnl:.2f} <= {stop_loss_pnl_threshold:.2f}",
                timestamp=datetime.utcnow(),
            )

        # 3. Hostile Regime Shift Check (e.g. Non-directional Iron Condor entering Volatility Expansion)
        if current_regime == MarketRegime.VOLATILITY_EXPANSION and position.strategy_type in (
            StrategyType.IRON_CONDOR,
            StrategyType.HEDGED_STRADDLE,
        ):
            return TradeSignal(
                strategy_type=position.strategy_type,
                signal_type=SignalType.EXIT,
                underlying=position.underlying,
                regime=current_regime,
                legs=exit_legs,
                reason="Hostile regime shift to VOLATILITY_EXPANSION detected. Exiting short-gamma position.",
                timestamp=datetime.utcnow(),
            )

        # Default: Hold
        return TradeSignal(
            strategy_type=position.strategy_type,
            signal_type=SignalType.NO_ACTION,
            underlying=position.underlying,
            regime=current_regime or position.entry_regime,
            legs=[],
            reason="Position within acceptable parameters. Holding.",
            timestamp=datetime.utcnow(),
        )

    # --- Strategy Builders ---

    def _build_iron_condor(
        self,
        chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build 4-leg Iron Condor entry signal."""
        short_ce, long_ce, short_pe, long_pe = self.strike_selector.select_iron_condor_strikes(chain)

        legs = [
            self._create_leg(short_ce, OrderAction.SELL, quantity, chain, is_hedge=False),
            self._create_leg(long_ce, OrderAction.BUY, quantity, chain, is_hedge=True),
            self._create_leg(short_pe, OrderAction.SELL, quantity, chain, is_hedge=False),
            self._create_leg(long_pe, OrderAction.BUY, quantity, chain, is_hedge=True),
        ]

        net_credit = (short_ce.ltp + short_pe.ltp) - (long_ce.ltp + long_pe.ltp)
        ce_wing_width = abs(long_ce.strike - short_ce.strike)
        pe_wing_width = abs(short_pe.strike - long_pe.strike)
        max_wing_width = max(ce_wing_width, pe_wing_width)

        max_profit = net_credit * quantity
        max_loss = (max_wing_width - net_credit) * quantity
        stop_loss = -(net_credit * 1.5) * quantity  # 1.5x credit stop loss rule
        target = (net_credit * 0.60) * quantity     # 60% max profit target

        return TradeSignal(
            strategy_type=StrategyType.IRON_CONDOR,
            signal_type=SignalType.ENTRY,
            underlying=chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=round(net_credit, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            stop_loss_threshold=round(stop_loss, 2),
            target_threshold=round(target, 2),
            reason=f"Iron Condor initiated for {regime.regime.value} (Credit: {net_credit:.2f} pts)",
        )

    def _build_bull_call_spread(
        self,
        chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build Bull Call Spread (Buy ATM CE, Sell OTM CE)."""
        buy_ce, sell_ce = self.strike_selector.select_directional_spread_strikes(chain, OptionType.CE)

        legs = [
            self._create_leg(buy_ce, OrderAction.BUY, quantity, chain, is_hedge=False),
            self._create_leg(sell_ce, OrderAction.SELL, quantity, chain, is_hedge=True),
        ]

        net_debit = buy_ce.ltp - sell_ce.ltp
        strike_width = sell_ce.strike - buy_ce.strike

        max_profit = (strike_width - net_debit) * quantity
        max_loss = net_debit * quantity
        stop_loss = -(net_debit * 0.50) * quantity  # 50% max debit stop loss
        target = (strike_width - net_debit) * 0.75 * quantity

        return TradeSignal(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            signal_type=SignalType.ENTRY,
            underlying=chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=-round(net_debit, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            stop_loss_threshold=round(stop_loss, 2),
            target_threshold=round(target, 2),
            reason=f"Bull Call Spread ({buy_ce.strike}/{sell_ce.strike} CE) in {regime.regime.value}",
        )

    def _build_bear_put_spread(
        self,
        chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build Bear Put Spread (Buy ATM PE, Sell OTM PE)."""
        buy_pe, sell_pe = self.strike_selector.select_directional_spread_strikes(chain, OptionType.PE)

        legs = [
            self._create_leg(buy_pe, OrderAction.BUY, quantity, chain, is_hedge=False),
            self._create_leg(sell_pe, OrderAction.SELL, quantity, chain, is_hedge=True),
        ]

        net_debit = buy_pe.ltp - sell_pe.ltp
        strike_width = buy_pe.strike - sell_pe.strike

        max_profit = (strike_width - net_debit) * quantity
        max_loss = net_debit * quantity
        stop_loss = -(net_debit * 0.50) * quantity
        target = (strike_width - net_debit) * 0.75 * quantity

        return TradeSignal(
            strategy_type=StrategyType.BEAR_PUT_SPREAD,
            signal_type=SignalType.ENTRY,
            underlying=chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=-round(net_debit, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            stop_loss_threshold=round(stop_loss, 2),
            target_threshold=round(target, 2),
            reason=f"Bear Put Spread ({buy_pe.strike}/{sell_pe.strike} PE) in {regime.regime.value}",
        )

    def _build_hedged_straddle(
        self,
        chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build Hedged Straddle / Iron Butterfly (Short ATM CE+PE, Buy OTM Wings)."""
        atm_ce, atm_pe, wing_ce, wing_pe = self.strike_selector.select_hedged_straddle_strikes(chain)

        legs = [
            self._create_leg(atm_ce, OrderAction.SELL, quantity, chain, is_hedge=False),
            self._create_leg(atm_pe, OrderAction.SELL, quantity, chain, is_hedge=False),
            self._create_leg(wing_ce, OrderAction.BUY, quantity, chain, is_hedge=True),
            self._create_leg(wing_pe, OrderAction.BUY, quantity, chain, is_hedge=True),
        ]

        net_credit = (atm_ce.ltp + atm_pe.ltp) - (wing_ce.ltp + wing_pe.ltp)
        wing_width = wing_ce.strike - atm_ce.strike
        max_profit = net_credit * quantity
        max_loss = (wing_width - net_credit) * quantity
        stop_loss = -(net_credit * 0.8) * quantity
        target = (net_credit * 0.50) * quantity

        return TradeSignal(
            strategy_type=StrategyType.HEDGED_STRADDLE,
            signal_type=SignalType.ENTRY,
            underlying=chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=round(net_credit, 2),
            max_profit=round(max_profit, 2),
            max_loss=round(max_loss, 2),
            stop_loss_threshold=round(stop_loss, 2),
            target_threshold=round(target, 2),
            reason=f"Hedged Straddle (Iron Fly at {atm_ce.strike}) in {regime.regime.value}",
        )

    def _build_ratio_spread(
        self,
        chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build 1x2 Ratio Spread (Buy 1 ATM CE, Sell 2 OTM CE or Put equivalent)."""
        opt_type = OptionType.CE if regime.trend == TrendDirection.BULLISH else OptionType.PE
        buy_strike, sell_strike = self.strike_selector.select_ratio_spread_strikes(chain, opt_type)

        legs = [
            self._create_leg(buy_strike, OrderAction.BUY, quantity, chain, is_hedge=False),
            self._create_leg(sell_strike, OrderAction.SELL, quantity * 2, chain, is_hedge=False),
        ]

        # Net credit or debit
        net_flow = (sell_strike.ltp * 2) - buy_strike.ltp
        strike_diff = abs(sell_strike.strike - buy_strike.strike)
        max_profit = (strike_diff + net_flow) * quantity

        return TradeSignal(
            strategy_type=StrategyType.RATIO_SPREAD,
            signal_type=SignalType.ENTRY,
            underlying=chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=round(net_flow, 2),
            max_profit=round(max_profit, 2),
            max_loss=None,  # Uncapped on 1 side without further wings
            stop_loss_threshold=-round((strike_diff * 0.5) * quantity, 2),
            target_threshold=round(max_profit * 0.50, 2),
            reason=f"1x2 Ratio Spread ({buy_strike.strike}/{sell_strike.strike} {opt_type.value}) in {regime.regime.value}",
        )

    def _build_calendar_spread(
        self,
        near_chain: OptionChainSnapshot,
        far_chain: OptionChainSnapshot,
        regime: RegimeClassification,
        quantity: int,
    ) -> TradeSignal:
        """Build Calendar Spread (Sell Near ATM CE, Buy Far ATM CE)."""
        near_atm = self.strike_selector.find_atm_strike(near_chain, OptionType.CE)
        far_atm = far_chain.get_strike(near_atm.strike, OptionType.CE)
        if not far_atm:
            far_atm = self.strike_selector.find_atm_strike(far_chain, OptionType.CE)

        legs = [
            self._create_leg(near_atm, OrderAction.SELL, quantity, near_chain, is_hedge=False),
            self._create_leg(far_atm, OrderAction.BUY, quantity, far_chain, is_hedge=True),
        ]

        net_debit = far_atm.ltp - near_atm.ltp
        max_loss = net_debit * quantity

        return TradeSignal(
            strategy_type=StrategyType.CALENDAR_SPREAD,
            signal_type=SignalType.ENTRY,
            underlying=near_chain.underlying,
            regime=regime.regime,
            legs=legs,
            entry_credit_debit=-round(net_debit, 2),
            max_profit=round(net_debit * 1.2 * quantity, 2),
            max_loss=round(max_loss, 2),
            stop_loss_threshold=-round(max_loss * 0.40, 2),
            target_threshold=round(net_debit * 0.50 * quantity, 2),
            reason=f"Calendar Spread at {near_atm.strike} ({near_chain.expiry} vs {far_chain.expiry})",
        )

    def _create_leg(
        self,
        strike_data: OptionStrikeData,
        action: OrderAction,
        quantity: int,
        chain: OptionChainSnapshot,
        is_hedge: bool = False,
    ) -> OptionLeg:
        """Helper to create an OptionLeg instance."""
        symbol = f"{chain.underlying.value}_{strike_data.expiry}_{int(strike_data.strike)}_{strike_data.option_type.value}"
        delta_val = strike_data.greeks.delta if strike_data.greeks else None

        return OptionLeg(
            symbol=symbol,
            underlying=chain.underlying,
            strike=strike_data.strike,
            option_type=strike_data.option_type,
            expiry=strike_data.expiry,
            action=action,
            quantity=quantity,
            target_delta=delta_val,
            actual_delta=delta_val,
            entry_price=strike_data.ltp,
            current_price=strike_data.ltp,
            greeks=strike_data.greeks,
            is_hedge_leg=is_hedge,
        )
