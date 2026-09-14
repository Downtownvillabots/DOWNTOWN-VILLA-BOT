# plugins/group_search.py
"""
🏨 DOWNTOWN VILLA — ULTIMATE Standalone Group Search.

Per-group settings:
  • auto_ffilter          → enable/disable search
  • result_buttons        → custom buttons on delivered file
  • fsub                  → custom force-sub channels
  • is_verify             → verification (shortener) — TODO
  • caption               → custom file caption
  • auto_delete           → toggle auto-delete of delivered files
  • delete_time           → seconds before delete (default 600)

Group flow:
  User types in group → read THAT group's settings → search → show file buttons
  User clicks file → Telegram switches to bot PM → /start file_{sid}_{idx}
  PM delivers file WITH that group's custom buttons + SHARE/UPDATES
  File auto-deletes per group's setting
"""

import asyncio
import logging
import re
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import db_manager

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded (ultimate)")


# ═══════════════════════════════════════════════════════════
# DEFAULTS
# ═══════════════════════════════════════════════════════════
DEFAULT_SETTINGS: Dict[str, Any] = {
    "auto_ffilter": True,
    "auto_delete": True,
    "delete_time": 600,
    "result_buttons": [],
    "fsub": [],
    "caption": None,
    "is_verify": False,
}

MAX_FILES_IN_LIST = 10
SESSION_TTL = 1800
DIV = "━" * 26

try:
    from core.config import UPDATE_CHNL_LNK
except Exception:
    UPDATE_CHNL_LNK = "https://t.me/"


# ═══════════════════════════════════════════════════════════
# SESSION STORE (in-memory)
# ═══════════════════════════════════════════════════════════
# { sid: {"hits": [...], "user_id": int, "chat_id": int, "expires": float, "buttons": [...]} }
_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _new_session(hits: List[Dict], user_id: int, chat_id: int,
                 custom_buttons: List[Dict]) -> str:
    sid = secrets.token_hex(8)
    _SESSIONS[sid] = {
        "hits": hits[:50],
        "user_id": user_id,
        "chat_id": chat_id,
        "custom_buttons": custom_buttons or [],
        "expires": time.time() + SESSION_TTL,
    }
    return sid


def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(sid, None)
        return None
    return s


def _cleanup_sessions() -> None:
    now = time.time()
    for sid in list(_SESSIONS.keys()):
        if _SESSIONS[sid]["expires"] < now:
            _SESSIONS.pop(sid, None)


# ═══════════════════════════════════════════════════════════
# DB HELPERS
# ═══════════════════════════════════════════════════════════
def _groups_coll():
    """Return groups collection."""
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None:
                    return db["groups"]
    except Exception:
        pass
    return None


def _media_collections() -> List[Tuple[int, Any]]:
    """All media shards: [(index, collection)]."""
    out: List[Tuple[int, Any]] = []
    try:
        if hasattr(db_manager, "get_media_db_list"):
            for idx in db_manager.get_media_db_list():
                db = db_manager.get_media_db(idx)
                if db is not None:
                    out.append((idx, db["media_files"]))
        if not out and hasattr(db_manager, "get_media_db"):
            try:
                db = db_manager.get_media_db()
            except TypeError:
                db = db_manager.get_media_db(1)
            if db is not None:
                out.append((1, db["media_files"]))
    except Exception as e:
        logger.warning(f"[GROUP-SEARCH] media colls failed: {e}")
    return out


async def _get_group_settings(chat_id: int) -> Dict[str, Any]:
    """
    Load full per-group settings.
    Merges: DEFAULTS → settings sub-doc → top-level fields.
    """
    if not chat_id:
        return dict(DEFAULT_SETTINGS)

    coll = _groups_coll()
    if coll is None:
        return dict(DEFAULT_SETTINGS)

    try:
        doc = await coll.find_one({"chat_id": int(chat_id)})
    except Exception as e:
        logger.warning(f"[GROUP-SEARCH] settings load failed: {e}")
        return dict(DEFAULT_SETTINGS)

    merged = dict(DEFAULT_SETTINGS)
    if not doc:
        return merged

    # Merge "settings" sub-doc first
    sub = doc.get("settings") or {}
    if isinstance(sub, dict):
        for k, v in sub.items():
            if v is not None:
                merged[k] = v

    # Then overlay top-level fields
    for k in list(DEFAULT_SETTINGS.keys()):
        if k in doc and doc[k] is not None:
            merged[k] = doc[k]

    return merged


