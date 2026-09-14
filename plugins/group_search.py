# ═══════════════════════════════════════════════════════════════════════════
# 🏨 DOWNTOWN VILLA — ULTIMATE GROUP SEARCH (COMPLETE STANDALONE)
# ═══════════════════════════════════════════════════════════════════════════
#
# This is a fully self-contained file. It does NOT import from media_search.
#
# FEATURES:
#   ✔ Group auto-search (per-group settings)
#   ✔ File list shown in group (small → big)
#   ✔ File click → redirect to PM (Telegram switches automatically)
#   ✔ PM /start file_{sid}_{idx} → delivers with per-group custom buttons
#   ✔ No results → IMDb suggestions (with years)
#   ✔ Suggestion click → retry search → if found show files
#   ✔ Suggestion click → still no files → post to REQUEST CHANNEL
#   ✔ Request channel has admin action buttons (uploaded/not found/etc.)
#   ✔ Admin action → user gets DM notification
#   ✔ Auto-delete (per-group setting)
#   ✔ Admin commands: /add_button, /list_buttons, /remove_button,
#                     /clear_buttons, /set_delete_time, /debug_buttons
#   ✔ All handlers use group=-999 (highest priority)
#   ✔ Full error handling & logging
#
# ═══════════════════════════════════════════════════════════════════════════

import asyncio
import logging
import re
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

from pyrogram import Client, filters, StopPropagation
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import (
    FloodWait, MessageIdInvalid, MessageNotModified, UserIsBlocked,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import db_manager

# Optional config imports (failsafe)
try:
    from core.config import UPDATE_CHNL_LNK as _U
    UPDATE_CHNL_LNK = _U or "https://t.me/"
except Exception:
    UPDATE_CHNL_LNK = "https://t.me/"

try:
    from core.config import SUPPORT_CHAT as _S
    SUPPORT_CHAT = _S or "https://t.me/"
except Exception:
    SUPPORT_CHAT = "https://t.me/"

try:
    from core.config import REQST_CHANNEL as _R
    REQST_CHANNEL = _R
except Exception:
    REQST_CHANNEL = None

try:
    from core.config import OWNER_LNK as _O
    OWNER_LNK = _O or "https://t.me/"
except Exception:
    OWNER_LNK = "https://t.me/"

try:
    from core.config import ADMINS as _A
    ADMINS = list(_A or [])
except Exception:
    ADMINS = []

# Optional IMDb service
try:
    from imdbkit import IMDBKit
    _IMDB = IMDBKit()
    _HAS_IMDB = True
except Exception as _e:
    _IMDB = None
    _HAS_IMDB = False

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] ═══════════════════════════════════════════")
logger.info("[GROUP-SEARCH] ULTIMATE module loading...")
logger.info(f"[GROUP-SEARCH] IMDb available: {_HAS_IMDB}")
logger.info(f"[GROUP-SEARCH] Request channel: {REQST_CHANNEL}")
logger.info(f"[GROUP-SEARCH] Admins: {len(ADMINS)}")
logger.info("[GROUP-SEARCH] ═══════════════════════════════════════════")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

DEFAULT_DELETE_TIME = 600          # 10 min
DEFAULT_MAX_BUTTONS = 8
FILES_PER_PAGE = 10
SESSION_TTL = 1800                 # 30 min
SUGGESTION_LIMIT = 10
DIV = "━" * 26
DIV2 = "─" * 26


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — IN-MEMORY SESSION STORE
# ═══════════════════════════════════════════════════════════════════════════

_SESSIONS: Dict[str, Dict[str, Any]] = {}
_SUGGESTIONS: Dict[str, Dict[str, Any]] = {}


def _new_search_session(hits: List[Dict], user_id: int, chat_id: int,
                        custom_buttons: List[Dict],
                        query: str = "") -> str:
    sid = secrets.token_hex(8)
    _SESSIONS[sid] = {
        "hits": hits[:60],
        "user_id": int(user_id or 0),
        "chat_id": int(chat_id or 0),
        "custom_buttons": list(custom_buttons or []),
        "query": query,
        "created": time.time(),
        "expires": time.time() + SESSION_TTL,
    }
    logger.info(
        f"[SESSION] created sid={sid} hits={len(hits)} "
        f"user={user_id} chat={chat_id} btns={len(custom_buttons or [])}"
    )
    return sid


