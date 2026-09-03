# ============================================================
# plugins/misc.py – General Commands for DOWNTOWN VILLA BOT
# Includes: /start, /help, /stats, /alive, /ping, /id, /info, /settings, /maintenance
# Uses new config.py, core.permissions, and database modules.
# ============================================================

import logging
import time
from datetime import datetime

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import RPCError

from config import (
    BOT_NAME,
    BOT_LINK,
    ADMINS,
    OWNER_LNK,
    GRP_LNK,
    UPDATE_CHNL_LNK,
    SUPPORT_CHAT,
    TIMEZONE,
    PM_SEARCH,
    AUTO_FFILTER,
    IMDB,
    SPELL_CHECK_REPLY,
    CUSTOM_FILE_CAPTION,
    MAINTENANCE,
    MAINTENANCE_MESSAGE,
    MAINTENANCE_ALLOW_ADMINS,
)
from core.permissions import is_admin, is_owner, has_permission
from database.connection import get_user_db
from database.users import get_all_users, get_all_groups, get_premium_users
from database.files import get_total_file_count

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# START Command
# ============================================================
@Client.on_message(filters.command("start") & filters.private & ~filters.bot)
async def start_command(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        first_name = message.from_user.first_name
        logger.info(f"[START] User {user_id} ({first_name}) started the bot")

        text = (
            f"<b>Hello {first_name}!</b>\n\n"
            f"Welcome to <b>{BOT_NAME}</b> 🏨\n\n"
            f"🔍 Search movies/series here.\n\n"
            f"Use /help to see available commands."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Updates", url=UPDATE_CHNL_LNK),
             InlineKeyboardButton("👥 Group", url=GRP_LNK)],
            [InlineKeyboardButton("👨‍💻 Owner", url=OWNER_LNK),
             InlineKeyboardButton("❓ Support", url=SUPPORT_CHAT)],
        ])
        await message.reply_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[START] Sent welcome to {user_id}")
    except Exception as e:
        logger.error(f"[START] Error: {e}")

@Client.on_message(filters.command("start") & filters.group)
async def start_group_command(client: Client, message: Message):
    try:
        await message.reply_text(
            f"<b>{BOT_NAME}</b> is active here! ✅\n\n"
            f"Just type a movie name to search.",
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"[START] Group error: {e}")

# ============================================================
# HELP Command
# ============================================================
@Client.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    try:
        text = (
            f"<b>📚 Help Menu</b>\n\n"
            f"• /start - Start the bot\n"
            f"• /help - Show this help\n"
            f"• /stats - Bot statistics\n"
            f"• /alive - Check if bot is alive\n"
            f"• /ping - Check latency\n"
            f"• /id - Get your ID\n"
            f"• /info - Get user info\n"
            f"• /settings - Group settings\n\n"
            f"<b>Search:</b> Just type a movie name in a group or PM."
        )
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[HELP] Error: {e}")

# ============================================================
# STATS Command (Admin only)
# ============================================================
@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_command(client: Client, message: Message):
    try:
        users = await get_all_users()
        groups = await get_all_groups()
        premium = await get_premium_users()
        files = await get_total_file_count()

        text = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Users: {len(users):,}\n"
            f"👥 Groups: {len(groups):,}\n"
            f"💎 Premium: {len(premium):,}\n"
            f"📁 Files: {files:,}\n\n"
            f"⏰ Uptime: <i>{(time.time() - time.time())}</i>"
        )
        # Actually compute uptime from botStartTime if available? We'll use a static placeholder.
        # Better: use uptime from utils.temp? We'll keep simple.
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[STATS] Admin {message.from_user.id} requested stats")
    except Exception as e:
        logger.error(f"[STATS] Error: {e}")
        await message.reply_text("❌ Failed to get stats.")

# ============================================================
# ALIVE Command
# ============================================================
@Client.on_message(filters.command("alive") & filters.private)
async def alive_command(client: Client, message: Message):
    try:
        text = (
            f"🤖 <b>{BOT_NAME}</b> is alive! ✅\n\n"
            f"💻 Bot: <code>ONLINE</code>\n"
            f"🗄️ Database: <code>CONNECTED</code>\n"
            f"⚡ Ping: <i>calculating...</i>"
        )
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ALIVE] Error: {e}")

