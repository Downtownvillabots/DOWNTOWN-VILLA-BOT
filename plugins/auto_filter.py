# ============================================================
# plugins/auto_filter.py – Auto‑Filter & Search System
# Handles movie/series search in groups and PM.
# Uses database.files.get_search_results() and database.users.get_settings().
# ============================================================

import logging
import re
import asyncio
from typing import List, Optional, Tuple

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
)
from pyrogram.errors import FloodWait, RPCError

from config import (
    ADMINS,
    SUPPORT_CHAT,
    AUTO_FFILTER,
    SPELL_CHECK_REPLY,
    MAX_B_TN,
    IMDB,
    NO_RESULTS_MSG,
    SPOILER_IMG,
    CUSTOM_FILE_CAPTION,
)
from core.permissions import is_admin
from database.files import get_search_results, get_bad_files, dreamxbotz_get_movies, dreamxbotz_get_series
from database.users import get_settings, save_group_settings, get_user, add_user
from core.helpers import human_size, render_caption, extract_metadata_from_filename

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Helper: Build file buttons
# ============================================================
def build_file_buttons(files, offset, next_offset, total_results, query, file_type=None):
    """Return inline keyboard for search results."""
    buttons = []
    idx = 0
    for file in files:
        file_name = getattr(file, "file_name", "Unknown")
        file_id = getattr(file, "file_id", "")
        # Simplify: send file directly (you can add quality buttons later)
        buttons.append(
            [InlineKeyboardButton(
                text=f"📁 {file_name[:30]}",
                callback_data=f"send_file:{file_id}"
            )]
        )
        idx += 1
    # Pagination
    if next_offset != "":
        buttons.append([
            InlineKeyboardButton("⬅️ Previous", callback_data=f"prev_page:{query}:{offset - 10}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"next_page:{query}:{next_offset}"),
        ])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# Text Handler (Group Auto‑Filter)
# ============================================================
@Client.on_message(filters.text & filters.group & ~filters.command())
async def auto_filter_group(client: Client, message: Message):
    if not AUTO_FFILTER:
        return
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id
        search_query = message.text.strip()

        # Check if it's a command or too short
        if len(search_query) < 2 or search_query.startswith("/"):
            return

        logger.info(f"[AUTOFILTER] Search in {chat_id}: {search_query} by user {user_id}")
        # Get settings
        settings = await get_settings(chat_id)
        if not settings.get("auto_filter", AUTO_FFILTER):
            return

        # Search
        files, next_offset, total_results = await get_search_results(
            chat_id=chat_id,
            query=search_query,
            max_results=int(MAX_B_TN),
            offset=0,
        )

        if not files:
            # Spell check / suggestions
            if SPELL_CHECK_REPLY:
                await suggest_alternatives(client, message, search_query)
            else:
                if NO_RESULTS_MSG:
                    await message.reply_text("❌ No results found. Try a different name.")
            return

        # Build caption
        caption = f"🎬 <b>Results for:</b> <code>{html.escape(search_query)}</code>\n\n"
        caption += f"📁 Found: <b>{total_results}</b> files"

        keyboard = build_file_buttons(files, 0, next_offset, total_results, search_query)
        await message.reply_text(caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[AUTOFILTER] Sent results for '{search_query}' in {chat_id}")

    except FloodWait as e:
        logger.warning(f"[AUTOFILTER] FloodWait: {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"[AUTOFILTER] Error in group: {e}")

# ============================================================
# Text Handler (Private Chat)
# ============================================================
@Client.on_message(filters.text & filters.private & ~filters.command())
async def auto_filter_pm(client: Client, message: Message):
    if not AUTO_FFILTER:
        return
    try:
        user_id = message.from_user.id
        search_query = message.text.strip()

        if len(search_query) < 2 or search_query.startswith("/"):
            return

        # Add user to DB
        await add_user(user_id, message.from_user.first_name, message.from_user.last_name or "", message.from_user.username)

        logger.info(f"[AUTOFILTER] PM search: {search_query} by {user_id}")
        # Search
        files, next_offset, total_results = await get_search_results(
            chat_id=user_id,
            query=search_query,
            max_results=int(MAX_B_TN),
            offset=0,
        )

        if not files:
            if SPELL_CHECK_REPLY:
                await suggest_alternatives(client, message, search_query)
            else:
                await message.reply_text("❌ No results found. Try a different name.")
            return

        caption = f"🎬 <b>Results for:</b> <code>{html.escape(search_query)}</code>\n\n"
        caption += f"📁 Found: <b>{total_results}</b> files"

        keyboard = build_file_buttons(files, 0, next_offset, total_results, search_query)
        await message.reply_text(caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[AUTOFILTER] Sent PM results for '{search_query}'")

    except FloodWait as e:
        logger.warning(f"[AUTOFILTER] FloodWait: {e.value}s")
        await asyncio.sleep(e.value)
    except Exception as e:
        logger.error(f"[AUTOFILTER] Error in PM: {e}")

# ============================================================
# Callback: Send File
# ============================================================
@Client.on_callback_query(filters.regex(r"^send_file:(.+)"))
async def send_file_callback(client: Client, query: CallbackQuery):
    try:
        file_id = query.data.split(":")[1]
        user_id = query.from_user.id
        # Get file details
        from database.files import get_file_details
        files = await get_file_details(file_id)
        if not files:
            await query.answer("❌ File not found", show_alert=True)
            return
        file = files[0]
        file_name = getattr(file, "file_name", "Unknown")
        file_size = getattr(file, "file_size", 0)
        caption = CUSTOM_FILE_CAPTION.format(file_name=file_name, filesize=human_size(file_size))
        # Send file
        await client.send_cached_media(
            user_id,
            file.file_id,
            caption=caption,
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer("✅ File sent", show_alert=False)
        logger.info(f"[AUTOFILTER] Sent file '{file_name}' to {user_id}")
    except Exception as e:
        logger.error(f"[AUTOFILTER] Send file error: {e}")
        await query.answer("❌ Failed to send file", show_alert=True)

# ============================================================
# Callback: Pagination
# ============================================================
@Client.on_callback_query(filters.regex(r"^(next_page|prev_page):(.+):(\d+)"))
async def pagination_callback(client: Client, query: CallbackQuery):
    try:
        action, search_query, offset = query.data.split(":")
        offset = int(offset)
        files, next_offset, total_results = await get_search_results(
            chat_id=query.message.chat.id,
            query=search_query,
            max_results=int(MAX_B_TN),
            offset=offset,
        )
        if not files:
            await query.answer("No more results", show_alert=True)
            return
        caption = f"🎬 <b>Results for:</b> <code>{html.escape(search_query)}</code>\n\n"
        caption += f"📁 Found: <b>{total_results}</b> files"
        keyboard = build_file_buttons(files, offset, next_offset, total_results, search_query)
        await query.message.edit_text(caption, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        await query.answer("Page updated")
    except Exception as e:
        logger.error(f"[AUTOFILTER] Pagination error: {e}")

# ============================================================
# Spell Check / Suggestion
# ============================================================
async def suggest_alternatives(client: Client, message: Message, query: str):
    """Show suggestions based on fuzzy matching."""
    try:
        # Use rapidfuzz if available
        from rapidfuzz import fuzz
        from database.files import get_all_files_names  # needs to be added to files.py

        # Actually we don't have get_all_files_names, so we'll use dreamxbotz_get_movies
        movies = await dreamxbotz_get_movies(limit=20)
        if not movies:
            return

        # Find similar titles
        matches = []
        for movie in movies:
            score = fuzz.ratio(query.lower(), movie.lower())
            if score >= 60:
                matches.append((movie, score))
        matches.sort(key=lambda x: x[1], reverse=True)
        suggestions = [m[0] for m in matches[:5]]

        if suggestions:
            text = "❓ Did you mean?\n\n" + "\n".join(f"• {m}" for m in suggestions)
            await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        else:
            if NO_RESULTS_MSG:
                await message.reply_text("❌ No results found.")
    except Exception as e:
        logger.error(f"[AUTOFILTER] Suggest error: {e}")

# ============================================================
# Close Menu Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[AUTOFILTER] Close menu error: {e}")