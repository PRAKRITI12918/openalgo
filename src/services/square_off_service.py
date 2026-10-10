"""
Emergency Risk-Control Service: "Square-Off All"
Immediately liquidates every open position on the user's active trading account.

SAFETY & DESIGN GUARANTEES:
1. Account verification happens FIRST: Selected account checked against server-trusted active account
   before ANY I/O or position fetching. On mismatch: blocked, audited, 400 error.
2. Two-step confirmation with short-lived, single-use token (TTL: 60s).
3. Concurrent execution lock per account: rejects concurrent/duplicate requests with 409 Conflict.
4. Per-order independence: batch treated as N independent state machines; one order failure never aborts others.
5. Confirmed-fill-only state updates: full fill closes, partial fill reduces, failure leaves untouched.
6. Durable pre- and post-execution audit trail for every action (prepared, executed, blocked, failed).
"""

from __future__ import annotations

import asyncio
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import HTTPException, status
import structlog

from src.adapters.base import BaseBrokerAdapter
from src.database.account_models import BrokerAccount, BrokerAccountStatus
from src.database.execution_db import (
    MockPositionRecord,
    db_session,
    get_square_off_audits,
    record_square_off_audit,
)
from src.models.schemas import LegOrderRequest, OrderAction, OrderStatus
from src.services.account_service import get_active_account_selection

logger = structlog.get_logger("openalgo.square_off_service")


@dataclass
class SquareOffToken:
    """Internal representation of a single-use confirmation token."""
    token: str
    user_id: str
    account_id: Optional[str]
    created_at: float
    expires_at: float
    consumed: bool = False
    open_positions: List[Dict[str, Any]] = field(default_factory=list)


