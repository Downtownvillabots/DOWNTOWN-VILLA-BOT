# plugins/missing.py
"""
🔍 DOWNTOWN VILLA — MISSING FILES FINDER

Compares TMDB with your local DB. No storage, no cache.
Results sent as plain messages (chunked if needed).
"""
# ═══════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
import asyncio
import calendar
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait
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

SESSION_TTL = 900
DIV = "━" * 26
DIV2 = "─" * 26

# Default filters (used for Hollywood + others)
MIN_POPULARITY = 5
MIN_VOTES = 20
MIN_RATING = 4.0
SKIP_ADULT = True

# Per-language filter overrides
REGIONAL_LANGS = {"ml", "ta", "te", "kn", "bn", "pa", "mr", "hi"}

def _filters_for(lang: str) -> Tuple[float, int, float]:
    """Return (min_pop, min_votes, min_rating) for a language."""
    if lang in REGIONAL_LANGS:
        return (1.0, 3, 3.0)
    if lang == "all":
        return (2.0, 10, 4.0)
    return (MIN_POPULARITY, MIN_VOTES, MIN_RATING)

# Output
MOVIES_PER_PART = 25

# Month names
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_FULL = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]

# Industries (TMDB language codes)
INDUSTRIES = [
    ("hollywood", "🇺🇸 Hollywood",   "en"),
    ("hindi",     "🇮🇳 Hindi",       "hi"),
    ("malayalam", "🇮🇳 Malayalam",   "ml"),
    ("tamil",     "🇮🇳 Tamil",       "ta"),
    ("telugu",    "🇮🇳 Telugu",      "te"),
    ("kannada",   "🇮🇳 Kannada",     "kn"),
    ("bengali",   "🇮🇳 Bengali",     "bn"),
    ("punjabi",   "🇮🇳 Punjabi",     "pa"),
    ("marathi",   "🇮🇳 Marathi",     "mr"),
    ("korean",    "🇰🇷 Korean",      "ko"),
    ("japanese",  "🇯🇵 Japanese",    "ja"),
    ("chinese",   "🇨🇳 Chinese",     "zh"),
    ("spanish",   "🇪🇸 Spanish",     "es"),
    ("turkish",   "🇹🇷 Turkish",     "tr"),
    ("arabic",    "🇸🇦 Arabic",      "ar"),
    ("french",    "🇫🇷 French",      "fr"),
    ("german",    "🇩🇪 German",      "de"),
    ("russian",   "🇷🇺 Russian",     "ru"),
    ("thai",      "🇹🇭 Thai",        "th"),
    ("indonesian","🇮🇩 Indonesian",  "id"),
    ("all",       "🌍 ALL",          "all"),
]
INDUSTRY_MAP = {code: (label, lang) for code, label, lang in INDUSTRIES}


# ═══════════════════════════════════════════════════════════════════════════
# FANCY FONTS
# ═══════════════════════════════════════════════════════════════════════════
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
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"

def _esc(t) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception: return False


# ═══════════════════════════════════════════════════════════════════════════
# DB HELPERS (read-only)
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

def _files_coll():
    d = _get_db()
    if d is None: return None
    for name in ("media_files", "files", "media"):
        try:
            c = d[name]
            if c is not None: return c
        except Exception: pass
    return None


