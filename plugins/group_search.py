# plugins/group_search.py
# ═══════════════════════════════════════════════════════════════════════════
# 🏨 DOWNTOWN VILLA — ULTIMATE STANDALONE GROUP SEARCH + PM DELIVERY
# ═══════════════════════════════════════════════════════════════════════════
#
# This file is COMPLETELY STANDALONE. It does NOT import from media_search.
# It handles EVERYTHING:
#   ✔ Group auto-search (reads per-group settings)
#   ✔ File list shown in group with buttons
#   ✔ File click → redirect to PM
#   ✔ PM /start file_{sid}_{idx} → deliver with per-group custom buttons
#   ✔ Auto-delete per-group setting
#   ✔ Admin commands: /add_button, /list_buttons, /remove_button, /clear_buttons
#   ✔ Conflict-free: uses group=-999 priority so nothing steals /start
#
# All handlers use VERY high priority (group=-999) to prevent conflicts.
# ═══════════════════════════════════════════════════════════════════════════

import asyncio
import logging
import re
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    MessageNotModified,
)
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import db_manager

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] ====================================")
logger.info("[GROUP-SEARCH] ULTIMATE module LOADED")
logger.info("[GROUP-SEARCH] ====================================")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_DELETE_TIME = 600         # 10 minutes
DEFAULT_MAX_BUTTONS = 8           # per group
FILES_PER_PAGE = 10
SESSION_TTL = 1800                # 30 min

# Fallback links
try:
    from core.config import UPDATE_CHNL_LNK as _UPDATE
    UPDATE_CHNL_LNK = _UPDATE or "https://t.me/"
except Exception:
    UPDATE_CHNL_LNK = "https://t.me/"

try:
    from core.config import SUPPORT_CHAT as _SUPPORT
    SUPPORT_CHAT = _SUPPORT or "https://t.me/"
except Exception:
    SUPPORT_CHAT = "https://t.me/"

# Visual separator used in messages
DIV = "━" * 26


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — SESSION STORAGE (in-memory + optional DB)
# ═══════════════════════════════════════════════════════════════════════════
# In-memory sessions live for SESSION_TTL seconds.
# If the bot restarts, sessions are lost — user just searches again.
# Each session stores the file hits + the group's custom buttons snapshot.
# ═══════════════════════════════════════════════════════════════════════════

_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _new_session(
    hits: List[Dict],
    user_id: int,
    chat_id: int,
    custom_buttons: List[Dict],
) -> str:
    """Create a new search session and return its ID."""
    sid = secrets.token_hex(8)
    _SESSIONS[sid] = {
        "hits": hits[:60],                 # cap at 60 to bound memory
        "user_id": int(user_id or 0),
        "chat_id": int(chat_id or 0),
        "custom_buttons": list(custom_buttons or []),
        "created": time.time(),
        "expires": time.time() + SESSION_TTL,
    }
    logger.info(
        f"[SESSION] created sid={sid} hits={len(hits)} "
        f"user={user_id} chat={chat_id} btns={len(custom_buttons or [])}"
    )
    return sid


def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    """Retrieve a session if not expired."""
    s = _SESSIONS.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(sid, None)
        logger.debug(f"[SESSION] sid={sid} expired")
        return None
    return s


def _cleanup_sessions() -> None:
    """Remove expired sessions."""
    now = time.time()
    n = 0
    for sid in list(_SESSIONS.keys()):
        if _SESSIONS[sid]["expires"] < now:
            _SESSIONS.pop(sid, None)
            n += 1
    if n:
        logger.debug(f"[SESSION] cleaned {n} expired sessions")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _get_db():
    """Return the primary DB (whatever db_manager exposes)."""
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
        return db_manager._db  # noqa
    except Exception:
        return None


def _groups_coll():
    """Return `groups` collection."""
    db = _get_db()
    return db["groups"] if db is not None else None


