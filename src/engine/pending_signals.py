# src/engine/pending_signals.py
"""
Pending Trade Signal Queue Manager.
Manages the lifecycle of human-in-the-loop and queued trade signals:
- Ingestion with TTL expiration tracking
- Thread/Async-safe atomic Compare-And-Swap (CAS) state transitions
- Prevention of duplicate approvals under concurrent requests
- Failure recovery ensuring signals are never silently marked approved
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.database.pending_signals_db import (
    PendingSignalRecord,
    append_status_history_entry,
    atomic_transition_state,
    get_pending_signal_by_id,
    init_pending_signals_db,
    insert_pending_signal,
    query_pending_signals,
    update_signal_record,
)
from src.models.schemas import (
    OrderAction,
    PendingSignalStatus,
    PendingSignalSummary,
    StrategySignalPayload,
)

logger = structlog.get_logger("openalgo.pending_signals")


class PendingSignalManager:
    """
    Manages state, persistence, and concurrency locks for pending trade signals.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        init_pending_signals_db()

    def _is_record_expired(self, record: PendingSignalRecord, now: Optional[datetime] = None) -> bool:
        """Helper to determine if a signal record has expired."""
        if now is None:
            now = datetime.utcnow()

        # Check explicit expires_at timestamp
        if record.expires_at and now > record.expires_at:
            return True

        # Check validity seconds from creation time
        if record.validity_seconds and record.created_at:
            max_expiry = record.created_at + timedelta(seconds=record.validity_seconds)
            if now > max_expiry:
                return True

        return False

    async def add_pending_signal(self, payload: StrategySignalPayload) -> PendingSignalSummary:
        """
        Store an ingested trade signal in PENDING state awaiting trader approval.
        """
        now = datetime.utcnow()
        validity = payload.validity_seconds if payload.validity_seconds is not None else 300
        expires_at = now + timedelta(seconds=validity) if validity > 0 else None

        # Derive representative summary values from legs
        actions = {leg.action for leg in payload.legs}
        if len(actions) == 1:
            rep_action = list(actions)[0].value
        else:
            rep_action = "MULTI-LEG"

        total_qty = sum(leg.quantity for leg in payload.legs)
        first_leg = payload.legs[0]
        rep_order_type = first_leg.order_type.value if hasattr(first_leg.order_type, "value") else str(first_leg.order_type)
        rep_price = first_leg.price if first_leg.price > 0 else 0.0

        # Estimate rough margin if legs are present
        margin_est = 0.0
        for leg in payload.legs:
            if leg.action == OrderAction.SELL:
                margin_est += leg.quantity * 1000.0  # Normalized rough estimate for short credit exposure
            else:
                margin_est += leg.quantity * (leg.price if leg.price > 0 else 50.0)

        initial_history = [
            {
                "status": PendingSignalStatus.PENDING.value,
                "timestamp": now.isoformat(),
                "action": "INGESTED",
                "actor": "system",
                "user_id": payload.user_id,
                "reason": "Signal accepted and enqueued for manual trader approval",
            }
        ]

        record_data: Dict[str, Any] = {
            "signal_id": payload.signal_id,
            "correlation_id": payload.correlation_id,
            "strategy_name": payload.strategy_name,
            "underlying": payload.underlying.value if hasattr(payload.underlying, "value") else str(payload.underlying),
            "signal_type": payload.signal_type.value if hasattr(payload.signal_type, "value") else str(payload.signal_type),
            "status": PendingSignalStatus.PENDING.value,
            "action": rep_action,
            "quantity": total_qty,
            "order_type": rep_order_type,
            "price": rep_price,
            "legs_count": len(payload.legs),
            "entry_credit_debit": payload.entry_credit_debit,
            "margin_estimate": margin_est,
            "payload_json": payload.model_dump_json(),
            "user_id": payload.user_id,
            "created_at": now,
            "expires_at": expires_at,
            "validity_seconds": validity,
            "actor": None,
            "status_history_json": json.dumps(initial_history),
        }

        async with self._lock:
            insert_pending_signal(record_data)

        logger.info(
            "pending_signal_stored",
            signal_id=payload.signal_id,
            strategy=payload.strategy_name,
            user_id=payload.user_id,
            expires_at=expires_at.isoformat() if expires_at else None,
        )

        time_remaining = int((expires_at - now).total_seconds()) if expires_at else None

        return PendingSignalSummary(
            signal_id=payload.signal_id,
            correlation_id=payload.correlation_id,
            strategy_name=payload.strategy_name,
            underlying=record_data["underlying"],
            signal_type=record_data["signal_type"],
            status=PendingSignalStatus.PENDING.value,
            user_id=payload.user_id,
            action=rep_action,
            quantity=total_qty,
            order_type=rep_order_type,
            price=rep_price,
            legs_count=len(payload.legs),
            entry_credit_debit=payload.entry_credit_debit,
            margin_estimate=margin_est,
            created_at=now,
            expires_at=expires_at,
            time_remaining_seconds=time_remaining,
            is_expired=False,
            status_history=initial_history,
            payload=payload.model_dump(mode="json"),
        )

    async def get_all_signals(self, status: Optional[str] = None) -> List[PendingSignalSummary]:
        """
        Query pending signals, dynamically evaluating TTL expiration.
        """
        now = datetime.utcnow()
        records = query_pending_signals(status=status)
        summaries: List[PendingSignalSummary] = []

        for rec in records:
            is_exp = False
            time_rem: Optional[int] = None
            current_status = rec.status

            if rec.expires_at:
                seconds_left = int((rec.expires_at - now).total_seconds())
                time_rem = seconds_left
                if seconds_left <= 0:
                    is_exp = True
                    if current_status in (PendingSignalStatus.PENDING.value, "PENDING_APPROVAL"):
                        # Auto-transition expired pending signal
                        current_status = PendingSignalStatus.EXPIRED.value
                        update_signal_record(rec.signal_id, status=current_status)
                        append_status_history_entry(rec.signal_id, {
                            "status": PendingSignalStatus.EXPIRED.value,
                            "timestamp": now.isoformat(),
                            "action": "EXPIRED",
                            "actor": "system",
                            "reason": "Signal exceeded validity TTL window",
                        })

            raw_payload: Optional[Dict[str, Any]] = None
            if rec.payload_json:
                try:
                    raw_payload = json.loads(rec.payload_json)
                except Exception:
                    pass

            history = []
            if rec.status_history_json:
                try:
                    history = json.loads(rec.status_history_json)
                except Exception:
                    pass

            summaries.append(
                PendingSignalSummary(
                    signal_id=rec.signal_id,
                    correlation_id=rec.correlation_id,
                    strategy_name=rec.strategy_name,
                    underlying=rec.underlying,
                    signal_type=rec.signal_type,
                    status=current_status,
                    user_id=rec.user_id,
                    action=rec.action,
                    quantity=rec.quantity,
                    order_type=rec.order_type,
                    price=rec.price,
                    legs_count=rec.legs_count,
                    entry_credit_debit=rec.entry_credit_debit,
                    margin_estimate=rec.margin_estimate,
                    created_at=rec.created_at,
                    expires_at=rec.expires_at,
                    time_remaining_seconds=time_rem,
                    is_expired=is_exp,
                    approved_at=rec.approved_at,
                    approved_by=rec.approved_by,
                    rejected_at=rec.rejected_at,
                    rejected_by=rec.rejected_by,
                    actor=rec.actor,
                    rejection_reason=rec.rejection_reason,
                    sequence_id=rec.sequence_id,
                    error_message=rec.error_message,
                    status_history=history,
                    payload=raw_payload,
                )
            )

        return summaries

    async def get_signal_payload(self, signal_id: str) -> Optional[StrategySignalPayload]:
        """Load and parse the full validated StrategySignalPayload from stored JSON."""
        rec = get_pending_signal_by_id(signal_id)
        if not rec or not rec.payload_json:
            return None
        try:
            return StrategySignalPayload.model_validate_json(rec.payload_json)
        except Exception as e:
            logger.error("parse_pending_payload_failed", signal_id=signal_id, error=str(e))
            return None

    async def prepare_for_approval(
        self,
        signal_id: str,
        actor: str = "dashboard-trader",
        user_id: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[StrategySignalPayload]]:
        """
        Concurrency-safe preparation for approval:
        1. Validates signal existence
        2. Validates non-expiration
        3. Enforces that current status is PENDING / PENDING_APPROVAL
        4. Atomically transitions state from PENDING/PENDING_APPROVAL to APPROVING via CAS
        Returns (success, reason_code, payload)
        """
        async with self._lock:
            rec = get_pending_signal_by_id(signal_id)
            if not rec:
                return False, "NOT_FOUND", None

            now = datetime.utcnow()
            if self._is_record_expired(rec, now):
                update_signal_record(signal_id, status=PendingSignalStatus.EXPIRED.value)
                append_status_history_entry(signal_id, {
                    "status": PendingSignalStatus.EXPIRED.value,
                    "timestamp": now.isoformat(),
                    "action": "EXPIRED",
                    "actor": "system",
                    "reason": "Signal expired prior to approval attempt",
                })
                return False, "SIGNAL_EXPIRED", None

            if rec.status in (
                PendingSignalStatus.APPROVED.value,
                PendingSignalStatus.REJECTED.value,
                PendingSignalStatus.FAILED.value,
                PendingSignalStatus.EXPIRED.value,
            ):
                return False, "ALREADY_TERMINAL", None

            if rec.status == PendingSignalStatus.APPROVING.value:
                return False, "CONFLICT", None

            if rec.status not in (PendingSignalStatus.PENDING.value, "PENDING_APPROVAL"):
                return False, "SIGNAL_NOT_PENDING_APPROVAL", None

            # Prepare audit entry for the atomic CAS
            history = json.loads(rec.status_history_json) if rec.status_history_json else []
            history.append({
                "from_status": rec.status,
                "to_status": PendingSignalStatus.APPROVING.value,
                "action": "APPROVE_INITIATED",
                "actor": actor,
                "user_id": user_id or actor,
                "timestamp": now.isoformat(),
                "reason": "Approval received, atomic CAS transition started",
            })

            # Execute atomic Compare-And-Swap (CAS) in DB
            cas_success = atomic_transition_state(
                signal_id=signal_id,
                from_status=[PendingSignalStatus.PENDING.value, "PENDING_APPROVAL"],
                to_status=PendingSignalStatus.APPROVING.value,
                actor=actor,
                approved_at=now,
                approved_by=user_id or actor,
                status_history_json=json.dumps(history),
            )

            if not cas_success:
                return False, "CONFLICT", None

            try:
                payload = StrategySignalPayload.model_validate_json(rec.payload_json)
            except Exception as e:
                logger.error("deserialization_failed_on_approve", signal_id=signal_id, error=str(e))
                update_signal_record(signal_id, status=PendingSignalStatus.FAILED.value, error_message="Payload deserialization error")
                append_status_history_entry(signal_id, {
                    "status": PendingSignalStatus.FAILED.value,
                    "timestamp": now.isoformat(),
                    "action": "CORRUPT_PAYLOAD",
                    "actor": "system",
                    "reason": "Payload deserialization error",
                })
                return False, "CORRUPT_PAYLOAD", None

            return True, "OK", payload

    async def finalize_approval(
        self,
        signal_id: str,
        sequence_id: str,
        user_id: Optional[str] = None,
    ) -> None:
        """Finalize the approval state to APPROVED after successful sequential execution."""
        now = datetime.utcnow()
        update_signal_record(
            signal_id,
            status=PendingSignalStatus.APPROVED.value,
            sequence_id=sequence_id,
        )
        append_status_history_entry(signal_id, {
            "status": PendingSignalStatus.APPROVED.value,
            "timestamp": now.isoformat(),
            "action": "EXECUTION_COMPLETED",
            "actor": user_id or "dashboard-trader",
            "sequence_id": sequence_id,
            "reason": "Signal approved and sequential execution completed successfully",
        })
        logger.info("pending_signal_approved_and_executed", signal_id=signal_id, sequence_id=sequence_id)

    async def finalize_failure(
        self,
        signal_id: str,
        error_message: str,
        sequence_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """Mark the signal as FAILED if execution pipeline encountered an error."""
        now = datetime.utcnow()
        update_kwargs: Dict[str, Any] = {
            "status": PendingSignalStatus.FAILED.value,
            "error_message": error_message,
        }
        if sequence_id:
            update_kwargs["sequence_id"] = sequence_id
        update_signal_record(signal_id, **update_kwargs)
        append_status_history_entry(signal_id, {
            "status": PendingSignalStatus.FAILED.value,
            "timestamp": now.isoformat(),
            "action": "EXECUTION_FAILED",
            "actor": user_id or "system",
            "sequence_id": sequence_id,
            "reason": error_message,
        })
        logger.error("pending_signal_execution_failed", signal_id=signal_id, error=error_message)

    async def reject_signal(
        self,
        signal_id: str,
        reason: Optional[str] = None,
        actor: str = "dashboard-trader",
        user_id: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Concurrency-safe rejection transition:
        1. Validates signal existence
        2. Validates non-expiration
        3. Enforces that current status is PENDING, PENDING_APPROVAL, or VALIDATED
        4. Atomically transitions state to REJECTED via CAS with sanitized reason (<= 500 chars)
        GUARANTEE: Has zero imports, bindings, or calls to the execution engine.
        """
        sanitized_reason = (reason or "Manual rejection from trader dashboard")[:500]

        async with self._lock:
            rec = get_pending_signal_by_id(signal_id)
            if not rec:
                return False, "NOT_FOUND"

            now = datetime.utcnow()
            if self._is_record_expired(rec, now):
                update_signal_record(signal_id, status=PendingSignalStatus.EXPIRED.value)
                append_status_history_entry(signal_id, {
                    "status": PendingSignalStatus.EXPIRED.value,
                    "timestamp": now.isoformat(),
                    "action": "EXPIRED",
                    "actor": "system",
                    "reason": "Signal expired prior to rejection attempt",
                })
                return False, "SIGNAL_EXPIRED"

            if rec.status in (
                PendingSignalStatus.APPROVED.value,
                PendingSignalStatus.REJECTED.value,
                PendingSignalStatus.FAILED.value,
                PendingSignalStatus.EXPIRED.value,
            ):
                return False, "ALREADY_TERMINAL"

            if rec.status == PendingSignalStatus.APPROVING.value:
                return False, "CONFLICT"

            if rec.status not in (PendingSignalStatus.PENDING.value, "PENDING_APPROVAL", "VALIDATED"):
                return False, "SIGNAL_NOT_PENDING_APPROVAL"

            history = json.loads(rec.status_history_json) if rec.status_history_json else []
            history.append({
                "from_status": rec.status,
                "to_status": PendingSignalStatus.REJECTED.value,
                "action": "REJECTED",
                "actor": actor,
                "user_id": user_id or actor,
                "timestamp": now.isoformat(),
                "reason": sanitized_reason,
            })

            cas_success = atomic_transition_state(
                signal_id=signal_id,
                from_status=[PendingSignalStatus.PENDING.value, "PENDING_APPROVAL", "VALIDATED"],
                to_status=PendingSignalStatus.REJECTED.value,
                actor=actor,
                rejected_by=user_id or actor,
                rejection_reason=sanitized_reason,
                rejected_at=now,
                status_history_json=json.dumps(history),
            )

            if not cas_success:
                return False, "CONFLICT"

            logger.info("pending_signal_rejected", signal_id=signal_id, actor=actor, user_id=user_id, reason=sanitized_reason)
            return True, "OK"

