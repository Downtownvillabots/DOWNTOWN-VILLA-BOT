# plugins/log_channel.py
"""
DOWNTOWN VILLA BOT — Basic Telegram Logging Channel Plugin

Sends important bot events to a configured Telegram channel.
This is the first simple version. More events (database, errors, admin, etc.)
will be added later, but this file will remain the single logging interface.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Global variables – set during bot startup
_bot = None
_channel_id: int = None


def set_bot(client):
    """Store the bot client instance so the log plugin can send messages."""
    global _bot
    _bot = client


def _get_channel_id():
    """
    Retrieve the logging channel ID from environment variable LOG_CHANNEL_ID.
    """
    global _channel_id
    if _channel_id is not None:
        return _channel_id

    raw = os.getenv("LOG_CHANNEL_ID")
    if not raw:
        logger.warning("No LOG_CHANNEL_ID set. Logging to Telegram is disabled.")
        return None

    try:
        _channel_id = int(raw)
        return _channel_id
    except ValueError:
        logger.warning("LOG_CHANNEL_ID is not a valid integer. Logging disabled.")
        return None


async def send_log(message: str) -> bool:
    """
    Send a message to the configured logging channel.

    Returns True if sent successfully, False otherwise.
    Never raises an exception – safe for the bot.
    """
    channel = _get_channel_id()
    if not _bot or not channel:
        return False

    try:
        await _bot.send_message(chat_id=channel, text=message)
        logger.info(f"Log message sent to channel {channel}")
        return True
    except Exception as e:
        logger.warning(f"Failed to send log message: {e}")
        return False


# ------------------------------------------------------------
# Ready-to-use event helpers
# ------------------------------------------------------------

async def bot_started():
    """Notify that the bot has started successfully."""
    await send_log("🚀 DOWNTOWN VILLA BOT STARTED\n\nStatus: 🟢 Online")


async def bot_restarted():
    """Notify that the bot has been restarted."""
    await send_log("🔄 DOWNTOWN VILLA BOT RESTARTED\n\nStatus: 🟢 Online")


async def feature_added(feature: str, version: str):
    """Notify that a new feature/version has been added."""
    await send_log(
        f"✨ NEW FEATURE\n\n"
        f"Feature: {feature}\n"
        f"Version: {version}\n\n"
        f"Status: 🟢 Enabled"
    )
