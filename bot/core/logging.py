"""
Logging configuration.

Optimised to:
 - Use a consistent format.
 - Silence noisy third‑party loggers.
 - Respect LOG_LEVEL from config.
"""

import logging
import sys

from bot.config import Config

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# List of noisy loggers to silence
NOISY_LOGGERS = [
    "pyrogram",
    "pyrogram.session",
    "pyrogram.client",
    "aiohttp",
    "motor",
]


def setup_logging() -> None:
    """Configure root logger and silence third‑party noise."""
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        stream=sys.stdout,
    )

    # Silence noisy loggers
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Reduce Pyrogram's internal debug logs (if any)
    logging.getLogger("pyrogram").setLevel(logging.INFO)
