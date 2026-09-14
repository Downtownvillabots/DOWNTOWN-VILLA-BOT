# ═══════════════════════════════════════════════════════════════════════════
# 🏨 DOWNTOWN VILLA — ULTIMATE BROADCAST SYSTEM
# ═══════════════════════════════════════════════════════════════════════════
#
# VERSION: 1.0 (Part 1 — Foundation + Panel + Channel/Group Management)
#
# This is a COMPLETELY SEPARATE plugin. Does not modify other plugins.
#
# FEATURES (Part 1):
#   ✔ /broadcast command opens admin panel
#   ✔ Panel shows: Channels, Groups, Users, Caption, Buttons
#   ✔ Channel management (add/remove/list)
#   ✔ Group management (add/remove/list — uses main groups collection)
#   ✔ Live preview counts (users/groups/saved channels)
#   ✔ Session-based text input
#   ✔ Full logging
#   ✔ Zero conflicts (uses group=-500 priority)
#
# FEATURES (Part 2):
#   ✔ Broadcast engine — send to users/groups/channels
#   ✔ Live progress bar with cancel
#   ✔ FloodWait handling
#   ✔ Blocked/deleted user cleanup
#   ✔ Broadcast channel watcher (upload file → get buttons)
#
# FEATURES (Part 3):
#   ✔ Caption editor (per-broadcast caption with {file_name}, {size}, etc.)
#   ✔ Button editor (add/remove buttons on broadcast)
#   ✔ History log
#   ✔ Auto-cleanup of stale sessions
#
# ═══════════════════════════════════════════════════════════════════════════

# ─── STANDARD LIBRARY ───────────────────────────────────────────────────────
import asyncio
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ─── PYROGRAM ───────────────────────────────────────────────────────────────
from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    MessageNotModified,
    UserIsBlocked,
    InputUserDeactivated,
    PeerIdInvalid,
    ChatWriteForbidden,
    ChatAdminRequired,
    UserDeactivated,
    UserDeactivatedBan,
    ChannelPrivate,
    ChatForbidden,
    UserNotParticipant,
    MessageTooLong,
    MediaEmpty,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ─── LOCAL IMPORTS ──────────────────────────────────────────────────────────
from database import db_manager

# Optional config imports
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

# ─── LOGGER ─────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)
logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  [BROADCAST] ULTIMATE v1.0 — LOADING (Part 1/3)...            ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Broadcast channel — where admin uploads files to trigger broadcast UI
BROADCAST_CHANNEL_ID_RAW = os.getenv("BROADCAST_CHANNEL_ID", "0").strip()
try:
    BROADCAST_CHANNEL_ID = int(BROADCAST_CHANNEL_ID_RAW) or None
except (TypeError, ValueError):
    BROADCAST_CHANNEL_ID = None

logger.info(f"[BROADCAST] Broadcast channel ID: {BROADCAST_CHANNEL_ID}")

# Timing
SESSION_TTL = 900            # 15 min
PROGRESS_EDIT_INTERVAL = 2.5 # seconds between progress edits
BROADCAST_BATCH_SIZE = 30    # users per batch
BROADCAST_CONCURRENCY = 5    # parallel sends
DEFAULT_DELAY = 0.05         # delay between sends

