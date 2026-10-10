"""
Database Models for Multi-Account Broker Management.
Provides isolated multi-account storage, status tracking, and active account resolution.

HARD CONSTRAINTS:
- Single Active Pointer: ActiveAccountSelection maintains exactly one active account row per user.
- Foreign Key & Ownership: active_broker_account_id must strictly reference a BrokerAccount owned by the same user.
- Masked Display: External broker credentials/client IDs are masked; raw tokens are never exposed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import os
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
import structlog

logger = structlog.get_logger("openalgo.account_models")

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


class BrokerAccountStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"


class BrokerAccount(Base):
    """
    SQLAlchemy model representing a specific connected broker account owned by a user.
    A user may possess multiple accounts across the same or different brokers.
    """
    __tablename__ = "broker_accounts"

    id = Column(String(64), primary_key=True, default=lambda: f"acc_{uuid.uuid4().hex[:12]}")
    user_id = Column(String(100), nullable=False, index=True)
    broker_id = Column(String(50), nullable=False, index=True)
    account_label = Column(String(100), nullable=False)
    external_account_id = Column(String(100), nullable=False)
    status = Column(
        String(30),
        default=BrokerAccountStatus.CONNECTED.value,
        nullable=False,
        index=True,
    )
    token_ref = Column(Text, nullable=False)  # Pointer/encrypted reference to secure token storage, NEVER raw token
    connected_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_verified_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "broker_id", "external_account_id", name="uq_user_broker_account"),
        Index("idx_broker_accounts_user_status", "user_id", "status"),
    )

    def mask_external_id(self) -> str:
        """Mask external broker account ID for display (e.g. 1113284554 -> ******4554)."""
        s = str(self.external_account_id).strip()
        if len(s) <= 4:
            return f"**{s}"
        return f"{'*' * (len(s) - 4)}{s[-4:]}"

    def to_display_dict(self, is_active: bool = False) -> Dict[str, Any]:
        """Display-safe serialization. Strictly excludes raw tokens or secrets."""
        return {
            "account_id": self.id,
            "broker_id": self.broker_id,
            "broker_display_name": self.broker_id.capitalize(),
            "account_label": self.account_label,
            "masked_external_id": self.mask_external_id(),
            "status": self.status,
            "is_active": is_active,
            "connected_at": self.connected_at.isoformat() if self.connected_at else "",
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else "",
        }


class ActiveAccountSelection(Base):
    """
    SQLAlchemy model maintaining exactly one active account pointer per user.
    Prevents race conditions and multiple-active anomalies.
    """
    __tablename__ = "active_account_selections"

    user_id = Column(String(100), primary_key=True, index=True)
    active_broker_account_id = Column(
        String(64),
        ForeignKey("broker_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    account = relationship("BrokerAccount", foreign_keys=[active_broker_account_id])

    __table_args__ = (
        Index("idx_active_acc_user", "user_id"),
    )


def init_account_db() -> None:
    """Initialize broker_accounts and active_account_selections tables."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("account_db_initialized")
    except Exception as e:
        logger.error("account_db_init_failed", error=str(e))