async def _find_local_files(title: str, year: str = "") -> List[Dict[str, Any]]:
    """Fuzzy search local DB for a movie by title (first 3 words) + year."""
    c = _files_coll()
    if c is None: return []
    try:
        base = re.sub(r"[^\w\s]", " ", title or "").strip()
        base = " ".join(base.split()[:3])
        if not base: return []
        pat = re.compile(re.escape(base), re.IGNORECASE)

        clauses: List[Dict[str, Any]] = [
            {"title": pat}, {"file_name": pat}, {"series_title": pat},
        ]
        query: Dict[str, Any] = {"$or": clauses}
        if year:
            y_int = int(year) if str(year).isdigit() else year
            query = {"$and": [
                {"$or": clauses},
                {"$or": [{"year": str(year)}, {"year": y_int}]},
            ]}

        cursor = c.find(query).limit(3)
        results = await cursor.to_list(length=3)
        return results
    except Exception as e:
        logger.debug(f"[MISS] find local: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}

def _new_session(uid: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[uid] = {"token": tok, "action": action, "data": data,
                      "expires": time.time() + SESSION_TTL}
    return tok

def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s

def _clear_session(uid: int) -> None:
    _SESSIONS.pop(uid, None)

def _cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now: _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# WEEK MATH
# ═══════════════════════════════════════════════════════════════════════════
def _weeks_of_month(year: int, month: int) -> List[Tuple[int, int, int]]:
    days_in_month = calendar.monthrange(year, month)[1]
    weeks: List[Tuple[int, int, int]] = []
    start = 1
    wk = 1
    while start <= days_in_month:
        end = min(start + 6, days_in_month)
        weeks.append((wk, start, end))
        start = end + 1
        wk += 1
    return weeks


def _date_range(year: int, month: int,
                week: Optional[Tuple[int, int, int]]) -> Tuple[str, str]:
    if week is None:
        last = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"
    _, start, end = week
    return f"{year:04d}-{month:02d}-{start:02d}", f"{year:04d}-{month:02d}-{end:02d}"


# ═══════════════════════════════════════════════════════════════════════════
# TMDB FETCHER
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_request(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY:
        logger.warning("[MISS] TMDB_API_KEY missing")
        return None
    try:
        import aiohttp
    except ImportError:
        logger.warning("[MISS] aiohttp not installed")
        return None
    base = "https://api.themoviedb.org/3"
    p = {"api_key": TMDB_API_KEY, "language": "en-US", **params}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}{path}", params=p, timeout=15) as r:
                if r.status != 200:
                    logger.debug(f"[MISS] tmdb {path} status {r.status}")
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[MISS] tmdb err: {e}")
        return None


async def _fetch_movies_range(gte: str, lte: str, lang: str,
                               max_pages: int = 6) -> List[Dict[str, Any]]:
    min_pop, min_votes, min_rating = _filters_for(lang)
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        params: Dict[str, Any] = {
            "primary_release_date.gte": gte,
            "primary_release_date.lte": lte,
            "sort_by": "popularity.desc",
            "page": page,
            "include_adult": "false" if SKIP_ADULT else "true",
        }
        if lang != "all":
            params["with_original_language"] = lang

        data = await _tmdb_request("/discover/movie", params)
        if not data: break
        results = data.get("results") or []
        if not results: break

        for r in results:
            pop = r.get("popularity", 0) or 0
            rating = r.get("vote_average", 0) or 0
            votes = r.get("vote_count", 0) or 0
            if pop < min_pop: continue
            if rating and rating < min_rating: continue
            if votes < min_votes: continue

            out.append({
                "tmdb_id": r.get("id"),
                "title": r.get("title") or r.get("original_title") or "",
                "original_title": r.get("original_title") or "",
                "year": (r.get("release_date") or "")[:4],
                "release_date": r.get("release_date") or "",
                "rating": round(rating, 1),
                "votes": votes,
                "popularity": round(pop, 1),
                "lang": r.get("original_language") or "",
            })

        total_pages = data.get("total_pages", 1)
        if page >= total_pages: break
        page += 1
        await asyncio.sleep(0.15)

    return out


async def _fetch_series_range(gte: str, lte: str, lang: str,
                               max_pages: int = 6) -> List[Dict[str, Any]]:
    min_pop, min_votes, min_rating = _filters_for(lang)
    out: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        params: Dict[str, Any] = {
            "first_air_date.gte": gte,
            "first_air_date.lte": lte,
            "sort_by": "popularity.desc",
            "page": page,
            "include_adult": "false" if SKIP_ADULT else "true",
        }
        if lang != "all":
            params["with_original_language"] = lang

        data = await _tmdb_request("/discover/tv", params)
        if not data: break
        results = data.get("results") or []
        if not results: break

        for r in results:
            pop = r.get("popularity", 0) or 0
            rating = r.get("vote_average", 0) or 0
            votes = r.get("vote_count", 0) or 0
            if pop < min_pop: continue
            if rating and rating < min_rating: continue
            if votes < min_votes: continue

            out.append({
                "tmdb_id": r.get("id"),
                "title": r.get("name") or r.get("original_name") or "",
                "original_title": r.get("original_name") or "",
                "year": (r.get("first_air_date") or "")[:4],
                "release_date": r.get("first_air_date") or "",
                "rating": round(rating, 1),
                "votes": votes,
                "popularity": round(pop, 1),
                "lang": r.get("original_language") or "",
            })

        total_pages = data.get("total_pages", 1)
        if page >= total_pages: break
        page += 1
        await asyncio.sleep(0.15)

    return out


async def _find_missing(items: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict]]:
    missing: List[Dict] = []
    present: List[Dict] = []
    for item in items:
        matches = await _find_local_files(item["title"], item["year"])
        if matches:
            present.append(item)
        else:
            missing.append(item)
    return missing, present


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_type():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MOVIES", callback_data="miss:type:movie"),
         InlineKeyboardButton("📺 SERIES", callback_data="miss:type:series")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="miss:close")],
    ])


