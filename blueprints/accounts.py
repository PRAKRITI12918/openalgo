"""
blueprints/accounts.py - REST API for Multi-Broker Account Management.

Endpoints:
- GET /api/accounts: List connected accounts and currently active account
- POST /api/accounts/switch: Switch active account
- DELETE /api/accounts/<account_id>: Disconnect an account
- GET /api/accounts/installed-brokers: Supported brokers with schema definitions
- POST /api/accounts/connect-zerodha: Connect Zerodha via Kite Connect credentials/OAuth
"""

import hashlib
import os
from flask import Blueprint, jsonify, request, session

from brokers import BROKER_SCHEMA_REGISTRY, get_all_brokers, get_broker_schema
from database.user_db import find_user_by_username
from limiter import limiter
from utils.account_context import (
    disconnect_account,
    get_active_account,
    get_connected_accounts,
    save_connected_account,
    switch_active_account,
)
from utils.auth_utils import handle_auth_success
from utils.config import get_broker_api_key, get_broker_api_secret, get_login_rate_limit_hour, get_login_rate_limit_min
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

accounts_bp = Blueprint("accounts_bp", __name__, url_prefix="/api/accounts")

LOGIN_RATE_LIMIT_MIN = get_login_rate_limit_min()
LOGIN_RATE_LIMIT_HOUR = get_login_rate_limit_hour()


def _resolve_current_username() -> str:
    """Resolve current logged-in username or fallback to default admin."""
    if "user" in session and session["user"]:
        return session["user"]
    admin = find_user_by_username()
    return admin.username if admin else "admin"


@accounts_bp.route("", methods=["GET"])
@accounts_bp.route("/", methods=["GET"])
def list_accounts():
    """List all connected broker accounts and the currently active account."""
    username = _resolve_current_username()
    accounts = get_connected_accounts(username)
    active = get_active_account(username)

    return jsonify({
        "status": "success",
        "username": username,
        "accounts": accounts,
        "active_account": active,
        "count": len(accounts),
    }), 200


@accounts_bp.route("/switch", methods=["POST"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
def switch_account_endpoint():
    """Switch active account to the specified account_id."""
    data = request.get_json(silent=True) or {}
    account_id = data.get("account_id") or request.form.get("account_id")

    if not account_id:
        return jsonify({"status": "error", "message": "account_id is required"}), 400

    username = _resolve_current_username()
    success, message = switch_active_account(username, account_id)

    if success:
        active = get_active_account(username)
        return jsonify({
            "status": "success",
            "message": message,
            "active_account": active,
        }), 200
    else:
        return jsonify({"status": "error", "message": message}), 404


@accounts_bp.route("/<account_id>", methods=["DELETE"])
def disconnect_account_endpoint(account_id):
    """Disconnect / revoke a connected broker account."""
    username = _resolve_current_username()
    success, message = disconnect_account(username, account_id)

    if success:
        return jsonify({
            "status": "success",
            "message": message,
            "accounts": get_connected_accounts(username),
            "active_account": get_active_account(username),
        }), 200
    else:
        return jsonify({"status": "error", "message": message}), 400


@accounts_bp.route("/installed-brokers", methods=["GET"])
def installed_brokers():
    """Return all genuine brokers installed in broker/ with their schemas."""
    try:
        brokers_dict = get_all_brokers()
        # Filter to brokers that actually exist in broker/
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        broker_dir = os.path.join(project_root, "broker")

        result = []
        for b_id, schema in brokers_dict.items():
            folder_path = os.path.join(broker_dir, b_id)
            if os.path.exists(folder_path):
                result.append({
                    "broker_id": b_id,
                    "name": schema.get("name", b_id.capitalize()),
                    "category": schema.get("category", "Discount"),
                    "auth_type": schema.get("auth_type", "oauth"),
                    "logo": schema.get("logo", b_id),
                    "badge": schema.get("badge", ""),
                    "docs_url": schema.get("docs_url", ""),
                    "alert_notice": schema.get("alert_notice", ""),
                    "fields": schema.get("fields", []),
                })

        return jsonify({
            "status": "success",
            "brokers": result,
            "count": len(result),
        }), 200
    except Exception as e:
        logger.exception(f"Error listing installed brokers: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@accounts_bp.route("/connect-zerodha", methods=["POST"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def connect_zerodha():
    """Handle Zerodha Kite Connect authentication.

    Supports:
    1. Initiating Kite OAuth redirect URL with provided API key.
    2. Exchanging a request_token directly (via API key + API secret + request_token).
    """
    payload = request.get_json(silent=True) or {}
    api_key = (
        payload.get("api_key")
        or payload.get("broker_api_key")
        or request.form.get("api_key")
        or get_broker_api_key()
    )
    api_secret = (
        payload.get("api_secret")
        or payload.get("broker_api_secret")
        or request.form.get("api_secret")
        or get_broker_api_secret()
    )
    request_token = payload.get("request_token") or request.form.get("request_token")

    if not api_key:
        return jsonify({
            "status": "error",
            "message": "Zerodha Kite API Key is required.",
        }), 400

    # Step A: If request_token is provided, exchange it immediately
    if request_token:
        if not api_secret:
            return jsonify({
                "status": "error",
                "message": "Zerodha Kite API Secret is required to exchange the request token.",
            }), 400

        try:
            from utils.httpx_client import get_httpx_client
            client = get_httpx_client()

            checksum_input = f"{api_key}{request_token}{api_secret}"
            checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

            url = "https://api.kite.trade/session/token"
            data = {"api_key": api_key, "request_token": request_token, "checksum": checksum}
            headers = {"X-Kite-Version": "3"}

            response = client.post(url, headers=headers, data=data)
            response.raise_for_status()
            res_json = response.json()

            if "data" in res_json and "access_token" in res_json["data"]:
                kite_token = res_json["data"]["access_token"]
                client_id = res_json["data"].get("user_id", "zerodha_user")
                full_auth_token = f"{api_key}:{kite_token}"

                username = _resolve_current_username()
                session["user"] = username

                # Save into isolated storage and make active
                acc_id = save_connected_account(
                    username=username,
                    broker="zerodha",
                    client_id=client_id,
                    auth_token=full_auth_token,
                    make_active=True,
                )

                handle_auth_success(
                    full_auth_token,
                    username,
                    "zerodha",
                    user_id=client_id,
                )

                return jsonify({
                    "status": "success",
                    "message": "Zerodha Kite account connected successfully!",
                    "account_id": acc_id,
                    "client_id": client_id,
                    "redirect_url": "/dashboard",
                }), 200
            else:
                return jsonify({
                    "status": "error",
                    "message": "Kite session token response missing access token.",
                }), 400

        except Exception as e:
            logger.exception(f"Error exchanging Zerodha request token: {e}")
            return jsonify({
                "status": "error",
                "message": f"Kite token exchange failed: {str(e)}",
            }), 400

    # Step B: If no request_token yet, generate Kite OAuth Login URL
    kite_login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    return jsonify({
        "status": "oauth_redirect",
        "login_url": kite_login_url,
        "message": "Redirect to Kite to authenticate your Zerodha account.",
    }), 200
