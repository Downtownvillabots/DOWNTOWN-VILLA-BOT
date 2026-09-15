# plugins/broadcast.py
"""
🏨 DOWNTOWN VILLA — ULTIMATE BROADCAST SYSTEM v3.0

Features:
  ✔ Per-channel captions & buttons
  ✔ Auto-delete timer for user broadcasts
  ✔ Global defaults as fallback
  ✔ Live progress, cancel, retry
  ✔ Caption templates, export/import
"""
# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import (
    FloodWait, MessageNotModified, MessageIdInvalid,
    UserIsBlocked, InputUserDeactivated, PeerIdInvalid,
    ChatWriteForbidden, ChatAdminRequired, UserDeactivated,
    UserDeactivatedBan, ChannelPrivate, ChatForbidden,
    UserNotParticipant, MediaEmpty, MessageTooLong,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import db_manager

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

try:
    from core.config import UPDATE_CHNL_LNK as _UPD
    UPDATE_CHNL_LNK = _UPD or "https://t.me/"
except Exception:
    UPDATE_CHNL_LNK = "https://t.me/"

try:
    from core.config import SUPPORT_CHAT as _S
    SUPPORT_CHAT = _S or "https://t.me/"
except Exception:
    SUPPORT_CHAT = "https://t.me/"

logger = logging.getLogger(__name__)
logger.info("[BC] DOWNTOWN VILLA BROADCAST v3.0 loading...")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONFIG
# ═══════════════════════════════════════════════════════════════════════════
BROADCAST_CHANNEL_ID_RAW = os.getenv("BROADCAST_CHANNEL_ID", "0").strip()
try:
    BROADCAST_CHANNEL_ID = int(BROADCAST_CHANNEL_ID_RAW) or None
except (TypeError, ValueError):
    BROADCAST_CHANNEL_ID = None

SESSION_TTL = 900
PROGRESS_EDIT_INTERVAL = 2.5
BROADCAST_BATCH_SIZE = 30
BROADCAST_CONCURRENCY = 5
DEFAULT_DELAY = 0.05
SOURCE_TTL = 3600
AUTODELETE_SCAN_INTERVAL = 60  # seconds

DEFAULT_BROADCAST_CAPTION = (
    "🎬 <b>{file_name}</b>\n"
    "📦 Size: <code>{file_size}</code>\n"
    "⭐ Rating: <b>{rating}</b>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

DIV = "━" * 26
DIV2 = "─" * 26

# Auto-delete timer presets (seconds)
AUTODELETE_PRESETS = [
    (1,  86400,   "1 DAY"),
    (3,  259200,  "3 DAYS"),
    (7,  604800,  "7 DAYS"),
    (10, 864000,  "10 DAYS"),
    (30, 2592000, "30 DAYS"),
    (0,  0,       "NEVER"),
]
AUTODELETE_LABELS = {d: label for _, d, label in AUTODELETE_PRESETS}
AUTODELETE_SECONDS = {d: s for d, s, _ in AUTODELETE_PRESETS}

# Fancy fonts
_M_BOLD = {
    **{chr(ord('A') + i): "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[i] for i in range(10)},
}
_M_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}

def fb(s): return "".join(_M_BOLD.get(c, c) for c in str(s))
def sc(s): return "".join(_M_SC.get(c, c) for c in str(s))


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — FORMATTING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════
def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"

def _fmt_size(size) -> str:
    if not size: return "0 B"
    try: s = float(size)
    except (TypeError, ValueError): return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0; i += 1
    return f"{s:.2f} {units[i]}"

def _fmt_duration(seconds: float) -> str:
    try: seconds = int(max(0, seconds))
    except (TypeError, ValueError): return "0s"
    if seconds < 60: return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24: return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"

def _esc(text) -> str:
    if text is None: return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _progress_colored(current, total, width=10) -> str:
    if total <= 0: return "⬛" * width + " 0%"
    pct = min(100.0, (current / total) * 100.0)
    filled = max(0, min(width, int(width * pct / 100.0)))
    empty = width - filled
    if pct >= 80: block = "🟩"
    elif pct >= 50: block = "🟨"
    elif pct >= 25: block = "🟧"
    else: block = "🟥"
    return block * filled + "⬛" * empty + f" {pct:.1f}%"

def _is_admin(user_id) -> bool:
    try:
        return int(user_id) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _get_db():
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None: return db
    except Exception: pass
    try: return db_manager._db
    except Exception: return None


def _broadcast_coll():
    db = _get_db()
    return db["broadcast_config"] if db is not None else None

def _users_coll():
    db = _get_db()
    return db["users"] if db is not None else None

def _groups_coll():
    db = _get_db()
    return db["groups"] if db is not None else None

def _history_coll():
    db = _get_db()
    return db["broadcast_history"] if db is not None else None

def _autodelete_coll():
    db = _get_db()
    return db["broadcast_autodelete"] if db is not None else None


# ─── Users ───
async def _count_users() -> int:
    c = _users_coll()
    if c is None: return 0
    try: return await c.estimated_document_count()
    except Exception: return 0


async def _get_all_users() -> List[int]:
    c = _users_coll()
    if c is None: return []
    ids = []
    try:
        async for doc in c.find({}, {"id": 1, "user_id": 1}):
            uid = doc.get("id") or doc.get("user_id")
            if uid: ids.append(int(uid))
    except Exception as e:
        logger.warning(f"[BC] users: {e}")
    return ids


async def _delete_user(user_id: int) -> None:
    c = _users_coll()
    if c is None: return
    try:
        await c.delete_many({"$or": [{"id": int(user_id)}, {"user_id": int(user_id)}]})
    except Exception: pass


# ─── Groups ───
async def _count_groups() -> int:
    c = _groups_coll()
    if c is None: return 0
    try: return await c.estimated_document_count()
    except Exception: return 0


async def _get_all_groups() -> List[int]:
    c = _groups_coll()
    if c is None: return []
    ids = []
    try:
        async for doc in c.find({}, {"chat_id": 1, "id": 1, "chat_status": 1}):
            cs = doc.get("chat_status") or {}
            if cs.get("is_disabled"): continue
            cid = doc.get("chat_id") or doc.get("id")
            if cid: ids.append(int(cid))
    except Exception as e:
        logger.warning(f"[BC] groups: {e}")
    return ids


# ─── Channels ───
async def _get_saved_channels() -> List[Dict[str, Any]]:
    c = _broadcast_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"_id": "channels"}) or {}
        return list(doc.get("list") or [])
    except Exception as e:
        logger.warning(f"[BC] channels: {e}"); return []


async def _get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    for ch in await _get_saved_channels():
        if ch.get("chat_id") == int(chat_id):
            return ch
    return None


