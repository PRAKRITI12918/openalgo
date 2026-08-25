"""
Dynamic Hedge Management Engine.
Monitors multi-leg options portfolios for Delta/Gamma Greek imbalances,
and generates automated adjustment instructions (rolling untested side, buying wing protection, delta neutralizing).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple
import uuid

from src.strategy_engine.models import (
    HedgeActionType,
    HedgeAdjustmentSignal,
    OptionChainSnapshot,
    OptionLeg,
    OptionStrikeData,
    OptionType,
    OrderAction,
    PositionState,
    StrategyType,
    UnderlyingIndex,
)
from src.strategy_engine.strike_selector import StrikeSelector


@dataclass(frozen=True)
class HedgeManagerConfig:
    """Configurable risk thresholds for dynamic hedging."""
    # Delta Imbalance Thresholds
    max_net_delta_abs: float = 10.0          # Max absolute aggregate delta before neutralizing
    max_delta_per_lot: float = 0.25         # Max delta per lot before rebalance

    # Leg Delta Pressure
    tested_short_delta_threshold: float = 0.30  # Delta level at which a short leg is deemed under pressure
    untested_short_delta_floor: float = 0.12    # Delta level below which untested leg should be rolled closer

    # Wing Protection
    gamma_spike_limit: float = 0.05         # Gamma spike threshold for tail risk wing addition


class HedgeManager:
    """
    Dynamic hedge manager for multi-leg option portfolios.
    Detects Greek imbalance and outputs structured HedgeAdjustmentSignals.
    """

    def __init__(
        self,
        config: Optional[HedgeManagerConfig] = None,
        strike_selector: Optional[StrikeSelector] = None,
    ):
        self.config = config or HedgeManagerConfig()
        self.strike_selector = strike_selector or StrikeSelector()

    def evaluate_hedge_requirement(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
    ) -> HedgeAdjustmentSignal:
        """
        Evaluate an active position against Greek imbalance triggers and return an adjustment action.

        Args:
            position: Active multi-leg PositionState
            chain: Current option chain snapshot with latest prices and Greeks

        Returns:
            HedgeAdjustmentSignal specifying exact legs to close and open.
        """
        # 1. Update position Greeks with latest chain data
        self._sync_position_greeks(position, chain)

        cfg = self.config
        net_delta = position.net_delta

        # 2. Check for Gamma Spike Tail Risk first (highest danger)
        if abs(position.net_gamma) > cfg.gamma_spike_limit:
            return self._generate_wing_protection_signal(position, chain)

        # 3. Check for Tested Side vs Untested Side Pressure (e.g. in Iron Condor / Strangles)
        if position.strategy_type in (StrategyType.IRON_CONDOR, StrategyType.HEDGED_STRADDLE, StrategyType.SHORT_STRANGLE):
            tested_signal = self._check_tested_side_roll(position, chain)
            if tested_signal is not None:
                return tested_signal

        # 4. Check for Aggregate Net Delta Breach
        lots = max(1, sum(leg.quantity for leg in position.legs if leg.action == OrderAction.SELL) // chain.underlying.default_lot_size)
        effective_delta_cap = max(cfg.max_net_delta_abs, cfg.max_delta_per_lot * lots * chain.underlying.default_lot_size)

        if abs(net_delta) > effective_delta_cap:
            return self._generate_delta_neutralize_signal(position, chain, net_delta)

        # Default: No hedge required
        return HedgeAdjustmentSignal(
            position_id=position.position_id,
            trigger_reason="Greeks are balanced within risk tolerances.",
            imbalance_type="NONE",
            hedge_action=HedgeActionType.NO_HEDGE_NEEDED,
            legs_to_close=[],
            legs_to_open=[],
            expected_delta_after=net_delta,
            timestamp=datetime.utcnow(),
        )

    def _sync_position_greeks(self, position: PositionState, chain: OptionChainSnapshot) -> None:
        """Sync live Greeks from option chain into position legs and recalculate aggregates."""
        for leg in position.legs:
            live_data = chain.get_strike(leg.strike, leg.option_type)
            if live_data:
                leg.current_price = live_data.ltp
                if live_data.greeks:
                    leg.greeks = live_data.greeks
                    leg.actual_delta = live_data.greeks.delta
        position.recalculate_greeks()

    def _check_tested_side_roll(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
    ) -> Optional[HedgeAdjustmentSignal]:
        """
        Detect if one side of a credit spread is tested and generate a Roll Untested Side adjustment.
        """
        cfg = self.config
        short_ce = next((l for l in position.legs if l.action == OrderAction.SELL and l.option_type == OptionType.CE), None)
        short_pe = next((l for l in position.legs if l.action == OrderAction.SELL and l.option_type == OptionType.PE), None)

        if not short_ce or not short_pe or not short_ce.greeks or not short_pe.greeks:
            return None

        ce_delta = abs(short_ce.greeks.delta)
        pe_delta = abs(short_pe.greeks.delta)

        # Case A: Market rallied -> Call side tested (ce_delta high, pe_delta decayed or delta asymmetry)
        if (ce_delta >= cfg.tested_short_delta_threshold and pe_delta <= cfg.untested_short_delta_floor) or (
            ce_delta >= 0.35 and (pe_delta < 0.15 or (ce_delta / max(0.01, pe_delta) >= 2.5))
        ):
            return self._roll_untested_put_side(position, chain, short_pe)

        # Case B: Market fell -> Put side tested (pe_delta high, ce_delta decayed or delta asymmetry)
        if (pe_delta >= cfg.tested_short_delta_threshold and ce_delta <= cfg.untested_short_delta_floor) or (
            pe_delta >= 0.35 and (ce_delta < 0.15 or (pe_delta / max(0.01, ce_delta) >= 2.5))
        ):
            return self._roll_untested_call_side(position, chain, short_ce)


        return None


    def _roll_untested_put_side(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
        untested_put_leg: OptionLeg,
    ) -> HedgeAdjustmentSignal:
        """Roll untested Put leg closer to the market to collect credit and neutralize delta."""
        # Find corresponding long put wing if Iron Condor
        long_pe = next(
            (l for l in position.legs if l.action == OrderAction.BUY and l.option_type == OptionType.PE and l.is_hedge_leg),
            None,
        )

        legs_to_close = [
            self._close_leg(untested_put_leg, chain),
        ]
        if long_pe:
            legs_to_close.append(self._close_leg(long_pe, chain))

        # Select new Put short strike at ~0.20 delta (closer to spot)
        new_short_pe = self.strike_selector.find_strike_by_delta(chain, target_delta=0.20, option_type=OptionType.PE)
        legs_to_open = [
            self._open_leg(new_short_pe, OrderAction.SELL, untested_put_leg.quantity, chain, is_hedge=False),
        ]

        if long_pe:
            step = chain.underlying.strike_step
            new_long_pe = self.strike_selector.find_strike_by_distance(
                chain, new_short_pe.strike, step * 4, OptionType.PE
            )
            legs_to_open.append(
                self._open_leg(new_long_pe, OrderAction.BUY, long_pe.quantity, chain, is_hedge=True)
            )

        return HedgeAdjustmentSignal(
            position_id=position.position_id,
            trigger_reason=(
                f"Call side under pressure (Short CE Delta: {position.net_delta:.2f}). "
                f"Rolling untested Put side UP from strike {untested_put_leg.strike} to {new_short_pe.strike}."
            ),
            imbalance_type="TESTED_CALL_SIDE_PRESSURE",
            hedge_action=HedgeActionType.ROLL_UNTESTED_SIDE,
            legs_to_close=legs_to_close,
            legs_to_open=legs_to_open,
            expected_delta_after=0.0,
            timestamp=datetime.utcnow(),
        )

    def _roll_untested_call_side(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
        untested_call_leg: OptionLeg,
    ) -> HedgeAdjustmentSignal:
        """Roll untested Call leg down closer to the market to collect credit and neutralize delta."""
        long_ce = next(
            (l for l in position.legs if l.action == OrderAction.BUY and l.option_type == OptionType.CE and l.is_hedge_leg),
            None,
        )

        legs_to_close = [
            self._close_leg(untested_call_leg, chain),
        ]
        if long_ce:
            legs_to_close.append(self._close_leg(long_ce, chain))

        # Select new Call short strike at ~0.20 delta (closer to spot)
        new_short_ce = self.strike_selector.find_strike_by_delta(chain, target_delta=0.20, option_type=OptionType.CE)
        legs_to_open = [
            self._open_leg(new_short_ce, OrderAction.SELL, untested_call_leg.quantity, chain, is_hedge=False),
        ]

        if long_ce:
            step = chain.underlying.strike_step
            new_long_ce = self.strike_selector.find_strike_by_distance(
                chain, new_short_ce.strike, step * 4, OptionType.CE
            )
            legs_to_open.append(
                self._open_leg(new_long_ce, OrderAction.BUY, long_ce.quantity, chain, is_hedge=True)
            )

        return HedgeAdjustmentSignal(
            position_id=position.position_id,
            trigger_reason=(
                f"Put side under pressure (Short PE Delta: {position.net_delta:.2f}). "
                f"Rolling untested Call side DOWN from strike {untested_call_leg.strike} to {new_short_ce.strike}."
            ),
            imbalance_type="TESTED_PUT_SIDE_PRESSURE",
            hedge_action=HedgeActionType.ROLL_UNTESTED_SIDE,
            legs_to_close=legs_to_close,
            legs_to_open=legs_to_open,
            expected_delta_after=0.0,
            timestamp=datetime.utcnow(),
        )

    def _generate_delta_neutralize_signal(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
        net_delta: float,
    ) -> HedgeAdjustmentSignal:
        """Add an opposing option hedge leg to bring portfolio net delta back to ~0.0."""
        lot_size = chain.underlying.default_lot_size
        needed_delta = -net_delta

        if needed_delta > 0:
            # Need positive delta -> Buy OTM Call or Sell OTM Put
            hedge_strike = self.strike_selector.find_strike_by_delta(chain, target_delta=0.25, option_type=OptionType.CE)
            opt_delta = hedge_strike.greeks.delta if hedge_strike.greeks else 0.25
            contracts = max(lot_size, int(round(needed_delta / max(0.05, opt_delta) / lot_size)) * lot_size)
            leg_action = OrderAction.BUY
            opt_type = OptionType.CE
        else:
            # Need negative delta -> Buy OTM Put or Sell OTM Call
            hedge_strike = self.strike_selector.find_strike_by_delta(chain, target_delta=0.25, option_type=OptionType.PE)
            opt_delta = abs(hedge_strike.greeks.delta) if hedge_strike.greeks else 0.25
            contracts = max(lot_size, int(round(abs(needed_delta) / max(0.05, opt_delta) / lot_size)) * lot_size)
            leg_action = OrderAction.BUY
            opt_type = OptionType.PE

        legs_to_open = [
            self._open_leg(hedge_strike, leg_action, contracts, chain, is_hedge=True),
        ]

        return HedgeAdjustmentSignal(
            position_id=position.position_id,
            trigger_reason=f"Net Delta breach ({net_delta:+.2f}). Adding delta-neutralizing hedge leg.",
            imbalance_type="DELTA_IMBALANCE_BREACH",
            hedge_action=HedgeActionType.DELTA_NEUTRALIZE,
            legs_to_close=[],
            legs_to_open=legs_to_open,
            expected_delta_after=round(net_delta + (contracts * (opt_delta if needed_delta > 0 else -opt_delta)), 2),
            timestamp=datetime.utcnow(),
        )

    def _generate_wing_protection_signal(
        self,
        position: PositionState,
        chain: OptionChainSnapshot,
    ) -> HedgeAdjustmentSignal:
        """Buy deep OTM wing protection to cap tail-risk / high gamma."""
        wing_ce = self.strike_selector.find_strike_by_delta(chain, target_delta=0.06, option_type=OptionType.CE)
        wing_pe = self.strike_selector.find_strike_by_delta(chain, target_delta=0.06, option_type=OptionType.PE)
        lot_size = chain.underlying.default_lot_size

        legs_to_open = [
            self._open_leg(wing_ce, OrderAction.BUY, lot_size, chain, is_hedge=True),
            self._open_leg(wing_pe, OrderAction.BUY, lot_size, chain, is_hedge=True),
        ]

        return HedgeAdjustmentSignal(
            position_id=position.position_id,
            trigger_reason="Excessive short gamma detected. Purchasing deep OTM wing protection.",
            imbalance_type="GAMMA_SPIKE",
            hedge_action=HedgeActionType.ADD_WING_PROTECTION,
            legs_to_close=[],
            legs_to_open=legs_to_open,
            expected_delta_after=position.net_delta,
            timestamp=datetime.utcnow(),
        )

    def _close_leg(self, leg: OptionLeg, chain: OptionChainSnapshot) -> OptionLeg:
        """Create counter leg to close existing position leg."""
        close_action = OrderAction.SELL if leg.action == OrderAction.BUY else OrderAction.BUY
        live = chain.get_strike(leg.strike, leg.option_type)
        return OptionLeg(
            symbol=leg.symbol,
            underlying=leg.underlying,
            strike=leg.strike,
            option_type=leg.option_type,
            expiry=leg.expiry,
            action=close_action,
            quantity=leg.quantity,
            entry_price=leg.entry_price,
            current_price=live.ltp if live else leg.current_price,
            greeks=live.greeks if live else leg.greeks,
            is_hedge_leg=leg.is_hedge_leg,
        )

    def _open_leg(
        self,
        strike_data: OptionStrikeData,
        action: OrderAction,
        quantity: int,
        chain: OptionChainSnapshot,
        is_hedge: bool = True,
    ) -> OptionLeg:
        """Create new hedge leg to open."""
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
