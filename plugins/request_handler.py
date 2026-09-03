# ============================================================
# plugins/request_handler.py – User Request Handler
# Handles movie/series requests when no results are found.
# Logs to REQUEST_CHANNEL and optionally notifies admin.
# ============================================================

import logging
import asyncio
from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, RPCError

from config import (
    ADMINS,
    REQST_CHANNEL,
    LOG_CHANNEL,
    SUPPORT_CHAT,
    NO_RESULTS_MSG,
)
from core.permissions import is_admin
from database.users import add_user, get_user

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Helper: Build request message
# ============================================================
async def send_request_to_channel(client: Client, user_id: int, query: str, message: Message):
    """Send request notification to REQST_CHANNEL."""
    if not REQST_CHANNEL:
        return
    try:
        user = await get_user(user_id)
        first_name = user.get("first_name", "Unknown") if user else "Unknown"
        username = user.get("username") if user else None
        text = (
            "🎬 <b>#NewRequest</b>\n\n"
            f"👤 User: <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"🔍 Query: <code>{html.escape(query)}</code>\n"
            f"📅 Date: {datetime.now().strftime('%d %b %Y %H:%M')}"
        )
        if username:
            text += f"\n📛 Username: @{username}"
        await client.send_message(REQST_CHANNEL, text, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[REQUESTS] Sent request for '{query}' by user {user_id}")
    except Exception as e:
        logger.error(f"[REQUESTS] Request channel error: {e}")

# ============================================================
# Hook: When no search results found, call this
# ============================================================
async def handle_no_results(client: Client, message: Message, query: str):
    """Called by auto_filter when no files are found."""
    try:
        user_id = message.from_user.id if message.from_user else None
        if not user_id:
            return

        # Add user to DB (if not exists)
        await add_user(user_id, message.from_user.first_name, message.from_user.last_name or "", message.from_user.username)

        # Send request to channel
        await send_request_to_channel(client, user_id, query, message)

        # Reply to user
        reply_text = "😔 No results found for your request.\n\n"
        reply_text += "Your request has been recorded. We'll add it soon if possible."
        if NO_RESULTS_MSG:
            reply_text += "\n\nTry a different name or check spelling."
        if SUPPORT_CHAT:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("❓ Support", url=SUPPORT_CHAT)],
            ])
            await message.reply_text(reply_text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply_text(reply_text, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        logger.error(f"[REQUESTS] No results handler error: {e}")

# ============================================================
# /request Command (optional)
# ============================================================
@Client.on_message(filters.command("request") & filters.private)
async def request_command(client: Client, message: Message):
    try:
        query = message.text.split(None, 1)[1] if len(message.command) > 1 else ""
        if not query:
            await message.reply_text("Usage: /request <movie name>")
            return
        # Just record the request
        await add_user(message.from_user.id, message.from_user.first_name, message.from_user.last_name or "", message.from_user.username)
        await send_request_to_channel(client, message.from_user.id, query, message)
        await message.reply_text("✅ Your request has been recorded.")
    except Exception as e:
        logger.error(f"[REQUESTS] Command error: {e}")

# ============================================================
# Close Menu (if needed)
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[REQUESTS] Close error: {e}")