async def _save_channel(chat_id: int, title: str, username: Optional[str] = None) -> bool:
    c = _broadcast_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = [x for x in (doc.get("list") or []) if x.get("chat_id") != int(chat_id)]
        chans.append({
            "chat_id": int(chat_id),
            "title": title or str(chat_id),
            "username": username,
            "caption": None,
            "buttons": None,
            "added_at": time.time(),
        })
        await c.update_one({"_id": "channels"},
                           {"$set": {"list": chans, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception as e:
        logger.warning(f"[BC] save channel: {e}"); return False


async def _update_channel(chat_id: int, **fields) -> bool:
    c = _broadcast_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        found = False
        for ch in chans:
            if ch.get("chat_id") == int(chat_id):
                ch.update(fields); found = True; break
        if not found: return False
        await c.update_one({"_id": "channels"},
                           {"$set": {"list": chans, "updated_at": time.time()}})
        return True
    except Exception as e:
        logger.warning(f"[BC] update channel: {e}"); return False


async def _remove_channel(chat_id: int) -> bool:
    c = _broadcast_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        new_list = [x for x in chans if x.get("chat_id") != int(chat_id)]
        await c.update_one({"_id": "channels"},
                           {"$set": {"list": new_list, "updated_at": time.time()}})
        return len(new_list) < len(chans)
    except Exception: return False


# ─── Global caption/buttons ───
async def _get_broadcast_caption() -> str:
    c = _broadcast_coll()
    if c is None: return DEFAULT_BROADCAST_CAPTION
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get("caption") or DEFAULT_BROADCAST_CAPTION
    except Exception: return DEFAULT_BROADCAST_CAPTION


async def _set_broadcast_caption(caption: str) -> bool:
    c = _broadcast_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {"caption": caption, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_broadcast_buttons() -> List[Dict[str, Any]]:
    c = _broadcast_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return list(doc.get("buttons") or [])
    except Exception: return []


async def _set_broadcast_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _broadcast_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {"buttons": buttons, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


# ─── History ───
async def _log_broadcast(data: Dict[str, Any]) -> None:
    c = _history_coll()
    if c is None: return
    try:
        data["created_at"] = time.time()
        await c.insert_one(data)
    except Exception: pass


async def _get_history(limit: int = 10) -> List[Dict[str, Any]]:
    c = _history_coll()
    if c is None: return []
    try:
        cursor = c.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        for d in docs: d.pop("_id", None)
        return docs
    except Exception: return []


# ─── Auto-delete DB (NEW) ───
async def _schedule_autodelete(chat_id: int, message_id: int,
                               seconds: int, job_id: str) -> None:
    """Register a message to be deleted after `seconds`."""
    c = _autodelete_coll()
    if c is None: return
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": time.time() + int(seconds),
            "job_id": job_id,
            "created_at": time.time(),
        })
    except Exception as e:
        logger.debug(f"[BC-AD] schedule fail: {e}")


async def _count_scheduled_autodeletes() -> int:
    c = _autodelete_coll()
    if c is None: return 0
    try: return await c.estimated_document_count()
    except Exception: return 0


async def _get_due_autodeletes(limit: int = 200) -> List[Dict[str, Any]]:
    c = _autodelete_coll()
    if c is None: return []
    try:
        cursor = c.find({"delete_at": {"$lte": time.time()}}).limit(limit)
        docs = await cursor.to_list(length=limit)
        return docs
    except Exception: return []


async def _remove_autodelete(doc_id) -> None:
    c = _autodelete_coll()
    if c is None: return
    try: await c.delete_one({"_id": doc_id})
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}

def _new_session(user_id: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[user_id] = {"token": tok, "action": action, "step": 1,
                          "data": data, "expires": time.time() + SESSION_TTL}
    logger.info(f"[BC] session start user={user_id} action={action}")
    return tok

def _get_session(user_id: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(user_id)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(user_id, None); return None
    return s

def _clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)

def _cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — JOBS
# ═══════════════════════════════════════════════════════════════════════════
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}


def _new_job(admin_id, kind, total, source_msg_id, source_chat_id,
             progress_chat_id, progress_msg_id, autodelete_seconds=0) -> str:
    jid = uuid.uuid4().hex[:10]
    _ACTIVE_JOBS[jid] = {
        "id": jid, "admin_id": admin_id, "kind": kind, "total": total,
        "sent": 0, "failed": 0, "blocked": 0, "deleted": 0,
        "started_at": time.time(), "status": "running",
        "cancel_flag": False, "last_edit": 0.0,
        "source_msg_id": source_msg_id, "source_chat_id": source_chat_id,
        "progress_chat_id": progress_chat_id,
        "progress_msg_id": progress_msg_id,
        "autodelete_seconds": int(autodelete_seconds or 0),
    }
    return jid

def _get_job(jid): return _ACTIVE_JOBS.get(jid)

def _finish_job(jid, status="completed"):
    j = _ACTIVE_JOBS.get(jid)
    if j: j["status"] = status; j["finished_at"] = time.time()

def _cleanup_jobs():
    now = time.time()
    for jid in list(_ACTIVE_JOBS.keys()):
        j = _ACTIVE_JOBS[jid]
        if j["status"] in ("completed", "cancelled", "failed"):
            if now - j.get("finished_at", now) > 300:
                _ACTIVE_JOBS.pop(jid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — SOURCES
# ═══════════════════════════════════════════════════════════════════════════
_SOURCES: Dict[str, Dict[str, Any]] = {}
_MANUAL_TARGETS: Dict[int, int] = {}
_BOT_CLIENT: Optional[Client] = None


def _register_source(message: Message) -> str:
    sid = uuid.uuid4().hex[:10]
    _SOURCES[sid] = {
        "message_id": message.id, "chat_id": message.chat.id,
        "created": time.time(), "expires": time.time() + SOURCE_TTL,
        "kind": (message.media.value if message.media else "text"),
    }
    logger.info(f"[BC-SRC] sid={sid} msg={message.id}")
    return sid

def _get_source(sid):
    s = _SOURCES.get(sid)
    if not s: return None
    if time.time() > s["expires"]:
        _SOURCES.pop(sid, None); return None
    return s

def _cleanup_sources():
    now = time.time()
    for sid in list(_SOURCES.keys()):
        if _SOURCES[sid]["expires"] < now: _SOURCES.pop(sid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — CAPTION / BUTTON EFFECTIVE
# ═══════════════════════════════════════════════════════════════════════════
async def _effective_caption(channel: Optional[Dict[str, Any]]) -> str:
    if channel is None or channel.get("caption") is None:
        return await _get_broadcast_caption()
    return channel["caption"]


async def _effective_buttons(channel: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if channel is None or channel.get("buttons") is None:
        return await _get_broadcast_buttons()
    return channel["buttons"]


def _build_kb_from_list(buttons: List[Dict[str, Any]]) -> Optional[InlineKeyboardMarkup]:
    if not buttons: return None
    rows = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url: continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    if not rows: return None
    return InlineKeyboardMarkup(rows)


def _build_caption_for(message: Message, template: str) -> str:
    try:
        file_name = "file"
        file_size_h = "0 B"
        file_caption = message.caption or ""
        for attr in ("video", "document", "audio", "photo", "animation"):
            media = getattr(message, attr, None)
            if media:
                file_name = (getattr(media, "file_name", None)
                             or file_caption[:80] or "file")
                size = getattr(media, "file_size", 0) or 0
                file_size_h = _fmt_size(size)
                break
        year = ""
        m = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", file_name)
        if m: year = m.group(1)
        return template.format(
            file_name=file_name[:100],
            file_size=file_size_h,
            rating="—",
            year=year or "—",
            file_caption=file_caption[:200] if file_caption else "—",
        )
    except Exception as e:
        logger.warning(f"[BC] caption render: {e}")
        return template


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_main(user_count, group_count, chan_count, btn_count, autodelete_count=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 CHANNELS ({chan_count})", callback_data="bc:channels")],
        [InlineKeyboardButton(f"👥 GROUPS ({group_count})", callback_data="bc:groups")],
        [InlineKeyboardButton(f"👤 USERS ({user_count})", callback_data="bc:users_menu")],
        [InlineKeyboardButton("📝 DEFAULT CAPTION", callback_data="bc:caption"),
         InlineKeyboardButton(f"🔘 DEFAULT BUTTONS ({btn_count})", callback_data="bc:buttons")],
        [InlineKeyboardButton("📚 TEMPLATES", callback_data="bc:caption_lib"),
         InlineKeyboardButton("🎯 MANUAL", callback_data="bc:manual")],
        [InlineKeyboardButton(f"⏱️ AUTO-DELETE ({autodelete_count})", callback_data="bc:autodelete")],
        [InlineKeyboardButton("📈 STATS", callback_data="bc:stats"),
         InlineKeyboardButton("📊 HISTORY", callback_data="bc:history")],
        [InlineKeyboardButton("💾 EXPORT", callback_data="bc:export"),
         InlineKeyboardButton("📥 IMPORT", callback_data="bc:import")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_channels(channels):
    rows = []
    for c in channels:
        title = (c.get("title") or "?")[:38]
        cid = c.get("chat_id")
        markers = ""
        if c.get("caption") is not None: markers += "📝"
        if c.get("buttons") is not None: markers += "🔘"
        label = f"📢 {title}"
        if markers: label = f"{markers} {label}"
        rows.append([InlineKeyboardButton(label, callback_data=f"bc:ch_view:{cid}")])
    rows.append([InlineKeyboardButton("➕ ADD CHANNEL", callback_data="bc:ch_add"),
                 InlineKeyboardButton("🔄 REFRESH", callback_data="bc:channels")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")])
    return InlineKeyboardMarkup(rows)


def kb_channel_view(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 EDIT CAPTION", callback_data=f"bc:ch_cap:{chat_id}"),
         InlineKeyboardButton("🔘 EDIT BUTTONS", callback_data=f"bc:ch_btn:{chat_id}")],
        [InlineKeyboardButton("♻️ RESET TO DEFAULTS", callback_data=f"bc:ch_reset:{chat_id}")],
        [InlineKeyboardButton("🗑️ REMOVE CHANNEL", callback_data=f"bc:ch_rm:{chat_id}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:channels"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_caption():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT CAPTION", callback_data="bc:caption_edit")],
        [InlineKeyboardButton("📚 LOAD TEMPLATE", callback_data="bc:caption_lib")],
        [InlineKeyboardButton("♻️ RESET DEFAULT", callback_data="bc:caption_reset")],
        [InlineKeyboardButton("👁️ PREVIEW", callback_data="bc:caption_preview")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_buttons(buttons):
    rows = []
    for i, b in enumerate(buttons, 1):
        name = (b.get("name") or "?")[:40]
        rows.append([InlineKeyboardButton(f"{i}. {name}",
                                          callback_data=f"bc:btn_view:{i-1}")])
    rows.append([InlineKeyboardButton("➕ ADD BUTTON", callback_data="bc:btn_add")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")])
    return InlineKeyboardMarkup(rows)


def kb_button_view(idx):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT NAME", callback_data=f"bc:btn_edit_name:{idx}")],
        [InlineKeyboardButton("🔗 EDIT URL",  callback_data=f"bc:btn_edit_url:{idx}")],
        [InlineKeyboardButton("🗑️ REMOVE",     callback_data=f"bc:btn_rm:{idx}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:buttons"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_main():
    u = await _count_users()
    g = await _count_groups()
    chans = await _get_saved_channels()
    btns = await _get_broadcast_buttons()
    ad = await _count_scheduled_autodeletes()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CONTROL CENTER')}</b>",
        DIV, "",
        f"👤 {sc('users')} · <code>{_fmt_int(u)}</code>",
        f"👥 {sc('groups')} · <code>{_fmt_int(g)}</code>",
        f"📢 {sc('saved channels')} · <code>{len(chans)}</code>",
        f"🔘 {sc('default buttons')} · <code>{len(btns)}</code>",
        f"⏱️ {sc('pending auto-deletes')} · <code>{_fmt_int(ad)}</code>",
        "", DIV2, "",
        f"📌 {sc('each channel can have its own caption & buttons')}",
        f"📌 {sc('user broadcasts support auto-delete timers')}",
        "", DIV2,
        f"🕒 {sc('updated')} · <code>{datetime.now().strftime('%H:%M:%S')}</code>",
    ])
    return text, kb_main(u, g, len(chans), len(btns), ad)


async def _view_channels():
    chans = await _get_saved_channels()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"📢 <b>{fb('BROADCAST CHANNELS')}</b>", DIV, ""]
    if not chans:
        lines += [f"⚪ {sc('no channels saved yet')}", "",
                  f"ᴄʟɪᴄᴋ {sc('add channel')} ᴛᴏ ꜱᴛᴀʀᴛ"]
    else:
        lines.append("📝 = custom caption · 🔘 = custom buttons")
        lines.append("")
        for i, c in enumerate(chans, 1):
            markers = ""
            if c.get("caption") is not None: markers += "📝"
            if c.get("buttons") is not None: markers += "🔘"
            if not markers: markers = "⚪"
            lines.append(f"{i}. {markers} <b>{_esc(c.get('title'))}</b>")
            lines.append(f"   <code>{c.get('chat_id')}</code>")
            lines.append("")
    return "\n".join(lines), kb_channels(chans)


async def _view_channel_detail(chat_id: int):
    ch = await _get_channel(chat_id)
    if not ch: return None
    cap_status = "🌐 using default" if ch.get("caption") is None else "📝 custom"
    btn_count = len(ch.get("buttons") or []) if ch.get("buttons") is not None else None
    btn_status = "🌐 using default" if btn_count is None else f"🔘 {btn_count} custom"
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('CHANNEL DETAILS')}</b>",
        DIV, "",
        f"📛 {sc('title')} · <b>{_esc(ch.get('title'))}</b>",
        f"🆔 {sc('chat id')} · <code>{ch.get('chat_id')}</code>",
    ]
    if ch.get("username"):
        lines.append(f"🔗 {sc('username')} · <code>@{ch.get('username')}</code>")
    lines += ["", DIV2, "",
              f"📝 {sc('caption')} · {cap_status}",
              f"🔘 {sc('buttons')} · {btn_status}",
              "", DIV2, "",
              f"📌 {sc('custom caption/buttons apply only when broadcasting to this channel')}"]
    return "\n".join(lines), kb_channel_view(int(chat_id))


async def _view_groups():
    count = await _count_groups()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"👥 <b>{fb('BROADCAST TO GROUPS')}</b>",
             DIV, "",
             f"📊 {sc('total groups')} · <code>{_fmt_int(count)}</code>",
             "", DIV2,
             f"📌 {sc('groups use the global default caption & buttons')}",
             "", DIV2]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 BROADCAST TO ALL ({count})", callback_data="bc:do_groups")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def _view_users_menu():
    count = await _count_users()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"👤 <b>{fb('BROADCAST TO USERS')}</b>",
             DIV, "",
             f"📊 {sc('total users')} · <code>{_fmt_int(count)}</code>",
             "", DIV2,
             f"📌 {sc('user broadcasts support auto-delete timers')}",
             f"📌 {sc('you will pick a timer before starting')}",
             "", DIV2]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 BROADCAST TO ALL ({count})", callback_data="bc:do_users")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def _view_caption():
    cap = await _get_broadcast_caption()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"📝 <b>{fb('DEFAULT BROADCAST CAPTION')}</b>",
             DIV, "",
             f"<b>{sc('current')}:</b>", "",
             f"<code>{_esc(cap)}</code>",
             "", DIV2, "",
             f"📌 {sc('placeholders')}:",
             f"• <code>{{file_name}}</code> <code>{{file_size}}</code>",
             f"• <code>{{rating}}</code> <code>{{year}}</code> <code>{{file_caption}}</code>"]
    return "\n".join(lines), kb_caption()


async def _view_buttons():
    btns = await _get_broadcast_buttons()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🔘 <b>{fb('DEFAULT BROADCAST BUTTONS')}</b>",
             DIV, ""]
    if not btns:
        lines.append(f"⚪ {sc('no buttons added yet')}")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")
    lines += [DIV2, f"ᴛʜᴇꜱᴇ ᴀʀᴇ ᴜꜱᴇᴅ ꜰᴏʀ ɢʀᴏᴜᴘꜱ ᴀɴᴅ ᴜꜱᴇʀꜱ."]
    return "\n".join(lines), kb_buttons(btns)


async def _view_button_detail(idx):
    btns = await _get_broadcast_buttons()
    if idx < 0 or idx >= len(btns): return None
    b = btns[idx]
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🔘 <b>{fb('BUTTON DETAILS')}</b>",
             DIV, "",
             f"📛 {sc('name')} · <b>{_esc(b.get('name'))}</b>",
             f"🔗 {sc('url')} · <code>{_esc(b.get('url'))}</code>"]
    return "\n".join(lines), kb_button_view(idx)


async def _view_history():
    hist = await _get_history(10)
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"📊 <b>{fb('BROADCAST HISTORY')}</b>",
             DIV, ""]
    if not hist:
        lines.append(f"⚪ {sc('no broadcasts yet')}")
    else:
        for h in hist:
            kind = h.get("kind", "?")
            icon = {"users": "👤", "channels": "📢",
                    "channel": "📢", "groups": "👥"}.get(kind, "📢")
            try:
                t = datetime.fromtimestamp(h.get("created_at", 0)).strftime("%d %b %H:%M")
            except Exception: t = "?"
            ad = h.get("autodelete_seconds", 0)
            ad_str = f" · ⏱️ {_fmt_duration(ad)}" if ad else ""
            lines.append(f"{icon} <b>{kind.upper()}</b> · <code>{t}</code>{ad_str}")
            lines.append(f"   ✅ {h.get('sent',0)}/{h.get('total',0)}")
            lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:history")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.warning(f"[BC] edit: {type(e).__name__}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — /broadcast COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command(["broadcast", "bc"]) & filters.private, group=-500)
async def cmd_broadcast(client: Client, message: Message):
    global _BOT_CLIENT
    _BOT_CLIENT = client
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        try:
            panel = await message.reply_text("🔄 ʟᴏᴀᴅɪɴɢ ᴘᴀɴᴇʟ...")
        except Exception: return
        text, kb = await _view_main()
        await _safe_edit(panel, text, kb)
    except Exception as e:
        logger.exception(f"[BC] /broadcast crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — PANEL CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:main$"), group=-500)
async def cb_main(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_main()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:close$"), group=-500)
async def cb_close(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^bc:cancel_session$"), group=-500)
async def cb_cancel_session(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    text, kb = await _view_main()
    await _safe_edit(q, text, kb)
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — CHANNEL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:channels$"), group=-500)
async def cb_channels(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_channels()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_view:(-?\d+)$"), group=-500)
async def cb_ch_view(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    r = await _view_channel_detail(cid)
    if r is None: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await _safe_edit(q, r[0], r[1]); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_add$"), group=-500)
async def cb_ch_add(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "add_channel")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BROADCAST CHANNEL')}</b>",
        DIV, "",
        f"📝 {sc('send the channel id or @username as next message')}",
        "", DIV2, "",
        f"📌 {sc('examples')}:",
        f"• <code>-1001234567890</code>",
        f"• <code>@mychannel</code>",
        "", f"⚠️ {sc('bot must be admin in that channel')}",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_rm:(-?\d+)$"), group=-500)
async def cb_ch_rm(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await _remove_channel(cid)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ" if ok else "⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ")
    text, kb = await _view_channels()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:ch_reset:(-?\d+)$"), group=-500)
async def cb_ch_reset(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await _update_channel(cid, caption=None, buttons=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    r = await _view_channel_detail(cid)
    if r: await _safe_edit(q, r[0], r[1])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — PER-CHANNEL CAPTION EDITOR
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:ch_cap:(-?\d+)$"), group=-500)
async def cb_ch_cap(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ch = await _get_channel(cid)
    if not ch: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    cur = ch.get("caption")
    cur_disp = "(using global default)" if cur is None else (cur or "(empty)")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('EDIT CHANNEL CAPTION')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(ch.get('title'))}</b>",
        "", DIV2, "",
        f"<b>{sc('current caption')}:</b>",
        f"<code>{_esc(cur_disp)}</code>",
        "", DIV2, "",
        f"📌 {sc('placeholders')}:",
        f"• <code>{{file_name}}</code> <code>{{file_size}}</code>",
        f"• <code>{{rating}}</code> <code>{{year}}</code> <code>{{file_caption}}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ SET CUSTOM CAPTION",
                              callback_data=f"bc:ch_cap_set:{cid}")],
        [InlineKeyboardButton("📚 LOAD TEMPLATE",
                              callback_data=f"bc:ch_cap_tpl:{cid}")],
        [InlineKeyboardButton("♻️ RESET TO DEFAULT",
                              callback_data=f"bc:ch_cap_rst:{cid}")],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"bc:ch_view:{cid}"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_cap_set:(-?\d+)$"), group=-500)
async def cb_ch_cap_set(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "ch_edit_caption", chat_id=cid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('SET CHANNEL CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as next message')}",
        f"📌 {sc('send')} <code>-</code> {sc('to use an empty caption')}",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data=f"bc:ch_cap:{cid}")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_cap_rst:(-?\d+)$"), group=-500)
async def cb_ch_cap_rst(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await _update_channel(cid, caption=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_cap(client, q)


@Client.on_callback_query(filters.regex(r"^bc:ch_cap_tpl:(-?\d+)$"), group=-500)
async def cb_ch_cap_tpl(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    rows = []
    for name in CAPTION_TEMPLATES:
        rows.append([InlineKeyboardButton(f"📝 {name.upper()}",
                                          callback_data=f"bc:ch_cap_use:{cid}:{name}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"bc:ch_cap:{cid}")])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('LOAD CAPTION TEMPLATE')}</b>",
        DIV, "",
        f"📌 {sc('pick a template to apply to this channel')}",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows)); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_cap_use:(-?\d+):(\w+)$"), group=-500)
async def cb_ch_cap_use(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    name = q.matches[0].group(2)
    tpl = CAPTION_TEMPLATES.get(name)
    if not tpl: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    ok = await _update_channel(cid, caption=tpl)
    await q.answer(f"✅ ʟᴏᴀᴅᴇᴅ {name}" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_cap(client, q)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 15 — PER-CHANNEL BUTTON EDITOR
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:ch_btn:(-?\d+)$"), group=-500)
async def cb_ch_btn(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ch = await _get_channel(cid)
    if not ch: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    custom = ch.get("buttons")
    using_default = custom is None
    btns = (await _get_broadcast_buttons()) if using_default else custom
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('CHANNEL BUTTONS')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(ch.get('title'))}</b>",
        "",
        f"📌 {sc('source')} · " + ("🌐 <b>global default</b>"
                                    if using_default else "🔘 <b>custom</b>"),
        "", DIV2, "",
    ]
    if not btns:
        lines.append("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")
    rows = []
    if not using_default:
        for i, b in enumerate(btns, 1):
            rows.append([InlineKeyboardButton(
                f"🗑️ {i}. {(b.get('name') or '?')[:30]}",
                callback_data=f"bc:ch_btn_rm:{cid}:{i-1}")])
        rows.append([InlineKeyboardButton("➕ ADD BUTTON",
                                          callback_data=f"bc:ch_btn_add:{cid}")])
        rows.append([InlineKeyboardButton("♻️ RESET TO DEFAULT",
                                          callback_data=f"bc:ch_btn_rst:{cid}")])
    else:
        rows.append([InlineKeyboardButton("✏️ SET CUSTOM BUTTONS",
                                          callback_data=f"bc:ch_btn_custom:{cid}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"bc:ch_view:{cid}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")])
    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_btn_custom:(-?\d+)$"), group=-500)
async def cb_ch_btn_custom(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    await _update_channel(cid, buttons=[])
    await q.answer("✏️ ᴇᴍᴘᴛʏ ᴄᴜꜱᴛᴏᴍ ꜱᴇᴛ ᴄʀᴇᴀᴛᴇᴅ")
    await cb_ch_btn(client, q)


@Client.on_callback_query(filters.regex(r"^bc:ch_btn_rst:(-?\d+)$"), group=-500)
async def cb_ch_btn_rst(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await _update_channel(cid, buttons=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_btn(client, q)


@Client.on_callback_query(filters.regex(r"^bc:ch_btn_add:(-?\d+)$"), group=-500)
async def cb_ch_btn_add(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "ch_add_button", chat_id=cid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON TO CHANNEL')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
        "", f"📌 {sc('example')}:",
        f"<code>Join Backups | https://t.me/backups</code>",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data=f"bc:ch_btn:{cid}")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_btn_rm:(-?\d+):(\d+)$"), group=-500)
async def cb_ch_btn_rm(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    idx = int(q.matches[0].group(2))
    ch = await _get_channel(cid)
    if not ch or ch.get("buttons") is None:
        return await q.answer("⚠️ ɴᴏ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ", show_alert=True)
    btns = list(ch["buttons"])
    if idx < 0 or idx >= len(btns):
        return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)
    btns.pop(idx)
    await _update_channel(cid, buttons=btns)
    await q.answer("🗑️ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_ch_btn(client, q)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — GLOBAL CAPTION EDITOR
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:caption$"), group=-500)
async def cb_caption(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption_edit$"), group=-500)
async def cb_caption_edit(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "edit_caption")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT DEFAULT CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as next message')}",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption_reset$"), group=-500)
async def cb_caption_reset(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    await _set_broadcast_caption(DEFAULT_BROADCAST_CAPTION)
    await q.answer("✅ ʀᴇꜱᴇᴛ")
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:caption_preview$"), group=-500)
async def cb_caption_preview(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cap = await _get_broadcast_caption()
    try:
        sample = cap.format(file_name="Interstellar.2014.1080p.mkv",
                            file_size="2.4 GB", rating="8.7", year="2014",
                            file_caption="Interstellar (2014)")
    except Exception: sample = cap
    text = "\n".join([f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                      f"👁️ <b>{fb('CAPTION PREVIEW')}</b>",
                      DIV, "", sample])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ BACK", callback_data="bc:caption")]])
    await _safe_edit(q, text, kb); await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17 — GLOBAL BUTTON EDITOR
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:buttons$"), group=-500)
async def cb_buttons(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_buttons()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_view:(\d+)$"), group=-500)
async def cb_btn_view(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    r = await _view_button_detail(idx)
    if r is None: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await _safe_edit(q, r[0], r[1]); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_add$"), group=-500)
async def cb_btn_add(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "add_button")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD DEFAULT BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_rm:(\d+)$"), group=-500)
async def cb_btn_rm(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    btns = await _get_broadcast_buttons()
    if idx < 0 or idx >= len(btns): return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    btns.pop(idx)
    await _set_broadcast_buttons(btns)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    text, kb = await _view_buttons()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:btn_edit_name:(\d+)$"), group=-500)
async def cb_btn_edit_name(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "edit_button_name", idx=idx)
    text = "✏️ ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ɴᴀᴍᴇ."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_edit_url:(\d+)$"), group=-500)
async def cb_btn_edit_url(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "edit_button_url", idx=idx)
    text = "✏️ ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ᴜʀʟ."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL",
                                                     callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18 — CAPTION TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════
CAPTION_TEMPLATES = {
    "default": DEFAULT_BROADCAST_CAPTION,
    "movies": (
        "🎬 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "⭐ Rating: <b>{rating}</b>\n\n"
        "🎞️ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 𝗠𝗼𝘃𝗶𝗲 𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "series": (
        "📺 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n\n"
        "🔥 𝗡𝗲𝘄 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 𝗥𝗲𝗹𝗲𝗮𝘀𝗲\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "minimal": "🎬 <b>{file_name}</b>\n📦 {file_size}",
    "spam": ("🔥 <b>{file_name}</b> 🔥\n📦 {file_size}\n⭐ {rating}\n\n"
             "📢 𝗝𝗼𝗶𝗻 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹"),
}


@Client.on_callback_query(filters.regex(r"^bc:caption_lib$"), group=-500)
async def cb_caption_lib(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    rows = [[InlineKeyboardButton(f"📝 {n.upper()}",
                                  callback_data=f"bc:caption_use:{n}")]
            for n in CAPTION_TEMPLATES]
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="bc:caption")])
    text = "\n".join([f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                      f"📚 <b>{fb('CAPTION TEMPLATES')}</b>",
                      DIV, "",
                      f"📌 {sc('pick a template to load into the global editor')}"])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows)); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption_use:(\w+)$"), group=-500)
async def cb_caption_use(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    name = q.matches[0].group(1)
    tpl = CAPTION_TEMPLATES.get(name)
    if not tpl: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await _set_broadcast_caption(tpl)
    await q.answer(f"✅ ʟᴏᴀᴅᴇᴅ {name}")
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 19 — TEXT INPUT HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=-450)
async def session_input(client, message):
    if not message.from_user: return
    session = _get_session(message.from_user.id)
    if not session: return

    action = session["action"]
    text = (message.text or "").strip()
    logger.info(f"[BC] input action={action}")

    try: message.stop_propagation()
    except Exception: pass

    # ADD CHANNEL
    if action == "add_channel":
        target_id = target_title = target_username = None
        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target_id = chat.id
                target_title = chat.title or text
                target_username = chat.username
            except Exception as e:
                return await message.reply_text(
                    f"❌ ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ <code>{_esc(text)}</code>\n<code>{_esc(e)}</code>",
                    parse_mode=ParseMode.HTML)
        else:
            try:
                target_id = int(text)
                try:
                    chat = await client.get_chat(target_id)
                    target_title = chat.title or str(target_id)
                    target_username = chat.username
                except Exception:
                    target_title = str(target_id)
            except ValueError:
                return await message.reply_text("❌ ꜱᴇɴᴅ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.")
        try:
            me = await client.get_me()
            m = await client.get_chat_member(target_id, me.id)
            st = getattr(m, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await message.reply_text(
                    f"⚠️ ʙᴏᴛ ɪꜱ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ <b>{_esc(target_title)}</b>.",
                    parse_mode=ParseMode.HTML)
        except Exception as e:
            return await message.reply_text(
                f"❌ ᴀᴅᴍɪɴ ᴄʜᴇᴄᴋ ꜰᴀɪʟᴇᴅ:\n<code>{_esc(e)}</code>",
                parse_mode=ParseMode.HTML)
        ok = await _save_channel(target_id, target_title, target_username)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ</b>\n\n"
                f"📛 <b>{_esc(target_title)}</b>\n"
                f"🆔 <code>{target_id}</code>\n\n"
                f"📌 ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ ꜱᴇᴛ ᴀ ᴄᴜꜱᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ/ʙᴜᴛᴛᴏɴꜱ ꜰᴏʀ ɪᴛ.",
                parse_mode=ParseMode.HTML)
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴀᴠᴇ.")
        return

    # EDIT GLOBAL CAPTION
    if action == "edit_caption":
        if len(text) < 3:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await _set_broadcast_caption(text)
        _clear_session(message.from_user.id)
        await message.reply_text("✅ ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ." if ok else "❌ ꜰᴀɪʟᴇᴅ.")
        return

    # ADD GLOBAL BUTTON
    if action == "add_button":
        if "|" not in text:
            return await message.reply_text("❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                                            parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url: url = f"https://{url}"
            else: return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        btns = await _get_broadcast_buttons()
        if len(btns) >= 8:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({"name": name[:60], "url": url, "position": len(btns) + 1})
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text(f"✅ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ: <b>{_esc(name)}</b>",
                                 parse_mode=ParseMode.HTML)
        return

    # EDIT GLOBAL BUTTON NAME
    if action == "edit_button_name":
        idx = session["data"].get("idx")
        btns = await _get_broadcast_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")
        if len(text) < 2: return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        btns[idx]["name"] = text[:60]
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text("✅ ɴᴀᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ.")
        return

    # EDIT GLOBAL BUTTON URL
    if action == "edit_button_url":
        idx = session["data"].get("idx")
        btns = await _get_broadcast_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")
        url = text.strip()
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url: url = f"https://{url}"
            else: return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        btns[idx]["url"] = url
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text("✅ ᴜʀʟ ᴜᴘᴅᴀᴛᴇᴅ.")
        return

    # CHANNEL-SPECIFIC CAPTION
    if action == "ch_edit_caption":
        cid = session["data"].get("chat_id")
        if cid is None:
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇꜱꜱɪᴏɴ.")
        new_cap = "" if text == "-" else text
        if text != "-" and len(text) < 3:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ. ꜱᴇɴᴅ '-' ꜰᴏʀ ᴇᴍᴘᴛʏ.")
        ok = await _update_channel(cid, caption=new_cap)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄʜᴀɴɴᴇʟ ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n"
                f"<code>{_esc(new_cap) if new_cap else '(empty)'}</code>",
                parse_mode=ParseMode.HTML)
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
        return

    # CHANNEL-SPECIFIC ADD BUTTON
    if action == "ch_add_button":
        cid = session["data"].get("chat_id")
        if cid is None:
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇꜱꜱɪᴏɴ.")
        if "|" not in text:
            return await message.reply_text("❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                                            parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url: url = f"https://{url}"
            else: return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        ch = await _get_channel(cid)
        if not ch:
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ᴄʜᴀɴɴᴇʟ ɴᴏᴛ ꜰᴏᴜɴᴅ.")
        existing = ch.get("buttons")
        btns = list(existing) if existing is not None else []
        if len(btns) >= 8:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({"name": name[:60], "url": url, "position": len(btns) + 1})
        ok = await _update_channel(cid, buttons=btns)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ ᴛᴏ ᴄʜᴀɴɴᴇʟ</b>\n\n"
                f"📛 <b>{_esc(name)}</b>\n🔗 <code>{_esc(url)}</code>",
                parse_mode=ParseMode.HTML)
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
        return

    # MANUAL TARGET
    if action == "manual_target":
        target_id = None
        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target_id = chat.id
            except Exception as e:
                return await message.reply_text(f"❌ ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ: {e}")
        else:
            try:
                target_id = int(text)
            except ValueError:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴛᴀʀɢᴇᴛ.")
        _clear_session(message.from_user.id)
        _MANUAL_TARGETS[message.from_user.id] = target_id
        await message.reply_text(
            f"✅ ᴛᴀʀɢᴇᴛ ꜱᴀᴠᴇᴅ · <code>{target_id}</code>\n\n"
            f"📌 ɴᴏᴡ ᴜᴘʟᴏᴀᴅ ᴀ ꜰɪʟᴇ ᴛᴏ ᴛʜᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄʜᴀɴɴᴇʟ.",
            parse_mode=ParseMode.HTML)
        return

    # IMPORT CONFIG
    if action == "import_config":
        try:
            data = json.loads(text)
        except Exception as e:
            _clear_session(message.from_user.id)
            return await message.reply_text(f"❌ ɪɴᴠᴀʟɪᴅ ᴊꜱᴏɴ: {e}")
        btns = data.get("buttons") or []
        cap = data.get("caption") or None
        if isinstance(btns, list):
            clean = []
            for b in btns[:8]:
                if not isinstance(b, dict): continue
                n = (b.get("name") or "").strip()
                u = (b.get("url") or "").strip()
                if n and u:
                    clean.append({"name": n[:60], "url": u, "position": len(clean) + 1})
            await _set_broadcast_buttons(clean)
        if cap: await _set_broadcast_caption(str(cap))
        _clear_session(message.from_user.id)
        await message.reply_text("✅ ᴄᴏɴꜰɪɢ ɪᴍᴘᴏʀᴛᴇᴅ.", parse_mode=ParseMode.HTML)
        return

    _clear_session(message.from_user.id)
    await message.reply_text("⚠️ ᴜɴᴋɴᴏᴡɴ ꜱᴇꜱꜱɪᴏɴ.")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 20 — BROADCAST CHANNEL WATCHER
# ═══════════════════════════════════════════════════════════════════════════
if BROADCAST_CHANNEL_ID:
    @Client.on_message(filters.chat(BROADCAST_CHANNEL_ID) & ~filters.service, group=-499)
    async def broadcast_channel_watcher(client, message):
        global _BOT_CLIENT
        _BOT_CLIENT = client
        try:
            logger.info(f"[BC-WATCH] msg={message.id}")
            sid = _register_source(message)
            manual_btn_row = []
            if message.from_user:
                tid = _MANUAL_TARGETS.pop(message.from_user.id, None)
                if tid:
                    manual_btn_row = [InlineKeyboardButton(
                        "🎯 SEND TO MANUAL TARGET",
                        callback_data=f"bcsend:manual:{sid}:{tid}")]
            rows = []
            if manual_btn_row: rows.append(manual_btn_row)
            rows += [
                [InlineKeyboardButton("📢 CHANNELS", callback_data=f"bcsend:ch:{sid}")],
                [InlineKeyboardButton("👥 GROUPS",   callback_data=f"bcsend:gr:{sid}")],
                [InlineKeyboardButton("👤 USERS",    callback_data=f"bcsend:us:{sid}")],
                [InlineKeyboardButton("❌ CANCEL",   callback_data=f"bcsend:no:{sid}")],
            ]
            kb = InlineKeyboardMarkup(rows)
            await message.reply_text(
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"📢 <b>{fb('BROADCAST READY')}</b>",
                    DIV, "",
                    f"📌 {sc('choose destination')}",
                    f"📢 {sc('channels')} — {sc('uses each channel own caption/buttons')}",
                    f"👥 {sc('groups')} — {sc('uses global default')}",
                    f"👤 {sc('users')} — {sc('pick auto-delete timer')}",
                    "", f"🆔 <code>{sid}</code>",
                ]),
                reply_markup=kb, parse_mode=ParseMode.HTML,
                reply_to_message_id=message.id, quote=True,
            )
        except Exception as e:
            logger.exception(f"[BC-WATCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 21 — DESTINATION PICKER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bcsend:ch:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_ch(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    chans = await _get_saved_channels()
    if not chans: return await q.answer("⚠️ ɴᴏ ꜱᴀᴠᴇᴅ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
    rows = []
    for c in chans:
        title = (c.get("title") or "?")[:38]
        cid = c.get("chat_id")
        markers = ""
        if c.get("caption") is not None: markers += "📝"
        if c.get("buttons") is not None: markers += "🔘"
        label = f"📢 {title}"
        if markers: label = f"{markers} {label}"
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"bcsend:goto_ch:{sid}:{cid}")])
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data=f"bcsend:no:{sid}")])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('SELECT CHANNEL')}</b>",
        DIV, "",
        f"📝 = custom caption · 🔘 = custom buttons",
        "", f"📌 {sc('each channel uses its own caption & buttons if set')}",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows)); await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:goto_ch:([a-f0-9]+):(-?\d+)$"), group=-500)
async def cb_bcsend_goto_ch(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1); target = int(q.matches[0].group(2))
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "channel", targets=[target])


@Client.on_callback_query(filters.regex(r"^bcsend:gr:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_gr(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    total = await _count_groups()
    if total == 0: return await q.answer("⚠️ ɴᴏ ɢʀᴏᴜᴘꜱ", show_alert=True)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ YES, SEND TO {total} GROUPS",
                              callback_data=f"bcsend:goto_gr:{sid}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"bcsend:no:{sid}")],
    ])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('CONFIRM GROUP BROADCAST')}</b>",
        DIV, "",
        f"📊 {sc('total groups')} · <code>{_fmt_int(total)}</code>",
        "", f"📌 {sc('uses global default caption & buttons')}",
    ])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:goto_gr:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_goto_gr(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "groups")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 22 — USER BROADCAST + AUTO-DELETE TIMER PICKER (NEW)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bcsend:us:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_us(client, q):
    """Show the auto-delete timer picker."""
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    total = await _count_users()
    if total == 0: return await q.answer("⚠️ ɴᴏ ᴜꜱᴇʀꜱ", show_alert=True)

    # 2 buttons per row
    rows = []
    row = []
    for d, _, label in AUTODELETE_PRESETS:
        row.append(InlineKeyboardButton(
            f"{'⏱️' if d else '♾️'} {label}",
            callback_data=f"bcsend:us_t:{sid}:{d}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data=f"bcsend:no:{sid}")])

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('AUTO-DELETE TIMER')}</b>",
        DIV, "",
        f"📊 {sc('target users')} · <code>{_fmt_int(total)}</code>",
        "",
        DIV2, "",
        f"📌 {sc('choose how long the message stays in each user chat')}",
        f"📌 {sc('after the timer expires, the message is auto-deleted')}",
        "", DIV2,
        f"💡 {sc('users will still see the file until it is deleted')}",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows)); await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:us_t:([a-f0-9]+):(\d+)$"), group=-500)
async def cb_bcsend_us_timer(client, q):
    """Confirm broadcast with the selected auto-delete timer."""
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    total = await _count_users()
    seconds = AUTODELETE_SECONDS.get(days, 0)
    label = AUTODELETE_LABELS.get(days, f"{days} days")
    ad_text = "♾️ Never" if seconds == 0 else f"⏱️ {label}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ CONFIRM · {ad_text}",
                              callback_data=f"bcsend:us_go:{sid}:{days}")],
        [InlineKeyboardButton("⬅️ CHANGE TIMER",
                              callback_data=f"bcsend:us:{sid}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"bcsend:no:{sid}")],
    ])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('CONFIRM USER BROADCAST')}</b>",
        DIV, "",
        f"📊 {sc('target users')} · <code>{_fmt_int(total)}</code>",
        f"⏱️ {sc('auto-delete')} · <b>{ad_text}</b>",
        "", DIV2, "",
        f"📌 {sc('uses global default caption & buttons')}",
        f"⚠️ {sc('blocked/deleted users will be auto-removed')}",
    ])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:us_go:([a-f0-9]+):(\d+)$"), group=-500)
async def cb_bcsend_us_go(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    seconds = AUTODELETE_SECONDS.get(days, 0)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "users", autodelete_seconds=seconds)


@Client.on_callback_query(filters.regex(r"^bcsend:manual:([a-f0-9]+):(-?\d+)$"), group=-500)
async def cb_bcsend_manual(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1); target = int(q.matches[0].group(2))
    if not _get_source(sid): return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "channel", targets=[target])


@Client.on_callback_query(filters.regex(r"^bcsend:no:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_no(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 23 — BROADCAST ENGINE
# ═══════════════════════════════════════════════════════════════════════════
async def _run_broadcast(client, q, sid, kind, targets=None,
                         autodelete_seconds: int = 0):
    src = _get_source(sid)
    if not src: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    if kind == "channel":
        if not targets: return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛ", show_alert=True)
        target_list = targets; kind_label = "ᴄʜᴀɴɴᴇʟ"
    elif kind == "groups":
        target_list = await _get_all_groups(); kind_label = "ɢʀᴏᴜᴘꜱ"
    else:
        target_list = await _get_all_users(); kind_label = "ᴜꜱᴇʀꜱ"

    total = len(target_list)
    if total == 0: return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)

    # Per-channel caption/buttons
    if kind == "channel" and len(target_list) == 1:
        ch = await _get_channel(target_list[0])
        cap_template = await _effective_caption(ch)
        buttons_list = await _effective_buttons(ch)
    else:
        cap_template = await _get_broadcast_caption()
        buttons_list = await _get_broadcast_buttons()

    try:
        src_msg = await client.get_messages(src["chat_id"], src["message_id"])
    except Exception as e:
        return await q.answer(f"⚠️ ᴄᴀɴɴᴏᴛ ꜰᴇᴛᴄʜ ꜱᴏᴜʀᴄᴇ: {e}"[:180], show_alert=True)
    if not src_msg or src_msg.empty:
        return await q.answer("⚠️ ꜱᴏᴜʀᴄᴇ ᴅᴇʟᴇᴛᴇᴅ", show_alert=True)

    caption = _build_caption_for(src_msg, cap_template)
    kb = _build_kb_from_list(buttons_list)

    progress_chat_id = q.message.chat.id
    try:
        progress_msg = await q.message.edit_text(
            f"🏨 <b>{fb('BROADCAST STARTED')}</b>\n{DIV}\n\n"
            f"📤 {sc('sending to')} <b>{_fmt_int(total)}</b> {kind_label}...",
            parse_mode=ParseMode.HTML)
    except MessageNotModified:
        progress_msg = q.message
    except Exception as e:
        logger.warning(f"[BC-RUN] progress: {e}")
        progress_msg = q.message

    job_id = _new_job(
        admin_id=q.from_user.id, kind=kind, total=total,
        source_msg_id=src["message_id"], source_chat_id=src["chat_id"],
        progress_chat_id=progress_chat_id, progress_msg_id=progress_msg.id,
        autodelete_seconds=autodelete_seconds)
    job = _get_job(job_id)
    job["targets"] = target_list
    job["current_index"] = 0

    task = asyncio.create_task(
        _broadcast_worker(client, job_id, src_msg, caption, kb))
    job["task"] = task


async def _broadcast_worker(client, job_id, src_msg, caption, kb):
    job = _get_job(job_id)
    if not job: return

    targets = job["targets"]; total = job["total"]
    ad_seconds = job.get("autodelete_seconds", 0)
    start_time = time.time()
    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    lock = asyncio.Lock()

    async def _send_one(target_id):
        if job["cancel_flag"]: return "cancelled"
        async with sem:
            if job["cancel_flag"]: return "cancelled"
            try:
                sent = None
                try:
                    sent = await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb)
                except (MediaEmpty, MessageNotModified):
                    sent = await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id)
                # Schedule auto-delete for users
                if (ad_seconds and ad_seconds > 0 and sent
                        and job["kind"] == "users"):
                    try:
                        await _schedule_autodelete(
                            target_id, sent.id, ad_seconds, job_id)
                    except Exception as e:
                        logger.debug(f"[BC-AD] schedule: {e}")
                await asyncio.sleep(DEFAULT_DELAY)
                return "sent"
            except FloodWait as e:
                await asyncio.sleep(max(1, int(e.value)) + 2)
                try:
                    sent = await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb)
                    if (ad_seconds and ad_seconds > 0 and sent
                            and job["kind"] == "users"):
                        try:
                            await _schedule_autodelete(
                                target_id, sent.id, ad_seconds, job_id)
                        except Exception: pass
                    return "sent"
                except Exception:
                    return "failed"
            except UserIsBlocked:
                return "blocked"
            except (InputUserDeactivated, UserDeactivated, UserDeactivatedBan):
                return "deleted"
            except (ChatWriteForbidden, ChatForbidden, ChatAdminRequired,
                    ChannelPrivate, PeerIdInvalid, UserNotParticipant):
                return "failed"
            except Exception as e:
                logger.debug(f"[BC-RUN] fail {target_id}: {type(e).__name__}: {e}")
                return "failed"

    async def _worker(tid):
        result = await _send_one(tid)
        async with lock:
            job["current_index"] += 1
            if result == "sent": job["sent"] += 1
            elif result == "blocked":
                job["blocked"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(tid))
            elif result == "deleted":
                job["deleted"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(tid))
            elif result == "failed": job["failed"] += 1

    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            if job["cancel_flag"]: break
            batch = targets[i:i + BROADCAST_BATCH_SIZE]
            await asyncio.gather(*[_worker(t) for t in batch])
            await _update_progress(client, job)
            _cleanup_jobs()

        if job["cancel_flag"]:
            _finish_job(job_id, "cancelled")
            await _render_done(client, job, cancelled=True)
        else:
            _finish_job(job_id, "completed")
            await _render_done(client, job, cancelled=False)

        await _log_broadcast({
            "job_id": job_id, "kind": job["kind"],
            "admin_id": job["admin_id"], "total": total,
            "sent": job["sent"], "failed": job["failed"],
            "blocked": job["blocked"], "deleted": job["deleted"],
            "elapsed": time.time() - start_time,
            "status": job["status"],
            "autodelete_seconds": ad_seconds,
        })
    except asyncio.CancelledError:
        _finish_job(job_id, "cancelled")
        await _render_done(client, job, cancelled=True)
        raise
    except Exception as e:
        logger.exception(f"[BC-RUN] crashed: {e}")
        _finish_job(job_id, "failed")
        try:
            await client.edit_message_text(
                chat_id=job["progress_chat_id"],
                message_id=job["progress_msg_id"],
                text=f"❌ ʙʀᴏᴀᴅᴄᴀꜱᴛ ꜰᴀɪʟᴇᴅ:\n<code>{_esc(e)}</code>",
                parse_mode=ParseMode.HTML)
        except Exception: pass


def _kind_label(kind):
    return {"channel": "ᴄʜᴀɴɴᴇʟ", "channels": "ᴄʜᴀɴɴᴇʟꜱ",
            "groups": "ɢʀᴏᴜᴘꜱ", "users": "ᴜꜱᴇʀꜱ"}.get(kind, kind)


async def _update_progress(client, job):
    if job["cancel_flag"]: return
    now = time.time()
    if now - job["last_edit"] < PROGRESS_EDIT_INTERVAL and job["current_index"] < job["total"]:
        return
    job["last_edit"] = now

    elapsed = max(0.001, now - job["started_at"])
    processed = job["current_index"]; total = job["total"]
    speed = processed / elapsed if elapsed > 0 else 0
    remaining = max(0, total - processed)
    eta = (remaining / speed) if speed > 0 else 0
    bar = _progress_colored(processed, total, width=14)

    ad = job.get("autodelete_seconds", 0)
    ad_line = ""
    if job["kind"] == "users" and ad > 0:
        ad_line = f"⏱️ {sc('auto-delete')} · <code>{_fmt_duration(ad)}</code>"

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST IN PROGRESS')}</b>",
        DIV, "",
        f"📤 {sc('sending to')} <b>{_kind_label(job['kind'])}</b>",
    ]
    if ad_line: lines.append(ad_line)
    lines += [
        "", bar, "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "", DIV2, "",
        f"📊 {sc('progress')} · <code>{processed}/{total}</code>",
        f"⚡ {sc('speed')} · <code>{speed:.1f}/s</code>",
        f"⏱️ {sc('eta')} · <code>{_fmt_duration(eta)}</code>",
    ]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "⏹️ CANCEL", callback_data=f"bcstop:{job['id']}")]])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text="\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except MessageNotModified: pass
    except Exception as e:
        logger.debug(f"[BC-RUN] progress edit: {e}")


