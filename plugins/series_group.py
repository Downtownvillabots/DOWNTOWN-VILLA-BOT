# plugins/series_group.py
"""
🎬 DOWNTOWN VILLA — SERIES GROUP (ULTIMATE)
"""
import asyncio
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait, UserIsBlocked
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import db_manager

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

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
DELIVER_BATCH_DELAY = 0.5

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
# SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(uid: int, **data) -> str:
    sid = secrets.token_urlsafe(6)[:8]
    _SESSIONS[uid] = {"sid": sid, "data": data,
                      "expires": time.time() + SESSION_TTL}
    return sid


def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s


def _clear_session(uid: int) -> None:
    _SESSIONS.pop(uid, None)


def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# DEDUPE — one file per (season, episode, quality). Prefer LARGEST.
# ═══════════════════════════════════════════════════════════════════════════
def _dedupe_by_episode(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not files:
        return []

    # 1. Sort all files by size descending (largest first)
    sorted_files = sorted(
        files,
        key=lambda x: (x.get("file_size") or 0),
        reverse=True,
    )

    # 2. Take the FIRST file for each unique key
    seen: Set[Tuple] = set()
    out: List[Dict[str, Any]] = []
    for f in sorted_files:
        s = f.get("season")
        e = f.get("episode")
        q = (f.get("quality") or "UNKNOWN").upper().strip()
        key = (s, e, q)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)

    # 3. Sort by (season, episode) for display
    out.sort(key=lambda x: (x.get("season") or 0, x.get("episode") or 0))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ENGINE SEARCH — NO YEAR, LENIENT, DEDUPED
