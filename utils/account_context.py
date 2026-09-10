"""
utils/account_context.py - Account Context Layer for OpenAlgo.

Enables multi-broker account support (Dhan, Zerodha, Fyers, Angel One, etc.)
with full data isolation, atomic switching, and zero disruption to existing
single-broker API contracts and services.

Architecture:
1. Legacy Active Pointer: Auth row where name = username (e.g. "Prakriti Dhanasekar")
   always mirrors the active account's credentials. This ensures all existing
   code calling get_auth_token(username) or get_auth_token_broker(api_key)
   functions with 100% backward compatibility.
2. Per-Account Isolated Storage: Each connected account is stored in Auth
   with name = f"account:{username}:{broker}:{client_id}".
3. Switching: switch_active_account(username, account_id) copies the selected
   account's credentials into the active pointer row and updates session["broker"]
   and session["active_account_id"] with zero process restart.
"""

from datetime import datetime
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from flask import has_request_context, session

from database.auth_db import (
    Auth,
    auth_cache,
    broker_cache,
    db_session,
    decrypt_token,
    encrypt_token,
    feed_token_cache,
)
from utils.auth_utils import mask_api_credential
from utils.logging import get_logger

logger = get_logger(__name__)

ACCOUNT_PREFIX = "account:"


def _build_account_name(username: str, broker: str, client_id: str) -> str:
    """Build standardized account identifier string for Auth.name."""
    clean_user = username.strip()
    clean_broker = broker.strip().lower()
    clean_client = str(client_id).strip()
    return f"{ACCOUNT_PREFIX}{clean_user}:{clean_broker}:{clean_client}"


def _parse_account_name(name: str) -> Optional[Dict[str, str]]:
    """Parse account name into components."""
    if not name.startswith(ACCOUNT_PREFIX):
        return None
    parts = name[len(ACCOUNT_PREFIX):].split(":", 2)
    if len(parts) == 3:
        return {
            "username": parts[0],
            "broker": parts[1],
            "client_id": parts[2],
            "account_id": f"{parts[1]}_{parts[2]}",
        }
    return None


def mask_client_id(client_id: str) -> str:
    """Mask client id for safe display (e.g. 1113284554 -> ******4554)."""
    if not client_id:
        return "Unknown"
    s = str(client_id).strip()
    if len(s) <= 4:
        return f"**{s}"
    return f"{'*' * (len(s) - 4)}{s[-4:]}"


def get_connected_accounts(username: str) -> List[Dict[str, Any]]:
    """Get all connected broker accounts for the given user.
    
    Returns list of dicts with masked client IDs and active status.
    """
    if not username:
        return []

    try:
        prefix = f"{ACCOUNT_PREFIX}{username.strip()}:"
        records = (
            Auth.query.filter(Auth.name.like(f"{prefix}%"))
            .all()
        )

        active_account_id = None
        if has_request_context():
            active_account_id = session.get("active_account_id")

        # Also check current active row to determine which broker/account is active
        active_row = Auth.query.filter_by(name=username.strip()).first()
        active_broker = active_row.broker if active_row else None
        active_client = active_row.user_id if active_row else None

        accounts: List[Dict[str, Any]] = []

        # If we have existing accounts in DB
        for r in records:
            meta = _parse_account_name(r.name)
            if not meta:
                continue

            acc_id = meta["account_id"]
            # Active if matches session active_account_id or matches active pointer row
            is_active = False
            if active_account_id:
                is_active = (acc_id == active_account_id)
            elif active_broker and active_client:
                is_active = (meta["broker"] == active_broker and meta["client_id"] == str(active_client))

            accounts.append({
                "account_id": acc_id,
                "broker": meta["broker"],
                "broker_name": meta["broker"].capitalize(),
                "client_id": meta["client_id"],
                "client_id_masked": mask_client_id(meta["client_id"]),
                "is_active": is_active,
                "is_revoked": bool(r.is_revoked),
                "status": "revoked" if r.is_revoked else ("active" if is_active else "connected"),
            })

        # Self-healing / Migration: If the user has a legacy active row in Auth but NO per-account row yet,
        # create one automatically so their currently working account (e.g. Dhan) appears seamlessly!
        if active_row and active_row.broker and active_row.user_id and not accounts:
            legacy_acc_id = f"{active_row.broker}_{active_row.user_id}"
            save_connected_account(
                username=username,
                broker=active_row.broker,
                client_id=active_row.user_id,
                auth_token=decrypt_token(active_row.auth),
                feed_token=decrypt_token(active_row.feed_token) if active_row.feed_token else None,
                make_active=True,
            )
            accounts.append({
                "account_id": legacy_acc_id,
                "broker": active_row.broker,
                "broker_name": active_row.broker.capitalize(),
                "client_id": active_row.user_id,
                "client_id_masked": mask_client_id(active_row.user_id),
                "is_active": True,
                "is_revoked": bool(active_row.is_revoked),
                "status": "active",
            })

        return accounts

    except Exception as e:
        logger.exception(f"Error querying connected accounts for {username}: {e}")
        return []


def get_active_account(username: str) -> Optional[Dict[str, Any]]:
    """Get the currently active account for the user."""
    accounts = get_connected_accounts(username)
    for acc in accounts:
        if acc["is_active"]:
            return acc
    return accounts[0] if accounts else None