async def _render_done(client, job, cancelled):
    elapsed = time.time() - job["started_at"]
    title = "🛑 ᴄᴀɴᴄᴇʟʟᴇᴅ" if cancelled else "✅ ᴄᴏᴍᴘʟᴇᴛᴇ"
    ad = job.get("autodelete_seconds", 0)
    ad_line = ""
    if job["kind"] == "users" and ad > 0:
        ad_line = f"⏱️ {sc('auto-delete')} · <code>{_fmt_duration(ad)}</code>"
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST ' + ('CANCELLED' if cancelled else 'COMPLETE'))}</b>",
        DIV, "",
        f"📤 {sc('target')} · <b>{_kind_label(job['kind'])}</b>",
    ]
    if ad_line: lines.append(ad_line)
    lines += [
        "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "", DIV2,
        f"🕒 {sc('total time')} · <code>{_fmt_duration(elapsed)}</code>",
        "", f"<b>{title}</b>",
    ]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "❌ CLOSE", callback_data=f"bcend:{job['id']}")]])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text="\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except MessageNotModified: pass
    except Exception as e:
        logger.warning(f"[BC-RUN] done edit: {e}")


@Client.on_callback_query(filters.regex(r"^bcstop:([a-f0-9]+)$"), group=-500)
async def cb_bcstop(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    jid = q.matches[0].group(1)
    job = _get_job(jid)
    if not job: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    job["cancel_flag"] = True
    job["status"] = "cancelled"
    await q.answer("⏹️ ᴄᴀɴᴄᴇʟʟɪɴɢ...")


@Client.on_callback_query(filters.regex(r"^bcend:([a-f0-9]+)$"), group=-500)
async def cb_bcend(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("✅ ᴅᴏɴᴇ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 24 — AUTODELETE BACKGROUND LOOP (NEW)
# ═══════════════════════════════════════════════════════════════════════════
async def _autodelete_loop():
    """Delete expired broadcast messages every AUTODELETE_SCAN_INTERVAL seconds."""
    while True:
        try:
            await asyncio.sleep(AUTODELETE_SCAN_INTERVAL)
            if _BOT_CLIENT is None: continue
            due = await _get_due_autodeletes(limit=200)
            if not due: continue
            deleted = 0; failed = 0
            for doc in due:
                cid = doc.get("chat_id")
                mid = doc.get("message_id")
                if not cid or not mid:
                    await _remove_autodelete(doc.get("_id")); continue
                try:
                    await _BOT_CLIENT.delete_messages(int(cid), int(mid))
                    deleted += 1
                except Exception as e:
                    failed += 1
                    logger.debug(f"[BC-AD] delete {cid}/{mid}: "
                                 f"{type(e).__name__}: {e}")
                # Always remove from DB after attempt (avoid infinite retry)
                await _remove_autodelete(doc.get("_id"))
            if deleted or failed:
                logger.info(f"[BC-AD] processed {len(due)} · "
                            f"deleted={deleted} failed={failed}")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[BC-AD] loop: {e}")


try:
    asyncio.get_event_loop().create_task(_autodelete_loop())
except Exception as e:
    logger.warning(f"[BC-AD] task: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 25 — MANUAL TARGET
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:manual$"), group=-500)
async def cb_manual(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "manual_target")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('MANUAL TARGET')}</b>",
        DIV, "",
        f"📝 {sc('send a chat id or @username as next message')}",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "❌ CANCEL", callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 26 — AUTODELETE PANEL
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:autodelete$"), group=-500)
async def cb_autodelete(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    count = await _count_scheduled_autodeletes()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('AUTO-DELETE STATUS')}</b>",
        DIV, "",
        f"📊 {sc('pending deletions')} · <code>{_fmt_int(count)}</code>",
        "",
        DIV2, "",
        f"📌 {sc('when broadcasting to users, you pick a timer')}",
        f"📌 {sc('after the timer expires, messages are auto-deleted')}",
        f"📌 {sc('the scheduler runs every')} <code>{AUTODELETE_SCAN_INTERVAL}s</code>",
        "", DIV2, "",
        f"🎛️ {sc('available presets')}:",
    ])
    for d, s, label in AUTODELETE_PRESETS:
        if s == 0:
            text += f"\n• ♾️ {label}"
        else:
            text += f"\n• ⏱️ {label}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:autodelete")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    await _safe_edit(q, text, kb); await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 27 — STATS / HISTORY / EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:stats$"), group=-500)