# ═══════════════════════════════════════════════════════════════════════════
async def _engine_search(title: str,
                         season: Optional[int] = None,
                         language: Optional[str] = None,
                         quality: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        from media_search.engine import engine
        from media_search.normalizer import normalize
    except Exception as e:
        logger.exception(f"[SG] engine import failed: {e}")
        return []

    all_files: List[Dict[str, Any]] = []

    try:
        norm = normalize(title)
        logger.info(f"[SG] engine.search_series({norm!r}) — NO YEAR")

        result = await engine.search_series(norm)
        hits = result.hits

        if not hits:
            logger.info(f"[SG] engine.search_any({norm!r})")
            result = await engine.search_any(norm)
            hits = result.hits

        logger.info(f"[SG] engine returned {len(hits)} hits")

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

            if season is not None and h_season != season:
                continue

            if language:
                lang_lower = language.lower()
                h_lower = [l.lower() for l in h_langs]
                if h_lower and not any(lang_lower in l or l in lang_lower
                                        for l in h_lower):
                    continue

            if quality and h_quality:
                if h_quality.upper() != quality.upper():
                    continue

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

        before = len(all_files)
        all_files = _dedupe_by_episode(all_files)
        logger.info(f"[SG] filter: {before} files → deduped: {len(all_files)}")

    except Exception as e:
        logger.exception(f"[SG] engine search failed: {e}")

    return all_files


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


def _parse_filename_light(filename: str) -> Dict[str, Any]:
    out = {"season": None, "episode": None, "quality": None, "languages": []}
    if not filename: return out
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts)$", "",
                  name, flags=re.I)
    wl = name.lower()

    for pat in _SE_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                out["season"] = int(m.group(1))
                out["episode"] = int(m.group(2))
                break
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
async def _tmdb_get(path: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
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


async def _tmdb_search_series(query: str) -> List[Dict[str, Any]]:
    data = await _tmdb_get("/search/tv", {"query": query,
                                           "include_adult": "false"})
    if not data: return []
    out = []
    for it in (data.get("results") or [])[:8]:
        title = it.get("name") or it.get("original_name") or ""
        if not title: continue
        date = it.get("first_air_date") or ""
        out.append({
            "tmdb_id": it.get("id"),
            "title": title,
            "year": (date or "")[:4],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
        })
    return out


async def _tmdb_series_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    return await _tmdb_get(f"/tv/{tmdb_id}", {})


def _tmdb_languages(details: Dict[str, Any]) -> List[str]:
    langs = set()
    orig = (details.get("original_language") or "").lower()
    if orig: langs.add(orig)
    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code: langs.add(code)
    code_to_name = {
        "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
        "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
        "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
        "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French",
        "de": "German", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
        "tr": "Turkish", "ar": "Arabic", "th": "Thai",
    }
    named = [code_to_name[c] for c in langs if c in code_to_name]
    named.sort(key=lambda x: (x != "English", x))
    return named or ["English"]


def _tmdb_seasons(details: Dict[str, Any]) -> List[Dict[str, Any]]:
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


def _poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ═══════════════════════════════════════════════════════════════════════════
# SUMMARIZE
# ═══════════════════════════════════════════════════════════════════════════
def _summarize(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    qualities: Set[str] = set()
    languages: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)

    for f in files:
        q = f.get("quality") or "UNKNOWN"
        if q != "UNKNOWN": qualities.add(q)
        for l in (f.get("languages") or []):
            languages.add(l)
        s = f.get("season")
        e = f.get("episode")
        if s is not None:
            seasons[s].add(e if e is not None else 0)

    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "languages": sorted(languages),
        "seasons": {s: sorted(eps) for s, eps in seasons.items()},
        "total_files": len(files),
    }


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_suggestions(items: List[Dict[str, Any]]):
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?")[:36]
        year = it.get("year") or ""
        label = f"🎬 {title}"
        if year: label += f" ({year})"
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"sg:pick:{i}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_languages(langs: List[str], local_langs: List[str]):
    rows = []
    row = []
    for i, lang in enumerate(langs[:12]):
        has = "🟢" if lang in local_langs else "⚪"
        row.append(InlineKeyboardButton(f"{has} {lang}",
                                          callback_data=f"sg:lang:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_sugg"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(seasons: List[Dict[str, Any]], local: Dict[int, List[int]]):
    rows = []
    for i, s in enumerate(seasons[:15]):
        sn = s["season"]
        eps = s.get("episodes", 0)
        local_eps = local.get(sn, [])
        if local_eps:
            count = len([e for e in local_eps if e > 0])
            mark = "🟢" if count >= eps else "🟡"
        else:
            count = 0; mark = "⚪"
        label = f"{mark} S{sn:02d} · {eps} ep"
        if count: label += f" · {count} local"
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"sg:seas:{i}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_lang"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_qualities(qualities: List[str]):
    rows = []
    row = []
    for i, q in enumerate(qualities[:12]):
        row.append(InlineKeyboardButton(f"🎯 {q}",
                                          callback_data=f"sg:qual:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_seas"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# VIEWS
# ═══════════════════════════════════════════════════════════════════════════
def _view_suggestions(raw: str, items: List[Dict[str, Any]]) -> str:
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES SEARCH')}</b>",
        DIV, "",
        f"🔍 {sc('you searched')} · <code>{_esc(raw)}</code>",
        "",
        f"📌 {sc('pick the series you meant')}",
        "", DIV2, "",
    ]
    for i, it in enumerate(items, 1):
        title = it.get("title") or "?"
        year = it.get("year") or ""
        rating = it.get("rating", 0)
        lines.append(f"<b>{i}.</b> <b>{_esc(title)}</b> ({year}) · ⭐ {rating:.1f}")
    return "\n".join(lines)


def _view_languages(title: str, year: str) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b> ({year})",
        DIV, "",
        f"🌍 {sc('pick language')}",
        "",
        f"🟢 = ʜᴀᴠᴇ ꜰɪʟᴇꜱ · ⚪ = ᴏɴʟʏ ᴛᴍᴅʙ",
    ])


def _view_seasons(title: str, year: str) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b> ({year})",
        DIV, "",
        f"📺 {sc('pick season')}",
        "",
        f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ɴᴏ ꜰɪʟᴇꜱ",
    ])


def _view_qualities(title: str, season: int) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {season:02d}</b>",
        DIV, "",
        f"🎯 {sc('pick quality')}",
        "",
        f"📌 {sc('files will be sent to your pm')}",
    ])


async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.exception(f"[SG] edit: {e}"); return False