def _media_collections() -> List[Tuple[int, Any]]:
    """Return list of (shard_index, collection) for every media shard."""
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
        logger.warning(f"[DB] media collections failed: {e}")
    return out


async def _load_group_settings(chat_id: int) -> Dict[str, Any]:
    """
    Load per-group settings from DB. Falls back to defaults.
    Supports BOTH the new-style (top-level) and old-style (settings sub-doc).
    """
    defaults = {
        "auto_ffilter": True,
        "auto_delete": True,
        "delete_time": DEFAULT_DELETE_TIME,
        "result_buttons": [],
        "fsub": [],
        "caption": None,
        "is_verify": False,
    }
    if not chat_id:
        return defaults

    coll = _groups_coll()
    if coll is None:
        return defaults

    try:
        doc = await coll.find_one({"chat_id": int(chat_id)})
    except Exception as e:
        logger.warning(f"[DB] settings read failed for {chat_id}: {e}")
        return defaults

    if not doc:
        return defaults

    merged = dict(defaults)

    # Old-style: settings sub-doc
    sub = doc.get("settings") or {}
    if isinstance(sub, dict):
        for k, v in sub.items():
            if v is not None:
                merged[k] = v

    # New-style: top-level fields
    for k in defaults.keys():
        if k in doc and doc[k] is not None:
            merged[k] = doc[k]

    return merged


