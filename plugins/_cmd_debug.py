# plugins/_cmd_debug.py
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


@Client.on_message(
    filters.private
    & filters.command(["start", "database", "index", "indexing",
                       "pm_search", "autofilter", "stats"])
)
async def _cmd_debug(client: Client, message: Message):
    logger.info(
        f"[CMD-DEBUG] got command: {message.text!r} "
        f"from={message.from_user.id}"
    )
