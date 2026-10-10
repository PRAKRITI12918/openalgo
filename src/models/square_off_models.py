"""
Square-Off Emergency Risk-Control Schemas.
Pydantic contracts for two-step confirmation, per-order independence, and audit trails.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class SquareOffPrepareRequest(BaseModel):
    """Payload to prepare an emergency square-off and request a single-use token."""
    model_config = ConfigDict(extra="ignore")

    selected_account_id: Optional[str] = Field(
        default=None,
        description="The account ID currently selected in the UI. Checked against server-trusted active account.",
    )


class SquareOffPrepareResponse(BaseModel):
    """Live snapshot of positions to be closed and single-use confirmation token."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(default="prepared", description="Preparation status")
    confirmation_token: str = Field(description="Short-lived, single-use confirmation token (TTL: 60s)")
    expires_in_seconds: int = Field(default=60, description="Token validity window in seconds")
    account_id: Optional[str] = Field(default=None, description="Resolved server-trusted active account ID")
    account_label: str = Field(default="", description="Human-readable label for account")
    broker_name: str = Field(default="", description="Broker provider ID")
    total_positions: int = Field(default=0, description="Count of open positions to close")
    open_positions: List[Dict[str, Any]] = Field(default_factory=list, description="Live positions snapshot")
    confirm_phrase: str = Field(default="CONFIRM", description="Phrase trader must submit to confirm execution")


class SquareOffExecuteRequest(BaseModel):
    """Payload to execute emergency square-off with confirmation token."""
    model_config = ConfigDict(extra="ignore")

    confirmation_token: str = Field(description="Single-use confirmation token obtained from /prepare")
    confirm_phrase: str = Field(description="Explicit confirmation phrase: 'CONFIRM' or 'CLOSE ALL'")
    selected_account_id: Optional[str] = Field(
        default=None,
        description="The account ID currently selected in the UI. Checked against server-trusted active account.",
    )


class SquareOffOrderResult(BaseModel):
    """Per-symbol outcome of an emergency exit order."""
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(description="Trading instrument symbol")
    action: str = Field(description="Exit order action (BUY or SELL)")
    requested_quantity: int = Field(description="Target exit quantity")
    filled_quantity: int = Field(default=0, description="Confirmed executed fill quantity")
    avg_price: float = Field(default=0.0, description="Execution fill price")
    status: str = Field(description="Outcome status: FILLED, PARTIAL, or FAILED")
    order_id: Optional[str] = Field(default=None, description="Broker assigned order ID")
    error: Optional[str] = Field(default=None, description="Error message if order was rejected or failed")


class SquareOffExecuteResponse(BaseModel):
    """Final summary of the emergency square-off execution."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(description="Overall execution status: success, partial_success, failed, or no_op")
    message: str = Field(description="Human-readable summary message")
    square_off_id: str = Field(description="Unique correlation ID for this square-off batch")
    account_id: Optional[str] = Field(default=None, description="Target account ID")
    account_label: str = Field(default="", description="Target account label")
    total_positions: int = Field(default=0, description="Total positions processed")
    filled_count: int = Field(default=0, description="Number of positions fully filled")
    partial_count: int = Field(default=0, description="Number of positions partially filled")
    failed_count: int = Field(default=0, description="Number of positions failed")
    results: List[SquareOffOrderResult] = Field(default_factory=list, description="Per-order breakdown")
    audit_id: str = Field(description="Durable audit trail record identifier")


class SquareOffAuditItem(BaseModel):
    """Audit entry representation."""
    model_config = ConfigDict(extra="ignore")

    audit_id: str
    square_off_id: str
    account_id: Optional[str] = None
    user_id: str
    action_type: str
    status: str
    total_positions: int
    filled_positions: int
    partial_positions: int
    failed_positions: int
    orders: List[Dict[str, Any]] = Field(default_factory=list)
    error_summary: Optional[str] = None
    created_at: str