def kb_industry(kind: str):
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label, _ in INDUSTRIES:
        row.append(InlineKeyboardButton(
            label, callback_data=f"miss:ind:{kind}:{code}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="miss:back_type"),
        InlineKeyboardButton("❌ CLOSE", callback_data="miss:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_months(kind: str, ind: str, year: int):
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, m in enumerate(MONTHS, 1):
        row.append(InlineKeyboardButton(
            f"📅 {m}", callback_data=f"miss:mo:{kind}:{ind}:{year}:{i}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK",
                             callback_data=f"miss:back_ind:{kind}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="miss:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_weeks(kind: str, ind: str, year: int, month: int,
             weeks: List[Tuple[int, int, int]]):
    rows: List[List[InlineKeyboardButton]] = []
    for wk, start, end in weeks:
        rows.append([InlineKeyboardButton(
            f"📆 W{wk} · {start:02d}-{end:02d} {MONTHS[month-1]}",
            callback_data=f"miss:wk:{kind}:{ind}:{year}:{month}:{wk}"
        )])
    rows.append([InlineKeyboardButton(
        f"📅 FULL MONTH ({MONTHS_FULL[month-1]})",
        callback_data=f"miss:wk:{kind}:{ind}:{year}:{month}:0")])
    rows.append([
        InlineKeyboardButton("◀️ BACK",
                             callback_data=f"miss:back_months:{kind}:{ind}:{year}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="miss:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_after_results(kind: str, ind: str, year: int, month: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 RESCAN",
            callback_data=f"miss:mo:{kind}:{ind}:{year}:{month}")],
        [InlineKeyboardButton(
            "📅 NEW WEEK",
            callback_data=f"miss:back_months:{kind}:{ind}:{year}")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="miss:close")],
    ])


def kb_back(target: str = "miss:back_type"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ BACK", callback_data=target)],
        [InlineKeyboardButton("❌ CLOSE", callback_data="miss:close")],
    ])


def kb_back_months(kind: str, ind: str, year: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ BACK",
                              callback_data=f"miss:back_ind:{kind}")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="miss:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def _view_start() -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('MISSING FILES FINDER')}</b>",
        DIV, "",
        f"📌 {sc('find what is missing from your bot')}",
        f"📌 {sc('compare tmdb with your local db')}",
        f"📌 {sc('no storage · results as plain messages')}",
        "",
        DIV2, "",
        f"🎯 {sc('how it works')}:",
        f"1️⃣ ᴘɪᴄᴋ ᴍᴏᴠɪᴇꜱ ᴏʀ ꜱᴇʀɪᴇꜱ",
        f"2️⃣ ᴘɪᴄᴋ ɪɴᴅᴜꜱᴛʀʏ",
        f"3️⃣ ᴛʏᴘᴇ ʏᴇᴀʀ",
        f"4️⃣ ᴘɪᴄᴋ ᴍᴏɴᴛʜ",
        f"5️⃣ ᴘɪᴄᴋ ᴡᴇᴇᴋ",
        f"6️⃣ ɢᴇᴛ ᴛʜᴇ ʟɪꜱᴛ",
        "",
        DIV2, "",
        f"⚙️ {sc('filters')} · ᴘᴏᴘ ≥ {MIN_POPULARITY} · "
        f"ᴠᴏᴛᴇꜱ ≥ {MIN_VOTES} · ʀᴀᴛɪɴɢ ≥ {MIN_RATING}",
        f"📌 {sc('regional languages use relaxed filters')}",
    ])


def _view_industry(kind: str) -> str:
    label = "MOVIES" if kind == "movie" else "SERIES"
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('MISSING ' + label)}</b>",
        DIV, "",
        f"📌 {sc('pick an industry')}",
        f"📌 {sc('all = every language (slower)')}",
    ])