# ═══════════════════════════════════════════════════════════
# QUERY NORMALIZATION
# ═══════════════════════════════════════════════════════════
_STOP_WORDS = {
    "movie", "movies", "film", "films", "download", "watch",
    "online", "free", "hd", "full", "the", "and",
}
_YEAR_RE = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")
_SERIES_RE = re.compile(
    r"\b(s\d{1,2}(?:e\d{1,3})?|season\s*\d+|episode\s*\d+|ep\s*\d+|\d+x\d+)\b",
    re.IGNORECASE,
)
_QUALITY_RE = re.compile(
    r"\b(2160p|4k|uhd|1440p|1080p|1080i|720p|576p|480p|360p|fhd|sd)\b",
    re.IGNORECASE,
)
_CODEC_RE = re.compile(
    r"\b(hevc|h\.?265|x265|h\.?264|x264|avc|av1|vp9|web-?dl|webrip|bluray|"
    r"blu-?ray|brrip|bdrip|hdrip|dvdrip|hdtv|hdcam|cam|pre-?dvd)\b",
    re.IGNORECASE,
)
_LANG_RE = re.compile(
    r"\b(eng|en|english|hin|hi|hindi|mal|ml|malayalam|tam|ta|tamil|"
    r"tel|te|telugu|kan|kn|kannada|multi)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[.\-_/,;:\\]+", " ", t)
    t = re.sub(r"\s+", " ", t)

    tokens = t.split()
    out, buf = [], []
    for tok in tokens:
        if len(tok) == 1 and tok.isalpha():
            buf.append(tok)
        else:
            if len(buf) >= 2:
                out.append("".join(buf))
            else:
                out.extend(buf)
            buf = []
            out.append(tok)
    if len(buf) >= 2:
        out.append("".join(buf))
    else:
        out.extend(buf)
    t = " ".join(out)

    t = re.sub(r"[^\w\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_query(raw: str) -> Tuple[str, Optional[int], bool]:
    year = None
    m = _YEAR_RE.search(raw or "")
    if m:
        year = int(m.group(1))

    is_series = bool(_SERIES_RE.search(raw or ""))

    t = _QUALITY_RE.sub(" ", raw or "")
    t = _CODEC_RE.sub(" ", t)
    t = _LANG_RE.sub(" ", t)
    t = _YEAR_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()

    norm = _normalize(t)
    words = [w for w in norm.split() if w not in _STOP_WORDS]
    return " ".join(words).strip(), year, is_series


# ═══════════════════════════════════════════════════════════
# SEARCH
# ═══════════════════════════════════════════════════════════
async def _search_all_shards(norm: str, year: Optional[int],
                              is_series: bool, limit: int = 100) -> List[Dict]:
    collections = _media_collections()
    if not collections:
        return []

    escaped = re.escape(norm)
    prefix_re = f"^{escaped}\\b"

    if is_series:
        mongo_q: Dict[str, Any] = {
            "$or": [
                {"normalized_series_title": norm},
                {"normalized_series_title": {"$regex": prefix_re}},
                {"normalized_title": norm},
                {"normalized_title": {"$regex": prefix_re}},
            ]
        }
    else:
        mongo_q = {
            "$or": [
                {"normalized_title": norm},
                {"normalized_title": {"$regex": prefix_re}},
                {"normalized_series_title": norm},
                {"normalized_series_title": {"$regex": prefix_re}},
            ]
        }

    if year:
        mongo_q["year"] = year

    async def _q_one(coll):
        try:
            cursor = coll.find(mongo_q).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] shard query failed: {e}")
            return []

    results = await asyncio.gather(*[_q_one(c) for _, c in collections])
    all_docs: List[Dict] = []
    for chunk in results:
        all_docs.extend(chunk)

    # Dedupe
    seen = set()
    uniq = []
    for d in all_docs:
        key = d.get("file_unique_id") or d.get("file_id") or d.get("_id")
        if key and key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    uniq.sort(key=lambda x: (x.get("file_size") is None, x.get("file_size") or 0))
    return uniq


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _human_size(size) -> str:
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


def _human_size_short(size) -> str:
    if not size:
        return "0B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    if s >= 100:
        return f"{int(s)}{units[i]}"
    return f"{s:.1f}{units[i]}"


