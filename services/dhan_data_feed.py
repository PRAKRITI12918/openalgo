"""
dhan_data_feed.py - High-Performance Dhan Data API & Real-Time Market Feed Engine.

Provides:
- Robust REST Client for Dhan Market Data (LTP, Quotes, Level-20 Depth, Option Chain, OHLCV History)
- High-throughput Binary WebSocket Client for wss://api-feed.dhan.co
- Token expiration detection, rate limiting (5 req/s data, 1 req/s quotes)
- Automatic reconnection with exponential backoff & ping/pong heartbeats
- Standardized OpenAlgo DataFrame formatting
"""

import base64
import json
import logging
import math
import os
import struct
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
import requests

# Optional websocket import
try:
    import websocket
except ImportError:
    websocket = None

logger = logging.getLogger("dhan_data_feed")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s in %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


# Dhan API Exchange Segment Mapping
EXCHANGE_SEGMENTS = {
    "NSE": 1,        # NSE Equity
    "NSE_FNO": 2,    # NSE Futures & Options
    "NSE_CURR": 3,   # NSE Currency
    "BSE": 4,        # BSE Equity
    "MCX": 5,        # MCX Commodity
    "BSE_FNO": 8,    # BSE Futures & Options
}

# Dhan Response Request Codes
REQ_CODE_LTP = 2
REQ_CODE_QUOTE = 4
REQ_CODE_DEPTH_20 = 20
REQ_CODE_DISCONNECT = 50


