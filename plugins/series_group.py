# plugins/series_group.py
"""
🎬 DOWNTOWN VILLA — SERIES GROUP (ULTIMATE v13 — FINAL)
"""
import asyncio
import base64
import logging
import os
import re
import secrets
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import MessageNotModified, FloodWait, UserIsBlocked
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
    InputMediaPhoto,
)

from database import db_manager

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

try:
    from core.config import REQST_CHANNEL as _REQST
    REQST_CHANNEL = _REQST
except Exception:
    REQST_CHANNEL = None

try:
    from core.config import UPDATE_CHNL_LNK as _UPD
    UPDATE_CHNL_LNK = _UPD or "https://t.me/"
except Exception:
    UPDATE_CHNL_LNK = "https://t.me/"

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

SERIES_GROUP_ID_RAW = os.getenv("SERIES_GROUP_ID", "0").strip()
try:
    SERIES_GROUP_ID = int(SERIES_GROUP_ID_RAW) or None
except (TypeError, ValueError):
    SERIES_GROUP_ID = None

SERIES_GROUP_ENABLED = os.getenv("SERIES_GROUP_ENABLED", "false").lower() in \
                       ("1", "true", "yes", "on")

SESSION_TTL = 900
PENDING_TTL = 600
DELIVER_BATCH_DELAY = 0.6

DELETE_PRESETS = [
    (0,    "♾️ NEVER"),
    (5,    "⏱️ 5 MIN"),
    (10,   "⏱️ 10 MIN"),
    (15,   "⏱️ 15 MIN"),
    (30,   "⏱️ 30 MIN"),
    (60,   "⏱️ 1 HOUR"),
    (120,  "⏱️ 2 HOURS"),
    (360,  "⏱️ 6 HOURS"),
    (1440, "⏱️ 1 DAY"),
]

DIV = "━" * 26
DIV2 = "─" * 26

QUALITY_RANK = {
    "4320P": 100, "8K": 100, "2160P": 90, "4K": 90, "UHD": 90,
    "1440P": 80, "2K": 80, "1080P": 70, "FULLHD": 70, "FHD": 70,
    "720P": 60, "HD": 60, "576P": 50, "480P": 40, "SD": 40,
    "360P": 30, "240P": 20, "UNKNOWN": 25,
}