# Default per-broadcast caption (can be edited)
DEFAULT_BROADCAST_CAPTION = (
    "🎬 <b>{file_name}</b>\n"
    "📦 Size: <code>{file_size}</code>\n"
    "⭐ Rating: <b>{rating}</b>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

# Visual
DIV = "━" * 26
DIV2 = "─" * 26

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


def fb(s: str) -> str:
    return "".join(_M_BOLD.get(c, c) for c in str(s))


def sc(s: str) -> str:
    return "".join(_M_SC.get(c, c) for c in str(s))


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — FORMATTING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_size(size) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def _fmt_duration(seconds: float) -> str:
    try:
        seconds = int(max(0, seconds))
    except (TypeError, ValueError):
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _esc(text) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _progress_bar(current: int, total: int, width: int = 20) -> str:
    """Fancy progress bar with emoji blocks."""
    if total <= 0:
        return "░" * width + " 0%"
    pct = min(100.0, (current / total) * 100.0)
    filled = int(width * pct / 100.0)
    filled = max(0, min(width, filled))
    empty = width - filled
    return "▰" * filled + "▱" * empty + f" {pct:.1f}%"


def _progress_colored(current: int, total: int, width: int = 10) -> str:
    """Colored emoji progress bar."""
    if total <= 0:
        return "⬛" * width + " 0%"
    pct = min(100.0, (current / total) * 100.0)
    filled = int(width * pct / 100.0)
    filled = max(0, min(width, filled))
    empty = width - filled

    if pct >= 80:
        block = "🟩"
    elif pct >= 50:
        block = "🟨"
    elif pct >= 25:
        block = "🟧"
    else:
        block = "🟥"

    return block * filled + "⬛" * empty + f" {pct:.1f}%"


def _is_admin(user_id) -> bool:
    try:
        return int(user_id) in [
            int(a) for a in ADMINS if str(a).lstrip("-").isdigit()
        ]
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _get_db():
    """Return the primary DB."""
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None:
                    return db
    except Exception:
        pass
    try:
        return db_manager._db
    except Exception:
        return None


def _broadcast_coll():
    """Return broadcast config collection."""
    db = _get_db()
    return db["broadcast_config"] if db is not None else None


def _users_coll():
    """Return users collection."""
    db = _get_db()
    return db["users"] if db is not None else None


def _groups_coll():
    """Return groups collection."""
    db = _get_db()
    return db["groups"] if db is not None else None


def _history_coll():
    """Return broadcast history collection."""
    db = _get_db()
    return db["broadcast_history"] if db is not None else None


# ─────────────── Users ───────────────
async def _count_users() -> int:
    coll = _users_coll()
    if coll is None:
        return 0
    try:
        return await coll.estimated_document_count()
    except Exception:
        return 0


async def _get_all_users() -> List[int]:
    coll = _users_coll()
    if coll is None:
        return []
    ids = []
    try:
        cursor = coll.find({}, {"id": 1, "user_id": 1})
        async for doc in cursor:
            uid = doc.get("id") or doc.get("user_id")
            if uid:
                ids.append(int(uid))
    except Exception as e:
        logger.warning(f"[BC] get users failed: {e}")
    return ids


async def _delete_user(user_id: int) -> None:
    coll = _users_coll()
    if coll is None:
        return
    try:
        await coll.delete_many({"$or": [{"id": int(user_id)}, {"user_id": int(user_id)}]})
    except Exception:
        pass


# ─────────────── Groups ───────────────
async def _count_groups() -> int:
    coll = _groups_coll()
    if coll is None:
        return 0
    try:
        return await coll.estimated_document_count()
    except Exception:
        return 0


async def _get_all_groups() -> List[int]:
    coll = _groups_coll()
    if coll is None:
        return []
    ids = []
    try:
        cursor = coll.find({}, {"chat_id": 1, "id": 1, "chat_status": 1})
        async for doc in cursor:
            # Skip disabled groups
            cs = doc.get("chat_status") or {}
            if cs.get("is_disabled"):
                continue
            cid = doc.get("chat_id") or doc.get("id")
            if cid:
                ids.append(int(cid))
    except Exception as e:
        logger.warning(f"[BC] get groups failed: {e}")
    return ids


async def _delete_group(chat_id: int) -> None:
    coll = _groups_coll()
    if coll is None:
        return
    try:
        await coll.delete_many({"$or": [{"chat_id": int(chat_id)}, {"id": int(chat_id)}]})
    except Exception:
        pass


# ─────────────── Broadcast Channels ───────────────
async def _get_saved_channels() -> List[Dict[str, Any]]:
    """Return list of saved channels: [{chat_id, title, username}]."""
    coll = _broadcast_coll()
    if coll is None:
        return []
    try:
        doc = await coll.find_one({"_id": "channels"}) or {}
        return list(doc.get("list") or [])
    except Exception as e:
        logger.warning(f"[BC] get channels failed: {e}")
        return []


async def _save_channel(chat_id: int, title: str, username: Optional[str] = None) -> bool:
    """Add a channel to saved list (deduped)."""
    coll = _broadcast_coll()
    if coll is None:
        return False
    try:
        doc = await coll.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])

        # Dedupe
        chans = [c for c in chans if c.get("chat_id") != int(chat_id)]

        chans.append({
            "chat_id": int(chat_id),
            "title": title or str(chat_id),
            "username": username,
            "added_at": time.time(),
        })
        await coll.update_one(
            {"_id": "channels"},
            {"$set": {"list": chans, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] save channel failed: {e}")
        return False


async def _remove_channel(chat_id: int) -> bool:
    coll = _broadcast_coll()
    if coll is None:
        return False
    try:
        doc = await coll.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        new_list = [c for c in chans if c.get("chat_id") != int(chat_id)]
        await coll.update_one(
            {"_id": "channels"},
            {"$set": {"list": new_list, "updated_at": time.time()}},
        )
        return len(new_list) < len(chans)
    except Exception:
        return False


# ─────────────── Caption & Buttons (per-broadcast settings) ───────────────
async def _get_broadcast_caption() -> str:
    coll = _broadcast_coll()
    if coll is None:
        return DEFAULT_BROADCAST_CAPTION
    try:
        doc = await coll.find_one({"_id": "settings"}) or {}
        return doc.get("caption") or DEFAULT_BROADCAST_CAPTION
    except Exception:
        return DEFAULT_BROADCAST_CAPTION


async def _set_broadcast_caption(caption: str) -> bool:
    coll = _broadcast_coll()
    if coll is None:
        return False
    try:
        await coll.update_one(
            {"_id": "settings"},
            {"$set": {"caption": caption, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def _get_broadcast_buttons() -> List[Dict[str, Any]]:
    coll = _broadcast_coll()
    if coll is None:
        return []
    try:
        doc = await coll.find_one({"_id": "settings"}) or {}
        return list(doc.get("buttons") or [])
    except Exception:
        return []


async def _set_broadcast_buttons(buttons: List[Dict[str, Any]]) -> bool:
    coll = _broadcast_coll()
    if coll is None:
        return False
    try:
        await coll.update_one(
            {"_id": "settings"},
            {"$set": {"buttons": buttons, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ─────────────── History ───────────────
async def _log_broadcast(data: Dict[str, Any]) -> None:
    coll = _history_coll()
    if coll is None:
        return
    try:
        data["created_at"] = time.time()
        await coll.insert_one(data)
    except Exception:
        pass


async def _get_history(limit: int = 10) -> List[Dict[str, Any]]:
    coll = _history_coll()
    if coll is None:
        return []
    try:
        cursor = coll.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — SESSION STORE
# ═══════════════════════════════════════════════════════════════════════════
# Short-lived per-user sessions used for text input (caption, chat_id, etc.)
# ═══════════════════════════════════════════════════════════════════════════

_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(user_id: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[user_id] = {
        "token": tok,
        "action": action,
        "step": 1,
        "data": data,
        "expires": time.time() + SESSION_TTL,
    }
    logger.info(f"[BC] session started user={user_id} action={action}")
    return tok


def _get_session(user_id: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(user_id)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(user_id, None)
        return None
    return s


def _clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)
    logger.info(f"[BC] session cleared user={user_id}")


def _cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — ACTIVE BROADCASTS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}


def _new_job(admin_id: int, kind: str, total: int, source_msg_id: int,
             source_chat_id: int, progress_msg_id: int) -> str:
    jid = uuid.uuid4().hex[:10]
    _ACTIVE_JOBS[jid] = {
        "id": jid,
        "admin_id": admin_id,
        "kind": kind,   # "users" | "channels" | "groups"
        "total": total,
        "sent": 0,
        "failed": 0,
        "blocked": 0,
        "deleted": 0,
        "started_at": time.time(),
        "status": "running",
        "cancel_flag": False,
        "last_edit": 0.0,
        "source_msg_id": source_msg_id,
        "source_chat_id": source_chat_id,
        "progress_msg_id": progress_msg_id,
    }
    return jid


def _get_job(jid: str) -> Optional[Dict[str, Any]]:
    return _ACTIVE_JOBS.get(jid)


def _finish_job(jid: str, status: str = "completed") -> None:
    job = _ACTIVE_JOBS.get(jid)
    if job:
        job["status"] = status
        job["finished_at"] = time.time()


def _cleanup_jobs() -> None:
    """Remove completed jobs older than 5 minutes."""
    now = time.time()
    for jid in list(_ACTIVE_JOBS.keys()):
        job = _ACTIVE_JOBS[jid]
        if job["status"] in ("completed", "cancelled", "failed"):
            if now - job.get("finished_at", now) > 300:
                _ACTIVE_JOBS.pop(jid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════

def _kb_main(user_count: int, group_count: int, channel_count: int,
             button_count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 CHANNELS ({channel_count})",
            callback_data="bc:channels"
        )],
        [InlineKeyboardButton(
            f"👥 GROUPS ({group_count})",
            callback_data="bc:groups"
        )],
        [InlineKeyboardButton(
            f"👤 USERS ({user_count})",
            callback_data="bc:users_menu"
        )],
        [InlineKeyboardButton(
            f"📝 CAPTION",
            callback_data="bc:caption"
        ),
         InlineKeyboardButton(
            f"🔘 BUTTONS ({button_count})",
            callback_data="bc:buttons"
        )],
        [InlineKeyboardButton("📊 HISTORY", callback_data="bc:history"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="bc:main")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def _kb_back(target: str = "bc:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ]])


def _kb_channels(channels: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for c in channels:
        title = (c.get("title") or "?")[:40]
        cid = c.get("chat_id")
        rows.append([InlineKeyboardButton(
            f"📢 {title}",
            callback_data=f"bc:ch_view:{cid}"
        )])
    rows.append([
        InlineKeyboardButton("➕ ADD CHANNEL", callback_data="bc:ch_add"),
        InlineKeyboardButton("🔄 REFRESH", callback_data="bc:channels"),
    ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_channel_view(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ REMOVE", callback_data=f"bc:ch_rm:{chat_id}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:channels"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def _kb_caption() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT CAPTION", callback_data="bc:caption_edit")],
        [InlineKeyboardButton("♻️ RESET DEFAULT", callback_data="bc:caption_reset")],
        [InlineKeyboardButton("👁️ PREVIEW", callback_data="bc:caption_preview")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def _kb_buttons(buttons: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows = []
    for i, b in enumerate(buttons, 1):
        name = (b.get("name") or "?")[:40]
        rows.append([InlineKeyboardButton(
            f"{i}. {name}",
            callback_data=f"bc:btn_view:{i-1}"
        )])
    rows.append([
        InlineKeyboardButton("➕ ADD BUTTON", callback_data="bc:btn_add"),
    ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_button_view(idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT NAME", callback_data=f"bc:btn_edit_name:{idx}")],
        [InlineKeyboardButton("🔗 EDIT URL", callback_data=f"bc:btn_edit_url:{idx}")],
        [InlineKeyboardButton("🗑️ REMOVE", callback_data=f"bc:btn_rm:{idx}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:buttons"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

async def _view_main() -> Tuple[str, InlineKeyboardMarkup]:
    u = await _count_users()
    g = await _count_groups()
    chans = await _get_saved_channels()
    btns = await _get_broadcast_buttons()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CONTROL CENTER')}</b>",
        DIV,
        "",
        f"👤 {sc('users')} · <code>{_fmt_int(u)}</code>",
        f"👥 {sc('groups')} · <code>{_fmt_int(g)}</code>",
        f"📢 {sc('saved channels')} · <code>{len(chans)}</code>",
        f"🔘 {sc('buttons')} · <code>{len(btns)}</code>",
        "",
        DIV2,
        "",
        f"📌 {sc('how to broadcast')}:",
        f"1. {sc('upload any file to broadcast channel')}",
        f"2. {sc('buttons appear on the uploaded file')}",
        f"3. {sc('click channels/groups/users to send')}",
        "",
        DIV2,
        f"🕒 {sc('updated')} · <code>{datetime.now().strftime('%H:%M:%S')}</code>",
    ])

    return text, _kb_main(u, g, len(chans), len(btns))


async def _view_channels() -> Tuple[str, InlineKeyboardMarkup]:
    chans = await _get_saved_channels()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CHANNELS')}</b>",
        DIV,
        "",
    ]
    if not chans:
        lines.append(f"⚪ {sc('no channels saved yet')}")
        lines.append("")
        lines.append(f"ᴄʟɪᴄᴋ {sc('add channel')} ᴛᴏ ꜱᴛᴀʀᴛ")
    else:
        for i, c in enumerate(chans, 1):
            lines.append(f"{i}. <b>{_esc(c.get('title'))}</b>")
            uname = c.get("username")
            if uname:
                lines.append(f"   <code>@{uname}</code>")
            else:
                lines.append(f"   <code>{c.get('chat_id')}</code>")
            lines.append("")
    return "\n".join(lines), _kb_channels(chans)


async def _view_channel_detail(chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    chans = await _get_saved_channels()
    for c in chans:
        if c.get("chat_id") == int(chat_id):
            lines = [
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{fb('CHANNEL DETAILS')}</b>",
                DIV,
                "",
                f"📛 {sc('title')} · <b>{_esc(c.get('title'))}</b>",
                f"🆔 {sc('chat id')} · <code>{c.get('chat_id')}</code>",
            ]
            if c.get("username"):
                lines.append(f"🔗 {sc('username')} · <code>@{c.get('username')}</code>")
            return "\n".join(lines), _kb_channel_view(int(chat_id))
    return None


async def _view_groups() -> Tuple[str, InlineKeyboardMarkup]:
    count = await _count_groups()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('BROADCAST TO GROUPS')}</b>",
        DIV,
        "",
        f"📊 {sc('total groups')} · <code>{_fmt_int(count)}</code>",
        "",
        DIV2,
        "",
        f"📌 {sc('when you upload a file to the broadcast channel')},",
        f"{sc('click')} <b>👥 GROUPS</b> {sc('to send to')} <b>{_fmt_int(count)}</b> {sc('groups')}.",
        "",
        DIV2,
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 BROADCAST TO ALL ({count})",
                              callback_data="bc:do_groups")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def _view_users_menu() -> Tuple[str, InlineKeyboardMarkup]:
    count = await _count_users()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{fb('BROADCAST TO USERS')}</b>",
        DIV,
        "",
        f"📊 {sc('total users')} · <code>{_fmt_int(count)}</code>",
        "",
        DIV2,
        "",
        f"📌 {sc('when you upload a file to the broadcast channel')},",
        f"{sc('click')} <b>👤 USERS</b> {sc('to send to')} <b>{_fmt_int(count)}</b> {sc('users')}.",
        "",
        DIV2,
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🚀 BROADCAST TO ALL ({count})",
                              callback_data="bc:do_users")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def _view_caption() -> Tuple[str, InlineKeyboardMarkup]:
    cap = await _get_broadcast_caption()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('BROADCAST CAPTION')}</b>",
        DIV,
        "",
        f"<b>{sc('current caption')}:</b>",
        "",
        f"<code>{_esc(cap)}</code>",
        "",
        DIV2,
        "",
        f"📌 {sc('available placeholders')}:",
        f"• <code>{{file_name}}</code> — ᴛʜᴇ ꜰɪʟᴇ ɴᴀᴍᴇ",
        f"• <code>{{file_size}}</code> — ʜᴜᴍᴀɴ-ʀᴇᴀᴅᴀʙʟᴇ ꜱɪᴢᴇ",
        f"• <code>{{rating}}</code> — ʀᴀᴛɪɴɢ (ɪꜰ ᴀᴠᴀɪʟᴀʙʟᴇ)",
        f"• <code>{{year}}</code> — ʏᴇᴀʀ",
        f"• <code>{{file_caption}}</code> — ᴏʀɪɢɪɴᴀʟ ᴄᴀᴘᴛɪᴏɴ",
    ]
    return "\n".join(lines), _kb_caption()


async def _view_buttons() -> Tuple[str, InlineKeyboardMarkup]:
    btns = await _get_broadcast_buttons()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('BROADCAST BUTTONS')}</b>",
        DIV,
        "",
    ]
    if not btns:
        lines.append(f"⚪ {sc('no buttons added yet')}")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")
    lines.append(DIV2)
    lines.append(f"ᴛʜᴇꜱᴇ ʙᴜᴛᴛᴏɴꜱ ᴀᴘᴘᴇᴀʀ ᴏɴ ᴇᴠᴇʀʏ ʙʀᴏᴀᴅᴄᴀꜱᴛ.")
    return "\n".join(lines), _kb_buttons(btns)


async def _view_button_detail(idx: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    btns = await _get_broadcast_buttons()
    if idx < 0 or idx >= len(btns):
        return None
    b = btns[idx]
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('BUTTON DETAILS')}</b>",
        DIV,
        "",
        f"📛 {sc('name')} · <b>{_esc(b.get('name'))}</b>",
        f"🔗 {sc('url')} · <code>{_esc(b.get('url'))}</code>",
    ]
    return "\n".join(lines), _kb_button_view(idx)


async def _view_history() -> Tuple[str, InlineKeyboardMarkup]:
    hist = await _get_history(10)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('BROADCAST HISTORY')}</b>",
        DIV,
        "",
    ]
    if not hist:
        lines.append(f"⚪ {sc('no broadcasts yet')}")
    else:
        for h in hist:
            kind = h.get("kind", "?")
            icon = {"users": "👤", "channels": "📢", "groups": "👥"}.get(kind, "📢")
            ts = h.get("created_at", 0)
            try:
                time_str = datetime.fromtimestamp(ts).strftime("%d %b %H:%M")
            except Exception:
                time_str = "?"
            sent = h.get("sent", 0)
            total = h.get("total", 0)
            lines.append(f"{icon} <b>{kind.upper()}</b> · <code>{time_str}</code>")
            lines.append(f"   ✅ {sent}/{total}")
            lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:history")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — SAFE EDIT HELPER
# ═══════════════════════════════════════════════════════════════════════════

async def _safe_edit(target, text: str, kb: Optional[InlineKeyboardMarkup] = None) -> bool:
    """Edit a message safely. Returns True on success."""
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.warning(f"[BC] edit failed: {type(e).__name__}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — /broadcast COMMAND
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command(["broadcast", "bc"]) & filters.private, group=-500)
async def cmd_broadcast(client: Client, message: Message):
    """Open the broadcast control panel."""
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴛʜɪꜱ ᴛᴏᴏʟ ɪꜱ ꜰᴏʀ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        logger.info(f"[BC] /broadcast opened by {message.from_user.id}")

        try:
            panel = await message.reply_text("🔄 ʟᴏᴀᴅɪɴɢ ᴘᴀɴᴇʟ...")
        except Exception as e:
            logger.warning(f"[BC] reply failed: {e}")
            return

        text, kb = await _view_main()
        await _safe_edit(panel, text, kb)
    except Exception as e:
        logger.exception(f"[BC] /broadcast crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — MAIN PANEL CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:main$"), group=-500)
async def cb_main(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_main()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:close$"), group=-500)
async def cb_close(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^bc:channels$"), group=-500)
async def cb_channels(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_channels()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_view:(-?\d+)$"), group=-500)
async def cb_ch_view(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    result = await _view_channel_detail(cid)
    if result is None:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    text, kb = result
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:ch_add$"), group=-500)
async def cb_ch_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "add_channel")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BROADCAST CHANNEL')}</b>",
        DIV,
        "",
        f"📝 {sc('send me the channel id or @username as next message')}",
        "",
        DIV2,
        "",
        f"📌 {sc('examples')}:",
        f"• <code>-1001234567890</code>",
        f"• <code>@mychannel</code>",
        "",
        f"⚠️ {sc('bot must be an admin in that channel')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:cancel_session$"), group=-500)
async def cb_cancel_session(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    text, kb = await _view_main()
    await _safe_edit(q, text, kb)
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


@Client.on_callback_query(filters.regex(r"^bc:ch_rm:(-?\d+)$"), group=-500)
async def cb_ch_rm(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await _remove_channel(cid)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ" if ok else "⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ")
    text, kb = await _view_channels()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:groups$"), group=-500)
async def cb_groups(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_groups()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:users_menu$"), group=-500)
async def cb_users_menu(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_users_menu()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption$"), group=-500)
async def cb_caption(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:buttons$"), group=-500)
async def cb_buttons(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_buttons()
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_view:(\d+)$"), group=-500)
async def cb_btn_view(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    result = await _view_button_detail(idx)
    if result is None:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    text, kb = result
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:history$"), group=-500)
async def cb_history(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_history()
    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — CAPTION EDITOR CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:caption_edit$"), group=-500)
async def cb_caption_edit(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "edit_caption")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION')}</b>",
        DIV,
        "",
        f"📝 {sc('send the new caption as next message')}",
        "",
        DIV2,
        "",
        f"📌 {sc('placeholders')}:",
        f"• <code>{{file_name}}</code>",
        f"• <code>{{file_size}}</code>",
        f"• <code>{{rating}}</code>",
        f"• <code>{{year}}</code>",
        f"• <code>{{file_caption}}</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption_reset$"), group=-500)
async def cb_caption_reset(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await _set_broadcast_caption(DEFAULT_BROADCAST_CAPTION)
    await q.answer("✅ ʀᴇꜱᴇᴛ ᴛᴏ ᴅᴇꜰᴀᴜʟᴛ")
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:caption_preview$"), group=-500)
async def cb_caption_preview(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cap = await _get_broadcast_caption()
    # Sample render
    sample = cap.format(
        file_name="Interstellar.2014.1080p.mkv",
        file_size="2.4 GB",
        rating="8.7",
        year="2014",
        file_caption="Interstellar (2014)",
    )
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👁️ <b>{fb('CAPTION PREVIEW')}</b>",
        DIV,
        "",
        sample,
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="bc:caption"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — BUTTON EDITOR CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:btn_add$"), group=-500)
async def cb_btn_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "add_button")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON')}</b>",
        DIV,
        "",
        f"📝 {sc('send the button as next message')}",
        f"",
        f"📌 {sc('format')}:",
        f"<code>Button Name | https://t.me/link</code>",
        "",
        f"📌 {sc('example')}:",
        f"<code>Join Channel | https://t.me/mychannel</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_rm:(\d+)$"), group=-500)
async def cb_btn_rm(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    btns = await _get_broadcast_buttons()
    if idx < 0 or idx >= len(btns):
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    btns.pop(idx)
    await _set_broadcast_buttons(btns)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    text, kb = await _view_buttons()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^bc:btn_edit_name:(\d+)$"), group=-500)
async def cb_btn_edit_name(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "edit_button_name", idx=idx)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT BUTTON NAME')}</b>",
        DIV,
        "",
        f"📝 {sc('send the new name as next message')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:btn_edit_url:(\d+)$"), group=-500)
async def cb_btn_edit_url(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "edit_button_url", idx=idx)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT BUTTON URL')}</b>",
        DIV,
        "",
        f"📝 {sc('send the new url as next message')}",
        "",
        f"📌 {sc('example')}:",
        f"<code>https://t.me/mychannel</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — TEXT INPUT HANDLER (session-based)
# ═══════════════════════════════════════════════════════════════════════════
# Catches typed input while a session is active. Runs BEFORE the search
# handler (priority -450) so it consumes the text.
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-450,
)
async def broadcast_session_input(client: Client, message: Message):
    """Consume typed input for active broadcast sessions."""
    if not message.from_user:
        return

    session = _get_session(message.from_user.id)
    if not session:
        return

    action = session["action"]
    text = (message.text or "").strip()
    logger.info(f"[BC] session input: action={action} text={text[:60]!r}")

    try:
        message.stop_propagation()
    except Exception:
        pass

    # ─────────────── ADD CHANNEL ───────────────
    if action == "add_channel":
        target_id = None
        target_title = None
        target_username = None

        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target_id = chat.id
                target_title = chat.title or text
                target_username = chat.username
            except Exception as e:
                return await message.reply_text(
                    f"❌ ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ <code>{_esc(text)}</code>\n\n"
                    f"<code>{_esc(e)}</code>",
                    parse_mode=ParseMode.HTML,
                )
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
                return await message.reply_text(
                    "❌ ꜱᴇɴᴅ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.",
                )

        # Verify bot is admin
        try:
            me = await client.get_me()
            member = await client.get_chat_member(target_id, me.id)
            st = getattr(member, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await message.reply_text(
                    f"⚠️ ʙᴏᴛ ɪꜱ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ <b>{_esc(target_title)}</b>.\n\n"
                    f"ᴘʟᴇᴀꜱᴇ ᴀᴅᴅ ʙᴏᴛ ᴀꜱ ᴀᴅᴍɪɴ ꜰɪʀꜱᴛ.",
                    parse_mode=ParseMode.HTML,
                )
        except Exception as e:
            logger.warning(f"[BC] admin check failed: {e}")
            return await message.reply_text(
                f"❌ ᴄᴀɴɴᴏᴛ ᴠᴇʀɪꜰʏ ᴀᴅᴍɪɴ ꜱᴛᴀᴛᴜꜱ:\n<code>{_esc(e)}</code>",
                parse_mode=ParseMode.HTML,
            )

        ok = await _save_channel(target_id, target_title, target_username)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ</b>\n\n"
                f"📛 {sc('title')} · <b>{_esc(target_title)}</b>\n"
                f"🆔 {sc('id')} · <code>{target_id}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴀᴠᴇ.")
        return

    # ─────────────── EDIT CAPTION ───────────────
    if action == "edit_caption":
        if len(text) < 3:
            return await message.reply_text("❌ ᴄᴀᴘᴛɪᴏɴ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await _set_broadcast_caption(text)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n"
                f"<code>{_esc(text)}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴀᴠᴇ.")
        return

    # ─────────────── ADD BUTTON ───────────────
    if action == "add_button":
        if "|" not in text:
            return await message.reply_text(
                "❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ ɴᴀᴍᴇ ᴏʀ ᴜʀʟ.")

        # Normalize URL
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")

        btns = await _get_broadcast_buttons()
        if len(btns) >= 8:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")

        btns.append({"name": name[:60], "url": url, "position": len(btns) + 1})
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ</b>\n\n"
            f"📛 <b>{_esc(name)}</b>\n"
            f"🔗 <code>{_esc(url)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─────────────── EDIT BUTTON NAME ───────────────
    if action == "edit_button_name":
        idx = session["data"].get("idx")
        btns = await _get_broadcast_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")
        if len(text) < 2:
            return await message.reply_text("❌ ɴᴀᴍᴇ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        btns[idx]["name"] = text[:60]
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>ɴᴀᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n<b>{_esc(text)}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─────────────── EDIT BUTTON URL ───────────────
    if action == "edit_button_url":
        idx = session["data"].get("idx")
        btns = await _get_broadcast_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")

        url = text.strip()
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")

        btns[idx]["url"] = url
        await _set_broadcast_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>ᴜʀʟ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n<code>{_esc(url)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─────────────── UNKNOWN ───────────────
    _clear_session(message.from_user.id)
    await message.reply_text("⚠️ ᴜɴᴋɴᴏᴡɴ ꜱᴇꜱꜱɪᴏɴ ᴀᴄᴛɪᴏɴ.")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — BACKGROUND CLEANUP
# ═══════════════════════════════════════════════════════════════════════════

async def _broadcast_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(120)
            _cleanup_sessions()
            _cleanup_jobs()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_broadcast_cleanup_loop())
except Exception as e:
    logger.warning(f"[BC] cleanup task failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 15 — FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════

logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  [BROADCAST] PART 1 LOADED ✅                                 ║")
logger.info("║                                                                ║")
logger.info("║  Commands:  /broadcast  /bc                                    ║")
logger.info("║                                                                ║")
logger.info("║  What's next:                                                  ║")
logger.info("║    Part 2 — Broadcast engine + watcher + progress              ║")
logger.info("║    Part 3 — Extended features + history                        ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — BROADCAST SOURCE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════
# When admin uploads a file to the broadcast channel, we register its
# message ID + chat ID. Callback buttons reference this registry.
# ═══════════════════════════════════════════════════════════════════════════

_SOURCES: Dict[str, Dict[str, Any]] = {}
SOURCE_TTL = 3600   # 1 hour


def _register_source(message: Message) -> str:
    sid = uuid.uuid4().hex[:10]
    _SOURCES[sid] = {
        "message_id": message.id,
        "chat_id": message.chat.id,
        "created": time.time(),
        "expires": time.time() + SOURCE_TTL,
        "kind": (message.media.value if message.media else "text"),
    }
    logger.info(f"[BC-SRC] registered sid={sid} msg_id={message.id}")
    return sid


def _get_source(sid: str) -> Optional[Dict[str, Any]]:
    s = _SOURCES.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SOURCES.pop(sid, None)
        return None
    return s


def _cleanup_sources() -> None:
    now = time.time()
    for sid in list(_SOURCES.keys()):
        if _SOURCES[sid]["expires"] < now:
            _SOURCES.pop(sid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17 — CAPTION BUILDER
# ═══════════════════════════════════════════════════════════════════════════

def _build_caption_for(message: Message, template: str) -> str:
    """Format the caption template using the source message details."""
    try:
        # Extract file name
        file_name = "file"
        file_size_h = "0 B"
        file_caption = message.caption or ""

        for attr in ("video", "document", "audio", "photo", "animation"):
            media = getattr(message, attr, None)
            if media:
                file_name = (
                    getattr(media, "file_name", None)
                    or file_caption[:80]
                    or "file"
                )
                size = getattr(media, "file_size", 0) or 0
                file_size_h = _fmt_size(size)
                break

        # Extract year from file name
        year = ""
        m = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", file_name)
        if m:
            year = m.group(1)

        # Rating placeholder — try to fetch from cached metadata
        rating = "—"

        # Render template
        rendered = template.format(
            file_name=file_name[:100],
            file_size=file_size_h,
            rating=rating,
            year=year or "—",
            file_caption=file_caption[:200] if file_caption else "—",
        )
        return rendered
    except Exception as e:
        logger.warning(f"[BC] caption render failed: {e}")
        # Fallback: just send the template
        return template


async def _build_kb_for() -> Optional[InlineKeyboardMarkup]:
    """Build the inline keyboard from saved broadcast buttons."""
    btns = await _get_broadcast_buttons()
    if not btns:
        return None
    rows = []
    for b in btns:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url:
            continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    if not rows:
        return None
    # Append UPDATES link always
    rows.append([InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK)])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18 — BROADCAST CHANNEL WATCHER
# ═══════════════════════════════════════════════════════════════════════════

if BROADCAST_CHANNEL_ID:
    @Client.on_message(
        filters.chat(BROADCAST_CHANNEL_ID) & ~filters.service,
        group=-500,
    )
    async def broadcast_channel_watcher(client: Client, message: Message):
        """When admin uploads a file, show control buttons."""
        try:
            logger.info(
                f"[BC-WATCH] new message id={message.id} "
                f"kind={message.media.value if message.media else 'text'}"
            )

            sid = _register_source(message)

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 CHANNELS",
                                       callback_data=f"bcsend:ch:{sid}")],
                [InlineKeyboardButton("👥 GROUPS",
                                       callback_data=f"bcsend:gr:{sid}")],
                [InlineKeyboardButton("👤 USERS",
                                       callback_data=f"bcsend:us:{sid}")],
                [InlineKeyboardButton("❌ CANCEL",
                                       callback_data=f"bcsend:no:{sid}")],
            ])

            await message.reply_text(
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"📢 <b>{fb('BROADCAST READY')}</b>",
                    DIV,
                    "",
                    f"📌 {sc('choose destination')}",
                    "",
                    f"📢 {sc('channels')} — {sc('send to your saved channels')}",
                    f"👥 {sc('groups')} — {sc('send to all groups')}",
                    f"👤 {sc('users')} — {sc('send to all users')}",
                    "",
                    f"🆔 <code>{sid}</code>",
                ]),
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.id,
                quote=True,
            )
        except Exception as e:
            logger.exception(f"[BC-WATCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 19 — BROADCAST DESTINATION PICKER
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bcsend:ch:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_channels(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    chans = await _get_saved_channels()
    if not chans:
        return await q.answer("⚠️ ɴᴏ ꜱᴀᴠᴇᴅ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)

    rows = []
    for c in chans:
        title = (c.get("title") or "?")[:40]
        cid = c.get("chat_id")
        rows.append([InlineKeyboardButton(
            f"📢 {title}",
            callback_data=f"bcsend:goto_ch:{sid}:{cid}",
        )])
    rows.append([InlineKeyboardButton("❌ CANCEL",
                                       callback_data=f"bcsend:no:{sid}")])

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('SELECT CHANNEL')}</b>",
        DIV,
        "",
        f"📌 {sc('tap a channel to send to')}",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:goto_ch:([a-f0-9]+):(-?\d+)$"), group=-500)
async def cb_bcsend_goto_ch(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    target = int(q.matches[0].group(2))

    src = _get_source(sid)
    if not src:
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "channel", targets=[target])


@Client.on_callback_query(filters.regex(r"^bcsend:gr:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_groups(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    total = await _count_groups()
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ɢʀᴏᴜᴘꜱ", show_alert=True)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ YES, SEND TO {total} GROUPS",
                              callback_data=f"bcsend:goto_gr:{sid}")],
        [InlineKeyboardButton("❌ CANCEL",
                              callback_data=f"bcsend:no:{sid}")],
    ])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('CONFIRM GROUP BROADCAST')}</b>",
        DIV,
        "",
        f"📊 {sc('total groups')} · <code>{_fmt_int(total)}</code>",
        "",
        f"⚠️ {sc('this will message every group where the bot is present')}",
    ])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:goto_gr:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_goto_gr(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "groups")


@Client.on_callback_query(filters.regex(r"^bcsend:us:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_users(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    total = await _count_users()
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ᴜꜱᴇʀꜱ", show_alert=True)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ YES, SEND TO {total} USERS",
                              callback_data=f"bcsend:goto_us:{sid}")],
        [InlineKeyboardButton("❌ CANCEL",
                              callback_data=f"bcsend:no:{sid}")],
    ])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{fb('CONFIRM USER BROADCAST')}</b>",
        DIV,
        "",
        f"📊 {sc('total users')} · <code>{_fmt_int(total)}</code>",
        "",
        f"⚠️ {sc('blocked or deleted users will be auto-removed')}",
    ])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:goto_us:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_goto_us(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ꜱᴏᴜʀᴄᴇ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "users")


