"""
Database Persistence Layer for Mock Execution Engine.
Stores simulated positions, unrealized/realized P&L, and immutable execution lifecycle events.

CRITICAL NOTICE:
All records in this module represent SIMULATED / MOCK trading activity.
No real money or live broker accounts are involved.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
import structlog

logger = structlog.get_logger("openalgo.execution_db")

# Standard OpenAlgo database URL resolution
_raw_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
if _raw_url.startswith("sqlite:///") and not os.path.isabs(_raw_url.replace("sqlite:///", "")):
    _rel_path = _raw_url.replace("sqlite:///", "")
    _dir = os.path.dirname(_rel_path)
    if _dir and not os.path.exists(_dir):
        try:
            os.makedirs(_dir, exist_ok=True)
        except OSError:
            pass

if "sqlite" in _raw_url:
    engine = create_engine(
        _raw_url, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    engine = create_engine(_raw_url, pool_size=20, max_overflow=50, pool_timeout=10)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class MockPositionRecord(Base):
    """
    SQLAlchemy model tracking simulated portfolio positions and realized/unrealized P&L.
    """
    __tablename__ = "mock_positions"

    position_id = Column(String(64), primary_key=True, index=True)
    signal_id = Column(String(64), index=True, nullable=True)
    strategy_name = Column(String(100), index=True, nullable=False)
    underlying = Column(String(50), index=True, nullable=False)
    instrument = Column(String(20), nullable=False)
    symbol = Column(String(100), index=True, nullable=False)

    # Position quantities (signed: positive for LONG, negative for SHORT, 0 for FLAT)
    quantity = Column(Integer, default=0, nullable=False)
    average_price = Column(Float, default=0.0, nullable=False)
    realized_pnl = Column(Float, default=0.0, nullable=False)
    unrealized_pnl = Column(Float, default=0.0, nullable=False)
    current_mark_price = Column(Float, default=0.0, nullable=False)
    is_open = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_mock_positions_symbol", "symbol"),
        Index("idx_mock_positions_underlying", "underlying"),
        Index("idx_mock_positions_strategy", "strategy_name"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "signal_id": self.signal_id,
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "instrument": self.instrument,
            "symbol": self.symbol,
            "net_quantity": self.quantity,
            "average_price": round(self.average_price, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "mark_price": round(self.current_mark_price, 4),
            "is_open": self.is_open,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


class MockExecutionEventRecord(Base):
    """
    SQLAlchemy model recording every simulated execution transition event.
    """
    __tablename__ = "mock_execution_events"

    event_id = Column(String(64), primary_key=True, index=True)
    signal_id = Column(String(64), index=True, nullable=False)
    leg_id = Column(String(64), index=True, nullable=True)
    order_id = Column(String(64), index=True, nullable=True)
    event_type = Column(String(50), nullable=False, index=True)
    from_state = Column(String(30), nullable=True)
    to_state = Column(String(30), nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_mock_exec_signal_id", "signal_id"),
        Index("idx_mock_exec_created_at", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        details = json.loads(self.details_json) if self.details_json else {}
        return {
            "event_id": self.event_id,
            "signal_id": self.signal_id,
            "leg_id": self.leg_id,
            "order_id": self.order_id,
            "event_type": self.event_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "details": details,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class SquareOffAuditRecord(Base):
    """
    Durable audit model recording every emergency square-off request, blocked attempt,
    and per-order execution outcome.
    """
    __tablename__ = "square_off_audits"

    audit_id = Column(String(64), primary_key=True, index=True)
    square_off_id = Column(String(64), index=True, nullable=False)
    account_id = Column(String(64), index=True, nullable=True)
    user_id = Column(String(64), index=True, nullable=False)
    action_type = Column(String(50), nullable=False)  # PREPARE, EXECUTE, BLOCKED, FAILED, COMPLETED
    status = Column(String(30), nullable=False)  # SUCCESS, PARTIAL_SUCCESS, FAILED, BLOCKED, NO_OP, PREPARED
    requested_mode = Column(String(30), nullable=True)
    total_positions = Column(Integer, default=0, nullable=False)
    filled_positions = Column(Integer, default=0, nullable=False)
    partial_positions = Column(Integer, default=0, nullable=False)
    failed_positions = Column(Integer, default=0, nullable=False)
    orders_json = Column(Text, nullable=True)
    error_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("idx_sq_audit_account_id", "account_id"),
        Index("idx_sq_audit_user_id", "user_id"),
        Index("idx_sq_audit_created_at", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        orders = json.loads(self.orders_json) if self.orders_json else []
        return {
            "audit_id": self.audit_id,
            "square_off_id": self.square_off_id,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "action_type": self.action_type,
            "status": self.status,
            "requested_mode": self.requested_mode,
            "total_positions": self.total_positions,
            "filled_positions": self.filled_positions,
            "partial_positions": self.partial_positions,
            "failed_positions": self.failed_positions,
            "orders": orders,
            "error_summary": self.error_summary,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


def init_execution_db() -> None:
    """Initialize mock positions and execution events tables."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("execution_db_initialized")
    except Exception as e:
        logger.error("execution_db_init_failed", error=str(e))
        raise


