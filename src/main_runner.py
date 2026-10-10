"""
HedgedAOS Live Trading Engine Master Runner (Phase 1 + Phase 2).
Connects Market Feed -> Regime Detector -> Strike Selector -> Signal Generator -> Order Router -> Position Tracker -> Hedge Manager.
"""

import asyncio
import logging
import signal
import sys
from typing import Dict, List, Optional

from src.adapters.factory import create_broker_adapter
from src.broker_pipeline.config import PipelineConfig
from src.broker_pipeline.market_feed import MarketDataFeed
from src.broker_pipeline.order_router import OrderRouter
from src.broker_pipeline.position_tracker import PositionTracker
from src.core.config import ExecutionConfig
from src.strategy_engine.hedge_manager import HedgeManager
from src.strategy_engine.models import (
    MarketRegime,
    OptionChainSnapshot,
    PositionState,
    RegimeClassification,
    SignalType,
    StrategyType,
    TradeSignal,
    UnderlyingIndex,
)
from src.strategy_engine.regime_detector import RegimeDetector
from src.strategy_engine.signal_generator import SignalGenerator
from src.strategy_engine.strike_selector import StrikeSelector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
)
logger = logging.getLogger("main_runner")


class StrategyExecutionEngine:
    """
    Master trading engine managing the complete automated options trading lifecycle.
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        target_indices: Optional[List[UnderlyingIndex]] = None,
    ):
        self.config = config or PipelineConfig()
        self.target_indices = target_indices or [UnderlyingIndex.NIFTY]

        # Pipeline components - instantiated strictly behind the mode-selection factory
        mode = getattr(self.config, "trading_mode", "SANDBOX")
        exec_cfg = ExecutionConfig(
            openalgo_host=self.config.openalgo_host,
            openalgo_api_key=self.config.openalgo_api_key or "pipeline_runner_key",
            strategy_tag=self.config.strategy_tag,
            live_trading_enabled=(mode == "LIVE"),
        )
        adapter = create_broker_adapter(mode=mode, config=exec_cfg)
        self.client = getattr(adapter, "client", None)
        self.regime_detector = RegimeDetector()
        self.strike_selector = StrikeSelector()
        self.signal_generator = SignalGenerator(strike_selector=self.strike_selector)
        self.hedge_manager = HedgeManager(strike_selector=self.strike_selector)

        self.market_feed = MarketDataFeed(client=self.client, regime_detector=self.regime_detector)
        self.order_router = OrderRouter(client=self.client, enforce_margin_safety=self.config.enforce_margin_safety_sequence)
        self.position_tracker = PositionTracker(client=self.client, hedge_manager=self.hedge_manager)

        self._running = False
        self._active_strategy_signals: Dict[str, TradeSignal] = {}

    async def initialize(self) -> bool:
        """Verify API connectivity, broker session, and available funds."""
        logger.info("Initializing HedgedAOS Strategy Execution Engine...")
        await self.client.start()

        # 1. Ping OpenAlgo server
        is_alive = await self.client.ping()
        if not is_alive:
            logger.warning(f"Unable to ping OpenAlgo at {self.config.openalgo_host}. Will proceed and retry.")
        else:
            logger.info(f"Connected to OpenAlgo at {self.config.openalgo_host}")

        # 2. Check funds
        funds = await self.position_tracker.sync_funds()
        logger.info(f"Broker Funds Synced: {funds}")

        return True

    async def run_cycle(self) -> None:
        """Execute one complete evaluation and execution cycle across target indices."""
        for underlying in self.target_indices:
            try:
                # 1. Fetch Market Data & Classify Regime
                chain, regime = await self.market_feed.get_latest_market_state(underlying)
                logger.info(f"[{underlying.value}] Spot: {chain.spot_price:.2f} | Regime: {regime.regime.value} ({regime.confidence*100:.0f}%) | PCR: {chain.pcr:.2f}")

                # 2. Sync Live Positions & Aggregate Greeks
                positions = await self.position_tracker.sync_positions(chain_snapshots={underlying: chain})

                # 3. Dynamic Risk & Hedge Adjustment Checks
                hedge_adjustments = self.position_tracker.evaluate_hedges({underlying: chain})
                for pos, hedge_sig in hedge_adjustments:
                    logger.warning(f"Executing Hedge: {hedge_sig.hedge_action.value} on position {pos.position_id}")
                    report = await self.order_router.route_hedge_adjustment(hedge_sig)
                    logger.info(f"Hedge execution status: {report.status}")

                # 4. Exit Signal Evaluation on Active Positions
                for pos in positions:
                    exit_signal = self.signal_generator.evaluate_exit_signals(pos, chain)
                    if exit_signal.signal_type != SignalType.NONE:
                        logger.info(f"Triggering Exit: {exit_signal.signal_type.value} for {pos.strategy_type.value} [{pos.position_id}]")
                        report = await self.order_router.route_exit_signal(exit_signal)
                        logger.info(f"Exit execution report: {report.status}")

                # 5. Entry Signal Generation (if capacity permits and no open conflicting positions)
                if not positions:
                    recommended_strats = regime.recommended_strategies
                    if recommended_strats:
                        target_strat = recommended_strats[0]
                        logger.info(f"Evaluating Entry for recommended strategy: {target_strat.value}")
                        entry_signal = self.signal_generator.generate_entry_signal(
                            strategy_type=target_strat,
                            chain=chain,
                            regime=regime,
                            quantity_lots=1,
                        )
                        if entry_signal and entry_signal.legs:
                            logger.info(f"Generated Entry Signal for {entry_signal.strategy_type.value} with {len(entry_signal.legs)} legs. Routing orders...")
                            report = await self.order_router.route_entry_signal(entry_signal)
                            logger.info(f"Entry Execution Result: {report.status} ({report.filled_legs}/{report.total_legs} legs filled)")
                            if report.status == "FULLY_FILLED":
                                self._active_strategy_signals[entry_signal.signal_id] = entry_signal

            except Exception as e:
                logger.error(f"Error during cycle for {underlying.value}: {e}", exc_info=True)

    async def start(self) -> None:
        """Start the continuous event loop."""
        await self.initialize()
        self._running = True
        logger.info(f"Trading Engine Event Loop started (poll interval: {self.config.feed_poll_interval_seconds}s)")

        while self._running:
            await self.run_cycle()
            await asyncio.sleep(self.config.feed_poll_interval_seconds)

    async def stop(self) -> None:
        """Gracefully stop the engine and close connections."""
        logger.info("Stopping Strategy Execution Engine...")
        self._running = False
        self.market_feed.stop_streaming()
        await self.client.close()
        logger.info("Strategy Execution Engine stopped successfully.")


async def main():
    engine = StrategyExecutionEngine()

    def handle_signal():
        logger.info("Received termination signal.")
        asyncio.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            pass  # Windows signal handler fallback

    try:
        await engine.start()
    except (asyncio.CancelledError, KeyboardInterrupt):
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
