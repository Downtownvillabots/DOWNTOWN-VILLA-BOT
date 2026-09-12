"""
📢 DOWNTOWN VILLA — Request Service
Posts no-result requests to REQST_CHANNEL with admin action buttons.
Handles the full lifecycle: poster DM, GET FILE, NOT RELEASED, NOT FOUND, CANCEL.
"""
import logging
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.config import REQST_CHANNEL, OWNER_LNK
from media_search.requests import requests as request_repo

logger = logging.getLogger(__name__)

DIV = "━" * 26


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def post_request(client: Client, user_id: int, username: str,
                       full_name: str, movie_name: str,
                       imdb_id: Optional[str] = None,
                       user_query: str = "") -> Optional[str]:
    """
    Post a no-result request to the request channel.
    Returns the token_id (used later to clear cache / update).
    """
    if not REQST_CHANNEL:
        logger.debug("[REQSVC] REQST_CHANNEL not set — skipping")
        return None

    # Create DB token
    token_id = await request_repo.create_token(
        user_id=user_id,
        username=username,
        full_name=full_name,
        movie_name=movie_name,
        imdb_id=imdb_id,
        user_query=user_query,
    )
    if not token_id:
        return None

    # Build text
    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "📝 <b>ɴᴇᴡ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ</b>",
        DIV,
        "",
        f"🎬 ᴍᴏᴠɪᴇ · <b>{_esc(movie_name)}</b>",
    ]
    if imdb_id:
        lines.append(f"🆔 ɪᴍᴅʙ · <code>{_esc(imdb_id)}</code>")
    lines.extend([
        "",
        f"👤 ᴜꜱᴇʀ · {_esc(full_name)}",
        f"🆔 ᴜꜱᴇʀ ɪᴅ · <code>{user_id}</code>",
    ])
    if username:
        lines.append(f"📛 ᴜꜱᴇʀɴᴀᴍᴇ · @{_esc(username)}")
    else:
        lines.append("📛 ᴜꜱᴇʀɴᴀᴍᴇ · —")
    lines.extend([
        "",
        f"🔑 ᴛᴏᴋᴇɴ · <code>{token_id}</code>",
        DIV,
        "",
        "<i>ᴀᴅᴍɪɴ · ᴄʜᴏᴏꜱᴇ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ</i>",
    ])
    text = "\n".join(lines)

    # Buttons
    buttons = [
        [InlineKeyboardButton("🎬 MOVIE UPDATED", callback_data=f"req:updated:{token_id}")],
        [
            InlineKeyboardButton("📅 NOT RELEASED", callback_data=f"req:notreleased:{token_id}"),
            InlineKeyboardButton("🔎 NOT FOUND", callback_data=f"req:notfound:{token_id}"),
        ],
        [InlineKeyboardButton("❌ CANCEL REQUEST", callback_data=f"req:cancel:{token_id}")],
    ]

    try:
        await client.send_message(
            chat_id=REQST_CHANNEL,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[REQSVC] posted request token={token_id} movie={movie_name!r}")
        return token_id
    except Exception as e:
        logger.warning(f"[REQSVC] post failed: {type(e).__name__}: {e}")
        # Rollback token
        await request_repo.delete_token(token_id)
        return None