async def _save_group_field(chat_id: int, field: str, value: Any) -> bool:
    """Atomically update one field in the group's settings."""
    coll = _groups_coll()
    if coll is None:
        return False
    try:
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$set": {
                    field: value,
                    f"settings.{field}": value,
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "created_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[DB] save failed {chat_id}/{field}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — QUERY NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════

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
    """Normalize query: lowercase, collapse separators, join single letters."""
    if not text:
        return ""

    t = text.strip().lower()

    # Collapse separators to spaces
    t = re.sub(r"[.\-_/,;:\\]+", " ", t)
    t = re.sub(r"\s+", " ", t)

    # K G F → KGF
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

    # Remove non-word chars
    t = re.sub(r"[^\w\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_query(raw: str) -> Tuple[str, Optional[int], bool]:
    """Return (normalized_title, year, is_series)."""
    year = None
    m = _YEAR_RE.search(raw or "")
    if m:
        year = int(m.group(1))

    is_series = bool(_SERIES_RE.search(raw or ""))

    # Strip metadata tokens
    t = _QUALITY_RE.sub(" ", raw or "")
    t = _CODEC_RE.sub(" ", t)
    t = _LANG_RE.sub(" ", t)
    t = _YEAR_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()

    norm = _normalize(t)
    words = [w for w in norm.split() if w not in _STOP_WORDS]
    return " ".join(words).strip(), year, is_series


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — SEARCH ENGINE (across all media shards)
# ═══════════════════════════════════════════════════════════════════════════

async def _search_all_shards(
    norm: str,
    year: Optional[int],
    is_series: bool,
    limit: int = 100,
) -> List[Dict]:
    """Search every media shard in parallel. Returns deduped list sorted by size."""
    collections = _media_collections()
    if not collections:
        logger.warning("[SEARCH] no media collections found")
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

    logger.info(f"[SEARCH] mongo_q={mongo_q}")

    async def _q_one(coll):
        try:
            cursor = coll.find(mongo_q).limit(limit)
            return await cursor.to_list(length=limit)
        except Exception as e:
            logger.warning(f"[SEARCH] shard query failed: {e}")
            return []

    results = await asyncio.gather(
        *[_q_one(c) for _, c in collections],
        return_exceptions=False,
    )

    all_docs: List[Dict] = []
    for chunk in results:
        all_docs.extend(chunk)

    # Dedupe by file_unique_id (or file_id or _id)
    seen = set()
    uniq = []
    for d in all_docs:
        key = d.get("file_unique_id") or d.get("file_id") or d.get("_id")
        if key and key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    # Sort by size ascending
    uniq.sort(key=lambda x: (x.get("file_size") is None, x.get("file_size") or 0))
    logger.info(f"[SEARCH] found {len(uniq)} unique files for {norm!r}")
    return uniq


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════

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
    """Clean a raw filename for display."""
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


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — KEYBOARD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════

def _build_custom_button_rows(raw_buttons: Any) -> List[List[InlineKeyboardButton]]:
    """Convert stored button dicts to InlineKeyboardButton rows. Permissive."""
    if not isinstance(raw_buttons, list):
        logger.info(f"[CUSTOM-BTNS] not a list: {type(raw_buttons)}")
        return []

    # Sort by position
    try:
        raw_buttons = sorted(raw_buttons, key=lambda b: b.get("position", 999))
    except Exception:
        pass

    logger.info(f"[CUSTOM-BTNS] raw data: {raw_buttons!r}")

    rows: List[List[InlineKeyboardButton]] = []
    for i, b in enumerate(raw_buttons):
        if not isinstance(b, dict):
            logger.info(f"[CUSTOM-BTNS] skip #{i}: not a dict")
            continue

        if b.get("enabled") is False:
            logger.info(f"[CUSTOM-BTNS] skip #{i}: disabled")
            continue

        name = (b.get("name") or b.get("text") or b.get("title") or "").strip()
        url = (b.get("url") or b.get("link") or b.get("href") or "").strip()

        if not name:
            logger.info(f"[CUSTOM-BTNS] skip #{i}: no name (keys: {list(b.keys())})")
            continue

        if not url:
            logger.info(f"[CUSTOM-BTNS] skip #{i}: no url (keys: {list(b.keys())})")
            continue

        # Normalize URL — accept t.me/xxx, @xxx, or bare domain
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif url.startswith("t.me/"):
            url = f"https://{url}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            # Try to make it a valid URL
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                logger.info(f"[CUSTOM-BTNS] skip #{i}: invalid url {url!r}")
                continue

        rows.append([InlineKeyboardButton(name[:60], url=url)])
        logger.info(f"[CUSTOM-BTNS] ✅ added: {name!r} → {url!r}")

    logger.info(f"[CUSTOM-BTNS] built {len(rows)} buttons")
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════

async def _is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    """Check if user is a group admin."""
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — GROUP SEARCH HANDLER (group=-999 to run first)
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-999,
)
async def group_search_handler(client: Client, message: Message):
    """
    Main group search handler.
    Only runs for TEXT messages in groups (not commands).
    """
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        raw = (message.text or "").strip()

        logger.info(
            f"[GROUP-SEARCH] msg chat={chat_id} user={user_id} text={raw!r}"
        )

        # Basic validation
        if len(raw) < 2 or len(raw) > 100:
            logger.debug("[GROUP-SEARCH] text too short/long, skipping")
            return

        # Load group settings
        settings = await _load_group_settings(chat_id)
        if not settings.get("auto_ffilter", True):
            logger.info("[GROUP-SEARCH] auto_ffilter OFF — skipping")
            return

        # Show status message
        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] cannot reply: {e}")
            return

        # Parse query
        norm, year, is_series = _parse_query(raw)
        if not norm:
            try:
                await status.edit_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
            except Exception:
                pass
            return

        # Search all shards
        docs = await _search_all_shards(norm, year, is_series)

        # Retry without year if empty
        if not docs and year:
            logger.info("[GROUP-SEARCH] retrying without year")
            docs = await _search_all_shards(norm, None, is_series)

        # Nothing found
        if not docs:
            logger.info("[GROUP-SEARCH] no results")
            try:
                await status.edit_text(
                    f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                    f"{DIV}\n\n"
                    f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{raw}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        # Snapshot custom buttons from THIS group
        raw_buttons = settings.get("result_buttons") or []

        # Create session
        sid = _new_session(
            hits=docs,
            user_id=user_id,
            chat_id=chat_id,
            custom_buttons=raw_buttons,
        )

        # Build file list buttons
        rows: List[List[InlineKeyboardButton]] = []
        for i, d in enumerate(docs[:FILES_PER_PAGE]):
            size = _human_size_short(d.get("file_size"))
            name = _clean_filename(
                d.get("file_name") or d.get("title"), max_len=42
            )
            label = f"📦 {size} · {name}"
            if len(label) > 62:
                label = label[:59] + "…"
            rows.append([InlineKeyboardButton(
                label,
                callback_data=f"gfile:{sid}:{i}",
            )])

        # "More" button if needed
        if len(docs) > FILES_PER_PAGE:
            rows.append([InlineKeyboardButton(
                f"➕ {len(docs) - FILES_PER_PAGE} ᴍᴏʀᴇ ʀᴇʟᴇᴀꜱᴇꜱ",
                callback_data=f"gfile:{sid}:more",
            )])

        # Close button
        rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="gclose")])

        # Title text
        title_display = raw.title() if raw else norm.title()
        text = (
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"{DIV}\n\n"
            f"🎬 <b>{title_display}</b>\n"
            f"📦 <b>{len(docs)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ\n\n"
            f"ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ:"
        )

        logger.info(
            f"[GROUP-SEARCH] sid={sid} buttons={len(rows)} "
            f"custom_btns={len(raw_buttons)}"
        )

        # Show file list in group
        try:
            await status.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            logger.info(f"[GROUP-SEARCH] ✅ file list shown sid={sid}")
        except MessageNotModified:
            pass
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] edit failed: {e}")

    except StopPropagation:
        raise
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — FILE CLICK CALLBACK (redirect to PM)
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^gfile:"), group=-999)
async def gfile_callback(client: Client, q: CallbackQuery):
    """
    File click in group → redirect to bot PM.
    If already in PM, deliver directly.
    """
    try:
        parts = q.data.split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        _, sid, idx = parts
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    logger.info(f"[GFILE] user={q.from_user.id} data={q.data!r}")

    session = _get_session(sid)
    if not session:
        return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ · ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ", show_alert=True)

    # "More" button
    if idx == "more":
        return await q.answer(
            "ᴜꜱᴇ ᴛʜᴇ ꜰɪʀꜱᴛ 10 ʀᴇʟᴇᴀꜱᴇꜱ", show_alert=True
        )

    try:
        i = int(idx)
    except ValueError:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx", show_alert=True)

    if i < 0 or i >= len(session["hits"]):
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx", show_alert=True)

    # Detect group vs PM
    try:
        is_group = q.message.chat.type in (
            ChatType.GROUP, ChatType.SUPERGROUP
        )
    except Exception:
        is_group = False

    if is_group:
        # ── GROUP → redirect to PM ──
        try:
            me = await client.get_me()
            deep_link = (
                f"https://t.me/{me.username}?start=file_{sid}_{i}"
            )
            logger.info(
                f"[GFILE] redirecting user={q.from_user.id} → {deep_link}"
            )
            try:
                q.stop_propagation()
            except Exception:
                pass
            await q.answer(url=deep_link)
        except Exception as e:
            logger.exception(f"[GFILE] redirect failed: {e}")
            try:
                await q.answer("⚠️ ᴇʀʀᴏʀ · ᴛʀʏ ᴀɢᴀɪɴ", show_alert=True)
            except Exception:
                pass
        return

    # ── PM → deliver directly ──
    try:
        await _deliver_file(client, q.from_user.id, session, i)
        try:
            await q.answer("✅ ꜱᴇɴᴛ ᴛᴏ ʏᴏᴜʀ ᴘᴍ")
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"[GFILE] PM delivery failed: {e}")
        try:
            await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — PM /start HANDLER (group=-999 to run first)
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command("start") & filters.private, group=-999)
async def pm_start_handler(client: Client, message: Message):
    """
    PM /start handler. Handles:
      /start                        → welcome
      /start file_{sid}_{idx}       → deliver file
      /start reff_{user_id}         → referral (ignored, shows welcome)
      /start anything_else          → welcome
    """
    logger.info(
        f"[START-PM] ⚡ fired user={message.from_user.id} "
        f"text={message.text!r} cmd_len={len(message.command)}"
    )

    try:
        if len(message.command) < 2:
            return await _send_welcome(client, message)

        payload = message.command[1]

        # ── File delivery payload ──
        if payload.startswith("file_"):
            try:
                _, sid, idx_str = payload.split("_", 2)
                i = int(idx_str)
            except Exception:
                logger.warning(f"[START-PM] malformed payload: {payload!r}")
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ.")

            logger.info(f"[START-PM] sid={sid} idx={i}")

            session = _get_session(sid)
            if not session:
                logger.info(f"[START-PM] session not found: {sid}")
                return await message.reply_text(
                    "⚠️ <b>ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.</b>\n\n"
                    "ᴘʟᴇᴀꜱᴇ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ.",
                    parse_mode=ParseMode.HTML,
                )

            if i < 0 or i >= len(session["hits"]):
                logger.warning(f"[START-PM] index out of range: {i}")
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ ɪɴᴅᴇx.")

            # Verify user is still in the group (optional)
            group_id = session.get("chat_id")
            if group_id:
                try:
                    await client.get_chat_member(
                        group_id, message.from_user.id
                    )
                except Exception as e:
                    logger.warning(f"[START-PM] user not in group: {e}")
                    # Continue anyway — user might have left, but we deliver

            # Deliver the file
            await _deliver_file(client, message.from_user.id, session, i)
            return

        # ── Any other payload → welcome ──
        return await _send_welcome(client, message)

    except StopPropagation:
        raise
    except Exception as e:
        logger.exception(f"[START-PM] crashed: {e}")