DEFAULT_EPISODE_CAPTION = (
    "🎬 <b>{series}</b>\n"
    "📺 <b>Season {season:02d} · Episode {episode:02d}</b>\n"
    "🎯 Quality: <code>{quality}</code>\n"
    "🌍 Language: <code>{language}</code>\n"
    "📦 Size: <code>{size}</code>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

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


class _SafeDict(dict):
    def __missing__(self, key): return ""


def _safe_caption(template: str, ctx: Dict[str, Any], fallback: str) -> str:
    """Format caption safely. Any missing placeholder → empty string."""
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:
        return fallback


def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"

def _fmt_size(b) -> str:
    if not b: return "0 B"
    try: s = float(b)
    except (TypeError, ValueError): return "0 B"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if s < 1024: return f"{s:.2f} {u}"
        s /= 1024
    return f"{s:.2f} PB"

def _esc(t) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception: return False

def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y · %H:%M IST")

def _normalize(s: str) -> str:
    if not s: return ""
    s = s.strip().lower()
    s = re.sub(r"[.\-_/,;:]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()

def _b64e(s: str) -> str:
    try: return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    except Exception: return ""

def _b64d(s: str) -> str:
    try:
        pad = "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode((s + pad).encode()).decode()
    except Exception: return ""


# ═══════════════════════════════════════════════════════════════════════════
# DB
# ═══════════════════════════════════════════════════════════════════════════
def _get_db():
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                d = fn()
                if d is not None: return d
    except Exception: pass
    try: return db_manager._db
    except Exception: return None


def _sgroup_coll():
    d = _get_db()
    return d["series_group"] if d is not None else None


def _req_coll():
    d = _get_db()
    return d["search_requests"] if d is not None else None


async def _get_caption() -> str:
    c = _sgroup_coll()
    if c is None: return DEFAULT_EPISODE_CAPTION
    try:
        doc = await c.find_one({"_id": "caption"}) or {}
        return doc.get("template") or DEFAULT_EPISODE_CAPTION
    except Exception: return DEFAULT_EPISODE_CAPTION


async def _set_caption(template: str) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "caption"},
                           {"$set": {"template": template,
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_buttons() -> List[Dict[str, Any]]:
    c = _sgroup_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"_id": "buttons"}) or {}
        return list(doc.get("list") or [])
    except Exception: return []


async def _set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "buttons"},
                           {"$set": {"list": buttons,
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_delete_minutes() -> int:
    c = _sgroup_coll()
    if c is None: return 10
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return int(doc.get("delete_minutes", 10))
    except Exception: return 10


async def _set_delete_minutes(minutes: int) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {"delete_minutes": int(minutes),
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_fsub_enabled() -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return bool(doc.get("fsub", False))
    except Exception: return False


async def _set_fsub_enabled(enabled: bool) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {"fsub": bool(enabled),
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_series_pref(slug: str) -> Dict[str, Any]:
    c = _sgroup_coll()
    if c is None: return {}
    try:
        return dict(await c.find_one({"title_slug": slug}) or {})
    except Exception: return {}


async def _set_series_pref(slug: str, title: str, qualities: List[str]) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"title_slug": slug},
                           {"$set": {"title_slug": slug, "title": title,
                                     "qualities": list(qualities),
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _list_series_prefs() -> List[Dict[str, Any]]:
    c = _sgroup_coll()
    if c is None: return []
    try:
        cursor = c.find({"title_slug": {"$exists": True}}).sort("updated_at", -1)
        return await cursor.to_list(length=200)
    except Exception: return []


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST RECORD
# ═══════════════════════════════════════════════════════════════════════════
async def _add_request(user_id, title, year, tmdb_id, source):
    c = _req_coll()
    if c is None: return None
    try:
        token = uuid.uuid4().hex[:12]
        await c.insert_one({
            "token_id": token, "user_id": int(user_id),
            "movie_name": title, "query": title,
            "year": year, "tmdb_id": tmdb_id, "kind": "series",
            "source": source, "status": "not_found",
            "created_at": time.time(),
        })
        return token
    except Exception as e:
        logger.warning(f"[SG-REQ] save failed: {e}"); return None


async def _get_request(token):
    c = _req_coll()
    if c is None: return None
    try: return await c.find_one({"token_id": token})
    except Exception: return None


async def _update_request(token, status):
    c = _req_coll()
    if c is None: return False
    try:
        r = await c.update_one({"token_id": token},
                                {"$set": {"status": status,
                                          "updated_at": time.time()}})
        return r.modified_count > 0
    except Exception: return False


async def _post_to_request_channel(client, user_id, title,
                                    year=None, tmdb_id=None,
                                    source="series_search"):
    if not REQST_CHANNEL:
        logger.warning("[SG-REQ] REQST_CHANNEL not set"); return None

    token = await _add_request(user_id, title, year, tmdb_id, source)
    if not token: return None

    try:
        user_obj = await client.get_users(user_id)
        user_mention = getattr(user_obj, "mention", f"user {user_id}")
    except Exception:
        user_mention = f"user {user_id}"

    title_disp = title + (f" ({year})" if year else "")
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📺 <b>{fb('NEW SERIES REQUEST')}</b>",
        DIV, "",
        f"🎬 {sc('series')} · <b>{_esc(title_disp)}</b>",
    ]
    if tmdb_id:
        lines.append(f"🎯 {sc('tmdb')} · <code>{tmdb_id}</code>")
    lines += [
        "", f"👤 {sc('user')} · {user_mention}",
        f"🆔 {sc('id')} · <code>{user_id}</code>",
        "", f"🔑 {sc('token')} · <code>{token}</code>",
        DIV, "",
        f"<i>ᴀᴅᴍɪɴ · ᴄʜᴏᴏꜱᴇ ᴀɴ ᴀᴄᴛɪᴏɴ ʙᴇʟᴏᴡ</i>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📺 SERIES UPDATED",
                               callback_data=f"gsreq:{token}:updated")],
        [InlineKeyboardButton("📅 NOT RELEASED",
                               callback_data=f"gsreq:{token}:notreleased"),
         InlineKeyboardButton("🔎 NOT FOUND",
                               callback_data=f"gsreq:{token}:notfound")],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=f"gsreq:{token}:cancel")],
    ])

    try:
        await client.send_message(
            chat_id=REQST_CHANNEL, text="\n".join(lines),
            reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
        logger.info(f"[SG-REQ] posted token={token} title={title!r}")
        return token
    except Exception as e:
        logger.warning(f"[SG-REQ] post failed: {e}"); return None


# ═══════════════════════════════════════════════════════════════════════════
# PENDING + TASKS + SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_PENDING: Dict[str, Dict[str, Any]] = {}
_BACKGROUND_TASKS: Set[asyncio.Task] = set()


def _pending_put(uid: int, chosen: Dict, files: List[Dict]) -> str:
    token = secrets.token_urlsafe(10)
    _PENDING[token] = {
        "user_id": uid, "chosen": dict(chosen), "files": list(files),
        "created": time.time(), "expires": time.time() + PENDING_TTL,
    }
    logger.info(f"[SG-PENDING] created {token} user={uid} files={len(files)}")
    return token


def _pending_get(token: str) -> Optional[Dict[str, Any]]:
    p = _PENDING.get(token)
    if not p: return None
    if time.time() > p["expires"]:
        _PENDING.pop(token, None); return None
    return p


def _pending_cleanup():
    now = time.time()
    for t in list(_PENDING.keys()):
        if _PENDING[t]["expires"] < now:
            _PENDING.pop(t, None)


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(uid, **data) -> str:
    sid = secrets.token_urlsafe(6)[:8]
    _SESSIONS[uid] = {"sid": sid, "data": data,
                      "expires": time.time() + SESSION_TTL}
    return sid


def _get_session(uid):
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s


def _clear_session(uid):
    _SESSIONS.pop(uid, None)


def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# DEDUPE
# ═══════════════════════════════════════════════════════════════════════════
def _dedupe_by_episode(files):
    if not files: return []
    seen_ids: Set[str] = set()
    by_id = []
    for f in files:
        fid = str(f.get("file_id") or f.get("file_unique_id") or "")
        if fid and fid in seen_ids: continue
        if fid: seen_ids.add(fid)
        by_id.append(f)

    def _size(f):
        s = f.get("file_size") or 0
        try: return int(s)
        except (TypeError, ValueError): return 0

    by_id.sort(key=_size, reverse=True)

    seen_keys: Set[Tuple] = set()
    out = []
    for f in by_id:
        s = f.get("season"); e = f.get("episode")
        if e is None:
            p = _parse_filename_light(f.get("file_name") or "")
            if p.get("episode") is not None:
                e = p["episode"]; f["episode"] = e
            if p.get("season") is not None and s is None:
                s = p["season"]; f["season"] = s
        q = (f.get("quality") or "UNKNOWN").upper().strip()
        key = (s, e, q)
        if key in seen_keys: continue
        seen_keys.add(key)
        out.append(f)

    out.sort(key=lambda x: (
        x.get("season") or 0,
        x.get("episode") if x.get("episode") is not None else 9999))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ENGINE SEARCH
# ═══════════════════════════════════════════════════════════════════════════
async def _engine_search(title, season=None, language=None, quality=None):
    try:
        from media_search.engine import engine
        from media_search.normalizer import normalize
    except Exception as e:
        logger.exception(f"[SG] engine import failed: {e}"); return []

    all_files = []
    try:
        norm = normalize(title)
        result = await engine.search_series(norm)
        hits = result.hits
        if not hits:
            result = await engine.search_any(norm)
            hits = result.hits

        logger.info(f"[SG] engine: {len(hits)} hits for {norm!r}")

        for h in hits:
            h_season = getattr(h, "season", None)
            h_episode = getattr(h, "episode", None)
            h_quality = getattr(h, "quality", None)
            h_langs = list(getattr(h, "audio_languages", []) or [])
            file_name = getattr(h, "file_name", "") or ""

            if h_season is None or h_episode is None or not h_quality or not h_langs:
                p = _parse_filename_light(file_name)
                if h_season is None: h_season = p.get("season")
                if h_episode is None: h_episode = p.get("episode")
                if not h_quality: h_quality = p.get("quality")
                if not h_langs: h_langs = p.get("languages") or []

            if season is not None and h_season != season: continue
            if language:
                ll = language.lower()
                hl = [l.lower() for l in h_langs]
                if hl and not any(ll in l or l in ll for l in hl): continue
            if quality and h_quality:
                if h_quality.upper() != quality.upper(): continue

            all_files.append({
                "file_hit": h,
                "file_id": getattr(h, "file_id", "") or "",
                "file_unique_id": getattr(h, "file_unique_id", None),
                "file_name": file_name,
                "file_size": getattr(h, "file_size", 0) or 0,
                "season": h_season,
                "episode": h_episode,
                "quality": (h_quality or "UNKNOWN"),
                "languages": h_langs,
                "title": getattr(h, "title", "") or "",
                "series_title": getattr(h, "series_title", None) or "",
                "chat_id": getattr(h, "chat_id", None),
                "message_id": getattr(h, "message_id", None) or
                              getattr(h, "msg_id", None),
            })
    except Exception as e:
        logger.exception(f"[SG] engine search failed: {e}")

    return _dedupe_by_episode(all_files)


async def _smart_db_search(title):
    norm = _normalize(title)
    if not norm: return None
    words = norm.split()
    for i in range(len(words), max(0, len(words) - 4), -1):
        partial = " ".join(words[:i])
        hits = await _engine_search(partial)
        if hits:
            matched = hits[0].get("series_title") or hits[0].get("title") or partial
            logger.info(f"[SG] smart: {title!r} → {matched!r} ({len(hits)})")
            return {"matched_title": matched, "hits": hits}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# LIGHT PARSER
# ═══════════════════════════════════════════════════════════════════════════
_SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]
_SEASON_ONLY = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]
_QUALITY_MARKERS = [
    ("4320p", "4320P"), ("2160p", "2160P"), ("4k", "4K"), ("uhd", "UHD"),
    ("1440p", "1440P"), ("1080p", "1080P"), ("fullhd", "1080P"), ("fhd", "1080P"),
    ("720p", "720P"), ("576p", "576P"), ("480p", "480P"), ("360p", "360P"),
]
_LANG_ALIASES = {
    "English": ["english", "eng"], "Hindi": ["hindi", "hin"],
    "Tamil": ["tamil", "tam"], "Telugu": ["telugu", "tel"],
    "Malayalam": ["malayalam", "mal"], "Kannada": ["kannada", "kan"],
    "Bengali": ["bengali", "bangla"], "Marathi": ["marathi"],
    "Punjabi": ["punjabi"], "Korean": ["korean"], "Japanese": ["japanese"],
    "Chinese": ["chinese", "mandarin"], "Spanish": ["spanish"],
    "French": ["french"], "German": ["german"], "Italian": ["italian"],
    "Portuguese": ["portuguese"], "Russian": ["russian"], "Turkish": ["turkish"],
    "Arabic": ["arabic"], "Thai": ["thai"],
}


def _parse_filename_light(filename):
    out = {"season": None, "episode": None, "quality": None, "languages": []}
    if not filename: return out
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts)$", "", name, flags=re.I)
    wl = name.lower()

    for pat in _SE_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                out["season"] = int(m.group(1))
                out["episode"] = int(m.group(2)); break
            except Exception: continue
    if out["season"] is None:
        for pat in _SEASON_ONLY:
            m = pat.search(name)
            if m:
                try: out["season"] = int(m.group(1)); break
                except Exception: continue

    for marker, label in _QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", wl):
            out["quality"] = label; break

    langs = []
    for ln, aliases in _LANG_ALIASES.items():
        for a in aliases:
            if re.search(r"\b" + re.escape(a) + r"\b", wl):
                if ln not in langs: langs.append(ln)
                break
    out["languages"] = langs
    return out


# ═══════════════════════════════════════════════════════════════════════════
# TMDB
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_get(path, params=None):
    if not TMDB_API_KEY: return None
    try:
        import aiohttp
    except ImportError: return None
    p = {"api_key": TMDB_API_KEY, "language": "en-US", **(params or {})}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.themoviedb.org/3{path}",
                                params=p, timeout=12) as r:
                if r.status != 200: return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[SG] tmdb: {e}"); return None


async def _tmdb_search_series(query):
    data = await _tmdb_get("/search/tv", {"query": query, "include_adult": "false"})
    if not data: return []
    out = []
    for it in (data.get("results") or [])[:8]:
        title = it.get("name") or it.get("original_name") or ""
        if not title: continue
        date = it.get("first_air_date") or ""
        out.append({
            "tmdb_id": it.get("id"), "title": title,
            "year": (date or "")[:4],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
        })
    return out


