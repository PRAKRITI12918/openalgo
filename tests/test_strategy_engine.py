"""
Comprehensive Test Suite for Decision & Strategy Logic Engine (Phase 1).
Tests models, Black-Scholes Greeks engine, regime detector, strike selector, signal generator, and dynamic hedge manager.
"""

from datetime import datetime
import pytest

from src.strategy_engine.greeks import (
    black_scholes_price,
    calculate_greeks,
    implied_volatility,
)
from src.strategy_engine.hedge_manager import (
    HedgeManager,
    HedgeManagerConfig,
)
from src.strategy_engine.models import (
    ExpiryType,
    Greeks,
    HedgeActionType,
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
from src.strategy_engine.regime_detector import (
    RegimeDetector,
    RegimeDetectorConfig,
)
from src.strategy_engine.signal_generator import SignalGenerator
from src.strategy_engine.strike_selector import (
    LiquidityFilterConfig,
    StrikeSelector,
)


# =============================================================================
# Fixtures & Mock Data Generators
# =============================================================================

def build_mock_option_chain(
    underlying: UnderlyingIndex = UnderlyingIndex.NIFTY,
    spot_price: float = 24000.0,
    dte_days: float = 7.0,
    iv: float = 0.15,
    expiry: str = "2026-08-27",
    num_strikes_each_side: int = 25,
) -> OptionChainSnapshot:
    """Helper to generate a realistic mock option chain with accurate Black-Scholes Greeks."""
    step = underlying.strike_step
    atm_strike = round(spot_price / step) * step
    dte_years = dte_days / 365.0

    strikes: list[OptionStrikeData] = []

    for i in range(-num_strikes_each_side, num_strikes_each_side + 1):
        strike = atm_strike + (i * step)

        # Call Option
        ce_price = black_scholes_price(spot_price, strike, dte_years, iv, option_type=OptionType.CE)
        ce_greeks = calculate_greeks(spot_price, strike, dte_years, iv, option_type=OptionType.CE)
        strikes.append(
            OptionStrikeData(
                strike=strike,
                option_type=OptionType.CE,
                ltp=max(0.50, round(ce_price, 2)),
                bid=max(0.40, round(ce_price * 0.99, 2)),
                ask=max(0.60, round(ce_price * 1.01, 2)),
                open_interest=50000 + max(0, 100000 - abs(i) * 3000),
                volume=10000 + max(0, 20000 - abs(i) * 500),
                iv=iv,
                greeks=ce_greeks,
                expiry=expiry,
            )
        )

        # Put Option
        pe_price = black_scholes_price(spot_price, strike, dte_years, iv, option_type=OptionType.PE)
        pe_greeks = calculate_greeks(spot_price, strike, dte_years, iv, option_type=OptionType.PE)
        strikes.append(
            OptionStrikeData(
                strike=strike,
                option_type=OptionType.PE,
                ltp=max(0.50, round(pe_price, 2)),
                bid=max(0.40, round(pe_price * 0.99, 2)),
                ask=max(0.60, round(pe_price * 1.01, 2)),
                open_interest=45000 + max(0, 95000 - abs(i) * 3000),
                volume=9000 + max(0, 19000 - abs(i) * 500),
                iv=iv,
                greeks=pe_greeks,
                expiry=expiry,
            )
        )

    return OptionChainSnapshot(
        underlying=underlying,
        spot_price=spot_price,
        expiry=expiry,
        strikes=strikes,
    )



# =============================================================================
# 1. Models & Schemas Test Suite
# =============================================================================

class TestModels:
    def test_underlying_index_properties(self):
        assert UnderlyingIndex.NIFTY.strike_step == 50.0
        assert UnderlyingIndex.BANKNIFTY.strike_step == 100.0
        assert UnderlyingIndex.SENSEX.strike_step == 100.0
        assert UnderlyingIndex.NIFTY.default_lot_size == 25

    def test_option_strike_data_spread_metrics(self):
        strike_data = OptionStrikeData(
            strike=24000.0,
            option_type=OptionType.CE,
            ltp=100.0,
            bid=98.0,
            ask=102.0,
            open_interest=5000,
            volume=500,
            iv=0.15,
            expiry="2026-08-27",
        )
        assert strike_data.bid_ask_spread == 4.0
        assert pytest.approx(strike_data.spread_percentage, 0.001) == 0.04

    def test_option_chain_snapshot_auto_computations(self):
        chain = build_mock_option_chain(spot_price=24035.0)
        assert chain.atm_strike == 24050.0  # Rounds to nearest 50
        assert chain.pcr is not None
        assert chain.pcr > 0.0

    def test_position_state_recalculate_greeks(self):
        greeks_ce = Greeks(delta=0.50, gamma=0.001, theta=-10.0, vega=15.0, rho=0.5, iv=0.15)
        greeks_pe = Greeks(delta=-0.50, gamma=0.001, theta=-10.0, vega=15.0, rho=-0.5, iv=0.15)

        leg1 = OptionLeg(
            symbol="NIFTY_CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=25,
            entry_price=100,
            current_price=100,
            greeks=greeks_ce,
        )
        leg2 = OptionLeg(
            symbol="NIFTY_PE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.PE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=25,
            entry_price=100,
            current_price=100,
            greeks=greeks_pe,
        )

        pos = PositionState(
            strategy_type=StrategyType.SHORT_STRANGLE,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.LOW_IV_RANGING,
            legs=[leg1, leg2],
        )
        pos.recalculate_greeks()

        # Net Delta: (-1 * 25 * 0.50) + (-1 * 25 * -0.50) = -12.5 + 12.5 = 0.0
        assert pos.net_delta == 0.0
        assert pos.net_theta == 500.0  # Sold legs collect positive theta: -(-10)*25*2 = +500


# =============================================================================
# 2. Black-Scholes & Greeks Engine Test Suite
# =============================================================================

class TestBlackScholesEngine:
    def test_call_put_parity_and_atm_pricing(self):
        spot = 24000.0
        strike = 24000.0
        dte_years = 7.0 / 365.0
        vol = 0.15
        r = 0.065

        call_px = black_scholes_price(spot, strike, dte_years, vol, r, OptionType.CE)
        put_px = black_scholes_price(spot, strike, dte_years, vol, r, OptionType.PE)

        assert call_px > 0
        assert put_px > 0
        # Call > Put for ATM due to positive interest rate drift
        assert call_px > put_px

    def test_greeks_delta_bounds_and_direction(self):
        spot = 24000.0
        dte_years = 10.0 / 365.0
        vol = 0.16

        # ATM Call
        ce_greeks = calculate_greeks(spot, 24000.0, dte_years, vol, option_type=OptionType.CE)
        assert 0.45 <= ce_greeks.delta <= 0.60
        assert ce_greeks.gamma > 0
        assert ce_greeks.theta < 0  # Daily decay is negative for long
        assert ce_greeks.vega > 0

        # ATM Put
        pe_greeks = calculate_greeks(spot, 24000.0, dte_years, vol, option_type=OptionType.PE)
        assert -0.60 <= pe_greeks.delta <= -0.40
        assert pe_greeks.gamma > 0
        assert pe_greeks.theta < 0

        # Deep OTM Call (Delta -> 0)
        deep_otm_ce = calculate_greeks(spot, 26000.0, dte_years, vol, option_type=OptionType.CE)
        assert 0.0 <= deep_otm_ce.delta <= 0.05

        # Deep ITM Call (Delta -> 1)
        deep_itm_ce = calculate_greeks(spot, 22000.0, dte_years, vol, option_type=OptionType.CE)
        assert 0.95 <= deep_itm_ce.delta <= 1.0

    def test_implied_volatility_solver_accuracy(self):
        spot = 24000.0
        strike = 24100.0
        dte_years = 14.0 / 365.0
        target_vol = 0.185

        # Generate price with known vol
        price = black_scholes_price(spot, strike, dte_years, target_vol, option_type=OptionType.CE)

        # Solve IV back
        recovered_iv = implied_volatility(price, spot, strike, dte_years, option_type=OptionType.CE)
        assert pytest.approx(recovered_iv, abs=0.005) == target_vol


# =============================================================================
# 3. Regime Detector Test Suite
# =============================================================================

class TestRegimeDetector:
    def setup_method(self):
        self.detector = RegimeDetector()

    def test_volatility_expansion_classification(self):
        ind = MarketIndicators(
            spot_ltp=24000.0,
            atr=150.0,
            adx=22.0,
            india_vix=21.5,  # Extreme VIX
            pcr=0.95,
            vix_change_pct=7.5,  # VIX spike > 5%
        )
        regime = self.detector.classify(ind)
        assert regime.regime == MarketRegime.VOLATILITY_EXPANSION
        assert StrategyType.CALENDAR_SPREAD in regime.recommended_strategies

    def test_high_iv_trending_classification(self):
        ind = MarketIndicators(
            spot_ltp=24200.0,
            atr=180.0,
            adx=31.0,  # Strong trend
            india_vix=17.5,  # High VIX
            pcr=1.35,  # Bullish PCR
            short_term_trend=TrendDirection.BULLISH,
        )
        regime = self.detector.classify(ind)
        assert regime.regime == MarketRegime.HIGH_IV_TRENDING
        assert regime.trend == TrendDirection.BULLISH
        assert StrategyType.BULL_CALL_SPREAD in regime.recommended_strategies

    def test_low_iv_ranging_classification(self):
        ind = MarketIndicators(
            spot_ltp=24000.0,
            atr=90.0,
            adx=14.0,  # Low ADX / Chop
            india_vix=12.8,  # Subdued VIX
            pcr=1.02,
        )
        regime = self.detector.classify(ind)
        assert regime.regime == MarketRegime.LOW_IV_RANGING
        assert regime.trend == TrendDirection.NEUTRAL
        assert StrategyType.IRON_CONDOR in regime.recommended_strategies
        assert StrategyType.HEDGED_STRADDLE in regime.recommended_strategies

    def test_mean_reverting_classification(self):
        ind = MarketIndicators(
            spot_ltp=24000.0,
            atr=110.0,
            adx=16.0,  # Exhausted trend
            india_vix=14.0,
            pcr=1.45,  # Extreme oversold Put heavy
        )
        regime = self.detector.classify(ind)
        assert regime.regime == MarketRegime.MEAN_REVERTING
        assert regime.trend == TrendDirection.BULLISH
        assert StrategyType.IRON_CONDOR in regime.recommended_strategies


# =============================================================================
# 4. Strike Selector Test Suite
# =============================================================================

class TestStrikeSelector:
    def setup_method(self):
        self.selector = StrikeSelector()
        self.chain = build_mock_option_chain(spot_price=24000.0, iv=0.15)

    def test_find_atm_strike(self):
        atm_ce = self.selector.find_atm_strike(self.chain, OptionType.CE)
        assert atm_ce.strike == 24000.0
        assert atm_ce.option_type == OptionType.CE

    def test_find_strike_by_delta(self):
        # Find ~0.20 delta OTM Call
        short_ce = self.selector.find_strike_by_delta(self.chain, target_delta=0.20, option_type=OptionType.CE)
        assert short_ce.strike > 24000.0
        assert short_ce.greeks is not None
        assert pytest.approx(short_ce.greeks.delta, abs=0.06) == 0.20

        # Find ~0.20 delta OTM Put
        short_pe = self.selector.find_strike_by_delta(self.chain, target_delta=0.20, option_type=OptionType.PE)
        assert short_pe.strike < 24000.0
        assert short_pe.greeks is not None
        assert pytest.approx(abs(short_pe.greeks.delta), abs=0.06) == 0.20

    def test_select_iron_condor_strikes(self):
        short_ce, long_ce, short_pe, long_pe = self.selector.select_iron_condor_strikes(
            self.chain,
            short_ce_delta=0.20,
            short_pe_delta=0.20,
            wing_width_points=200.0,
        )

        # Ordering assertions: Long PE < Short PE < Spot(24000) < Short CE < Long CE
        assert long_pe.strike < short_pe.strike < 24000.0 < short_ce.strike < long_ce.strike
        assert abs(long_ce.strike - short_ce.strike) == 200.0
        assert abs(short_pe.strike - long_pe.strike) == 200.0

    def test_select_hedged_straddle_strikes(self):
        atm_ce, atm_pe, wing_ce, wing_pe = self.selector.select_hedged_straddle_strikes(
            self.chain,
            wing_distance_points=300.0,
        )
        assert atm_ce.strike == 24000.0
        assert atm_pe.strike == 24000.0
        assert wing_ce.strike == 24300.0
        assert wing_pe.strike == 23700.0

    def test_liquidity_filter_rejection(self):
        # Create chain with an illiquid strike
        chain_illiquid = build_mock_option_chain(spot_price=24000.0)
        for s in chain_illiquid.strikes:
            if s.strike == 24200.0 and s.option_type == OptionType.CE:
                s.open_interest = 10  # Below 1000 threshold
                s.volume = 5

        selector_strict = StrikeSelector(LiquidityFilterConfig(min_open_interest=1000, enforce_liquidity=True))
        selected = selector_strict.find_strike_by_delta(chain_illiquid, target_delta=0.30, option_type=OptionType.CE)
        assert selected.strike != 24200.0  # Must not pick the illiquid strike


# =============================================================================
# 5. Signal Generator Test Suite
# =============================================================================

class TestSignalGenerator:
    def setup_method(self):
        self.generator = SignalGenerator()
        self.chain = build_mock_option_chain(spot_price=24000.0)

    def test_generate_iron_condor_signal(self):
        regime = RegimeClassification(
            regime=MarketRegime.LOW_IV_RANGING,
            trend=TrendDirection.NEUTRAL,
            confidence=0.85,
            description="Low IV chop",
        )
        signal = self.generator.generate_entry_signal(StrategyType.IRON_CONDOR, self.chain, regime, quantity_lots=2)

        assert signal is not None
        assert signal.strategy_type == StrategyType.IRON_CONDOR
        assert signal.signal_type == SignalType.ENTRY
        assert len(signal.legs) == 4
        assert signal.entry_credit_debit > 0  # Net credit
        assert signal.max_profit is not None and signal.max_profit > 0
        assert signal.max_loss is not None and signal.max_loss > 0
        assert signal.stop_loss_threshold is not None and signal.stop_loss_threshold < 0

    def test_generate_bull_call_spread_signal(self):
        regime = RegimeClassification(
            regime=MarketRegime.HIGH_IV_TRENDING,
            trend=TrendDirection.BULLISH,
            confidence=0.80,
            description="High IV breakout",
        )
        signal = self.generator.generate_entry_signal(StrategyType.BULL_CALL_SPREAD, self.chain, regime, quantity_lots=1)

        assert signal is not None
        assert signal.strategy_type == StrategyType.BULL_CALL_SPREAD
        assert len(signal.legs) == 2
        assert signal.entry_credit_debit < 0  # Net debit
        assert signal.legs[0].action == OrderAction.BUY  # Buy ATM
        assert signal.legs[1].action == OrderAction.SELL # Sell OTM

    def test_exit_signal_evaluation(self):
        # Create active position
        leg = OptionLeg(
            symbol="NIFTY_24000_CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=25,
            entry_price=100.0,
            current_price=150.0,
        )
        pos = PositionState(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.HIGH_IV_TRENDING,
            legs=[leg],
        )

        # 1. Target Hit
        target_signal = self.generator.evaluate_exit_signals(
            pos, self.chain, current_pnl=1250.0, target_pnl_threshold=1000.0
        )
        assert target_signal.signal_type == SignalType.TARGET

        # 2. Stop Loss Hit
        sl_signal = self.generator.evaluate_exit_signals(
            pos, self.chain, current_pnl=-600.0, stop_loss_pnl_threshold=-500.0
        )
        assert sl_signal.signal_type == SignalType.STOP_LOSS

        # 3. Hostile Regime Shift on Iron Condor
        ic_pos = PositionState(
            strategy_type=StrategyType.IRON_CONDOR,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.LOW_IV_RANGING,
            legs=[leg],
        )
        shift_signal = self.generator.evaluate_exit_signals(
            ic_pos, self.chain, current_pnl=50.0, current_regime=MarketRegime.VOLATILITY_EXPANSION
        )
        assert shift_signal.signal_type == SignalType.EXIT


# =============================================================================
# 6. Dynamic Hedge Manager Test Suite
# =============================================================================

class TestHedgeManager:
    def setup_method(self):
        self.hedge_mgr = HedgeManager(HedgeManagerConfig(max_net_delta_abs=10.0))
        self.chain = build_mock_option_chain(spot_price=24000.0)

    def test_roll_untested_put_side_on_call_rally(self):
        """When market rallies, Short CE delta rises and Short PE delta decays. Should roll PE up."""
        short_ce = OptionLeg(
            symbol="NIFTY_CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24200,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=25,
            entry_price=80,
            current_price=140,
        )
        short_pe = OptionLeg(
            symbol="NIFTY_PE",
            underlying=UnderlyingIndex.NIFTY,
            strike=23600,
            option_type=OptionType.PE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=25,
            entry_price=80,
            current_price=10,
        )

        pos = PositionState(
            strategy_type=StrategyType.IRON_CONDOR,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.LOW_IV_RANGING,
            legs=[short_ce, short_pe],
        )

        # Market rallies to 24200 (CE is now ATM / tested)
        chain_rallied = build_mock_option_chain(spot_price=24200.0)
        hedge_signal = self.hedge_mgr.evaluate_hedge_requirement(pos, chain_rallied)

        assert hedge_signal.hedge_action == HedgeActionType.ROLL_UNTESTED_SIDE
        assert hedge_signal.imbalance_type == "TESTED_CALL_SIDE_PRESSURE"
        assert len(hedge_signal.legs_to_close) >= 1
        assert hedge_signal.legs_to_close[0].strike == 23600  # Closes old Put strike
        assert hedge_signal.legs_to_open[0].strike > 23600   # Rolls up to higher Put strike


    def test_delta_neutralize_breach(self):
        """When net delta breaches threshold without tested leg condition, hedge manager neutralizes delta."""
        leg = OptionLeg(
            symbol="NIFTY_CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.BUY,
            quantity=50,  # 2 lots
            greeks=Greeks(delta=0.50, gamma=0.001, theta=-10, vega=15, iv=0.15),
        )
        pos = PositionState(
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.HIGH_IV_TRENDING,
            legs=[leg],
        )
        pos.recalculate_greeks()
        # pos.net_delta = +25.0 (exceeds cap of 10.0)

        hedge_signal = self.hedge_mgr.evaluate_hedge_requirement(pos, self.chain)
        assert hedge_signal.hedge_action == HedgeActionType.DELTA_NEUTRALIZE
        assert len(hedge_signal.legs_to_open) >= 1
        assert hedge_signal.legs_to_open[0].option_type == OptionType.PE  # Buys PE to neutralize long delta

    def test_gamma_spike_wing_protection(self):
        """When net short gamma spikes, hedge manager buys wings."""
        short_ce = OptionLeg(
            symbol="NIFTY_CE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.CE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=100,
            greeks=Greeks(delta=0.50, gamma=0.003, theta=-20, vega=25, iv=0.25),
        )
        short_pe = OptionLeg(
            symbol="NIFTY_PE",
            underlying=UnderlyingIndex.NIFTY,
            strike=24000,
            option_type=OptionType.PE,
            expiry="2026-08-27",
            action=OrderAction.SELL,
            quantity=100,
            greeks=Greeks(delta=-0.50, gamma=0.003, theta=-20, vega=25, iv=0.25),
        )
        pos = PositionState(
            strategy_type=StrategyType.SHORT_STRANGLE,
            underlying=UnderlyingIndex.NIFTY,
            entry_regime=MarketRegime.LOW_IV_RANGING,
            legs=[short_ce, short_pe],
        )

        hedge_signal = self.hedge_mgr.evaluate_hedge_requirement(pos, self.chain)
        assert hedge_signal.hedge_action == HedgeActionType.ADD_WING_PROTECTION
        assert len(hedge_signal.legs_to_open) == 2  # CE and PE wings


# =============================================================================
# 7. End-to-End Strategy Lifecycle Integration Test
# =============================================================================

class TestEndToEndStrategyLifecycle:
    def test_complete_iron_condor_lifecycle(self):
        """Simulate entry -> market drift -> dynamic hedge roll -> target exit."""
        # 1. Detect Regime (Low IV Ranging)
        detector = RegimeDetector()
        ind = MarketIndicators(spot_ltp=24000.0, atr=95.0, adx=15.0, india_vix=13.0, pcr=1.05)
        regime = detector.classify(ind)
        assert regime.regime == MarketRegime.LOW_IV_RANGING

        # 2. Generate Entry Signal (Iron Condor)
        chain_t0 = build_mock_option_chain(spot_price=24000.0)
        signal_gen = SignalGenerator()
        entry_sig = signal_gen.generate_entry_signal(StrategyType.IRON_CONDOR, chain_t0, regime, quantity_lots=1)
        assert entry_sig is not None

        # 3. Create Position
        pos = PositionState(
            strategy_type=entry_sig.strategy_type,
            underlying=entry_sig.underlying,
            entry_regime=entry_sig.regime,
            legs=entry_sig.legs,
        )
        pos.recalculate_greeks()
        assert abs(pos.net_delta) < 5.0

        # 4. Market rallies by 250 points to 24250 (Call side pressure)
        chain_t1 = build_mock_option_chain(spot_price=24250.0)
        hedge_mgr = HedgeManager()
        hedge_sig = hedge_mgr.evaluate_hedge_requirement(pos, chain_t1)

        # Hedge Manager should detect tested Call side pressure or delta breach and prescribe roll
        assert hedge_sig.hedge_action in (HedgeActionType.ROLL_UNTESTED_SIDE, HedgeActionType.DELTA_NEUTRALIZE)

        # 5. Position reaches 60% profit target
        exit_sig = signal_gen.evaluate_exit_signals(
            pos,
            chain_t1,
            current_pnl=entry_sig.target_threshold + 50.0,
            target_pnl_threshold=entry_sig.target_threshold,
        )
        assert exit_sig.signal_type == SignalType.TARGET