def _get_search_session(sid: str) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(sid, None)
        return None
    return s


def _new_suggestion_session(suggestions: List[Dict], user_id: int,
                            chat_id: int, query: str,
                            custom_buttons: List[Dict]) -> str:
    sid = secrets.token_hex(8)
    _SUGGESTIONS[sid] = {
        "suggestions": suggestions[:15],
        "user_id": int(user_id or 0),
        "chat_id": int(chat_id or 0),
        "query": query,
        "custom_buttons": list(custom_buttons or []),
        "expires": time.time() + SESSION_TTL,
    }
    logger.info(
        f"[SUGGEST] session created sid={sid} count={len(suggestions)} query={query!r}"
    )
    return sid


def _get_suggestion_session(sid: str) -> Optional[Dict[str, Any]]:
    s = _SUGGESTIONS.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SUGGESTIONS.pop(sid, None)
        return None
    return s


def _cleanup_expired() -> None:
    now = time.time()
    for sid in list(_SESSIONS.keys()):
        if _SESSIONS[sid]["expires"] < now:
            _SESSIONS.pop(sid, None)
    for sid in list(_SUGGESTIONS.keys()):
        if _SUGGESTIONS[sid]["expires"] < now:
            _SUGGESTIONS.pop(sid, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — DATABASE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _get_db():
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
    db = _get_db()
    return db["groups"] if db is not None else None


def _requests_coll():
    db = _get_db()
    return db["search_requests"] if db is not None else None


def _media_collections() -> List[Tuple[int, Any]]:
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
        logger.warning(f"[DB] media colls failed: {e}")
    return out


async def _load_group_settings(chat_id: int) -> Dict[str, Any]:
    defaults = {
        "auto_ffilter": True,
        "auto_delete": True,
        "delete_time": DEFAULT_DELETE_TIME,
        "result_buttons": [],
        "fsub": [],
        "is_verify": False,
        "send_suggestions": True,
        "request_enabled": True,
    }
    if not chat_id:
        return defaults

    coll = _groups_coll()
    if coll is None:
        return defaults

    try:
        doc = await coll.find_one({"chat_id": int(chat_id)})
    except Exception as e:
        logger.warning(f"[DB] settings load failed {chat_id}: {e}")
        return defaults

    if not doc:
        return defaults

    merged = dict(defaults)
    sub = doc.get("settings") or {}
    if isinstance(sub, dict):
        for k, v in sub.items():
            if v is not None:
                merged[k] = v
    for k in defaults.keys():
        if k in doc and doc[k] is not None:
            merged[k] = doc[k]
    return merged


async def _save_group_field(chat_id: int, field: str, value: Any) -> bool:
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


async def _add_request_record(user_id: int, query: str,
                               movie_name: str, source: str = "search") -> Optional[str]:
    """Save a not-found request to DB. Returns token_id."""
    coll = _requests_coll()
    if coll is None:
        return None
    try:
        token_id = uuid.uuid4().hex[:12]
        now = time.time()
        await coll.insert_one({
            "token_id": token_id,
            "user_id": int(user_id),
            "query": query,
            "movie_name": movie_name,
            "status": "not_found",
            "source": source,
            "created_at": now,
            "expires_at": now + (7 * 24 * 3600),
        })
        logger.info(f"[REQ] request saved token={token_id} user={user_id} query={query!r}")
        return token_id
    except Exception as e:
        logger.warning(f"[REQ] save failed: {e}")
        return None


async def _update_request_status(token_id: str, status: str) -> bool:
    coll = _requests_coll()
    if coll is None:
        return False
    try:
        r = await coll.update_one(
            {"token_id": token_id},
            {"$set": {"status": status, "updated_at": time.time()}},
        )
        return r.modified_count > 0
    except Exception:
        return False


async def _get_request(token_id: str) -> Optional[Dict]:
    coll = _requests_coll()
    if coll is None:
        return None
    try:
        return await coll.find_one({"token_id": token_id})
    except Exception:
        return None


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


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — SEARCH ENGINE
# ═══════════════════════════════════════════════════════════════════════════

async def _search_all_shards(norm: str, year: Optional[int],
                              is_series: bool, limit: int = 100) -> List[Dict]:
    if not norm:
        return []
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
            logger.warning(f"[SEARCH] shard query failed: {e}")
            return []

    results = await asyncio.gather(
        *[_q_one(c) for _, c in collections],
        return_exceptions=False,
    )

    all_docs: List[Dict] = []
    for chunk in results:
        all_docs.extend(chunk)

    seen = set()
    uniq = []
    for d in all_docs:
        key = d.get("file_unique_id") or d.get("file_id") or d.get("_id")
        if key and key in seen:
            continue
        seen.add(key)
        uniq.append(d)

    uniq.sort(key=lambda x: (x.get("file_size") is None, x.get("file_size") or 0))
    logger.info(f"[SEARCH] {len(uniq)} unique files for {norm!r} year={year}")
    return uniq


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — IMDb SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════

async def _imdb_suggestions(query: str) -> List[Dict[str, Any]]:
    """Get IMDb suggestions with years."""
    if not _HAS_IMDB:
        return []
    try:
        result = await asyncio.to_thread(_IMDB.search_movie, query)
        titles = getattr(result, "titles", None) if result else None
        if not titles:
            logger.info(f"[IMDB] no suggestions for {query!r}")
            return []

        out: List[Dict[str, Any]] = []
        for m in titles:
            t = getattr(m, "title", None)
            if not t:
                continue
            out.append({
                "title": t,
                "year": getattr(m, "year", None),
                "imdb_id": getattr(m, "imdb_id", None),
                "kind": getattr(m, "kind", None),
            })
            if len(out) >= SUGGESTION_LIMIT:
                break

        logger.info(f"[IMDB] {len(out)} suggestions for {query!r}")
        return out
    except Exception as e:
        logger.warning(f"[IMDB] suggestion failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — FORMATTING
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
    """Ultra-permissive custom button builder."""
    if not raw_buttons or not isinstance(raw_buttons, list):
        return []
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
        name = (b.get("name") or b.get("text") or b.get("title")
                or b.get("label") or "").strip()
        url = (b.get("url") or b.get("link") or b.get("href") or "").strip()
        if not name or not url:
            continue
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif url.startswith("t.me/") or url.startswith("telegram.me/"):
            url = f"https://{url}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — PERMISSIONS
# ═══════════════════════════════════════════════════════════════════════════

def _is_bot_owner(user_id: int) -> bool:
    try:
        return int(user_id) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


async def _is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    if _is_bot_owner(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — REQUEST CHANNEL POSTING
# ═══════════════════════════════════════════════════════════════════════════

async def _post_request_to_channel(client: Client, user_id: int,
                                    user_mention: str, movie_name: str,
                                    year: Optional[int] = None,
                                    imdb_id: Optional[str] = None,
                                    source: str = "search") -> Optional[str]:
    """Post a request to REQST_CHANNEL with admin action buttons."""
    if not REQST_CHANNEL:
        logger.info("[REQ] no REQST_CHANNEL configured")
        return None

    token_id = await _add_request_record(user_id, movie_name, movie_name, source)
    if not token_id:
        return None

    title_display = movie_name + (f" ({year})" if year else "")
    text = (
        f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        f"📝 <b>ɴᴇᴡ ᴍᴏᴠɪᴇ ʀᴇǫᴜᴇꜱᴛ</b>\n"
        f"{DIV}\n\n"
        f"🎬 ᴍᴏᴠɪᴇ · <b>{title_display}</b>\n"
    )
    if imdb_id:
        text += f"🆔 ɪᴍᴅʙ · <code>{imdb_id}</code>\n"
    text += (
        f"\n"
        f"👤 ᴜꜱᴇʀ · {user_mention}\n"
        f"🆔 ᴜꜱᴇʀ ɪᴅ · <code>{user_id}</code>\n\n"
        f"🔑 ᴛᴏᴋᴇɴ · <code>{token_id}</code>\n"
        f"{DIV}\n\n"
        f"<i>ᴀᴅᴍɪɴ · ᴄʜᴏᴏꜱᴇ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ</i>"
    )

    buttons = [
        [InlineKeyboardButton(
            "🎬 MOVIE UPDATED",
            callback_data=f"greq:{token_id}:updated",
        )],
        [
            InlineKeyboardButton(
                "📅 NOT RELEASED",
                callback_data=f"greq:{token_id}:notreleased",
            ),
            InlineKeyboardButton(
                "🔎 NOT FOUND",
                callback_data=f"greq:{token_id}:notfound",
            ),
        ],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"greq:{token_id}:cancel",
        )],
    ]

    try:
        sent = await client.send_message(
            chat_id=REQST_CHANNEL,
            text=text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[REQ] posted to channel token={token_id}")
        return token_id
    except Exception as e:
        logger.warning(f"[REQ] post failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — GROUP MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-999,
)
async def group_search_handler(client: Client, message: Message):
    try:
        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        user_mention = (message.from_user.mention
                        if message.from_user and hasattr(message.from_user, "mention")
                        else "user")
        raw = (message.text or "").strip()

        logger.info(
            f"[GROUP-SEARCH] msg chat={chat_id} user={user_id} text={raw!r}"
        )

        if len(raw) < 2 or len(raw) > 100:
            return

        settings = await _load_group_settings(chat_id)
        if not settings.get("auto_ffilter", True):
            logger.info("[GROUP-SEARCH] auto_ffilter OFF")
            return

        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] reply failed: {e}")
            return

        norm, year, is_series = _parse_query(raw)
        if not norm:
            try:
                await status.edit_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
            except Exception:
                pass
            return

        docs = await _search_all_shards(norm, year, is_series)

        # Retry without year
        if not docs and year:
            docs = await _search_all_shards(norm, None, is_series)

        # ── NO RESULTS → IMDb SUGGESTIONS ──
        if not docs:
            logger.info(f"[GROUP-SEARCH] no files — fetching IMDb suggestions")
            await _handle_no_results(
                client, message, status, raw, norm, year, is_series,
                settings, user_id, user_mention,
            )
            return

        # ── RESULTS FOUND → show file list ──
        raw_buttons = settings.get("result_buttons") or []
        sid = _new_search_session(
            hits=docs,
            user_id=user_id,
            chat_id=chat_id,
            custom_buttons=raw_buttons,
            query=raw,
        )
        await _show_file_list(status, raw, docs, sid, user_mention)

    except StopPropagation:
        raise
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")


async def _handle_no_results(client, message, status, raw, norm, year,
                              is_series, settings, user_id, user_mention):
    """Handle no results: IMDb suggestions or request channel."""
    # Check if suggestions are enabled
    if not settings.get("send_suggestions", True):
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

    # Try IMDb
    suggestions = await _imdb_suggestions(raw)

    if not suggestions:
        # No IMDb suggestions either
        logger.info("[GROUP-SEARCH] no IMDb suggestions")
        try:
            await status.edit_text(
                f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"{DIV}\n\n"
                f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{raw}</code>\n\n"
                f"ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ꜱᴘᴇʟʟɪɴɢ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        # Send to request channel
        if settings.get("request_enabled", True):
            await _post_request_to_channel(
                client, user_id, user_mention, raw,
                year=year, source="no_suggestions",
            )
        return

    # Build suggestion session
    raw_buttons = settings.get("result_buttons") or []
    ssid = _new_suggestion_session(
        suggestions=suggestions,
        user_id=user_id,
        chat_id=message.chat.id,
        query=raw,
        custom_buttons=raw_buttons,
    )

    # Build suggestion buttons
    rows = []
    for i, s in enumerate(suggestions[:10]):
        title = s.get("title") or "?"
        yr = s.get("year")
        label = f"🎬 {title}" + (f" ({yr})" if yr else "")
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"gsug:{ssid}:{i}",
        )])

    rows.append([InlineKeyboardButton(
        "🔎 CHECK ON GOOGLE",
        url=f"https://www.google.com/search?q={quote_plus(raw)}",
    )])
    rows.append([InlineKeyboardButton(
        "📝 REQUEST TO ADMIN",
        callback_data=f"gsug:{ssid}:request",
    )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="gclose")])

    text = (
        f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        f"🤔 <b>ᴅɪᴅ ʏᴏᴜ ᴍᴇᴀɴ?</b>\n"
        f"{DIV}\n\n"
        f"🔍 ʏᴏᴜ ꜱᴇᴀʀᴄʜᴇᴅ: <code>{raw}</code>\n\n"
        f"📝 <b>{len(suggestions)}</b> ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ:\n\n"
        f"ᴘɪᴄᴋ ᴛʜᴇ ᴏɴᴇ ʏᴏᴜ ᴍᴇᴀɴᴛ:"
    )

    try:
        await status.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[SUGGEST] shown {len(suggestions)} suggestions ssid={ssid}")
    except Exception as e:
        logger.warning(f"[SUGGEST] edit failed: {e}")


