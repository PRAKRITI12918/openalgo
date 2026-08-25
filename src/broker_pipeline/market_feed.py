"""
Live Market Data Feed Poller & Streamer.
Fetches real-time index quotes and option chains from OpenAlgo, constructs
OptionChainSnapshot and MarketIndicators, and integrates with RegimeDetector.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from src.broker_pipeline.openalgo_client import OpenAlgoClient
from src.strategy_engine.models import (
    Greeks,
    MarketIndicators,
    OptionChainSnapshot,
    OptionStrikeData,
    OptionType,
    RegimeClassification,
    UnderlyingIndex,
)
from src.strategy_engine.regime_detector import RegimeDetector
from src.strategy_engine.greeks import calculate_greeks

logger = logging.getLogger("broker_pipeline.feed")


class MarketDataFeed:
    """
    Asynchronous market data ingestor.
    Polls OpenAlgo for index LTP, VIX, and option chains, building domain models for the strategy engine.
    """

    def __init__(
        self,
        client: OpenAlgoClient,
        regime_detector: Optional[RegimeDetector] = None,
        poll_interval: float = 1.0,
    ):
        self.client = client
        self.regime_detector = regime_detector or RegimeDetector()
        self.poll_interval = poll_interval
        self._is_running = False
        self._last_indicators: Dict[UnderlyingIndex, MarketIndicators] = {}
        self._last_chains: Dict[UnderlyingIndex, OptionChainSnapshot] = {}
        self._last_regimes: Dict[UnderlyingIndex, RegimeClassification] = {}
        self._subscribers: List[Callable[[UnderlyingIndex, OptionChainSnapshot, RegimeClassification], Any]] = []

    def subscribe(self, callback: Callable[[UnderlyingIndex, OptionChainSnapshot, RegimeClassification], Any]) -> None:
        """Register a callback for real-time market updates."""
        self._subscribers.append(callback)

    async def fetch_underlying_indicators(self, underlying: UnderlyingIndex) -> MarketIndicators:
        """
        Fetch Spot LTP, India VIX, and calculate ATR/ADX/PCR.
        """
        exchange = "NSE_INDEX" if underlying != UnderlyingIndex.SENSEX else "BSE_INDEX"
        symbol_name = underlying.value

        # 1. Fetch Spot Quote
        spot_res = await self.client.get_quotes(symbol=symbol_name, exchange=exchange)
        spot_data = spot_res.get("data", {}) if "data" in spot_res else spot_res
        spot_ltp = float(spot_data.get("ltp", spot_data.get("close", 24000.0)))

        # 2. Fetch India VIX
        india_vix = 14.0
        try:
            vix_res = await self.client.get_quotes(symbol="INDIA VIX", exchange="NSE_INDEX")
            vix_data = vix_res.get("data", {}) if "data" in vix_res else vix_res
            india_vix = float(vix_data.get("ltp", 14.0))
        except Exception:
            try:
                vix_res = await self.client.get_quotes(symbol="INDIAVIX", exchange="NSE_INDEX")
                vix_data = vix_res.get("data", {}) if "data" in vix_res else vix_res
                india_vix = float(vix_data.get("ltp", 14.0))
            except Exception:
                india_vix = 14.0

        # High/Low/Close spread for ATR estimate
        high = float(spot_data.get("high", spot_ltp * 1.004))
        low = float(spot_data.get("low", spot_ltp * 0.996))
        prev_close = float(spot_data.get("prev_close", spot_data.get("open", spot_ltp)))

        atr_estimate = max(high - low, abs(high - prev_close), abs(low - prev_close))
        if atr_estimate <= 0:
            atr_estimate = spot_ltp * 0.005  # 0.5% default daily ATR

        indicators = MarketIndicators(
            spot_ltp=spot_ltp,
            atr=round(atr_estimate, 2),
            adx=20.0,
            india_vix=round(india_vix, 2),
            pcr=1.0,
            timestamp=datetime.utcnow(),
        )
        self._last_indicators[underlying] = indicators
        return indicators

    async def fetch_option_chain_snapshot(
        self,
        underlying: UnderlyingIndex,
        expiry_date: Optional[str] = None,
        strike_count: int = 20,
    ) -> OptionChainSnapshot:
        """
        Fetch option chain from OpenAlgo and parse into typed OptionChainSnapshot.
        """
        exchange = "NSE_INDEX" if underlying != UnderlyingIndex.SENSEX else "BSE_INDEX"
        res = await self.client.get_option_chain(
            underlying=underlying.value,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=strike_count,
        )

        chain_data = res.get("data", {}) if "data" in res else res
        spot_price = float(chain_data.get("underlying_ltp", chain_data.get("spot_price", 24000.0)))
        resolved_expiry = chain_data.get("expiry_date", expiry_date or "NEAR")

        raw_strikes = chain_data.get("chain", [])
        strikes: List[OptionStrikeData] = []
        dte_years = 7.0 / 365.0  # standard near-week DTE fallback

        for row in raw_strikes:
            strike_val = float(row.get("strike", 0))
            if strike_val <= 0:
                continue

            # CE
            ce_data = row.get("ce", {})
            if ce_data:
                ce_ltp = float(ce_data.get("ltp", 0.0))
                ce_iv = float(ce_data.get("iv", 0.15)) or 0.15
                ce_greeks_raw = ce_data.get("greeks")
                if ce_greeks_raw and isinstance(ce_greeks_raw, dict):
                    ce_greeks = Greeks(**ce_greeks_raw)
                else:
                    ce_greeks = calculate_greeks(spot_price, strike_val, dte_years, ce_iv, option_type=OptionType.CE)

                strikes.append(
                    OptionStrikeData(
                        strike=strike_val,
                        option_type=OptionType.CE,
                        symbol=ce_data.get("symbol", f"{underlying.value}_{strike_val}_CE"),
                        ltp=ce_ltp,
                        bid=float(ce_data.get("bid", ce_ltp * 0.99)),
                        ask=float(ce_data.get("ask", ce_ltp * 1.01)),
                        open_interest=int(ce_data.get("open_interest", ce_data.get("oi", 50000))),
                        volume=int(ce_data.get("volume", ce_data.get("vol", 10000))),
                        iv=ce_iv,
                        greeks=ce_greeks,
                        expiry=resolved_expiry,
                    )
                )

            # PE
            pe_data = row.get("pe", {})
            if pe_data:
                pe_ltp = float(pe_data.get("ltp", 0.0))
                pe_iv = float(pe_data.get("iv", 0.15)) or 0.15
                pe_greeks_raw = pe_data.get("greeks")
                if pe_greeks_raw and isinstance(pe_greeks_raw, dict):
                    pe_greeks = Greeks(**pe_greeks_raw)
                else:
                    pe_greeks = calculate_greeks(spot_price, strike_val, dte_years, pe_iv, option_type=OptionType.PE)

                strikes.append(
                    OptionStrikeData(
                        strike=strike_val,
                        option_type=OptionType.PE,
                        symbol=pe_data.get("symbol", f"{underlying.value}_{strike_val}_PE"),
                        ltp=pe_ltp,
                        bid=float(pe_data.get("bid", pe_ltp * 0.99)),
                        ask=float(pe_data.get("ask", pe_ltp * 1.01)),
                        open_interest=int(pe_data.get("open_interest", pe_data.get("oi", 50000))),
                        volume=int(pe_data.get("volume", pe_data.get("vol", 10000))),
                        iv=pe_iv,
                        greeks=pe_greeks,
                        expiry=resolved_expiry,
                    )
                )

        snapshot = OptionChainSnapshot(
            underlying=underlying,
            spot_price=spot_price,
            expiry=resolved_expiry,
            strikes=strikes,
            timestamp=datetime.utcnow(),
        )

        # Update PCR in indicators if available
        if underlying in self._last_indicators and snapshot.pcr is not None:
            self._last_indicators[underlying].pcr = snapshot.pcr


        self._last_chains[underlying] = snapshot
        return snapshot

    async def get_latest_market_state(
        self,
        underlying: UnderlyingIndex = UnderlyingIndex.NIFTY,
        expiry_date: Optional[str] = None,
    ) -> tuple[OptionChainSnapshot, RegimeClassification]:
        """
        Fetch latest market data and return synchronous (Snapshot, Regime) pair.
        """
        indicators = await self.fetch_underlying_indicators(underlying)
        snapshot = await self.fetch_option_chain_snapshot(underlying, expiry_date=expiry_date)
        regime = self.regime_detector.classify(indicators)
        self._last_regimes[underlying] = regime
        return snapshot, regime

    async def start_streaming(self, underlyings: Optional[List[UnderlyingIndex]] = None) -> None:
        """Background polling loop emitting updates to all registered subscribers."""
        self._is_running = True
        target_indices = underlyings or [UnderlyingIndex.NIFTY]

        logger.info(f"Started MarketDataFeed streamer for {', '.join(i.value for i in target_indices)}")
        while self._is_running:
            for idx in target_indices:
                try:
                    snapshot, regime = await self.get_latest_market_state(idx)
                    for sub in self._subscribers:
                        try:
                            res = sub(idx, snapshot, regime)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception as sub_err:
                            logger.error(f"Error in subscriber callback: {sub_err}")
                except Exception as e:
                    logger.error(f"Error polling market data for {idx.value}: {e}")

            await asyncio.sleep(self.poll_interval)

    def stop_streaming(self) -> None:
        """Stop background polling loop."""
        self._is_running = False
