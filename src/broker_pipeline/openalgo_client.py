"""
High-Performance Asynchronous OpenAlgo v1 REST Client.
Wraps all official OpenAlgo endpoints with structured schemas, retries, and strict error handling.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from src.broker_pipeline.config import PipelineConfig

logger = logging.getLogger("broker_pipeline.client")


class OpenAlgoError(Exception):
    """Base exception for OpenAlgo client errors."""
    pass


class OpenAlgoNetworkError(OpenAlgoError):
    """Network connection or timeout error."""
    pass


class OpenAlgoAuthError(OpenAlgoError):
    """API key or authentication failure."""
    pass


class OpenAlgoOrderRejectedError(OpenAlgoError):
    """Order rejected by broker or risk controls."""
    pass


class OpenAlgoAPIError(OpenAlgoError):
    """General API protocol or schema validation error."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class OpenAlgoClient:
    """
    Async HTTP client for OpenAlgo v1 Trading & Market Data API.
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.config = config or PipelineConfig()
        self.base_url = self.config.openalgo_host.rstrip("/")
        self.api_key = self.config.openalgo_api_key
        self.strategy_tag = self.config.strategy_tag
        self._custom_client = http_client
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "OpenAlgoClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Initialize underlying httpx AsyncClient session."""
        if self._custom_client:
            self._client = self._custom_client
        elif self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.config.request_timeout_seconds),
                headers={"Content-Type": "application/json"},
            )

    async def close(self) -> None:
        """Close client session."""
        if self._client and not self._custom_client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            if self._custom_client:
                return self._custom_client
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.config.request_timeout_seconds),
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def _post_request(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Execute POST request with automatic retry and error mapping."""
        client = self._get_client()
        url = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        # Inject default API key if not present in payload
        if "apikey" not in payload and self.api_key:
            payload["apikey"] = self.api_key

        last_err: Optional[Exception] = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                response = await client.post(url, json=payload)
                status = response.status_code

                if status == 401 or status == 403:
                    raise OpenAlgoAuthError(f"Authentication failed ({status}): {response.text}")

                try:
                    data = response.json()
                except Exception:
                    data = {"status": "error", "message": response.text}

                if status >= 400:
                    msg = data.get("message", response.text)
                    if "rejected" in str(msg).lower() or "margin" in str(msg).lower():
                        raise OpenAlgoOrderRejectedError(f"Broker rejected: {msg}")
                    raise OpenAlgoAPIError(f"API error ({status}): {msg}", status_code=status, response_data=data)

                if isinstance(data, dict) and data.get("status") == "error":
                    msg = data.get("message", "Unknown error")
                    if "rejected" in str(msg).lower() or "margin" in str(msg).lower():
                        raise OpenAlgoOrderRejectedError(f"Broker rejected: {msg}")
                    raise OpenAlgoAPIError(f"OpenAlgo error: {msg}", status_code=status, response_data=data)

                return data

            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as net_err:
                last_err = OpenAlgoNetworkError(f"Network error on {url} (attempt {attempt}/{self.config.max_retries}): {net_err}")
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_backoff_seconds * attempt)
            except (OpenAlgoAuthError, OpenAlgoOrderRejectedError, OpenAlgoAPIError):
                raise
            except Exception as e:
                last_err = OpenAlgoAPIError(f"Unexpected error calling {url}: {e}")
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.retry_backoff_seconds * attempt)

        if last_err:
            raise last_err
        raise OpenAlgoNetworkError(f"Failed to execute request to {url}")

    # =========================================================================
    # Market Data Endpoints
    # =========================================================================

    async def get_quotes(self, symbol: str, exchange: str = "NSE_INDEX") -> Dict[str, Any]:
        """Fetch real-time quotes / LTP for a symbol."""
        payload = {
            "symbol": symbol,
            "exchange": exchange,
        }
        return await self._post_request("/api/v1/quotes", payload)

    async def get_option_chain(
        self,
        underlying: str,
        exchange: str = "NSE_INDEX",
        expiry_date: Optional[str] = None,
        strike_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Fetch live option chain snapshot."""
        payload: Dict[str, Any] = {
            "underlying": underlying,
            "exchange": exchange,
        }
        if expiry_date:
            payload["expiry_date"] = expiry_date
        if strike_count is not None:
            payload["strike_count"] = strike_count

        return await self._post_request("/api/v1/optionchain", payload)

    async def get_option_greeks(
        self,
        underlying: str,
        exchange: str = "NSE_INDEX",
        expiry_date: Optional[str] = None,
        interest_rate: float = 0.07,
    ) -> Dict[str, Any]:
        """Fetch option chain with calculated Black-Scholes Greeks."""
        payload: Dict[str, Any] = {
            "underlying": underlying,
            "exchange": exchange,
            "interest_rate": interest_rate,
        }
        if expiry_date:
            payload["expiry_date"] = expiry_date

        return await self._post_request("/api/v1/optiongreeks", payload)

    async def get_expiry_dates(self, underlying: str, exchange: str = "NSE_INDEX") -> Dict[str, Any]:
        """Fetch available option contract expiry dates."""
        payload = {
            "underlying": underlying,
            "exchange": exchange,
        }
        return await self._post_request("/api/v1/expiry", payload)

    # =========================================================================
    # Order Execution Endpoints
    # =========================================================================

    async def place_order(
        self,
        symbol: str,
        action: str,
        quantity: int,
        exchange: str = "NFO",
        pricetype: str = "MARKET",
        price: float = 0.0,
        product: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Place single-leg regular or derivative order."""
        payload = {
            "strategy": strategy or self.strategy_tag,
            "symbol": symbol,
            "action": action.upper(),
            "exchange": exchange,
            "pricetype": pricetype.upper(),
            "quantity": quantity,
            "price": price,
            "product": product or self.config.default_product,
        }
        return await self._post_request("/api/v1/placeorder", payload)

    async def place_options_multiorder(
        self,
        underlying: str,
        legs: List[Dict[str, Any]],
        exchange: str = "NSE_INDEX",
        expiry_date: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Place multi-leg option strategy in one atomic batch.
        Legs payload format: [{"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 25}, ...]
        """
        payload: Dict[str, Any] = {
            "strategy": strategy or self.strategy_tag,
            "underlying": underlying,
            "exchange": exchange,
            "legs": legs,
        }
        if expiry_date:
            payload["expiry_date"] = expiry_date

        return await self._post_request("/api/v1/optionsmultiorder", payload)

    async def close_position(
        self,
        symbol: str,
        exchange: str = "NFO",
        product: Optional[str] = None,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Square off open position for a specific symbol."""
        payload = {
            "strategy": strategy or self.strategy_tag,
            "symbol": symbol,
            "exchange": exchange,
            "product": product or self.config.default_product,
        }
        return await self._post_request("/api/v1/closeposition", payload)

    async def get_order_status(self, orderid: str) -> Dict[str, Any]:
        """Query execution status of a placed order."""
        payload = {"orderid": str(orderid)}
        return await self._post_request("/api/v1/orderstatus", payload)

    # =========================================================================
    # Portfolio & Account Endpoints
    # =========================================================================

    async def get_position_book(self) -> Dict[str, Any]:
        """Fetch open and closed broker positions."""
        return await self._post_request("/api/v1/positionbook", {})

    async def get_funds(self) -> Dict[str, Any]:
        """Fetch account margin and available funds."""
        return await self._post_request("/api/v1/funds", {})

    async def get_order_book(self) -> Dict[str, Any]:
        """Fetch daily orderbook records."""
        return await self._post_request("/api/v1/orderbook", {})

    async def ping(self) -> bool:
        """Health check OpenAlgo API."""
        client = self._get_client()
        try:
            res = await client.get("/api/v1/ping")
            return res.status_code == 200
        except Exception:
            return False