async def _send_welcome(client: Client, message: Message):
    """Send a simple welcome message in PM."""
    try:
        await message.reply_text(
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"{DIV}\n\n"
            "🔎 ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ,\n"
            "ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ʜᴇʀᴇ.",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[START-PM] welcome failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — FILE DELIVERY
# ═══════════════════════════════════════════════════════════════════════════

async def _deliver_file(
    client: Client,
    chat_id: int,
    session: Dict[str, Any],
    idx: int,
):
    """Deliver a file to `chat_id` with per-group custom buttons + auto-delete."""
    try:
        doc = session["hits"][idx]
    except Exception:
        return

    file_id = doc.get("file_id") or doc.get("_id")
    if not file_id:
        logger.warning("[DELIVERY] no file_id in doc")
        return

    # ── Extract metadata ──
    title = doc.get("title") or doc.get("series_title") or "file"
    file_name = doc.get("file_name") or title
    quality = (doc.get("quality") or "").upper()
    codec = (doc.get("codec") or "").upper()
    audio = ", ".join(doc.get("audio_languages") or []) or "—"
    subtitle = ", ".join(doc.get("subtitle_languages") or []) or "—"
    size = _human_size(doc.get("file_size"))
    year = doc.get("year")

    # ── Build caption ──
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

    # ── Build keyboard: custom buttons + SHARE + UPDATES ──
    kb_rows: List[List[InlineKeyboardButton]] = []

    custom_rows = _build_custom_button_rows(
        session.get("custom_buttons") or []
    )
    if custom_rows:
        kb_rows.extend(custom_rows)

    # Bot username
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
        InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK),
    ])

    kb = InlineKeyboardMarkup(kb_rows)

    # ── Send the file ──
    sent = None
    try:
        sent = await client.send_cached_media(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            reply_markup=kb,
        )
        logger.info(
            f"[DELIVERY] ✅ sent file_id={file_id[:20]}… to={chat_id} "
            f"custom_btns={len(custom_rows)}"
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
            logger.info(f"[DELIVERY] ✅ sent after FloodWait to={chat_id}")
        except Exception as e2:
            logger.warning(f"[DELIVERY] retry failed: {e2}")
            return
    except Exception as e:
        logger.warning(f"[DELIVERY] failed: {e}")
        try:
            await client.send_message(
                chat_id=chat_id,
                text="❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ꜰɪʟᴇ. ᴛʀʏ ᴀɢᴀɪɴ.",
            )
        except Exception:
            pass
        return

    # ── Auto-delete per group settings ──
    group_id = session.get("chat_id") or 0
    settings = await _load_group_settings(group_id)

    if not settings.get("auto_delete", True):
        return

    delete_time = int(settings.get("delete_time", DEFAULT_DELETE_TIME))
    if delete_time < 30:
        delete_time = 30

    minutes = max(1, delete_time // 60)

    if sent:
        warning_id = None
        try:
            warn = await client.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ "
                    f"<b>{minutes} ᴍɪɴᴜᴛᴇꜱ</b>.\n"
                    f"ᴘʟᴇᴀꜱᴇ ꜱᴀᴠᴇ ɪᴛ ɴᴏᴡ."
                ),
                parse_mode=ParseMode.HTML,
            )
            warning_id = warn.id
        except Exception:
            pass

        asyncio.create_task(
            _auto_delete(client, chat_id, sent.id, warning_id, delete_time)
        )


