# ============================================================
# plugins/movie_updates.py – Movie Update Notifications
# Automatically posts to MOVIE_UPDATE_CHANNEL when a new file is saved.
# Uses database.files and config.
# ============================================================

import logging
import asyncio
import time
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, RPCError

from config import (
    MOVIE_UPDATE_NOTIFICATION,
    MOVIE_UPDATE_CHANNEL,
    DREAMXBOTZ_IMAGE_FETCH,
    IMDB,
    TMDB_API_KEY,
    UPDATE_CHNL_LNK,
    GRP_LNK,
)
from core.helpers import (
    render_caption,
    human_size,
    extract_metadata_from_filename,
)
from database.files import save_file, get_file_details
from database.users import get_settings, save_group_settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Helper: Get TMDB/IMDb poster if enabled
# ============================================================
async def get_movie_poster(title: str, year: str = "") -> Optional[str]:
    """Fetch poster from TMDB (if enabled and API key exists)."""
    if not TMDB_API_KEY:
        return None
    try:
        # Use existing IMDb/TMDB poster function from utils (if available)
        # We'll call a simplified version that may exist in utils.py
        from utils import get_poster
        poster = await get_poster(title, year)
        return poster if poster else None
    except Exception as e:
        logger.error(f"[MOVIE_UPDATES] Poster error: {e}")
        return None

# ============================================================
# Hook: When a file is saved, send notification
# ============================================================
async def notify_movie_update(client: Client, file_data: dict, original_message: Message = None):
    """Called after save_file() succeeds. Posts to MOVIE_UPDATE_CHANNEL."""
    if not MOVIE_UPDATE_NOTIFICATION:
        return
    if not MOVIE_UPDATE_CHANNEL:
        return

    try:
        # Extract metadata
        filename = file_data.get("file_name", "Unknown")
        metadata = extract_metadata_from_filename(filename)
        title = metadata.get("title", filename)
        year = metadata.get("year", "")

        # Get poster (if enabled)
        poster = None
        if DREAMXBOTZ_IMAGE_FETCH:
            poster = await get_movie_poster(title, year)

        # Build caption
        caption = f"🎬 <b>{html.escape(filename)}</b>"
        if year:
            caption += f"\n📅 {year}"
        if metadata.get("quality"):
            caption += f"\n🎞️ Quality: {metadata['quality']}"
        if metadata.get("language"):
            caption += f"\n🗣️ Language: {metadata['language']}"

        # Add buttons
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 SEARCH", url=UPDATE_CHNL_LNK),
             InlineKeyboardButton("👥 GROUP", url=GRP_LNK)],
        ])

        # Send to channel
        if poster:
            await client.send_photo(
                MOVIE_UPDATE_CHANNEL,
                poster,
                caption=caption,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML
            )
        else:
            await client.send_message(
                MOVIE_UPDATE_CHANNEL,
                caption,
                reply_markup=keyboard,
                parse_mode=enums.ParseMode.HTML
            )
        logger.info(f"[MOVIE_UPDATES] Sent update for {filename}")
    except FloodWait as e:
        logger.warning(f"[MOVIE_UPDATES] FloodWait: {e.value}s")
        await asyncio.sleep(e.value)
        # Retry once
        try:
            await client.send_message(MOVIE_UPDATE_CHANNEL, caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        except Exception as e2:
            logger.error(f"[MOVIE_UPDATES] Retry failed: {e2}")
    except Exception as e:
        logger.error(f"[MOVIE_UPDATES] Notification error: {e}")

# ============================================================
# Admin Command: Toggle Movie Updates
# ============================================================
@Client.on_message(filters.command("movie_update") & filters.user(ADMINS))
async def toggle_movie_update(client: Client, message: Message):
    try:
        # Toggle setting in DB
        from database.connection import get_user_db
        db = get_user_db()
        settings_col = db["bot_settings"]
        current = await settings_col.find_one({"_id": "global"})
        enabled = current.get("movie_update", MOVIE_UPDATE_NOTIFICATION) if current else MOVIE_UPDATE_NOTIFICATION
        new_state = not enabled
        await settings_col.update_one({"_id": "global"}, {"$set": {"movie_update": new_state}}, upsert=True)
        await message.reply_text(f"✅ Movie update notifications {'enabled' if new_state else 'disabled'}")
        logger.info(f"[MOVIE_UPDATES] Toggled to {new_state} by {message.from_user.id}")
    except Exception as e:
        logger.error(f"[MOVIE_UPDATES] Toggle error: {e}")

# ============================================================
# Hook into save_file (this is optional – we can call notify_movie_update from elsewhere)
# ============================================================
# We'll add an async wrapper that other plugins can call.
async def movie_update_hook(file_data: dict, client: Client):
    """Wrapper to call notify_movie_update without breaking existing code."""
    await notify_movie_update(client, file_data)

# ============================================================
# Close Menu Callback (if needed)
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[MOVIE_UPDATES] Close error: {e}")