def _clean_filename(name: Optional[str], max_len: int = 70) -> str:
    if not name:
        return ""
    n = str(name)
    n = re.sub(
        r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg|3gp|srt|vtt|ass)$",
        "", n, flags=re.IGNORECASE,
    )
    n = re.sub(r"@[\w_]+", " ", n)
    n = re.sub(r"https?://\S+", " ", n)
    n = re.sub(r"www\.\S+", " ", n)
    n = re.sub(r"[._\-+\[\]\(\)\{\}]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    if len(n) > max_len:
        n = n[: max_len - 1].rstrip() + "…"
    return n or "file"


def _build_custom_button_rows(raw_buttons: Any) -> List[List[InlineKeyboardButton]]:
    """Convert saved button dicts → InlineKeyboardButton rows."""
    if not isinstance(raw_buttons, list):
        return []
    # sort by position
    try:
        raw_buttons = sorted(raw_buttons, key=lambda b: b.get("position", 999))
    except Exception:
        pass

    rows: List[List[InlineKeyboardButton]] = []
    for b in raw_buttons:
        if not isinstance(b, dict):
            continue
        if b.get("enabled") is False:
            continue
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")
                or url.startswith("tg://")):
            continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return rows


# ═══════════════════════════════════════════════════════════
# 1) GROUP MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════
@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-10,
)
async def group_search_handler(client: Client, message: Message):
    logger.info(
        f"[GROUP-SEARCH] chat={message.chat.id} "
        f"user={message.from_user.id if message.from_user else '?'} "
        f"text={message.text!r}"
    )

    try:
        # ── Load per-group settings ──
        settings = await _get_group_settings(message.chat.id)
        if not settings.get("auto_ffilter", True):
            logger.info("[GROUP-SEARCH] auto_ffilter OFF — skip")
            return

        raw = (message.text or "").strip()
        if len(raw) < 2 or len(raw) > 100:
            return

        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] reply failed: {e}")
            return

        norm, year, is_series = _parse_query(raw)
        if not norm:
            await status.edit_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
            return

        docs = await _search_all_shards(norm, year, is_series)
        logger.info(f"[GROUP-SEARCH] {len(docs)} hits")

        if not docs and year:
            docs = await _search_all_shards(norm, None, is_series)
            logger.info(f"[GROUP-SEARCH] retry without year: {len(docs)} hits")

        if not docs:
            try:
                await status.edit_text(
                    f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                    f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{raw}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        # ── Snapshot the group's custom buttons NOW ──
        raw_buttons = settings.get("result_buttons") or []
        sid = _new_session(
            docs,
            user_id=message.from_user.id if message.from_user else 0,
            chat_id=message.chat.id,
            custom_buttons=raw_buttons,
        )

        # ── Build file list buttons ──
        rows: List[List[InlineKeyboardButton]] = []
        for i, d in enumerate(docs[:MAX_FILES_IN_LIST]):
            size = _human_size_short(d.get("file_size"))
            name = _clean_filename(d.get("file_name") or d.get("title"), max_len=42)
            label = f"📦 {size} · {name}"
            if len(label) > 62:
                label = label[:59] + "…"
            rows.append([InlineKeyboardButton(
                label,
                callback_data=f"gfile:{sid}:{i}",
            )])

        if len(docs) > MAX_FILES_IN_LIST:
            rows.append([InlineKeyboardButton(
                f"➕ {len(docs) - MAX_FILES_IN_LIST} ᴍᴏʀᴇ",
                callback_data=f"gfile:{sid}:more",
            )])

        rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="gclose")])

        title_display = raw.title() if raw else norm.title()
        text = (
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"{DIV}\n\n"
            f"🎬 <b>{title_display}</b>\n"
            f"📦 <b>{len(docs)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ\n\n"
            f"ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ:"
        )

        logger.info(
            f"[GROUP-SEARCH] session={sid} buttons={len(rows)} "
            f"custom_btns={len(raw_buttons)}"
        )

        try:
            await status.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            logger.info(f"[GROUP-SEARCH] ✅ file list shown (sid={sid})")
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] edit failed: {e}")

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════
# 2) FILE CLICK → REDIRECT
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gfile:"), group=-100)
async def gfile_callback(client: Client, q: CallbackQuery):
    try:
        _, sid, idx = q.data.split(":", 2)
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    logger.info(f"[GROUP-SEARCH] callback user={q.from_user.id} data={q.data!r}")

    session = _get_session(sid)
    if not session:
        return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    if idx == "more":
        return await q.answer("ᴜꜱᴇ ᴛʜᴇ ꜰɪʀꜱᴛ 10 ʀᴇʟᴇᴀꜱᴇꜱ", show_alert=True)

    try:
        i = int(idx)
    except ValueError:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if i < 0 or i >= len(session["hits"]):
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    is_group = q.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

    if is_group:
        try:
            me = await client.get_me()
            deep_link = f"https://t.me/{me.username}?start=file_{sid}_{i}"
            logger.info(f"[GROUP-SEARCH] redirect user={q.from_user.id} → {deep_link}")
            try:
                q.stop_propagation()
            except Exception:
                pass
            await q.answer(url=deep_link)
        except Exception as e:
            logger.exception(f"[GROUP-SEARCH] redirect failed: {e}")
            await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        return

    await _deliver_file(client, q.from_user.id, session, i)


