"""
Account Profile Manager for OpenAlgo.
Enables saving, listing, switching, and managing multiple broker accounts (Dhan, Zerodha, Fyers, Angel, etc.)
with encrypted secret storage and automated environment switching.
"""

import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
PROFILES_FILE = os.path.join(PROJECT_ROOT, "db", "account_profiles.json")


def _get_fernet() -> Fernet:
    """Derive Fernet cipher from API_KEY_PEPPER and FERNET_SALT."""
    load_dotenv(ENV_PATH, override=False)
    pepper = os.getenv("API_KEY_PEPPER", "OPENALGO_DEFAULT_PEPPER_KEY_32_BYTES_HEX_1234567890")
    salt_raw = os.getenv("FERNET_SALT", "")
    try:
        salt = bytes.fromhex(salt_raw) if len(salt_raw) >= 32 else b"openalgo_static_salt"
    except Exception:
        salt = b"openalgo_static_salt"

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode()))
    return Fernet(key)


def _encrypt(text: str) -> str:
    """Encrypt a secret string."""
    if not text:
        return ""
    f = _get_fernet()
    return f.encrypt(text.encode()).decode()


def _decrypt(cipher_text: str) -> str:
    """Decrypt an encrypted secret string."""
    if not cipher_text:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(cipher_text.encode()).decode()
    except Exception:
        return ""


def _load_profiles_data() -> Dict[str, Any]:
    """Load profiles storage file."""
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    if not os.path.exists(PROFILES_FILE):
        return {"profiles": {}, "active_profile": None}
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"profiles": {}, "active_profile": None}


