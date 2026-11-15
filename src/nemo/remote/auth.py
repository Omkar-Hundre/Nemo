"""Device Authentication and Security for Nemo Remote.

Generates and persists a secure, device-locked Stream Key.
Ensures only the user's authorized phone can connect to the PC live stream.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import secrets

logger = logging.getLogger(__name__)

AUTH_FILE = Path.home() / ".nemo" / "device_auth.json"


def get_device_key() -> str:
    """Retrieve existing 6-digit device key or generate a secure new one."""
    # 1. Environment variable override
    env_key = os.getenv("NEMO_DEVICE_KEY", "").strip()
    if env_key:
        return env_key

    # 2. Stored key file in ~/.nemo/device_auth.json
    try:
        if AUTH_FILE.exists():
            data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            saved_key = str(data.get("device_key", "")).strip()
            if saved_key:
                return saved_key
    except Exception as exc:
        logger.debug("Failed to read device_auth.json: %s", exc)

    # 3. Generate a memorable secure 6-digit PIN
    new_key = f"{secrets.randbelow(900000) + 100000}"
    try:
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps({"device_key": new_key, "description": "Nemo Mobile Remote Device Authorization Key"}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not persist device_auth.json: %s", exc)

    return new_key


def reset_device_key() -> str:
    """Regenerate a fresh device key."""
    new_key = f"{secrets.randbelow(900000) + 100000}"
    try:
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps({"device_key": new_key, "description": "Nemo Mobile Remote Device Authorization Key"}, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Could not write device_auth.json: %s", exc)
    return new_key
