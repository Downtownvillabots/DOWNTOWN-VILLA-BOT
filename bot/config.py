"""
Central configuration module.

Reads all environment variables once and provides a single source of truth.
No feature‑specific settings are here; only engine‑level ones.
"""

import os
from typing import Optional, Dict, List

class Config:
    """Static class holding configuration values."""

    # Telegram API credentials
    API_ID: int = int(os.getenv("API_ID", "0"))          # required
    API_HASH: str = os.getenv("API_HASH", "")            # required
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")          # required

    # Owner / admin / sudo user IDs (comma separated)
    OWNER_IDS: list[int] = [
        int(x) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()
    ]
    ADMIN_IDS: list[int] = [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
    ]
    SUDO_IDS: list[int] = [
        int(x) for x in os.getenv("SUDO_IDS", "").split(",") if x.strip()
    ]

    # ---------- NEW DYNAMIC DATABASE CONFIGURATION ----------
    # System database URI (single)
    SYSTEM_DATABASE_URI: Optional[str] = os.getenv("SYSTEM_DATABASE_URI")

    # User databases – unlimited (scan env for USER_DATABASE_URI_*)
    @staticmethod
    def _get_all_uris(prefix: str) -> List[str]:
        """
        Returns a list of URIs whose environment variable name starts with `prefix`.
        Example: prefix="USER_DATABASE_URI_" returns values for
                 USER_DATABASE_URI_1, USER_DATABASE_URI_2, ... in order.
        """
        uris = []
        i = 1
        while True:
            key = f"{prefix}{i}"
            val = os.getenv(key)
            if val is None:
                break
            uris.append(val.strip())
            i += 1
        return uris

    USER_DATABASE_URIS: List[str] = _get_all_uris("USER_DATABASE_URI_")
    FILE_DATABASE_URIS: List[str] = _get_all_uris("FILE_DATABASE_URI_")

    # Legacy (optional) – kept for backward compatibility with old code
    STORAGE_URI: Optional[str] = os.getenv("STORAGE_URI")

    # Web server (Render)
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Engine tuning
    WORKERS: int = int(os.getenv("WORKERS", "4"))          # Pyrogram concurrency
    HEARTBEAT_INTERVAL: int = int(os.getenv("HEARTBEAT", "10"))  # seconds

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def validate_required() -> None:
    """Ensure critical credentials are set."""
    missing = []
    if not Config.API_ID:
        missing.append("API_ID")
    if not Config.API_HASH:
        missing.append("API_HASH")
    if not Config.BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
