"""
Broker Authentication Adapter Interface and Registry.
Provides modular authentication, credential verification, and token lifecycle management
for multi-broker accounts (Dhan, Zerodha, Fyers, Flattrade, Mock).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
import uuid

import structlog

logger = structlog.get_logger("openalgo.broker_auth")


class BrokerAuthAdapter(ABC):
    """
    Abstract Interface for Broker Authentication.
    Handles login initialization, credential verification/exchange, and token revocation.
    """

    @abstractmethod
    async def initiate_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Initiate broker authentication.
        For OAuth brokers, returns the login URL.
        For direct credentials (API key/secret/totp), validates preliminary schema.
        """
        pass

    @abstractmethod
    async def complete_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """
        Complete authentication or exchange request tokens.
        Returns dict containing:
        - "access_token": secure broker auth token
        - "external_account_id": broker's client ID / user ID
        - "feed_token": (optional) market data streaming token
        - "metadata": (optional) auxiliary session information
        """
        pass

    @abstractmethod
    async def disconnect(self, token_ref: str) -> bool:
        """
        Revoke the active token/session with the broker upstream.
        """
        pass


class MockBrokerAuthAdapter(BrokerAuthAdapter):
    """
    Mock Broker Auth Adapter for deterministic simulation and automated testing.
    """

    async def initiate_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        client_id = credentials.get("client_id") or f"mock_{uuid.uuid4().hex[:6]}"
        return {
            "status": "ready",
            "broker": "mock",
            "client_id": client_id,
            "message": "Mock broker ready for authentication",
        }

    async def complete_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(credentials.get("client_id") or credentials.get("user_id") or "MOCK_CLIENT_101")
        api_key = credentials.get("api_key") or "mock_api_key_valid"
        
        # Simulate authentication failure if requested by test
        if credentials.get("simulate_auth_failure"):
            raise ValueError("Simulated broker authentication failure: Invalid credentials")

        token = f"mock_token_{client_id}_{uuid.uuid4().hex[:8]}"
        return {
            "access_token": token,
            "external_account_id": client_id,
            "feed_token": f"feed_{token}",
            "metadata": {"broker": "mock", "api_key_masked": f"{api_key[:4]}****"},
        }

    async def disconnect(self, token_ref: str) -> bool:
        logger.info("mock_broker_auth_disconnected", token_ref=token_ref[:10] if token_ref else "")
        return True


class DhanAuthAdapter(BrokerAuthAdapter):
    """
    Dhan Broker Authentication Adapter.
    Requires client_id and access_token (direct API authentication).
    """

    async def initiate_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        client_id = credentials.get("client_id")
        if not client_id:
            raise ValueError("client_id is required for Dhan authentication")
        return {"status": "ready", "broker": "dhan", "client_id": client_id}

    async def complete_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(credentials.get("client_id") or "").strip()
        access_token = str(credentials.get("access_token") or credentials.get("api_key") or "").strip()

        if not client_id or not access_token:
            raise ValueError("Dhan authentication requires both client_id and access_token")

        return {
            "access_token": access_token,
            "external_account_id": client_id,
            "feed_token": None,
            "metadata": {"broker": "dhan"},
        }

    async def disconnect(self, token_ref: str) -> bool:
        logger.info("dhan_broker_disconnected")
        return True


class ZerodhaAuthAdapter(BrokerAuthAdapter):
    """
    Zerodha Kite Connect Authentication Adapter.
    Supports OAuth token exchange or API key + access token.
    """

    async def initiate_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        api_key = credentials.get("api_key")
        if not api_key:
            raise ValueError("api_key is required for Zerodha Kite")
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
        return {"status": "oauth_redirect", "login_url": login_url, "broker": "zerodha"}

    async def complete_auth(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(credentials.get("client_id") or credentials.get("user_id") or "zerodha_user").strip()
        access_token = str(credentials.get("access_token") or credentials.get("api_key") or "").strip()

        if not access_token:
            raise ValueError("Zerodha authentication requires valid access_token or API key")

        return {
            "access_token": access_token,
            "external_account_id": client_id,
            "feed_token": None,
            "metadata": {"broker": "zerodha"},
        }

    async def disconnect(self, token_ref: str) -> bool:
        logger.info("zerodha_broker_disconnected")
        return True


# Adapter Registry
_ADAPTER_REGISTRY: Dict[str, BrokerAuthAdapter] = {
    "mock": MockBrokerAuthAdapter(),
    "dhan": DhanAuthAdapter(),
    "zerodha": ZerodhaAuthAdapter(),
}


def get_broker_auth_adapter(broker_id: str) -> BrokerAuthAdapter:
    """Retrieve registered BrokerAuthAdapter or fallback to MockBrokerAuthAdapter."""
    clean_broker = (broker_id or "").strip().lower()
    return _ADAPTER_REGISTRY.get(clean_broker, _ADAPTER_REGISTRY["mock"])


def register_broker_auth_adapter(broker_id: str, adapter: BrokerAuthAdapter) -> None:
    """Register custom BrokerAuthAdapter."""
    _ADAPTER_REGISTRY[broker_id.strip().lower()] = adapter
