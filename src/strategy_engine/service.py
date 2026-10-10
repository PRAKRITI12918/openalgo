"""
Strategy Engine Service Layer.
Encapsulates strategy cataloging, definition resolution, and execution metadata
away from REST/WebSocket route handlers (Separation of Concerns).
"""

from __future__ import annotations

from typing import List

from src.models.schemas import StrategyDefinitionModel, StrategyListResponse
from src.strategy_engine.models import MarketRegime, StrategyType


_STRATEGY_CATALOG: List[StrategyDefinitionModel] = [
    StrategyDefinitionModel(
        strategy_type=StrategyType.IRON_CONDOR,
        name="Iron Condor",
        description="4-leg defined-risk neutral options strategy combining an OTM Bear Call Spread and an OTM Bull Put Spread to capture premium in range-bound conditions.",
        legs_count=4,
        favorable_regimes=[MarketRegime.LOW_IV_RANGING, MarketRegime.MEAN_REVERTING],
        risk_profile="Defined Risk (Max Loss = Wing Width - Net Credit)",
        directionality="NEUTRAL",
        default_product="MIS",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.HEDGED_STRADDLE,
        name="Hedged Straddle (Iron Butterfly)",
        description="4-leg neutral options structure selling ATM Call and Put while buying protective outer wings for strict margin relief and gap safety.",
        legs_count=4,
        favorable_regimes=[MarketRegime.LOW_IV_RANGING, MarketRegime.MEAN_REVERTING],
        risk_profile="Defined Risk (Max Loss = Wing Width - Net Credit)",
        directionality="NEUTRAL",
        default_product="MIS",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.BULL_CALL_SPREAD,
        name="Bull Call Spread",
        description="2-leg vertical spread buying an ATM/near-OTM call and selling a higher strike OTM call with identical expiration for directional upside.",
        legs_count=2,
        favorable_regimes=[MarketRegime.HIGH_IV_TRENDING, MarketRegime.VOLATILITY_EXPANSION],
        risk_profile="Defined Risk (Max Loss = Net Debit Paid)",
        directionality="BULLISH",
        default_product="MIS",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.BEAR_PUT_SPREAD,
        name="Bear Put Spread",
        description="2-leg vertical spread buying an ATM/near-OTM put and selling a lower strike OTM put with identical expiration for directional downside.",
        legs_count=2,
        favorable_regimes=[MarketRegime.HIGH_IV_TRENDING, MarketRegime.VOLATILITY_EXPANSION],
        risk_profile="Defined Risk (Max Loss = Net Debit Paid)",
        directionality="BEARISH",
        default_product="MIS",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.CALENDAR_SPREAD,
        name="Calendar Time Spread",
        description="Horizontal time spread selling near-term expiration options and buying longer-dated options at identical strikes to harvest differential theta decay.",
        legs_count=2,
        favorable_regimes=[MarketRegime.LOW_IV_RANGING],
        risk_profile="Defined Risk (Net Debit Paid)",
        directionality="NEUTRAL",
        default_product="NRML",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.RATIO_SPREAD,
        name="1x2 Ratio Spread",
        description="Asymmetric multi-leg spread buying 1 ATM option and selling 2 further OTM options to finance the long wing with minimal debit or net credit.",
        legs_count=3,
        favorable_regimes=[MarketRegime.MEAN_REVERTING],
        risk_profile="Partially Undefined Risk beyond short strikes",
        directionality="NEUTRAL",
        default_product="MIS",
    ),
    StrategyDefinitionModel(
        strategy_type=StrategyType.SHORT_STRANGLE,
        name="Short Strangle",
        description="Volatility harvesting structure selling out-of-the-money Call and Put outside 1-sigma expected move, with active delta hedge monitoring.",
        legs_count=2,
        favorable_regimes=[MarketRegime.HIGH_IV_TRENDING, MarketRegime.MEAN_REVERTING],
        risk_profile="Undefined Risk (monitored by hedge manager)",
        directionality="NEUTRAL",
        default_product="MIS",
    ),
]


def get_supported_strategies() -> StrategyListResponse:
    """
    Retrieve the catalog of supported quantitative options strategies.
    Separates domain business logic from HTTP controller routing.
    """
    return StrategyListResponse(
        success=True,
        count=len(_STRATEGY_CATALOG),
        strategies=_STRATEGY_CATALOG,
    )
