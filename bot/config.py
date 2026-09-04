"""
Central configuration module.

Reads all environment variables once and provides a single source of truth.
No feature‑specific settings are here; only engine‑level ones.
"""

import os
from typing import Optional


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

    # Database (optional)
    STORAGE_URI: Optional[str] = os.getenv("STORAGE_URI")  # e.g. mongodb://...

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