async def _tmdb_series_details(tmdb_id):
    return await _tmdb_get(f"/tv/{tmdb_id}", {})


def _tmdb_languages(details):
    langs = set()
    orig = (details.get("original_language") or "").lower()
    if orig: langs.add(orig)
    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code: langs.add(code)
    m = {"en":"English","hi":"Hindi","ta":"Tamil","te":"Telugu","ml":"Malayalam",
         "kn":"Kannada","bn":"Bengali","mr":"Marathi","pa":"Punjabi",
         "gu":"Gujarati","ur":"Urdu","ko":"Korean","ja":"Japanese",
         "zh":"Chinese","es":"Spanish","fr":"French","de":"German",
         "it":"Italian","pt":"Portuguese","ru":"Russian","tr":"Turkish",
         "ar":"Arabic","th":"Thai"}
    named = [m[c] for c in langs if c in m]
    named.sort(key=lambda x: (x != "English", x))
    return named or ["English"]


def _tmdb_seasons(details):
    out = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0: continue
        out.append({
            "season": sn,
            "episodes": s.get("episode_count", 0),
            "year": (s.get("air_date") or "")[:4],
        })
    out.sort(key=lambda x: x["season"])
    return out


def _poster_url(path, size="w500"):
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


def _summarize(files):
    qualities: Set[str] = set()
    languages: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)
    for f in files:
        q = f.get("quality") or "UNKNOWN"
        if q != "UNKNOWN": qualities.add(q)
        for l in (f.get("languages") or []): languages.add(l)
        s = f.get("season"); e = f.get("episode")
        if s is not None: seasons[s].add(e if e is not None else 0)
    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "languages": sorted(languages),
        "seasons": {s: sorted(eps) for s, eps in seasons.items()},
        "total_files": len(files),
    }


# ═══════════════════════════════════════════════════════════════════════════
# RENDER
# ═══════════════════════════════════════════════════════════════════════════
async def _render(client, chat_id, msg_id, text, kb, poster=None):
    if poster:
        try:
            await client.edit_message_media(
                chat_id=chat_id, message_id=msg_id,
                media=InputMediaPhoto(media=poster, caption=text,
                                       parse_mode=ParseMode.HTML),
                reply_markup=kb)
            return True
        except Exception as e:
            logger.debug(f"[SG] edit_media: {e}")
        try: await client.delete_messages(chat_id, msg_id)
        except Exception: pass
        try:
            await client.send_photo(chat_id=chat_id, photo=poster,
                                     caption=text, reply_markup=kb,
                                     parse_mode=ParseMode.HTML)
            return True
        except Exception as e:
            logger.warning(f"[SG] send_photo: {e}")
            try:
                await client.send_message(chat_id=chat_id, text=text,
                                           reply_markup=kb,
                                           parse_mode=ParseMode.HTML,
                                           disable_web_page_preview=True)
                return True
            except Exception: return False

    try:
        await client.edit_message_text(chat_id=chat_id, message_id=msg_id,
                                        text=text, reply_markup=kb,
                                        parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.debug(f"[SG] edit_text: {e}")
        try:
            await client.send_message(chat_id=chat_id, text=text,
                                       reply_markup=kb,
                                       parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)
            return True
        except Exception: return False


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_suggestions(items):
    """Buttons: NAME IN CAPS + ⭐ rating."""
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating", 0)
        if len(title) > 42:
            title = title[:41] + "…"
        label = title
        if rating:
            label += f" ⭐{rating:.1f}"
        rows.append([InlineKeyboardButton(label, callback_data=f"sg:pick:{i}")])
    rows.append([InlineKeyboardButton("📩 REQUEST TO ADMIN",
                                       callback_data="sg:request")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_languages(langs, local_langs):
    rows = []; row = []
    for i, lang in enumerate(langs[:12]):
        has = "🟢" if lang in local_langs else "⚪"
        row.append(InlineKeyboardButton(f"{has} {lang}",
                                          callback_data=f"sg:lang:{i}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_sugg"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(seasons, local):
    rows = []
    for i, s in enumerate(seasons[:15]):
        sn = s["season"]; eps = s.get("episodes", 0)
        local_eps = local.get(sn, [])
        if local_eps:
            count = len([e for e in local_eps if e > 0])
            mark = "🟢" if count >= eps else "🟡"
        else:
            count = 0; mark = "⚪"
        label = f"{mark} S{sn:02d} · {eps} ᴇᴘ"
        if count: label += f" · {count} ʟᴏᴄᴀʟ"
        rows.append([InlineKeyboardButton(label, callback_data=f"sg:seas:{i}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_lang"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_qualities(qualities):
    rows = []; row = []
    for i, q in enumerate(qualities[:12]):
        row.append(InlineKeyboardButton(f"🎯 {q}",
                                          callback_data=f"sg:qual:{i}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_seas"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# VIEWS
# ═══════════════════════════════════════════════════════════════════════════
def _view_suggestions(raw, items):
    """Suggestions list: NAME IN CAPS + ⭐ rating."""
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES SUGGESTIONS')}</b>",
        DIV, "",
        f"🔍 {sc('you searched')} · <code>{_esc(raw)}</code>",
        "", f"📌 {sc('pick the series you meant')}",
        "", DIV2, "",
    ]
    for i, it in enumerate(items, 1):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating", 0)
        line = f"<b>{i}.</b> <b>{_esc(title)}</b>"
        if rating:
            line += f" · ⭐ {rating:.1f}"
        lines.append(line)
    lines += ["", DIV2,
              f"💡 {sc('not what you wanted?')} · ᴛᴀᴘ ʀᴇǫᴜᴇꜱᴛ ʙᴜᴛᴛᴏɴ"]
    return "\n".join(lines)


def _view_languages(title, year):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b> ({year})",
        DIV, "", f"🌍 {sc('pick language')}",
        "", f"🟢 {sc('has files')} · ⚪ {sc('tmdb only')}",
    ])


def _view_seasons(title, year):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b> ({year})",
        DIV, "", f"📺 {sc('pick season')}",
        "", f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ɴᴏ ꜰɪʟᴇꜱ",
    ])


def _view_qualities(title, season, count):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {season:02d}</b>",
        DIV, "", f"🎯 {sc('pick quality')}",
        "", f"📁 <code>{count}</code> ꜰɪʟᴇꜱ ᴛᴏ ꜱᴇɴᴅ",
        f"📩 {sc('files will go to your pm')}",
    ])


def _view_redirecting(title, season, quality, count):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('REDIRECTING TO PM')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {season:02d}</b>",
        f"🎯 <code>{quality}</code>",
        "", f"📁 <code>{count}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
        "", f"📌 {sc('bot will open in pm')}",
        f"📌 {sc('files will be delivered there')}",
    ])


# ═══════════════════════════════════════════════════════════════════════════
# FORCE SUB CHECK
# ═══════════════════════════════════════════════════════════════════════════
async def _check_fsub(client, user_id) -> Tuple[bool, List[int]]:
    if not await _get_fsub_enabled():
        return True, []
    try:
        from media_search.subscription import subscription
        ok, missing = await subscription.is_subscribed(client, user_id)
        return bool(ok), list(missing or [])
    except Exception as e:
        logger.debug(f"[SG-FSUB] check failed: {e}")
        return True, []


def _kb_fsub(missing_ids):
    rows = []
    for ch in missing_ids[:5]:
        try:
            cid = str(ch).replace("-100", "").replace("-", "")
            url = f"https://t.me/c/{cid}/1"
        except Exception:
            url = "https://t.me/"
        rows.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=url)])
    rows.append([InlineKeyboardButton("🔄 CHECK AGAIN",
                                       callback_data="sg:fsub_check")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# GROUP SEARCH
# ═══════════════════════════════════════════════════════════════════════════
if SERIES_GROUP_ID and SERIES_GROUP_ENABLED:
    @Client.on_message(
        filters.chat(SERIES_GROUP_ID) & filters.text & ~filters.regex(r"^/"),
        group=-9999)
    async def series_group_search(client, message):
        try:
            txt = (message.text or "").strip()
            if len(txt) < 2 or len(txt) > 80: return
            if not message.from_user: return
            if "http" in txt.lower(): return

            try: message.stop_propagation()
            except Exception: pass

            uid = message.from_user.id
            logger.info(f"[SG] search: {txt!r} from {uid}")

            try:
                status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
            except Exception: return

            db_match = await _smart_db_search(txt)
            if db_match:
                matched_title = db_match["matched_title"]
                hits = db_match["hits"]
                logger.info(f"[SG] DB: {matched_title!r} ({len(hits)})")

                tmdb_results = await _tmdb_search_series(matched_title)
                if not tmdb_results:
                    tmdb_results = await _tmdb_search_series(txt)

                tmdb_langs = ["English"]; tmdb_seasons = []
                poster = None; year = ""; tmdb_id = None

                if tmdb_results:
                    ch = tmdb_results[0]
                    tmdb_id = ch.get("tmdb_id")
                    details = await _tmdb_series_details(tmdb_id)
                    if details:
                        tmdb_langs = _tmdb_languages(details)
                        tmdb_seasons = _tmdb_seasons(details)
                    poster = ch.get("poster")
                    year = ch.get("year") or ""

                display_title = matched_title
                if tmdb_results and tmdb_results[0].get("title"):
                    display_title = tmdb_results[0]["title"]

                _new_session(uid, suggestions=[], raw_query=txt)
                s = _SESSIONS[uid]
                summary = _summarize(hits)
                s["data"]["chosen"] = {
                    "tmdb_id": tmdb_id, "title": display_title,
                    "year": year, "poster": poster,
                    "tmdb_langs": tmdb_langs, "tmdb_seasons": tmdb_seasons,
                    "local_langs": summary["languages"],
                    "local_seasons": summary["seasons"],
                }
                await _render_languages(client, message.chat.id, status.id, uid)
                return

            results = await _tmdb_search_series(txt)
            if not results:
                await _handle_no_results(client, message, status, txt)
                return

            _new_session(uid, suggestions=results, raw_query=txt)
            await _render(client, message.chat.id, status.id,
                           _view_suggestions(txt, results),
                           kb_suggestions(results), None)
        except Exception as e:
            logger.exception(f"[SG] group search: {e}")


async def _render_languages(client, chat_id, msg_id, uid):
    s = _get_session(uid)
    if not s: return
    c = s["data"].get("chosen") or {}
    if not c: return
    tmdb_langs = c.get("tmdb_langs") or ["English"]
    local_langs = c.get("local_langs") or []
    ordered = [l for l in tmdb_langs if l in local_langs] + \
              [l for l in tmdb_langs if l not in local_langs]
    c["ordered_langs"] = ordered
    text = _view_languages(c.get("title"), c.get("year"))
    kb = kb_languages(ordered, local_langs)
    poster = _poster_url(c.get("poster"), "w500")
    await _render(client, chat_id, msg_id, text, kb, poster)


async def _handle_no_results(client, message, status, raw):
    try:
        await client.edit_message_text(
            chat_id=message.chat.id, message_id=status.id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🔎 <b>{fb('NOT FOUND')}</b>",
                DIV, "", f"🎬 <code>{_esc(raw)}</code>",
                "", f"📌 {sc('no match in db')}",
                f"📌 {sc('no match on tmdb')}",
                "", DIV2, "",
                f"📩 {sc('sending request to admin')}...",
            ]), parse_mode=ParseMode.HTML)

        token = await _post_to_request_channel(
            client, message.from_user.id, raw, source="series_no_match")

        if token:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=status.id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('REQUEST SENT')}</b>",
                    DIV, "", f"🎬 <b>{_esc(raw)}</b>",
                    "", f"📌 {sc('admin will review soon')}",
                    f"📌 {sc('you will be notified in pm')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")]]),
                parse_mode=ParseMode.HTML)
        else:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=status.id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NOT FOUND')}</b>",
                    DIV, "", f"🎬 <code>{_esc(raw)}</code>",
                    "", f"📌 {sc('try a different name')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")]]),
                parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[SG] no results: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:pick:(\d+)$"), group=-9999)
