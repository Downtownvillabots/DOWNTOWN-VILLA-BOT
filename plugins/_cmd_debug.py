# plugins/_cmd_debug.py
import logging
from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)


# group=-100 → runs BEFORE every other handler
@Client.on_message(filters.private & filters.text, group=-100)
async def _cmd_debug(client: Client, message: Message):
    txt = (message.text or "").strip()
    logger.info(f"[CMD-DEBUG] got: {txt[:60]!r}")
    try:
        await message.reply_text(f"🔔 DEBUG: got {txt[:80]!r}")
    except Exception as e:
        logger.warning(f"[CMD-DEBUG] reply failed: {type(e).__name__}: {e}")