def record_execution_event(
    session: Any,
    signal_id: str,
    event_type: str,
    leg_id: Optional[str] = None,
    order_id: Optional[str] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> MockExecutionEventRecord:
    """Record an individual execution audit event within the active session."""
    event = MockExecutionEventRecord(
        event_id=f"evt_{uuid.uuid4().hex}",
        signal_id=signal_id,
        leg_id=leg_id,
        order_id=order_id,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        details_json=json.dumps(details or {}),
        created_at=datetime.utcnow(),
    )
    session.add(event)
    return event


def update_position_on_fill(
    session: Any,
    symbol: str,
    underlying: str,
    strategy_name: str,
    instrument: str,
    action: str,
    fill_qty: int,
    fill_price: float,
    mark_price: float,
    signal_id: Optional[str] = None,
) -> Tuple[MockPositionRecord, float, float]:
    """
    Atomically updates simulated position and calculates realized/unrealized PnL.
    Returns (position_record, delta_realized_pnl, total_unrealized_pnl).
    """
    pos = (
        session.query(MockPositionRecord)
        .filter_by(symbol=symbol, strategy_name=strategy_name)
        .first()
    )

    if not pos:
        pos = MockPositionRecord(
            position_id=f"pos_{uuid.uuid4().hex}",
            signal_id=signal_id,
            strategy_name=strategy_name,
            underlying=underlying,
            instrument=instrument,
            symbol=symbol,
            quantity=0,
            average_price=0.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            current_mark_price=mark_price,
            is_open=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(pos)

    curr_qty = pos.quantity
    curr_avg = pos.average_price
    delta_realized_pnl = 0.0

    if curr_qty == 0:
        # Opening new position
        pos.quantity = fill_qty if action == "BUY" else -fill_qty
        pos.average_price = fill_price
        pos.is_open = True
    elif curr_qty > 0:
        # Currently Long
        if action == "BUY":
            # Add to long
            new_qty = curr_qty + fill_qty
            pos.average_price = ((curr_qty * curr_avg) + (fill_qty * fill_price)) / new_qty
            pos.quantity = new_qty
        else:
            # Sell against long (reduce or flip)
            if fill_qty <= curr_qty:
                delta_realized_pnl = fill_qty * (fill_price - curr_avg)
                pos.quantity = curr_qty - fill_qty
                if pos.quantity == 0:
                    pos.average_price = 0.0
                    pos.is_open = False
            else:
                # Flip long to short
                closed_qty = curr_qty
                excess_qty = fill_qty - curr_qty
                delta_realized_pnl = closed_qty * (fill_price - curr_avg)
                pos.quantity = -excess_qty
                pos.average_price = fill_price
                pos.is_open = True
    else:
        # Currently Short (curr_qty < 0)
        short_qty = abs(curr_qty)
        if action == "SELL":
            # Add to short
            new_short_qty = short_qty + fill_qty
            pos.average_price = ((short_qty * curr_avg) + (fill_qty * fill_price)) / new_short_qty
            pos.quantity = -new_short_qty
        else:
            # Buy against short (reduce or flip)
            if fill_qty <= short_qty:
                delta_realized_pnl = fill_qty * (curr_avg - fill_price)
                pos.quantity = -(short_qty - fill_qty)
                if pos.quantity == 0:
                    pos.average_price = 0.0
                    pos.is_open = False
            else:
                # Flip short to long
                closed_qty = short_qty
                excess_qty = fill_qty - short_qty
                delta_realized_pnl = closed_qty * (curr_avg - fill_price)
                pos.quantity = excess_qty
                pos.average_price = fill_price
                pos.is_open = True

    pos.realized_pnl += delta_realized_pnl
    pos.current_mark_price = mark_price

    # Compute unrealized PnL
    if pos.quantity > 0:
        pos.unrealized_pnl = pos.quantity * (mark_price - pos.average_price)
    elif pos.quantity < 0:
        pos.unrealized_pnl = abs(pos.quantity) * (pos.average_price - mark_price)
    else:
        pos.unrealized_pnl = 0.0

    pos.updated_at = datetime.utcnow()
    return pos, delta_realized_pnl, pos.unrealized_pnl


def get_all_positions(
    strategy_name: Optional[str] = None,
    underlying: Optional[str] = None,
) -> List[MockPositionRecord]:
    """Retrieve all simulated positions with optional filtering."""
    session = db_session()
    try:
        q = session.query(MockPositionRecord)
        if strategy_name:
            q = q.filter_by(strategy_name=strategy_name)
        if underlying:
            q = q.filter_by(underlying=underlying.upper())
        return q.all()
    finally:
        session.close()


def get_events_for_signal(signal_id: str) -> List[MockExecutionEventRecord]:
    """Retrieve chronological execution events for a signal."""
    session = db_session()
    try:
        return (
            session.query(MockExecutionEventRecord)
            .filter_by(signal_id=signal_id)
            .order_by(MockExecutionEventRecord.created_at.asc())
            .all()
        )
    finally:
        session.close()


def record_square_off_audit(
    square_off_id: str,
    user_id: str,
    action_type: str,
    status: str,
    account_id: Optional[str] = None,
    requested_mode: Optional[str] = None,
    total_positions: int = 0,
    filled_positions: int = 0,
    partial_positions: int = 0,
    failed_positions: int = 0,
    orders: Optional[List[Dict[str, Any]]] = None,
    error_summary: Optional[str] = None,
) -> str:
    """Record an emergency square-off audit log into the persistent database."""
    session = db_session()
    audit_id = f"aud_sq_{uuid.uuid4().hex[:12]}"
    try:
        record = SquareOffAuditRecord(
            audit_id=audit_id,
            square_off_id=square_off_id,
            account_id=account_id,
            user_id=user_id,
            action_type=action_type,
            status=status,
            requested_mode=requested_mode,
            total_positions=total_positions,
            filled_positions=filled_positions,
            partial_positions=partial_positions,
            failed_positions=failed_positions,
            orders_json=json.dumps(orders or []),
            error_summary=error_summary,
            created_at=datetime.utcnow(),
        )
        session.add(record)
        session.commit()
        return audit_id
    except Exception as exc:
        session.rollback()
        logger.error("failed_to_record_square_off_audit", error=str(exc))
        return audit_id
    finally:
        session.close()


def get_square_off_audits(
    account_id: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
) -> List[SquareOffAuditRecord]:
    """Retrieve audit history for square-off executions."""
    session = db_session()
    try:
        q = session.query(SquareOffAuditRecord)
        if account_id:
            q = q.filter_by(account_id=account_id)
        if user_id:
            q = q.filter_by(user_id=user_id)
        return q.order_by(SquareOffAuditRecord.created_at.desc()).limit(limit).all()
    finally:
        session.close()

