# plugins/indexing.py
"""
📚 DOWNTOWN VILLA — ULTIMATE FILE INDEXING CENTER
Manual backward indexing + automatic live indexing.
Movies + Series. Metadata-first, no downloads.
"""
import asyncio
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.config import ADMINS
from database import db_registry
from database.media.routing import media_router
from database.media.indexing import indexing_jobs
from database.media.files import media_files_repo
from indexing.pipeline import process_message
from indexing.parsers import extract_series, extract_year

logger = logging.getLogger(__name__)

# ═══════════════════════ FANCY FONTS ═══════════════════════
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

def fb(s: str) -> str: return "".join(_M_BOLD.get(c, c) for c in s)
def sc(s: str) -> str: return "".join(_M_SC.get(c, c) for c in s)

# ═══════════════════════ CONSTANTS ═══════════════════════
IST = timezone(timedelta(hours=5, minutes=30))
TICK = "▰"
EMPTY = "▱"
BAR_W = 18
DIV = "━" * 26
DIV_S = "┄" * 26
PROGRESS_MIN_INTERVAL = 3.0   # seconds between progress edits

# ═══════════════════════ ENV ═══════════════════════
def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default

DATABASE_CHANNEL_ID: Optional[int] = _env_int("DATABASE_CHANNEL_ID")
AUTO_INDEXING_ENABLED = os.getenv("AUTO_INDEXING_ENABLED", "True").lower() in ("1", "true", "yes", "on")

# ═══════════════════════ HELPERS ═══════════════════════
def fmt_int(n: Optional[int]) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"

def now_ist() -> str:
    return datetime.now(IST).strftime("%I:%M:%S %p IST")

def is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False

def pbar(p: float, w: int = BAR_W) -> str:
    try:
        p = max(0.0, min(100.0, float(p)))
    except (TypeError, ValueError):
        p = 0.0
    filled = int(round(w * p / 100.0))
    filled = max(0, min(w, filled))
    return TICK * filled + EMPTY * (w - filled)

def pcolor(p: float) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "🔴"
    if p >= 100: return "🟢"
    if p >= 75:  return "🟢"
    if p >= 50:  return "🟡"
    if p >= 25:  return "🟠"
    return "🔴"

def progress_line(label: str, p: float, w: int = BAR_W) -> str:
    return f"{pcolor(p)} <b>{sc(label)}</b> · <code>{p:.1f}%</code>\n<code>{pbar(p, w)}</code>"

def fmt_duration(seconds: float) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"

# ═══════════════════════ JOB STATE ═══════════════════════
class _Jobs:
    """In-memory registry of running/paused indexing jobs."""
    def __init__(self):
        self.state: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    def create(self, job_id: str, data: Dict[str, Any]) -> None:
        self.state[job_id] = data

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.state.get(job_id)

    def attach(self, job_id: str, task: asyncio.Task) -> None:
        self.tasks[job_id] = task

    def drop(self, job_id: str) -> None:
        self.state.pop(job_id, None)
        self.tasks.pop(job_id, None)

    def pause(self, job_id: str) -> bool:
        st = self.state.get(job_id)
        if not st or st["status"] != "running":
            return False
        st["status"] = "paused"
        return True

    def resume(self, job_id: str) -> bool:
        st = self.state.get(job_id)
        if not st or st["status"] != "paused":
            return False
        st["status"] = "running"
        return True

    async def stop(self, job_id: str) -> bool:
        st = self.state.get(job_id)
        if not st:
            return False
        st["status"] = "stopped"
        task = self.tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except Exception:
                pass
        return True

    def has_running_for_channel(self, channel_id: int) -> Optional[str]:
        for jid, st in self.state.items():
            if st.get("channel_id") == channel_id and st["status"] in ("running", "paused"):
                return jid
        return None

jobs = _Jobs()

# Pending forward state (awaiting media-mode selection)
_pending_forwards: Dict[int, Dict[str, Any]] = {}


# ═══════════════════════ MAIN KEYBOARD ═══════════════════════
def kb_main() -> InlineKeyboardMarkup:
    auto_status = "🟢 ACTIVE" if (DATABASE_CHANNEL_ID and AUTO_INDEXING_ENABLED) else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 START CHANNEL INDEX", callback_data="idx_start")],
        [InlineKeyboardButton("📡 AUTO INDEXING", callback_data="idx_auto")],
        [InlineKeyboardButton("🎬 MOVIE INDEXING", callback_data="idx_movies"),
         InlineKeyboardButton("📺 SERIES INDEXING", callback_data="idx_series")],
        [InlineKeyboardButton("📊 INDEXING STATISTICS", callback_data="idx_stats"),
         InlineKeyboardButton("📋 INDEXING HISTORY", callback_data="idx_history")],
        [InlineKeyboardButton("🧹 DUPLICATE CONTROL", callback_data="idx_dups"),
         InlineKeyboardButton("🗄️ DATABASE ROUTING", callback_data="idx_routing")],
        [InlineKeyboardButton("📈 LIVE STATUS", callback_data="idx_live"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="idx_main")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="idx_close")],
    ])