class SquareOffService:
    """
    Emergency Risk-Control Orchestrator for Square-Off All feature.
    """

    def __init__(
        self,
        broker_adapter: Optional[BaseBrokerAdapter] = None,
        event_broadcaster: Optional[Any] = None,
    ):
        self.default_broker = broker_adapter
        self.event_broadcaster = event_broadcaster
        self._lock = asyncio.Lock()
        self._tokens: Dict[str, SquareOffToken] = {}
        self._consumed_tokens: Set[str] = set()
        self._in_flight_accounts: Set[str] = set()
        self._progress_cache: Dict[str, Dict[str, Any]] = {}

    def _get_broker(self, injected_broker: Optional[BaseBrokerAdapter] = None) -> BaseBrokerAdapter:
        broker = injected_broker or self.default_broker
        if not broker:
            raise RuntimeError("No broker adapter configured for square-off service.")
        return broker

    def _cleanup_expired_tokens(self) -> None:
        """Purge stale confirmation tokens past their TTL."""
        now = time.time()
        expired = [t for t, tok in self._tokens.items() if now > tok.expires_at]
        for t in expired:
            self._tokens.pop(t, None)

    # -------------------------------------------------------------------------
    # STEP 1: PREPARE SQUARE-OFF
    # -------------------------------------------------------------------------

    async def prepare_square_off(
        self,
        user_id: str,
        selected_account_id: Optional[str] = None,
        broker_adapter: Optional[BaseBrokerAdapter] = None,
    ) -> Dict[str, Any]:
        """
        Step 1 of Two-Step Confirmation:
        - Verifies active account match FIRST before any I/O or position fetching.
        - Fetches live open positions for the active account (never stale/cached).
        - Generates a short-lived single-use confirmation token (TTL 60s).
        - Records durable pre-audit log.
        """
        broker = self._get_broker(broker_adapter)
        square_off_id = f"sq_{uuid.uuid4().hex[:12]}"

        # 1. Server-trusted active account resolution
        active_account = get_active_account_selection(user_id)
        has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None

        # 2. Strict Account Match Check FIRST (before any I/O or position fetch)
        if selected_account_id is not None:
            active_id = active_account.id if active_account else None
            if active_id != selected_account_id:
                error_msg = (
                    f"ACCOUNT_MISMATCH: UI selected account '{selected_account_id}' does not match "
                    f"server-trusted active account '{active_id}'. Operation blocked."
                )
                logger.warn("square_off_prepare_blocked_account_mismatch", error=error_msg, user_id=user_id)
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=selected_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_msg,
                )

        # 3. Validate Account Connection Status
        if has_accounts or bool(user_id and user_id != "default_user"):
            if not active_account:
                error_msg = f"NO_ACTIVE_ACCOUNT: No active broker account configured for user '{user_id}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=None,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            if active_account.status == BrokerAccountStatus.TOKEN_EXPIRED.value:
                error_msg = "TOKEN_EXPIRED: Active broker account token has expired. Reconnection required."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=active_account.id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg)

            if active_account.status != BrokerAccountStatus.CONNECTED.value:
                error_msg = f"ACTIVE_ACCOUNT_NOT_CONNECTED: Active account is in status '{active_account.status}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=active_account.id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

        target_account_id = active_account.id if active_account else None
        target_account_label = active_account.account_label if active_account else "GLOBAL"

        # 4. Check In-Flight Lock
        async with self._lock:
            if target_account_id and target_account_id in self._in_flight_accounts:
                error_msg = f"SQUARE_OFF_IN_PROGRESS: Square-off already executing for account '{target_account_label}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)

        # 5. Fetch Live Open Positions (Never Cached)
        positions = await broker.get_positions(account_id=target_account_id)
        open_positions: List[Dict[str, Any]] = []

        for port in positions:
            for leg in port.legs:
                if leg.quantity > 0:
                    exit_action = OrderAction.SELL.value if leg.action == OrderAction.BUY else OrderAction.BUY.value
                    open_positions.append({
                        "symbol": leg.symbol,
                        "current_action": leg.action.value,
                        "quantity": leg.quantity,
                        "exit_action": exit_action,
                        "exit_quantity": leg.quantity,
                        "order_type": "MARKET",
                        "underlying": leg.underlying.value if hasattr(leg.underlying, "value") else str(leg.underlying),
                        "strike": leg.strike,
                        "option_type": leg.option_type,
                        "expiry": leg.expiry,
                        "price": leg.price,
                    })

        # 6. Generate Single-Use Token (TTL: 60 seconds)
        token_str = f"sq_tok_{secrets.token_hex(16)}"
        now = time.time()
        token_obj = SquareOffToken(
            token=token_str,
            user_id=user_id,
            account_id=target_account_id,
            created_at=now,
            expires_at=now + 60.0,
            consumed=False,
            open_positions=open_positions,
        )

        async with self._lock:
            self._cleanup_expired_tokens()
            self._tokens[token_str] = token_obj

        # 7. Durable Pre-Audit Record
        audit_id = record_square_off_audit(
            square_off_id=square_off_id,
            user_id=user_id,
            account_id=target_account_id,
            action_type="PREPARE",
            status="PREPARED",
            total_positions=len(open_positions),
            orders=open_positions,
        )

        logger.info(
            "square_off_prepared",
            square_off_id=square_off_id,
            user_id=user_id,
            account_id=target_account_id,
            positions_count=len(open_positions),
            audit_id=audit_id,
        )

        return {
            "status": "prepared",
            "confirmation_token": token_str,
            "expires_in_seconds": 60,
            "account_id": target_account_id,
            "account_label": target_account_label,
            "broker_name": active_account.broker_id if active_account else "MOCK",
            "total_positions": len(open_positions),
            "open_positions": open_positions,
            "confirm_phrase": "CONFIRM",
            "audit_id": audit_id,
        }

    # -------------------------------------------------------------------------
    # STEP 2: EXECUTE SQUARE-OFF
    # -------------------------------------------------------------------------

    async def execute_square_off(
        self,
        user_id: str,
        confirmation_token: str,
        confirm_phrase: str,
        selected_account_id: Optional[str] = None,
        broker_adapter: Optional[BaseBrokerAdapter] = None,
    ) -> Dict[str, Any]:
        """
        Step 2 of Two-Step Confirmation:
        - Verifies account match FIRST.
        - Validates and consumes single-use confirmation token atomically.
        - Verifies confirmation phrase ('CONFIRM' or 'CLOSE ALL').
        - Acquires in-flight execution lock for the account (rejecting concurrent requests with 409).
        - Fetches live positions and executes exit orders with PER-ORDER INDEPENDENCE.
        - Updates position state only on confirmed fills.
        - Records durable post-audit trail.
        """
        broker = self._get_broker(broker_adapter)
        square_off_id = f"sq_{uuid.uuid4().hex[:12]}"

        # 1. Resolve Active Account
        active_account = get_active_account_selection(user_id)
        has_accounts = BrokerAccount.query.filter_by(user_id=user_id).first() is not None

        # 2. Strict Account Match Check FIRST
        if selected_account_id is not None:
            active_id = active_account.id if active_account else None
            if active_id != selected_account_id:
                error_msg = (
                    f"ACCOUNT_MISMATCH: UI selected account '{selected_account_id}' does not match "
                    f"server-trusted active account '{active_id}'. Execution blocked."
                )
                logger.warn("square_off_execute_blocked_account_mismatch", error=error_msg, user_id=user_id)
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=selected_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

        # 3. Validate Account Connection Status
        if has_accounts or bool(user_id and user_id != "default_user"):
            if not active_account:
                error_msg = f"NO_ACTIVE_ACCOUNT: No active broker account configured for user '{user_id}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=None,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            if active_account.status == BrokerAccountStatus.TOKEN_EXPIRED.value:
                error_msg = "TOKEN_EXPIRED: Active broker account token has expired. Reconnection required."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=active_account.id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_msg)

            if active_account.status != BrokerAccountStatus.CONNECTED.value:
                error_msg = f"ACTIVE_ACCOUNT_NOT_CONNECTED: Active account is in status '{active_account.status}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=active_account.id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

        target_account_id = active_account.id if active_account else None
        target_account_label = active_account.account_label if active_account else "GLOBAL"

        # 4. Validate Confirm Phrase
        clean_phrase = (confirm_phrase or "").strip().upper()
        if clean_phrase not in ("CONFIRM", "CLOSE ALL"):
            error_msg = f"INVALID_CONFIRM_PHRASE: Must explicitly type 'CONFIRM' or 'CLOSE ALL' (received: '{confirm_phrase}')."
            logger.warn("square_off_execute_invalid_phrase", error=error_msg, user_id=user_id)
            record_square_off_audit(
                square_off_id=square_off_id,
                user_id=user_id,
                account_id=target_account_id,
                action_type="BLOCKED",
                status="BLOCKED",
                error_summary=error_msg,
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

        # 5. Atomically Validate and Consume Single-Use Token & In-Flight Lock
        async with self._lock:
            self._cleanup_expired_tokens()

            if confirmation_token in self._consumed_tokens:
                error_msg = "TOKEN_ALREADY_USED: Confirmation token has already been consumed. Refusing duplicate execution."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)

            token_obj = self._tokens.get(confirmation_token)

            if not token_obj:
                error_msg = "INVALID_TOKEN: Confirmation token is not recognized or has expired."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            if time.time() > token_obj.expires_at:
                error_msg = "TOKEN_EXPIRED: Confirmation token has expired. Prepare a new square-off request."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            if token_obj.consumed:
                error_msg = "TOKEN_ALREADY_USED: Confirmation token has already been consumed. Refusing duplicate execution."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)

            if token_obj.account_id != target_account_id:
                error_msg = f"ACCOUNT_MISMATCH: Token was generated for account '{token_obj.account_id}', not '{target_account_id}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

            # Check and acquire in-flight lock
            lock_key = target_account_id or "GLOBAL"
            if lock_key in self._in_flight_accounts:
                error_msg = f"SQUARE_OFF_IN_PROGRESS: Square-off already in progress for account '{target_account_label}'."
                record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="BLOCKED",
                    status="BLOCKED",
                    error_summary=error_msg,
                )
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)

            # Consume token and acquire lock
            token_obj.consumed = True
            self._consumed_tokens.add(confirmation_token)
            self._in_flight_accounts.add(lock_key)

        # 6. Execute Square-Off with Per-Order Independence
        lock_key = target_account_id or "GLOBAL"
        try:
            # Fetch fresh live open positions at this exact moment
            positions = await broker.get_positions(account_id=target_account_id)
            legs_to_close: List[LegOrderRequest] = []
            for port in positions:
                for leg in port.legs:
                    if leg.quantity > 0:
                        legs_to_close.append(leg)

            # Case: No open positions -> No-op with audit trail
            if not legs_to_close:
                audit_id = record_square_off_audit(
                    square_off_id=square_off_id,
                    user_id=user_id,
                    account_id=target_account_id,
                    action_type="EXECUTE",
                    status="NO_OP",
                    total_positions=0,
                    error_summary="No open positions found to close.",
                )
                logger.info(
                    "square_off_no_open_positions_noop",
                    square_off_id=square_off_id,
                    account_id=target_account_id,
                    audit_id=audit_id,
                )
                return {
                    "status": "no_op",
                    "message": f"No open positions found to square off for account '{target_account_label}'.",
                    "square_off_id": square_off_id,
                    "account_id": target_account_id,
                    "account_label": target_account_label,
                    "total_positions": 0,
                    "filled_count": 0,
                    "partial_count": 0,
                    "failed_count": 0,
                    "results": [],
                    "audit_id": audit_id,
                }

            # Initialize Progress Tracking
            self._progress_cache[square_off_id] = {
                "square_off_id": square_off_id,
                "status": "EXECUTING",
                "total_positions": len(legs_to_close),
                "processed_positions": 0,
                "results": [],
            }

            results: List[Dict[str, Any]] = []

            # Execute Each Position Independently
            for leg in legs_to_close:
                exit_action = OrderAction.SELL if leg.action == OrderAction.BUY else OrderAction.BUY
                exit_leg = LegOrderRequest(
                    symbol=leg.symbol,
                    underlying=leg.underlying,
                    strike=leg.strike,
                    option_type=leg.option_type,
                    expiry=leg.expiry,
                    action=exit_action,
                    quantity=leg.quantity,
                    price=0.0,
                    is_hedge_leg=False,
                )

                try:
                    order_res = await broker.place_order(
                        exit_leg,
                        correlation_id=f"SQ_{square_off_id}",
                        account_id=target_account_id,
                    )

                    if order_res.status == OrderStatus.COMPLETE:
                        res_item = {
                            "symbol": leg.symbol,
                            "action": exit_action.value,
                            "requested_quantity": leg.quantity,
                            "filled_quantity": order_res.filled_quantity,
                            "avg_price": order_res.execution_price,
                            "status": "FILLED",
                            "order_id": order_res.order_id,
                            "error": None,
                        }
                        # Sync DB MockPositionRecord if exists
                        self._sync_position_db(leg.symbol, target_account_id, filled_qty=order_res.filled_quantity)
                    elif order_res.status == OrderStatus.PARTIALLY_FILLED:
                        res_item = {
                            "symbol": leg.symbol,
                            "action": exit_action.value,
                            "requested_quantity": leg.quantity,
                            "filled_quantity": order_res.filled_quantity,
                            "avg_price": order_res.execution_price,
                            "status": "PARTIAL",
                            "order_id": order_res.order_id,
                            "error": None,
                        }
                        self._sync_position_db(leg.symbol, target_account_id, filled_qty=order_res.filled_quantity)
                    else:
                        # Order was rejected - position state untouched
                        res_item = {
                            "symbol": leg.symbol,
                            "action": exit_action.value,
                            "requested_quantity": leg.quantity,
                            "filled_quantity": 0,
                            "avg_price": 0.0,
                            "status": "FAILED",
                            "order_id": order_res.order_id,
                            "error": order_res.error_message or "Order rejected by broker",
                        }
                except Exception as exc:
                    logger.error("square_off_leg_exception", symbol=leg.symbol, error=str(exc))
                    res_item = {
                        "symbol": leg.symbol,
                        "action": exit_action.value,
                        "requested_quantity": leg.quantity,
                        "filled_quantity": 0,
                        "avg_price": 0.0,
                        "status": "FAILED",
                        "order_id": None,
                        "error": str(exc),
                    }

                results.append(res_item)
                self._progress_cache[square_off_id]["processed_positions"] = len(results)
                self._progress_cache[square_off_id]["results"].append(res_item)

                if self.event_broadcaster:
                    try:
                        await self.event_broadcaster({
                            "event": "SQUARE_OFF_PROGRESS",
                            "square_off_id": square_off_id,
                            "processed": len(results),
                            "total": len(legs_to_close),
                            "latest_result": res_item,
                        })
                    except Exception:
                        pass

            # Calculate Final Aggregates
            filled_count = sum(1 for r in results if r["status"] == "FILLED")
            partial_count = sum(1 for r in results if r["status"] == "PARTIAL")
            failed_count = sum(1 for r in results if r["status"] == "FAILED")

            if failed_count == 0 and partial_count == 0:
                final_status = "SUCCESS"
            elif filled_count > 0 or partial_count > 0:
                final_status = "PARTIAL_SUCCESS"
            else:
                final_status = "FAILED"

            self._progress_cache[square_off_id]["status"] = final_status

            # Durable Post-Audit Trail
            audit_id = record_square_off_audit(
                square_off_id=square_off_id,
                user_id=user_id,
                account_id=target_account_id,
                action_type="EXECUTE",
                status=final_status,
                total_positions=len(results),
                filled_positions=filled_count,
                partial_positions=partial_count,
                failed_positions=failed_count,
                orders=results,
            )

            if self.event_broadcaster:
                try:
                    await self.event_broadcaster({
                        "event": "EMERGENCY_SQUARE_OFF_COMPLETED",
                        "square_off_id": square_off_id,
                        "status": final_status,
                        "filled_count": filled_count,
                        "partial_count": partial_count,
                        "failed_count": failed_count,
                        "audit_id": audit_id,
                    })
                except Exception:
                    pass

            logger.info(
                "square_off_execution_completed",
                square_off_id=square_off_id,
                status=final_status,
                filled=filled_count,
                partial=partial_count,
                failed=failed_count,
                audit_id=audit_id,
            )

            return {
                "status": final_status.lower(),
                "message": (
                    f"Square-off completed for account '{target_account_label}': "
                    f"{filled_count} filled, {partial_count} partial, {failed_count} failed."
                ),
                "square_off_id": square_off_id,
                "account_id": target_account_id,
                "account_label": target_account_label,
                "total_positions": len(results),
                "filled_count": filled_count,
                "partial_count": partial_count,
                "failed_count": failed_count,
                "results": results,
                "audit_id": audit_id,
            }

        finally:
            async with self._lock:
                self._in_flight_accounts.discard(lock_key)

    # -------------------------------------------------------------------------
    # DIRECT EXECUTION (Backward Compatible)
    # -------------------------------------------------------------------------

    async def execute_direct(
        self,
        user_id: str,
        selected_account_id: Optional[str] = None,
        broker_adapter: Optional[BaseBrokerAdapter] = None,
    ) -> Dict[str, Any]:
        """
        Direct single-call execution for backward compatibility with legacy endpoints and tests.
        Internally prepares with auto-token and executes immediately with full safety and audit.
        """
        prep = await self.prepare_square_off(
            user_id=user_id,
            selected_account_id=selected_account_id,
            broker_adapter=broker_adapter,
        )
        return await self.execute_square_off(
            user_id=user_id,
            confirmation_token=prep["confirmation_token"],
            confirm_phrase="CONFIRM",
            selected_account_id=selected_account_id,
            broker_adapter=broker_adapter,
        )

    # -------------------------------------------------------------------------
    # AUXILIARY / AUDIT METHODS
    # -------------------------------------------------------------------------

    def get_progress(self, square_off_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve progress snapshot for an ongoing or completed square-off."""
        return self._progress_cache.get(square_off_id)

    def get_audit_trail(
        self,
        account_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve historical square-off audit entries."""
        records = get_square_off_audits(account_id=account_id, user_id=user_id, limit=limit)
        return [r.to_dict() for r in records]

    def _sync_position_db(self, symbol: str, account_id: Optional[str], filled_qty: int) -> None:
        """Update MockPositionRecord state in database on confirmed fills."""
        session = db_session()
        try:
            pos = session.query(MockPositionRecord).filter_by(symbol=symbol, is_open=True).first()
            if pos:
                abs_qty = abs(pos.quantity)
                if filled_qty >= abs_qty:
                    pos.quantity = 0
                    pos.is_open = False
                else:
                    new_abs = abs_qty - filled_qty
                    pos.quantity = new_abs if pos.quantity > 0 else -new_abs
                pos.updated_at = datetime.utcnow()
                session.commit()
        except Exception as exc:
            session.rollback()
            logger.warn("failed_to_sync_position_db", symbol=symbol, error=str(exc))
        finally:
            session.close()