def _view_year_input(kind: str, ind_label: str) -> str:
    type_label = "MOVIES" if kind == "movie" else "SERIES"
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('ENTER YEAR')}</b>",
        DIV, "",
        f"🎬 {sc('type')} · <code>{type_label}</code>",
        f"🌍 {sc('industry')} · <b>{_esc(ind_label)}</b>",
        "",
        DIV2, "",
        f"📝 {sc('send the year as next message')}",
        "",
        f"📌 {sc('example')} · <code>2000</code>",
        f"📌 {sc('range')} · <code>1950 – 2027</code>",
    ])


def _view_months(kind: str, ind_label: str, year: int) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('YEAR')}</b> · <code>{year}</code>",
        DIV, "",
        f"🎬 {sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {sc('industry')} · <b>{_esc(ind_label)}</b>",
        "",
        DIV2, "",
        f"📌 {sc('pick a month to scan')}",
    ])


def _view_weeks(kind: str, ind_label: str, year: int, month: int) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{MONTHS_FULL[month-1].upper()} {year}</b>",
        DIV, "",
        f"🎬 {sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {sc('industry')} · <b>{_esc(ind_label)}</b>",
        "",
        DIV2, "",
        f"📌 {sc('pick a week to scan')}",
        f"📌 {sc('full month = slower (30-45s)')}",
        f"📌 {sc('week = fast (5-8s)')}",
    ])