async def cb_pick(client, q):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = _get_session(uid)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        items = s["data"].get("suggestions") or []
        if idx >= len(items):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = items[idx]
        tmdb_id = chosen.get("tmdb_id")
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""

        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")

        local_files = await _engine_search(title)
        logger.info(f"[SG] pick: {title!r} → {len(local_files)} files")

        if not local_files:
            token = await _post_to_request_channel(
                client, uid, title, year=year or None,
                tmdb_id=tmdb_id, source="suggestion_not_in_db")
            if token:
                await _render(client, q.message.chat.id, q.message.id,
                    "\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"📩 <b>{fb('REQUEST SENT')}</b>",
                        DIV, "", f"🎬 <b>{_esc(title)}</b> ({year})",
                        "", f"📌 {sc('not in our db')}",
                        f"📌 {sc('admin will review your request')}",
                    ]),
                    InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ CLOSE",
                                              callback_data="sg:close")]]), None)
                return
            await _render(client, q.message.chat.id, q.message.id,
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NOT IN DB')}</b>",
                    DIV, "", f"🎬 <b>{_esc(title)}</b> ({year})",
                    "", f"📌 {sc('not available right now')}",
                ]),
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close")]]), None)
            return

        details = await _tmdb_series_details(tmdb_id)
        tmdb_langs = _tmdb_languages(details) if details else ["English"]
        tmdb_seasons = _tmdb_seasons(details) if details else []
        summary = _summarize(local_files)

        s["data"]["chosen"] = {
            "tmdb_id": tmdb_id, "title": title, "year": year,
            "poster": chosen.get("poster"),
            "tmdb_langs": tmdb_langs, "tmdb_seasons": tmdb_seasons,
            "local_langs": summary["languages"],
            "local_seasons": summary["seasons"],
        }
        await _render_languages(client, q.message.chat.id, q.message.id, uid)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] pick: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^sg:request$"), group=-9999)
async def cb_request(client, q):
    try:
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        raw = s["data"].get("raw_query") or ""
        await q.answer("📩 ꜱᴇɴᴅɪɴɢ...")
        token = await _post_to_request_channel(
            client, q.from_user.id, raw, source="series_manual_request")
        if token:
            await _render(client, q.message.chat.id, q.message.id,
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('REQUEST SENT')}</b>",
                    DIV, "", f"🎬 <b>{_esc(raw)}</b>", "",
                    f"📌 {sc('admin will review soon')}",
                ]),
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close")]]), None)
    except Exception as e:
        logger.exception(f"[SG] request: {e}")


@Client.on_callback_query(filters.regex(r"^sg:lang:(\d+)$"), group=-9999)
async def cb_lang(client, q):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = _get_session(uid)
        if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        c = s["data"].get("chosen") or {}
        ordered = c.get("ordered_langs") or []
        if idx >= len(ordered):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        lang = ordered[idx]
        c["selected_language"] = lang
        await q.answer(f"🌍 {lang}")

        files = await _engine_search(c.get("title") or "", language=lang)
        c["files_by_lang"] = files
        summary = _summarize(files)
        c["seasons_for_lang"] = summary["seasons"]
        logger.info(f"[SG] lang {lang}: {len(files)} files")

        seasons = c.get("tmdb_seasons") or []
        await _render(client, q.message.chat.id, q.message.id,
                       _view_seasons(c.get("title"), c.get("year")),
                       kb_seasons(seasons, summary["seasons"]), None)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] lang: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^sg:seas:(\d+)$"), group=-9999)
