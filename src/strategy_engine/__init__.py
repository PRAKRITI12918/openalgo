"""
Decision & Strategy Logic Engine (Phase 1) for Automated Indian Index Options.
Exposes core models, regime detector, strike selector, signal generator, and dynamic hedge manager.
"""

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
    HedgeAdjustmentSignal,
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
from src.strategy_engine.signal_generator import (
    SignalGenerator,
)
from src.strategy_engine.strike_selector import (
    LiquidityFilterConfig,
    StrikeSelector,
)

__all__ = [
    # Models & Enums
    "MarketRegime",
    "TrendDirection",
    "StrategyType",
    "OptionType",
    "OrderAction",
    "SignalType",
    "UnderlyingIndex",
    "ExpiryType",
    "HedgeActionType",
    "Greeks",
    "OptionStrikeData",
    "OptionChainSnapshot",
    "MarketIndicators",
    "RegimeClassification",
    "OptionLeg",
    "TradeSignal",
    "PositionState",
    "HedgeAdjustmentSignal",
    # Greeks
    "black_scholes_price",
    "calculate_greeks",
    "implied_volatility",
    # Modules & Configs
    "RegimeDetector",
    "RegimeDetectorConfig",
    "StrikeSelector",
    "LiquidityFilterConfig",
    "SignalGenerator",
    "HedgeManager",
    "HedgeManagerConfig",
]