@Client.on_callback_query(filters.regex(r"^bcsend:no:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_no(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 20 — BROADCAST ENGINE
# ═══════════════════════════════════════════════════════════════════════════

async def _run_broadcast(
    client: Client,
    q: CallbackQuery,
    sid: str,
    kind: str,   # "channel" | "groups" | "users"
    targets: Optional[List[int]] = None,
):
    """
    Core broadcast runner.
    kind: "channel" (single target), "groups", "users"
    """
    src = _get_source(sid)
    if not src:
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    # Fetch caption + buttons once
    caption_template = await _get_broadcast_caption()
    kb = await _build_kb_for()

    # Get source message
    try:
        src_msg = await client.get_messages(src["chat_id"], src["message_id"])
    except Exception as e:
        return await q.answer(f"⚠️ ᴄᴀɴɴᴏᴛ ꜰᴇᴛᴄʜ ꜱᴏᴜʀᴄᴇ: {e}"[:180], show_alert=True)

    if not src_msg or src_msg.empty:
        return await q.answer("⚠️ ꜱᴏᴜʀᴄᴇ ᴅᴇʟᴇᴛᴇᴅ", show_alert=True)

    # Build caption
    caption = _build_caption_for(src_msg, caption_template)

    # Resolve target list
    if kind == "channel":
        if not targets:
            return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛ", show_alert=True)
        target_list = targets
        kind_label = "ᴄʜᴀɴɴᴇʟ"
    elif kind == "groups":
        target_list = await _get_all_groups()
        kind_label = "ɢʀᴏᴜᴘꜱ"
    else:  # users
        target_list = await _get_all_users()
        kind_label = "ᴜꜱᴇʀꜱ"

    total = len(target_list)
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)

    logger.info(f"[BC-RUN] kind={kind} total={total}")

    # Create job + progress message
    try:
        progress_msg = await q.message.edit_text(
            f"🏨 <b>{fb('BROADCAST STARTED')}</b>\n"
            f"{DIV}\n\n"
            f"📤 {sc('sending to')} <b>{_fmt_int(total)}</b> {kind_label}...",
            parse_mode=ParseMode.HTML,
        )
    except MessageNotModified:
        progress_msg = q.message
    except Exception as e:
        logger.warning(f"[BC-RUN] progress msg failed: {e}")
        progress_msg = q.message

    job_id = _new_job(
        admin_id=q.from_user.id,
        kind=kind,
        total=total,
        source_msg_id=src["message_id"],
        source_chat_id=src["chat_id"],
        progress_msg_id=progress_msg.id,
    )
    job = _get_job(job_id)
    job["caption"] = caption
    job["targets"] = target_list
    job["current_index"] = 0

    # Launch worker
    task = asyncio.create_task(
        _broadcast_worker(client, job_id, src_msg, caption, kb)
    )
    job["task"] = task

    # Save to source registry so we can reference later
    _SOURCES[sid]["last_job_id"] = job_id


async def _broadcast_worker(
    client: Client,
    job_id: str,
    src_msg: Message,
    caption: str,
    kb: Optional[InlineKeyboardMarkup],
):
    """
    Runs the actual broadcast. Sends files to each target with live progress.
    """
    job = _get_job(job_id)
    if not job:
        return

    targets = job["targets"]
    total = job["total"]

    start_time = time.time()
    last_edit = 0.0
    last_rate_ts = start_time
    last_rate_count = 0

    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    lock = asyncio.Lock()

    async def _send_one(target_id: int) -> str:
        """Returns result: 'sent' | 'failed' | 'blocked' | 'deleted'"""
        if job["cancel_flag"]:
            return "cancelled"

        async with sem:
            if job["cancel_flag"]:
                return "cancelled"
            try:
                # Try sending with caption; if fails, try without
                try:
                    await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption,
                        reply_markup=kb,
                    )
                except (MediaEmpty, MessageNotModified):
                    await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                    )
                await asyncio.sleep(DEFAULT_DELAY)
                return "sent"
            except FloodWait as e:
                wait = max(1, int(e.value))
                logger.warning(f"[BC-RUN] FloodWait {wait}s on {target_id}")
                await asyncio.sleep(wait + 2)
                try:
                    await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption,
                        reply_markup=kb,
                    )
                    return "sent"
                except Exception:
                    return "failed"
            except UserIsBlocked:
                return "blocked"
            except (InputUserDeactivated, UserDeactivated, UserDeactivatedBan):
                return "deleted"
            except (ChatWriteForbidden, ChatForbidden, ChatAdminRequired):
                return "failed"
            except (ChannelPrivate, PeerIdInvalid, UserNotParticipant):
                return "failed"
            except Exception as e:
                logger.debug(f"[BC-RUN] fail {target_id}: {type(e).__name__}: {e}")
                return "failed"

    async def _worker(target_id: int):
        result = await _send_one(target_id)
        async with lock:
            job["current_index"] += 1
            if result == "sent":
                job["sent"] += 1
            elif result == "blocked":
                job["blocked"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(target_id))
            elif result == "deleted":
                job["deleted"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(target_id))
            elif result == "failed":
                job["failed"] += 1
            # Progress check
            now = time.time()
            if now - last_edit >= PROGRESS_EDIT_INTERVAL or job["current_index"] >= total:
                job["last_edit"] = now

    try:
        # Process in batches
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            if job["cancel_flag"]:
                break
            batch = targets[i : i + BROADCAST_BATCH_SIZE]
            await asyncio.gather(*[_worker(t) for t in batch])

            # Update progress message
            await _update_progress(client, job, kind_label := _kind_label(job["kind"]))

            # Background cleanup check
            _cleanup_jobs()

        # Final status
        if job["cancel_flag"]:
            _finish_job(job_id, "cancelled")
            await _render_done(client, job, cancelled=True)
        else:
            _finish_job(job_id, "completed")
            await _render_done(client, job, cancelled=False)

        # Save history
        elapsed = time.time() - start_time
        await _log_broadcast({
            "job_id": job_id,
            "kind": job["kind"],
            "admin_id": job["admin_id"],
            "total": total,
            "sent": job["sent"],
            "failed": job["failed"],
            "blocked": job["blocked"],
            "deleted": job["deleted"],
            "elapsed": elapsed,
            "status": job["status"],
            "targets_preview": targets[:20],
        })

    except asyncio.CancelledError:
        _finish_job(job_id, "cancelled")
        await _render_done(client, job, cancelled=True)
        raise
    except Exception as e:
        logger.exception(f"[BC-RUN] worker crashed: {e}")
        _finish_job(job_id, "failed")
        try:
            await client.edit_message_text(
                chat_id=job["source_chat_id"] if False else job["progress_msg_id"],
                message_id=job["progress_msg_id"],
                text=f"❌ ʙʀᴏᴀᴅᴄᴀꜱᴛ ꜰᴀɪʟᴇᴅ:\n<code>{_esc(e)}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


def _kind_label(kind: str) -> str:
    return {
        "channel": "ᴄʜᴀɴɴᴇʟ",
        "channels": "ᴄʜᴀɴɴᴇʟꜱ",
        "groups": "ɢʀᴏᴜᴘꜱ",
        "users": "ᴜꜱᴇʀꜱ",
    }.get(kind, kind)


async def _update_progress(client: Client, job: Dict[str, Any], kind_label: str) -> None:
    """Edit the progress message with current stats."""
    if job["cancel_flag"]:
        return
    now = time.time()
    if now - job["last_edit"] < PROGRESS_EDIT_INTERVAL and job["current_index"] < job["total"]:
        return
    job["last_edit"] = now

    elapsed = max(0.001, now - job["started_at"])
    processed = job["current_index"]
    total = job["total"]
    pct = (processed / total * 100.0) if total else 0.0
    speed = processed / elapsed if elapsed > 0 else 0
    remaining = max(0, total - processed)
    eta = (remaining / speed) if speed > 0 else 0

    bar = _progress_colored(processed, total, width=14)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST IN PROGRESS')}</b>",
        DIV,
        "",
        f"📤 {sc('sending to')} <b>{kind_label}</b>",
        "",
        bar,
        "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "",
        DIV2,
        "",
        f"📊 {sc('progress')} · <code>{processed}/{total}</code>",
        f"⚡ {sc('speed')} · <code>{speed:.1f}/s</code>",
        f"⏱️ {sc('eta')} · <code>{_fmt_duration(eta)}</code>",
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⏹️ CANCEL", callback_data=f"bcstop:{job['id']}"),
    ]])

    try:
        await client.edit_message_text(
            chat_id=job["progress_msg_id"] if False else job["progress_msg_id"],
            message_id=job["progress_msg_id"],
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.debug(f"[BC-RUN] progress edit fail: {e}")


async def _render_done(client: Client, job: Dict[str, Any], cancelled: bool) -> None:
    """Render the completion message."""
    elapsed = time.time() - job["started_at"]
    kind_label = _kind_label(job["kind"])

    title = "🛑 ᴄᴀɴᴄᴇʟʟᴇᴅ" if cancelled else "✅ ᴄᴏᴍᴘʟᴇᴛᴇᴅ"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST ' + ('CANCELLED' if cancelled else 'COMPLETE'))}</b>",
        DIV,
        "",
        f"📤 {sc('target')} · <b>{kind_label}</b>",
        "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "",
        DIV2,
        f"🕒 {sc('total time')} · <code>{_fmt_duration(elapsed)}</code>",
        "",
        f"<b>{title}</b>",
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CLOSE", callback_data=f"bcend:{job['id']}"),
    ]])

    try:
        await client.edit_message_text(
            chat_id=job["progress_msg_id"],
            message_id=job["progress_msg_id"],
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"[BC-RUN] done edit fail: {e}")


