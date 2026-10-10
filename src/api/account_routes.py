"""
REST API Routes for Multi-Account Broker Management.
Handles connecting, listing, switching (with open-positions confirmation gate),
and disconnecting broker accounts.

HARD CONSTRAINTS:
- Server-side authorization check FIRST on all endpoints.
- User identity is ALWAYS extracted from authenticated session/header, never request body.
- Display-safe masked account metadata only — NEVER expose raw credentials or tokens.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
import structlog

from src.adapters.base import BaseBrokerAdapter
from src.database.account_models import BrokerAccountStatus
from src.services.account_service import (
    connect_broker_account,
    disconnect_account,
    get_active_account_selection,
    list_user_accounts,
    mark_account_token_expired,
    resolve_authenticated_user,
    switch_active_account,
    verify_account_ownership,
)

logger = structlog.get_logger("openalgo.account_api")

account_router = APIRouter(prefix="/api/v1/accounts", tags=["Broker Accounts"])


# -----------------------------------------------------------------------------
# Request & Response Contracts
# -----------------------------------------------------------------------------

class AccountConnectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    broker_id: str = Field(..., description="Broker identifier (e.g. 'dhan', 'zerodha', 'mock')")
    account_label: str = Field(..., description="User-defined account nickname (e.g. 'Main Dhan', 'Account B')")
    credentials: Dict[str, Any] = Field(default_factory=dict, description="Broker-specific credentials per schema")
    make_active: bool = Field(default=False, description="Whether to activate immediately after connecting")


class AccountActivateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    confirm: bool = Field(default=False, description="Explicit confirmation if active account has open positions")


class AccountDisplayModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_id: str
    broker_id: str
    broker_display_name: str
    account_label: str
    masked_external_id: str
    status: str
    is_active: bool
    connected_at: str
    last_verified_at: str


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------

@account_router.post(
    "/connect",
    response_model=AccountDisplayModel,
    status_code=status.HTTP_201_CREATED,
    summary="Connect New Broker Account",
    description="Authenticates against broker upstream and saves a new BrokerAccount row for the requesting user.",
)
async def connect_account_endpoint(
    body: AccountConnectRequest,
    request: Request,
) -> AccountDisplayModel:
    user_id = resolve_authenticated_user(request)
    result = await connect_broker_account(
        user_id=user_id,
        broker_id=body.broker_id,
        account_label=body.account_label,
        credentials=body.credentials,
        make_active=body.make_active,
    )
    return AccountDisplayModel(**result)


@account_router.get(
    "",
    response_model=List[AccountDisplayModel],
    status_code=status.HTTP_200_OK,
    summary="List Connected Broker Accounts",
    description="Returns all accounts owned by the authenticated requesting user, with the active account marked.",
)
async def list_accounts_endpoint(
    request: Request,
) -> List[AccountDisplayModel]:
    user_id = resolve_authenticated_user(request)
    accounts = list_user_accounts(user_id)
    return [AccountDisplayModel(**acc) for acc in accounts]


@account_router.get(
    "/active",
    response_model=Optional[AccountDisplayModel],
    status_code=status.HTTP_200_OK,
    summary="Get Currently Active Broker Account",
)
async def get_active_account_endpoint(
    request: Request,
) -> Optional[AccountDisplayModel]:
    user_id = resolve_authenticated_user(request)
    active = get_active_account_selection(user_id)
    if not active:
        return None
    return AccountDisplayModel(**active.to_display_dict(is_active=True))


@account_router.post(
    "/{account_id}/activate",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Switch Active Broker Account",
    description="Activates the specified account. If current active account has open positions, requires confirmation.",
)
async def activate_account_endpoint(
    account_id: str,
    request: Request,
    body: Optional[AccountActivateRequest] = None,
    confirm: bool = Query(default=False, description="Confirmation flag if open positions exist"),
) -> Dict[str, Any]:
    user_id = resolve_authenticated_user(request)
    effective_confirm = confirm or (body.confirm if body else False)

    # Helper to check open positions via the app's broker adapter or DB
    async def _check_positions(acc_id: str):
        # Query positions for the current active account
        if hasattr(request.app.state, "broker_adapter"):
            adapter: BaseBrokerAdapter = request.app.state.broker_adapter
            if hasattr(adapter, "get_positions_for_account"):
                return await adapter.get_positions_for_account(acc_id)
            elif hasattr(adapter, "get_positions"):
                return await adapter.get_positions()
        return []

    result = await switch_active_account(
        user_id=user_id,
        account_id=account_id,
        confirm=effective_confirm,
        open_positions_checker=_check_positions,
    )

    if result.get("requires_confirmation"):
        # Return 409 Conflict if confirmation is required and not yet provided
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result,
        )

    return result


@account_router.post(
    "/{account_id}/disconnect",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Disconnect Broker Account",
    description="Disconnects account and marks status DISCONNECTED. Clears active pointer if it was the active account.",
)
async def disconnect_account_endpoint(
    account_id: str,
    request: Request,
) -> Dict[str, Any]:
    user_id = resolve_authenticated_user(request)
    return await disconnect_account(user_id=user_id, account_id=account_id)


@account_router.post(
    "/{account_id}/simulate-token-expiry",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Simulate Token Expiration (Test Utility)",
)
async def simulate_token_expiry_endpoint(
    account_id: str,
    request: Request,
) -> Dict[str, Any]:
    user_id = resolve_authenticated_user(request)
    mark_account_token_expired(user_id, account_id)
    return {
        "status": "success",
        "message": f"Account '{account_id}' status transitioned to {BrokerAccountStatus.TOKEN_EXPIRED.value}",
        "account_id": account_id,
        "new_status": BrokerAccountStatus.TOKEN_EXPIRED.value,
    }
