"""
Comprehensive Pytest Suite for OpenAlgo Broker Pipeline (Phase 2).
Uses respx to mock OpenAlgo v1 REST API endpoints.
"""

import asyncio
import pytest
import respx
import httpx
from datetime import datetime

from src.broker_pipeline.config import PipelineConfig
from src.broker_pipeline.openalgo_client import (
    OpenAlgoAuthError,
    OpenAlgoClient,
    OpenAlgoNetworkError,
    OpenAlgoOrderRejectedError,
)
from src.broker_pipeline.market_feed import MarketDataFeed
from src.broker_pipeline.order_router import OrderRouter
from src.broker_pipeline.position_tracker import PositionTracker
from src.main_runner import StrategyExecutionEngine
from src.strategy_engine.models import (
    Greeks,
    HedgeActionType,
    HedgeAdjustmentSignal,
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


@pytest.fixture
def mock_config():
    return PipelineConfig(
        openalgo_host="http://127.0.0.1:5000",
        openalgo_api_key="test_api_key_123",
        strategy_tag="HedgedAOS_Test",
        request_timeout_seconds=2.0,
        max_retries=2,
        retry_backoff_seconds=0.01,
        enforce_margin_safety_sequence=True,
    )


# =============================================================================
# 1. Config Tests
# =============================================================================

def test_pipeline_config_defaults():
    cfg = PipelineConfig()
    assert cfg.openalgo_host == "http://127.0.0.1:5000"
    assert cfg.strategy_tag == "HedgedAOS"
    assert cfg.default_product == "MIS"
    assert cfg.enforce_margin_safety_sequence is True


# =============================================================================
# 2. OpenAlgoClient Tests
# =============================================================================

class TestOpenAlgoClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_quotes_success(self, mock_config):
        respx.post("http://127.0.0.1:5000/api/v1/quotes").mock(
            return_value=httpx.Response(200, json={"status": "success", "symbol": "NIFTY", "ltp": 24250.0, "high": 24300.0, "low": 24200.0})
        )

        client = OpenAlgoClient(config=mock_config)
        res = await client.get_quotes("NIFTY", "NSE_INDEX")
        assert res["status"] == "success"
        assert res["ltp"] == 24250.0
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_option_chain_success(self, mock_config):
        mock_chain_resp = {
            "status": "success",
            "underlying": "NIFTY",
            "underlying_ltp": 24000.0,
            "expiry_date": "2026-08-27",
            "chain": [
                {
                    "strike": 24000.0,
                    "ce": {"symbol": "NIFTY_24000_CE", "ltp": 120.0, "iv": 0.15, "oi": 80000, "vol": 25000},
                    "pe": {"symbol": "NIFTY_24000_PE", "ltp": 115.0, "iv": 0.15, "oi": 75000, "vol": 23000},
                }
            ],
        }
        respx.post("http://127.0.0.1:5000/api/v1/optionchain").mock(
            return_value=httpx.Response(200, json=mock_chain_resp)
        )

        client = OpenAlgoClient(config=mock_config)
        res = await client.get_option_chain("NIFTY", "NSE_INDEX")
        assert res["status"] == "success"
        assert len(res["chain"]) == 1
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_place_order_success(self, mock_config):
        respx.post("http://127.0.0.1:5000/api/v1/placeorder").mock(
            return_value=httpx.Response(200, json={"status": "success", "orderid": "ORD12345678", "message": "Order placed successfully"})
        )

        client = OpenAlgoClient(config=mock_config)
        res = await client.place_order(symbol="NIFTY_24000_CE", action="BUY", quantity=25)
        assert res["status"] == "success"
        assert res["orderid"] == "ORD12345678"
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_auth_failure_raises_exception(self, mock_config):
        respx.post("http://127.0.0.1:5000/api/v1/quotes").mock(
            return_value=httpx.Response(401, json={"status": "error", "message": "Invalid API Key"})
        )

        client = OpenAlgoClient(config=mock_config)
        with pytest.raises(OpenAlgoAuthError):
            await client.get_quotes("NIFTY")
        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_order_rejection_raises_exception(self, mock_config):
        respx.post("http://127.0.0.1:5000/api/v1/placeorder").mock(
            return_value=httpx.Response(400, json={"status": "error", "message": "Insufficient margin rejected by broker"})
        )

        client = OpenAlgoClient(config=mock_config)
        with pytest.raises(OpenAlgoOrderRejectedError):
            await client.place_order("NIFTY_24000_CE", "SELL", 25)
        await client.close()


# =============================================================================
# 3. MarketDataFeed Tests
# =============================================================================

class TestMarketDataFeed:
    @pytest.mark.asyncio
    @respx.mock
    async def test_fetch_underlying_indicators_and_chain(self, mock_config):
        respx.post("http://127.0.0.1:5000/api/v1/quotes").mock(
            return_value=httpx.Response(200, json={"status": "success", "symbol": "NIFTY", "ltp": 24000.0, "high": 24100.0, "low": 23900.0, "prev_close": 23950.0})
        )
        mock_chain = {
            "status": "success",
            "underlying": "NIFTY",
            "underlying_ltp": 24000.0,
            "expiry_date": "2026-08-27",
            "chain": [
                {
                    "strike": 24000.0,
                    "ce": {"symbol": "NIFTY26AUG24000CE", "ltp": 120.0, "iv": 0.15, "oi": 50000, "vol": 10000},
                    "pe": {"symbol": "NIFTY26AUG24000PE", "ltp": 115.0, "iv": 0.15, "oi": 55000, "vol": 11000},
                }
            ],
        }
        respx.post("http://127.0.0.1:5000/api/v1/optionchain").mock(
            return_value=httpx.Response(200, json=mock_chain)
        )

        client = OpenAlgoClient(config=mock_config)
        feed = MarketDataFeed(client=client)

        snapshot, regime = await feed.get_latest_market_state(UnderlyingIndex.NIFTY)
        assert snapshot.spot_price == 24000.0
        assert len(snapshot.strikes) == 2  # 1 CE + 1 PE
        assert isinstance(regime, RegimeClassification)
        await client.close()


# =============================================================================
# 4. OrderRouter Tests (Margin Safety Sequencing)
# =============================================================================

class TestOrderRouter:
    @pytest.mark.asyncio
    @respx.mock
    async def test_margin_safety_sequencing_buys_wings_first(self, mock_config):
        """Crucial risk check: BUY protection legs MUST be placed before SELL credit legs."""
        call_log = []

        def place_order_callback(request):
            body = httpx.Request(request.method, request.url, content=request.content).read().decode()
            call_log.append(body)
            return httpx.Response(200, json={"status": "success", "orderid": f"ORD_{len(call_log)}"})

        respx.post("http://127.0.0.1:5000/api/v1/placeorder").mock(side_effect=place_order_callback)

        client = OpenAlgoClient(config=mock_config)
        router = OrderRouter(client=client, enforce_margin_safety=True, delay_between_legs_seconds=0.0)

        # Create Iron Condor signal with 2 BUY legs and 2 SELL legs in mixed order
        short_ce = OptionLeg(symbol="NIFTY_24200_CE", underlying=UnderlyingIndex.NIFTY, strike=24200, option_type=OptionType.CE, expiry="2026-08-27", action=OrderAction.SELL, quantity=25)
        buy_ce = OptionLeg(symbol="NIFTY_24400_CE", underlying=UnderlyingIndex.NIFTY, strike=24400, option_type=OptionType.CE, expiry="2026-08-27", action=OrderAction.BUY, quantity=25)
        short_pe = OptionLeg(symbol="NIFTY_23800_PE", underlying=UnderlyingIndex.NIFTY, strike=23800, option_type=OptionType.PE, expiry="2026-08-27", action=OrderAction.SELL, quantity=25)
        buy_pe = OptionLeg(symbol="NIFTY_23600_PE", underlying=UnderlyingIndex.NIFTY, strike=23600, option_type=OptionType.PE, expiry="2026-08-27", action=OrderAction.BUY, quantity=25)

        signal = TradeSignal(
            signal_type=SignalType.ENTRY,
            strategy_type=StrategyType.IRON_CONDOR,
            underlying=UnderlyingIndex.NIFTY,
            regime=MarketRegime.LOW_IV_RANGING,
            legs=[short_ce, buy_ce, short_pe, buy_pe],  # Sell is listed first in raw list
        )

        report = await router.route_entry_signal(signal)
        assert report.status == "FULLY_FILLED"
        assert report.filled_legs == 4

        # Verify execution sequence: The first 2 executions MUST be BUY orders!
        import json
        assert json.loads(call_log[0])["action"] == "BUY"
        assert json.loads(call_log[1])["action"] == "BUY"
        assert json.loads(call_log[2])["action"] == "SELL"
        assert json.loads(call_log[3])["action"] == "SELL"

        await client.close()

    @pytest.mark.asyncio
    @respx.mock
    async def test_exit_signal_closes_short_legs_first(self, mock_config):
        """When exiting, short risk legs must be bought back first."""
        call_log = []

        def place_order_callback(request):
            body = request.content.decode()
            call_log.append(body)
            return httpx.Response(200, json={"status": "success", "orderid": "ORD_EXIT"})

        respx.post("http://127.0.0.1:5000/api/v1/placeorder").mock(side_effect=place_order_callback)

        client = OpenAlgoClient(config=mock_config)
        router = OrderRouter(client=client, delay_between_legs_seconds=0.0)

        # Original position: 1 SELL leg, 1 BUY leg
        short_ce = OptionLeg(symbol="NIFTY_24200_CE", underlying=UnderlyingIndex.NIFTY, strike=24200, option_type=OptionType.CE, expiry="2026-08-27", action=OrderAction.SELL, quantity=25)
        buy_ce = OptionLeg(symbol="NIFTY_24400_CE", underlying=UnderlyingIndex.NIFTY, strike=24400, option_type=OptionType.CE, expiry="2026-08-27", action=OrderAction.BUY, quantity=25)

        exit_signal = TradeSignal(
            signal_type=SignalType.TARGET,
            strategy_type=StrategyType.BULL_CALL_SPREAD,
            underlying=UnderlyingIndex.NIFTY,
            regime=MarketRegime.HIGH_IV_TRENDING,
            legs=[buy_ce, short_ce],
        )

        report = await router.route_exit_signal(exit_signal)
        assert report.status == "FULLY_FILLED"

        # The short CE must be closed first with a BUY action
        import json
        assert json.loads(call_log[0])["action"] == "BUY"
        assert json.loads(call_log[1])["action"] == "SELL"
        await client.close()


# =============================================================================
# 5. PositionTracker Tests
# =============================================================================

class TestPositionTracker:
    @pytest.mark.asyncio
    @respx.mock
    async def test_sync_positions_and_greeks(self, mock_config):
        mock_positions = {
            "status": "success",
            "data": [
                {"symbol": "NIFTY26AUG24200CE", "quantity": -25, "sell_price": 85.0, "ltp": 70.0, "exchange": "NFO"},
                {"symbol": "NIFTY26AUG23800PE", "quantity": -25, "sell_price": 80.0, "ltp": 65.0, "exchange": "NFO"},
            ],
        }
        respx.post("http://127.0.0.1:5000/api/v1/positionbook").mock(
            return_value=httpx.Response(200, json=mock_positions)
        )

        client = OpenAlgoClient(config=mock_config)
        tracker = PositionTracker(client=client)

        states = await tracker.sync_positions()
        assert len(states) == 1
        pos = states[0]
        assert pos.underlying == UnderlyingIndex.NIFTY
        assert len(pos.legs) == 2
        assert pos.legs[0].action == OrderAction.SELL
        assert pos.legs[1].action == OrderAction.SELL
        await client.close()


# =============================================================================
# 6. Master Runner End-to-End Test
# =============================================================================

class TestMainRunnerIntegration:
    @pytest.mark.asyncio
    @respx.mock
    async def test_engine_single_run_cycle(self, mock_config):
        """Verify master runner executes a complete cycle end-to-end with mocked broker API."""
        # 1. Mock ping & funds
        respx.get("http://127.0.0.1:5000/api/v1/ping").mock(return_value=httpx.Response(200, json={"status": "pong"}))
        respx.post("http://127.0.0.1:5000/api/v1/funds").mock(return_value=httpx.Response(200, json={"status": "success", "data": {"available_margin": 500000.0}}))

        # 2. Mock quotes & option chain (Low IV Ranging -> Iron Condor)
        respx.post("http://127.0.0.1:5000/api/v1/quotes").mock(
            return_value=httpx.Response(200, json={"status": "success", "symbol": "NIFTY", "ltp": 24000.0, "high": 24050.0, "low": 23950.0, "prev_close": 24000.0})
        )

        # Build realistic chain with strikes around 24000
        strikes_payload = []
        for strike in [23600, 23800, 24000, 24200, 24400]:
            strikes_payload.append({
                "strike": float(strike),
                "ce": {"symbol": f"NIFTY_{strike}_CE", "ltp": max(5.0, 24000.0 - strike + 100.0), "iv": 0.15, "oi": 60000, "vol": 15000},
                "pe": {"symbol": f"NIFTY_{strike}_PE", "ltp": max(5.0, strike - 24000.0 + 100.0), "iv": 0.15, "oi": 60000, "vol": 15000},
            })

        respx.post("http://127.0.0.1:5000/api/v1/optionchain").mock(
            return_value=httpx.Response(200, json={"status": "success", "underlying": "NIFTY", "underlying_ltp": 24000.0, "expiry_date": "2026-08-27", "chain": strikes_payload})
        )

        # 3. Mock empty position book (triggers entry signal)
        respx.post("http://127.0.0.1:5000/api/v1/positionbook").mock(
            return_value=httpx.Response(200, json={"status": "success", "data": []})
        )

        # 4. Mock order placement
        respx.post("http://127.0.0.1:5000/api/v1/placeorder").mock(
            return_value=httpx.Response(200, json={"status": "success", "orderid": "ORD_AUTO_1"})
        )

        engine = StrategyExecutionEngine(config=mock_config, target_indices=[UnderlyingIndex.NIFTY])
        await engine.initialize()
        await engine.run_cycle()

        # Engine should have processed cycle without unhandled exceptions
        assert engine.config.openalgo_host == "http://127.0.0.1:5000"
        await engine.stop()