async def _build_main() -> str:
    auto_status = "🟢 ᴀᴄᴛɪᴠᴇ" if (DATABASE_CHANNEL_ID and AUTO_INDEXING_ENABLED) else "🔴 ᴏꜰꜰ"
    ch = f"<code>{DATABASE_CHANNEL_ID}</code>" if DATABASE_CHANNEL_ID else "—"
    total = await media_files_repo.count_all()
    routing = await media_router.status()
    active = sum(1 for r in routing if r["ok"])
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('FILE INDEXING CENTER')}</b>",
        DIV, "",
        f"🕐 {sc('updated')} · <code>{now_ist()}</code>",
        "",
        f"📡 {sc('auto indexing')} · {auto_status}",
        f"📺 {sc('channel')} · {ch}",
        "",
        f"🎬 {sc('movies')} + 📺 {sc('series')}",
        f"🗄️ {sc('media shards')} · <b>{len(routing)}</b> · 🟢 <b>{active}</b> ʀᴇᴀᴅʏ",
        f"📦 {sc('total indexed')} · <code>{fmt_int(total)}</code>",
        "",
        DIV_S,
        f"ᴛᴡᴏ ᴍᴏᴅᴇꜱ · ᴍᴀɴᴜᴀʟ + ᴀᴜᴛᴏᴍᴀᴛɪᴄ",
        f"ᴍᴇᴛᴀᴅᴀᴛᴀ ꜰɪʀꜱᴛ · ɴᴏ ꜰɪʟᴇ ᴅᴏᴡɴʟᴏᴀᴅ",
    ])


# ═══════════════════════ COMMANDS ═══════════════════════
@Client.on_message(filters.command(["index", "indexing"]) & filters.private)
async def cmd_index(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
        return
    m = await message.reply_text("🔄 ʟᴏᴀᴅɪɴɢ...")
    try:
        text = await _build_main()
        await m.edit_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML,
                          disable_web_page_preview=True)
    except Exception as e:
        logger.exception("cmd_index failed")
        await m.edit_text(f"🔴 ꜰᴀɪʟᴇᴅ: <code>{e}</code>", parse_mode=ParseMode.HTML)


# ═══════════════════════ MAIN CALLBACKS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^idx_main$"))
async def cb_main(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    try:
        text = await _build_main()
        await q.message.edit_text(text, reply_markup=kb_main(), parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_close$"))
async def cb_close(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^idx_start$"))
async def cb_start(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📥 <b>{fb('CHANNEL BACKWARD INDEXING')}</b>",
        DIV, "",
        "ꜰᴏʀᴡᴀʀᴅ ᴀɴʏ ᴍᴇᴅɪᴀ ᴍᴇꜱꜱᴀɢᴇ ꜰʀᴏᴍ ᴛʜᴇ ᴛᴀʀɢᴇᴛ ᴄʜᴀɴɴᴇʟ ᴛᴏ ᴛʜɪꜱ ᴄʜᴀᴛ.",
        "",
        DIV_S,
        f"✅ ᴛʜᴇ ʙᴏᴛ ᴍᴜꜱᴛ ʙᴇ ᴀᴅᴍɪɴ ɪɴ ᴛʜᴀᴛ ᴄʜᴀɴɴᴇʟ",
        f"⬇️ ɪɴᴅᴇxɪɴɢ ɢᴏᴇꜱ ɴᴇᴡᴇꜱᴛ → ᴏʟᴅᴇꜱᴛ (ʙᴀᴄᴋᴡᴀʀᴅ)",
        f"⏸️ ᴘᴀᴜꜱᴇ / ʀᴇꜱᴜᴍᴇ / ꜱᴛᴏᴘ ꜱᴜᴘᴘᴏʀᴛᴇᴅ",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="idx_main")]])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_auto$"))
