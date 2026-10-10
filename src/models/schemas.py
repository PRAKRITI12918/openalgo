"""
Comprehensive Pydantic V2 schemas and data contracts for the Phase 2 Execution Engine.
Defines strict validation rules for signal ingestion, multi-leg sequencing, order lifecycle,
and real-time WebSocket state streaming to Phase 3.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar
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
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    PARTIAL = "PARTIAL"
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
    validity_seconds: Optional[int] = Field(default=300, description="Validity window in seconds before signal expires; default 5 mins")
    requires_approval: bool = Field(default=False, description="If True, routes to pending queue instead of immediate execution")
    reason: str = Field(default="", description="Algorithmic rationale for signal generation")
    account_id: Optional[str] = Field(default=None, description="Optional target broker account ID")
    user_id: Optional[str] = Field(default=None, description="Optional user ID for multi-account scoping")
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
    account_id: Optional[str] = Field(default=None, description="Broker account ID used for execution")
    user_id: Optional[str] = Field(default=None, description="Owner user ID")
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


# -----------------------------------------------------------------------------
# API Foundation Standardized Response Contracts
# -----------------------------------------------------------------------------

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Standardized consistent JSON response envelope for API endpoints.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=True, description="Indicates whether the request succeeded")
    data: Optional[T] = Field(default=None, description="Primary response payload")
    message: Optional[str] = Field(default=None, description="Human-readable informational or error message")
    error: Optional[str] = Field(default=None, description="Specific error category or detail when success=False")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response generation timestamp")


class HealthLivenessResponse(BaseModel):
    """
    Dependency-free system liveness contract for container probes and monitoring.
    """
    model_config = ConfigDict(extra="ignore")

    status: str = Field(default="healthy", description="Service liveness state")
    service: str = Field(default="openalgo-execution-engine", description="Service identifier")
    version: str = Field(default="2.0.0", description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Liveness check timestamp")
    environment: str = Field(default="development", description="Runtime environment")


class StrategyDefinitionModel(BaseModel):
    """
    Metadata specification for a supported quantitative options strategy structure.
    """
    model_config = ConfigDict(extra="ignore")

    strategy_type: StrategyType = Field(..., description="Unique strategy type identifier")
    name: str = Field(..., description="Human-readable strategy name")
    description: str = Field(..., description="Strategy mechanics and objectives")
    legs_count: int = Field(..., ge=1, description="Standard number of option legs in structure")
    favorable_regimes: List[MarketRegime] = Field(default_factory=list, description="Optimal market volatility regimes")
    risk_profile: str = Field(..., description="Defined Risk vs Undefined Risk")
    directionality: str = Field(..., description="NEUTRAL, BULLISH, BEARISH")
    default_product: str = Field(default="MIS", description="Default order product (MIS, NRML)")


class StrategyListResponse(BaseModel):
    """
    Standard response payload for listing supported quantitative strategies.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=True, description="Request success indicator")
    count: int = Field(..., ge=0, description="Number of available strategies")
    strategies: List[StrategyDefinitionModel] = Field(default_factory=list, description="Supported strategy definitions")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


# -----------------------------------------------------------------------------
# Pending Trade Signal Approval Queue Schemas
# -----------------------------------------------------------------------------

class PendingSignalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVING = "APPROVING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class PendingSignalSummary(BaseModel):
    """
    Summary view of a pending trade signal formatted for trader dashboard and action queues.
    """
    model_config = ConfigDict(extra="ignore")

    signal_id: str = Field(..., description="Unique trade signal identifier")
    correlation_id: str = Field(..., description="Trace correlation ID")
    strategy_name: str = Field(..., description="Strategy name")
    underlying: str = Field(..., description="Target underlying asset/index")
    signal_type: str = Field(..., description="ENTRY, EXIT, STOP_LOSS, etc.")
    status: str = Field(..., description="PENDING, APPROVING, APPROVED, REJECTED, EXPIRED, FAILED")
    action: str = Field(..., description="Primary action or multi-leg overview (e.g. BUY/SELL, CONDOR)")
    quantity: int = Field(..., description="Aggregate or primary unit quantity")
    order_type: str = Field(..., description="MARKET, LIMIT, SL")
    price: float = Field(default=0.0, description="Price limit or benchmark")
    legs_count: int = Field(..., ge=1, description="Total legs in strategy")
    entry_credit_debit: float = Field(default=0.0, description="Expected net credit (+ve) or debit (-ve)")
    margin_estimate: float = Field(default=0.0, description="Estimated margin utilization if available")
    created_at: datetime = Field(..., description="Signal receipt timestamp")
    expires_at: Optional[datetime] = Field(default=None, description="Signal validity expiration timestamp")
    time_remaining_seconds: Optional[int] = Field(default=None, description="Seconds until expiry (negative if expired)")
    is_expired: bool = Field(default=False, description="True if signal has exceeded validity TTL or contract date")
    user_id: Optional[str] = Field(default=None, description="User identifier owning the signal")
    approved_at: Optional[datetime] = Field(default=None, description="Approval timestamp")
    approved_by: Optional[str] = Field(default=None, description="User identifier who approved signal")
    rejected_at: Optional[datetime] = Field(default=None, description="Rejection timestamp")
    rejected_by: Optional[str] = Field(default=None, description="User identifier who rejected signal")
    actor: Optional[str] = Field(default=None, description="User or system entity acting on signal")
    rejection_reason: Optional[str] = Field(default=None, description="Reason if rejected")
    sequence_id: Optional[str] = Field(default=None, description="Execution sequence run ID if executed")
    error_message: Optional[str] = Field(default=None, description="Error reason if execution failed")
    status_history: List[Dict[str, Any]] = Field(default_factory=list, description="Immutable audit trail of status transitions")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Full raw signal payload")