async def cb_seas(client, q):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = _get_session(uid)
        if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        c = s["data"].get("chosen") or {}
        seasons = c.get("tmdb_seasons") or []
        if idx >= len(seasons):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        season = seasons[idx]["season"]
        c["selected_season"] = season
        await q.answer(f"📺 Season {season:02d}")

        lang = c.get("selected_language")
        files = await _engine_search(c.get("title") or "",
                                      language=lang, season=season)
        c["files_by_season"] = files
        logger.info(f"[SG] S{season} ({lang}): {len(files)}")

        qualities = sorted({f["quality"] for f in files
                             if f.get("quality") not in (None, "UNKNOWN")},
                            key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)

        slug = re.sub(r"[^a-z0-9]+", "_",
                       (c.get("title") or "").lower()).strip("_")
        pref = await _get_series_pref(slug)
        admin_quals = pref.get("qualities") or []

        if admin_quals:
            final_quals = [x for x in admin_quals if x in qualities] or admin_quals
        else:
            final_quals = qualities

        if not final_quals:
            fallback = sorted({f["quality"] for f in files
                               if f.get("quality")}, reverse=True)
            if fallback: final_quals = fallback
            else:
                return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ", show_alert=True)

        c["available_qualities"] = final_quals
        await _render(client, q.message.chat.id, q.message.id,
                       _view_qualities(c.get("title"), season, len(files)),
                       kb_qualities(final_quals), None)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] seas: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# QUALITY CLICK → REDIRECT TO PM
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:qual:(\d+)$"), group=-9999)
async def cb_qual(client, q):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = _get_session(uid)
        if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        c = s["data"].get("chosen") or {}
        quals = c.get("available_qualities") or []
        if idx >= len(quals):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        quality = quals[idx]
        c["selected_quality"] = quality

        files = [f for f in (c.get("files_by_season") or [])
                 if (f.get("quality") or "").upper() == quality.upper()
                 or (f.get("quality") == "UNKNOWN")]
        files = _dedupe_by_episode(files)
        files.sort(key=lambda x: (x.get("episode") or 0))

        logger.info(f"[SG] qual {quality}: {len(files)} → {uid}")

        if not files:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ", show_alert=True)

        ok_fsub, missing = await _check_fsub(client, uid)
        if not ok_fsub:
            await _render(client, q.message.chat.id, q.message.id,
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"⚠️ <b>{fb('JOIN CHANNELS FIRST')}</b>",
                    DIV, "",
                    f"📌 {sc('please join the channels below')}",
                    f"📌 {sc('then try again')}",
                ]),
                _kb_fsub(missing), None)
            return await q.answer("⚠️ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟꜱ ꜰɪʀꜱᴛ", show_alert=True)

        token = _pending_put(uid, c, files)

        me = await client.get_me()
        bot_username = me.username or "Downtown_Villa_The_Ultimate_Bot"
        deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"

        await _render(client, q.message.chat.id, q.message.id,
                       _view_redirecting(c.get("title") or "?",
                                          c.get("selected_season") or 0,
                                          quality, len(files)),
                       InlineKeyboardMarkup([[
                           InlineKeyboardButton("🚀 OPEN BOT PM",
                                                 url=deep_link)]]),
                       None)

        await q.answer(url=deep_link)
        logger.info(f"[SG] redirected {uid} to PM · token={token}")

    except Exception as e:
        logger.exception(f"[SG] qual: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^sg:fsub_check$"), group=-9999)
async def cb_fsub_check(client, q):
    try:
        ok, missing = await _check_fsub(client, q.from_user.id)
        if ok:
            await q.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ! ᴛʀʏ ᴀɢᴀɪɴ", show_alert=True)
            try: await q.message.delete()
            except Exception: pass
        else:
            await q.answer("❌ ꜱᴛɪʟʟ ᴍɪꜱꜱɪɴɢ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
    except Exception as e:
        logger.debug(f"[SG] fsub_check: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PM /start HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command("start") & filters.private, group=-9999)
async def pm_start_handler(client, message):
    try:
        uid = message.from_user.id if message.from_user else None
        if not uid: return

        logger.info(f"[SG-PM] /start from {uid} text={message.text!r}")

        if len(message.command) < 2:
            await message.reply_text(
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    DIV, "",
                    f"📌 {sc('search for series in the series group')}",
                    f"📌 {sc('files will arrive here in pm')}",
                ]),
                parse_mode=ParseMode.HTML)
            return

        payload = message.command[1]

        if payload.startswith("deliver_"):
            token = payload[8:]
            pending = _pending_get(token)

            if not pending:
                await message.reply_text(
                    "\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"⚠️ <b>{fb('SESSION EXPIRED')}</b>",
                        DIV, "",
                        f"📌 {sc('please search again in the group')}",
                    ]),
                    parse_mode=ParseMode.HTML)
                return

            if pending["user_id"] != uid:
                await message.reply_text("❌ ᴛʜɪꜱ ʟɪɴᴋ ɪꜱ ɴᴏᴛ ꜰᴏʀ ʏᴏᴜ.")
                return

            _PENDING.pop(token, None)

            files = pending["files"]
            chosen = pending["chosen"]
            logger.info(f"[SG-PM] delivering {len(files)} files "
                        f"for {chosen.get('title')!r} to {uid}")

            delete_min = await _get_delete_minutes()
            _spawn(_deliver_episodes(client, uid, chosen, files,
                                      delete_minutes=delete_min))
            return

        await message.reply_text(
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                DIV, "",
                f"📌 {sc('search for series in the series group')}",
                f"📌 {sc('files will arrive here in pm')}",
            ]),
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[SG-PM] start: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ⭐⭐ DELIVERY — uses CUSTOM caption + CUSTOM buttons ⭐⭐
# ═══════════════════════════════════════════════════════════════════════════
async def _deliver_episodes(client, user_id, chosen, files,
                             group_chat_id=None, group_msg_id=None,
                             delete_minutes: int = 10):
    try:
        logger.info(f"[SG-DELIVER] ═══ START user={user_id} files={len(files)} "
                    f"delete={delete_minutes}min ═══")

        # Intro to PM
        try:
            await client.send_message(
                chat_id=user_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"📤 <b>{fb('DELIVERING')}</b>",
                    DIV, "",
                    f"🎬 <b>{_esc(chosen.get('title'))}</b>",
                    f"📺 Season {chosen.get('selected_season'):02d}",
                    f"🎯 <code>{chosen.get('selected_quality')}</code>",
                    f"🌍 <code>{chosen.get('selected_language')}</code>",
                    "", f"📁 <code>{len(files)}</code> episodes",
                ]),
                parse_mode=ParseMode.HTML)
            logger.info(f"[SG-DELIVER] ✅ intro → {user_id}")
        except UserIsBlocked:
            logger.warning(f"[SG-DELIVER] ❌ user {user_id} blocked")
            if group_chat_id and group_msg_id:
                try:
                    me = await client.get_me()
                    await client.edit_message_text(
                        chat_id=group_chat_id, message_id=group_msg_id,
                        text="\n".join([
                            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                            f"⚠️ <b>{fb('START THE BOT FIRST')}</b>",
                            DIV, "",
                            f"📌 {sc('open the bot in pm and tap start')}",
                            f"📌 {sc('then try again here')}",
                        ]),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🚀 START BOT",
                                url=f"https://t.me/{me.username}?start=start")]]),
                        parse_mode=ParseMode.HTML)
                except Exception: pass
            return
        except Exception as e:
            logger.exception(f"[SG-DELIVER] ❌ intro failed: {e}")
            return

        # Load CUSTOM caption + buttons
        template = await _get_caption()
        custom_buttons = await _get_buttons()
        custom_kb = _build_extra_kb(custom_buttons)
        logger.info(f"[SG-DELIVER] caption len={len(template)} "
                    f"buttons={len(custom_buttons)}")

        sent_ids: List[int] = []
        sent = 0; failed = 0

        for i, f in enumerate(files):
            ep = f.get("episode")
            size = _fmt_size(f.get("file_size", 0))
            title_str = chosen.get("title") or "?"
            season_n = chosen.get("selected_season") or 0
            quality_s = chosen.get("selected_quality") or ""
            lang_s = chosen.get("selected_language") or ""

            # ── BUILD CAPTION (custom template, safe format) ──
            ctx = {
                "series": title_str,
                "title": title_str,
                "season": season_n,
                "episode": ep or 0,
                "quality": quality_s,
                "language": lang_s,
                "lang": lang_s,
                "size": size,
                "file_size": size,
                "file_name": f.get("file_name") or "",
                "rating": "—",
                "year": chosen.get("year") or "—",
                "file_caption": title_str,
            }
            fallback = (f"🎬 <b>{_esc(title_str)}</b>\n"
                        f"📺 S{season_n:02d}E{ep or 0:02d} · "
                        f"<code>{quality_s}</code>")
            caption = _safe_caption(template, ctx, fallback)

            fh = f.get("file_hit")
            fid = f.get("file_id")
            if not fid and fh:
                fid = getattr(fh, "file_id", "") or ""

            src_chat = f.get("chat_id")
            src_msg = f.get("message_id")
            if fh:
                if not src_chat:
                    src_chat = getattr(fh, "chat_id", None)
                if not src_msg:
                    src_msg = getattr(fh, "message_id", None) or \
                              getattr(fh, "msg_id", None)

            logger.info(f"[SG-DELIVER] [{i+1}/{len(files)}] ep={ep} "
                        f"fid={'Y' if fid else 'N'} "
                        f"src={'Y' if (src_chat and src_msg) else 'N'}")

            sent_msg = None
            success = False

            # ── METHOD 1: send_cached_media with OUR caption + OUR buttons ──
            if not success and fid:
                try:
                    sent_msg = await client.send_cached_media(
                        chat_id=user_id, file_id=fid,
                        caption=caption, reply_markup=custom_kb,
                        parse_mode=ParseMode.HTML)
                    success = True; sent += 1
                    if sent_msg and sent_msg.id:
                        sent_ids.append(sent_msg.id)
                    logger.info(f"[SG-DELIVER] ✅ M1 (cached) ep={ep}")
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                    try:
                        sent_msg = await client.send_cached_media(
                            chat_id=user_id, file_id=fid,
                            caption=caption, reply_markup=custom_kb,
                            parse_mode=ParseMode.HTML)
                        success = True; sent += 1
                        if sent_msg and sent_msg.id:
                            sent_ids.append(sent_msg.id)
                        logger.info(f"[SG-DELIVER] ✅ M1 after wait ep={ep}")
                    except Exception as e2:
                        logger.warning(f"[SG-DELIVER] M1 retry fail: {e2}")
                except Exception as e:
                    logger.warning(f"[SG-DELIVER] M1 fail: "
                                   f"{type(e).__name__}: {e}")

            # ── METHOD 2: copy_message from source ──
            if not success and src_chat and src_msg:
                try:
                    sent_msg = await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=src_chat, message_id=src_msg,
                        caption=caption, reply_markup=custom_kb,
                        parse_mode=ParseMode.HTML)
                    success = True; sent += 1
                    if sent_msg and sent_msg.id:
                        sent_ids.append(sent_msg.id)
                    logger.info(f"[SG-DELIVER] ✅ M2 (copy) ep={ep}")
                except Exception as e:
                    logger.warning(f"[SG-DELIVER] M2 fail: "
                                   f"{type(e).__name__}: {e}")

            # ── METHOD 3: media_search.delivery (LAST RESORT — uses its own caption) ──
            if not success and fh:
                try:
                    from media_search.delivery import delivery as _d
                    ok_d, err = await _d.send_file(client, user_id, fh)
                    if ok_d:
                        success = True; sent += 1
                        logger.info(f"[SG-DELIVER] ✅ M3 (delivery fallback) ep={ep}")
                except Exception as e:
                    logger.warning(f"[SG-DELIVER] M3 fail: "
                                   f"{type(e).__name__}: {e}")

            if not success:
                failed += 1
                logger.error(f"[SG-DELIVER] ❌ ALL FAILED ep={ep}")

            await asyncio.sleep(DELIVER_BATCH_DELAY)

        # Auto-delete with warning
        if delete_minutes > 0 and sent_ids:
            try:
                warn = await client.send_message(
                    chat_id=user_id,
                    text=(f"⚠️ <b>ᴛʜɪꜱ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ "
                          f"{delete_minutes} ᴍɪɴᴜᴛᴇꜱ</b>\n\n"
                          f"📌 ꜰᴏʀᴡᴀʀᴅ ᴏʀ ꜱᴀᴠᴇ ᴛʜᴇ ꜰɪʟᴇꜱ ɴᴏᴡ"),
                    parse_mode=ParseMode.HTML)
                sent_ids.append(warn.id)
            except Exception: pass

            _spawn(_auto_delete_batch(client, user_id, sent_ids,
                                       delete_minutes * 60))

        # Final summary
        try:
            await client.send_message(
                chat_id=user_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('DONE')}</b>",
                    DIV, "",
                    f"🎬 <b>{_esc(chosen.get('title'))}</b>",
                    f"📺 <b>Season {chosen.get('selected_season'):02d}</b>",
                    f"🎯 <code>{chosen.get('selected_quality')}</code> · "
                    f"🌍 <code>{chosen.get('selected_language')}</code>",
                    "", f"✅ {sc('sent')} · <code>{sent}</code>",
                    f"❌ {sc('failed')} · <code>{failed}</code>",
                    "", f"🕒 <code>{_now_ist()}</code>",
                ]),
                parse_mode=ParseMode.HTML)
        except Exception: pass

        logger.info(f"[SG-DELIVER] ═══ DONE sent={sent}/{len(files)} → {user_id} ═══")
    except Exception as e:
        logger.exception(f"[SG-DELIVER] ═══ CRASHED: {e} ═══")


