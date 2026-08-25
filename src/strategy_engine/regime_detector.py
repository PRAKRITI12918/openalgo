"""
Rule-Based Market Regime Classifier.
Classifies index market conditions using Spot LTP, ATR, ADX, India VIX, and Put-Call Ratio (PCR).
Deterministic, transparent, and calibrated for Indian index options markets (NIFTY, BANKNIFTY, SENSEX).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.strategy_engine.models import (
    MarketIndicators,
    MarketRegime,
    RegimeClassification,
    StrategyType,
    TrendDirection,
)


@dataclass(frozen=True)
class RegimeDetectorConfig:
    """Configurable thresholds for regime classification."""
    # VIX Thresholds (India VIX)
    vix_low_threshold: float = 14.5        # Below this is considered low-IV / compression
    vix_high_threshold: float = 16.0       # Above this is elevated IV
    vix_extreme_threshold: float = 19.0    # Sharp volatility expansion
    vix_spike_pct_threshold: float = 5.0   # +5% 1-day VIX surge

    # ADX Trend Thresholds
    adx_ranging_max: float = 22.0          # Below 22 indicates sideways/ranging action
    adx_trending_min: float = 25.0         # Above 25 indicates strong directional momentum

    # Put-Call Ratio (PCR) Extremes
    pcr_oversold_threshold: float = 1.35   # Heavy Put writing (bullish mean reversion potential)
    pcr_overbought_threshold: float = 0.70 # Heavy Call writing (bearish mean reversion potential)
    pcr_balanced_min: float = 0.80
    pcr_balanced_max: float = 1.25


class RegimeDetector:
    """
    Deterministic rule-based market regime detector.
    Evaluates market indicators against quantitative thresholds to output an immutable RegimeClassification.
    """

    def __init__(self, config: Optional[RegimeDetectorConfig] = None):
        self.config = config or RegimeDetectorConfig()

    def classify(self, indicators: MarketIndicators) -> RegimeClassification:
        """
        Classify the market into one of four distinct regimes.

        1. VOLATILITY_EXPANSION: Sudden VIX surge or extreme high IV environment.
        2. HIGH_IV_TRENDING: Elevated VIX coupled with strong ADX directional momentum.
        3. LOW_IV_RANGING: Low VIX and weak ADX indicating rangebound theta-decay environment.
        4. MEAN_REVERTING: Extended prices with extreme PCR sentiment and non-trending ADX.
        """
        cfg = self.config
        vix = indicators.india_vix
        adx = indicators.adx
        pcr = indicators.pcr
        vix_change = indicators.vix_change_pct
        trend = self._determine_trend(indicators)

        # 1. Check for Volatility Expansion first (highest priority risk regime)
        if vix_change >= cfg.vix_spike_pct_threshold or vix >= cfg.vix_extreme_threshold:
            confidence = min(0.95, 0.70 + (vix_change / 20.0) * 0.15 + (vix / 30.0) * 0.10)
            desc = (
                f"Volatility Expansion detected: India VIX at {vix:.2f} ({vix_change:+.1f}%), "
                f"indicating risk-off or sharp gamma expansion."
            )
            recs = [StrategyType.CALENDAR_SPREAD]
            if trend == TrendDirection.BULLISH:
                recs.append(StrategyType.BULL_CALL_SPREAD)
            elif trend == TrendDirection.BEARISH:
                recs.append(StrategyType.BEAR_PUT_SPREAD)

            return RegimeClassification(
                regime=MarketRegime.VOLATILITY_EXPANSION,
                trend=trend,
                confidence=round(confidence, 2),
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )

        # 2. Check for High-IV Trending
        if vix >= cfg.vix_high_threshold and adx >= cfg.adx_trending_min:
            confidence = min(0.95, 0.70 + ((adx - cfg.adx_trending_min) / 30.0) * 0.25)
            desc = (
                f"High-IV Trending regime: Elevated VIX ({vix:.2f}) combined with strong directional "
                f"ADX ({adx:.1f}) and {trend.value} bias."
            )
            if trend == TrendDirection.BULLISH:
                recs = [StrategyType.BULL_CALL_SPREAD, StrategyType.RATIO_SPREAD]
            elif trend == TrendDirection.BEARISH:
                recs = [StrategyType.BEAR_PUT_SPREAD, StrategyType.RATIO_SPREAD]
            else:
                recs = [StrategyType.RATIO_SPREAD, StrategyType.IRON_CONDOR]

            return RegimeClassification(
                regime=MarketRegime.HIGH_IV_TRENDING,
                trend=trend,
                confidence=round(confidence, 2),
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )

        # 3. Check for Mean-Reverting (Extreme PCR or EMA divergence with weak trend strength)
        is_pcr_extreme = pcr >= cfg.pcr_oversold_threshold or pcr <= cfg.pcr_overbought_threshold
        is_adx_exhausted = adx < cfg.adx_trending_min

        if is_pcr_extreme and is_adx_exhausted:
            mean_revert_trend = TrendDirection.BULLISH if pcr >= cfg.pcr_oversold_threshold else TrendDirection.BEARISH
            confidence = 0.80 if vix < cfg.vix_high_threshold else 0.72
            desc = (
                f"Mean-Reverting regime: Sentiment extreme detected with PCR at {pcr:.2f} "
                f"and exhausted trend momentum ADX ({adx:.1f}). Expecting mean snap-back."
            )
            recs = [StrategyType.IRON_CONDOR, StrategyType.RATIO_SPREAD, StrategyType.HEDGED_STRADDLE]

            return RegimeClassification(
                regime=MarketRegime.MEAN_REVERTING,
                trend=mean_revert_trend,
                confidence=round(confidence, 2),
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )

        # 4. Check for Low-IV Ranging (Default theta harvest regime)
        if vix <= cfg.vix_high_threshold and adx <= cfg.adx_ranging_max:
            confidence = min(0.95, 0.75 + ((cfg.adx_ranging_max - adx) / cfg.adx_ranging_max) * 0.20)
            desc = (
                f"Low-IV Ranging regime: Subdued VIX ({vix:.2f}) and low directional ADX ({adx:.1f}). "
                f"Optimal environment for premium decay / non-directional strategies."
            )
            recs = [
                StrategyType.IRON_CONDOR,
                StrategyType.HEDGED_STRADDLE,
                StrategyType.SHORT_STRANGLE,
            ]

            return RegimeClassification(
                regime=MarketRegime.LOW_IV_RANGING,
                trend=TrendDirection.NEUTRAL,
                confidence=round(confidence, 2),
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )

        # 5. Boundary / Moderate conditions fallback: Classify by trend & volatility
        if adx >= cfg.adx_trending_min:
            desc = f"Moderate Trending regime (ADX {adx:.1f}, VIX {vix:.2f})."
            recs = [StrategyType.BULL_CALL_SPREAD if trend == TrendDirection.BULLISH else StrategyType.BEAR_PUT_SPREAD]
            return RegimeClassification(
                regime=MarketRegime.HIGH_IV_TRENDING,
                trend=trend,
                confidence=0.65,
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )
        else:
            desc = f"Consolidation / Rangebound regime (ADX {adx:.1f}, VIX {vix:.2f})."
            recs = [StrategyType.IRON_CONDOR, StrategyType.HEDGED_STRADDLE]
            return RegimeClassification(
                regime=MarketRegime.LOW_IV_RANGING,
                trend=TrendDirection.NEUTRAL,
                confidence=0.70,
                description=desc,
                recommended_strategies=recs,
                timestamp=indicators.timestamp,
            )

    def _determine_trend(self, ind: MarketIndicators) -> TrendDirection:
        """Evaluate directional bias from EMAs, PCR, and explicit trend hint."""
        if ind.short_term_trend != TrendDirection.NEUTRAL:
            return ind.short_term_trend

        # If EMAs are provided
        if ind.fast_ema is not None and ind.slow_ema is not None:
            if ind.fast_ema > ind.slow_ema and ind.pcr >= 0.95:
                return TrendDirection.BULLISH
            elif ind.fast_ema < ind.slow_ema and ind.pcr <= 1.05:
                return TrendDirection.BEARISH

        # Fallback to PCR sentiment
        if ind.pcr > 1.20:
            return TrendDirection.BULLISH
        elif ind.pcr < 0.80:
            return TrendDirection.BEARISH

        return TrendDirection.NEUTRAL