# ═══════════════════════════════════════════════════════════════════════════
# GROUP SEARCH — group=-9999 so we run FIRST
# ═══════════════════════════════════════════════════════════════════════════
if SERIES_GROUP_ID and SERIES_GROUP_ENABLED:
    @Client.on_message(
        filters.chat(SERIES_GROUP_ID) & filters.text & ~filters.regex(r"^/"),
        group=-9999,
    )
    async def series_group_search(client: Client, message: Message):
        try:
            txt = (message.text or "").strip()
            if len(txt) < 2 or len(txt) > 80: return
            if not message.from_user: return
            if "http" in txt.lower(): return

            # ⭐ Stop other plugins from also handling this message
            try:
                message.stop_propagation()
            except Exception: pass

            logger.info(f"[SG] search: {txt!r}")

            try:
                status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
            except Exception: return

            results = await _tmdb_search_series(txt)
            if not results:
                await _safe_edit(status,
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
                    f"❌ ɴᴏ ᴛᴍᴅʙ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{_esc(txt)}</code>",
                    InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ CLOSE",
                                              callback_data="sg:close")]]))
                return

            _new_session(message.from_user.id,
                         suggestions=results, raw_query=txt)

            text = _view_suggestions(txt, results)
            kb = kb_suggestions(results)

            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=status.id,
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception as e:
                logger.warning(f"[SG] edit: {e}")

            try:
                await client.send_message(
                    chat_id=message.from_user.id,
                    text="📩 <b>ᴄʜᴇᴄᴋ ᴛʜᴇ ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ</b>!",
                    parse_mode=ParseMode.HTML)
            except Exception: pass

        except Exception as e:
            logger.exception(f"[SG] group search: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PICK SUGGESTION
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:pick:(\d+)$"), group=-9999)
async def cb_pick(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ · ᴛʀʏ ᴀɢᴀɪɴ", show_alert=True)

        items = s["data"].get("suggestions") or []
        if idx >= len(items):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = items[idx]
        tmdb_id = chosen.get("tmdb_id")
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""

        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")

        details = await _tmdb_series_details(tmdb_id)
        if not details:
            return await q.answer("⚠️ ᴛᴍᴅʙ ᴇʀʀᴏʀ", show_alert=True)

        tmdb_langs = _tmdb_languages(details)
        tmdb_seasons = _tmdb_seasons(details)

        local_files = await _engine_search(title)
        summary = _summarize(local_files)

        logger.info(f"[SG] pick: {title!r} · local_files={len(local_files)}")

        s["data"]["chosen"] = {
            "tmdb_id": tmdb_id, "title": title, "year": year,
            "poster": chosen.get("poster"),
            "tmdb_langs": tmdb_langs,
            "tmdb_seasons": tmdb_seasons,
            "local_langs": summary["languages"],
            "local_seasons": summary["seasons"],
        }

        await _show_languages(client, q)
    except Exception as e:
        logger.exception(f"[SG] pick: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


async def _show_languages(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return
    c = s["data"].get("chosen") or {}
    tmdb_langs = c.get("tmdb_langs") or ["English"]
    local_langs = c.get("local_langs") or []

    ordered = [l for l in tmdb_langs if l in local_langs] + \
              [l for l in tmdb_langs if l not in local_langs]
    c["ordered_langs"] = ordered

    text = _view_languages(c.get("title"), c.get("year"))
    kb = kb_languages(ordered, local_langs)
    poster = _poster_url(c.get("poster"), "w500")

    if poster:
        try: await q.message.delete()
        except Exception: pass
        try:
            await client.send_photo(chat_id=q.message.chat.id, photo=poster,
                                     caption=text, reply_markup=kb,
                                     parse_mode=ParseMode.HTML)
            await q.answer()
            return
        except Exception as e:
            logger.debug(f"[SG] photo: {e}")

    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# PICK LANGUAGE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:lang:(\d+)$"), group=-9999)
async def cb_lang(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
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
        text = _view_seasons(c.get("title"), c.get("year"))
        kb = kb_seasons(seasons, summary["seasons"])
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] lang: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# PICK SEASON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:seas:(\d+)$"), group=-9999)
async def cb_seas(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
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

        logger.info(f"[SG] S{season} ({lang}): {len(files)} files")

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

        c["available_qualities"] = final_quals

        if not final_quals:
            fallback = sorted({f["quality"] for f in files
                               if f.get("quality")}, reverse=True)
            if fallback:
                c["available_qualities"] = fallback
            else:
                return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇᴀꜱᴏɴ",
                                       show_alert=True)

        text = _view_qualities(c.get("title"), season)
        kb = kb_qualities(c["available_qualities"])
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[SG] seas: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# PICK QUALITY → DELIVER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:qual:(\d+)$"), group=-9999)
async def cb_qual(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        c = s["data"].get("chosen") or {}
        quals = c.get("available_qualities") or []
        if idx >= len(quals):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        quality = quals[idx]
        c["selected_quality"] = quality
        await q.answer(f"📩 ꜱᴇɴᴅɪɴɢ {quality} ᴛᴏ ʏᴏᴜʀ ᴘᴍ...")

        # Filter for this quality
        files = [f for f in (c.get("files_by_season") or [])
                 if (f.get("quality") or "").upper() == quality.upper()
                 or (f.get("quality") == "UNKNOWN")]

        # ⭐ Dedupe again — 1 file per (season, episode, quality)
        files = _dedupe_by_episode(files)
        files.sort(key=lambda x: (x.get("episode") or 0))

        logger.info(f"[SG] qual {quality}: delivering {len(files)} files "
                    f"to user {q.from_user.id}")

        if not files:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ", show_alert=True)

        # Show "sending" in the group
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📤 <b>{fb('SENDING TO YOUR PM')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(c.get('title'))}</b>",
            f"📺 <b>Season {c.get('selected_season'):02d}</b>",
            f"🎯 <code>{quality}</code> · 🌍 <code>{c.get('selected_language')}</code>",
            "",
            f"📁 <code>{len(files)}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
            "",
            f"📌 {sc('check your bot pm')}",
        ])
        await _safe_edit(q, text, InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")]]))

        # Deliver in background
        asyncio.create_task(_deliver_episodes(client, q.from_user.id, c, files))
    except Exception as e:
        logger.exception(f"[SG] qual: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# DELIVER — build proper FileHit for reliability
# ═══════════════════════════════════════════════════════════════════════════
async def _deliver_episodes(client: Client, user_id: int,
                             chosen: Dict[str, Any],
                             files: List[Dict[str, Any]]):
    try:
        logger.info(f"[SG-DELIVER] start: user={user_id} files={len(files)}")

        # Load delivery helper
        delivery = None
        try:
            from media_search.delivery import delivery as _d
            delivery = _d
        except Exception as e:
            logger.exception(f"[SG-DELIVER] delivery import failed: {e}")

        # Load FileHit class for rebuilding
        FileHit = None
        try:
            from media_search.models import FileHit as _FH
            FileHit = _FH
        except Exception as e:
            logger.debug(f"[SG-DELIVER] FileHit import: {e}")

        # Load normalize
        normalize = None
        try:
            from media_search.normalizer import normalize as _n
            normalize = _n
        except Exception:
            pass

        # Send intro to PM
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
                    "",
                    f"📁 Sending <code>{len(files)}</code> episodes...",
                ]),
                parse_mode=ParseMode.HTML)
            logger.info(f"[SG-DELIVER] intro sent")
        except UserIsBlocked:
            logger.warning(f"[SG-DELIVER] user blocked bot")
            return
        except Exception as e:
            logger.exception(f"[SG-DELIVER] intro failed: {e}")
            return

        template = await _get_caption()
        extra_buttons = await _get_buttons()
        extra_kb = _build_extra_kb(extra_buttons)

        sent = 0
        failed = 0

        for f in files:
            try:
                ep = f.get("episode")
                size = _fmt_size(f.get("file_size", 0))
                try:
                    caption = template.format(
                        series=chosen.get("title") or "",
                        season=chosen.get("selected_season") or 0,
                        episode=ep or 0,
                        quality=chosen.get("selected_quality") or "",
                        language=chosen.get("selected_language") or "",
                        size=size)
                except Exception:
                    caption = (f"🎬 {chosen.get('title')} "
                               f"S{chosen.get('selected_season'):02d}"
                               f"E{ep or 0:02d}")

                file_hit = f.get("file_hit")

                # ── METHOD 1: delivery.send_file with original FileHit ──
                if delivery is not None and file_hit is not None:
                    try:
                        ok_d, err = await delivery.send_file(
                            client, user_id, file_hit)
                        if ok_d:
                            sent += 1
                            logger.info(f"[SG-DELIVER] OK (method1) ep={ep}")
                            await asyncio.sleep(DELIVER_BATCH_DELAY)
                            continue
                        else:
                            logger.warning(f"[SG-DELIVER] method1 failed: {err}")
                    except Exception as e:
                        logger.exception(f"[SG-DELIVER] method1 exc: {e}")

                # ── METHOD 2: rebuild FileHit and use delivery ──
                if delivery is not None and FileHit is not None:
                    try:
                        hit = FileHit(
                            file_id=f.get("file_id", "") or "",
                            file_unique_id=f.get("file_unique_id"),
                            file_name=f.get("file_name"),
                            file_size=f.get("file_size"),
                            title=f.get("title", "") or "",
                            normalized_title=(normalize(f.get("title") or "")
                                              if normalize else
                                              (f.get("title") or "").lower()),
                            year=None,
                            type="series",
                            quality=f.get("quality"),
                            codec=None,
                            audio_languages=list(f.get("languages") or []),
                            subtitle_languages=[],
                            has_subtitle=False,
                            series_title=f.get("series_title") or "",
                            season=f.get("season"),
                            episode=f.get("episode"),
                            caption=None,
                        )
                        ok_d, err = await delivery.send_file(client, user_id, hit)
                        if ok_d:
                            sent += 1
                            logger.info(f"[SG-DELIVER] OK (method2) ep={ep}")
                            await asyncio.sleep(DELIVER_BATCH_DELAY)
                            continue
                        else:
                            logger.warning(f"[SG-DELIVER] method2: {err}")
                    except Exception as e:
                        logger.debug(f"[SG-DELIVER] method2 exc: {e}")

                # ── METHOD 3: copy_message by chat+msg ──
                src_chat = f.get("chat_id")
                src_msg = f.get("message_id")
                if src_chat and src_msg:
                    try:
                        await client.copy_message(
                            chat_id=user_id,
                            from_chat_id=src_chat,
                            message_id=src_msg,
                            caption=caption,
                            reply_markup=extra_kb,
                            parse_mode=ParseMode.HTML)
                        sent += 1
                        logger.info(f"[SG-DELIVER] OK (method3 copy) ep={ep}")
                        await asyncio.sleep(DELIVER_BATCH_DELAY)
                        continue
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 2)
                        try:
                            await client.copy_message(
                                chat_id=user_id,
                                from_chat_id=src_chat,
                                message_id=src_msg,
                                caption=caption,
                                reply_markup=extra_kb,
                                parse_mode=ParseMode.HTML)
                            sent += 1
                            await asyncio.sleep(DELIVER_BATCH_DELAY)
                            continue
                        except Exception: failed += 1
                    except Exception as e:
                        logger.debug(f"[SG-DELIVER] method3 exc: {e}")

                # ── METHOD 4: send_cached_media by file_id ──
                fid = f.get("file_id")
                if fid:
                    try:
                        await client.send_cached_media(
                            chat_id=user_id, file_id=fid,
                            caption=caption, reply_markup=extra_kb,
                            parse_mode=ParseMode.HTML)
                        sent += 1
                        logger.info(f"[SG-DELIVER] OK (method4 cached) ep={ep}")
                        await asyncio.sleep(DELIVER_BATCH_DELAY)
                        continue
                    except Exception as e:
                        logger.debug(f"[SG-DELIVER] method4 exc: {e}")

                failed += 1
                logger.warning(f"[SG-DELIVER] FAIL ep={ep} - all methods failed")

            except Exception as e:
                logger.exception(f"[SG-DELIVER] one file exc: {e}")
                failed += 1

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
                    "",
                    f"✅ {sc('sent')} · <code>{sent}</code>",
                    f"❌ {sc('failed')} · <code>{failed}</code>",
                    "",
                    f"🕒 <code>{_now_ist()}</code>",
                ]),
                parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.debug(f"[SG-DELIVER] final: {e}")

        logger.info(f"[SG-DELIVER] done: {sent}/{len(files)} to {user_id}")
    except Exception as e:
        logger.exception(f"[SG-DELIVER] crashed: {e}")


