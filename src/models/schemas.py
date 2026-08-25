"""
Comprehensive Pydantic V2 schemas and data contracts for the Phase 2 Execution Engine.
Defines strict validation rules for signal ingestion, multi-leg sequencing, order lifecycle,
and real-time WebSocket state streaming to Phase 3.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.strategy_engine.models import (
    Greeks,
    MarketRegime,
    OptionType,
    OrderAction,
    SignalType,
    StrategyType,
    UnderlyingIndex,
)


class OrderType(str, Enum):
    """Order pricing execution types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL_MARKET = "SL_MARKET"
    SL_LIMIT = "SL_LIMIT"


class OrderStatus(str, Enum):
    """Execution lifecycle status transitions for orders."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    TRIGGERED = "TRIGGERED"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


class WebSocketEventType(str, Enum):
    """Downstream event categories for real-time WebSocket broadcasting."""
    TICK = "TICK"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_UPDATE = "ORDER_UPDATE"
    SEQUENCE_UPDATE = "SEQUENCE_UPDATE"
    POSITION_UPDATE = "POSITION_UPDATE"
    CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
    ROLLBACK_TRIGGERED = "ROLLBACK_TRIGGERED"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"


class LegOrderRequest(BaseModel):
    """
    Data contract for an individual option leg in an incoming strategy order.
    """
    model_config = ConfigDict(extra="ignore")

    leg_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique ID for this leg request")
    symbol: str = Field(..., min_length=2, description="Trading symbol or token (e.g. NIFTY26AUG24200CE)")
    underlying: UnderlyingIndex = Field(..., description="Target Index underlying")
    strike: float = Field(..., gt=0, description="Strike price of option")
    option_type: OptionType = Field(..., description="Option type (CE or PE)")
    expiry: str = Field(..., min_length=8, description="Expiry date formatted YYYY-MM-DD")
    action: OrderAction = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0, description="Order quantity in units (must be > 0)")
    order_type: OrderType = Field(default=OrderType.MARKET, description="MARKET, LIMIT, SL_MARKET, SL_LIMIT")
    price: float = Field(default=0.0, ge=0.0, description="Limit price (required if LIMIT)")
    trigger_price: float = Field(default=0.0, ge=0.0, description="Trigger price for stop loss orders")
    is_hedge_leg: bool = Field(default=False, description="Flag marking this leg as a long protection/hedge wing")
    sequence_group: int = Field(default=0, ge=0, description="Execution sequence priority (0 = Hedge/Buy, 1 = Short/Sell)")
    target_delta: Optional[float] = Field(default=None, description="Theoretical target delta")
    actual_delta: Optional[float] = Field(default=None, description="Actual or calculated entry delta")
    greeks: Optional[Greeks] = Field(default=None, description="Black-Scholes Greek parameters")
    product: str = Field(default="MIS", description="Product code (MIS, NRML, CNC)")
    exchange: str = Field(default="NFO", description="Exchange segment (NFO, BFO)")

    @model_validator(mode="after")
    def validate_limit_prices_and_group(self) -> "LegOrderRequest":
        if self.order_type in (OrderType.LIMIT, OrderType.SL_LIMIT) and self.price <= 0:
            raise ValueError(f"Limit price must be > 0 for order_type={self.order_type.value}")
        if self.order_type in (OrderType.SL_MARKET, OrderType.SL_LIMIT) and self.trigger_price <= 0:
            raise ValueError(f"Trigger price must be > 0 for order_type={self.order_type.value}")
        # Automatically mark BUY legs as hedge/group 0 if not explicitly designated
        if self.action == OrderAction.BUY and not self.is_hedge_leg:
            object.__setattr__(self, "is_hedge_leg", True)
        if self.is_hedge_leg or self.action == OrderAction.BUY:
            object.__setattr__(self, "sequence_group", 0)
        else:
            object.__setattr__(self, "sequence_group", 1)
        return self


class StrategySignalPayload(BaseModel):
    """
    Standardized REST/WebSocket signal ingestion payload received from the Phase 1 Strategy Engine.
    """
    model_config = ConfigDict(extra="ignore")

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique trade signal identifier")
    strategy_name: str = Field(..., min_length=2, description="Strategy name (e.g. IRON_CONDOR, SHORT_STRANGLE)")
    strategy_type: Optional[StrategyType] = Field(default=None, description="Strategy enumeration matching Phase 1")
    signal_type: SignalType = Field(default=SignalType.ENTRY, description="Signal intent (ENTRY, EXIT, STOP_LOSS, TARGET, HEDGE_ADJUSTMENT)")
    underlying: UnderlyingIndex = Field(..., description="Target index underlying")
    regime: MarketRegime = Field(..., description="Detected market volatility regime")
    legs: List[LegOrderRequest] = Field(..., min_length=1, description="Multi-leg array of options positions to execute")
    entry_credit_debit: float = Field(default=0.0, description="Expected net credit (+ve) or debit (-ve) per unit")
    max_profit: Optional[float] = Field(default=None, description="Max profit potential")
    max_loss: Optional[float] = Field(default=None, description="Max loss risk threshold")
    stop_loss_threshold: Optional[float] = Field(default=None, description="Max loss before automated exit trigger")
    target_threshold: Optional[float] = Field(default=None, description="Profit target trigger")
    trailing_stop_step: Optional[float] = Field(default=None, description="Trailing stop step size")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Traceability correlation ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Signal creation timestamp")
    reason: str = Field(default="", description="Algorithmic rationale for signal generation")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary strategy metadata")

    @model_validator(mode="after")
    def sync_strategy_type(self) -> "StrategySignalPayload":
        if self.strategy_type is None:
            try:
                self.strategy_type = StrategyType(self.strategy_name)
            except ValueError:
                pass
        return self


class LegExecutionState(BaseModel):
    """
    Execution status, fills, and latency metrics for an individual option leg.
    """
    model_config = ConfigDict(extra="ignore")

    leg_id: str = Field(..., description="ID matching the originating LegOrderRequest")
    symbol: str = Field(..., description="Option symbol")
    action: OrderAction = Field(..., description="BUY or SELL")
    strike: float = Field(..., description="Option strike price")
    quantity: int = Field(..., description="Ordered quantity")
    filled_quantity: int = Field(default=0, description="Cumulative filled quantity")
    requested_price: float = Field(default=0.0, description="Requested limit or benchmark price")
    execution_price: float = Field(default=0.0, description="Average fill price achieved")
    slippage: float = Field(default=0.0, description="Slippage in currency (execution_price - requested_price)")
    status: OrderStatus = Field(default=OrderStatus.PENDING, description="Current lifecycle state")
    order_id: Optional[str] = Field(default=None, description="Broker assigned order identifier")
    broker_response: Dict[str, Any] = Field(default_factory=dict, description="Raw broker response")
    error_message: Optional[str] = Field(default=None, description="Failure reason if rejected")
    latency_ms: float = Field(default=0.0, description="Execution round-trip latency in milliseconds")
    is_hedge_leg: bool = Field(default=False, description="Flag indicating if this was a hedge/protection leg")
    placed_at: datetime = Field(default_factory=datetime.utcnow, description="Submission timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last status update timestamp")


class OrderExecutionSequence(BaseModel):
    """
    Aggregated multi-leg execution workflow status and audit trail.
    """
    model_config = ConfigDict(extra="ignore")

    sequence_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Execution sequence run ID")
    signal_id: str = Field(..., description="Originating trade signal ID")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Distributed tracing correlation ID")
    strategy_name: str = Field(..., description="Strategy name")
    underlying: UnderlyingIndex = Field(..., description="Underlying Index")
    status: str = Field(default="PENDING", description="PENDING, IN_PROGRESS, FULLY_FILLED, PARTIALLY_FILLED, FAILED, ABORTED_CIRCUIT_BREAKER, ROLLED_BACK")
    total_legs: int = Field(..., ge=1, description="Total legs in sequence")
    completed_legs: int = Field(default=0, ge=0, description="Count of successfully filled legs")
    failed_legs: int = Field(default=0, ge=0, description="Count of failed or rejected legs")
    circuit_breaker_triggered: bool = Field(default=False, description="True if circuit breaker halted downstream legs")
    leg_states: List[LegExecutionState] = Field(default_factory=list, description="State of each leg in sequence")
    error_summary: Optional[str] = Field(default=None, description="Consolidated error description")
    execution_start_time: datetime = Field(default_factory=datetime.utcnow, description="Workflow start time")
    execution_end_time: Optional[datetime] = Field(default=None, description="Workflow completion timestamp")


class RollbackReport(BaseModel):
    """
    Audit log generated when circuit-breaker rolls back or cancels partially filled legs.
    """
    model_config = ConfigDict(extra="ignore")

    sequence_id: str = Field(..., description="Sequence ID that triggered rollback")
    signal_id: str = Field(..., description="Signal ID")
    correlation_id: str = Field(..., description="Correlation ID")
    reason: str = Field(..., description="Reason for rollback execution")
    rolled_back_legs: List[LegExecutionState] = Field(default_factory=list, description="Legs squared off or cancelled")
    status: str = Field(default="ROLLED_BACK", description="Rollback state")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PositionStateModel(BaseModel):
    """
    Live aggregated portfolio position and Greeks contract for Phase 3 dashboard.
    """
    model_config = ConfigDict(extra="ignore")

    position_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Position tracker identifier")
    strategy_name: str = Field(..., description="Strategy name")
    underlying: UnderlyingIndex = Field(..., description="Underlying index")
    legs: List[LegOrderRequest] = Field(default_factory=list, description="Currently active option legs")
    net_delta: float = Field(default=0.0, description="Portfolio aggregate delta")
    net_gamma: float = Field(default=0.0, description="Portfolio aggregate gamma")
    net_theta: float = Field(default=0.0, description="Portfolio aggregate theta")
    net_vega: float = Field(default=0.0, description="Portfolio aggregate vega")
    unrealized_pnl: float = Field(default=0.0, description="Current mark-to-market unrealized PnL")
    realized_pnl: float = Field(default=0.0, description="Realized PnL from closed legs")
    total_pnl: float = Field(default=0.0, description="Total cumulative PnL")
    margin_utilized: float = Field(default=0.0, description="Estimated margin deployed")
    is_active: bool = Field(default=True, description="True if position is currently open")
    entry_time: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SyntheticTickPayload(BaseModel):
    """
    Real-time market tick contract emitted by the synthetic feed or data replayer.
    """
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., description="Symbol (e.g. NIFTY_SPOT, NIFTY26AUG24200CE)")
    underlying: UnderlyingIndex = Field(..., description="Underlying Index")
    spot_price: float = Field(..., gt=0, description="Current underlying spot index price")
    ltp: float = Field(..., ge=0, description="Last traded price")
    bid: float = Field(default=0.0, ge=0.0, description="Best bid price")
    ask: float = Field(default=0.0, ge=0.0, description="Best ask price")
    open_interest: int = Field(default=0, ge=0, description="Open interest")
    volume: int = Field(default=0, ge=0, description="Traded volume")
    iv: float = Field(default=0.0, ge=0.0, description="Implied volatility decimal")
    greeks: Optional[Greeks] = Field(default=None, description="Black-Scholes Greeks")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Tick generation timestamp")


class ExecutionEventMessage(BaseModel):
    """
    Envelope schema for WebSocket broadcasts to downstream consumers (Phase 3 Dashboard).
    """
    model_config = ConfigDict(extra="ignore")

    event_type: WebSocketEventType = Field(..., description="Category of event")
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Trace correlation ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event emission timestamp")
    data: Dict[str, Any] = Field(default_factory=dict, description="Event payload contents")