async def cb_auto(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    ch = f"<code>{DATABASE_CHANNEL_ID}</code>" if DATABASE_CHANNEL_ID else "ᴜɴꜱᴇᴛ"
    en = "🟢 ᴇɴᴀʙʟᴇᴅ" if AUTO_INDEXING_ENABLED else "🔴 ᴅɪꜱᴀʙʟᴇᴅ"
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📡 <b>{fb('AUTOMATIC INDEXING')}</b>",
        DIV, "",
        f"📺 {sc('channel id')} · {ch}",
        f"⚙️ {sc('auto indexing')} · {en}",
        "",
        DIV_S,
        "ᴡʜᴇɴ ᴀ ɴᴇᴡ ꜰɪʟᴇ ᴀʀʀɪᴠᴇꜱ ɪɴ ᴛʜᴇ ᴄᴏɴꜰɪɢᴜʀᴇᴅ ᴄʜᴀɴɴᴇʟ, ɪᴛ ᴡɪʟʟ ʙᴇ ᴘᴀʀꜱᴇᴅ ᴀɴᴅ ꜱᴀᴠᴇᴅ ꜱɪʟᴇɴᴛʟʏ.",
        "ɴᴏ ᴘʀᴏɢʀᴇꜱꜱ ꜱᴘᴀᴍ. ᴏɴʟʏ ᴇʀʀᴏʀꜱ ᴀɴᴅ ᴍᴀᴊᴏʀ ᴡᴀʀɴɪɴɢꜱ ᴀʀᴇ ꜱᴜʀꜰᴀᴄᴇᴅ.",
        "",
        f"ᴛᴏ ᴄʜᴀɴɢᴇ: ꜱᴇᴛ ᴇɴᴠ <code>DATABASE_CHANNEL_ID</code> ᴀɴᴅ <code>AUTO_INDEXING_ENABLED</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main")]])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_movies$"))
async def cb_movies(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('MOVIE INDEXING')}</b>",
        DIV, "",
        "ᴜꜱᴇ <b>📥 START CHANNEL INDEX</b> ᴀɴᴅ ᴄʜᴏᴏꜱᴇ <b>MOVIES ONLY</b> ᴡʜᴇɴ ᴘʀᴏᴍᴘᴛᴇᴅ.",
        "",
        DIV_S,
        "ᴏɴʟʏ ᴍᴏᴠɪᴇꜱ ᴡɪʟʟ ʙᴇ ɪɴᴅᴇxᴇᴅ ꜰʀᴏᴍ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ.",
        "ꜱᴇʀɪᴇꜱ ᴍᴇꜱꜱᴀɢᴇꜱ ᴡɪʟʟ ʙᴇ ꜱᴋɪᴘᴘᴇᴅ.",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📥 START CHANNEL INDEX", callback_data="idx_start")],
        [InlineKeyboardButton("◀️ BACK", callback_data="idx_main")]])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_series$"))
async def cb_series(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📺 <b>{fb('SERIES INDEXING')}</b>",
        DIV, "",
        "ᴜꜱᴇ <b>📥 START CHANNEL INDEX</b> ᴀɴᴅ ᴄʜᴏᴏꜱᴇ <b>SERIES ONLY</b> ᴡʜᴇɴ ᴘʀᴏᴍᴘᴛᴇᴅ.",
        "",
        DIV_S,
        "ᴏɴʟʏ ꜱᴇʀɪᴇꜱ (ᴡɪᴛʜ ꜱᴇᴀꜱᴏɴ/ᴇᴘɪꜱᴏᴅᴇ ᴍᴀʀᴋᴇʀꜱ) ᴡɪʟʟ ʙᴇ ɪɴᴅᴇxᴇᴅ.",
        "ᴍᴏᴠɪᴇꜱ ᴡɪʟʟ ʙᴇ ꜱᴋɪᴘᴘᴇᴅ.",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📥 START CHANNEL INDEX", callback_data="idx_start")],
        [InlineKeyboardButton("◀️ BACK", callback_data="idx_main")]])
    try:
        await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


# ═══════════════════════ FORWARD DETECTION ═══════════════════════
@Client.on_message(filters.private & ~filters.service & filters.user([int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]) if ADMINS else None)
async def forward_detect(client: Client, message: Message):
    """Detect forwarded messages from channels and offer indexing."""
    if not message.forward_from_chat:
        return
    chat = message.forward_from_chat
    if chat.type != ChatType.CHANNEL:
        return

    channel_id = chat.id
    channel_title = chat.title or chat.username or str(channel_id)
    start_msg_id = message.forward_from_message_id or message.id

    # Check for existing job on this channel
    existing = jobs.has_running_for_channel(channel_id)
    token = uuid.uuid4().hex[:10]
    _pending_forwards[message.from_user.id] = {
        "token": token,
        "channel_id": channel_id,
        "channel_title": channel_title,
        "start_message_id": start_msg_id,
    }

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📥 <b>{fb('CHANNEL DETECTED')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <code>{channel_title}</code>",
        f"🆔 {sc('channel id')} · <code>{channel_id}</code>",
        f"🆔 {sc('start message')} · <code>{start_msg_id}</code>",
        "",
        DIV_S,
        "ᴡʜᴀᴛ ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ɪɴᴅᴇx?",
    ])
    if existing:
        text += f"\n\n⚠️ ᴀ ᴊᴏʙ ɪꜱ ᴀʟʀᴇᴀᴅʏ ʀᴜɴɴɪɴɢ ꜰᴏʀ ᴛʜɪꜱ ᴄʜᴀɴɴᴇʟ (<code>{existing}</code>)."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MOVIES ONLY", callback_data=f"idx_mode:{token}:movies")],
        [InlineKeyboardButton("📺 SERIES ONLY", callback_data=f"idx_mode:{token}:series")],
        [InlineKeyboardButton("🎬 + 📺 BOTH", callback_data=f"idx_mode:{token}:both")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"idx_cancel:{token}")],
    ])
    try:
        await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)
    except Exception:
        logger.exception("forward_detect reply failed")