async def cb_stats(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    hist = await _get_history(100)
    total_b = len(hist)
    total_sent = sum(h.get("sent", 0) for h in hist)
    total_failed = sum(h.get("failed", 0) for h in hist)
    total_blocked = sum(h.get("blocked", 0) for h in hist)
    total_deleted = sum(h.get("deleted", 0) for h in hist)
    ad_pending = await _count_scheduled_autodeletes()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('BROADCAST STATISTICS')}</b>",
        DIV, "",
        f"🔢 {sc('total broadcasts')} · <code>{_fmt_int(total_b)}</code>",
        "", DIV2, "",
        f"✅ {sc('sent')} · <code>{_fmt_int(total_sent)}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(total_failed)}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(total_blocked)}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(total_deleted)}</code>",
        "", DIV2, "",
        f"⏱️ {sc('pending auto-deletes')} · <code>{_fmt_int(ad_pending)}</code>",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:stats"),
         InlineKeyboardButton("◀️ BACK", callback_data="bc:main")],
    ])
    await _safe_edit(q, "\n".join(lines), kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:history$"), group=-500)
async def cb_history(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_history()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:export$"), group=-500)
async def cb_export(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    btns = await _get_broadcast_buttons()
    cap = await _get_broadcast_caption()
    data = {"buttons": btns, "caption": cap,
            "exported_at": datetime.now().isoformat()}
    text = json.dumps(data, indent=2, ensure_ascii=False)
    bio = BytesIO(text.encode("utf-8"))
    bio.name = "broadcast_config.json"
    try:
        await client.send_document(
            chat_id=q.from_user.id, document=bio,
            caption=(f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
                     f"💾 <b>{fb('BROADCAST CONFIG EXPORT')}</b>"),
            parse_mode=ParseMode.HTML)
        await q.answer("✅ ᴇxᴘᴏʀᴛᴇᴅ")
    except Exception as e:
        await q.answer(f"❌ {e}"[:180], show_alert=True)


@Client.on_callback_query(filters.regex(r"^bc:import$"), group=-500)
async def cb_import(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "import_config")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📥 <b>{fb('IMPORT CONFIG')}</b>",
        DIV, "",
        f"📝 {sc('send the JSON config as next message')}",
    ])
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "❌ CANCEL", callback_data="bc:cancel_session")]])
    await _safe_edit(q, text, kb); await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 28 — CLEANUP + LOG
# ═══════════════════════════════════════════════════════════════════════════
async def _broadcast_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(120)
            _cleanup_sessions()
            _cleanup_jobs()
            _cleanup_sources()
        except asyncio.CancelledError: break
        except Exception: pass


try:
    asyncio.get_event_loop().create_task(_broadcast_cleanup_loop())
except Exception as e:
    logger.warning(f"[BC] cleanup task: {e}")


logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  [BROADCAST] v3.0 LOADED ✅                                    ║")
logger.info("║                                                                ║")
logger.info("║  Commands:  /broadcast  /bc                                    ║")
logger.info("║                                                                ║")
logger.info("║  ✨ Per-channel captions & buttons                             ║")
logger.info("║  ✨ Auto-delete timer for user broadcasts                      ║")
logger.info("║  ✨ Global defaults as fallback                                ║")
logger.info("║                                                                ║")
logger.info("║  User broadcast flow:                                          ║")
logger.info("║    1. Upload file → tap 👤 USERS                               ║")
logger.info("║    2. Pick timer: 1d / 3d / 7d / 10d / 30d / never             ║")
logger.info("║    3. Confirm → broadcast starts                               ║")
logger.info("║    4. After timer expires, messages auto-delete                ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