async def _auto_delete(
    client: Client,
    chat_id: int,
    msg_id: int,
    warn_id: Optional[int],
    seconds: int,
):
    """Delete the file (and warning) after `seconds`."""
    try:
        await asyncio.sleep(seconds)
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
    except Exception as e:
        logger.debug(f"[AUTODEL] error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — CLOSE CALLBACK
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^gclose$"), group=-999)
async def gclose_callback(client: Client, q: CallbackQuery):
    """Delete the search message when user clicks CLOSE."""
    try:
        await q.message.delete()
    except Exception:
        pass
    try:
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — ADMIN COMMANDS (in group)
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command("add_button") & filters.group, group=-999)
async def cmd_add_button(client: Client, message: Message):
    """Add a custom button that appears on delivered files."""
    try:
        if not message.from_user:
            return
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or "|" not in args[1]:
            return await message.reply_text(
                "ᴜꜱᴀɢᴇ:\n<code>/add_button NAME | URL</code>\n\n"
                "ᴇxᴀᴍᴘʟᴇ:\n"
                "<code>/add_button Join Channel | https://t.me/yourchannel</code>",
                parse_mode=ParseMode.HTML,
            )

        name, url = [p.strip() for p in args[1].split("|", 1)]
        if not (url.startswith("http://") or url.startswith("https://")
                or url.startswith("tg://")):
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")

        coll = _groups_coll()
        if coll is None:
            return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")

        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = list(
            doc.get("result_buttons")
            or (doc.get("settings") or {}).get("result_buttons")
            or []
        )

        if len(btns) >= DEFAULT_MAX_BUTTONS:
            return await message.reply_text(
                f"⚠️ ᴍᴀx {DEFAULT_MAX_BUTTONS} ʙᴜᴛᴛᴏɴꜱ ᴀʟʟᴏᴡᴇᴅ."
            )

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
            f"✅ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ\n\n"
            f"ɴᴀᴍᴇ: <b>{name}</b>\n"
            f"ᴜʀʟ: <code>{url}</code>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(
            f"[ADMIN] add_button chat={message.chat.id} name={name!r}"
        )
    except Exception as e:
        logger.exception(f"[ADMIN] add_button crashed: {e}")
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("list_buttons") & filters.group, group=-999)
async def cmd_list_buttons(client: Client, message: Message):
    """List all custom buttons for this group."""
    try:
        coll = _groups_coll()
        if coll is None:
            return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")

        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = (
            doc.get("result_buttons")
            or (doc.get("settings") or {}).get("result_buttons")
            or []
        )

        if not btns:
            return await message.reply_text(
                "⚪ ɴᴏ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ.\n"
                "ᴜꜱᴇ <code>/add_button NAME | URL</code> ᴛᴏ ᴀᴅᴅ ᴏɴᴇ.",
                parse_mode=ParseMode.HTML,
            )

        lines = ["📦 <b>ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ</b>", DIV, ""]
        for i, b in enumerate(btns, 1):
            enabled = "🟢" if b.get("enabled", True) else "🔴"
            lines.append(
                f"{i}. {enabled} <b>{b.get('name')}</b>\n"
                f"   <code>{b.get('url')}</code>"
            )
        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("remove_button") & filters.group, group=-999)