def _save_profiles_data(data: Dict[str, Any]) -> None:
    """Save profiles to JSON file."""
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask sensitive string."""
    if not value:
        return ""
    if len(value) <= show_chars:
        return "*" * 8
    return value[:show_chars] + "*" * 8


def save_account_profile(
    name: str,
    broker: str,
    api_key: str,
    api_secret: str,
    redirect_url: Optional[str] = None,
    api_key_market: Optional[str] = None,
    api_secret_market: Optional[str] = None,
    description: str = "",
) -> Tuple[bool, str]:
    """
    Save or update an account profile.
    """
    name = name.strip().lower().replace(" ", "_")
    if not name:
        return False, "Profile name is required"
    if not broker:
        return False, "Broker name is required"
    if not api_key:
        return False, "API Key is required"
    if not api_secret:
        return False, "API Secret is required"

    if not redirect_url:
        redirect_url = f"http://127.0.0.1:5000/{broker}/callback"

    # Extract client id if present in api_key (e.g. 1110835259:::3d418c30)
    client_id = ""
    if ":::" in api_key:
        client_id = api_key.split(":::", 1)[0]

    data = _load_profiles_data()
    profiles = data.setdefault("profiles", {})

    encrypted_secret = _encrypt(api_secret)
    encrypted_secret_market = _encrypt(api_secret_market) if api_secret_market else ""

    profiles[name] = {
        "name": name,
        "broker": broker.lower(),
        "client_id": client_id,
        "api_key": api_key,
        "api_secret_encrypted": encrypted_secret,
        "api_key_market": api_key_market or "",
        "api_secret_market_encrypted": encrypted_secret_market,
        "redirect_url": redirect_url,
        "description": description or f"{broker.upper()} account ({client_id or name})",
        "updated_at": datetime.utcnow().isoformat(),
    }

    _save_profiles_data(data)
    return True, f"Profile '{name}' saved successfully"


def list_account_profiles() -> List[Dict[str, Any]]:
    """
    List all saved account profiles with masked credentials and active status.
    """
    data = _load_profiles_data()
    profiles = data.get("profiles", {})
    active_profile = get_active_profile_name()

    result = []
    for name, p in profiles.items():
        result.append(
            {
                "name": name,
                "broker": p.get("broker", ""),
                "client_id": p.get("client_id", ""),
                "api_key_masked": mask_secret(p.get("api_key", ""), 6),
                "redirect_url": p.get("redirect_url", ""),
                "description": p.get("description", ""),
                "is_active": (name == active_profile),
                "updated_at": p.get("updated_at", ""),
            }
        )
    return result


def get_active_profile_name() -> Optional[str]:
    """Identify which saved profile currently matches the .env file."""
    if not os.path.exists(ENV_PATH):
        return None

    load_dotenv(ENV_PATH, override=True)
    current_key = os.getenv("BROKER_API_KEY", "")
    current_url = os.getenv("REDIRECT_URL", "")

    data = _load_profiles_data()
    profiles = data.get("profiles", {})

    # Check matching profile
    for name, p in profiles.items():
        if p.get("api_key") == current_key and p.get("redirect_url") == current_url:
            return name

    return data.get("active_profile")


def switch_account_profile(name: str, restart_server: bool = True) -> Tuple[bool, str]:
    """
    Switch active OpenAlgo broker configuration to the specified profile.
    Updates .env file and optionally restarts the server process.
    """
    name = name.strip().lower().replace(" ", "_")
    data = _load_profiles_data()
    profiles = data.get("profiles", {})

    if name not in profiles:
        available = ", ".join(profiles.keys()) if profiles else "None"
        return False, f"Profile '{name}' not found. Available profiles: {available}"

    profile = profiles[name]
    broker = profile.get("broker", "")
    api_key = profile.get("api_key", "")
    encrypted_secret = profile.get("api_secret_encrypted", "")
    api_secret = _decrypt(encrypted_secret)
    redirect_url = profile.get("redirect_url", f"http://127.0.0.1:5000/{broker}/callback")
    api_key_market = profile.get("api_key_market", "")
    api_secret_market = _decrypt(profile.get("api_secret_market_encrypted", ""))

    if not api_secret:
        return False, f"Failed to decrypt API secret for profile '{name}'"

    # Read and update .env
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        def update_val(c: str, k: str, v: str) -> str:
            pattern = rf"^({re.escape(k)}\s*=\s*).*$"
            if "'" in v:
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                new_v = f'"{escaped}"'
            else:
                new_v = f"'{v}'"
            replacement = rf"\g<1>{new_v}"
            new_c, count = re.subn(pattern, replacement, c, flags=re.MULTILINE)
            if count == 0:
                if not new_c.endswith("\n"):
                    new_c += "\n"
                new_c += f"{k} = {new_v}\n"
            return new_c

        content = update_val(content, "BROKER_API_KEY", api_key)
        content = update_val(content, "BROKER_API_SECRET", api_secret)
        content = update_val(content, "REDIRECT_URL", redirect_url)

        if api_key_market:
            content = update_val(content, "BROKER_API_KEY_MARKET", api_key_market)
        if api_secret_market:
            content = update_val(content, "BROKER_API_SECRET_MARKET", api_secret_market)

        with open(ENV_PATH, "w", encoding="utf-8") as f:
            f.write(content)

        # Update active marker
        data["active_profile"] = name
        _save_profiles_data(data)

        # Clear in-memory auth caches if server is running
        try:
            from database.auth_db import clear_all_auth_caches
            clear_all_auth_caches()
        except Exception:
            pass

        restart_msg = ""
        if restart_server:
            restarted, r_msg = restart_openalgo_server()
            restart_msg = f" ({r_msg})"

        return True, f"Successfully switched active account to '{name}' ({broker.upper()}){restart_msg}"

    except Exception as e:
        return False, f"Error updating .env: {str(e)}"


def delete_account_profile(name: str) -> Tuple[bool, str]:
    """Delete a saved profile."""
    name = name.strip().lower().replace(" ", "_")
    data = _load_profiles_data()
    profiles = data.get("profiles", {})

    if name not in profiles:
        return False, f"Profile '{name}' does not exist"

    del profiles[name]
    if data.get("active_profile") == name:
        data["active_profile"] = None

    _save_profiles_data(data)
    return True, f"Profile '{name}' deleted successfully"


def restart_openalgo_server() -> Tuple[bool, str]:
    """
    Find running OpenAlgo process on port 5000, stop it, and start a new daemon process.
    """
    try:
        # Check running process on port 5000 using PowerShell
        find_cmd = 'netstat -ano | findstr :5000'
        out = subprocess.run(find_cmd, shell=True, capture_output=True, text=True).stdout
        pids = set()
        for line in out.splitlines():
            if "LISTENING" in line:
                parts = line.strip().split()
                if len(parts) >= 5:
                    pids.add(parts[-1])

        # Kill existing PID on 5000
        for pid in pids:
            try:
                subprocess.run(f"Stop-Process -Id {pid} -Force", shell=True, capture_output=True)
            except Exception:
                pass

        # Spawn new app.py in background
        python_exe = sys.executable
        app_path = os.path.join(PROJECT_ROOT, "app.py")
        subprocess.Popen([python_exe, app_path], cwd=PROJECT_ROOT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)

        return True, "Server restarted on port 5000"
    except Exception as e:
        return False, f"Server restart notification: {str(e)}"
