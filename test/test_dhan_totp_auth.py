"""Tests for Dhan Direct TOTP Authentication flow."""

from unittest.mock import MagicMock
import pytest
from broker.dhan.api.auth_api import generate_access_token_with_totp, authenticate_broker


def test_generate_access_token_with_totp_missing_params():
    token, meta, err = generate_access_token_with_totp("", "123456", "123456")
    assert token is None
    assert "required" in err.lower()

    token, meta, err = generate_access_token_with_totp("1113284554", "", "123456")
    assert token is None
    assert "required" in err.lower()

    token, meta, err = generate_access_token_with_totp("1113284554", "123456", "")
    assert token is None
    assert "required" in err.lower()


def test_generate_access_token_with_totp_success(monkeypatch):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "success",
        "accessToken": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dhan-test-token",
        "dhanClientId": "1113284554",
        "dhanClientName": "Test User",
        "expiryTime": "2026-08-30 06:00:00",
    }
    mock_client.post.return_value = mock_resp

    monkeypatch.setattr("broker.dhan.api.auth_api.get_httpx_client", lambda: mock_client)

    token, meta, err = generate_access_token_with_totp("1113284554", "123456", "654321")
    assert token == "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dhan-test-token"
    assert err is None
    assert meta["dhan_client_id"] == "1113284554"


def test_generate_access_token_with_totp_error(monkeypatch):
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "error",
        "message": "Invalid TOTP",
    }
    mock_client.post.return_value = mock_resp

    monkeypatch.setattr("broker.dhan.api.auth_api.get_httpx_client", lambda: mock_client)

    token, meta, err = generate_access_token_with_totp("1113284554", "123456", "000000")
    assert token is None
    assert err == "Invalid TOTP"


def test_authenticate_broker_with_pin_and_totp(monkeypatch):
    monkeypatch.setattr(
        "broker.dhan.api.auth_api.generate_access_token_with_totp",
        lambda client_id, pin, totp: ("mock-access-token", {"dhan_client_id": client_id}, None),
    )

    token, user_id, err = authenticate_broker("1113284554", pin="123456", totp="654321")
    assert token == "mock-access-token"
    assert user_id == "1113284554"
    assert err is None