# ═══════════════════════════════════════════════════════════
# 3) PM /start
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("start") & filters.private)
async def pm_start_handler(client: Client, message: Message):
    logger.info(f"[START-PM] user={message.from_user.id} text={message.text!r}")

    if len(message.command) < 2:
        return await _send_welcome(client, message)

    payload = message.command[1]

    if payload.startswith("file_"):
        try:
            _, sid, idx = payload.split("_", 2)
            i = int(idx)
        except Exception:
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ.")

        logger.info(f"[START-PM] sid={sid} idx={i}")

        session = _get_session(sid)
        if not session:
            return await message.reply_text(
                "⚠️ <b>ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.</b>\n"
                "ᴘʟᴇᴀꜱᴇ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ.",
                parse_mode=ParseMode.HTML,
            )

        if i < 0 or i >= len(session["hits"]):
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ ɪɴᴅᴇx.")

        # ── Verify user still has access to the group ──
        group_id = session.get("chat_id")
        if group_id:
            try:
                await client.get_chat_member(group_id, message.from_user.id)
            except Exception:
                # User left the group — still allow delivery? No, block.
                return await message.reply_text(
                    "⚠️ ʏᴏᴜ ᴀʀᴇ ɴᴏ ʟᴏɴɢᴇʀ ɪɴ ᴛʜᴀᴛ ɢʀᴏᴜᴘ.",
                    parse_mode=ParseMode.HTML,
                )

        await _deliver_file(client, message.from_user.id, session, i)
        return

    return await _send_welcome(client, message)


async def _send_welcome(client: Client, message: Message):
    await message.reply_text(
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ,\n"
        "ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ʜᴇʀᴇ.",
        parse_mode=ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
# 4) DELIVER FILE (uses session's stored group buttons)
# ═══════════════════════════════════════════════════════════
async def _deliver_file(client: Client, chat_id: int,
                        session: Dict[str, Any], idx: int):
    doc = session["hits"][idx]
    file_id = doc.get("file_id") or doc.get("_id")
    if not file_id:
        logger.warning("[DELIVERY] no file_id")
        return

    title = doc.get("title") or doc.get("series_title") or "file"
    file_name = doc.get("file_name") or title
    quality = (doc.get("quality") or "").upper()
    codec = (doc.get("codec") or "").upper()
    audio = ", ".join(doc.get("audio_languages") or []) or "—"
    subtitle = ", ".join(doc.get("subtitle_languages") or []) or "—"
    size = _human_size(doc.get("file_size"))
    year = doc.get("year")

    # ── Caption ──
    lines = [f"🎬 <b>{_clean_filename(file_name, max_len=80)}</b>"]
    if year:
        lines.append(f"📅 {year}")
    lines.append("")
    if quality:
        lines.append(f"🎞️ Qᴜᴀʟɪᴛʏ: <code>{quality}</code>")
    if codec:
        lines.append(f"🧬 Cᴏᴅᴇᴄ: <code>{codec}</code>")
    lines.append(f"🔊 Aᴜᴅɪᴏ: <code>{audio}</code>")
    lines.append(f"📝 Sᴜʙᴛɪᴛʟᴇ: <code>{subtitle}</code>")
    lines.append(f"💾 Sɪᴢᴇ: <code>{size}</code>")
    lines.append("")
    lines.append("⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>")
    caption = "\n".join(lines)

    # ── Build keyboard ──
    # 1) Custom group buttons (from the ORIGINAL group)
    kb_rows: List[List[InlineKeyboardButton]] = []
    custom = _build_custom_button_rows(session.get("custom_buttons") or [])
    if custom:
        kb_rows.extend(custom)

    # 2) SHARE + UPDATES always on top row(s)
    try:
        me = await client.get_me()
        bot_username = me.username
    except Exception:
        bot_username = ""

    share_url = (
        f"https://t.me/share/url?"
        f"url=https://t.me/{bot_username}&"
        f"text={quote_plus(f'🎬 {title} — via @{bot_username}')}"
    )
    kb_rows.append([
        InlineKeyboardButton("📤 SHARE", url=share_url),
        InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK or "https://t.me/"),
    ])

    kb = InlineKeyboardMarkup(kb_rows)

    # ── Send file ──
    sent = None
    try:
        sent = await client.send_cached_media(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            reply_markup=kb,
        )
        logger.info(
            f"[DELIVERY] sent file_id={file_id[:20]}… to={chat_id} "
            f"custom_btns={len(custom)}"
        )
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            sent = await client.send_cached_media(
                chat_id=chat_id,
                file_id=file_id,
                caption=caption,
                reply_markup=kb,
            )
        except Exception as e2:
            logger.warning(f"[DELIVERY] retry failed: {e2}")
            return
    except Exception as e:
        logger.warning(f"[DELIVERY] failed: {e}")
        return

    # ── Auto-delete using ORIGINAL group's setting ──
    group_id = session.get("chat_id") or 0
    group_settings = await _get_group_settings(group_id)
    if not group_settings.get("auto_delete", True):
        return

    minutes = max(1, int(group_settings.get("delete_time", 600)) // 60)
    if sent:
        warning_msg_id = None
        try:
            warn = await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ "
                    f"<b>{minutes} ᴍɪɴᴜᴛᴇꜱ</b>."
                ),
                parse_mode=ParseMode.HTML,
            )
            warning_msg_id = warn.id
        except Exception:
            pass

        asyncio.create_task(
            _auto_delete(client, chat_id, sent.id, warning_msg_id, minutes)
        )


