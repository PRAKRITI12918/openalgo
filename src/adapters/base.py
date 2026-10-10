"""
Abstract Base Broker Adapter.
Defines the standard asynchronous interface for hot-swapping between MockBroker,
OpenAlgo Sandbox, and Live Broker connections (Zerodha, DhanHQ, Flattrade) without
altering core execution engine sequencing logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.models.schemas import LegExecutionState, LegOrderRequest, PositionStateModel


class BaseBrokerAdapter(ABC):
    """
    Abstract contract for broker execution backends.
    All methods are non-blocking coroutines and thread-safe.
    """

    @abstractmethod
    async def place_order(
        self,
        leg: LegOrderRequest,
        correlation_id: str = "",
        account_id: Optional[str] = None,
    ) -> LegExecutionState:
        """
        Place an individual single-leg option order.
        Returns the resulting LegExecutionState containing broker order_id, fills, and status.
        """
        pass

    @abstractmethod
    async def place_multi_leg_batch(
        self,
        legs: List[LegOrderRequest],
        correlation_id: str = "",
        account_id: Optional[str] = None,
    ) -> List[LegExecutionState]:
        """
        Place a batch of multi-leg option orders concurrently or sequentially.
        """
        pass

    @abstractmethod
    async def cancel_order(
        self,
        order_id: str,
        correlation_id: str = "",
    ) -> bool:
        """
        Request immediate cancellation of an open or pending order.
        """
        pass

    @abstractmethod
    async def get_order_status(
        self,
        order_id: str,
    ) -> LegExecutionState:
        """
        Query current execution lifecycle status for an existing order.
        """
        pass

    @abstractmethod
    async def get_positions(self, account_id: Optional[str] = None) -> List[PositionStateModel]:
        """
        Query active open portfolio positions from the broker.
        """
        pass

    @abstractmethod
    async def get_funds(self, account_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Retrieve available cash, margin used, and account leverage limits.
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verify connection vitality and broker API responsiveness.
        """
        pass

    @abstractmethod
    async def square_off_all(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Emergency square-off: liquidate all open positions for the specified account.
        """
        pass
