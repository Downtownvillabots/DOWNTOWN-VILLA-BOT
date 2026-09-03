# ============================================================
# plugins/superbroadcast.py – Super Broadcast / Multi-Channel Distribution
# Command: /superbroadcast
# Allows admin to create one release (poster + files) and distribute to
# selected channels, all channels, PM users, or both.
# Uses config.py, core.permissions, database.users, database.files.
# ============================================================

import logging
import asyncio
import html
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    Message, Photo, Document, Video, Audio
)
from pyrogram.errors import (
    FloodWait, ChatAdminRequired, PeerIdInvalid, Forbidden,
    MessageDeleteForbidden, RPCError, UserIsBlocked, InputUserDeactivated
)

from config import (
    ADMINS,
    DELETE_TIME,
    BROADCAST_MAX_CONCURRENT,
    BROADCAST_RETRY_COUNT,
    BROADCAST_FLOOD_WAIT_MODE,
    BROADCAST_DELAY,
    BROADCAST_BATCH_SIZE,
    BROADCAST_PROGRESS_INTERVAL,
    BROADCAST_LOG_CHANNEL,
    DISTRIBUTION_CHANNELS,
)
from core.permissions import is_admin
from database.connection import get_user_db
from database.users import (
    get_all_users,
    get_user,
    add_user,
)
from database.files import (
    get_media_dbs,
    get_media_collections,
    get_media_labels,
)
from core.helpers import (
    render_caption,
    human_size,
    extract_metadata_from_filename,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# CONSTANTS
# ============================================================
COLLECTION_CHANNELS = "superbroadcast_channels"
COLLECTION_HISTORY = "superbroadcast_history"

def get_channels_collection():
    return get_user_db()[COLLECTION_CHANNELS]

def get_history_collection():
    return get_user_db()[COLLECTION_HISTORY]

# ============================================================
# GLOBAL CAPTION STORAGE
# ============================================================
async def get_global_caption() -> str:
    col = get_channels_collection()
    doc = await col.find_one({"type": "global_caption"})
    if doc and doc.get("caption"):
        return doc["caption"]
    return "🎬 <b>{title}</b>\n\n📁 {filename}\n💾 {filesize}\n🔗 {link}"

async def set_global_caption(caption: str):
    col = get_channels_collection()
    await col.update_one({"type": "global_caption"}, {"$set": {"caption": caption}}, upsert=True)

async def get_channel_caption(channel_id: int) -> Optional[str]:
    col = get_channels_collection()
    doc = await col.find_one({"channel_id": channel_id})
    return doc.get("caption") if doc else None

async def set_channel_caption(channel_id: int, caption: str):
    col = get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": {"caption": caption}})

async def reset_channel_caption(channel_id: int):
    col = get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": {"caption": None}})

# ============================================================
# CHANNEL MANAGEMENT
# ============================================================
async def add_channel(channel_id: int) -> bool:
    col = get_channels_collection()
    exists = await col.find_one({"channel_id": channel_id})
    if exists:
        return False
    await col.insert_one({
        "channel_id": channel_id,
        "enabled": True,
        "caption": None,
        "last_broadcast": None,
        "last_error": None,
        "title": "",
        "username": ""
    })
    return True

async def remove_channel(channel_id: int):
    col = get_channels_collection()
    await col.delete_one({"channel_id": channel_id})

async def get_all_channels() -> List[dict]:
    col = get_channels_collection()
    channels = []
    async for doc in col.find({"type": {"$ne": "global_caption"}}):
        channels.append(doc)
    return channels

async def update_channel(channel_id: int, **kwargs):
    col = get_channels_collection()
    await col.update_one({"channel_id": channel_id}, {"$set": kwargs})

async def validate_channel(client: Client, channel_id: int) -> Tuple[str, str]:
    try:
        chat = await client.get_chat(channel_id)
        title = chat.title or str(channel_id)
        member = await client.get_chat_member(channel_id, "me")
        if member.status == enums.ChatMemberStatus.ADMINISTRATOR:
            return "CONNECTED", title
        return "BOT_NOT_ADMIN", title
    except PeerIdInvalid:
        return "INVALID", ""
    except ChatAdminRequired:
        return "BOT_NOT_ADMIN", ""
    except Exception as e:
        logger.error(f"[SUPERBROADCAST] Channel validation error: {e}")
        return "ERROR", ""

# ============================================================
# SESSION STATE (per admin)
# ============================================================
SUPER_STATE: Dict[int, Dict[str, Any]] = {}

async def start_release_session(user_id: int):
    SUPER_STATE[user_id] = {
        "stage": "poster",
        "poster": None,
        "files": [],
        "title": "",
        "caption": None,
        "selected_channels": [],
        "pm_distribution": False,
        "paused": False,
        "cancelled": False,
    }

async def clear_release_session(user_id: int):
    SUPER_STATE.pop(user_id, None)

# ============================================================
# MAIN COMMAND
# ============================================================
@Client.on_message(filters.command("superbroadcast") & filters.private)
async def superbroadcast_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("❌ **Admin Only** – You are not authorized.")
        return
    logger.info(f"[SUPERBROADCAST] Admin {message.from_user.id} opened dashboard")
    await show_main_dashboard(client, message.chat.id)

# ============================================================
# MAIN DASHBOARD
# ============================================================
async def show_main_dashboard(client: Client, chat_id: int, message_id: int = None):
    try:
        channels = await get_all_channels()
        users_count = await get_user_db()["users"].count_documents({})

        text = (
            "╔══════════════════════════════════════════════════╗\n"
            "║         🚀 SUPER BROADCAST CORE                 ║\n"
            "║           RELEASE DISTRIBUTION                   ║\n"
            "╚══════════════════════════════════════════════════╝\n\n"
            "🟢 SYSTEM: ONLINE\n"
            "👤 ADMIN: AUTHORIZED\n"
            f"📡 CHANNELS: {len(channels)}\n"
            f"👥 USERS: {users_count:,}\n"
            "📝 CAPTION ENGINE: ACTIVE\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📊 DISTRIBUTION STATUS\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🟢 Connected Channels : {len(channels)}\n"
            "👥 PM Distribution     : ENABLED\n\n"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 NEW RELEASE", callback_data="sb_new_release")],
            [InlineKeyboardButton("📡 CHANNELS", callback_data="sb_channels"),
             InlineKeyboardButton("👥 USER PM", callback_data="sb_pm_settings")],
            [InlineKeyboardButton("📝 CAPTIONS", callback_data="sb_captions"),
             InlineKeyboardButton("⚙️ SETTINGS", callback_data="sb_settings")],
            [InlineKeyboardButton("📊 HISTORY", callback_data="sb_history"),
             InlineKeyboardButton("📈 STATISTICS", callback_data="sb_stats")],
            [InlineKeyboardButton("🔄 REFRESH", callback_data="sb_refresh"),
             InlineKeyboardButton("❌ CLOSE", callback_data="sb_close")],
        ])
        if message_id:
            await client.edit_message_text(chat_id, message_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
        else:
            await client.send_message(chat_id, text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)
    except Exception as e:
        logger.error(f"[SUPERBROADCAST] Dashboard error: {e}")

# ============================================================
# CHANNEL MANAGEMENT CALLBACKS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_main$"))
async def sb_back_to_main(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await show_main_dashboard(client, query.message.chat.id, query.message.id)

@Client.on_callback_query(filters.regex(r"^sb_refresh$"))
async def sb_refresh(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await show_main_dashboard(client, query.message.chat.id, query.message.id)

@Client.on_callback_query(filters.regex(r"^sb_close$"))
async def sb_close(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.delete()
    await query.answer("Closed")

@Client.on_callback_query(filters.regex(r"^sb_channels$"))
async def sb_channels_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    text = "📡 **CHANNEL MANAGEMENT**\n\n"
    if channels:
        for i, ch in enumerate(channels, 1):
            status = "🟢" if ch.get("enabled", True) else "🔴"
            title = ch.get("title") or ch["channel_id"]
            text += f"{status} {i}. {html.escape(title)}\n"
    else:
        text += "No channels configured.\n\nUse ➕ ADD to add channel IDs."
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ADD", callback_data="sb_add_channel"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="sb_refresh_channels")],
        [InlineKeyboardButton("🗑️ REMOVE", callback_data="sb_remove_channel_menu"),
         InlineKeyboardButton("🧪 TEST", callback_data="sb_test_channels")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_add_channel$"))
async def sb_add_channel_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "➕ **ADD CHANNEL**\n\nSend the channel ID(s) (comma separated):\n\n"
        "Example:\n-1001234567890,-1009876543210",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_channels")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "add_channel"}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS) & filters.regex(r"^-?\d"))
async def sb_capture_channel_ids(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "add_channel":
        return
    ids = message.text.replace(" ", "").split(",")
    added, failed = 0, []
    for id_str in ids:
        try:
            cid = int(id_str)
        except ValueError:
            failed.append(id_str)
            continue
        if await add_channel(cid):
            added += 1
        else:
            failed.append(id_str)
    SUPER_STATE.pop(user_id, None)
    await message.reply_text(f"✅ Added {added} channels. Failed: {len(failed)} {failed}")
    await sb_channels_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_remove_channel_menu$"))
async def sb_remove_channel_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    if not channels:
        await query.answer("No channels configured", show_alert=True)
        return
    keyboard = []
    for ch in channels:
        title = ch.get("title") or ch["channel_id"]
        keyboard.append([InlineKeyboardButton(f"🗑️ {html.escape(title)}", callback_data=f"sb_rm_{ch['channel_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_channels")])
    await query.message.edit_text("🗑️ **Select channel to remove:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_rm_(\-?\d+)$"))
async def sb_remove_channel_confirm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    await remove_channel(cid)
    logger.info(f"[SUPERBROADCAST] Admin removed channel {cid}")
    await query.answer(f"Removed {cid}", show_alert=True)
    await sb_channels_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_refresh_channels$"))
async def sb_refresh_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    for ch in channels:
        status, title = await validate_channel(client, ch["channel_id"])
        await update_channel(ch["channel_id"], status=status, title=title)
    await query.answer("✅ Refreshed channel statuses")
    await sb_channels_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_test_channels$"))
async def sb_test_channels(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    for ch in channels:
        status, _ = await validate_channel(client, ch["channel_id"])
        await update_channel(ch["channel_id"], status=status)
    await query.answer("✅ Tested all channels", show_alert=True)
    await sb_channels_menu(client, query)

# ============================================================
# CAPTIONS MENU
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_captions$"))
async def sb_captions_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 GLOBAL DEFAULT", callback_data="sb_caption_global")],
        [InlineKeyboardButton("📡 PER-CHANNEL", callback_data="sb_caption_channel_menu")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text("📝 **CAPTION CENTER**\n\nChoose caption type:\n\n", reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_global$"))
async def sb_global_caption_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    caption = await get_global_caption()
    text = (
        "🌐 **GLOBAL DEFAULT CAPTION**\n\n"
        "**Current:**\n"
        f"{html.escape(caption)}\n\n"
        "**Placeholders:**\n"
        "`{title}`, `{filename}`, `{filesize}`, `{quality}`, `{year}`, `{language}`, `{season}`, `{episode}`, `{part}`, `{channel}`, `{date}`, `{time}`, `{link}`\n\n"
        "**HTML Example:**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "💾 Size: {filesize}\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ VIEW", callback_data="sb_caption_global_view"),
         InlineKeyboardButton("✏️ EDIT", callback_data="sb_caption_global_edit")],
        [InlineKeyboardButton("🔄 RESET", callback_data="sb_caption_global_reset"),
         InlineKeyboardButton("🧪 TEST", callback_data="sb_caption_global_test")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_captions")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_edit$"))
async def sb_global_caption_edit_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.message.edit_text(
        "✏️ **EDIT GLOBAL CAPTION**\n\nSend the new caption as a message.\n\n"
        "**Example HTML:**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "💾 Size: {filesize}\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```\n\nNow send your caption:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_caption_global")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "edit_global_caption"}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def sb_capture_global_caption(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "edit_global_caption":
        return
    await set_global_caption(message.text.html)
    SUPER_STATE.pop(user_id, None)
    logger.info(f"[SUPERBROADCAST] Global caption updated by {user_id}")
    await message.reply_text("✅ **Global caption updated.**")
    await sb_global_caption_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_reset$"))
async def sb_global_caption_reset(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await set_global_caption("🎬 <b>{title}</b>\n\n📁 {filename}\n🔗 {link}")
    await query.answer("✅ Global caption reset", show_alert=True)
    await sb_global_caption_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_caption_global_test$"))
async def sb_global_caption_test(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("🧪 Test sent", show_alert=True)
    test_data = {
        "title": "Example Movie",
        "filename": "Example.Movie.1080p.mkv",
        "filesize": "1.2 GB",
        "quality": "1080p",
        "year": "2026",
        "language": "English",
        "season": "S01",
        "episode": "E03",
        "part": "Part 1",
        "channel": "Test Channel",
        "link": "https://t.me/example"
    }
    caption = await get_global_caption()
    text = render_caption(caption, test_data)
    await client.send_message(query.from_user.id, text, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_caption_channel_menu$"))
async def sb_caption_channel_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    channels = await get_all_channels()
    keyboard = []
    for ch in channels:
        title = ch.get("title") or ch["channel_id"]
        keyboard.append([InlineKeyboardButton(f"📡 {html.escape(title)}", callback_data=f"sb_chcap_{ch['channel_id']}")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_captions")])
    await query.message.edit_text("📡 **Select channel for caption edit:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_chcap_(\-?\d+)$"))
async def sb_channel_caption_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    col = get_channels_collection()
    ch = await col.find_one({"channel_id": cid})
    if not ch:
        await query.answer("Channel not found", show_alert=True)
        return
    current = ch.get("caption") or (await get_global_caption())
    text = (
        "📝 **CHANNEL CAPTION**\n\n"
        f"📡 Channel: {html.escape(ch.get('title', cid))}\n"
        f"🟢 Status: {ch.get('status', 'UNKNOWN')}\n\n"
        "**Current Caption:**\n"
        f"{html.escape(current)}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👁️ VIEW", callback_data=f"sb_chcap_view_{cid}"),
         InlineKeyboardButton("✏️ EDIT", callback_data=f"sb_chcap_edit_{cid}")],
        [InlineKeyboardButton("🔄 RESET TO DEFAULT", callback_data=f"sb_chcap_reset_{cid}"),
         InlineKeyboardButton("🧪 TEST", callback_data=f"sb_chcap_test_{cid}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_caption_channel_menu")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_chcap_edit_(\-?\d+)$"))
async def sb_channel_caption_edit_prompt(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[3])
    await query.message.edit_text(
        "✏️ **EDIT CHANNEL CAPTION**\n\nSend the new caption.\n\n"
        "**Example HTML:**\n"
        "```html\n"
        "<b>🎬 {title}</b>\n"
        "<i>Quality: {quality}</i>\n"
        "🔗 <a href='{link}'>Get Files</a>\n"
        "```\n\nNow send your caption:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data=f"sb_chcap_{cid}")]]),
        parse_mode=enums.ParseMode.HTML
    )
    SUPER_STATE[query.from_user.id] = {"stage": "edit_channel_caption", "channel_id": cid}

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def sb_capture_channel_caption(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "edit_channel_caption":
        return
    cid = state["channel_id"]
    await set_channel_caption(cid, message.text.html)
    SUPER_STATE.pop(user_id, None)
    logger.info(f"[SUPERBROADCAST] Channel caption updated for {cid} by {user_id}")
    await message.reply_text("✅ **Channel caption updated.**")
    await sb_caption_channel_menu(client, message)

@Client.on_callback_query(filters.regex(r"^sb_chcap_reset_(\-?\d+)$"))
async def sb_channel_caption_reset(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[3])
    await reset_channel_caption(cid)
    await query.answer("✅ Channel caption reset", show_alert=True)
    await sb_channel_caption_menu(client, query)

@Client.on_callback_query(filters.regex(r"^sb_chcap_test_(\-?\d+)$"))
async def sb_channel_caption_test(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("🧪 Test sent", show_alert=True)
    cid = int(query.data.split("_")[3])
    col = get_channels_collection()
    ch = await col.find_one({"channel_id": cid})
    caption = ch.get("caption") or (await get_global_caption())
    test_data = {
        "title": "Example Movie",
        "filename": "Example.Movie.1080p.mkv",
        "filesize": "1.2 GB",
        "quality": "1080p",
        "year": "2026",
        "language": "English",
        "channel": ch.get("title", cid),
        "link": "https://t.me/example"
    }
    text = render_caption(caption, test_data)
    await client.send_message(query.from_user.id, text, parse_mode=enums.ParseMode.HTML)

# ============================================================
# PM SETTINGS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_pm_settings$"))
async def sb_pm_settings(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = get_channels_collection()
    doc = await col.find_one({"type": "pm_settings"})
    enabled = doc.get("enabled", True) if doc else True
    text = f"👥 **PM DISTRIBUTION**\n\nEnabled: {'✅' if enabled else '❌'}\n\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ ENABLE", callback_data="sb_pm_enable"),
         InlineKeyboardButton("❌ DISABLE", callback_data="sb_pm_disable")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_pm_enable$"))
async def sb_pm_enable(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = get_channels_collection()
    await col.update_one({"type": "pm_settings"}, {"$set": {"enabled": True}}, upsert=True)
    await query.answer("✅ PM distribution enabled", show_alert=True)
    await sb_pm_settings(client, query)

@Client.on_callback_query(filters.regex(r"^sb_pm_disable$"))
async def sb_pm_disable(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = get_channels_collection()
    await col.update_one({"type": "pm_settings"}, {"$set": {"enabled": False}}, upsert=True)
    await query.answer("❌ PM distribution disabled", show_alert=True)
    await sb_pm_settings(client, query)

# ============================================================
# NEW RELEASE WIZARD
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_new_release$"))
async def sb_new_release_start(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await start_release_session(query.from_user.id)
    await query.message.reply_text(
        "🎬 **NEW RELEASE**\n\nSend a **poster** (photo) to begin.\n\n"
        "Or send /cancel to abort.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data="sb_cancel_release")]]),
        parse_mode=enums.ParseMode.HTML
    )

@Client.on_callback_query(filters.regex(r"^sb_cancel_release$"))
async def sb_cancel_release(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await clear_release_session(query.from_user.id)
    await query.message.edit_text("❌ **Release cancelled.**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]]))
    await query.answer("Cancelled")

@Client.on_message(filters.private & filters.user(ADMINS) & (filters.photo | filters.document | filters.video | filters.audio))
async def sb_release_media_collect(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") not in ("poster", "files"):
        return

    if state["stage"] == "poster":
        if message.photo:
            state["poster"] = message.photo.file_id
            state["stage"] = "files"
            await message.reply_text(
                "📦 **Now send files** (multiple allowed).\n\nWhen done, click ✅ FINISH FILES.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ FINISH FILES", callback_data="sb_finish_files")]])
            )
        else:
            await message.reply_text("Please send a photo as poster, or /cancel.")
        return

    if state["stage"] == "files":
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name or "Document"
        elif message.video:
            file_id = message.video.file_id
            file_name = "Video"
        elif message.audio:
            file_id = message.audio.file_id
            file_name = "Audio"
        else:
            await message.reply_text("❌ Unsupported file type.")
            return
        meta = extract_metadata_from_filename(file_name)
        meta.update({"filename": file_name, "filesize": human_size(message.document.file_size if message.document else message.video.file_size if message.video else 0)})
        state["files"].append({"file_id": file_id, "file_name": file_name, "metadata": meta})
        logger.info(f"[SUPERBROADCAST] Admin {user_id} added file {file_name}")
        await message.reply_text(f"✅ Added file: <code>{html.escape(file_name)}</code> (Total: {len(state['files'])})", parse_mode=enums.ParseMode.HTML)

# ============================================================
# DESTINATION SELECTION
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_finish_files$"))
async def sb_finish_files(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "files":
        await query.answer("No active release session", show_alert=True)
        return
    if not state["files"]:
        await query.answer("⚠️ No files collected yet", show_alert=True)
        return
    await query.message.edit_text(
        "🎬 **Release Title**\n\nSend the title (or /skip to use default).",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ SKIP", callback_data="sb_title_skip")]]),
        parse_mode=enums.ParseMode.HTML
    )
    state["stage"] = "title"

@Client.on_callback_query(filters.regex(r"^sb_title_skip$"))
async def sb_title_skip(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "title":
        return
    state["title"] = "Release"
    state["stage"] = "destination"
    await sb_show_destination_menu(client, query)

@Client.on_message(filters.private & filters.text & filters.user(ADMINS))
async def sb_capture_release_title(client: Client, message: Message):
    user_id = message.from_user.id
    state = SUPER_STATE.get(user_id)
    if not state or state.get("stage") != "title":
        return
    state["title"] = message.text.strip()
    state["stage"] = "destination"
    logger.info(f"[SUPERBROADCAST] Release title set to {state['title']} by {user_id}")
    await message.reply_text("✅ Title set. Now choose destination.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 SELECT DESTINATION", callback_data="sb_dest_menu")]]))

@Client.on_callback_query(filters.regex(r"^sb_dest_menu$"))
async def sb_show_destination_menu(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state or state.get("stage") != "destination":
        return
    text = (
        "🎯 **SELECT DESTINATION**\n\n"
        "• 📡 SELECT CHANNELS\n"
        "• 📡 ALL CHANNELS\n"
        "• 👥 ALL USERS (PM)\n"
        "• 🌐 CHANNELS + USERS\n\n"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 SELECT CHANNELS", callback_data="sb_dest_select")],
        [InlineKeyboardButton("📡 ALL CHANNELS", callback_data="sb_dest_all")],
        [InlineKeyboardButton("👥 ALL USERS / PM", callback_data="sb_dest_pm")],
        [InlineKeyboardButton("🌐 CHANNELS + USERS", callback_data="sb_dest_both")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="sb_cancel_release")],
    ])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_dest_select$"))
async def sb_dest_select(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    enabled = [ch for ch in channels if ch.get("enabled", True)]
    if not enabled:
        await query.answer("No enabled channels", show_alert=True)
        return
    state["selected_channels"] = []
    await sb_show_channel_selection(client, query, 0)

async def sb_show_channel_selection(client: Client, query: CallbackQuery, page: int):
    state = SUPER_STATE.get(query.from_user.id)
    channels = await get_all_channels()
    enabled = [ch for ch in channels if ch.get("enabled", True)]
    per_page = 5
    start = page * per_page
    end = start + per_page
    page_channels = enabled[start:end]
    keyboard = []
    for ch in page_channels:
        title = ch.get("title") or ch["channel_id"]
        selected = "☑️" if ch["channel_id"] in state.get("selected_channels", []) else "☐"
        keyboard.append([InlineKeyboardButton(f"{selected} {html.escape(title)}", callback_data=f"sb_toggle_{ch['channel_id']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"sb_dest_page_{page-1}"))
    if end < len(enabled):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"sb_dest_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("✅ CONFIRM", callback_data="sb_dest_confirm")])
    keyboard.append([InlineKeyboardButton("⬅️ BACK", callback_data="sb_dest_menu")])
    await query.message.edit_text("📡 **Select channels**\n\nClick to toggle:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_dest_page_(\d+)$"))
async def sb_dest_page(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    page = int(query.data.split("_")[3])
    await sb_show_channel_selection(client, query, page)

@Client.on_callback_query(filters.regex(r"^sb_toggle_(\-?\d+)$"))
async def sb_toggle_channel(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    cid = int(query.data.split("_")[2])
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    if cid in state.get("selected_channels", []):
        state["selected_channels"].remove(cid)
    else:
        state["selected_channels"].append(cid)
    await sb_show_channel_selection(client, query, 0)

@Client.on_callback_query(filters.regex(r"^sb_dest_all$"))
async def sb_dest_all(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    state["selected_channels"] = [ch["channel_id"] for ch in channels if ch.get("enabled", True)]
    state["stage"] = "dest_confirm"
    await query.message.edit_text(f"📡 **ALL CHANNELS selected ({len(state['selected_channels'])})**\n\nReady?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START", callback_data="sb_start_broadcast")],
        [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
    ]))

@Client.on_callback_query(filters.regex(r"^sb_dest_pm$"))
async def sb_dest_pm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    state["selected_channels"] = []
    state["pm_distribution"] = True
    state["stage"] = "dest_confirm"
    await query.message.edit_text("👥 **PM DISTRIBUTION**\n\nBroadcast to all users?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START", callback_data="sb_start_broadcast")],
        [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
    ]))

@Client.on_callback_query(filters.regex(r"^sb_dest_both$"))
async def sb_dest_both(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    channels = await get_all_channels()
    state["selected_channels"] = [ch["channel_id"] for ch in channels if ch.get("enabled", True)]
    state["pm_distribution"] = True
    state["stage"] = "dest_confirm"
    await query.message.edit_text(f"🌐 **CHANNELS + USERS** ({len(state['selected_channels'])} channels)", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START", callback_data="sb_start_broadcast")],
        [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
    ]))

@Client.on_callback_query(filters.regex(r"^sb_dest_confirm$"))
async def sb_dest_confirm(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        return
    selected = state.get("selected_channels", [])
    pm = state.get("pm_distribution", False)
    if not selected and not pm:
        await query.answer("No destination selected", show_alert=True)
        return
    await query.message.edit_text(f"📡 **DESTINATIONS**\n\nChannels: {len(selected)}\nPM: {'Yes' if pm else 'No'}\n\nReady?", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START", callback_data="sb_start_broadcast")],
        [InlineKeyboardButton("🔙 CHANGE", callback_data="sb_dest_menu")]
    ]))

# ============================================================
# BROADCAST EXECUTION
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_start_broadcast$"))
async def sb_start_broadcast(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    state = SUPER_STATE.get(query.from_user.id)
    if not state:
        await query.answer("Session expired", show_alert=True)
        return
    release = {
        "title": state.get("title", "Release"),
        "poster": state.get("poster"),
        "files": state.get("files", []),
        "caption": state.get("caption"),
        "channels": state.get("selected_channels", []),
        "pm": state.get("pm_distribution", False)
    }
    logger.info(f"[SUPERBROADCAST] Admin {query.from_user.id} started broadcast for {release['title']}")
    asyncio.create_task(sb_execute_broadcast(client, query.from_user.id, release))
    await query.message.edit_text("🚀 **BROADCAST STARTED**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 LOGS", callback_data="sb_live_logs")]]))

async def sb_send_log_channel(client: Client, text: str):
    if not BROADCAST_LOG_CHANNEL:
        return
    try:
        await client.send_message(BROADCAST_LOG_CHANNEL, text, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[SUPERBROADCAST] Log sent to {BROADCAST_LOG_CHANNEL}")
    except Exception as e:
        logger.error(f"[SUPERBROADCAST] Log channel error: {e}")

async def sb_execute_broadcast(client: Client, admin_id: int, release: dict):
    try:
        logger.info(f"[SUPERBROADCAST] Executing broadcast for '{release['title']}'")
        total_channels = len(release["channels"])
        total_users = await get_user_db()["users"].count_documents({}) if release["pm"] else 0
        completed_channels = 0
        failed_channels = 0
        sent_users = 0
        failed_users = 0
        start_time = time.time()

        # Send to channels
        for ch_id in release["channels"]:
            try:
                await sb_send_release_to_channel(client, ch_id, release)
                completed_channels += 1
                logger.info(f"[SUPERBROADCAST] Sent to channel {ch_id}")
            except FloodWait as e:
                logger.warning(f"[SUPERBROADCAST] FloodWait on {ch_id}: {e.value}s")
                await asyncio.sleep(e.value)
                try:
                    await sb_send_release_to_channel(client, ch_id, release)
                    completed_channels += 1
                except Exception as e2:
                    failed_channels += 1
                    logger.error(f"[SUPERBROADCAST] Failed channel {ch_id} after flood: {e2}")
            except Exception as e:
                failed_channels += 1
                logger.error(f"[SUPERBROADCAST] Failed channel {ch_id}: {e}")

        # Send to users
        if release["pm"]:
            users_cursor = get_user_db()["users"].find({})
            async for user in users_cursor:
                user_id = user.get("_id")
                if not user_id:
                    continue
                try:
                    await sb_send_release_to_user(client, user_id, release)
                    sent_users += 1
                except FloodWait as e:
                    logger.warning(f"[SUPERBROADCAST] FloodWait for user {user_id}: {e.value}s")
                    await asyncio.sleep(e.value)
                    try:
                        await sb_send_release_to_user(client, user_id, release)
                        sent_users += 1
                    except Exception:
                        failed_users += 1
                except (UserIsBlocked, InputUserDeactivated):
                    failed_users += 1
                except Exception:
                    failed_users += 1

        elapsed = time.time() - start_time
        # Save history
        col = get_history_collection()
        await col.insert_one({
            "title": release["title"],
            "admin_id": admin_id,
            "timestamp": datetime.utcnow(),
            "channels_total": total_channels,
            "channels_success": completed_channels,
            "channels_failed": failed_channels,
            "users_total": total_users,
            "users_sent": sent_users,
            "users_failed": failed_users,
            "duration": elapsed,
            "status": "COMPLETED" if failed_channels == 0 and failed_users == 0 else "PARTIAL"
        })
        logger.info(f"[SUPERBROADCAST] Broadcast completed in {elapsed}s. Channels: {completed_channels}/{total_channels}, Users: {sent_users}/{total_users}")
        await client.send_message(admin_id, "✅ **Broadcast completed**")
    except Exception as e:
        logger.exception(f"[SUPERBROADCAST] Broadcast crashed: {e}")

async def sb_send_release_to_channel(client: Client, channel_id: int, release: dict):
    caption_template = release.get("caption") or (await get_channel_caption(channel_id)) or (await get_global_caption())
    data = {
        "title": release["title"],
        "channel": "channel",
        "date": datetime.now().strftime("%d %b %Y"),
        "time": datetime.now().strftime("%H:%M"),
        "link": ""
    }
    if release["files"]:
        first = release["files"][0]
        data.update(first["metadata"])
        data["filename"] = first["file_name"]
        data["filesize"] = first["metadata"].get("filesize", "0 B")
        data["quality"] = first["metadata"].get("quality", "")
    caption = render_caption(caption_template, data)
    if release["poster"]:
        await client.send_photo(channel_id, release["poster"], caption=caption, parse_mode=enums.ParseMode.HTML)
    else:
        await client.send_message(channel_id, caption, parse_mode=enums.ParseMode.HTML)
    for file in release["files"]:
        await client.send_cached_media(channel_id, file["file_id"], caption=caption, parse_mode=enums.ParseMode.HTML)

async def sb_send_release_to_user(client: Client, user_id: int, release: dict):
    caption_template = release.get("caption") or (await get_global_caption())
    data = {
        "title": release["title"],
        "channel": "PM",
        "date": datetime.now().strftime("%d %b %Y"),
        "time": datetime.now().strftime("%H:%M"),
        "link": ""
    }
    if release["files"]:
        first = release["files"][0]
        data.update(first["metadata"])
        data["filename"] = first["file_name"]
        data["filesize"] = first["metadata"].get("filesize", "0 B")
    caption = render_caption(caption_template, data)
    if release["poster"]:
        await client.send_photo(user_id, release["poster"], caption=caption, parse_mode=enums.ParseMode.HTML)
    else:
        await client.send_message(user_id, caption, parse_mode=enums.ParseMode.HTML)
    for file in release["files"]:
        sent = await client.send_cached_media(user_id, file["file_id"])
        asyncio.create_task(sb_auto_delete(client, user_id, sent.id))

async def sb_auto_delete(client: Client, chat_id: int, message_id: int):
    await asyncio.sleep(DELETE_TIME)
    try:
        await client.delete_messages(chat_id, message_id)
        logger.info(f"[SUPERBROADCAST] Auto-deleted message {message_id}")
    except Exception as e:
        logger.error(f"[SUPERBROADCAST] Auto-delete error: {e}")

# ============================================================
# HISTORY & STATS
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_history$"))
async def sb_history(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = get_history_collection()
    history = []
    async for doc in col.find().sort("timestamp", -1).limit(10):
        history.append(doc)
    text = "📊 **HISTORY**\n\n"
    if history:
        for h in history:
            text += f"🟢 {h['title']} – {h['timestamp'].strftime('%d %b %Y %H:%M')}\n"
            text += f"   Ch: {h['channels_success']}/{h['channels_total']} | Users: {h['users_sent']}/{h['users_total']}\n"
    else:
        text += "No broadcasts yet."
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

@Client.on_callback_query(filters.regex(r"^sb_stats$"))
async def sb_stats(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    col = get_history_collection()
    total = await col.count_documents({})
    channels = 0
    users = 0
    async for doc in col.find({}):
        channels += doc.get("channels_success", 0)
        users += doc.get("users_sent", 0)
    text = f"📈 **STATISTICS**\n\nTotal Broadcasts: {total}\nTotal Channel Deliveries: {channels}\nTotal PM Deliveries: {users}\n"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text(text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# ============================================================
# SETTINGS (placeholder)
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_settings$"))
async def sb_settings(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="sb_main")]])
    await query.message.edit_text("⚙️ **SETTINGS**\n\nComing soon.", reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

# ============================================================
# LIVE LOGS (placeholder)
# ============================================================
@Client.on_callback_query(filters.regex(r"^sb_live_logs$"))
async def sb_live_logs(client: Client, query: CallbackQuery):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    await query.answer("Check /admin -> LOGS")

# ============================================================
# INITIALIZE DISTRIBUTION CHANNELS FROM ENV
# ============================================================
async def initialize_distribution_channels():
    channels_env = environ.get("DISTRIBUTION_CHANNELS", "")
    if not channels_env:
        logger.info("[SUPERBROADCAST] No DISTRIBUTION_CHANNELS env var")
        return
    for ch_str in channels_env.split(","):
        try:
            cid = int(ch_str.strip())
        except ValueError:
            continue
        exists = await get_channels_collection().find_one({"channel_id": cid})
        if not exists:
            await add_channel(cid)
            logger.info(f"[SUPERBROADCAST] Added channel {cid} from env")

async def __init_sb_on_start():
    await initialize_distribution_channels()

asyncio.get_event_loop().create_task(__init_sb_on_start())