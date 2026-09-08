"""
Basic plugin to prove the engine works.

Handles /start in private chats and logs all private messages.
"""

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Hello {first_name}! I am {bot_name}.\n"
    "Engine is running."
)

def setup(app: Client) -> None:
    """Register the message handlers."""

    @app.on_message(filters.private & filters.command("start"))
    async def start_command(client: Client, message: Message):
        """Send a welcome message."""
        await message.reply_text(
            HELP_TEXT.format(
                first_name=message.from_user.first_name,
                bot_name=(await client.get_me()).first_name or "Bot",
            )
        )

    @app.on_message(filters.private & ~filters.command("start"))
    async def log_private(client: Client, message: Message):
        """Log every private message for debugging."""
        logger.info(
            "Private message from %s (id=%d): %s",
            message.from_user.first_name,
            message.from_user.id,
            message.text or "[non-text]",
        )