async def _auto_delete_batch(client, chat_id, msg_ids, seconds):
    try:
        await asyncio.sleep(seconds)
        for mid in msg_ids:
            try:
                await client.delete_messages(chat_id, mid)
            except Exception: pass
        logger.info(f"[SG-AUTODEL] deleted {len(msg_ids)} msgs")
    except asyncio.CancelledError: pass
    except Exception as e:
        logger.debug(f"[SG-AUTODEL] {e}")


def _build_extra_kb(buttons):
    if not buttons: return None
    rows = []
    for b in buttons:
        if not isinstance(b, dict): continue
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url: continue
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        if not (url.startswith("http://") or url.startswith("https://")
                or url.startswith("tg://")):
            continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST CALLBACK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gsreq:"), group=-9999)
async def cb_gsreq(client, q):
    try:
        _, token, action = q.data.split(":", 2)
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if not _is_admin(q.from_user.id):
        try:
            m = await client.get_chat_member(q.message.chat.id, q.from_user.id)
            st = getattr(m, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)
        except Exception:
            return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)

    req = await _get_request(token)
    if not req:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

    user_id = req.get("user_id")
    title = req.get("movie_name") or ""
    year = req.get("year")

    messages = {
        "updated": f"🎬 <b>{sc('good news!')}</b>\n\nʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{_esc(title)}</b> ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ ✅\n\nᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ɪᴛ.",
        "notreleased": f"📅 <b>{sc('not released yet')}</b>\n\n<b>{_esc(title)}</b> ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ.",
        "notfound": f"🔎 <b>{sc('not found')}</b>\n\nᴡᴇ ᴄᴏᴜʟᴅɴ'ᴛ ꜰɪɴᴅ <b>{_esc(title)}</b>.",
        "cancel": f"❌ <b>{sc('cancelled')}</b>\n\nʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{_esc(title)}</b> ʜᴀꜱ ʙᴇᴇɴ ᴄᴀɴᴄᴇʟʟᴇᴅ.",
    }
    icons = {"updated": "📺 SERIES UPDATED ✅", "notreleased": "📅 NOT RELEASED",
             "notfound": "🔎 NOT FOUND", "cancel": "❌ CANCELLED"}

    if user_id:
        try:
            kb_rows = []
            if action == "updated" and title:
                b64t = _b64e(title)
                b64y = _b64e(str(year) if year else "")
                kb_rows.append([InlineKeyboardButton(
                    f"🔍 SEARCH · {title[:40]}",
                    callback_data=f"greqsearch:{b64t}:{b64y}")])
            kb_rows.append([InlineKeyboardButton(
                "📢 UPDATES", url=UPDATE_CHNL_LNK)])

            await client.send_message(
                chat_id=user_id,
                text=messages.get(action, "✅ ꜱᴛᴀᴛᴜꜱ ᴜᴘᴅᴀᴛᴇᴅ"),
                reply_markup=InlineKeyboardMarkup(kb_rows),
                parse_mode=ParseMode.HTML)
            logger.info(f"[SG-REQ] notified {user_id}")
        except UserIsBlocked:
            logger.info(f"[SG-REQ] user blocked")
        except Exception as e:
            logger.warning(f"[SG-REQ] DM fail: {e}")

    await _update_request(token, action)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>{icons.get(action, '✅ DONE')}</b>",
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"[SG-REQ] edit: {e}")

    await q.answer(f"✅ {action}")


@Client.on_callback_query(filters.regex(r"^greqsearch:"), group=-9999)
async def cb_greq_search(client, q):
    try:
        parts = q.data.split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        _, b64t, b64y = parts
        title = _b64d(b64t)
        year = _b64d(b64y) or ""
        if not title:
            return await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)

        uid = q.from_user.id
        logger.info(f"[SG-REQ-SEARCH] user={uid} title={title!r}")

        await q.answer("🔍 ꜱᴇᴀʀᴄʜɪɴɢ...")

        local_files = await _engine_search(title)
        logger.info(f"[SG-REQ-SEARCH] {len(local_files)} files found")

        if not local_files:
            await q.message.edit_text(
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"⏳ <b>{fb('STILL NOT AVAILABLE')}</b>",
                    DIV, "",
                    f"🎬 <b>{_esc(title)}</b> {f'({year})' if year else ''}",
                    "",
                    f"📌 {sc('the files are being processed')}",
                    f"📌 {sc('try again in a few minutes')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close")]]),
                parse_mode=ParseMode.HTML)
            return

        tmdb_results = await _tmdb_search_series(title)
        tmdb_langs = ["English"]; tmdb_seasons = []
        poster = None; year_disp = year; tmdb_id = None

        if tmdb_results:
            ch = tmdb_results[0]
            tmdb_id = ch.get("tmdb_id")
            details = await _tmdb_series_details(tmdb_id)
            if details:
                tmdb_langs = _tmdb_languages(details)
                tmdb_seasons = _tmdb_seasons(details)
            poster = ch.get("poster")
            year_disp = ch.get("year") or year

        display_title = title
        if tmdb_results and tmdb_results[0].get("title"):
            display_title = tmdb_results[0]["title"]

        _new_session(uid, suggestions=[], raw_query=title)
        s = _SESSIONS[uid]
        summary = _summarize(local_files)
        s["data"]["chosen"] = {
            "tmdb_id": tmdb_id, "title": display_title,
            "year": year_disp, "poster": poster,
            "tmdb_langs": tmdb_langs, "tmdb_seasons": tmdb_seasons,
            "local_langs": summary["languages"],
            "local_seasons": summary["seasons"],
        }
        await _render_languages(client, q.message.chat.id, q.message.id, uid)
    except Exception as e:
        logger.exception(f"[SG-REQ-SEARCH] {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# BACK / CLOSE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:back_sugg$"), group=-9999)