# ═══════════════════════════════════════════════════════════════════════════
# SAFE EDIT
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.exception(f"[MISS] edit failed: {type(e).__name__}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# /missing COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["missing", "lackfiles", "gapscan"]) & filters.private,
    group=-460,
)
async def cmd_missing(client: Client, message: Message):
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        if not TMDB_API_KEY:
            return await message.reply_text(
                "⚠️ <b>TMDB_API_KEY ɴᴏᴛ ꜱᴇᴛ</b>\n\n"
                "ꜱᴇᴛ ɪᴛ ɪɴ ʏᴏᴜʀ ᴇɴᴠɪʀᴏɴᴍᴇɴᴛ ᴠᴀʀɪᴀʙʟᴇꜱ.",
                parse_mode=ParseMode.HTML)
        _clear_session(message.from_user.id)
        await message.reply_text(
            _view_start(), reply_markup=kb_type(),
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[MISS] /missing crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^miss:close$"), group=-460)
async def cb_close(client: Client, q: CallbackQuery):
    try:
        _clear_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^miss:back_type$"), group=-460)
async def cb_back_type(client: Client, q: CallbackQuery):
    try:
        _clear_session(q.from_user.id)
        await _safe_edit(q, _view_start(), kb_type())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_back_type: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^miss:type:(movie|series)$"), group=-460)
async def cb_type(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        _new_session(q.from_user.id, "missing_kind", kind=kind)
        await _safe_edit(q, _view_industry(kind), kb_industry(kind))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_type: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^miss:back_ind:(movie|series)$"), group=-460)
async def cb_back_ind(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        _new_session(q.from_user.id, "missing_kind", kind=kind)
        await _safe_edit(q, _view_industry(kind), kb_industry(kind))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_back_ind: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^miss:ind:(movie|series):(\w+)$"), group=-460)
async def cb_industry(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)

        if code not in INDUSTRY_MAP:
            return await q.answer("⚠️ ᴜɴᴋɴᴏᴡɴ ɪɴᴅᴜꜱᴛʀʏ", show_alert=True)

        label, lang = INDUSTRY_MAP[code]
        _new_session(q.from_user.id, "missing_year_input",
                     kind=kind, ind=code, ind_label=label, ind_lang=lang)

        await _safe_edit(q, _view_year_input(kind, label),
                         kb_back(f"miss:back_ind:{kind}"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_industry: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^miss:back_months:(movie|series):(\w+):(\d{4})$"),
    group=-460)
async def cb_back_months(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        label, _ = INDUSTRY_MAP.get(code, ("?", "en"))
        _new_session(q.from_user.id, "missing_month_pick",
                     kind=kind, ind=code, ind_label=label, year=year)
        await _safe_edit(q, _view_months(kind, label, year),
                         kb_months(kind, code, year))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_back_months: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^miss:mo:(movie|series):(\w+):(\d{4}):(\d{1,2})$"),
    group=-460)
async def cb_month(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        month = int(q.matches[0].group(4))

        if not (1 <= month <= 12):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴍᴏɴᴛʜ", show_alert=True)

        label, _ = INDUSTRY_MAP.get(code, ("?", "en"))
        weeks = _weeks_of_month(year, month)

        _new_session(q.from_user.id, "missing_week_pick",
                     kind=kind, ind=code, ind_label=label,
                     year=year, month=month)

        await _safe_edit(q, _view_weeks(kind, label, year, month),
                         kb_weeks(kind, code, year, month, weeks))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] cb_month: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^miss:wk:(movie|series):(\w+):(\d{4}):(\d{1,2}):(\d{1,2})$"),
    group=-460)
async def cb_week(client: Client, q: CallbackQuery):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        month = int(q.matches[0].group(4))
        week_num = int(q.matches[0].group(5))

        label, lang = INDUSTRY_MAP.get(code, ("?", "en"))
        weeks = _weeks_of_month(year, month)

        week_tuple: Optional[Tuple[int, int, int]] = None
        if week_num > 0:
            for w in weeks:
                if w[0] == week_num:
                    week_tuple = w
                    break
            if week_tuple is None:
                return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴡᴇᴇᴋ", show_alert=True)

        _clear_session(q.from_user.id)
        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ...")
        await _run_scan(client, q, kind, code, label, lang,
                        year, month, week_tuple)
    except Exception as e:
        logger.exception(f"[MISS] cb_week: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# YEAR INPUT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-459,
)
async def missing_year_input(client: Client, message: Message):
    if not message.from_user: return
    session = _get_session(message.from_user.id)
    if not session or session["action"] != "missing_year_input":
        return

    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()

    try:
        year = int(text)
        if year < 1950 or year > 2027:
            raise ValueError
    except (TypeError, ValueError):
        return await message.reply_text(
            "❌ ɪɴᴠᴀʟɪᴅ ʏᴇᴀʀ.\n\n"
            "📌 ꜱᴇɴᴅ ᴀ ɴᴜᴍʙᴇʀ ʙᴇᴛᴡᴇᴇɴ <code>1950</code> ᴀɴᴅ <code>2027</code>.",
            parse_mode=ParseMode.HTML)

    data = session.get("data") or {}
    kind = data.get("kind", "movie")
    code = data.get("ind", "hollywood")
    label = data.get("ind_label", "Hollywood")

    _new_session(message.from_user.id, "missing_month_pick",
                 kind=kind, ind=code, ind_label=label, year=year)

    await message.reply_text(
        _view_months(kind, label, year),
        reply_markup=kb_months(kind, code, year),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ═══════════════════════════════════════════════════════════════════════════
# THE SCANNER
# ═══════════════════════════════════════════════════════════════════════════
async def _run_scan(client: Client, q: CallbackQuery, kind: str, code: str,
                    label: str, lang: str, year: int, month: int,
                    week: Optional[Tuple[int, int, int]]) -> None:
    gte, lte = _date_range(year, month, week)

    if week is None:
        period = f"FULL {MONTHS_FULL[month-1].upper()} {year}"
        period_short = f"{MONTHS[month-1]} {year}"
    else:
        wk, start, end = week
        period = f"W{wk} · {start:02d}-{end:02d} {MONTHS_FULL[month-1]} {year}"
        period_short = f"{MONTHS[month-1]} {year} · W{wk}"

    # Progress
    try:
        progress = await q.message.edit_text(
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🔍 <b>{fb('SCANNING')}</b>",
                DIV, "",
                f"📅 {sc('period')} · <code>{_esc(period_short)}</code>",
                f"🎬 {sc('type')} · <code>{kind.upper()}</code>",
                f"🌍 {sc('industry')} · <b>{_esc(label)}</b>",
                "", DIV2, "",
                f"⏳ {sc('fetching from tmdb')}...",
            ]),
            parse_mode=ParseMode.HTML)
    except MessageNotModified:
        progress = q.message
    except Exception:
        progress = q.message

    chat_id = q.message.chat.id
    progress_id = progress.id

    # Fetch
    try:
        if kind == "movie":
            items = await _fetch_movies_range(gte, lte, lang)
        else:
            items = await _fetch_series_range(gte, lte, lang)
    except Exception as e:
        logger.exception(f"[MISS] fetch failed: {e}")
        items = []

    fetched = len(items)

    # Progress 2
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=progress_id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🔍 <b>{fb('SCANNING')}</b>",
                DIV, "",
                f"📅 {sc('period')} · <code>{_esc(period_short)}</code>",
                f"🎬 {sc('type')} · <code>{kind.upper()}</code>",
                f"🌍 {sc('industry')} · <b>{_esc(label)}</b>",
                "", DIV2, "",
                f"📥 {sc('fetched')} · <code>{_fmt_int(fetched)}</code>",
                f"🔎 {sc('comparing with your db')}...",
            ]),
            parse_mode=ParseMode.HTML)
    except Exception: pass

    # Empty
    if not items:
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=progress_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NO RESULTS')}</b>",
                    DIV, "",
                    f"📅 <code>{_esc(period_short)}</code>",
                    f"🎬 <code>{kind.upper()}</code> · 🌍 <b>{_esc(label)}</b>",
                    "", DIV2, "",
                    f"📌 {sc('no movies found on tmdb for this range')}",
                    "", f"💡 <b>{sc('try')}</b>:",
                    f"• ᴜꜱᴇ <b>FULL MONTH</b> ɪɴꜱᴛᴇᴀᴅ ᴏꜰ ᴀ ᴡᴇᴇᴋ",
                    f"• ᴛʀʏ ᴀ <b>ʀᴇᴄᴇɴᴛ ʏᴇᴀʀ</b> (2023–2025)",
                    f"• ᴛʀʏ <b>🌍 ALL</b> ɪɴᴅᴜꜱᴛʀʏ",
                    f"• ᴛᴍᴅʙ ᴍᴀʏ ɴᴏᴛ ᴄᴏᴠᴇʀ ᴛʜɪꜱ ᴘᴇʀɪᴏᴅ",
                ]),
                reply_markup=kb_after_results(kind, code, year, month),
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    missing, present = await _find_missing(items)
    in_db = len(present)
    missing_count = len(missing)

    missing.sort(key=lambda x: x.get("popularity", 0), reverse=True)

    # Delete progress
    try:
        await client.delete_messages(chat_id, progress_id)
    except Exception: pass

    # Send results
    await _send_results(
        client, chat_id, kind, label, period_short,
        fetched, in_db, missing_count, missing,
        kind_code=code, year=year, month=month,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SEND RESULTS
# ═══════════════════════════════════════════════════════════════════════════
async def _send_results(client: Client, chat_id: int, kind: str, label: str,
                        period: str, fetched: int, in_db: int, missing_count: int,
                        missing: List[Dict[str, Any]],
                        kind_code: str = "hollywood",
                        year: int = 2000, month: int = 1) -> None:
    type_label = "MOVIES" if kind == "movie" else "SERIES"

    header_lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('MISSING ' + type_label)}</b>",
        DIV, "",
        f"📅 {sc('period')} · <code>{_esc(period)}</code>",
        f"🌍 {sc('industry')} · <b>{_esc(label)}</b>",
        "",
        f"📥 {sc('fetched from tmdb')} · <code>{_fmt_int(fetched)}</code>",
        f"✅ {sc('already in your db')} · <code>{_fmt_int(in_db)}</code>",
        f"❌ {sc('missing')} · <code>{_fmt_int(missing_count)}</code>",
    ]

    # No missing → done
    if missing_count == 0:
        header_lines += [
            "", DIV2, "",
            f"🎉 <b>{sc('your db is complete for this range!')}</b>",
            f"📌 {sc('nothing to add')}",
        ]
        try:
            await client.send_message(
                chat_id=chat_id, text="\n".join(header_lines),
                reply_markup=kb_after_results(kind_code, kind_code, year, month),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"[MISS] header: {e}")
        return

    header_lines += [
        "", DIV2, "",
        f"📌 {sc('list below')} · <code>{missing_count}</code> ᴛɪᴛʟᴇꜱ",
        f"📌 {sc('sorted by popularity')}",
        f"📌 {sc('forward / save each message')}",
    ]

    try:
        await client.send_message(
            chat_id=chat_id, text="\n".join(header_lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"[MISS] header send: {e}")

    # Chunks
    total_parts = (len(missing) + MOVIES_PER_PART - 1) // MOVIES_PER_PART

    for part_idx in range(total_parts):
        chunk = missing[part_idx * MOVIES_PER_PART:
                        (part_idx + 1) * MOVIES_PER_PART]

        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔍 <b>{fb('MISSING ' + type_label)}</b>",
            f"📅 <code>{_esc(period)}</code> · 🌍 <b>{_esc(label)}</b>",
            f"📄 {sc('part')} · <code>{part_idx + 1}/{total_parts}</code>",
            DIV, "",
        ]

        base_num = part_idx * MOVIES_PER_PART + 1
        for i, m in enumerate(chunk):
            num = base_num + i
            title = m.get("title") or "?"
            yr = m.get("year") or ""
            rating = m.get("rating", 0)
            pop = m.get("popularity", 0)
            lang_code = (m.get("lang") or "").upper()

            lines.append(f"<b>{num}.</b> {_esc(title)} ({yr})")
            meta = []
            if rating: meta.append(f"⭐ {rating}")
            if pop:    meta.append(f"🎯 {pop}")
            if lang_code: meta.append(lang_code)
            if meta:
                lines.append(f"   <code>{' · '.join(meta)}</code>")
            lines.append("")

        if part_idx == total_parts - 1:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 RESCAN",
                    callback_data=f"miss:mo:{kind}:{kind_code}:{year}:{month}")],
                [InlineKeyboardButton(
                    "📅 NEW WEEK",
                    callback_data=f"miss:back_months:{kind}:{kind_code}:{year}")],
                [InlineKeyboardButton("❌ CLOSE", callback_data="miss:close")],
            ])
        else:
            kb = None

        try:
            await client.send_message(
                chat_id=chat_id, text="\n".join(lines),
                reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
            await asyncio.sleep(0.4)
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            logger.warning(f"[MISS] part {part_idx+1}: {e}")

    logger.info(f"[MISS] scan done: {missing_count} missing "
                f"({kind} · {label} · {period})")


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(600)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════
logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🔍 MISSING FILES FINDER LOADED ✅                             ║")
logger.info("║                                                                ║")
logger.info("║  Commands:                                                     ║")
logger.info("║    /missing    — find missing movies/series (admin)            ║")
logger.info("║    /lackfiles  — alias                                         ║")
logger.info("║    /gapscan    — alias                                         ║")
logger.info("║                                                                ║")
logger.info("║  Flow:                                                         ║")
logger.info("║    Type → Industry → Year → Month → Week → Results             ║")
logger.info("║                                                                ║")
logger.info("║  No storage · No cache · Plain text output                     ║")
logger.info("║  Regional languages (Malayalam, Tamil, etc.) use relaxed       ║")
logger.info("║  filters so you actually get results.                          ║")
logger.info("║                                                                ║")
logger.info("║  Env:                                                          ║")
logger.info("║    TMDB_API_KEY=xxx                                            ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