@Client.on_callback_query(filters.regex(r"^idx_cancel:(.+)$"))
async def cb_cancel_pending(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    _pending_forwards.pop(q.from_user.id, None)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄᴀɴᴄᴇʟʟᴇᴅ")


@Client.on_callback_query(filters.regex(r"^idx_mode:(.+):(movies|series|both)$"))
async def cb_mode(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    token = q.matches[0].group(1)
    mode = q.matches[0].group(2)
    pending = _pending_forwards.get(q.from_user.id)
    if not pending or pending.get("token") != token:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return

    channel_id = pending["channel_id"]
    channel_title = pending["channel_title"]
    start_msg_id = pending["start_message_id"]
    _pending_forwards.pop(q.from_user.id, None)

    # Block concurrent jobs on the same channel
    existing = jobs.has_running_for_channel(channel_id)
    if existing:
        await q.answer("⚠️ ᴀ ᴊᴏʙ ɪꜱ ᴀʟʀᴇᴀᴅʏ ʀᴜɴɴɪɴɢ ꜰᴏʀ ᴛʜɪꜱ ᴄʜᴀɴɴᴇʟ", show_alert=True)
        return

    job_id = f"INDEX-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    state = {
        "job_id": job_id,
        "admin_id": q.from_user.id,
        "chat_id": q.message.chat.id,
        "message_id": q.message.id,
        "channel_id": channel_id,
        "channel_title": channel_title,
        "start_message_id": start_msg_id,
        "current_message_id": start_msg_id,
        "mode": mode,
        "direction": "backward",
        "status": "running",
        "stats": {
            "processed": 0, "indexed": 0, "duplicates": 0,
            "skipped": 0, "failed": 0, "movies": 0, "series": 0,
        },
        "start_time": time.time(),
        "last_edit": 0.0,
    }
    jobs.create(job_id, state)

    # Persist initial job record
    try:
        db_id = await indexing_jobs.create({
            "job_id": job_id,
            "admin_id": q.from_user.id,
            "channel_id": channel_id,
            "channel_title": channel_title,
            "start_message_id": start_msg_id,
            "mode": mode,
            "direction": "backward",
            "status": "running",
            "stats": state["stats"],
        })
        state["db_id"] = db_id
    except Exception:
        state["db_id"] = None

    # Render initial progress and start task
    await _render_progress(client, job_id, force=True)
    task = asyncio.create_task(_run_job(client, job_id))
    jobs.attach(job_id, task)
    await q.answer("▶️ ꜱᴛᴀʀᴛᴇᴅ")


# ═══════════════════════ PROGRESS RENDER ═══════════════════════
async def _render_progress(client: Client, job_id: str, force: bool = False) -> None:
    st = jobs.get(job_id)
    if not st:
        return
    now = time.time()
    if not force and (now - st["last_edit"] < PROGRESS_MIN_INTERVAL):
        return
    st["last_edit"] = now

    stats = st["stats"]
    total_range = max(1, st["start_message_id"])
    current = st["current_message_id"]
    done = max(0, st["start_message_id"] - current)
    pct = min(100.0, (done / total_range) * 100.0)
    elapsed = max(0.0, now - st["start_time"])
    speed = stats["processed"] / (elapsed / 60.0) if elapsed > 0 else 0.0

    mode_label = {"movies": "🎬 MOVIES", "series": "📺 SERIES",
                  "both": "🎬 + 📺 BOTH"}.get(st["mode"], st["mode"].upper())

    # ────────── COMPLETED SCREEN ──────────
    if st["status"] == "completed":
        avg = speed
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('INDEXING COMPLETE')}</b>",
            DIV, "",
            f"📢 {sc('channel')} · <code>{st['channel_title']}</code>",
            f"🎬 {sc('mode')} · {mode_label}",
            "",
            DIV,
            f"📦 {sc('total processed')} · <code>{fmt_int(stats['processed'])}</code>",
            f"✅ {sc('files stored')} · <code>{fmt_int(stats['indexed'])}</code>",
            f"⏭️ {sc('duplicates found')} · <code>{fmt_int(stats['duplicates'])}</code>",
            f"⏭️ {sc('skipped')} · <code>{fmt_int(stats['skipped'])}</code>",
            f"❌ {sc('errors')} · <code>{fmt_int(stats['failed'])}</code>",
            "",
            f"🎬 {sc('movies')} · <code>{fmt_int(stats['movies'])}</code>",
            f"📺 {sc('series')} · <code>{fmt_int(stats['series'])}</code>",
            "",
            DIV,
            f"{pcolor_progress(100.0)} <b>{sc('progress')}</b> · <code>100.0%</code>",
            f"<code>{pbar(100.0)}</code>",
            "",
            f"⏱️ {sc('total time')} · <code>{fmt_duration(elapsed)}</code>",
            f"⚡ {sc('avg speed')} · <code>{avg:.1f} ꜰɪʟᴇꜱ/ᴍɪɴ</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CLOSE", callback_data="idx_close")]])
        try:
            await client.edit_message_text(
                chat_id=st["chat_id"], message_id=st["message_id"],
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception:
            pass
        return

    # ────────── STOPPED SCREEN ──────────
    if st["status"] == "stopped":
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🛑 <b>{fb('INDEXING STOPPED')}</b>",
            DIV, "",
            f"📢 {sc('channel')} · <code>{st['channel_title']}</code>",
            "",
            f"📦 {sc('processed')} · <code>{fmt_int(stats['processed'])}</code>",
            f"✅ {sc('files stored')} · <code>{fmt_int(stats['indexed'])}</code>",
            f"⏭️ {sc('duplicates')} · <code>{fmt_int(stats['duplicates'])}</code>",
            f"❌ {sc('errors')} · <code>{fmt_int(stats['failed'])}</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CLOSE", callback_data="idx_close")]])
        try:
            await client.edit_message_text(
                chat_id=st["chat_id"], message_id=st["message_id"],
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception:
            pass
        return

    # ────────── ERROR SCREEN ──────────
    if st["status"] == "error":
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔴 <b>{fb('INDEXING ERROR')}</b>",
            DIV, "",
            f"📢 {sc('channel')} · <code>{st['channel_title']}</code>",
            "",
            f"<code>{(st.get('error') or 'Unknown error')[:400]}</code>",
            "",
            f"📦 {sc('processed')} · <code>{fmt_int(stats['processed'])}</code>",
            f"✅ {sc('files stored')} · <code>{fmt_int(stats['indexed'])}</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CLOSE", callback_data="idx_close")]])
        try:
            await client.edit_message_text(
                chat_id=st["chat_id"], message_id=st["message_id"],
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception:
            pass
        return

    # ────────── RUNNING / PAUSED SCREEN ──────────
    status_icon = {"running": "🟢 ʀᴜɴɴɪɴɢ", "paused": "🟡 ᴘᴀᴜꜱᴇᴅ"}.get(
        st["status"], st["status"].upper())

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('CHANNEL INDEXING')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <code>{st['channel_title']}</code>",
        f"🆔 {sc('channel id')} · <code>{st['channel_id']}</code>",
        f"🎬 {sc('mode')} · {mode_label}",
        f"🔄 {sc('direction')} · ɴᴇᴡᴇꜱᴛ → ᴏʟᴅᴇꜱᴛ",
        f"🆔 {sc('start')} · <code>{st['start_message_id']}</code>",
        f"🆔 {sc('current')} · <code>{current}</code>",
        f"⚙️ {sc('status')} · {status_icon}",
        "",
        DIV,
        f"📦 {sc('processed')} · <code>{fmt_int(stats['processed'])}</code>",
        f"✅ {sc('indexed')} · <code>{fmt_int(stats['indexed'])}</code>",
        f"⏭️ {sc('duplicates')} · <code>{fmt_int(stats['duplicates'])}</code>",
        f"⏭️ {sc('skipped')} · <code>{fmt_int(stats['skipped'])}</code>",
        f"❌ {sc('failed')} · <code>{fmt_int(stats['failed'])}</code>",
        "",
        f"🎬 {sc('movies')} · <code>{fmt_int(stats['movies'])}</code>",
        f"📺 {sc('series')} · <code>{fmt_int(stats['series'])}</code>",
        "",
        DIV,
        f"{pcolor_progress(pct)} <b>{sc('progress')}</b> · <code>{pct:.1f}%</code>",
        f"<code>{pbar(pct)}</code>",
        "",
        f"⚡ {sc('speed')} · <code>{speed:.1f} ꜰɪʟᴇꜱ/ᴍɪɴ</code>",
        f"⏱️ {sc('elapsed')} · <code>{fmt_duration(elapsed)}</code>",
    ]
    text = "\n".join(lines)

    if st["status"] == "paused":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ RESUME", callback_data=f"idx_resume:{job_id}"),
             InlineKeyboardButton("❌ STOP", callback_data=f"idx_stop:{job_id}")],
        ])
    else:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⏸️ PAUSE", callback_data=f"idx_pause:{job_id}"),
             InlineKeyboardButton("❌ STOP", callback_data=f"idx_stop:{job_id}")],
        ])

    try:
        await client.edit_message_text(
            chat_id=st["chat_id"], message_id=st["message_id"],
            text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
    except Exception:
        pass

# ═══════════════════════ LIVE UPDATER ═══════════════════════
async def _live_updater(client: Client, job_id: str) -> None:
    """Update the progress message every 3 seconds while the job is active."""
    try:
        while True:
            st = jobs.get(job_id)
            if not st:
                return
            if st["status"] not in ("running", "paused"):
                # final render is handled by _finish
                return
            await _render_progress(client, job_id, force=True)
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.warning(f"live updater stopped: {e}")


# ═══════════════════════ PARALLEL BATCH PROCESSOR ═══════════════════════
async def _process_one(msg, st, stats, lock):
    """Process a single message and update stats safely, with live logs."""
    msg_id = getattr(msg, "id", "?")
    try:
        result = await process_message(msg, mode="manual")
        s = result["status"]
        rec = result.get("record") or {}
        title = rec.get("title") or rec.get("series_title") or "?"
        rtype = rec.get("type") or "?"
        quality = rec.get("quality") or "-"
        codec = rec.get("codec") or "-"
        audio = ",".join(rec.get("audio_languages") or []) or "-"

        async with lock:
            stats["processed"] += 1
            st["current_message_id"] = msg.id
            if s == "saved":
                stats["indexed"] += 1
                if rtype == "movie":
                    stats["movies"] += 1
                elif rtype == "series":
                    stats["series"] += 1
                shard = result.get("shard_index")
                logger.info(
                    f"[IDX] ✅ SAVED msg={msg_id} type={rtype} "
                    f"title='{title}' q={quality} c={codec} a={audio} "
                    f"shard=DB{shard+1 if isinstance(shard, int) else shard}"
                )
            elif s == "duplicate":
                stats["duplicates"] += 1
                reason = result.get("reason") or "unknown"
                shard = result.get("shard_index")
                logger.info(
                    f"[IDX] ♻️ DUPLICATE msg={msg_id} reason={reason} "
                    f"title='{title}' shard=DB{shard+1 if isinstance(shard, int) else shard}"
                )
            elif s == "skipped":
                stats["skipped"] += 1
                reason = result.get("reason") or "no_reason"
                logger.info(f"[IDX] ⏭️ SKIPPED msg={msg_id} reason={reason}")
            else:
                stats["failed"] += 1
                reason = result.get("reason") or "unknown"
                logger.warning(f"[IDX] ❌ FAILED msg={msg_id} reason={reason}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"[IDX] ❌ ERROR msg={msg_id}: {type(e).__name__}: {e}")
        async with lock:
            stats["processed"] += 1
            stats["failed"] += 1
            st["current_message_id"] = msg.id

async def _process_batch(msgs, st, stats, concurrency: int = 20):
    """Process a batch of messages with bounded concurrency."""
    clean = [m for m in msgs if m is not None and not getattr(m, "empty", False)]
    if not clean:
        return
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()

    async def _worker(msg):
        async with sem:
            await _process_one(msg, st, stats, lock)

    await asyncio.gather(*[_worker(m) for m in clean])


# ═══════════════════════ JOB WORKER ═══════════════════════
async def _run_job(client: Client, job_id: str) -> None:
    st = jobs.get(job_id)
    if not st:
        return

    stats = st["stats"]
    channel_id = st["channel_id"]
    start_id = st["start_message_id"]
    BATCH = 100         # Telegram GetMessages hard cap
    CONCURRENCY = 20    # parallel processors
    PREFETCH = True     # fetch next batch while processing current

    async def _finish(status: str):
        st["status"] = status
        await _render_progress(client, job_id, force=True)
        if st.get("db_id"):
            await indexing_jobs.update(st["db_id"], {
                "status": status,
                "end_time": datetime.utcnow(),
                "stats": stats,
                "current_message_id": st["current_message_id"],
                "error": st.get("error"),
            })

    async def _fetch(channel_id_, ids):
        try:
            msgs = await client.get_messages(channel_id_, message_ids=ids)
            if not isinstance(msgs, list):
                msgs = [msgs]
            return msgs
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
            return await _fetch(channel_id_, ids)
        except Exception as e:
            logger.warning(f"Batch fetch failed: {e}")
            return []

    try:
        # ── Verify bot can see the channel ──
        try:
            chat = await client.get_chat(channel_id)
            st["channel_title"] = chat.title or st.get("channel_title")
        except Exception as e:
            st["error"] = f"Cannot access channel {channel_id}: {type(e).__name__}: {e}"
            await _finish("error")
            return

        # ── Start live updater (every 3s) ──
        live_task = asyncio.create_task(_live_updater(client, job_id))

        current = start_id
        pending = None

        try:
            while current >= 1:
                # Cooperative pause
                while st["status"] == "paused":
                    await asyncio.sleep(0.5)
                if st["status"] in ("stopped", "error"):
                    await _finish(st["status"])
                    return

                # Compute the current batch
                batch_ids = list(range(max(1, current - BATCH + 1), current + 1))
                batch_ids.reverse()

                # Fetch current batch (await prefetched, or start fresh)
                if pending is not None:
                    msgs = await pending
                    pending = None
                else:
                    msgs = await _fetch(channel_id, batch_ids)

                # Kick off next batch fetch in background
                next_current = current - BATCH
                if PREFETCH and next_current >= 1:
                    next_ids = list(range(max(1, next_current - BATCH + 1), next_current + 1))
                    next_ids.reverse()
                    pending = asyncio.create_task(_fetch(channel_id, next_ids))

                # Process current batch in parallel
                await _process_batch(msgs, st, stats, concurrency=CONCURRENCY)
                                # Periodic status log every batch
                logger.info(
                    f"[IDX] batch done — current={current} "
                    f"processed={stats['processed']} saved={stats['indexed']} "
                    f"dups={stats['duplicates']} skipped={stats['skipped']} "
                    f"failed={stats['failed']} "
                    f"movies={stats['movies']} series={stats['series']}"
                )

                current = next_current
                if current < 1:
                    break

            await _finish("completed")
        finally:
            live_task.cancel()
            try:
                await live_task
            except Exception:
                pass

    except asyncio.CancelledError:
        st["status"] = "stopped"
        raise
    except Exception as e:
        logger.exception("Job failed")
        st["error"] = f"{type(e).__name__}: {e}"
        await _finish("error")
    finally:
        jobs.drop(job_id)

# ═══════════════════════ PAUSE / RESUME / STOP ═══════════════════════
@Client.on_callback_query(filters.regex(r"^idx_pause:(.+)$"))
async def cb_pause(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    jid = q.matches[0].group(1)
    if jobs.pause(jid):
        await q.answer("⏸️ ᴘᴀᴜꜱᴇᴅ")
        await _render_progress(client, jid, force=True)
    else:
        await q.answer("ᴄᴀɴɴᴏᴛ ᴘᴀᴜꜱᴇ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^idx_resume:(.+)$"))
async def cb_resume(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    jid = q.matches[0].group(1)
    if jobs.resume(jid):
        await q.answer("▶️ ʀᴇꜱᴜᴍᴇᴅ")
        await _render_progress(client, jid, force=True)
    else:
        await q.answer("ᴄᴀɴɴᴏᴛ ʀᴇꜱᴜᴍᴇ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^idx_stop:(.+)$"))
async def cb_stop(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    jid = q.matches[0].group(1)
    if await jobs.stop(jid):
        await q.answer("❌ ꜱᴛᴏᴘᴘᴇᴅ")
        st = jobs.get(jid)
        if st:
            await _render_progress(client, jid, force=True)
    else:
        await q.answer("ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)


# ═══════════════════════ STATS / HISTORY / DUPS / ROUTING ═══════════════════════
@Client.on_callback_query(filters.regex(r"^idx_stats$"))
async def cb_stats(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    total = await media_files_repo.count_all()
    routing = await media_router.status()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('INDEXING STATISTICS')}</b>",
        DIV, "",
        f"📦 {sc('total indexed')} · <code>{fmt_int(total)}</code>",
        "",
        DIV_S,
        f"🗄️ {sc('media shard distribution')}",
    ]
    total_docs = max(1, total)
    for r in routing:
        if not r["ok"] and r["used_mb"] is None:
            lines.append(f"🔴 <b>{sc('shard')} {r['index']:02d}</b> · ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ")
            continue
        p = r["pct"]
        lines.append(f"{pcolor(p)} <b>{sc('shard')} {r['index']:02d}</b> · "
                     f"<code>{r['used_mb']} MB</code> / <code>{r['threshold_mb']} MB</code>")
        lines.append(f"<code>{pbar(p, 16)}</code> {p:.1f}%")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="idx_stats"),
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main"),
    ]])
    try:
        await q.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_history$"))