async def cb_back_sugg(client, q):
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    items = s["data"].get("suggestions") or []
    raw = s["data"].get("raw_query") or ""
    if not items:
        return await q.answer("⚠️ ɴᴏ ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ", show_alert=True)
    await _render(client, q.message.chat.id, q.message.id,
                   _view_suggestions(raw, items),
                   kb_suggestions(items), None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_lang$"), group=-9999)
async def cb_back_lang(client, q):
    await _render_languages(client, q.message.chat.id, q.message.id, q.from_user.id)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_seas$"), group=-9999)
async def cb_back_seas(client, q):
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    c = s["data"].get("chosen") or {}
    seasons = c.get("tmdb_seasons") or []
    local = c.get("seasons_for_lang") or {}
    await _render(client, q.message.chat.id, q.message.id,
                   _view_seasons(c.get("title"), c.get("year")),
                   kb_seasons(seasons, local), None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:close$"), group=-9999)
async def cb_close(client, q):
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command(["sgroup", "series_group"]) & filters.private,
                    group=-9998)
async def cmd_sgroup(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_session(message.from_user.id)
        text, kb = await _view_admin_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[SG] /sgroup: {e}")


async def _view_admin_main():
    caption = await _get_caption()
    buttons = await _get_buttons()
    prefs = await _list_series_prefs()
    delete_min = await _get_delete_minutes()
    fsub_on = await _get_fsub_enabled()

    gid = f"<code>{SERIES_GROUP_ID}</code>" if SERIES_GROUP_ID else "⚠️ ɴᴏᴛ ꜱᴇᴛ"
    en = "🟢 ᴏɴ" if SERIES_GROUP_ENABLED else "🔴 ᴏꜰꜰ"
    delete_str = "♾️ ᴏꜰꜰ" if delete_min == 0 else f"⏱️ {delete_min}ᴍ"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES GROUP · ADMIN')}</b>",
        DIV, "",
        f"📢 {sc('group id')} · {gid}",
        f"⚙️ {sc('enabled')} · {en}",
        f"⏱️ {sc('auto-delete')} · <code>{delete_str}</code>",
        f"🔒 {sc('force sub')} · {'🟢 ᴏɴ' if fsub_on else '🔴 ᴏꜰꜰ'}",
        f"📝 {sc('caption')} · "
        f"<code>{'custom' if caption != DEFAULT_EPISODE_CAPTION else 'default'}</code>",
        f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
        f"🎯 {sc('series prefs')} · <code>{len(prefs)}</code>",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ AUTO-DELETE", callback_data="sg:a_del"),
         InlineKeyboardButton("🔒 FORCE SUB", callback_data="sg:a_fsub")],
        [InlineKeyboardButton("📝 EDIT CAPTION", callback_data="sg:a_caption"),
         InlineKeyboardButton("🔘 MANAGE BUTTONS", callback_data="sg:a_buttons")],
        [InlineKeyboardButton("🎯 SERIES PREFS", callback_data="sg:a_prefs"),
         InlineKeyboardButton("📊 STATS", callback_data="sg:a_stats")],
        [InlineKeyboardButton("📢 SEND TEST", callback_data="sg:a_test")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
    ])
    return text, kb


@Client.on_callback_query(filters.regex(r"^sg:a_main$"), group=-9998)
async def cb_a_main(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_admin_main()
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_close$"), group=-9998)
async def cb_a_close(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sg:a_del$"), group=-9998)
async def cb_a_del(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cur = await _get_delete_minutes()
    rows = []; row = []
    for mins, label in DELETE_PRESETS:
        marker = "✅" if mins == cur else "⬜"
        row.append(InlineKeyboardButton(f"{marker} {label}",
                                          callback_data=f"sg:a_del_set:{mins}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main")])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('AUTO-DELETE TIME')}</b>",
        DIV, "",
        f"📌 {sc('how long files stay in user pm')}",
        f"📌 {sc('a warning will be shown before delete')}",
        "",
        f"✅ {sc('current')} · "
        f"<code>{'never' if cur == 0 else str(cur) + ' min'}</code>",
    ])
    await _render(client, q.message.chat.id, q.message.id,
                   text, InlineKeyboardMarkup(rows), None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_del_set:(\d+)$"), group=-9998)
async def cb_a_del_set(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    mins = int(q.matches[0].group(1))
    ok = await _set_delete_minutes(mins)
    await q.answer(f"✅ {mins}ᴍ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
    await cb_a_del(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_fsub$"), group=-9998)
async def cb_a_fsub(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    cur = await _get_fsub_enabled()
    new = not cur
    ok = await _set_fsub_enabled(new)
    await q.answer(f"{'🟢 ᴏɴ' if new else '🔴 ᴏꜰꜰ'}" if ok else "❌ ꜰᴀɪʟᴇᴅ")
    text, kb = await _view_admin_main()
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)


@Client.on_callback_query(filters.regex(r"^sg:a_caption$"), group=-9998)
async def cb_a_caption(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    current = await _get_caption()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('EPISODE CAPTION')}</b>",
        DIV, "", f"<code>{_esc(current[:400])}</code>",
        "", DIV2, f"📌 {sc('placeholders')}:",
        f"<code>{{series}}</code> <code>{{season}}</code> <code>{{episode}}</code>",
        f"<code>{{quality}}</code> <code>{{language}}</code> <code>{{size}}</code>",
        f"<code>{{file_name}}</code> <code>{{year}}</code> <code>{{rating}}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT", callback_data="sg:a_cap_edit")],
        [InlineKeyboardButton("♻️ RESET", callback_data="sg:a_cap_reset"),
         InlineKeyboardButton("👁️ PREVIEW", callback_data="sg:a_cap_prev")],
        [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
    ])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_cap_edit$"), group=-9998)
async def cb_a_cap_edit(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, edit_caption=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION')}</b>",
        DIV, "", f"📝 {sc('send the new caption template')}",
        "", f"📌 {sc('placeholders')}:",
        f"<code>{{series}}</code> <code>{{season}}</code> <code>{{episode}}</code>",
        f"<code>{{quality}}</code> <code>{{language}}</code> <code>{{size}}</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_caption")]])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_cap_reset$"), group=-9998)
async def cb_a_cap_reset(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    await _set_caption(DEFAULT_EPISODE_CAPTION)
    await q.answer("♻️ ʀᴇꜱᴇᴛ")
    await cb_a_caption(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_cap_prev$"), group=-9998)
async def cb_a_cap_prev(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    template = await _get_caption()
    preview = _safe_caption(template, {
        "series": "Breaking Bad", "title": "Breaking Bad",
        "season": 1, "episode": 5, "quality": "1080P",
        "language": "English", "lang": "English",
        "size": "1.45 GB", "file_size": "1.45 GB",
        "file_name": "Breaking.Bad.S01E05.1080p.mkv",
        "rating": "9.5", "year": "2008",
        "file_caption": "Breaking Bad",
    }, template)
    text = "\n".join([f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                      f"👁️ <b>{fb('PREVIEW')}</b>", DIV, "", preview])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="sg:a_caption")]])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_buttons$"), group=-9998)