async def cmd_remove_button(client: Client, message: Message):
    """Remove a button by its list number."""
    try:
        if not message.from_user:
            return
        if not await _is_admin(client, message.chat.id, message.from_user.id):
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

        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        btns = list(
            doc.get("result_buttons")
            or (doc.get("settings") or {}).get("result_buttons")
            or []
        )

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


@Client.on_message(filters.command("clear_buttons") & filters.group, group=-999)
async def cmd_clear_buttons(client: Client, message: Message):
    """Remove all custom buttons for this group."""
    try:
        if not message.from_user:
            return
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        coll = _groups_coll()
        if coll is None:
            return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")

        await coll.update_one(
            {"chat_id": message.chat.id},
            {"$set": {"result_buttons": []}},
        )
        await message.reply_text("✅ ᴀʟʟ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ ᴄʟᴇᴀʀᴇᴅ.")
    except Exception as e:
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("set_delete_time") & filters.group, group=-999)
async def cmd_set_delete_time(client: Client, message: Message):
    """Set auto-delete seconds for this group."""
    try:
        if not message.from_user:
            return
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        args = (message.text or "").split()
        if len(args) < 2:
            return await message.reply_text(
                "ᴜꜱᴀɢᴇ: <code>/set_delete_time 600</code> (seconds)\n"
                "ᴇxᴀᴍᴘʟᴇꜱ:\n"
                "• 60 = 1 min\n"
                "• 600 = 10 min\n"
                "• 1800 = 30 min",
                parse_mode=ParseMode.HTML,
            )
        try:
            secs = int(args[1])
        except ValueError:
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇᴄᴏɴᴅꜱ.")

        if secs < 30:
            return await message.reply_text("⚠️ ᴍɪɴɪᴍᴜᴍ 30 ꜱᴇᴄᴏɴᴅꜱ.")

        ok = await _save_group_field(message.chat.id, "delete_time", secs)
        if ok:
            await message.reply_text(
                f"✅ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇ ꜱᴇᴛ ᴛᴏ <b>{secs} ꜱᴇᴄᴏɴᴅꜱ</b>.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴀᴠᴇ.")
    except Exception as e:
        await message.reply_text(f"❌ {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 15 — BACKGROUND CLEANUP
# ═══════════════════════════════════════════════════════════════════════════

async def _session_cleanup_loop():
    """Periodically clean expired sessions."""
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_session_cleanup_loop())
except Exception as e:
    logger.warning(f"[GROUP-SEARCH] cleanup task failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — STARTUP VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

async def _startup_check():
    """Verify DB + media shards at startup."""
    try:
        await asyncio.sleep(3)
        db = _get_db()
        if db is None:
            logger.error("[GROUP-SEARCH] ⚠️ primary DB unavailable")
            return
        logger.info(f"[GROUP-SEARCH] ✅ primary DB ready")
        shards = _media_collections()
        logger.info(f"[GROUP-SEARCH] ✅ {len(shards)} media shards available")
        for idx, coll in shards[:5]:
            try:
                n = await coll.estimated_document_count()
                logger.info(
                    f"[GROUP-SEARCH]   shard #{idx} → {n:,} documents"
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[GROUP-SEARCH] startup check failed: {e}")


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_startup_check())
except Exception:
    pass


logger.info("[GROUP-SEARCH] ALL HANDLERS REGISTERED ✅")
logger.info("[GROUP-SEARCH] Commands: /add_button /list_buttons "
            "/remove_button /clear_buttons /set_delete_time")
logger.info("[GROUP-SEARCH] Ready.")