async def cb_history(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    items = await indexing_jobs.recent(15)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📋 <b>{fb('INDEXING HISTORY')}</b>",
        DIV, "",
    ]
    if not items:
        lines.append("⚪ ɴᴏ ᴊᴏʙꜱ ʏᴇᴛ.")
    for j in items:
        s = j.get("stats", {})
        status = j.get("status", "?")
        icon = {"running": "🟢", "paused": "🟡", "stopped": "🔴",
                "completed": "🟢", "error": "🔴"}.get(status, "⚪")
        lines.append(f"{icon} <b>{j.get('job_id')}</b>")
        lines.append(f"  📢 <code>{j.get('channel_title')}</code>")
        lines.append(f"  🎬 {s.get('movies', 0)}  📺 {s.get('series', 0)}  ✅ {s.get('indexed', 0)}")
        lines.append(f"  ⏭️ {s.get('duplicates', 0)}  ⏭️ {s.get('skipped', 0)}  ❌ {s.get('failed', 0)}")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="idx_history"),
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main"),
    ]])
    try:
        await q.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_dups$"))
async def cb_dups(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🧹 <b>{fb('DUPLICATE CONTROL')}</b>",
        DIV, "",
        "ᴅᴜᴘʟɪᴄᴀᴛᴇ ᴅᴇᴛᴇᴄᴛɪᴏɴ ʀᴜɴꜱ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴅᴜʀɪɴɢ ɪɴᴅᴇxɪɴɢ:",
        "",
        DIV_S,
        "1️⃣ ᴇxᴀᴄᴛ · <code>file_unique_id</code> / <code>file_id</code>",
        "2️⃣ ʟᴏɢɪᴄᴀʟ · ᴛɪᴛʟᴇ + ʏᴇᴀʀ + ǫᴜᴀʟɪᴛʏ + ᴄᴏᴅᴇᴄ + ᴀᴜᴅɪᴏ + ꜱᴜʙ",
        "",
        "⚠️ ꜰɪʟᴇ ꜱɪᴢᴇ ɪꜱ ɴᴇᴠᴇʀ ᴜꜱᴇᴅ ᴀꜱ ᴀ ᴅᴜᴘʟɪᴄᴀᴛᴇ ᴋᴇʏ.",
        "⚠️ ʀᴇᴍᴏᴠᴀʟ ɪꜱ ɴᴏᴛ ᴇxᴘᴏꜱᴇᴅ ʜᴇʀᴇ — ᴜꜱᴇ ᴛʜᴇ ᴅᴀᴛᴀʙᴀꜱᴇ ᴄᴏɴᴛʀᴏʟ ᴄᴇɴᴛᴇʀ (/database).",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main")]])
    try:
        await q.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_routing$"))
async def cb_routing(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    routing = await media_router.status()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🗄️ <b>{fb('DATABASE ROUTING')}</b>",
        DIV, "",
        f"🎯 {sc('threshold')} · <code>{routing[0]['threshold_mb'] if routing else '—'} MB</code>",
        "",
    ]
    for r in routing:
        if r["used_mb"] is None:
            lines.append(f"🔴 <b>{sc('shard')} {r['index']:02d}</b> · ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ")
            continue
        p = r["pct"]
        active = "🟢 ᴀᴄᴛɪᴠᴇ" if r["ok"] else "🔴 ꜰᴜʟʟ"
        lines.append(f"{pcolor(p)} <b>{sc('shard')} {r['index']:02d}</b> · {active}")
        lines.append(f"  💾 <code>{r['used_mb']} MB</code> / <code>{r['threshold_mb']} MB</code>")
        lines.append(f"  <code>{pbar(p, 16)}</code> {p:.1f}%")
        lines.append("")
    lines.append(DIV_S)
    lines.append("ɴᴇᴡ ꜰɪʟᴇꜱ ɢᴏ ᴛᴏ ᴛʜᴇ ꜰɪʀꜱᴛ ꜱʜᴀʀᴅ ᴛʜᴀᴛ ɪꜱ ʙᴇʟᴏᴡ ᴛʜʀᴇꜱʜᴏʟᴅ.")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="idx_routing"),
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main"),
    ]])
    try:
        await q.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^idx_live$"))
