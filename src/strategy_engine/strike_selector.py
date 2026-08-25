"""
Strike Selector Engine.
Selects optimal option strikes based on target Delta, ATM proximity, and strict liquidity filters.
Calibrated for Indian index options step intervals (NIFTY, BANKNIFTY, SENSEX).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.strategy_engine.models import (
    OptionChainSnapshot,
    OptionStrikeData,
    OptionType,
    UnderlyingIndex,
)


@dataclass(frozen=True)
class LiquidityFilterConfig:
    """Configurable liquidity criteria for strike validation."""
    min_open_interest: int = 1000          # Minimum OI required in contracts
    min_volume: int = 100                  # Minimum volume in contracts
    max_bid_ask_spread_pct: float = 0.08   # Maximum allowable bid-ask spread (8% of LTP)
    enforce_liquidity: bool = True         # Toggle liquidity enforcement


class StrikeSelector:
    """
    Quantitative strike selection module.
    Evaluates option chains to select optimal strikes by Delta, distance, and liquidity.
    """

    def __init__(self, liquidity_config: Optional[LiquidityFilterConfig] = None):
        self.liquidity_config = liquidity_config or LiquidityFilterConfig()

    def find_atm_strike(
        self,
        chain: OptionChainSnapshot,
        option_type: OptionType = OptionType.CE,
    ) -> OptionStrikeData:
        """
        Find the At-The-Money (ATM) strike in the option chain.
        """
        step = chain.underlying.strike_step
        target_atm_price = round(chain.spot_price / step) * step

        # Filter strikes by option type
        strikes = [s for s in chain.strikes if s.option_type == option_type]
        if not strikes:
            raise ValueError(f"No {option_type.value} strikes available in option chain for {chain.underlying.value}")

        # Find closest match to target ATM price
        closest_strike = min(strikes, key=lambda s: abs(s.strike - target_atm_price))
        return closest_strike

    def find_strike_by_delta(
        self,
        chain: OptionChainSnapshot,
        target_delta: float,
        option_type: OptionType,
        apply_liquidity_filter: bool = True,
    ) -> OptionStrikeData:
        """
        Find the strike closest to the desired target absolute delta (e.g. 0.20 for 20-delta OTM).

        Args:
            chain: OptionChainSnapshot point-in-time snapshot
            target_delta: Target delta in absolute terms (e.g. 0.20 or -0.20)
            option_type: OptionType.CE or OptionType.PE
            apply_liquidity_filter: Whether to filter by OI/volume/spread

        Returns:
            Best matching OptionStrikeData
        """
        abs_target = abs(target_delta)
        strikes = [s for s in chain.strikes if s.option_type == option_type]

        if not strikes:
            raise ValueError(f"No strikes found for {option_type.value} on {chain.underlying.value}")

        # Filter by liquidity if enabled
        if apply_liquidity_filter and self.liquidity_config.enforce_liquidity:
            liquid_strikes = [s for s in strikes if self._is_liquid(s)]
            if liquid_strikes:
                strikes = liquid_strikes  # Use liquid candidate subset

        # If greeks are present, match by Delta
        strikes_with_greeks = [s for s in strikes if s.greeks is not None]
        if strikes_with_greeks:
            best_strike = min(strikes_with_greeks, key=lambda s: abs(abs(s.greeks.delta) - abs_target))
            return best_strike

        # Fallback: estimate delta by moneyness if greeks are absent
        spot = chain.spot_price
        if option_type == OptionType.CE:
            # For Call, higher strike -> lower delta
            otm_strikes = [s for s in strikes if s.strike >= spot]
            candidates = otm_strikes if otm_strikes else strikes
        else:
            # For Put, lower strike -> lower delta (further OTM)
            otm_strikes = [s for s in strikes if s.strike <= spot]
            candidates = otm_strikes if otm_strikes else strikes

        # Approximate delta rank based on distance
        return min(candidates, key=lambda s: abs(s.strike - (spot * (1.0 + (0.5 - abs_target) * 0.08))))

    def find_strike_by_distance(
        self,
        chain: OptionChainSnapshot,
        base_strike: float,
        distance_points: float,
        option_type: OptionType,
    ) -> OptionStrikeData:
        """
        Find strike at a specific distance from a base strike (e.g., base + 300 for CE wing).
        """
        target_strike = base_strike + distance_points if option_type == OptionType.CE else base_strike - distance_points
        step = chain.underlying.strike_step
        target_quantized = round(target_strike / step) * step

        strikes = [s for s in chain.strikes if s.option_type == option_type]
        if not strikes:
            raise ValueError(f"No {option_type.value} strikes available in chain.")

        return min(strikes, key=lambda s: abs(s.strike - target_quantized))

    def select_iron_condor_strikes(
        self,
        chain: OptionChainSnapshot,
        short_ce_delta: float = 0.20,
        short_pe_delta: float = 0.20,
        wing_width_points: Optional[float] = None,
        long_wing_delta: Optional[float] = 0.08,
    ) -> Tuple[OptionStrikeData, OptionStrikeData, OptionStrikeData, OptionStrikeData]:
        """
        Select 4 strikes for an Iron Condor:
        (Short Call, Long Call Wing, Short Put, Long Put Wing)

        Args:
            chain: Option chain snapshot
            short_ce_delta: Target delta for Short Call (e.g. 0.20)
            short_pe_delta: Target delta for Short Put (e.g. 0.20)
            wing_width_points: Explicit wing distance in index points (optional)
            long_wing_delta: Target delta for Long wings if distance not specified

        Returns:
            Tuple of (short_ce, long_ce, short_pe, long_pe)
        """
        short_ce = self.find_strike_by_delta(chain, target_delta=short_ce_delta, option_type=OptionType.CE)
        short_pe = self.find_strike_by_delta(chain, target_delta=short_pe_delta, option_type=OptionType.PE)

        # Ensure Short PE is below Spot and Short CE is above Spot
        if short_pe.strike >= short_ce.strike:
            # Fallback to ATM +/- 2 standard steps
            atm = self.find_atm_strike(chain, OptionType.CE).strike
            step = chain.underlying.strike_step
            short_ce = self.find_strike_by_distance(chain, atm, step * 3, OptionType.CE)
            short_pe = self.find_strike_by_distance(chain, atm, step * 3, OptionType.PE)

        # Select Long Wings
        if wing_width_points is not None and wing_width_points > 0:
            long_ce = self.find_strike_by_distance(chain, short_ce.strike, wing_width_points, OptionType.CE)
            long_pe = self.find_strike_by_distance(chain, short_pe.strike, wing_width_points, OptionType.PE)
        else:
            long_ce = self.find_strike_by_delta(chain, target_delta=long_wing_delta or 0.08, option_type=OptionType.CE)
            long_pe = self.find_strike_by_delta(chain, target_delta=long_wing_delta or 0.08, option_type=OptionType.PE)

            # Ensure wings are strictly outer strikes
            step = chain.underlying.strike_step
            if long_ce.strike <= short_ce.strike:
                long_ce = self.find_strike_by_distance(chain, short_ce.strike, step * 4, OptionType.CE)
            if long_pe.strike >= short_pe.strike:
                long_pe = self.find_strike_by_distance(chain, short_pe.strike, step * 4, OptionType.PE)

        return short_ce, long_ce, short_pe, long_pe

    def select_directional_spread_strikes(
        self,
        chain: OptionChainSnapshot,
        option_type: OptionType,
        buy_delta: float = 0.50,
        sell_delta: float = 0.25,
    ) -> Tuple[OptionStrikeData, OptionStrikeData]:
        """
        Select strikes for Bull Call Spread or Bear Put Spread:
        (Buy Leg [ATM/ITM], Sell Leg [OTM])
        """
        buy_leg = self.find_strike_by_delta(chain, target_delta=buy_delta, option_type=option_type)
        sell_leg = self.find_strike_by_delta(chain, target_delta=sell_delta, option_type=option_type)

        step = chain.underlying.strike_step
        # Validate strike ordering
        if option_type == OptionType.CE:
            if sell_leg.strike <= buy_leg.strike:
                sell_leg = self.find_strike_by_distance(chain, buy_leg.strike, step * 3, OptionType.CE)
        else:
            if sell_leg.strike >= buy_leg.strike:
                sell_leg = self.find_strike_by_distance(chain, buy_leg.strike, step * 3, OptionType.PE)

        return buy_leg, sell_leg

    def select_ratio_spread_strikes(
        self,
        chain: OptionChainSnapshot,
        option_type: OptionType,
        buy_delta: float = 0.50,
        sell_delta: float = 0.20,
    ) -> Tuple[OptionStrikeData, OptionStrikeData]:
        """
        Select strikes for a 1x2 Ratio Spread (Buy 1 ATM, Sell 2 OTM).
        """
        return self.select_directional_spread_strikes(
            chain=chain,
            option_type=option_type,
            buy_delta=buy_delta,
            sell_delta=sell_delta,
        )

    def select_hedged_straddle_strikes(
        self,
        chain: OptionChainSnapshot,
        wing_distance_points: Optional[float] = None,
        wing_delta: float = 0.10,
    ) -> Tuple[OptionStrikeData, OptionStrikeData, OptionStrikeData, OptionStrikeData]:
        """
        Select strikes for Hedged Straddle (Iron Butterfly):
        (Short ATM Call, Short ATM Put, Long OTM Wing Call, Long OTM Wing Put)
        """
        atm_ce = self.find_atm_strike(chain, OptionType.CE)
        atm_pe = self.find_atm_strike(chain, OptionType.PE)

        step = chain.underlying.strike_step
        if wing_distance_points is not None and wing_distance_points > 0:
            wing_ce = self.find_strike_by_distance(chain, atm_ce.strike, wing_distance_points, OptionType.CE)
            wing_pe = self.find_strike_by_distance(chain, atm_pe.strike, wing_distance_points, OptionType.PE)
        else:
            wing_ce = self.find_strike_by_delta(chain, target_delta=wing_delta, option_type=OptionType.CE)
            wing_pe = self.find_strike_by_delta(chain, target_delta=wing_delta, option_type=OptionType.PE)

            # Ensure wings are strictly outer
            if wing_ce.strike <= atm_ce.strike:
                wing_ce = self.find_strike_by_distance(chain, atm_ce.strike, step * 6, OptionType.CE)
            if wing_pe.strike >= atm_pe.strike:
                wing_pe = self.find_strike_by_distance(chain, atm_pe.strike, step * 6, OptionType.PE)

        return atm_ce, atm_pe, wing_ce, wing_pe

    def _is_liquid(self, strike_data: OptionStrikeData) -> bool:
        """Check if an individual strike satisfies the configured liquidity thresholds."""
        cfg = self.liquidity_config
        if strike_data.open_interest < cfg.min_open_interest:
            return False
        if strike_data.volume < cfg.min_volume:
            return False
        if strike_data.spread_percentage > cfg.max_bid_ask_spread_pct:
            return False
        return True