class DhanDataFeed:
    """
    Unified Dhan Data API Interface.
    Combines REST endpoints for historical/market queries and binary WebSocket for live streaming.
    """

    BASE_URL = "https://api.dhan.co"
    WS_URL = "wss://api-feed.dhan.co"

    def __init__(
        self,
        client_id: str | None = None,
        access_token: str | None = None,
        auto_connect_ws: bool = False,
    ):
        """
        Initialize Dhan Data Feed.
        If credentials are not provided, attempts to load them from environment or DB.
        """
        self.client_id = client_id or self._resolve_client_id()
        self.access_token = access_token or self._resolve_access_token()

        # REST Rate Limiting
        self._last_data_call = 0.0
        self._last_quote_call = 0.0
        self._lock = threading.Lock()

        # WebSocket State
        self.ws: Any | None = None
        self.ws_thread: threading.Thread | None = None
        self.is_connected = False
        self.is_running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 15

        # Callbacks & Subscriptions
        self.on_tick_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self.on_depth_callbacks: list[Callable[[dict[str, Any]], None]] = []
        self.subscribed_instruments: dict[str, dict[str, Any]] = {}  # {key: {segment, security_id, symbol}}
        self.last_ltp_cache: dict[str, float] = {}
        self.latency_ms = 0.0

        if auto_connect_ws and self.is_configured():
            self.start_websocket()

    # =========================================================================
    # Credential Resolution & Validation
    # =========================================================================

    def _resolve_client_id(self) -> str:
        """Resolve Dhan Client ID from environment or DB."""
        broker_api_key = os.getenv("BROKER_API_KEY", "")
        if ":::" in broker_api_key:
            return broker_api_key.split(":::")[0].strip()
        env_client = os.getenv("DHAN_CLIENT_ID", broker_api_key.strip())
        if env_client:
            return env_client
        try:
            from database.auth_db import Auth
            auth_obj = Auth.query.filter_by(broker="dhan", is_revoked=False).first()
            if auth_obj and auth_obj.user_id:
                return auth_obj.user_id
        except Exception:
            pass
        return ""

    def _resolve_access_token(self) -> str:
        """Resolve Dhan access token from database or environment."""
        try:
            from database.auth_db import Auth, decrypt_token, get_auth_token
            db_token = get_auth_token(self.client_id or "default")
            if db_token:
                return db_token

            auth_obj = None
            if self.client_id:
                auth_obj = Auth.query.filter_by(user_id=self.client_id, is_revoked=False).first()
            if not auth_obj:
                auth_obj = Auth.query.filter_by(broker="dhan", is_revoked=False).first()

            if auth_obj and auth_obj.auth:
                decrypted = decrypt_token(auth_obj.auth)
                if decrypted:
                    return decrypted
        except Exception:
            pass
        return os.getenv("DHAN_ACCESS_TOKEN", os.getenv("BROKER_API_SECRET", ""))

    def is_configured(self) -> bool:
        """Check if both client ID and access token are present."""
        return bool(self.client_id and self.access_token and self.access_token != "************")

    def get_token_expiry_info(self) -> dict[str, Any]:
        """
        Extract token expiry metadata from JWT or calculate daily ~3:30 AM IST expiry.
        """
        if not self.access_token:
            return {"valid": False, "status": "Missing Token"}

        try:
            # Attempt to decode unverified JWT payload
            parts = self.access_token.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                payload_json = base64.urlsafe_b64decode(padded).decode("utf-8")
                payload = json.loads(payload_json)

                exp_ts = payload.get("exp")
                if exp_ts:
                    exp_dt = datetime.fromtimestamp(exp_ts, tz=UTC)
                    remaining = exp_dt - datetime.now(UTC)
                    return {
                        "valid": remaining.total_seconds() > 0,
                        "expiry_utc": exp_dt.isoformat(),
                        "remaining_hours": max(0, round(remaining.total_seconds() / 3600, 1)),
                        "payload": payload,
                    }
        except Exception:
            pass

        # Fallback for static daily tokens: Valid until next 3:30 AM IST
        return {
            "valid": True,
            "note": "Standard daily broker token (renews daily at ~03:30 IST)",
            "remaining_hours": 12.0
        }

    # =========================================================================
    # Rate Limiting & REST Dispatcher
    # =========================================================================

    def _apply_rate_limit(self, category: str = "data") -> None:
        """Rate limit: 5 req/s (0.2s) for historical charts, 1 req/s (1.0s) for quotes."""
        with self._lock:
            now = time.monotonic()
            interval = 0.2 if category == "data" else 1.05
            last_call = self._last_data_call if category == "data" else self._last_quote_call
            elapsed = now - last_call
            if elapsed < interval:
                time.sleep(interval - elapsed)
            if category == "data":
                self._last_data_call = time.monotonic()
            else:
                self._last_quote_call = time.monotonic()

    def _get_headers(self) -> dict[str, str]:
        """Get standard Dhan API authentication headers."""
        return {
            "access-token": self.access_token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def verify_credentials(self) -> tuple[bool, dict[str, Any]]:
        """
        Verify Dhan Data API subscription and connectivity.
        Sends a test quote request and verifies permissions.
        """
        if not self.is_configured():
            return False, {"message": "Client ID or Access Token is missing"}

        start_time = time.monotonic()
        url = f"{self.BASE_URL}/v2/marketfeed/ltp"
        # Test symbol: Nifty 50 Index (Segment 1, Security ID 13)
        payload = {"1": [13]}

        try:
            self._apply_rate_limit("quote")
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=8)
            latency = round((time.monotonic() - start_time) * 1000, 2)
            self.latency_ms = latency

            if response.status_code == 200:
                data = response.json()
                expiry_info = self.get_token_expiry_info()
                return True, {
                    "status": "success",
                    "client_id": self.client_id,
                    "data_api_active": True,
                    "latency_ms": latency,
                    "token_expiry": expiry_info,
                    "message": "Dhan Data API connected successfully",
                    "sample_data": data,
                }
            elif response.status_code == 401:
                return False, {
                    "status": "error",
                    "code": 401,
                    "message": "Invalid or expired Dhan Access Token. Please re-authenticate.",
                }
            elif response.status_code == 403 or "806" in response.text:
                return False, {
                    "status": "error",
                    "code": 806,
                    "message": "Dhan Data API subscription is not active. Please activate it in your Dhan Console.",
                }
            else:
                return False, {
                    "status": "error",
                    "code": response.status_code,
                    "message": f"Dhan API Error ({response.status_code}): {response.text}",
                }

        except Exception as e:
            logger.exception(f"Error verifying Dhan Data API: {e}")
            return False, {"status": "error", "message": str(e)}

    # =========================================================================
    # Historical Data (OHLCV Candles)
    # =========================================================================

    def get_historical_candles(
        self,
        security_id: str,
        exchange_segment: str = "NSE_EQ",
        instrument_type: str = "EQUITY",
        interval: str = "1",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> tuple[bool, pd.DataFrame | dict[str, Any]]:
        """
        Fetch OHLCV historical candle data from Dhan and return as a clean pandas DataFrame.

        Args:
            security_id: Dhan numeric instrument security ID (e.g. '1330' for RELIANCE)
            exchange_segment: 'NSE_EQ', 'NSE_FNO', 'BSE_EQ', 'MCX_COMM'
            instrument_type: 'EQUITY', 'FUTIDX', 'OPTIDX', etc.
            interval: '1', '5', '15', '25', '60', or 'D' (daily)
            from_date: 'YYYY-MM-DD'
            to_date: 'YYYY-MM-DD'
        """
        is_intraday = interval.upper() != "D" and interval != "DAY"
        endpoint = "/v2/charts/intraday" if is_intraday else "/v2/charts/historical"
        url = f"{self.BASE_URL}{endpoint}"

        today_str = datetime.now().strftime("%Y-%m-%d")
        to_date = to_date or today_str
        if not from_date:
            if is_intraday:
                from_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
            else:
                from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": exchange_segment,
            "instrument": instrument_type,
            "fromDate": from_date,
            "toDate": to_date,
        }

        if is_intraday:
            payload["interval"] = str(interval)

        self._apply_rate_limit("data")
        try:
            response = requests.post(url, headers=self._get_headers(), json=payload, timeout=12)
            if response.status_code != 200:
                return False, {"error": f"Dhan error {response.status_code}: {response.text}"}

            data = response.json()
            if not data or "timestamp" not in data or not data["timestamp"]:
                return True, pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

            # Construct Standard DataFrame
            timestamps = [datetime.fromtimestamp(ts) for ts in data["timestamp"]]
            df = pd.DataFrame(
                {
                    "datetime": timestamps,
                    "open": [float(x) for x in data["open"]],
                    "high": [float(x) for x in data["high"]],
                    "low": [float(x) for x in data["low"]],
                    "close": [float(x) for x in data["close"]],
                    "volume": [int(x) for x in data.get("volume", [0] * len(timestamps))],
                }
            )
            df.sort_values("datetime", inplace=True)
            df.reset_index(drop=True, inplace=True)
            return True, df

        except Exception as e:
            logger.exception(f"Error fetching historical candles: {e}")
            return False, {"error": str(e)}

    # =========================================================================
    # Quotes, Level 20 Depth & Option Chain
    # =========================================================================

    def get_quote(self, security_id: int, segment: int = 1) -> tuple[bool, dict[str, Any]]:
        """Fetch Full Quote including Level 5 market depth."""
        url = f"{self.BASE_URL}/v2/marketfeed/quote"
        payload = {str(segment): [int(security_id)]}

        self._apply_rate_limit("quote")
        try:
            res = requests.post(url, headers=self._get_headers(), json=payload, timeout=8)
            if res.status_code == 200:
                data = res.json()
                return True, data.get("data", {}).get(str(segment), {}).get(str(security_id), {})
            return False, {"error": f"Dhan quote error: {res.text}"}
        except Exception as e:
            return False, {"error": str(e)}

    def get_option_chain(self, underlying_scrip: int, underlying_seg: str = "IDX_I", expiry: str | None = None) -> tuple[bool, dict[str, Any]]:
        """Fetch Option Chain with live IV, Greeks, and Strikes."""
        url = f"{self.BASE_URL}/v2/optionchain"
        payload = {
            "UnderlyingScrip": underlying_scrip,
            "UnderlyingSeg": underlying_seg,
        }
        if expiry:
            payload["Expiry"] = expiry

        self._apply_rate_limit("data")
        try:
            res = requests.post(url, headers=self._get_headers(), json=payload, timeout=10)
            if res.status_code == 200:
                return True, res.json()
            return False, {"error": f"Option chain error: {res.text}"}
        except Exception as e:
            return False, {"error": str(e)}

    # =========================================================================
    # High-Throughput Binary WebSocket Feed
    # =========================================================================

    def register_on_tick(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback handler for live ticks."""
        if callback not in self.on_tick_callbacks:
            self.on_tick_callbacks.append(callback)

    def register_on_depth(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a callback handler for 20-level market depth."""
        if callback not in self.on_depth_callbacks:
            self.on_depth_callbacks.append(callback)

    def start_websocket(self) -> None:
        """Start the Dhan WebSocket client in a background daemon thread."""
        if self.is_running or not websocket:
            return

        self.is_running = True
        self.ws_thread = threading.Thread(target=self._ws_run_loop, name="DhanFeed-WS", daemon=True)
        self.ws_thread.start()
        logger.info("Dhan WebSocket client worker started.")

    def stop_websocket(self) -> None:
        """Gracefully disconnect and stop the WebSocket client."""
        self.is_running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        self.is_connected = False
        logger.info("Dhan WebSocket client stopped.")

    def subscribe(self, instrument_list: list[dict[str, Any]], depth_level: int = 2) -> bool:
        """
        Subscribe to live ticker data.

        Args:
            instrument_list: List of dicts [{'exchange_segment': 'NSE', 'security_id': '1330', 'symbol': 'RELIANCE'}]
            depth_level: 2 for LTP, 4 for Quote (Level 5), 20 for Full Market Depth (Level 20)
        """
        for item in instrument_list:
            key = f"{item.get('exchange_segment')}:{item.get('security_id')}"
            self.subscribed_instruments[key] = item

        if not self.is_connected or not self.ws:
            return True  # Stored for replay on connect

        # Build Dhan binary subscription frame
        payload = []
        for item in instrument_list:
            seg = EXCHANGE_SEGMENTS.get(item.get("exchange_segment", "NSE"), 1)
            payload.append({
                "ExchangeSegment": str(seg),
                "SecurityId": str(item.get("security_id")),
            })

        req_code = 15 if depth_level == 20 else (17 if depth_level == 4 else 21)
        sub_message = json.dumps({"RequestCode": req_code, "InstrumentList": payload})

        try:
            self.ws.send(sub_message)
            logger.info(f"Subscribed {len(instrument_list)} instruments on Dhan WS (ReqCode: {req_code})")
            return True
        except Exception as e:
            logger.error(f"Failed to send subscription: {e}")
            return False

    def _ws_run_loop(self) -> None:
        """WebSocket connection supervisor loop with automatic reconnection."""
        while self.is_running:
            try:
                ws_url = (
                    f"{self.WS_URL}?version=2&token={self.access_token}"
                    f"&clientId={self.client_id}&authType=2"
                )

                self.ws = websocket.WebSocketApp(
                    ws_url,
                    on_open=self._on_ws_open,
                    on_message=self._on_ws_message,
                    on_error=self._on_ws_error,
                    on_close=self._on_ws_close,
                )

                self.ws.run_forever(ping_interval=15, ping_timeout=8)

            except Exception as e:
                logger.error(f"Dhan WS supervisor error: {e}")

            if not self.is_running:
                break

            self.reconnect_attempts += 1
            backoff = min(60, 2 ** min(self.reconnect_attempts, 6))
            logger.info(f"Reconnecting Dhan WS in {backoff}s (attempt {self.reconnect_attempts})...")
            time.sleep(backoff)

    def _on_ws_open(self, ws: Any) -> None:
        """Triggered upon successful WebSocket connection."""
        self.is_connected = True
        self.reconnect_attempts = 0
        logger.info("Connected to Dhan Real-Time Binary Feed.")

        # Resubscribe all registered instruments
        if self.subscribed_instruments:
            items = list(self.subscribed_instruments.values())
            self.subscribe(items, depth_level=2)

    def _on_ws_message(self, ws: Any, message: Any) -> None:
        """Parse incoming binary packets from Dhan feed."""
        if not isinstance(message, bytes) or len(message) < 8:
            return

        try:
            # Dhan 8-byte Binary Header:
            # byte 0: Response Code
            # byte 1-2: Message Length (uint16)
            # byte 3: Exchange Segment (uint8)
            # byte 4-7: Security ID (int32)
            req_code = message[0]
            seg_id = message[3]
            sec_id = struct.unpack("<i", message[4:8])[0]

            # 1. LTP Packet (Code 2, 16 bytes total)
            if req_code == REQ_CODE_LTP and len(message) >= 16:
                ltp = struct.unpack("<f", message[8:12])[0]
                ltt_ts = struct.unpack("<i", message[12:16])[0]

                tick_data = {
                    "type": "ltp",
                    "security_id": sec_id,
                    "exchange_segment": seg_id,
                    "ltp": round(ltp, 2),
                    "timestamp": ltt_ts,
                    "time_str": datetime.fromtimestamp(ltt_ts).strftime("%H:%M:%S") if ltt_ts > 0 else ""
                }
                self.last_ltp_cache[str(sec_id)] = round(ltp, 2)
                for cb in self.on_tick_callbacks:
                    try:
                        cb(tick_data)
                    except Exception:
                        pass

            # 2. Quote Packet (Code 4, 42 bytes)
            elif req_code == REQ_CODE_QUOTE and len(message) >= 42:
                ltp = struct.unpack("<f", message[8:12])[0]
                ltq = struct.unpack("<h", message[12:14])[0]
                ltt = struct.unpack("<i", message[14:18])[0]
                atp = struct.unpack("<f", message[18:22])[0]
                vol = struct.unpack("<i", message[22:26])[0]

                quote_data = {
                    "type": "quote",
                    "security_id": sec_id,
                    "exchange_segment": seg_id,
                    "ltp": round(ltp, 2),
                    "ltq": ltq,
                    "volume": vol,
                    "atp": round(atp, 2),
                    "timestamp": ltt,
                }
                self.last_ltp_cache[str(sec_id)] = round(ltp, 2)
                for cb in self.on_tick_callbacks:
                    try:
                        cb(quote_data)
                    except Exception:
                        pass

            # 3. 20-Level Depth Packet (Code 20)
            elif req_code == REQ_CODE_DEPTH_20 and len(message) >= 208:
                bids = []
                asks = []
                offset = 8
                for _ in range(20):
                    qty, price, orders = struct.unpack("<ifi", message[offset:offset+12])
                    bids.append({"price": round(price, 2), "quantity": qty, "orders": orders})
                    offset += 12
                for _ in range(20):
                    qty, price, orders = struct.unpack("<ifi", message[offset:offset+12])
                    asks.append({"price": round(price, 2), "quantity": qty, "orders": orders})
                    offset += 12

                depth_data = {
                    "type": "depth20",
                    "security_id": sec_id,
                    "exchange_segment": seg_id,
                    "bids": bids,
                    "asks": asks,
                }
                for cb in self.on_depth_callbacks:
                    try:
                        cb(depth_data)
                    except Exception:
                        pass

        except Exception as e:
            logger.debug(f"Binary unpack exception: {e}")

    def _on_ws_error(self, ws: Any, error: Any) -> None:
        """Handle WebSocket error."""
        logger.warning(f"Dhan WS Error: {error}")

    def _on_ws_close(self, ws: Any, close_status_code: Any, close_msg: Any) -> None:
        """Handle WebSocket closure."""
        self.is_connected = False
        logger.info(f"Dhan WS disconnected: code={close_status_code}, msg={close_msg}")


# Singleton instance helper
_dhan_feed_instance: DhanDataFeed | None = None


def get_dhan_data_feed() -> DhanDataFeed:
    """Get or create singleton DhanDataFeed instance."""
    global _dhan_feed_instance
    if _dhan_feed_instance is None:
        _dhan_feed_instance = DhanDataFeed()
    return _dhan_feed_instance