async def cb_live(client: Client, q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📈 <b>{fb('LIVE INDEXING STATUS')}</b>",
        DIV, "",
    ]
    running = [st for st in jobs.state.values() if st["status"] in ("running", "paused")]
    if not running:
        lines.append("🟢 ɴᴏ ᴀᴄᴛɪᴠᴇ ᴊᴏʙꜱ.")
    for st in running:
        s = st["stats"]
        lines.append(f"📚 <b>{st['job_id']}</b>")
        lines.append(f"  📢 <code>{st['channel_title']}</code>")
        lines.append(f"  ⚙️ <code>{st['status']}</code>")
        lines.append(f"  📦 {s['processed']}  ✅ {s['indexed']}  ⏭️ {s['duplicates']}")
        lines.append("")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data="idx_live"),
        InlineKeyboardButton("◀️ BACK", callback_data="idx_main"),
    ]])
    try:
        await q.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception:
        pass
    await q.answer()


# ═══════════════════════ AUTO INDEXING ═══════════════════════
if DATABASE_CHANNEL_ID:
    @Client.on_message(filters.chat(DATABASE_CHANNEL_ID) & ~filters.service)
    async def auto_index_handler(client: Client, message: Message):
        """Silent auto-indexing. No progress spam."""
        if not AUTO_INDEXING_ENABLED:
            return
        # Ignore messages without media
        if not (message.video or message.document or message.audio):
            return
        try:
            result = await process_message(message, mode="auto")
            status = result["status"]
            if status == "saved":
                logger.info(f"[AUTO-IDX] saved msg={message.id} "
                            f"type={(result.get('record') or {}).get('type')}")
            elif status == "duplicate":
                logger.debug(f"[AUTO-IDX] duplicate msg={message.id}")
            elif status == "error":
                logger.warning(f"[AUTO-IDX] error msg={message.id}: {result.get('reason')}")
        except Exception as e:
            logger.exception(f"[AUTO-IDX] handler failed: {e}")