def save_connected_account(
    username: str,
    broker: str,
    client_id: str,
    auth_token: str,
    feed_token: Optional[str] = None,
    make_active: bool = True,
) -> str:
    """Save or update a broker account in isolated storage and optionally make active.
    
    Returns the account_id.
    """
    clean_user = username.strip()
    clean_broker = broker.strip().lower()
    clean_client = str(client_id).strip()
    account_name = _build_account_name(clean_user, clean_broker, clean_client)
    account_id = f"{clean_broker}_{clean_client}"

    encrypted_token = encrypt_token(auth_token)
    encrypted_feed_token = encrypt_token(feed_token) if feed_token else None

    # Upsert the isolated per-account Auth row
    acc_obj = Auth.query.filter_by(name=account_name).first()
    if acc_obj:
        acc_obj.auth = encrypted_token
        acc_obj.feed_token = encrypted_feed_token
        acc_obj.broker = clean_broker
        acc_obj.user_id = clean_client
        acc_obj.is_revoked = False
    else:
        acc_obj = Auth(
            name=account_name,
            auth=encrypted_token,
            feed_token=encrypted_feed_token,
            broker=clean_broker,
            user_id=clean_client,
            is_revoked=False,
        )
        db_session.add(acc_obj)
    db_session.commit()
    logger.info(f"Saved account record '{account_name}' (ID: {account_id})")

    if make_active:
        switch_active_account(clean_user, account_id)

    return account_id


def switch_active_account(username: str, account_id: str) -> Tuple[bool, str]:
    """Switch active account for user.
    
    Atomically synchronizes the active pointer row (`name = username`)
    and updates the session context without disconnecting any account.
    """
    clean_user = username.strip()
    clean_acc_id = account_id.strip()

    # Find the target account record
    parts = clean_acc_id.split("_", 1)
    if len(parts) != 2:
        return False, f"Invalid account ID format: {clean_acc_id}"

    broker, client_id = parts[0].lower(), parts[1]
    account_name = _build_account_name(clean_user, broker, client_id)

    target = Auth.query.filter_by(name=account_name).first()
    if not target:
        # Fallback search by broker and user_id under this user's accounts
        prefix = f"{ACCOUNT_PREFIX}{clean_user}:"
        matches = Auth.query.filter(
            Auth.name.like(f"{prefix}%"),
            Auth.broker == broker,
            Auth.user_id == client_id,
        ).first()
        target = matches

    if not target:
        return False, f"Account '{clean_acc_id}' not found in connected accounts."

    # Update the legacy active pointer row in Auth (name = clean_user)
    active_row = Auth.query.filter_by(name=clean_user).first()
    if active_row:
        active_row.auth = target.auth
        active_row.feed_token = target.feed_token
        active_row.broker = target.broker
        active_row.user_id = target.user_id
        active_row.is_revoked = target.is_revoked
    else:
        active_row = Auth(
            name=clean_user,
            auth=target.auth,
            feed_token=target.feed_token,
            broker=target.broker,
            user_id=target.user_id,
            is_revoked=target.is_revoked,
        )
        db_session.add(active_row)
    db_session.commit()

    # Clear all caches so the new credentials take effect immediately
    auth_cache.clear()
    broker_cache.clear()
    feed_token_cache.clear()

    # Update Flask session if in request context
    if has_request_context():
        session["active_account_id"] = clean_acc_id
        session["broker"] = target.broker
        session["USER_ID"] = target.user_id
        session["logged_in"] = True

    logger.info(f"Successfully switched active account for {clean_user} to '{clean_acc_id}' ({target.broker.upper()})")
    return True, f"Switched active account to {target.broker.upper()} ({mask_client_id(target.user_id)})"


def disconnect_account(username: str, account_id: str) -> Tuple[bool, str]:
    """Disconnect / revoke a specific broker account.
    
    If it was the active account, switches to another connected account if available.
    """
    clean_user = username.strip()
    clean_acc_id = account_id.strip()

    parts = clean_acc_id.split("_", 1)
    if len(parts) != 2:
        return False, "Invalid account identifier"

    broker, client_id = parts[0].lower(), parts[1]
    account_name = _build_account_name(clean_user, broker, client_id)

    target = Auth.query.filter_by(name=account_name).first()
    if not target:
        return False, f"Account '{clean_acc_id}' not found"

    # Mark revoked
    target.is_revoked = True
    db_session.commit()

    # Check if this was the active account
    active_acc = get_active_account(clean_user)
    was_active = active_acc and active_acc.get("account_id") == clean_acc_id

    remaining = [
        a for a in get_connected_accounts(clean_user)
        if a["account_id"] != clean_acc_id and not a["is_revoked"]
    ]

    if was_active:
        if remaining:
            # Switch to first remaining active account
            switch_active_account(clean_user, remaining[0]["account_id"])
        else:
            # No accounts left
            active_row = Auth.query.filter_by(name=clean_user).first()
            if active_row:
                active_row.is_revoked = True
                db_session.commit()
            if has_request_context():
                session.pop("active_account_id", None)
                session.pop("broker", None)

    return True, f"Account {broker.upper()} ({mask_client_id(client_id)}) disconnected."
