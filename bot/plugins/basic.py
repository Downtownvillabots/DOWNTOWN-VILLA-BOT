"""
Basic plugin to prove the engine works.

Handles /start in private chats and logs all private messages.
This can be replaced or extended later by other plugins.
"""

from pyrogram import Client, filters
from pyrogram.types import Message

from bot.config import Config
from bot.core.helpers import human_readable_size  # not used here, but imported as example

HELP_TEXT = (
    "Hello {first_name}! I am {bot_name}.\n"
    "Engine is running."
)


# Register handlers using the decorator style
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
        """Log every private message for debugging (will be removed later)."""
        # Use the app's logger
        app.logger.info(
            "Private message from %s (id=%d): %s",
            message.from_user.first_name,
            message.from_user.id,
            message.text or "[non-text]",
        )
        # You could add more logic here later
