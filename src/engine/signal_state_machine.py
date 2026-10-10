"""
State Machine and Simulated Mock Executor for Trading Signals (Phase 2).
Enforces strict lifecycle transition invariants and maintains an immutable audit trail.

CRITICAL NOTICE:
Execution in this module is 100% SIMULATED / MOCKED.
It is NOT connected to any real-money broker API or live trading infrastructure.
All order placement, filling, and state progression are mock simulations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
import structlog

from src.models.signal_schema import SignalStatus

logger = structlog.get_logger("openalgo.signal_state_machine")


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal status transition is attempted on a Signal."""
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Illegal state transition from '{current_status}' to '{target_status}'. "
            f"Allowed transitions from '{current_status}': "
            f"{[s.value for s in ALLOWED_TRANSITIONS.get(SignalStatus(current_status), set())]}"
        )
        self.current_status = current_status
        self.target_status = target_status


# Explicit State Machine Transitions Map
ALLOWED_TRANSITIONS: Dict[SignalStatus, Set[SignalStatus]] = {
    SignalStatus.RECEIVED: {
        SignalStatus.VALIDATED,
        SignalStatus.REJECTED,
    },
    SignalStatus.VALIDATED: {
        SignalStatus.PENDING_APPROVAL,
        SignalStatus.APPROVED,
        SignalStatus.EXECUTING,
        SignalStatus.REJECTED,
    },
    SignalStatus.PENDING_APPROVAL: {
        SignalStatus.APPROVED,
        SignalStatus.REJECTED,
    },
    SignalStatus.APPROVED: {
        SignalStatus.EXECUTING,
        SignalStatus.REJECTED,
    },
    SignalStatus.EXECUTING: {
        SignalStatus.COMPLETED,
        SignalStatus.FAILED,
    },
    # Terminal states have no outgoing transitions
    SignalStatus.REJECTED: set(),
    SignalStatus.COMPLETED: set(),
    SignalStatus.FAILED: set(),
}


def can_transition(current: SignalStatus, target: SignalStatus) -> bool:
    """Check whether a transition from current to target is allowed."""
    return target in ALLOWED_TRANSITIONS.get(current, set())


def validate_transition(current_status: str | SignalStatus, target_status: str | SignalStatus) -> None:
    """
    Validate that transition from current_status to target_status is permissible.
    Raises InvalidStateTransitionError if illegal.
    """
    curr = SignalStatus(current_status)
    tgt = SignalStatus(target_status)
    if not can_transition(curr, tgt):
        raise InvalidStateTransitionError(curr.value, tgt.value)


def build_audit_entry(
    status: SignalStatus | str,
    actor: str = "system",
    reason: str = "Status updated",
    timestamp: Optional[datetime] = None,
) -> Dict[str, str]:
    """Helper to create a normalized audit trail record."""
    ts = timestamp or datetime.utcnow()
    status_str = status.value if isinstance(status, SignalStatus) else str(status)
    return {
        "status": status_str,
        "timestamp": ts.isoformat(),
        "actor": actor,
        "reason": reason,
    }


# =============================================================================
# MOCK EXECUTION STUB (SIMULATED ONLY — NO REAL BROKER INTERACTION)
# =============================================================================

async def execute_signal_mock(
    signal_id: str,
    simulate_delay_seconds: float = 0.05,
    force_failure: bool = False,
    failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Simulated Mock Execution for Phase 2 Trade Signal Ingestion.

    ========================================================================
    DISCLAIMER: STUB/MOCK ONLY
    This function simulates downstream order processing, latency, and fills.
    NO real-money broker API calls are made. NO live orders are routed.
    ========================================================================

    Args:
        signal_id: Unique identifier of the signal being mock-executed.
        simulate_delay_seconds: Time delay in seconds to simulate async fill latency.
        force_failure: If True, simulates an execution rejection/failure.
        failure_reason: Optional reason string explaining mock failure.

    Returns:
        Dict detailing the mock execution outcome.
    """
    logger.info(
        "mock_execution_started",
        signal_id=signal_id,
        simulated_delay=simulate_delay_seconds,
        note="MOCK EXECUTION STUB - NOT REAL MONEY",
    )

    if simulate_delay_seconds > 0:
        await asyncio.sleep(simulate_delay_seconds)

    if force_failure:
        outcome = SignalStatus.FAILED
        reason = failure_reason or "Mock broker simulated order rejection: Insufficient virtual balance"
        logger.warn(
            "mock_execution_failed",
            signal_id=signal_id,
            reason=reason,
            note="MOCK EXECUTION STUB - NOT REAL MONEY",
        )
    else:
        outcome = SignalStatus.COMPLETED
        reason = "Mock execution completed: All legs filled virtually at simulated prices"
        logger.info(
            "mock_execution_completed",
            signal_id=signal_id,
            outcome=outcome.value,
            note="MOCK EXECUTION STUB - NOT REAL MONEY",
        )

    return {
        "signal_id": signal_id,
        "final_status": outcome.value,
        "reason": reason,
        "executed_at": datetime.utcnow().isoformat(),
        "is_mock": True,
    }
