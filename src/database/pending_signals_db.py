# src/database/pending_signals_db.py
"""
Database persistence layer for Pending Trade Signals.
Stores pending strategy signals awaiting trader review and approval,
supporting atomic compare-and-swap (CAS) transitions to eliminate race conditions.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional

from sqlalchemy import (
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

logger = structlog.get_logger("openalgo.pending_signals_db")

# Standard OpenAlgo database URL resolution
_raw_url = os.getenv("DATABASE_URL", "sqlite:///db/openalgo.db")
if _raw_url.startswith("sqlite:///") and not os.path.isabs(_raw_url.replace("sqlite:///", "")):
    # If running from project root or subfolder, ensure db directory exists
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


class PendingSignalRecord(Base):
    """
    SQLAlchemy model representing a pending trade signal in the approval queue.
    """
    __tablename__ = "pending_trade_signals"

    signal_id = Column(String(64), primary_key=True, index=True)
    correlation_id = Column(String(64), index=True, nullable=False)
    strategy_name = Column(String(100), nullable=False)
    underlying = Column(String(50), nullable=False)
    signal_type = Column(String(50), default="ENTRY")
    status = Column(String(30), default="PENDING", index=True, nullable=False)

    # Core summary fields for rapid dashboard query
    action = Column(String(20), default="BUY")
    quantity = Column(Integer, default=0)
    order_type = Column(String(20), default="MARKET")
    price = Column(Float, default=0.0)
    legs_count = Column(Integer, default=1)
    entry_credit_debit = Column(Float, default=0.0)
    margin_estimate = Column(Float, default=0.0)

    # Full payload
    payload_json = Column(Text, nullable=False)

    # User scoping
    user_id = Column(String(64), nullable=True, index=True)

    # Timestamps & TTL
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    validity_seconds = Column(Integer, default=300)

    # Audit tracking
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(255), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejected_by = Column(String(255), nullable=True)
    actor = Column(String(255), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    status_history_json = Column(Text, nullable=True)

    # Downstream execution linkage
    sequence_id = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_pending_signal_status", "status"),
        Index("idx_pending_signal_created", "created_at"),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert pending signal record to dictionary."""
        history = json.loads(self.status_history_json) if self.status_history_json else []
        return {
            "signal_id": self.signal_id,
            "correlation_id": self.correlation_id,
            "strategy_name": self.strategy_name,
            "underlying": self.underlying,
            "signal_type": self.signal_type,
            "status": self.status,
            "user_id": self.user_id,
            "action": self.action,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "price": self.price,
            "legs_count": self.legs_count,
            "entry_credit_debit": self.entry_credit_debit,
            "margin_estimate": self.margin_estimate,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "validity_seconds": self.validity_seconds,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_by": self.rejected_by,
            "actor": self.actor,
            "rejection_reason": self.rejection_reason,
            "sequence_id": self.sequence_id,
            "error_message": self.error_message,
            "status_history": history,
        }


def init_pending_signals_db() -> None:
    """Initialize pending signal database schema and apply safe column migrations."""
    from sqlalchemy import text
    try:
        Base.metadata.create_all(bind=engine)
        # Migrate optional columns if table already exists in SQLite
        with engine.connect() as conn:
            for col_sql in [
                "ALTER TABLE pending_trade_signals ADD COLUMN user_id VARCHAR(64);",
                "ALTER TABLE pending_trade_signals ADD COLUMN approved_by VARCHAR(255);",
                "ALTER TABLE pending_trade_signals ADD COLUMN rejected_by VARCHAR(255);",
                "ALTER TABLE pending_trade_signals ADD COLUMN status_history_json TEXT;",
            ]:
                try:
                    conn.execute(text(col_sql))
                    conn.commit()
                except Exception:
                    pass
        logger.info("pending_signals_db_initialized", table=PendingSignalRecord.__tablename__)
    except Exception as e:
        logger.error("pending_signals_db_init_failed", error=str(e))
        raise


def insert_pending_signal(record_data: Dict[str, Any]) -> bool:
    """Insert a new pending signal record."""
    session = db_session()
    try:
        record = PendingSignalRecord(**record_data)
        session.add(record)
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error("insert_pending_signal_failed", error=str(e), signal_id=record_data.get("signal_id"))
        raise
    finally:
        session.close()


def get_pending_signal_by_id(signal_id: str) -> Optional[PendingSignalRecord]:
    """Query a pending signal record by its primary key ID."""
    session = db_session()
    try:
        return session.query(PendingSignalRecord).filter_by(signal_id=signal_id).first()
    finally:
        session.close()


def query_pending_signals(status: Optional[str] = None) -> List[PendingSignalRecord]:
    """Query pending signal records with optional status filter."""
    session = db_session()
    try:
        query = session.query(PendingSignalRecord)
        if status:
            query = query.filter_by(status=status)
        return query.order_by(PendingSignalRecord.created_at.desc()).all()
    finally:
        session.close()


def atomic_transition_state(
    signal_id: str,
    from_status: str | List[str] | Tuple[str, ...],
    to_status: str,
    **kwargs: Any,
) -> bool:
    """
    Atomic Compare-And-Swap (CAS) update.
    Returns True if exactly 1 row was transitioned from from_status to to_status.
    Returns False if 0 rows matched (meaning signal was already transitioned or not found).
    """
    session = db_session()
    try:
        update_values = {"status": to_status}
        update_values.update(kwargs)
        if isinstance(from_status, (list, tuple, set)):
            status_filter = PendingSignalRecord.status.in_(list(from_status))
        else:
            status_filter = (PendingSignalRecord.status == from_status)

        rows_updated = (
            session.query(PendingSignalRecord)
            .filter(
                PendingSignalRecord.signal_id == signal_id,
                status_filter,
            )
            .update(update_values, synchronize_session=False)
        )
        session.commit()
        return rows_updated == 1
    except Exception as e:
        session.rollback()
        logger.error("atomic_transition_failed", error=str(e), signal_id=signal_id)
        raise
    finally:
        session.close()


def update_signal_record(signal_id: str, **kwargs: Any) -> bool:
    """Unconditionally update attributes of a signal record."""
    session = db_session()
    try:
        rows = (
            session.query(PendingSignalRecord)
            .filter_by(signal_id=signal_id)
            .update(kwargs)
        )
        session.commit()
        return rows > 0
    except Exception as e:
        session.rollback()
        logger.error("update_signal_record_failed", error=str(e), signal_id=signal_id)
        raise
    finally:
        session.close()


def append_status_history_entry(signal_id: str, entry: Dict[str, Any]) -> None:
    """Append an immutable audit entry to status_history_json of a signal record."""
    session = db_session()
    try:
        rec = session.query(PendingSignalRecord).filter_by(signal_id=signal_id).first()
        if rec:
            history = json.loads(rec.status_history_json) if rec.status_history_json else []
            history.append(entry)
            rec.status_history_json = json.dumps(history)
            session.commit()
    except Exception as e:
        session.rollback()
        logger.error("append_status_history_failed", error=str(e), signal_id=signal_id)
    finally:
        session.close()

