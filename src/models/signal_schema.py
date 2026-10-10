"""
Strict Pydantic V2 Domain Models and Validation Schema for Phase 2 Signal Ingestion.
Ensures rigorous validation of trading signals, idempotency contracts,
lot size multiples, price-trigger directionality, and contiguous leg sequencing.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalInstrumentType(str, Enum):
    FUTURE = "FUTURE"
    OPTION = "OPTION"
    EQUITY = "EQUITY"


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SignalOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class SignalOptionType(str, Enum):
    CE = "CE"
    PE = "PE"


class SignalStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Known lot sizes for Indian index and stock derivatives
KNOWN_LOT_SIZES: Dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
    "SENSEX": 10,
    "BANKEX": 15,
}


def validate_lot_size(underlying: str, instrument: SignalInstrumentType, quantity: int) -> None:
    """Validates that derivative quantities are multiples of known lot sizes."""
    if instrument in (SignalInstrumentType.FUTURE, SignalInstrumentType.OPTION):
        u_clean = underlying.strip().upper()
        if u_clean in KNOWN_LOT_SIZES:
            lot_size = KNOWN_LOT_SIZES[u_clean]
            if quantity % lot_size != 0:
                raise ValueError(
                    f"Quantity {quantity} must be a multiple of lot size ({lot_size}) for {u_clean} {instrument.value}"
                )


def validate_prices_and_direction(
    order_type: SignalOrderType,
    action: SignalAction,
    price: Optional[float],
    trigger_price: Optional[float],
) -> None:
    """
    Validates price and trigger_price requirements and directional consistency.
    - LIMIT orders require price > 0.
    - SL orders require both price > 0 and trigger_price > 0.
    - SL-M orders require trigger_price > 0.
    - For BUY SL orders, limit price must be >= trigger_price.
    - For SELL SL orders, limit price must be <= trigger_price.
    """
    if order_type in (SignalOrderType.LIMIT, SignalOrderType.SL):
        if price is None or price <= 0:
            raise ValueError(f"Price is required and must be > 0 for {order_type.value} orders")

    if order_type in (SignalOrderType.SL, SignalOrderType.SL_M):
        if trigger_price is None or trigger_price <= 0:
            raise ValueError(f"Trigger price is required and must be > 0 for {order_type.value} orders")

    # Validate directional consistency for SL orders
    if order_type == SignalOrderType.SL and price is not None and trigger_price is not None:
        if action == SignalAction.BUY and price < trigger_price:
            raise ValueError(
                f"Invalid trigger direction for BUY SL order: limit price ({price}) must be >= trigger_price ({trigger_price})"
            )
        elif action == SignalAction.SELL and price > trigger_price:
            raise ValueError(
                f"Invalid trigger direction for SELL SL order: limit price ({price}) must be <= trigger_price ({trigger_price})"
            )


class SignalLegPayload(BaseModel):
    """
    Individual leg specification within a multi-leg strategy signal.
    """
    model_config = ConfigDict(extra="forbid")

    leg_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for this leg")
    underlying: Optional[str] = Field(default=None, min_length=1, max_length=50, description="Leg underlying if different from root")
    instrument: Optional[SignalInstrumentType] = Field(default=None, description="Leg instrument type")
    action: SignalAction = Field(..., description="Trade action: BUY or SELL")
    quantity: int = Field(..., gt=0, description="Order quantity (must be > 0 and lot size multiple if applicable)")
    order_type: SignalOrderType = Field(default=SignalOrderType.MARKET, description="Order type: MARKET, LIMIT, SL, SL-M")
    price: Optional[float] = Field(default=None, description="Limit price for LIMIT / SL orders")
    trigger_price: Optional[float] = Field(default=None, description="Trigger price for SL / SL-M orders")
    execution_sequence: int = Field(..., ge=1, description="Relative execution order within the strategy (>= 1)")

    # Option-specific details
    strike: Optional[float] = Field(default=None, gt=0, description="Option strike price")
    expiry: Optional[str] = Field(default=None, min_length=8, description="Option expiry date (YYYY-MM-DD)")
    option_type: Optional[SignalOptionType] = Field(default=None, description="Option type: CE or PE")

    # Dependency and role attributes for execution sequencing & hedge-before-short ordering
    leg_role: Optional[str] = Field(default=None, description="Leg role: HEDGE or PRIMARY")
    depends_on_leg_id: Optional[str] = Field(default=None, description="ID of prerequisite leg that must be FILLED first")
    is_optional: bool = Field(default=False, description="If True, failure of this leg does not fail the entire strategy signal")

    @model_validator(mode="after")
    def validate_leg(self) -> "SignalLegPayload":
        validate_prices_and_direction(self.order_type, self.action, self.price, self.trigger_price)
        if self.instrument == SignalInstrumentType.OPTION:
            if self.strike is None or self.strike <= 0:
                raise ValueError("Strike price is required and must be > 0 for OPTION legs")
            if not self.expiry:
                raise ValueError("Expiry date is required for OPTION legs")
            if self.option_type is None:
                raise ValueError("Option type (CE or PE) is required for OPTION legs")
        return self


class SignalIngestPayload(BaseModel):
    """
    Strict Signal Ingestion Payload received from external strategy engines.
    """
    model_config = ConfigDict(extra="forbid")

    strategy_name: str = Field(..., min_length=1, max_length=100, description="Strategy name identifier")
    underlying: str = Field(..., min_length=1, max_length=50, description="Underlying asset (e.g. NIFTY, RELIANCE)")
    instrument: SignalInstrumentType = Field(..., description="Instrument category: FUTURE, OPTION, EQUITY")
    action: SignalAction = Field(..., description="Trade action: BUY or SELL")
    quantity: int = Field(..., gt=0, description="Order quantity (must be > 0 and lot size multiple if applicable)")
    order_type: SignalOrderType = Field(default=SignalOrderType.MARKET, description="Order type: MARKET, LIMIT, SL, SL-M")
    price: Optional[float] = Field(default=None, description="Price for LIMIT / SL orders")
    trigger_price: Optional[float] = Field(default=None, description="Trigger price for SL / SL-M orders")
    execution_sequence: int = Field(default=1, ge=1, description="Execution priority sequence (>= 1)")

    # Option-specific details for single-leg signals
    strike: Optional[float] = Field(default=None, gt=0, description="Option strike price if instrument is OPTION")
    expiry: Optional[str] = Field(default=None, min_length=8, description="Option expiry date (YYYY-MM-DD) if instrument is OPTION")
    option_type: Optional[SignalOptionType] = Field(default=None, description="Option type (CE/PE) if instrument is OPTION")

    # Dependency and role attributes for single-leg signals
    leg_role: Optional[str] = Field(default=None, description="Leg role: HEDGE or PRIMARY")
    depends_on_leg_id: Optional[str] = Field(default=None, description="ID of prerequisite leg")
    is_optional: bool = Field(default=False, description="If True, failure of this leg does not fail the entire strategy signal")

    # Multi-leg array
    legs: Optional[List[SignalLegPayload]] = Field(default=None, description="Legs array for multi-leg strategies")

    # Timestamp & Idempotency
    signal_timestamp: datetime = Field(..., description="Signal generation timestamp in ISO8601 format")
    idempotency_key: Optional[str] = Field(default=None, description="Unique idempotency key for deduplication")
    client_signal_id: Optional[str] = Field(default=None, description="Client signal ID (alias for idempotency_key)")

    # Free-form metadata capped at 5KB
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata object (capped at 5KB serialized)")

    @model_validator(mode="after")
    def validate_payload(self) -> "SignalIngestPayload":
        # 1. Enforce idempotency key presence
        effective_key = self.idempotency_key or self.client_signal_id
        if not effective_key or not str(effective_key).strip():
            raise ValueError("Either 'idempotency_key' or 'client_signal_id' is required and must be non-empty")
        object.__setattr__(self, "idempotency_key", str(effective_key).strip())

        # 2. Enforce 5KB serialized size cap on metadata
        if self.metadata is not None:
            serialized_meta = json.dumps(self.metadata)
            if len(serialized_meta.encode("utf-8")) > 5120:
                raise ValueError(
                    f"Metadata serialized size ({len(serialized_meta.encode('utf-8'))} bytes) exceeds maximum limit of 5KB (5120 bytes)"
                )

        # 3. Validation for Single-Leg vs Multi-Leg
        if not self.legs:
            # Single-leg validation
            validate_lot_size(self.underlying, self.instrument, self.quantity)
            validate_prices_and_direction(self.order_type, self.action, self.price, self.trigger_price)
            if self.instrument == SignalInstrumentType.OPTION:
                if self.strike is None or self.strike <= 0:
                    raise ValueError("Strike price is required and must be > 0 for single-leg OPTION signals")
                if not self.expiry:
                    raise ValueError("Expiry date is required for single-leg OPTION signals")
                if self.option_type is None:
                    raise ValueError("Option type (CE or PE) is required for single-leg OPTION signals")
        else:
            # Multi-leg validation
            if len(self.legs) == 0:
                raise ValueError("Legs list cannot be empty when provided")

            # Check uniqueness and contiguity of execution sequences
            seqs = [leg.execution_sequence for leg in self.legs]
            if len(seqs) != len(set(seqs)):
                raise ValueError(f"Execution sequences across legs must be unique; duplicate sequence found: {seqs}")
            expected_seqs = list(range(1, len(self.legs) + 1))
            if sorted(seqs) != expected_seqs:
                raise ValueError(
                    f"Execution sequences across legs must be contiguous starting from 1; expected {expected_seqs}, got {sorted(seqs)}"
                )

            # Validate each leg
            for idx, leg in enumerate(self.legs):
                effective_underlying = leg.underlying or self.underlying
                effective_instrument = leg.instrument or self.instrument
                validate_lot_size(effective_underlying, effective_instrument, leg.quantity)
                if effective_instrument == SignalInstrumentType.OPTION:
                    if leg.strike is None or leg.strike <= 0:
                        raise ValueError(f"Leg index {idx} ({leg.leg_id}): Strike price is required for OPTION legs")
                    if not leg.expiry:
                        raise ValueError(f"Leg index {idx} ({leg.leg_id}): Expiry date is required for OPTION legs")
                    if leg.option_type is None:
                        raise ValueError(f"Leg index {idx} ({leg.leg_id}): Option type (CE/PE) is required for OPTION legs")

        return self


class SignalTransitionRequest(BaseModel):
    """
    Request payload to transition a signal to a new status.
    """
    target_status: SignalStatus = Field(..., description="Target status enum")
    reason: Optional[str] = Field(default="Status transition requested", description="Audit reason for transition")
    actor: Optional[str] = Field(default="system", description="Actor initiating the transition")


class SignalResponse(BaseModel):
    """
    Immediate response payload returned upon signal ingestion.
    """
    signal_id: str
    status: SignalStatus
    received_at: str
    is_duplicate: bool = False
    message: Optional[str] = None


class SignalAuditEntry(BaseModel):
    """
    Audit log entry recording an individual status change.
    """
    status: str
    timestamp: str
    actor: str
    reason: str


class SignalDetailResponse(BaseModel):
    """
    Detailed query response for a single signal including full status history.
    """
    signal_id: str
    idempotency_key: str
    strategy_name: str
    underlying: str
    instrument: str
    action: str
    quantity: int
    order_type: str
    price: Optional[float]
    trigger_price: Optional[float]
    execution_sequence: int
    status: str
    legs: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    status_history: List[SignalAuditEntry] = Field(default_factory=list)
    created_at: str
    updated_at: str


class SignalListResponse(BaseModel):
    """
    Paginated/filtered list response for signals.
    """
    success: bool = True
    count: int
    signals: List[SignalDetailResponse]


# =============================================================================
# Mock Execution Engine Models & Statuses (STRICTLY SIMULATED)
# =============================================================================

class MockOrderStatus(str, Enum):
    """Order lifecycle states for simulated leg orders."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class MockLegExecutionResult(BaseModel):
    """Execution state and fill metrics for an individual simulated leg."""
    model_config = ConfigDict(extra="ignore")

    leg_id: str
    order_id: str
    execution_sequence: int
    status: MockOrderStatus
    action: SignalAction
    requested_quantity: int
    filled_quantity: int
    requested_price: Optional[float] = None
    fill_price: Optional[float] = None
    realized_pnl: float = 0.0
    failure_reason: Optional[str] = None
    is_mock: bool = True
    created_at: str
    executed_at: Optional[str] = None


class PositionSnapshot(BaseModel):
    """Point-in-time state of an underlying position tracker."""
    model_config = ConfigDict(extra="ignore")

    symbol: str
    underlying: str
    instrument: str
    net_quantity: int
    average_price: float
    realized_pnl: float
    unrealized_pnl: float
    mark_price: float
    is_open: bool
    updated_at: str


class MockSignalExecutionResult(BaseModel):
    """Aggregated execution report for a simulated strategy signal."""
    model_config = ConfigDict(extra="ignore")

    signal_id: str
    strategy_name: str
    status: SignalStatus
    total_legs: int
    filled_legs: int
    failed_legs: int
    cancelled_legs: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    leg_executions: List[MockLegExecutionResult]
    positions: List[PositionSnapshot]
    is_mock: bool = True
    executed_at: str