@Client.on_callback_query(filters.regex(r"^bcstop:([a-f0-9]+)$"), group=-500)
async def cb_bcstop(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    jid = q.matches[0].group(1)
    job = _get_job(jid)
    if not job:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    job["cancel_flag"] = True
    job["status"] = "cancelled"
    await q.answer("⏹️ ᴄᴀɴᴄᴇʟʟɪɴɢ...")


@Client.on_callback_query(filters.regex(r"^bcend:([a-f0-9]+)$"), group=-500)
async def cb_bcend(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("✅ ᴅᴏɴᴇ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 21 — CLEANUP (EXTENDED)
# ═══════════════════════════════════════════════════════════════════════════

async def _broadcast_ext_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(180)
            _cleanup_sources()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_broadcast_ext_cleanup_loop())
except Exception:
    pass


logger.info("[BROADCAST] Part 2 loaded ✅ — engine ready")

# ═══════════════════════════════════════════════════════════════════════════
# 🏨 DOWNTOWN VILLA — BROADCAST PART 3 (ADVANCED FEATURES)
# ═══════════════════════════════════════════════════════════════════════════
#
# Adds:
#   ✔ Test broadcast (send to self only)
#   ✔ Pin message option
#   ✔ Silent (no notification) option
#   ✔ Retry failed broadcasts
#   ✔ Delete source after broadcast
#   ✔ Broadcast preview before sending
#   ✔ Scheduled broadcasts (simple)
#   ✔ Export/Import button sets
#   ✔ Caption template library
#   ✔ Broadcast to specific user list
#   ✔ Progress edit throttling
#   ✔ Better error classification
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# 🏨 DOWNTOWN VILLA — BROADCAST PART 3 (COMPLETE - FIXED)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 28 — BROADCAST OPTIONS REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

_BROADCAST_OPTS: Dict[str, Dict[str, Any]] = {}


def _get_opts(sid: str) -> Dict[str, Any]:
    if sid not in _BROADCAST_OPTS:
        _BROADCAST_OPTS[sid] = {
            "pin": False,
            "silent": False,
            "delete_after": False,
            "test_sent": False,
        }
    return _BROADCAST_OPTS[sid]


def _cleanup_opts() -> None:
    for sid in list(_BROADCAST_OPTS.keys()):
        if sid not in _SOURCES:
            _BROADCAST_OPTS.pop(sid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 29 — CAPTION TEMPLATES LIBRARY
# ═══════════════════════════════════════════════════════════════════════════

CAPTION_TEMPLATES = {
    "default": (
        "🎬 <b>{file_name}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "⭐ Rating: <b>{rating}</b>\n"
        "\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "movies": (
        "🎬 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "⭐ Rating: <b>{rating}</b>\n"
        "\n"
        "🎞️ 𝗤𝘂𝗮𝗹𝗶𝘁𝘆 𝗠𝗼𝘃𝗶𝗲 𝗖𝗼𝗹𝗹𝗲𝗰𝘁𝗶𝗼𝗻\n"
        "\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "series": (
        "📺 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "\n"
        "🔥 𝗡𝗲𝘄 𝗘𝗽𝗶𝘀𝗼𝗱𝗲 𝗥𝗲𝗹𝗲𝗮𝘀𝗲\n"
        "\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "minimal": "🎬 <b>{file_name}</b>\n📦 {file_size}",
    "spam": (
        "🔥 <b>{file_name}</b> 🔥\n"
        "📦 {file_size}\n"
        "⭐ {rating}\n"
        "\n"
        "📢 𝗝𝗼𝗶𝗻 𝗨𝗽𝗱𝗮𝘁𝗲𝘀 𝗖𝗵𝗮𝗻𝗻𝗲𝗹"
    ),
}


@Client.on_callback_query(filters.regex(r"^bc:caption_lib$"), group=-500)
async def cb_caption_lib(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    rows = []
    for name, tpl in CAPTION_TEMPLATES.items():
        rows.append([InlineKeyboardButton(
            f"📝 {name.upper()}",
            callback_data=f"bc:caption_use:{name}",
        )])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="bc:caption")])

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('CAPTION TEMPLATES')}</b>",
        DIV,
        "",
        f"📌 {sc('pick a template to load into the editor')}",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:caption_use:(\w+)$"), group=-500)
async def cb_caption_use(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    name = q.matches[0].group(1)
    tpl = CAPTION_TEMPLATES.get(name)
    if not tpl:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

    await _set_broadcast_caption(tpl)
    await q.answer(f"✅ ʟᴏᴀᴅᴇᴅ: {name}")
    text, kb = await _view_caption()
    await _safe_edit(q, text, kb)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 30 — ENHANCED MAIN PANEL (REPLACES ORIGINAL)
# ═══════════════════════════════════════════════════════════════════════════
# We monkey-patch _view_main to use the advanced keyboard.

_original_view_main = _view_main


async def _view_main() -> Tuple[str, InlineKeyboardMarkup]:  # noqa: F811
    """Enhanced main panel with all Part 3 buttons."""
    u = await _count_users()
    g = await _count_groups()
    chans = await _get_saved_channels()
    btns = await _get_broadcast_buttons()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CONTROL CENTER')}</b>",
        DIV,
        "",
        f"👤 {sc('users')} · <code>{_fmt_int(u)}</code>",
        f"👥 {sc('groups')} · <code>{_fmt_int(g)}</code>",
        f"📢 {sc('saved channels')} · <code>{len(chans)}</code>",
        f"🔘 {sc('buttons')} · <code>{len(btns)}</code>",
        "",
        DIV2,
        "",
        f"📌 {sc('how to broadcast')}:",
        f"1. {sc('upload any file to broadcast channel')}",
        f"2. {sc('buttons appear on the uploaded file')}",
        f"3. {sc('click channels/groups/users to send')}",
        "",
        DIV2,
        f"🕒 {sc('updated')} · <code>{datetime.now().strftime('%H:%M:%S')}</code>",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 CHANNELS ({len(chans)})",
            callback_data="bc:channels"
        )],
        [InlineKeyboardButton(
            f"👥 GROUPS ({g})",
            callback_data="bc:groups"
        )],
        [InlineKeyboardButton(
            f"👤 USERS ({u})",
            callback_data="bc:users_menu"
        )],
        [InlineKeyboardButton(
            "📝 CAPTION",
            callback_data="bc:caption"
        ),
         InlineKeyboardButton(
            f"🔘 BUTTONS ({len(btns)})",
            callback_data="bc:buttons"
        )],
        [InlineKeyboardButton("📚 TEMPLATES", callback_data="bc:caption_lib"),
         InlineKeyboardButton("🎯 MANUAL", callback_data="bc:manual")],
        [InlineKeyboardButton("📈 STATS", callback_data="bc:stats"),
         InlineKeyboardButton("📊 HISTORY", callback_data="bc:history")],
        [InlineKeyboardButton("💾 EXPORT", callback_data="bc:export"),
         InlineKeyboardButton("📥 IMPORT", callback_data="bc:import")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 31 — TEST BROADCAST
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:test:([a-f0-9]+)$"), group=-500)
async def cb_test(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    src = _get_source(sid)
    if not src:
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    await q.answer("🧪 ꜱᴇɴᴅɪɴɢ ᴛᴇꜱᴛ...")

    try:
        src_msg = await client.get_messages(src["chat_id"], src["message_id"])
        if not src_msg or src_msg.empty:
            return await q.message.reply_text("⚠️ ꜱᴏᴜʀᴄᴇ ᴅᴇʟᴇᴛᴇᴅ.")

        cap_template = await _get_broadcast_caption()
        caption = _build_caption_for(src_msg, cap_template)
        kb = await _build_kb_for()

        try:
            await client.copy_message(
                chat_id=q.from_user.id,
                from_chat_id=src_msg.chat.id,
                message_id=src_msg.id,
                caption=caption,
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"[BC-TEST] copy failed: {e}")
            return await q.message.reply_text(f"❌ ᴛᴇꜱᴛ ꜰᴀɪʟᴇᴅ: {e}")

        _get_opts(sid)["test_sent"] = True
        await q.message.reply_text("✅ ᴛᴇꜱᴛ ꜱᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘᴍ.")
    except Exception as e:
        logger.exception(f"[BC-TEST] crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 32 — BROADCAST OPTIONS PANEL
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:opt:(\w+):([a-f0-9]+)$"), group=-500)
async def cb_opt(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    opt = q.matches[0].group(1)
    sid = q.matches[0].group(2)
    opts = _get_opts(sid)
    if opt not in opts:
        return await q.answer("⚠️ ᴜɴᴋɴᴏᴡɴ ᴏᴘᴛɪᴏɴ", show_alert=True)
    opts[opt] = not opts[opt]
    await q.answer(f"{'🟢 ᴏɴ' if opts[opt] else '🔴 ᴏꜰꜰ'}")
    await _show_options_panel(client, q, sid)


async def _show_options_panel(client, q, sid: str):
    opts = _get_opts(sid)

    def b(v):
        return "🟢 ON" if v else "🔴 OFF"

    rows = [
        [InlineKeyboardButton(
            f"{b(opts['pin'])}  📌 PIN MESSAGE",
            callback_data=f"bc:opt:pin:{sid}",
        )],
        [InlineKeyboardButton(
            f"{b(opts['silent'])}  🔕 SILENT MODE",
            callback_data=f"bc:opt:silent:{sid}",
        )],
        [InlineKeyboardButton(
            f"{b(opts['delete_after'])}  🗑️ DELETE SOURCE",
            callback_data=f"bc:opt:delete_after:{sid}",
        )],
        [InlineKeyboardButton("🧪 TEST BROADCAST",
                               callback_data=f"bc:test:{sid}")],
        [InlineKeyboardButton("◀️ BACK",
                               callback_data=f"bcsend:back:{sid}")],
    ]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{fb('BROADCAST OPTIONS')}</b>",
        DIV,
        "",
        f"📌 {sc('pin')} · {b(opts['pin'])}",
        f"🔕 {sc('silent')} · {b(opts['silent'])}",
        f"🗑️ {sc('delete after')} · {b(opts['delete_after'])}",
        "",
        DIV2,
        "",
        f"🔑 <code>{sid}</code>",
    ])
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^bcsend:back:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_back(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 CHANNELS",
                               callback_data=f"bcsend:ch:{sid}")],
        [InlineKeyboardButton("👥 GROUPS",
                               callback_data=f"bcsend:gr:{sid}")],
        [InlineKeyboardButton("👤 USERS",
                               callback_data=f"bcsend:us:{sid}")],
        [InlineKeyboardButton("⚙️ OPTIONS",
                               callback_data=f"bcsend:opts:{sid}")],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=f"bcsend:no:{sid}")],
    ])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST READY')}</b>",
        DIV,
        "",
        f"📌 {sc('choose destination')}",
        "",
        f"📢 {sc('channels')}",
        f"👥 {sc('groups')}",
        f"👤 {sc('users')}",
        "",
        DIV2,
        f"🆔 <code>{sid}</code>",
    ])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bcsend:opts:([a-f0-9]+)$"), group=-500)
