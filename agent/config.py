"""
Agent Configuration and Persistent Storage Manager.

Maintains agent settings and DPAPI-protected credentials in ProgramData
or local development directory.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from agent.crypto import dpapi_decrypt, dpapi_encrypt, mask_secret

AGENT_VERSION = "1.0.0"
DEFAULT_PORT = os.environ.get("SENTINELX_BACKEND_PORT", "8001")
DEFAULT_SERVER_URL = f"http://127.0.0.1:{DEFAULT_PORT}/api/v1"


def get_data_dir() -> Path:
    """Returns the base data directory for agent storage."""
    env_dir = os.environ.get("SENTINELX_AGENT_DIR")
    if env_dir:
        p = Path(env_dir)
    elif sys.platform == "win32":
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        p = Path(program_data) / "SentinelX" / "agent"
    else:
        p = Path.home() / ".sentinelx_agent"

    p.mkdir(parents=True, exist_ok=True)
    return p


def get_config_path() -> Path:
    return get_data_dir() / "config.json"


def get_key_path() -> Path:
    return get_data_dir() / "device_key.dat"


def get_log_dir() -> Path:
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


class AgentConfig:
    """In-memory configuration wrapper with persistent disk backing."""

    def __init__(self) -> None:
        self.server_url: str = DEFAULT_SERVER_URL
        self.device_id: str | None = None
        self.device_name: str | None = None
        self.operating_system: str | None = None
        self.agent_version: str = AGENT_VERSION
        self.enabled_categories: set[str] = set()
        self.consent_version: str = "v1.0"
        self.last_heartbeat_at: str | None = None
        self.load()

    def load(self) -> None:
        """Loads configuration from JSON file."""
        cfg_file = get_config_path()
        if cfg_file.exists():
            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.server_url = data.get("server_url", DEFAULT_SERVER_URL).rstrip("/")
                if not self.server_url.endswith("/api/v1"):
                    # normalize
                    if "/api/v1" not in self.server_url:
                        self.server_url += "/api/v1"
                self.device_id = data.get("device_id")
                self.device_name = data.get("device_name")
                self.operating_system = data.get("operating_system")
                self.agent_version = data.get("agent_version", AGENT_VERSION)
                self.enabled_categories = set(data.get("enabled_categories", []))
                self.consent_version = data.get("consent_version", "v1.0")
                self.last_heartbeat_at = data.get("last_heartbeat_at")
            except Exception:
                pass

    def save(self) -> None:
        """Persists configuration to JSON file."""
        cfg_file = get_config_path()
        data = {
            "server_url": self.server_url,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "operating_system": self.operating_system,
            "agent_version": self.agent_version,
            "enabled_categories": sorted(list(self.enabled_categories)),
            "consent_version": self.consent_version,
            "last_heartbeat_at": self.last_heartbeat_at,
        }
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def is_enrolled(self) -> bool:
        """Returns True if device ID and valid API key exist."""
        return bool(self.device_id and self.get_api_key())

    def get_api_key(self) -> str | None:
        """Decrypts and returns the stored device API key."""
        key_file = get_key_path()
        if not key_file.exists():
            return None
        try:
            with open(key_file, "r", encoding="ascii") as f:
                encrypted = f.read().strip()
            if not encrypted:
                return None
            return dpapi_decrypt(encrypted)
        except Exception:
            return None

    def save_api_key(self, api_key: str) -> None:
        """Encrypts and stores the device API key using DPAPI."""
        key_file = get_key_path()
        encrypted = dpapi_encrypt(api_key.strip())
        with open(key_file, "w", encoding="ascii") as f:
            f.write(encrypted)

    def update_consent(self, categories: list[str], version: str = "v1.0") -> None:
        """Updates active consent categories."""
        self.enabled_categories = set(categories)
        self.consent_version = version
        self.save()

    def clear(self) -> None:
        """Removes local credentials on revoke or uninstall."""
        key_file = get_key_path()
        if key_file.exists():
            key_file.unlink(missing_ok=True)
        cfg_file = get_config_path()
        if cfg_file.exists():
            cfg_file.unlink(missing_ok=True)
        self.device_id = None
        self.enabled_categories = set()

