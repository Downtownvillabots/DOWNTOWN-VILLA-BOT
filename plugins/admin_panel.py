# ============================================================
# plugins/admin_panel.py – Admin Panel / Dashboard
# Provides /admin command, database control center, live logs,
# and basic admin controls with logging and error handling.
# ============================================================

import logging
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

from config import (
    ADMINS,
    OWNER_IDS,
    LOG_CHANNEL,
    BOT_NAME,
    COLLECTION_NAME,
    DELETE_TIME,
    BROADCAST_ENABLED,
    SUPERBROADCAST_ENABLED,
    MAINTENANCE,
)
from core.permissions import is_admin, is_owner, has_permission
from database.connection import get_user_db, get_media_dbs, get_media_collections, get_media_labels
from database.users import (
    get_all_users,
    get_all_groups,
    get_premium_users,
    get_banned,
)
from database.files import get_total_file_count, check_db_size
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Live Logs Storage (in-memory)
# ============================================================
live_logs: List[str] = []

def add_log_entry(level: str, message: str):
    """Add a log entry to in-memory list for admin panel display."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    entry = f"{timestamp} | {level} | {message}"
    live_logs.append(entry)
    if len(live_logs) > 200:
        live_logs.pop(0)

# ============================================================
# ADMIN COMMAND
# ============================================================
@Client.on_message(filters.command("admin") & filters.private)
async def admin_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("❌ Admin only.")
        return
    logger.info(f"[ADMIN] Admin {message.from_user.id} opened admin panel")
    await show_admin_dashboard(client, message.chat.id, message.id)

# ============================================================
# DASHBOARD
# ============================================================
async def show_admin_dashboard(client: Client, chat_id: int, message_id: int = None):
    """Show main admin dashboard."""
    try:
        users = await get_all_users()
        groups = await get_all_groups()
        premium = await get_premium_users()
        files = await get_total_file_count()
        db_count = len(get_media_dbs())

        text = (
            "╔══════════════════════════════════════════════════╗\n"
            "║             🏠 DOWNTOWN VILLA ADMIN              ║\n"
            "╚══════════════════════════════════════════════════╝\n\n"
            f"🟢 Bot: <b>{BOT_NAME}</b>\n"
            f"👤 Admin: AUTHORIZED\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 OVERVIEW\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Users: {len(users):,}\n"
            f"👥 Groups: {len(groups):,}\n"
            f"💎 Premium: {len(premium):,}\n"
            f"📁 Files: {files:,}\n"
            f"🗄️ Databases: {db_count}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🛠️ CONTROLS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗄️ DATABASES", callback_data="admin_db"),
             InlineKeyboardButton("📋 LOGS", callback_data="admin_logs")],
            [InlineKeyboardButton("📊 USERS", callback_data="admin_users"),
             InlineKeyboardButton("📡 CHANNELS", callback_data="admin_channels")],
            [InlineKeyboardButton("📤 BROADCAST", callback_data="admin_broadcast"),
             InlineKeyboardButton("🚀 SUPERBROADCAST", callback_data="admin_superbroadcast")],
            [InlineKeyboardButton("🧹 CLEANUP", callback_data="admin_cleanup"),
             InlineKeyboardButton("🔧 SYSTEM", callback_data="admin_system")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="close_menu")],
        ])

        if message_id:
            await client.edit_message_text(chat_id, message_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_message(chat_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Dashboard error: {e}")

# ============================================================
# DATABASE CONTROL CENTER
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_db$"))
async def admin_db(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        dbs = get_media_dbs()
        collections = get_media_collections()
        labels = get_media_labels()
        text = "🗄️ <b>DATABASE CONTROL CENTER</b>\n\n"
        text += f"📚 Collection: <code>{COLLECTION_NAME}</code>\n"
        text += f"🗄️ Databases: {len(dbs)}\n\n"
        for idx, (db, collection, label) in enumerate(zip(dbs, collections, labels), 1):
            count = await collection.count_documents({})
            text += f"🟢 DATABASE {idx:02d}\n"
            text += f"🏷️ Cluster: <code>{label}</code>\n"
            text += f"📦 Files: {count:,}\n\n"
        text += "─────────────────────\n"
        text += f"📊 TOTAL FILES: {await get_total_file_count():,}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[ADMIN] Database page shown to {query.from_user.id}")
    except Exception as e:
        logger.error(f"[ADMIN] DB error: {e}")
        await query.answer("Error loading databases", show_alert=True)

# ============================================================
# LIVE LOGS
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_logs$"))
async def admin_logs(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        text = "📋 <b>LIVE LOGS</b>\n\n"
        if live_logs:
            text += "\n".join(f"<code>{entry}</code>" for entry in live_logs[-20:])
        else:
            text += "No logs yet."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 REFRESH", callback_data="admin_logs"),
                                          InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Logs error: {e}")

# ============================================================
# USERS
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_users$"))
async def admin_users(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        users = await get_all_users()
        groups = await get_all_groups()
        premium = await get_premium_users()
        text = (
            "👥 <b>USERS</b>\n\n"
            f"Total Users: {len(users):,}\n"
            f"Total Groups: {len(groups):,}\n"
            f"Premium Users: {len(premium):,}\n\n"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Users error: {e}")

# ============================================================
# CHANNELS
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_channels$"))
async def admin_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        text = "📡 <b>CHANNELS</b>\n\n"
        text += "Use /superbroadcast to manage distribution channels.\n\n"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 SUPERBROADCAST", callback_data="admin_superbroadcast")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")],
        ])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Channels error: {e}")

# ============================================================
# BROADCAST
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_broadcast$"))
async def admin_broadcast(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        text = "📤 <b>BROADCAST</b>\n\nUse /broadcast to send messages to all users.\n\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Broadcast error: {e}")

# ============================================================
# SUPERBROADCAST
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_superbroadcast$"))
async def admin_superbroadcast(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        text = "🚀 <b>SUPERBROADCAST</b>\n\nUse /superbroadcast to distribute releases.\n\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Superbroadcast error: {e}")

# ============================================================
# CLEANUP (Placeholder – full cleanup plugin already exists)
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_cleanup$"))
async def admin_cleanup(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        text = "🧹 <b>CLEANUP</b>\n\nUse /cleanup for full cleanup controls.\n\n"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] Cleanup error: {e}")

# ============================================================
# SYSTEM INFO
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_system$"))
async def admin_system(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        import platform
        import psutil
        uptime = time.time() - temp.BOT_START_TIME if hasattr(temp, "BOT_START_TIME") else "Unknown"
        text = (
            "🔧 <b>SYSTEM</b>\n\n"
            f"Platform: {platform.platform()}\n"
            f"Python: {platform.python_version()}\n"
            f"CPU: {psutil.cpu_percent()}%\n"
            f"RAM: {psutil.virtual_memory().percent}%\n"
            f"Uptime: {uptime}\n\n"
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="admin_main")]])
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ADMIN] System error: {e}")

# ============================================================
# BACK TO MAIN
# ============================================================
@Client.on_callback_query(filters.regex(r"^admin_main$"))
async def admin_back(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await show_admin_dashboard(client, query.message.chat.id, query.message.id)

# ============================================================
# CLOSE MENU
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[ADMIN] Close error: {e}")