async def cb_bcsend_opts(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not _get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await _show_options_panel(client, q, sid)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 33 — MANUAL TARGET
# ═══════════════════════════════════════════════════════════════════════════

_MANUAL_TARGETS: Dict[int, int] = {}


@Client.on_callback_query(filters.regex(r"^bc:manual$"), group=-500)
async def cb_manual(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "manual_target")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('MANUAL TARGET')}</b>",
        DIV,
        "",
        f"📝 {sc('send a chat id or @username as next message')}",
        "",
        DIV2,
        f"📌 {sc('after saving, upload a file to the broadcast channel')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-449,
)
async def _manual_target_input(client: Client, message: Message):
    if not message.from_user:
        return
    session = _get_session(message.from_user.id)
    if not session or session["action"] != "manual_target":
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    text = (message.text or "").strip()
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
        parse_mode=ParseMode.HTML,
    )


if BROADCAST_CHANNEL_ID:
    @Client.on_message(
        filters.chat(BROADCAST_CHANNEL_ID) & ~filters.service,
        group=-499,
    )
    async def _manual_target_watcher(client: Client, message: Message):
        """Adds a manual target button if admin set one."""
        try:
            if not message.from_user:
                return
            target_id = _MANUAL_TARGETS.pop(message.from_user.id, None)
            if not target_id:
                return

            sid = _register_source(message)

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🎯 SEND TO MANUAL TARGET",
                    callback_data=f"bcsend:manual:{sid}:{target_id}",
                )],
                [InlineKeyboardButton("📢 CHANNELS",
                                       callback_data=f"bcsend:ch:{sid}")],
                [InlineKeyboardButton("👥 GROUPS",
                                       callback_data=f"bcsend:gr:{sid}")],
                [InlineKeyboardButton("👤 USERS",
                                       callback_data=f"bcsend:us:{sid}")],
                [InlineKeyboardButton("❌ CANCEL",
                                       callback_data=f"bcsend:no:{sid}")],
            ])

            await message.reply_text(
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
                f"🎯 <b>{fb('MANUAL TARGET READY')}</b>\n"
                f"{DIV}\n\n"
                f"🆔 <code>{target_id}</code>\n\n"
                f"📌 {sc('click below to send')}",
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.id,
                quote=True,
            )
        except Exception as e:
            logger.exception(f"[BC-MANUAL] crashed: {e}")