async def _show_file_list(target, raw, docs, sid, user_mention):
    """Show file list with buttons."""
    rows = []
    for i, d in enumerate(docs[:FILES_PER_PAGE]):
        size = _human_size_short(d.get("file_size"))
        name = _clean_filename(d.get("file_name") or d.get("title"), max_len=42)
        label = f"📦 {size} · {name}"
        if len(label) > 62:
            label = label[:59] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"gfile:{sid}:{i}",
        )])

    if len(docs) > FILES_PER_PAGE:
        rows.append([InlineKeyboardButton(
            f"➕ {len(docs) - FILES_PER_PAGE} ᴍᴏʀᴇ ʀᴇʟᴇᴀꜱᴇꜱ",
            callback_data=f"gfile:{sid}:more",
        )])

    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="gclose")])

    title_display = raw.title() if raw else "?"
    text = (
        f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        f"{DIV}\n\n"
        f"🎬 <b>{title_display}</b>\n"
        f"📦 <b>{len(docs)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ\n\n"
        f"ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ:"
    )

    try:
        await target.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[GROUP-SEARCH] file list shown sid={sid}")
    except Exception as e:
        logger.warning(f"[GROUP-SEARCH] edit failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — SUGGESTION CLICK HANDLER
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^gsug:"), group=-999)
async def gsug_callback(client: Client, q: CallbackQuery):
    """User clicked an IMDb suggestion."""
    try:
        parts = q.data.split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        _, ssid, idx = parts
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    session = _get_suggestion_session(ssid)
    if not session:
        return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    # Manual request button
    if idx == "request":
        await q.answer("📝 ꜱᴇɴᴅɪɴɢ ʀᴇǫᴜᴇꜱᴛ...")
        user_mention = q.from_user.mention if hasattr(q.from_user, "mention") else "user"
        await _post_request_to_channel(
            client, q.from_user.id, user_mention,
            session["query"], source="manual_request",
        )
        try:
            await q.message.edit_text(
                f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"{DIV}\n\n"
                f"✅ ʀᴇǫᴜᴇꜱᴛ ꜱᴇɴᴛ ᴛᴏ ᴀᴅᴍɪɴ!\n\n"
                f"🎬 <b>{session['query']}</b>\n\n"
                f"ᴡᴇ ᴡɪʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ᴡʜᴇɴ ɪᴛ'ꜱ ᴀᴠᴀɪʟᴀʙʟᴇ.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Suggestion click
    try:
        i = int(idx)
    except ValueError:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if i < 0 or i >= len(session["suggestions"]):
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    suggestion = session["suggestions"][i]
    title = suggestion.get("title") or ""
    year = suggestion.get("year")
    imdb_id = suggestion.get("imdb_id")

    logger.info(f"[SUGGEST] user picked {title!r} ({year})")

    await q.answer(f"🔎 ꜱᴇᴀʀᴄʜɪɴɢ: {title[:30]}")

    # Retry search with corrected title
    norm = _normalize(title)
    docs = await _search_all_shards(norm, year, False)
    if not docs and year:
        docs = await _search_all_shards(norm, None, False)

    if not docs:
        # Still no files → send to request channel
        user_mention = q.from_user.mention if hasattr(q.from_user, "mention") else "user"

        await _post_request_to_channel(
            client, q.from_user.id, user_mention,
            title, year=year, imdb_id=imdb_id,
            source="suggestion_failed",
        )

        try:
            await q.message.edit_text(
                f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"{DIV}\n\n"
                f"😌 <b>{title}</b>" + (f" ({year})" if year else "") + "\n\n"
                f"ɪꜱ ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ ʀɪɢʜᴛ ɴᴏᴡ.\n\n"
                f"📝 ʀᴇǫᴜᴇꜱᴛ ꜱᴇɴᴛ ᴛᴏ ᴀᴅᴍɪɴ.\n"
                f"ᴡᴇ'ʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ᴡʜᴇɴ ɪᴛ'ꜱ ᴀᴠᴀɪʟᴀʙʟᴇ.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK),
                ], [
                    InlineKeyboardButton("❌ CLOSE", callback_data="gclose"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.warning(f"[SUGGEST] edit failed: {e}")
        return

    # Files found → show file list
    raw_buttons = session.get("custom_buttons") or []
    sid = _new_search_session(
        hits=docs,
        user_id=q.from_user.id,
        chat_id=session["chat_id"],
        custom_buttons=raw_buttons,
        query=title,
    )

    user_mention = q.from_user.mention if hasattr(q.from_user, "mention") else "user"
    await _show_file_list(q.message, title, docs, sid, user_mention)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — FILE CLICK CALLBACK
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^gfile:"), group=-999)
async def gfile_callback(client: Client, q: CallbackQuery):
    try:
        parts = q.data.split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        _, sid, idx = parts
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    logger.info(f"[GFILE] user={q.from_user.id} data={q.data!r}")

    session = _get_search_session(sid)
    if not session:
        return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    if idx == "more":
        return await q.answer("ᴜꜱᴇ ꜰɪʀꜱᴛ 10 ʀᴇʟᴇᴀꜱᴇꜱ", show_alert=True)

    try:
        i = int(idx)
    except ValueError:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if i < 0 or i >= len(session["hits"]):
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    try:
        is_group = q.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    except Exception:
        is_group = False

    if is_group:
        try:
            me = await client.get_me()
            deep_link = f"https://t.me/{me.username}?start=file_{sid}_{i}"
            logger.info(f"[GFILE] redirect user={q.from_user.id} → {deep_link}")
            try:
                q.stop_propagation()
            except Exception:
                pass
            await q.answer(url=deep_link)
        except Exception as e:
            logger.exception(f"[GFILE] redirect failed: {e}")
            try:
                await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
            except Exception:
                pass
        return

    # PM delivery
    try:
        await _deliver_file(client, q.from_user.id, session, i)
        await q.answer("✅ ꜱᴇɴᴛ")
    except Exception as e:
        logger.exception(f"[GFILE] PM delivery failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — PM /start HANDLER
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command("start") & filters.private, group=-999)
async def pm_start_handler(client: Client, message: Message):
    logger.info(
        f"[START-PM] ⚡ user={message.from_user.id} text={message.text!r}"
    )

    try:
        if len(message.command) < 2:
            return await _send_welcome(client, message)

        payload = message.command[1]

        if payload.startswith("file_"):
            try:
                _, sid, idx_str = payload.split("_", 2)
                i = int(idx_str)
            except Exception:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ.")

            session = _get_search_session(sid)
            if not session:
                return await message.reply_text(
                    f"⚠️ <b>ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.</b>\n\n"
                    f"ᴘʟᴇᴀꜱᴇ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ.",
                    parse_mode=ParseMode.HTML,
                )

            if i < 0 or i >= len(session["hits"]):
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ.")

            await _deliver_file(client, message.from_user.id, session, i)
            return

        return await _send_welcome(client, message)

    except StopPropagation:
        raise
    except Exception as e:
        logger.exception(f"[START-PM] crashed: {e}")


async def _send_welcome(client: Client, message: Message):
    try:
        await message.reply_text(
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"{DIV}\n\n"
            f"🔎 ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ,\n"
            f"ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ʜᴇʀᴇ.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"[START-PM] welcome failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — FILE DELIVERY
# ═══════════════════════════════════════════════════════════════════════════

async def _deliver_file(client: Client, chat_id: int,
                        session: Dict[str, Any], idx: int):
    try:
        doc = session["hits"][idx]
    except Exception:
        return

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

    kb_rows: List[List[InlineKeyboardButton]] = []
    custom_rows = _build_custom_button_rows(session.get("custom_buttons") or [])
    logger.info(f"[DELIVERY] custom rows: {len(custom_rows)}")
    if custom_rows:
        kb_rows.extend(custom_rows)

    try:
        me = await client.get_me()
        bot_username = me.username or ""
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

    sent = None
    try:
        sent = await client.send_cached_media(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            reply_markup=kb,
        )
        logger.info(
            f"[DELIVERY] ✅ sent to={chat_id} custom_btns={len(custom_rows)}"
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
        try:
            await client.send_message(
                chat_id=chat_id,
                text="❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ꜰɪʟᴇ.",
            )
        except Exception:
            pass
        return

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


async def _auto_delete(client: Client, chat_id: int, msg_id: int,
                       warn_id: Optional[int], seconds: int):
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
# SECTION 15 — REQUEST ACTION CALLBACK (admin → user)
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^greq:"), group=-999)
async def greq_callback(client: Client, q: CallbackQuery):
    """Admin clicked an action button on a request message."""
    try:
        _, token_id, action = q.data.split(":", 2)
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if not _is_bot_owner(q.from_user.id):
        try:
            member = await client.get_chat_member(q.message.chat.id, q.from_user.id)
            st = getattr(member, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)
        except Exception:
            return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)

    req = await _get_request(token_id)
    if not req:
        return await q.answer("⚠️ ʀᴇǫᴜᴇꜱᴛ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or ""

    # Determine user-facing message
    messages = {
        "updated": (
            f"🎬 <b>ɢᴏᴏᴅ ɴᴇᴡꜱ!</b>\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{movie_name}</b> ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ ✅\n\n"
            f"ᴋɪɴᴅʟʏ ꜱᴇᴀʀᴄʜ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ."
        ),
        "notreleased": (
            f"📅 <b>ɴᴏᴛ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ</b>\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{movie_name}</b> ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ.\n"
            f"ᴡᴇ'ʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ᴡʜᴇɴ ɪᴛ'ꜱ ᴀᴠᴀɪʟᴀʙʟᴇ."
        ),
        "notfound": (
            f"🔎 <b>ɴᴏᴛ ꜰᴏᴜɴᴅ</b>\n\n"
            f"ᴡᴇ ᴄᴏᴜʟᴅɴ'ᴛ ꜰɪɴᴅ <b>{movie_name}</b>.\n"
            f"ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ᴛʜᴇ ꜱᴘᴇʟʟɪɴɢ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ."
        ),
        "cancel": (
            f"❌ <b>ʀᴇǫᴜᴇꜱᴛ ᴄᴀɴᴄᴇʟʟᴇᴅ</b>\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{movie_name}</b> ʜᴀꜱ ʙᴇᴇɴ ᴄᴀɴᴄᴇʟʟᴇᴅ ʙʏ ᴀᴅᴍɪɴ."
        ),
    }

    action_icons = {
        "updated": "🎬 MOVIE UPDATED ✅",
        "notreleased": "📅 NOT RELEASED",
        "notfound": "🔎 NOT FOUND",
        "cancel": "❌ CANCELLED",
    }

    # Notify user
    if user_id:
        try:
            await client.send_message(
                chat_id=user_id,
                text=messages.get(action, "✅ ꜱᴛᴀᴛᴜꜱ ᴜᴘᴅᴀᴛᴇᴅ"),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK)],
                ]),
                parse_mode=ParseMode.HTML,
            )
            logger.info(f"[REQ] notified user {user_id} about token {token_id}")
        except UserIsBlocked:
            logger.info(f"[REQ] user {user_id} blocked the bot")
        except Exception as e:
            logger.warning(f"[REQ] DM failed: {e}")

    # Update DB
    await _update_request_status(token_id, action)

    # Update channel message
    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>{action_icons.get(action, '✅ DONE')}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug(f"[REQ] edit failed: {e}")

    await q.answer(f"✅ ᴜꜱᴇʀ ɴᴏᴛɪꜰɪᴇᴅ: {action}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — CLOSE
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(r"^gclose$"), group=-999)
async def gclose_callback(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    try:
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17 — ADMIN COMMANDS
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(filters.command("add_button") & filters.group, group=-999)
async def cmd_add_button(client: Client, message: Message):
    try:
        if not message.from_user:
            return
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
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
                or url.startswith("tg://")
                or url.startswith("t.me/")
                or url.startswith("@")):
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
    except Exception as e:
        logger.exception(f"[ADMIN] add_button crashed: {e}")
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("list_buttons") & filters.group, group=-999)
async def cmd_list_buttons(client: Client, message: Message):
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
                "ᴜꜱᴇ <code>/add_button NAME | URL</code>",
                parse_mode=ParseMode.HTML,
            )

        lines = [f"📦 <b>ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ</b>", DIV, ""]
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
    try:
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
    try:
        if not message.from_user:
            return
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
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
    try:
        if not message.from_user:
            return
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        args = (message.text or "").split()
        if len(args) < 2:
            return await message.reply_text(
                "ᴜꜱᴀɢᴇ: <code>/set_delete_time 600</code> (seconds)\n"
                "ᴇxᴀᴍᴘʟᴇꜱ: 60=1min, 600=10min, 1800=30min",
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
                f"✅ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ɪɴ <b>{secs}ꜱ</b>.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
    except Exception as e:
        await message.reply_text(f"❌ {e}")


@Client.on_message(filters.command("debug_buttons") & filters.group, group=-999)
async def cmd_debug_buttons(client: Client, message: Message):
    try:
        if not message.from_user:
            return
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        coll = _groups_coll()
        if coll is None:
            return await message.reply_text("❌ no DB")

        doc = await coll.find_one({"chat_id": message.chat.id}) or {}
        top = doc.get("result_buttons")
        sub = (doc.get("settings") or {}).get("result_buttons")

        await message.reply_text(
            f"<b>🔍 DEBUG</b>\n\n"
            f"<b>Top-level keys:</b>\n<code>{list(doc.keys())}</code>\n\n"
            f"<b>doc.result_buttons:</b>\n<code>{top!r}</code>\n\n"
            f"<b>doc.settings.result_buttons:</b>\n<code>{sub!r}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18 — BACKGROUND CLEANUP + STARTUP CHECK
# ═══════════════════════════════════════════════════════════════════════════

async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_expired()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def _startup_check():
    try:
        await asyncio.sleep(3)
        db = _get_db()
        if db is not None:
            logger.info("[GROUP-SEARCH] ✅ primary DB ready")
        shards = _media_collections()
        logger.info(f"[GROUP-SEARCH] ✅ {len(shards)} media shards")
        for idx, coll in shards[:5]:
            try:
                n = await coll.estimated_document_count()
                logger.info(f"[GROUP-SEARCH]   shard #{idx} → {n:,} docs")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"[GROUP-SEARCH] startup check failed: {e}")


try:
    loop = asyncio.get_event_loop()
    loop.create_task(_cleanup_loop())
    loop.create_task(_startup_check())
except Exception:
    pass


logger.info("[GROUP-SEARCH] ═══════════════════════════════════════════")
logger.info("[GROUP-SEARCH] ALL HANDLERS REGISTERED ✅")
logger.info("[GROUP-SEARCH] Admin cmds: /add_button /list_buttons")
logger.info("[GROUP-SEARCH]            /remove_button /clear_buttons")
logger.info("[GROUP-SEARCH]            /set_delete_time /debug_buttons")
logger.info("[GROUP-SEARCH] ═══════════════════════════════════════════")
