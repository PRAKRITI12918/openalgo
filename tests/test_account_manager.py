import os
import pytest
from utils.account_manager import (
    save_account_profile,
    list_account_profiles,
    get_active_profile_name,
    delete_account_profile,
    mask_secret,
    _encrypt,
    _decrypt,
)


def test_encryption_roundtrip():
    secret = "730627e3-13ab-47da-a37c-172789d2ed22"
    enc = _encrypt(secret)
    assert enc != secret
    dec = _decrypt(enc)
    assert dec == secret


def test_mask_secret():
    assert mask_secret("1110835259:::3d418c30", 6) == "111083********"
    assert mask_secret("", 4) == ""
    assert mask_secret("abc", 4) == "********"


def test_save_and_list_profile():
    # Save a test profile
    ok, msg = save_account_profile(
        name="test_dhan_account",
        broker="dhan",
        api_key="1119999999:::testkey123",
        api_secret="test_secret_guid_456",
        description="Test Account",
    )
    assert ok is True
    assert "saved successfully" in msg

    profiles = list_account_profiles()
    names = [p["name"] for p in profiles]
    assert "test_dhan_account" in names

    # Verify fields
    p = next(p for p in profiles if p["name"] == "test_dhan_account")
    assert p["broker"] == "dhan"
    assert p["client_id"] == "1119999999"
    assert "test_secret" not in p["api_key_masked"]

    # Delete test profile
    del_ok, _ = delete_account_profile("test_dhan_account")
    assert del_ok is True