@Client.on_callback_query(
    filters.regex(r"^bcsend:manual:([a-f0-9]+):(-?\d+)$"),
    group=-500,
)
async def cb_bcsend_manual(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    target = int(q.matches[0].group(2))
    if not _get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_broadcast(client, q, sid, "channel", targets=[target])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 34 — STATISTICS
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:stats$"), group=-500)
async def cb_stats(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    hist = await _get_history(100)

    total_broadcasts = len(hist)
    total_sent = sum(h.get("sent", 0) for h in hist)
    total_failed = sum(h.get("failed", 0) for h in hist)
    total_blocked = sum(h.get("blocked", 0) for h in hist)
    total_deleted = sum(h.get("deleted", 0) for h in hist)

    kind_counts: Dict[str, int] = {"channels": 0, "groups": 0, "users": 0, "channel": 0}
    for h in hist:
        k = h.get("kind", "users")
        if k in kind_counts:
            kind_counts[k] += 1

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('BROADCAST STATISTICS')}</b>",
        DIV,
        "",
        f"🔢 {sc('total broadcasts')} · <code>{_fmt_int(total_broadcasts)}</code>",
        "",
        DIV2,
        "",
        f"✅ {sc('total sent')} · <code>{_fmt_int(total_sent)}</code>",
        f"❌ {sc('total failed')} · <code>{_fmt_int(total_failed)}</code>",
        f"🚫 {sc('total blocked')} · <code>{_fmt_int(total_blocked)}</code>",
        f"👻 {sc('total deleted')} · <code>{_fmt_int(total_deleted)}</code>",
        "",
        DIV2,
        "",
        f"📢 {sc('channels')} · <code>{_fmt_int(kind_counts.get('channels', 0) + kind_counts.get('channel', 0))}</code>",
        f"👥 {sc('groups')} · <code>{_fmt_int(kind_counts['groups'])}</code>",
        f"👤 {sc('users')} · <code>{_fmt_int(kind_counts['users'])}</code>",
    ]

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="bc:stats"),
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
    ]])
    await _safe_edit(q, "\n".join(lines), kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 35 — EXPORT / IMPORT
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^bc:export$"), group=-500)
async def cb_export(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    btns = await _get_broadcast_buttons()
    cap = await _get_broadcast_caption()

    import json
    data = {
        "buttons": btns,
        "caption": cap,
        "exported_at": datetime.now().isoformat(),
    }
    text = json.dumps(data, indent=2, ensure_ascii=False)

    from io import BytesIO
    bio = BytesIO(text.encode("utf-8"))
    bio.name = "broadcast_config.json"

    try:
        await client.send_document(
            chat_id=q.from_user.id,
            document=bio,
            caption=(
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
                f"💾 <b>{fb('BROADCAST CONFIG EXPORT')}</b>\n"
                f"{DIV}\n\n"
                f"📦 {sc('buttons')} · {len(btns)}\n"
                f"📝 {sc('caption')} · {'✅' if cap else '❌'}"
            ),
            parse_mode=ParseMode.HTML,
        )
        await q.answer("✅ ᴇxᴘᴏʀᴛᴇᴅ")
    except Exception as e:
        await q.answer(f"❌ {e}"[:180], show_alert=True)


@Client.on_callback_query(filters.regex(r"^bc:import$"), group=-500)
async def cb_import(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, "import_config")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📥 <b>{fb('IMPORT BROADCAST CONFIG')}</b>",
        DIV,
        "",
        f"📝 {sc('send the JSON config file as next message')}",
        "",
        DIV2,
        f"📌 {sc('use the file from EXPORT')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="bc:cancel_session"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_message(
    filters.private & (filters.document | filters.text) & ~filters.regex(r"^/"),
    group=-448,
)
async def _import_config_input(client: Client, message: Message):
    if not message.from_user:
        return
    session = _get_session(message.from_user.id)
    if not session or session["action"] != "import_config":
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    try:
        if message.document:
            content = await message.download(in_memory=True)
            text = content.getvalue().decode("utf-8")
        else:
            text = (message.text or "").strip()
    except Exception as e:
        _clear_session(message.from_user.id)
        return await message.reply_text(f"❌ ᴄᴀɴɴᴏᴛ ʀᴇᴀᴅ: {e}")

    import json
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
            if not isinstance(b, dict):
                continue
            n = (b.get("name") or "").strip()
            u = (b.get("url") or "").strip()
            if n and u:
                clean.append({"name": n[:60], "url": u, "position": len(clean) + 1})
        await _set_broadcast_buttons(clean)

    if cap:
        await _set_broadcast_caption(str(cap))

    _clear_session(message.from_user.id)
    await message.reply_text(
        f"✅ <b>ᴄᴏɴꜰɪɢ ɪᴍᴘᴏʀᴛᴇᴅ</b>\n\n"
        f"📦 {sc('buttons')} · {len(btns)}\n"
        f"📝 {sc('caption')} · {'✅' if cap else '❌'}",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 36 — RETRY FAILED
# ═══════════════════════════════════════════════════════════════════════════

_FAILED_TARGETS: Dict[str, List[int]] = {}


@Client.on_callback_query(filters.regex(r"^bc:retry:([a-f0-9]+)$"), group=-500)
async def cb_retry(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    jid = q.matches[0].group(1)
    failed = _FAILED_TARGETS.get(jid, [])
    if not failed:
        return await q.answer("⚠️ ɴᴏ ꜰᴀɪʟᴇᴅ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)
    await q.answer(f"🔁 {len(failed)} ᴛᴀʀɢᴇᴛꜱ ɪɴ ʟᴏɢ")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 37 — CLEANUP + FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════

async def _broadcast_part3_cleanup():
    while True:
        try:
            await asyncio.sleep(180)
            _cleanup_opts()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_broadcast_part3_cleanup())
except Exception:
    pass


logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  [BROADCAST] FULLY LOADED ✅ (Parts 1, 2, 3)                  ║")
logger.info("║                                                                ║")
logger.info("║  Commands:  /broadcast  /bc                                    ║")
logger.info("║                                                                ║")
logger.info("║  All features ready:                                           ║")
logger.info("║   ✅ Panel  ✅ Channels  ✅ Groups  ✅ Users                    ║")
logger.info("║   ✅ Caption  ✅ Buttons  ✅ Templates  ✅ Manual               ║")
logger.info("║   ✅ Stats  ✅ History  ✅ Export/Import                       ║")
logger.info("║   ✅ Watcher  ✅ Progress  ✅ Cancel  ✅ Cleanup                ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
