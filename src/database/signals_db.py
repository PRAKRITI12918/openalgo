"""
Database Persistence Layer for Phase 2 Trade Signal Ingestion.
Enforces database-level unique idempotency constraints, indexes for query performance,
and atomic state transitions with full audit trail histories.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
import structlog

from src.engine.signal_state_machine import (
    build_audit_entry,
    validate_transition,
)
from src.models.signal_schema import SignalStatus

logger = structlog.get_logger("openalgo.signals_db")

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


class SignalRecord(Base):
    """
    SQLAlchemy model representing an ingested trade strategy signal.
    Enforces a unique DB constraint on idempotency_key to prevent duplicate ingestion.
    """
    __tablename__ = "trade_signals"

    signal_id = Column(String(64), primary_key=True, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    strategy_name = Column(String(100), nullable=False, index=True)
    underlying = Column(String(50), nullable=False, index=True)
    instrument = Column(String(20), nullable=False)
    action = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    order_type = Column(String(20), nullable=False)
    price = Column(Float, nullable=True)
    trigger_price = Column(Float, nullable=True)
    execution_sequence = Column(Integer, default=1, nullable=False)
    status = Column(String(30), default="RECEIVED", index=True, nullable=False)

    # Optional option attributes
    strike = Column(Float, nullable=True)
    expiry = Column(String(20), nullable=True)
    option_type = Column(String(10), nullable=True)

    # Multi-leg and metadata payloads
    legs_json = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    payload_json = Column(Text, nullable=False)
    status_history_json = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_signals_status", "status"),
        Index("idx_signals_strategy_name", "strategy_name"),
        Index("idx_signals_underlying", "underlying"),
        Index("idx_signals_created_at", "created_at"),
        Index("uq_signals_idempotency_key", "idempotency_key", unique=True),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert database record to dictionary with parsed JSON fields."""
        legs = json.loads(self.legs_json) if self.legs_json else None
        meta = json.loads(self.metadata_json) if self.metadata_json else None
        history = json.loads(self.status_history_json) if self.status_history_json else []

        return {
            "signal_id": self.signal_id,
            "idempotency_key": self.idempotency_key,
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "instrument": self.instrument,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "price": self.price,
            "trigger_price": self.trigger_price,
            "execution_sequence": self.execution_sequence,
            "status": self.status,
            "strike": self.strike,
            "expiry": self.expiry,
            "option_type": self.option_type,
            "legs": legs,
            "metadata": meta,
            "status_history": history,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }


def init_signals_db() -> None:
    """
    Initialize trade signals database schema and ensure unique idempotency index.
    Acts as schema setup and migration runner for trade_signals.
    """
    try:
        Base.metadata.create_all(bind=engine)
        # Explicit index migration check
        with engine.connect() as conn:
            try:
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS uq_signals_idempotency_key ON trade_signals(idempotency_key);")
                )
                conn.commit()
            except Exception:
                pass  # May already exist or be managed by create_all
        logger.info("signals_db_initialized", table=SignalRecord.__tablename__)
    except Exception as e:
        logger.error("signals_db_init_failed", error=str(e))
        raise


def get_signal_by_id(signal_id: str) -> Optional[SignalRecord]:
    """Retrieve signal by unique signal_id."""
    session = db_session()
    try:
        return session.query(SignalRecord).filter_by(signal_id=signal_id).first()
    finally:
        session.close()


def get_signal_by_idempotency_key(idempotency_key: str) -> Optional[SignalRecord]:
    """Retrieve signal by its unique idempotency key."""
    session = db_session()
    try:
        return session.query(SignalRecord).filter_by(idempotency_key=idempotency_key).first()
    finally:
        session.close()


def insert_signal_record(record_data: Dict[str, Any]) -> Tuple[SignalRecord, bool]:
    """
    Insert a new signal record.
    If a record with the same idempotency_key already exists (caught via DB unique constraint),
    returns the existing record with is_created=False.
    Otherwise returns the newly created record with is_created=True.
    """
    session = db_session()
    try:
        record = SignalRecord(**record_data)
        session.add(record)
        session.commit()
        session.refresh(record)
        # Detach/copy data before closing
        return record, True
    except IntegrityError:
        session.rollback()
        # Fetch the existing record to return idempotent response
        existing = session.query(SignalRecord).filter_by(idempotency_key=record_data["idempotency_key"]).first()
        if existing:
            return existing, False
        raise
    except Exception as e:
        session.rollback()
        logger.error(
            "insert_signal_record_failed",
            error=str(e),
            signal_id=record_data.get("signal_id"),
            idempotency_key=record_data.get("idempotency_key"),
        )
        raise
    finally:
        session.close()


def transition_signal_status(
    signal_id: str,
    target_status: SignalStatus | str,
    actor: str = "system",
    reason: str = "Status transition",
) -> SignalRecord:
    """
    Validate and execute an atomic status transition on a signal record,
    appending to the JSON audit history.
    """
    tgt = SignalStatus(target_status)
    session = db_session()
    try:
        record = session.query(SignalRecord).filter_by(signal_id=signal_id).with_for_update().first()
        if not record:
            raise KeyError(f"Signal {signal_id} not found")

        curr = SignalStatus(record.status)
        validate_transition(curr, tgt)

        # Update status
        record.status = tgt.value
        record.updated_at = datetime.utcnow()

        # Append to status history
        history: List[Dict[str, str]] = json.loads(record.status_history_json) if record.status_history_json else []
        history.append(build_audit_entry(tgt, actor=actor, reason=reason, timestamp=record.updated_at))
        record.status_history_json = json.dumps(history)

        session.commit()
        session.refresh(record)
        return record
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def list_signals(
    status: Optional[str] = None,
    underlying: Optional[str] = None,
    strategy_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """Query signals with filtering, pagination, and total count."""
    session = db_session()
    try:
        query = session.query(SignalRecord)
        if status:
            query = query.filter_by(status=status.upper())
        if underlying:
            query = query.filter_by(underlying=underlying.upper())
        if strategy_name:
            query = query.filter_by(strategy_name=strategy_name)

        total_count = query.count()
        records = query.order_by(SignalRecord.created_at.desc()).offset(offset).limit(limit).all()
        return [r.to_dict() for r in records], total_count
    finally:
        session.close()