async def cb_a_buttons(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    buttons = await _get_buttons()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🔘 <b>{fb('EXTRA BUTTONS')}</b>", DIV, ""]
    if not buttons: lines.append("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ ʏᴇᴛ.")
    else:
        for i, b in enumerate(buttons, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")
    rows = [[InlineKeyboardButton(
        f"🗑️ {i}. {(b.get('name') or '?')[:30]}",
        callback_data=f"sg:a_btn_rm:{i-1}")] for i, b in enumerate(buttons, 1)]
    rows.append([InlineKeyboardButton("➕ ADD", callback_data="sg:a_btn_add")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")])
    await _render(client, q.message.chat.id, q.message.id,
                   "\n".join(lines), InlineKeyboardMarkup(rows), None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_btn_add$"), group=-9998)
async def cb_a_btn_add(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, add_button=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON')}</b>",
        DIV, "", f"📝 {sc('send')} <code>Name | URL</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_buttons")]])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_btn_rm:(\d+)$"), group=-9998)
async def cb_a_btn_rm(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    buttons = await _get_buttons()
    if 0 <= idx < len(buttons):
        buttons.pop(idx)
        await _set_buttons(buttons)
    await q.answer("🗑️")
    await cb_a_buttons(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_prefs$"), group=-9998)
async def cb_a_prefs(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    prefs = await _list_series_prefs()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🎯 <b>{fb('SERIES PREFS')}</b>", DIV, ""]
    if not prefs: lines.append("⚪ ɴᴏɴᴇ ꜱᴇᴛ.")
    else:
        for p in prefs[:30]:
            lines.append(f"🎬 <b>{_esc(p.get('title'))}</b>")
            lines.append(f"   🎯 <code>{', '.join(p.get('qualities') or [])}</code>")
            lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ SET PREFS", callback_data="sg:a_pref_add")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_prefs")],
        [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
    ])
    await _render(client, q.message.chat.id, q.message.id,
                   "\n".join(lines), kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_pref_add$"), group=-9998)
async def cb_a_pref_add(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, pref_add_name=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "", f"📝 {sc('send the series name')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_prefs")]])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_stats$"), group=-9998)
async def cb_a_stats(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    prefs = await _list_series_prefs()
    buttons = await _get_buttons()
    delete_min = await _get_delete_minutes()
    fsub_on = await _get_fsub_enabled()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('STATS')}</b>", DIV, "",
        f"🎯 {sc('prefs')} · <code>{len(prefs)}</code>",
        f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
        f"⏱️ {sc('delete')} · "
        f"<code>{'off' if delete_min == 0 else str(delete_min) + ' min'}</code>",
        f"🔒 {sc('fsub')} · {'🟢' if fsub_on else '🔴'}",
        f"📢 {sc('group')} · <code>{SERIES_GROUP_ID or '—'}</code>",
        f"⚙️ {sc('enabled')} · {'🟢' if SERIES_GROUP_ENABLED else '🔴'}",
        f"🕒 <code>{_now_ist()}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_stats")],
        [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")]])
    await _render(client, q.message.chat.id, q.message.id, text, kb, None)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_test$"), group=-9998)
async def cb_a_test(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    if not SERIES_GROUP_ID:
        return await q.answer("⚠️ ɴᴏ ɢʀᴏᴜᴘ ɪᴅ", show_alert=True)
    try:
        await client.send_message(
            chat_id=SERIES_GROUP_ID,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🎬 <b>{fb('SERIES SEARCH READY')}</b>",
                DIV, "", f"📌 {sc('type any series name')}",
            ]),
            parse_mode=ParseMode.HTML)
        await q.answer("✅ ꜱᴇɴᴛ")
    except Exception as e:
        await q.answer(f"❌ {str(e)[:100]}", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN TEXT INPUT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"),
                    group=-9997)
async def sg_admin_input(client, message):
    if not message.from_user: return
    if not _is_admin(message.from_user.id): return
    s = _get_session(message.from_user.id)
    if not s: return

    data = s.get("data") or {}
    action = None
    for k in ("edit_caption", "add_button", "pref_add_name"):
        if data.get(k): action = k; break
    if not action: return

    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()

    if action == "edit_caption":
        if len(text) < 10: return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await _set_caption(text)
        _clear_session(message.from_user.id)
        await message.reply_text("✅ ꜱᴀᴠᴇᴅ." if ok else "❌ ꜰᴀɪʟᴇᴅ.")
        return

    if action == "add_button":
        if "|" not in text:
            return await message.reply_text(
                "❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url: return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http") or url.startswith("tg://")):
            if "." in url and " " not in url: url = f"https://{url}"
            else: return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        buttons = await _get_buttons()
        if len(buttons) >= 6:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 6 ʙᴜᴛᴛᴏɴꜱ.")
        buttons.append({"name": name[:60], "url": url,
                        "position": len(buttons) + 1})
        await _set_buttons(buttons)
        _clear_session(message.from_user.id)
        await message.reply_text(f"✅ ᴀᴅᴅᴇᴅ: <b>{_esc(name)}</b>",
                                  parse_mode=ParseMode.HTML)
        return

    if action == "pref_add_name":
        loading = await message.reply_text("🔍 ꜱᴄᴀɴɴɪɴɢ ᴅʙ...")
        files = await _engine_search(text)
        if not files:
            _clear_session(message.from_user.id)
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text=f"❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ <code>{_esc(text)}</code>.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return
        quals = sorted({f.get("quality") for f in files
                        if f.get("quality") not in (None, "UNKNOWN")},
                       key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
        if not quals:
            _clear_session(message.from_user.id)
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text="⚠️ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return
        _new_session(message.from_user.id,
                     pref_slug=re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_"),
                     pref_title=text, pref_quals=list(quals),
                     pref_selected=list(quals))
        await _show_pref_picker(client, message.chat.id, loading.id)
        return


async def _show_pref_picker(client, chat_id, msg_id):
    uid = None
    for u, s in _SESSIONS.items():
        d = s.get("data") or {}
        if d.get("pref_slug"): uid = u; break
    if uid is None: return
    d = _SESSIONS[uid]["data"]
    title = d.get("pref_title"); quals = d.get("pref_quals") or []
    selected = d.get("pref_selected") or []
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "", f"🎬 <b>{_esc(title)}</b>", "",
        f"✅ {sc('selected')} · <code>{', '.join(selected) or 'none'}</code>",
    ]
    rows = []; row = []
    for q in quals:
        mark = "✅" if q in selected else "⬜"
        row.append(InlineKeyboardButton(f"{mark} {q}",
                                          callback_data=f"sg:a_pref_tog:{q}"))
        if len(row) == 3: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("💾 SAVE", callback_data="sg:a_pref_save")])
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_prefs")])
    await _render(client, chat_id, msg_id, "\n".join(lines),
                   InlineKeyboardMarkup(rows), None)


@Client.on_callback_query(filters.regex(r"^sg:a_pref_tog:(\w+)$"), group=-9998)
async def cb_a_pref_tog(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    qual = q.matches[0].group(1)
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    d = s["data"]
    selected = list(d.get("pref_selected") or [])
    if qual in selected: selected.remove(qual)
    else: selected.append(qual)
    d["pref_selected"] = selected
    await q.answer("✅" if qual in selected else "⬜")
    await _show_pref_picker(client, q.message.chat.id, q.message.id)


@Client.on_callback_query(filters.regex(r"^sg:a_pref_save$"), group=-9998)
async def cb_a_pref_save(client, q):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    d = s["data"]
    ok = await _set_series_pref(d.get("pref_slug"), d.get("pref_title"),
                                  d.get("pref_selected") or [])
    _clear_session(q.from_user.id)
    await q.answer("✅ ꜱᴀᴠᴇᴅ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
    await cb_a_prefs(client, q)


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP + LOG
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_sessions()
            _pending_cleanup()
        except asyncio.CancelledError: break
        except Exception: pass

try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception: pass


logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🎬 SERIES GROUP ULTIMATE v13 — LOADED ✅                      ║")
logger.info("║                                                                ║")
logger.info("║  ✅ kb_suggestions now defined (was missing!)                  ║")
logger.info("║  ✅ Suggestions: NAME CAPS + ⭐ rating                         ║")
logger.info("║  ✅ Custom caption works (safe formatting)                     ║")
logger.info("║  ✅ Custom buttons work (cached_media first)                   ║")
logger.info("║  ✅ Auto-delete + Force-sub                                    ║")
logger.info("║  ✅ Quality click → auto-redirect to PM                        ║")
logger.info("║                                                                ║")
logger.info(f"║  Group ID: {SERIES_GROUP_ID or 'NOT SET':<50}║")
logger.info(f"║  Enabled:  {'YES' if SERIES_GROUP_ENABLED else 'NO':<50}║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