def _build_extra_kb(buttons: List[Dict[str, Any]]) -> Optional[InlineKeyboardMarkup]:
    if not buttons: return None
    rows = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if name and url:
            rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ═══════════════════════════════════════════════════════════════════════════
# BACK / CLOSE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:back_sugg$"), group=-9999)
async def cb_back_sugg(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    items = s["data"].get("suggestions") or []
    raw = s["data"].get("raw_query") or ""
    await _safe_edit(q, _view_suggestions(raw, items), kb_suggestions(items))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_lang$"), group=-9999)
async def cb_back_lang(client: Client, q: CallbackQuery):
    await _show_languages(client, q)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_seas$"), group=-9999)
async def cb_back_seas(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    c = s["data"].get("chosen") or {}
    seasons = c.get("tmdb_seasons") or []
    local = c.get("seasons_for_lang") or {}
    await _safe_edit(q, _view_seasons(c.get("title"), c.get("year")),
                      kb_seasons(seasons, local))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:close$"), group=-9999)
async def cb_close(client: Client, q: CallbackQuery):
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["sgroup", "series_group"]) & filters.private,
    group=-9998)
async def cmd_sgroup(client: Client, message: Message):
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

    group_status = (f"<code>{SERIES_GROUP_ID}</code>"
                    if SERIES_GROUP_ID else "⚠️ ɴᴏᴛ ꜱᴇᴛ")
    enabled_txt = "🟢 ᴏɴ" if SERIES_GROUP_ENABLED else "🔴 ᴏꜰꜰ"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES GROUP · ADMIN')}</b>",
        DIV, "",
        f"📢 {sc('group id')} · {group_status}",
        f"⚙️ {sc('enabled')} · {enabled_txt}",
        f"📝 {sc('caption')} · "
        f"<code>{'custom' if caption != DEFAULT_EPISODE_CAPTION else 'default'}</code>",
        f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
        f"🎯 {sc('series prefs')} · <code>{len(prefs)}</code>",
    ])

    kb = InlineKeyboardMarkup([
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
async def cb_a_main(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    text, kb = await _view_admin_main()
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_close$"), group=-9998)
async def cb_a_close(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sg:a_caption$"), group=-9998)
async def cb_a_caption(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    current = await _get_caption()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('EPISODE CAPTION')}</b>",
        DIV, "",
        f"<code>{_esc(current[:400])}</code>",
        "",
        DIV2, "",
        f"📌 {sc('placeholders')}:",
        f"<code>{{series}}</code> <code>{{season}}</code> <code>{{episode}}</code>",
        f"<code>{{quality}}</code> <code>{{language}}</code> <code>{{size}}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT", callback_data="sg:a_cap_edit")],
        [InlineKeyboardButton("♻️ RESET", callback_data="sg:a_cap_reset"),
         InlineKeyboardButton("👁️ PREVIEW", callback_data="sg:a_cap_prev")],
        [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
    ])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_cap_edit$"), group=-9998)
async def cb_a_cap_edit(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, edit_caption=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption template')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_caption")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_cap_reset$"), group=-9998)
async def cb_a_cap_reset(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    await _set_caption(DEFAULT_EPISODE_CAPTION)
    await q.answer("♻️ ʀᴇꜱᴇᴛ")
    await cb_a_caption(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_cap_prev$"), group=-9998)
async def cb_a_cap_prev(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    template = await _get_caption()
    try:
        preview = template.format(series="Breaking Bad", season=1, episode=5,
                                   quality="1080P", language="English",
                                   size="1.45 GB")
    except Exception:
        preview = template
    text = "\n".join([f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                      f"👁️ <b>{fb('PREVIEW')}</b>", DIV, "", preview])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="sg:a_caption")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_buttons$"), group=-9998)
async def cb_a_buttons(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    buttons = await _get_buttons()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🔘 <b>{fb('EXTRA BUTTONS')}</b>", DIV, ""]
    if not buttons:
        lines.append("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ ʏᴇᴛ.")
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
    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_btn_add$"), group=-9998)
async def cb_a_btn_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, add_button=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_buttons")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_btn_rm:(\d+)$"), group=-9998)
async def cb_a_btn_rm(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    buttons = await _get_buttons()
    if 0 <= idx < len(buttons):
        buttons.pop(idx)
        await _set_buttons(buttons)
    await q.answer("🗑️")
    await cb_a_buttons(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_prefs$"), group=-9998)
async def cb_a_prefs(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    prefs = await _list_series_prefs()
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🎯 <b>{fb('SERIES PREFS')}</b>", DIV, ""]
    if not prefs:
        lines.append("⚪ ɴᴏɴᴇ ꜱᴇᴛ.")
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
    await _safe_edit(q, "\n".join(lines), kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_pref_add$"), group=-9998)
async def cb_a_pref_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, pref_add_name=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "",
        f"📝 {sc('send the series name')}",
        f"📌 {sc('example')} · <code>Breaking Bad</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_prefs")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_stats$"), group=-9998)
async def cb_a_stats(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    prefs = await _list_series_prefs()
    buttons = await _get_buttons()
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('STATS')}</b>",
        DIV, "",
        f"🎯 {sc('prefs')} · <code>{len(prefs)}</code>",
        f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
        f"📢 {sc('group')} · <code>{SERIES_GROUP_ID or '—'}</code>",
        f"⚙️ {sc('enabled')} · {'🟢' if SERIES_GROUP_ENABLED else '🔴'}",
        f"🕒 <code>{_now_ist()}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_stats")],
        [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")]])
    await _safe_edit(q, text, kb); await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_test$"), group=-9998)
async def cb_a_test(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    if not SERIES_GROUP_ID:
        return await q.answer("⚠️ ɴᴏ ɢʀᴏᴜᴘ ɪᴅ", show_alert=True)
    try:
        await client.send_message(
            chat_id=SERIES_GROUP_ID,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🎬 <b>{fb('SERIES SEARCH READY')}</b>",
                DIV, "",
                f"📌 {sc('type any series name')}",
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
async def sg_admin_input(client: Client, message: Message):
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
        if len(text) < 10:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
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
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
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
                     pref_title=text,
                     pref_quals=list(quals),
                     pref_selected=list(quals))

        await _show_pref_picker(client, message.chat.id, loading.id)
        return


async def _show_pref_picker(client: Client, chat_id: int, msg_id: int):
    uid = None
    for u, s in _SESSIONS.items():
        d = s.get("data") or {}
        if d.get("pref_slug"): uid = u; break
    if uid is None: return

    d = _SESSIONS[uid]["data"]
    title = d.get("pref_title")
    quals = d.get("pref_quals") or []
    selected = d.get("pref_selected") or []

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"✅ {sc('selected')} · <code>{', '.join(selected) or 'none'}</code>",
    ]
    rows = []
    row = []
    for q in quals:
        mark = "✅" if q in selected else "⬜"
        row.append(InlineKeyboardButton(f"{mark} {q}",
                                          callback_data=f"sg:a_pref_tog:{q}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("💾 SAVE", callback_data="sg:a_pref_save")])
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_prefs")])

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"[SG] pref picker: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_pref_tog:(\w+)$"), group=-9998)
async def cb_a_pref_tog(client: Client, q: CallbackQuery):
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
async def cb_a_pref_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id): return await q.answer("⛔", show_alert=True)
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    d = s["data"]
    ok = await _set_series_pref(
        d.get("pref_slug"), d.get("pref_title"),
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
            await asyncio.sleep(600)
            _cleanup_sessions()
        except asyncio.CancelledError: break
        except Exception: pass

try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception: pass


logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🎬 SERIES GROUP ULTIMATE — LOADED ✅                          ║")
logger.info("║                                                                ║")
logger.info(f"║  Group ID: {SERIES_GROUP_ID or 'NOT SET':<50}║")
logger.info(f"║  Enabled:  {'YES' if SERIES_GROUP_ENABLED else 'NO':<50}║")
logger.info("║                                                                ║")
logger.info("║  ⚠️  IF YOU SEE 2 REPLIES IN THE GROUP:                        ║")
logger.info("║      Another plugin (group_search) is also responding.         ║")
logger.info("║      Solution: Use a DIFFERENT group ID for this plugin,       ║")
logger.info("║      or delete plugins/group_search.py                         ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