class PendingSignalListResponse(BaseModel):
    """
    API response contract for listing pending trade signals.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=True, description="Request success indicator")
    count: int = Field(..., ge=0, description="Total pending signals returned")
    signals: List[PendingSignalSummary] = Field(default_factory=list, description="Array of pending signals")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class SignalApprovalRequest(BaseModel):
    """
    Request body for approving a pending trade signal.
    """
    model_config = ConfigDict(extra="ignore")

    actor: Optional[str] = Field(default="dashboard-trader", description="Trader identifier approving execution")


class SignalApprovalResponse(BaseModel):
    """
    Response returned when a pending signal is approved and executed.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=True, description="Approval operation success indicator")
    signal_id: str = Field(..., description="Approved signal ID")
    status: str = Field(..., description="Terminal status, typically APPROVED or EXECUTED")
    sequence_id: Optional[str] = Field(default=None, description="Downstream execution sequence run ID")
    approved_at: Optional[datetime] = Field(default=None, description="Approval timestamp")
    approved_by: Optional[str] = Field(default=None, description="User ID who approved the signal")
    message: str = Field(default="Signal successfully approved and executed through sequential pipeline", description="Informational message")
    sequence: Optional[Dict[str, Any]] = Field(default=None, description="Full execution sequence details")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")


class SignalRejectionRequest(BaseModel):
    """
    Request body for rejecting a pending trade signal.
    """
    model_config = ConfigDict(extra="ignore")

    reason: Optional[str] = Field(default="Manual rejection from trader dashboard", description="Rejection rationale")
    actor: Optional[str] = Field(default="dashboard-trader", description="Trader identifier rejecting signal")


class SignalRejectionResponse(BaseModel):
    """
    Response returned when a pending signal is rejected.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(default=True, description="Rejection operation success indicator")
    signal_id: str = Field(..., description="Rejected signal ID")
    status: str = Field(default="REJECTED", description="Terminal state")
    reason: Optional[str] = Field(default=None, description="Archived rejection reason")
    rejected_at: datetime = Field(default_factory=datetime.utcnow, description="Rejection timestamp")
    rejected_by: Optional[str] = Field(default=None, description="User ID who rejected the signal")
    actor: Optional[str] = Field(default="dashboard-trader", description="Audit actor")
    message: str = Field(default="Signal rejected and archived without execution", description="Status message")


class LegProgressState(BaseModel):
    """Per-leg execution progress information."""
    model_config = ConfigDict(extra="ignore")

    leg_id: str = Field(..., description="Leg identifier")
    symbol: str = Field(..., description="Symbol")
    action: str = Field(..., description="BUY or SELL")
    status: str = Field(..., description="PENDING, OPEN, FILLED, REJECTED, CANCELLED, FAILED")
    order_id: Optional[str] = Field(default=None, description="Broker order ID")
    strike: float = Field(default=0.0, description="Strike price")
    quantity: int = Field(default=0, description="Order quantity")
    filled_quantity: int = Field(default=0, description="Filled quantity")
    requested_price: float = Field(default=0.0, description="Requested price")
    execution_price: float = Field(default=0.0, description="Average executed price")
    placed_at: Optional[str] = Field(default=None, description="Placed timestamp")
    updated_at: Optional[str] = Field(default=None, description="Updated timestamp")
    error_message: Optional[str] = Field(default=None, description="Error message if leg failed")


class SignalProgressResponse(BaseModel):
    """Execution progress details for polling/subscription."""
    model_config = ConfigDict(extra="ignore")

    signal_id: str = Field(..., description="Signal identifier")
    status: str = Field(..., description="Overall signal status")
    sequence_id: Optional[str] = Field(default=None, description="Execution sequence ID")
    strategy_name: Optional[str] = Field(default=None, description="Strategy name")
    underlying: Optional[str] = Field(default=None, description="Underlying")
    user_id: Optional[str] = Field(default=None, description="Owner user ID")
    approved_at: Optional[str] = Field(default=None, description="Approval timestamp")
    approved_by: Optional[str] = Field(default=None, description="Approved by user ID")
    rejected_at: Optional[str] = Field(default=None, description="Rejection timestamp")
    rejected_by: Optional[str] = Field(default=None, description="Rejected by user ID")
    rejection_reason: Optional[str] = Field(default=None, description="Rejection reason")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")
    legs: List[LegProgressState] = Field(default_factory=list, description="Per-leg execution progress")
    status_history: List[Dict[str, Any]] = Field(default_factory=list, description="Immutable status transition history")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="Execution event stream")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