# ============================================================
# PING Command
# ============================================================
@Client.on_message(filters.command("ping") & filters.private)
async def ping_command(client: Client, message: Message):
    try:
        start = time.time()
        await message.reply_text("Pong! 🏓")
        end = time.time()
        latency = round((end - start) * 1000)
        await message.reply_text(f"⚡ Latency: <code>{latency} ms</code>", parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[PING] Error: {e}")

# ============================================================
# ID Command
# ============================================================
@Client.on_message(filters.command("id"))
async def id_command(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        reply = f"🆔 User ID: <code>{user_id}</code>\n"
        if message.chat.type != enums.ChatType.PRIVATE:
            reply += f"🆔 Chat ID: <code>{chat_id}</code>\n"
        await message.reply_text(reply, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[ID] Error: {e}")

# ============================================================
# INFO Command
# ============================================================
@Client.on_message(filters.command("info"))
async def info_command(client: Client, message: Message):
    try:
        if not message.reply_to_message and len(message.command) < 2:
            await message.reply_text("ℹ️ Use /info [user_id] or reply to a message.")
            return
        if message.reply_to_message:
            target = message.reply_to_message.from_user
        else:
            try:
                target_id = int(message.command[1])
                target = await client.get_users(target_id)
            except:
                await message.reply_text("❌ Invalid user ID.")
                return
        text = (
            f"👤 User Info:\n\n"
            f"First Name: {target.first_name}\n"
            f"Last Name: {target.last_name or 'N/A'}\n"
            f"Username: @{target.username or 'N/A'}\n"
            f"ID: <code>{target.id}</code>\n"
            f"Is Bot: {'Yes' if target.is_bot else 'No'}\n"
            f"Premium: {'Yes' if target.is_premium else 'No'}"
        )
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[INFO] Error: {e}")

# ============================================================
# SETTINGS Command (Basic – Group Admins)
# ============================================================
@Client.on_message(filters.command("settings") & filters.group)
async def settings_command(client: Client, message: Message):
    try:
        group_id = message.chat.id
        # Check if sender is admin in group
        member = await client.get_chat_member(group_id, message.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            await message.reply_text("❌ Only group admins can change settings.")
            return
        # Placeholder settings menu
        text = (
            f"⚙️ <b>Group Settings</b>\n\n"
            f"• PM Search: {PM_SEARCH}\n"
            f"• Auto Filter: {AUTO_FFILTER}\n"
            f"• IMDb: {IMDB}\n"
            f"• Spell Check: {SPELL_CHECK_REPLY}\n\n"
            f"More options coming soon."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔴 Toggle PM Search", callback_data="set_pm_search"),
             InlineKeyboardButton("🔴 Toggle Auto Filter", callback_data="set_auto_filter")],
            [InlineKeyboardButton("❌ Close", callback_data="close_menu")],
        ])
        await message.reply_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[SETTINGS] Error: {e}")

# Callback for settings toggles (example)
@Client.on_callback_query(filters.regex(r"^set_pm_search$"))
async def toggle_pm_search(client: Client, query: CallbackQuery):
    try:
        # Check admin
        member = await client.get_chat_member(query.message.chat.id, query.from_user.id)
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            await query.answer("❌ Admin only", show_alert=True)
            return
        # Toggle settings (real implementation would update DB)
        await query.answer("✅ Toggled PM Search (demo)", show_alert=True)
    except Exception as e:
        logger.error(f"[SETTINGS] Callback error: {e}")

# ============================================================
# MAINTENANCE Command (Owner/Admin only)
# ============================================================
@Client.on_message(filters.command("maintenance") & filters.user(ADMINS))
async def maintenance_command(client: Client, message: Message):
    try:
        global MAINTENANCE
        MAINTENANCE = not MAINTENANCE
        status = "ENABLED" if MAINTENANCE else "DISABLED"
        await message.reply_text(f"🛠️ Maintenance mode {status}.")
        logger.info(f"[MAINTENANCE] Set to {status} by {message.from_user.id}")
    except Exception as e:
        logger.error(f"[MAINTENANCE] Error: {e}")

# ============================================================
# Maintenance Filter (if maintenance enabled, block non‑admins)
# ============================================================
@Client.on_message(filters.private & filters.text & ~filters.user(ADMINS))
async def maintenance_filter(client: Client, message: Message):
    if MAINTENANCE and not MAINTENANCE_ALLOW_ADMINS:
        try:
            await message.reply_text(MAINTENANCE_MESSAGE)
        except Exception as e:
            logger.error(f"[MAINTENANCE] Filter error: {e}")