async def _auto_delete(client: Client, chat_id: int, msg_id: int,
                       warn_id: Optional[int], minutes: int):
    try:
        await asyncio.sleep(max(30, minutes * 60))
        if warn_id:
            try:
                await client.delete_messages(chat_id, warn_id)
            except Exception:
                pass
        try:
            await client.delete_messages(chat_id, msg_id)
            logger.info(f"[AUTODEL] deleted chat={chat_id} msg={msg_id}")
        except Exception:
            pass
    except asyncio.CancelledError:
        return


# ═══════════════════════════════════════════════════════════
# 5) CLOSE
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gclose$"))
async def gclose(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


# ═══════════════════════════════════════════════════════════
# 6) CLEANUP TASK
# ═══════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception:
    pass


# ═══════════════════════════════════════════════════════════
# 7) ADMIN IN-GROUP BUTTON MANAGEMENT
# ═══════════════════════════════════════════════════════════
async def _is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


@Client.on_message(filters.command("add_button") & filters.group)
async def cmd_add_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ:\n<code>/add_button NAME | URL</code>",
            parse_mode=ParseMode.HTML,
        )

    name, url = [p.strip() for p in args[1].split("|", 1)]
    if not (url.startswith("http://") or url.startswith("https://")
            or url.startswith("tg://")):
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")

    coll = _groups_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")

    try:
        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = list(doc.get("result_buttons") or
                    (doc.get("settings") or {}).get("result_buttons") or [])
        if len(btns) >= 8:
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({
            "name": name[:60],
            "url": url,
            "position": len(btns) + 1,
            "enabled": True,
        })
        await coll.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"result_buttons": btns}},
            upsert=True,
        )
        await message.reply_text(
            f"✅ ᴀᴅᴅᴇᴅ ʙᴜᴛᴛᴏɴ: <b>{name}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] add_button failed: {e}")
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("list_buttons") & filters.group)
async def cmd_list_buttons(client: Client, message: Message):
    coll = _groups_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")
    try:
        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = doc.get("result_buttons") or \
               (doc.get("settings") or {}).get("result_buttons") or []
        if not btns:
            return await message.reply_text("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ.")
        lines = ["📦 <b>ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ</b>", DIV, ""]
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{b.get('name')}</b> → <code>{b.get('url')}</code>")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("remove_button") & filters.group)
async def cmd_remove_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/remove_button NUMBER</code>",
            parse_mode=ParseMode.HTML,
        )
    try:
        idx = int(args[1]) - 1
    except ValueError:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.")
    coll = _groups_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")
    try:
        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = list(doc.get("result_buttons") or
                    (doc.get("settings") or {}).get("result_buttons") or [])
        if idx < 0 or idx >= len(btns):
            return await message.reply_text("❌ ᴏᴜᴛ ᴏꜰ ʀᴀɴɢᴇ.")
        removed = btns.pop(idx)
        for i, b in enumerate(btns, 1):
            b["position"] = i
        await coll.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"result_buttons": btns}},
        )
        await message.reply_text(
            f"✅ ʀᴇᴍᴏᴠᴇᴅ: <b>{removed.get('name')}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("clear_buttons") & filters.group)
async def cmd_clear_buttons(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    coll = _groups_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")
    try:
        await coll.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"result_buttons": []}},
        )
        await message.reply_text("✅ ᴀʟʟ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ ᴄʟᴇᴀʀᴇᴅ.")
    except Exception as e:
        await message.reply_text(f"❌ {e}")
