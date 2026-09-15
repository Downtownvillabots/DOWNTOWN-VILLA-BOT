# plugins/ott.py
"""
📅 DOWNTOWN VILLA — WEEKLY OTT RELEASE SYSTEM

- Monday 10 AM IST: weekly releases to broadcast channel
- Everyone: browse days, movies, notify (subscribe)
- Admins: broadcast to channels/groups/users with custom captions
- File checker: 00-06 + 12-18 IST every 30 min
- Auto-delete: files 5h, notify msgs 12h (admin editable)
- TTL-based storage, low RAM/CPU
"""
# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
import asyncio
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import db_manager

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

# Reuse broadcast plugin
BROADCAST_OK = False
try:
    from plugins.broadcast import (
        _get_broadcast_caption, _get_broadcast_buttons,
        _build_kb_from_list, _get_all_users, _get_all_groups,
        _get_saved_channels, _schedule_autodelete, _log_broadcast,
        _get_channel, _effective_caption, _effective_buttons,
        AUTODELETE_PRESETS, AUTODELETE_SECONDS, AUTODELETE_LABELS,
    )
    BROADCAST_OK = True
except Exception as _e:
    logging.getLogger(__name__).warning(f"[OTT] broadcast helpers: {_e}")

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))

TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()
BROADCAST_CHANNEL_ID_RAW = os.getenv("BROADCAST_CHANNEL_ID", "0").strip()
try:
    BROADCAST_CHANNEL_ID = int(BROADCAST_CHANNEL_ID_RAW) or None
except (TypeError, ValueError):
    BROADCAST_CHANNEL_ID = None

# Weekly trigger — Monday 10 AM IST
WEEKLY_DAY = 0
WEEKLY_HOUR = 10
WEEKLY_MINUTE = 0

# Region / language
DEFAULT_REGION = os.getenv("OTT_REGION", "IN").upper()
DEFAULT_LANG = os.getenv("OTT_LANG", "en-US")
DEFAULT_RELEASE_TIME = os.getenv("OTT_RELEASE_TIME", "12:00")  # IST

# File checker windows (IST hours)
CHECK_WINDOWS = [(0, 6), (12, 18)]
CHECK_INTERVAL = 30 * 60      # 30 min
SCHEDULER_INTERVAL = 60        # check scheduler every 60s
CLEANUP_INTERVAL = 600         # 10 min

# Defaults (admin-overridable)
DEFAULT_FILE_TTL_HOURS = 5
DEFAULT_NOTIFY_TTL_HOURS = 12
DEFAULT_SUB_TTL_DAYS = 60

# Session
SESSION_TTL = 900

# Visual
DIV = "━" * 26
DIV2 = "─" * 26
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_ICONS = ["📅", "📆", "🗓️", "📅", "📆", "🗓️", "🎉"]

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
# SECTION 3 — HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"

def _fmt_dur(s) -> str:
    try: s = int(max(0, s))
    except (TypeError, ValueError): return "0s"
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24: return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"

def _esc(t) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception: return False

def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y · %H:%M IST")

def _now_hour_ist() -> int:
    return datetime.now(IST).hour

def _in_check_window() -> bool:
    """Are we inside a file-check window?"""
    h = _now_hour_ist()
    for start, end in CHECK_WINDOWS:
        if start <= h < end:
            return True
    return False

def _week_range_ist() -> Tuple[datetime, datetime]:
    now = datetime.now(IST)
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=7)

def _week_key() -> str:
    now = datetime.now(IST)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

def _day_date(day_idx: int) -> datetime:
    monday, _ = _week_range_ist()
    return monday + timedelta(days=day_idx)

def _day_date_str(day_idx: int) -> str:
    return _day_date(day_idx).strftime("%Y-%m-%d")

def _day_pretty(day_idx: int) -> str:
    return _day_date(day_idx).strftime("%A · %d %b %Y")

def _countdown(target_ts: float) -> str:
    delta = target_ts - time.time()
    if delta <= 0: return "🎬 released"
    if delta < 3600: return f"in {int(delta/60)}m"
    if delta < 86400: return f"in {int(delta/3600)}h"
    days = int(delta / 86400)
    if days == 1: return "tomorrow"
    return f"in {days}d"


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — DB (with TTL indexes)
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

def _weeks_coll():    d = _get_db(); return d["ott_weeks"] if d is not None else None
def _movies_coll():   d = _get_db(); return d["ott_movies"] if d is not None else None
def _subs_coll():     d = _get_db(); return d["ott_subscriptions"] if d is not None else None
def _pending_coll():  d = _get_db(); return d["ott_pending_msgs"] if d is not None else None
def _cfg_coll():      d = _get_db(); return d["ott_config"] if d is not None else None
def _sent_coll():     d = _get_db(); return d["ott_sent_log"] if d is not None else None

def _files_coll():
    """Indexed media files collection."""
    d = _get_db()
    for name in ("media_files", "files", "media"):
        try:
            c = d[name]
            if c is not None: return c
        except Exception: pass
    return None


async def _ensure_indexes():
    """Create TTL + query indexes once at boot."""
    try:
        subs = _subs_coll()
        if subs is not None:
            await subs.create_index("expires_at", expireAfterSeconds=0)
            await subs.create_index([("tmdb_id", 1), ("notified", 1)])

        pending = _pending_coll()
        if pending is not None:
            await pending.create_index("delete_at", expireAfterSeconds=0)

        weeks = _weeks_coll()
        if weeks is not None:
            await weeks.create_index("expires_at", expireAfterSeconds=0)

        movies = _movies_coll()
        if movies is not None:
            await movies.create_index("cached_at", expireAfterSeconds=30*86400)

        sent = _sent_coll()
        if sent is not None:
            await sent.create_index("sent_at", expireAfterSeconds=7*86400)

        logger.info("[OTT] indexes ready")
    except Exception as e:
        logger.warning(f"[OTT] index: {e}")


# ─── Config (single doc) ───
DEFAULT_CFG = {
    "file_ttl_hours": DEFAULT_FILE_TTL_HOURS,
    "notify_ttl_hours": DEFAULT_NOTIFY_TTL_HOURS,
    "region": DEFAULT_REGION,
    "release_time": DEFAULT_RELEASE_TIME,
    "share_button": True,
    "notify_button": True,
    "weekly_enabled": True,
}

async def _get_cfg() -> Dict[str, Any]:
    c = _cfg_coll()
    if c is None: return dict(DEFAULT_CFG)
    try:
        doc = await c.find_one({"_id": "config"}) or {}
        merged = dict(DEFAULT_CFG)
        merged.update({k: v for k, v in doc.items() if k != "_id"})
        return merged
    except Exception:
        return dict(DEFAULT_CFG)

async def _save_cfg(**fields) -> bool:
    c = _cfg_coll()
    if c is None: return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": "config"}, {"$set": fields}, upsert=True)
        return True
    except Exception as e:
        logger.warning(f"[OTT] save cfg: {e}")
        return False


# ─── Weeks ───
async def _week_save(week_key: str, days: List[List[Dict]], posted: bool = False) -> bool:
    c = _weeks_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"_id": week_key},
            {"$set": {
                "week_key": week_key, "days": days, "posted": posted,
                "updated_at": time.time(),
                "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
            }},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[OTT] week save: {e}")
        return False

async def _week_get(week_key: str) -> Optional[Dict[str, Any]]:
    c = _weeks_coll()
    if c is None: return None
    try:
        return await c.find_one({"_id": week_key})
    except Exception: return None


# ─── Movie metadata cache ───
async def _meta_save(movie: Dict[str, Any]) -> None:
    c = _movies_coll()
    if c is None: return
    try:
        await c.update_one(
            {"tmdb_id": movie["tmdb_id"]},
            {"$set": {**movie, "cached_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception: pass

async def _meta_get(tmdb_id: int) -> Optional[Dict[str, Any]]:
    c = _movies_coll()
    if c is None: return None
    try:
        return await c.find_one({"tmdb_id": int(tmdb_id)})
    except Exception: return None


# ─── Subscriptions ───
async def _sub_add(user_id: int, tmdb_id: int, title: str, year: str,
                   release_date: str) -> bool:
    c = _subs_coll()
    if c is None: return False
    try:
        expires = datetime.now(timezone.utc) + timedelta(days=DEFAULT_SUB_TTL_DAYS)
        await c.update_one(
            {"user_id": int(user_id), "tmdb_id": int(tmdb_id)},
            {"$set": {
                "user_id": int(user_id),
                "tmdb_id": int(tmdb_id),
                "title": title, "year": year,
                "release_date": release_date,
                "notified": False,
                "created_at": time.time(),
                "expires_at": expires,
            }},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.debug(f"[OTT] sub add: {e}")
        return False

async def _sub_remove(user_id: int, tmdb_id: int) -> bool:
    c = _subs_coll()
    if c is None: return False
    try:
        r = await c.delete_one({"user_id": int(user_id), "tmdb_id": int(tmdb_id)})
        return r.deleted_count > 0
    except Exception: return False

async def _sub_exists(user_id: int, tmdb_id: int) -> bool:
    c = _subs_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"user_id": int(user_id), "tmdb_id": int(tmdb_id)})
        return doc is not None
    except Exception: return False

async def _sub_count_for_movie(tmdb_id: int) -> int:
    c = _subs_coll()
    if c is None: return 0
    try:
        return await c.count_documents({"tmdb_id": int(tmdb_id)})
    except Exception: return 0

async def _sub_count_for_user(user_id: int) -> int:
    c = _subs_coll()
    if c is None: return 0
    try:
        return await c.count_documents({"user_id": int(user_id)})
    except Exception: return 0

async def _subs_for_user(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    c = _subs_coll()
    if c is None: return []
    try:
        cursor = c.find({"user_id": int(user_id)}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception: return []

async def _pending_movies_to_notify(limit: int = 50) -> List[Dict[str, Any]]:
    """Distinct tmdb_ids that have pending subscribers."""
    c = _subs_coll()
    if c is None: return []
    try:
        pipeline = [
            {"$match": {"notified": False}},
            {"$group": {
                "_id": "$tmdb_id",
                "title": {"$first": "$title"},
                "year": {"$first": "$year"},
                "release_date": {"$first": "$release_date"},
                "count": {"$sum": 1},
            }},
            {"$limit": limit},
        ]
        return await c.aggregate(pipeline).to_list(length=limit)
    except Exception: return []

async def _subs_for_movie(tmdb_id: int, limit: int = 5000) -> List[Dict[str, Any]]:
    c = _subs_coll()
    if c is None: return []
    try:
        cursor = c.find({"tmdb_id": int(tmdb_id), "notified": False}).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception: return []

async def _mark_subs_notified(tmdb_id: int) -> None:
    c = _subs_coll()
    if c is None: return
    try:
        await c.update_many(
            {"tmdb_id": int(tmdb_id)},
            {"$set": {"notified": True, "notified_at": time.time()}},
        )
    except Exception: pass


# ─── Pending auto-delete messages ───
async def _pending_add(chat_id: int, message_id: int, ttl_seconds: int) -> None:
    c = _pending_coll()
    if c is None: return
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            "created_at": time.time(),
        })
    except Exception: pass

async def _pending_due(limit: int = 100) -> List[Dict[str, Any]]:
    c = _pending_coll()
    if c is None: return []
    try:
        now = datetime.now(timezone.utc)
        cursor = c.find({"delete_at": {"$lte": now}}).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception: return []

async def _pending_remove(doc_id) -> None:
    c = _pending_coll()
    if c is None: return
    try: await c.delete_one({"_id": doc_id})
    except Exception: pass


# ─── Sent log (who received what) ───
async def _sent_log(user_id: int, tmdb_id: int, mode: str = "notify") -> None:
    c = _sent_coll()
    if c is None: return
    try:
        await c.insert_one({
            "user_id": int(user_id),
            "tmdb_id": int(tmdb_id),
            "mode": mode,
            "sent_at": datetime.now(timezone.utc),
        })
    except Exception: pass


# ─── Find local files ───
async def _find_local_files(title: str, year: str = "") -> List[Dict[str, Any]]:
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
            query = {"$and": [{"$or": clauses}, {"$or": [
                {"year": str(year)}, {"year": int(year) if year.isdigit() else year}
            ]}]}

        cursor = c.find(query).limit(10)
        results = await cursor.to_list(length=10)
        for r in results: r.pop("_id", None)
        return results
    except Exception as e:
        logger.debug(f"[OTT] find local: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — SESSIONS
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
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)




# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — TMDB FETCHER
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_request(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY:
        logger.warning("[OTT] TMDB_API_KEY missing")
        return None
    try:
        import aiohttp
    except ImportError:
        logger.warning("[OTT] aiohttp not installed")
        return None
    base = "https://api.themoviedb.org/3"
    p = {"api_key": TMDB_API_KEY, "language": DEFAULT_LANG, **params}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}{path}", params=p, timeout=15) as r:
                if r.status != 200:
                    logger.debug(f"[OTT] tmdb {path} status {r.status}")
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[OTT] tmdb err: {e}")
        return None


async def _tmdb_weekly_releases(region: str = None) -> Dict[int, List[Dict]]:
    """Return {day_index: [movie, ...]} for this week (Mon–Sun)."""
    if region is None:
        cfg = await _get_cfg()
        region = cfg.get("region", DEFAULT_REGION)

    monday, next_mon = _week_range_ist()
    gte = monday.strftime("%Y-%m-%d")
    lte = (next_mon - timedelta(days=1)).strftime("%Y-%m-%d")

    data = await _tmdb_request("/discover/movie", {
        "region": region,
        "primary_release_date.gte": gte,
        "primary_release_date.lte": lte,
        "sort_by": "popularity.desc",
        "page": 1,
    })
    if not data:
        return {i: [] for i in range(7)}

    results = data.get("results", []) or []
    by_day: Dict[int, List[Dict]] = {i: [] for i in range(7)}

    for item in results:
        rd = item.get("release_date") or ""
        if not rd: continue
        try:
            d = datetime.strptime(rd, "%Y-%m-%d").replace(tzinfo=IST)
        except Exception: continue
        idx = d.weekday()
        if not (0 <= idx <= 6): continue

        movie = {
            "tmdb_id": item.get("id"),
            "title": item.get("title") or item.get("original_title") or "",
            "overview": item.get("overview") or "",
            "poster_path": item.get("poster_path"),
            "backdrop_path": item.get("backdrop_path"),
            "release_date": rd,
            "vote_average": item.get("vote_average", 0),
            "vote_count": item.get("vote_count", 0),
            "popularity": item.get("popularity", 0),
            "original_language": item.get("original_language", ""),
            "genre_ids": item.get("genre_ids", []),
            "adult": item.get("adult", False),
            "region": region,
        }
        by_day[idx].append(movie)

    return by_day


async def _tmdb_movie_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Fetch full details for a movie."""
    return await _tmdb_request(f"/movie/{tmdb_id}", {
        "append_to_response": "watch/providers,credits,release_dates",
    })


def _poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


def _tmdb_genre_map() -> Dict[int, str]:
    return {
        28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
        80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
        14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
        9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie",
        53: "Thriller", 10752: "War", 37: "Western",
    }


def _extract_ott_provider(details: Dict[str, Any], region: str) -> str:
    try:
        providers = (details.get("watch/providers") or {}).get("results") or {}
        r = providers.get(region.upper()) or {}
        for key in ("flatrate", "free", "ads", "rent", "buy"):
            lst = r.get(key) or []
            if lst:
                name = lst[0].get("provider_name") or "—"
                suffix = ""
                if key in ("rent", "buy"):
                    suffix = f" ({key})"
                return f"{name}{suffix}"
    except Exception: pass
    return "—"


def _extract_release_info(details: Dict[str, Any], region: str) -> Dict[str, str]:
    out = {"date": "", "type": "", "certification": ""}
    try:
        rd = (details.get("release_dates") or {}).get("results") or []
        for r in rd:
            if (r.get("iso_3166_1") or "").upper() == region.upper():
                dates = r.get("release_dates") or []
                if dates:
                    first = dates[0]
                    out["date"] = (first.get("release_date") or "")[:10]
                    type_map = {1: "Premiere", 2: "Theatrical (Limited)",
                                3: "Theatrical", 4: "Digital",
                                5: "Physical", 6: "TV"}
                    out["type"] = type_map.get(first.get("type"), "")
                    out["certification"] = first.get("certification") or ""
                break
    except Exception: pass
    return out


def _extract_director(details: Dict[str, Any]) -> str:
    try:
        crew = (details.get("credits") or {}).get("crew") or []
        for c in crew:
            if (c.get("job") or "").lower() == "director":
                return c.get("name") or "—"
    except Exception: pass
    return "—"


def _extract_cast(details: Dict[str, Any], limit: int = 3) -> str:
    try:
        cast = (details.get("credits") or {}).get("cast") or []
        names = [c.get("name") for c in cast[:limit] if c.get("name")]
        return ", ".join(names) if names else "—"
    except Exception: return "—"


async def _enrich_movie(movie: Dict[str, Any], region: str = None) -> Dict[str, Any]:
    """Fetch + enrich a movie with full details, cache result."""
    if region is None:
        cfg = await _get_cfg()
        region = cfg.get("region", DEFAULT_REGION)

    # Already cached?
    cached = await _meta_get(movie["tmdb_id"])
    if cached and cached.get("overview"):
        return cached

    details = await _tmdb_movie_details(movie["tmdb_id"])
    if not details:
        return movie

    genres_map = _tmdb_genre_map()
    genre_names = ", ".join(
        genres_map.get(g.get("id"), "") for g in (details.get("genres") or [])
        if genres_map.get(g.get("id"))
    )

    enriched = {
        "tmdb_id": movie["tmdb_id"],
        "title": details.get("title") or movie.get("title") or "",
        "overview": details.get("overview") or movie.get("overview") or "",
        "poster_path": details.get("poster_path") or movie.get("poster_path"),
        "backdrop_path": details.get("backdrop_path") or movie.get("backdrop_path"),
        "release_date": details.get("release_date") or movie.get("release_date"),
        "vote_average": details.get("vote_average", movie.get("vote_average", 0)),
        "vote_count": details.get("vote_count", movie.get("vote_count", 0)),
        "runtime": details.get("runtime", 0),
        "genres": genre_names,
        "original_language": details.get("original_language", ""),
        "director": _extract_director(details),
        "cast": _extract_cast(details),
        "provider": _extract_ott_provider(details, region),
        "region": region,
        "region_release": _extract_release_info(details, region),
    }
    await _meta_save(enriched)
    return enriched


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — KEYBOARDS (all with Close button)
# ═══════════════════════════════════════════════════════════════════════════
def kb_weekly(counts: List[int]):
    rows = []
    row = []
    for i in range(7):
        label = f"{DAY_ICONS[i]} {DAY_SHORT[i]}"
        if counts[i] > 0:
            label += f" ({counts[i]})"
        row.append(InlineKeyboardButton(label, callback_data=f"ott:day:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("🔔 MY NOTIFICATIONS", callback_data="ott:mysubs"),
    ])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH", callback_data="ott:refresh"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_day_movies(day_idx: int, movies: List[Dict]):
    rows = []
    for m in movies[:20]:
        title = (m.get("title") or "?")[:34]
        rating = m.get("vote_average", 0)
        icon = "⭐" if rating >= 7 else ("🎬" if rating >= 5 else "📽️")
        rows.append([InlineKeyboardButton(
            f"{icon} {title}",
            callback_data=f"ott:mv:{m['tmdb_id']}"
        )])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="ott:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_movie_admin(tmdb_id: int):
    """Admin sees broadcast target options."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 CHANNELS", callback_data=f"ott:tgt:{tmdb_id}:channels"),
         InlineKeyboardButton("👥 GROUPS",   callback_data=f"ott:tgt:{tmdb_id}:groups")],
        [InlineKeyboardButton("👤 USERS",    callback_data=f"ott:tgt:{tmdb_id}:users"),
         InlineKeyboardButton("🎯 BOTH",     callback_data=f"ott:tgt:{tmdb_id}:both")],
        [InlineKeyboardButton("✏️ EDIT CAPTION",
                              callback_data=f"ott:cap:{tmdb_id}"),
         InlineKeyboardButton("🔘 EDIT BUTTONS",
                              callback_data=f"ott:btn:{tmdb_id}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="ott:back_day"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_movie_user(tmdb_id: int, subscribed: bool):
    """Regular user sees Notify button."""
    btn = ("🔕 UNNOTIFY" if subscribed else "🔔 NOTIFY ME")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn, callback_data=f"ott:sub:{tmdb_id}")],
        [InlineKeyboardButton("👥 MY SUBSCRIPTIONS", callback_data="ott:mysubs")],
        [InlineKeyboardButton("◀️ BACK", callback_data="ott:back_day"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_targets(tmdb_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 CHANNELS", callback_data=f"ott:tgt:{tmdb_id}:channels"),
         InlineKeyboardButton("👥 GROUPS",   callback_data=f"ott:tgt:{tmdb_id}:groups")],
        [InlineKeyboardButton("👤 USERS",    callback_data=f"ott:tgt:{tmdb_id}:users"),
         InlineKeyboardButton("🎯 BOTH",     callback_data=f"ott:tgt:{tmdb_id}:both")],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"ott:mv:{tmdb_id}"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_channels_pick(tmdb_id: int, channels: List[Dict]):
    rows = []
    for c in channels:
        title = (c.get("title") or "?")[:38]
        cid = c.get("chat_id")
        rows.append([InlineKeyboardButton(
            f"📢 {title}",
            callback_data=f"ott:send_ch:{tmdb_id}:{cid}"
        )])
    rows.append([InlineKeyboardButton(
        "🎯 ALL CHANNELS",
        callback_data=f"ott:send_ch_all:{tmdb_id}")])
    rows.append([InlineKeyboardButton(
        "◀️ BACK", callback_data=f"ott:tgt:{tmdb_id}:channels"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")])
    return InlineKeyboardMarkup(rows)


def kb_when_picker(tmdb_id: int, release_date: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 SEND NOW",
                              callback_data=f"ott:when:{tmdb_id}:now")],
        [InlineKeyboardButton("📅 SCHEDULE FOR RELEASE DATE",
                              callback_data=f"ott:when:{tmdb_id}:sched")],
        [InlineKeyboardButton("⏱️ PICK CUSTOM TIME",
                              callback_data=f"ott:when:{tmdb_id}:custom")],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"ott:tgt:{tmdb_id}:users"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_autodelete_picker(tmdb_id: int, mode: str, cid: Optional[int] = None,
                         window: str = "file"):
    """window = 'file' (after get-file) or 'notify' (pre-release msg)."""
    rows = []
    row = []
    if window == "file":
        opts = [(1, "1H"), (3, "3H"), (5, "5H"), (12, "12H"), (24, "24H"), (0, "NEVER")]
    else:
        opts = [(6, "6H"), (12, "12H"), (24, "24H"), (48, "48H"), (72, "72H"), (0, "NEVER")]
    for h, label in opts:
        cb = f"ott:adt:{tmdb_id}:{mode}:{window}:{h}"
        if cid is not None:
            cb += f":{cid}"
        icon = "♾️" if h == 0 else "⏱️"
        row.append(InlineKeyboardButton(f"{icon} {label}", callback_data=cb))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"ott:tgt:{tmdb_id}:{mode}")])
    return InlineKeyboardMarkup(rows)


def kb_confirm(tmdb_id: int, mode: str, file_h: int, cid: Optional[int] = None,
               when: str = "now"):
    cb_send = f"ott:send_go:{tmdb_id}:{mode}:{file_h}:{when}"
    if cid is not None:
        cb_send += f":{cid}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ CONFIRM SEND", callback_data=cb_send)],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"ott:tgt:{tmdb_id}:{mode}"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_notify_msg(tmdb_id: int, share_enabled: bool = True):
    """The button set inside the file notification message."""
    rows = [[InlineKeyboardButton("📥 GET FILE",
                                  callback_data=f"ott:getfile:{tmdb_id}")]]
    if share_enabled:
        rows.append([InlineKeyboardButton(
            "📤 SHARE", callback_data=f"ott:share:{tmdb_id}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")])
    return InlineKeyboardMarkup(rows)


def kb_sent_file(tmdb_id: int, share_enabled: bool = True):
    rows = []
    if share_enabled:
        rows.append([InlineKeyboardButton(
            "📤 SHARE", callback_data=f"ott:share:{tmdb_id}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")])
    return InlineKeyboardMarkup(rows)


def kb_mysubs(subs: List[Dict[str, Any]]):
    rows = []
    for s in subs[:15]:
        title = (s.get("title") or "?")[:32]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=f"ott:mv:{s.get('tmdb_id')}"
        )])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="ott:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_settings(cfg: Dict[str, Any]):
    file_h = cfg.get("file_ttl_hours", 5)
    notify_h = cfg.get("notify_ttl_hours", 12)
    region = cfg.get("region", "IN")
    rel_time = cfg.get("release_time", "12:00")
    share = cfg.get("share_button", True)
    notify = cfg.get("notify_button", True)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⏱️ FILE TTL · {file_h}H",
                              callback_data="ott:set_file_ttl")],
        [InlineKeyboardButton(f"⏱️ NOTIFY TTL · {notify_h}H",
                              callback_data="ott:set_notify_ttl")],
        [InlineKeyboardButton(f"🌍 REGION · {region}",
                              callback_data="ott:set_region")],
        [InlineKeyboardButton(f"🕐 RELEASE TIME · {rel_time} IST",
                              callback_data="ott:set_reltime")],
        [InlineKeyboardButton(f"📤 SHARE BTN · {'ON' if share else 'OFF'}",
                              callback_data="ott:tog_share"),
         InlineKeyboardButton(f"🔔 NOTIFY BTN · {'ON' if notify else 'OFF'}",
                              callback_data="ott:tog_notify")],
        [InlineKeyboardButton("◀️ BACK", callback_data="ott:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")],
    ])


def kb_back(target: str = "ott:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def _build_weekly_message(week_key: str, by_day: Dict[int, List[Dict]]) -> str:
    counts = [len(by_day.get(i, [])) for i in range(7)]
    total = sum(counts)
    mon = _day_date(0).strftime("%d %b")
    sun = _day_date(6).strftime("%d %b %Y")

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('WEEKLY OTT RELEASES')}</b>",
        DIV, "",
        f"🗓️ {sc('week')} · <code>{mon} → {sun}</code>",
        f"🎬 {sc('total releases')} · <code>{total}</code>",
        "",
        DIV2, "",
        f"📌 {sc('tap a day below to see movies')}",
        f"📌 {sc('tap any movie for full details')}",
        f"📌 {sc('notify when files arrive')}",
        "",
        DIV2,
    ]
    for i in range(7):
        cnt = counts[i]
        if cnt == 0:
            lines.append(f"{DAY_ICONS[i]} {DAY_SHORT[i]} · —")
        else:
            lines.append(f"{DAY_ICONS[i]} <b>{DAY_SHORT[i]}</b> · "
                         f"<code>{cnt}</code> ʀᴇʟᴇᴀꜱᴇ{'ꜱ' if cnt != 1 else ''}")
    lines += [
        "", DIV2,
        f"🕒 {sc('updated')} · <code>{_now_ist()}</code>",
        f"🆔 <code>{week_key}</code>",
    ]
    return "\n".join(lines)


async def _view_day(day_idx: int) -> Tuple[str, InlineKeyboardMarkup]:
    week_key = _week_key()
    w = await _week_get(week_key) or {}
    days = w.get("days") or []
    movies = days[day_idx] if 0 <= day_idx < len(days) else []

    pretty = _day_pretty(day_idx)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('RELEASES')}</b>",
        f"<code>{_esc(pretty)}</code>",
        DIV, "",
    ]
    if not movies:
        lines.append("⚪ ɴᴏ ʀᴇʟᴇᴀꜱᴇꜱ ᴛʜɪꜱ ᴅᴀʏ.")
    else:
        lines.append(f"🎬 <b>{len(movies)}</b> ʀᴇʟᴇᴀꜱᴇ{'ꜱ' if len(movies) != 1 else ''}")
        lines.append("")
        for m in movies[:20]:
            title = m.get("title") or "?"
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0)
            lang = (m.get("original_language") or "").upper()
            lines.append(f"⭐ <b>{_esc(title)}</b> ({year})")
            meta = []
            if rating: meta.append(f"{rating:.1f}/10")
            if lang:   meta.append(lang)
            if meta:
                lines.append(f"   🎯 <code>{' · '.join(meta)}</code>")
            lines.append("")
    return "\n".join(lines), kb_day_movies(day_idx, movies)


async def _view_movie(tmdb_id: int, user_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup, Optional[str]]]:
    """Return (text, keyboard, poster_url). Admin sees broadcast, user sees notify."""
    # Get raw from week cache first
    week_key = _week_key()
    w = await _week_get(week_key) or {}
    days = w.get("days") or []
    raw = None
    for day_movies in days:
        for m in day_movies:
            if int(m.get("tmdb_id", 0)) == int(tmdb_id):
                raw = m; break
        if raw: break

    if raw is None:
        raw = await _meta_get(tmdb_id)
    if raw is None:
        details = await _tmdb_movie_details(tmdb_id)
        if not details: return None
        raw = {
            "tmdb_id": tmdb_id,
            "title": details.get("title") or "",
            "overview": details.get("overview") or "",
            "poster_path": details.get("poster_path"),
            "release_date": details.get("release_date") or "",
            "vote_average": details.get("vote_average", 0),
            "vote_count": details.get("vote_count", 0),
            "original_language": details.get("original_language", ""),
        }

    movie = await _enrich_movie(raw)

    # Files?
    year = (movie.get("release_date") or "")[:4]
    files = await _find_local_files(movie.get("title", ""), year)
    has_files = len(files) > 0

    # Subscription check
    is_admin = _is_admin(user_id)
    subscribed = False
    if not is_admin:
        subscribed = await _sub_exists(user_id, tmdb_id)

    # Subscriber count for admins
    sub_count = 0
    if is_admin:
        sub_count = await _sub_count_for_movie(tmdb_id)

    title = movie.get("title") or "?"
    yr = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0)
    votes = movie.get("vote_count", 0)
    runtime = movie.get("runtime", 0) or 0
    genres = movie.get("genres") or ""
    overview = (movie.get("overview") or "")[:600]
    provider = movie.get("provider") or "—"
    orig_lang = (movie.get("original_language") or "").upper()
    director = movie.get("director") or "—"
    cast = movie.get("cast") or "—"
    rel = movie.get("region_release") or {}
    region = movie.get("region", DEFAULT_REGION)

    cfg = await _get_cfg()
    rel_time = cfg.get("release_time", "12:00")

    lines = [
        f"🎬 <b>{_esc(title)}</b> ({yr})",
        DIV, "",
        f"⭐ {sc('rating')} · <code>{rating:.1f}/10</code> · "
        f"<code>{_fmt_int(votes)}</code> ᴠᴏᴛᴇꜱ",
        f"🎭 {sc('genres')} · <code>{_esc(genres or '—')}</code>",
        f"⏱️ {sc('runtime')} · <code>{runtime} ᴍɪɴ</code>",
        f"🌐 {sc('language')} · <code>{orig_lang or '—'}</code>",
        f"🎥 {sc('director')} · <code>{_esc(director)}</code>",
        f"👥 {sc('cast')} · <code>{_esc(cast)}</code>",
        "", DIV2, "",
        f"📅 {sc('release date')} · <code>{rel.get('date') or movie.get('release_date') or '—'}</code>",
        f"🕐 {sc('release time')} · <code>{rel_time} IST</code>",
        f"🏷️ {sc('release type')} · <code>{rel.get('type') or '—'}</code>",
        f"🔞 {sc('certification')} · <code>{rel.get('certification') or '—'}</code>",
        f"📺 {sc('streaming on')} · <b>{_esc(provider)}</b>",
        f"🌍 {sc('region')} · <code>{region}</code>",
        "", DIV2, "",
    ]
    if overview:
        lines.append(f"📖 <b>{sc('plot')}</b>")
        lines.append(f"<i>{_esc(overview)}</i>")
        lines.append("")

    if is_admin:
        lines += [
            DIV2, "",
            f"🔔 {sc('subscribers waiting')} · <code>{_fmt_int(sub_count)}</code>",
            f"📁 {sc('files in db')} · <code>{len(files) if has_files else 0}</code>",
            "",
            f"📌 {sc('choose where to broadcast')}",
        ]
        kb = kb_movie_admin(tmdb_id)
    else:
        if subscribed:
            lines += [f"🔔 {sc('you will be notified when files arrive')}"]
        else:
            lines += [f"🔕 {sc('tap notify to be alerted when files arrive')}"]
        kb = kb_movie_user(tmdb_id, subscribed)

    poster = _poster_url(movie.get("poster_path"), size="w500")
    return "\n".join(lines), kb, poster


async def _view_mysubs(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    subs = await _subs_for_user(user_id)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔔 <b>{fb('MY NOTIFICATIONS')}</b>",
        DIV, "",
    ]
    if not subs:
        lines.append("⚪ ʏᴏᴜ ʜᴀᴠᴇ ɴᴏ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴꜱ ʏᴇᴛ.")
        lines.append("")
        lines.append("📌 ᴛᴀᴘ ᴀɴʏ ᴍᴏᴠɪᴇ ᴀɴᴅ ᴘʀᴇꜱꜱ 🔔 NOTIFY ᴛᴏ ꜱᴛᴀʀᴛ.")
    else:
        lines.append(f"📊 <b>{len(subs)}</b> ᴍᴏᴠɪᴇꜱ")
        lines.append("")
        for s in subs[:15]:
            title = s.get("title") or "?"
            notified = s.get("notified", False)
            icon = "✅" if notified else "🔔"
            rel_date = s.get("release_date") or ""
            lines.append(f"{icon} <b>{_esc(title)}</b>")
            if rel_date:
                lines.append(f"   📅 <code>{rel_date}</code>")
            lines.append("")
    return "\n".join(lines), kb_mysubs(subs)


async def _view_settings() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await _get_cfg()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{fb('OTT SETTINGS')}</b>",
        DIV, "",
        f"⏱️ {sc('file ttl')} · <code>{cfg.get('file_ttl_hours', 5)}h</code>",
        f"⏱️ {sc('notify msg ttl')} · <code>{cfg.get('notify_ttl_hours', 12)}h</code>",
        f"🌍 {sc('region')} · <code>{cfg.get('region', 'IN')}</code>",
        f"🕐 {sc('release time')} · <code>{cfg.get('release_time', '12:00')} IST</code>",
        f"📤 {sc('share button')} · {'🟢 ᴏɴ' if cfg.get('share_button') else '🔴 ᴏꜰꜰ'}",
        f"🔔 {sc('notify button')} · {'🟢 ᴏɴ' if cfg.get('notify_button') else '🔴 ᴏꜰꜰ'}",
        "", DIV2, "",
        f"📌 {sc('file ttl')} — ꜰɪʟᴇꜱ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ᴀꜰᴛᴇʀ ᴜꜱᴇʀ ɢᴇᴛꜱ ᴛʜᴇᴍ",
        f"📌 {sc('notify ttl')} — ᴘʀᴇ-ʀᴇʟᴇᴀꜱᴇ ᴍꜱɢ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇꜱ ɪꜰ ɴᴏ ᴀᴄᴛɪᴏɴ",
    ]
    return "\n".join(lines), kb_settings(cfg)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — SAFE EDIT
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.debug(f"[OTT] edit: {type(e).__name__}: {e}")
        return False


async def _safe_edit_or_resend(client: Client, target, text: str, kb=None,
                               poster_url: Optional[str] = None,
                               chat_id: Optional[int] = None) -> None:
    """If poster_url given, replace text message with photo message."""
    if poster_url:
        try:
            await target.message.delete()
        except Exception: pass
        try:
            await client.send_photo(
                chat_id=chat_id or target.message.chat.id,
                photo=poster_url,
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception as e:
            logger.debug(f"[OTT] photo send: {e}")
    await _safe_edit(target, text, kb)



# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — COMMANDS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command(["ott", "releases", "weekly"]) & filters.private, group=-470)
async def cmd_ott(client: Client, message: Message):
    """Anyone can open the OTT panel."""
    try:
        try:
            panel = await message.reply_text("📅 ʟᴏᴀᴅɪɴɢ ᴡᴇᴇᴋʟʏ ʀᴇʟᴇᴀꜱᴇꜱ...")
        except Exception: return

        week_key = _week_key()
        w = await _week_get(week_key)

        if not w or not w.get("days"):
            by_day = await _tmdb_weekly_releases()
            days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
            await _week_save(week_key, days, posted=False)
            counts = [len(by_day.get(i, [])) for i in range(7)]
            text = _build_weekly_message(week_key, by_day)
        else:
            days = w.get("days") or []
            counts = [len(days[i]) if i < len(days) else 0 for i in range(7)]
            by_day = {i: (days[i] if i < len(days) else []) for i in range(7)}
            text = _build_weekly_message(week_key, by_day)

        await _safe_edit(panel, text, kb_weekly(counts))
    except Exception as e:
        logger.exception(f"[OTT] /ott crashed: {e}")


@Client.on_message(filters.command(["mysubs", "myott"]) & filters.private, group=-470)
async def cmd_mysubs(client: Client, message: Message):
    try:
        text, kb = await _view_mysubs(message.from_user.id)
        await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[OTT] /mysubs: {e}")


@Client.on_message(filters.command(["ott_settings"]) & filters.private, group=-470)
async def cmd_ott_settings(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        text, kb = await _view_settings()
        await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[OTT] /ott_settings: {e}")


@Client.on_message(filters.command(["ott_post"]) & filters.private, group=-470)
async def cmd_ott_post(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    ok = await _post_weekly(client, force=True)
    await message.reply_text("✅ ᴘᴏꜱᴛᴇᴅ ᴛᴏ ᴄʜᴀɴɴᴇʟ" if ok else "❌ ꜰᴀɪʟᴇᴅ")


@Client.on_message(filters.command(["ott_subs"]) & filters.private, group=-470)
async def cmd_ott_subs(client: Client, message: Message):
    """Admin: list top movies by subscriber count."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        pending = await _pending_movies_to_notify(limit=50)
        if not pending:
            return await message.reply_text("⚪ ɴᴏ ᴘᴇɴᴅɪɴɢ ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴꜱ.")
        pending.sort(key=lambda x: x.get("count", 0), reverse=True)
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('TOP PENDING MOVIES')}</b>",
            DIV, "",
        ]
        for p in pending[:20]:
            title = p.get("title") or "?"
            yr = p.get("year") or ""
            cnt = p.get("count", 0)
            lines.append(f"🎬 <b>{_esc(title)}</b> ({yr})")
            lines.append(f"   🔔 <code>{_fmt_int(cnt)}</code> ᴡᴀɪᴛɪɴɢ")
            lines.append("")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[OTT] /ott_subs: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — MAIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:main$"), group=-470)
async def cb_main(client: Client, q: CallbackQuery):
    try:
        week_key = _week_key()
        w = await _week_get(week_key)
        if not w or not w.get("days"):
            by_day = await _tmdb_weekly_releases()
            days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
            await _week_save(week_key, days, posted=False)
        else:
            days = w.get("days") or []
            by_day = {i: (days[i] if i < len(days) else []) for i in range(7)}

        counts = [len(by_day.get(i, [])) for i in range(7)]
        text = _build_weekly_message(week_key, by_day)
        await _safe_edit(q, text, kb_weekly(counts))
        await q.answer()
    except Exception as e:
        logger.exception(f"[OTT] cb_main: {e}")
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^ott:close$"), group=-470)
async def cb_close(client: Client, q: CallbackQuery):
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^ott:refresh$"), group=-470)
async def cb_refresh(client: Client, q: CallbackQuery):
    await q.answer("🔄 ʀᴇꜰʀᴇꜱʜɪɴɢ...")
    try:
        week_key = _week_key()
        by_day = await _tmdb_weekly_releases()
        days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
        await _week_save(week_key, days)
        counts = [len(by_day.get(i, [])) for i in range(7)]
        text = _build_weekly_message(week_key, by_day)
        await _safe_edit(q, text, kb_weekly(counts))
    except Exception as e:
        logger.exception(f"[OTT] refresh: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — DAY VIEW
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:day:(\d)$"), group=-470)
async def cb_day(client: Client, q: CallbackQuery):
    idx = int(q.matches[0].group(1))
    try:
        sess = _SESSIONS.setdefault(q.from_user.id, {})
        sess["last_day"] = idx
        text, kb = await _view_day(idx)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[OTT] cb_day: {e}")


@Client.on_callback_query(filters.regex(r"^ott:back_day$"), group=-470)
async def cb_back_day(client: Client, q: CallbackQuery):
    sess = _SESSIONS.get(q.from_user.id) or {}
    idx = sess.get("last_day", 0)
    try:
        text, kb = await _view_day(idx)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[OTT] cb_back_day: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — MOVIE CARD
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:mv:(\d+)$"), group=-470)
async def cb_movie(client: Client, q: CallbackQuery):
    tmdb_id = int(q.matches[0].group(1))
    await q.answer("🔄 ʟᴏᴀᴅɪɴɢ...")
    try:
        r = await _view_movie(tmdb_id, q.from_user.id)
        if r is None:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        text, kb, poster = r
        await _safe_edit_or_resend(
            client, q, text, kb, poster_url=poster,
            chat_id=q.message.chat.id,
        )
    except Exception as e:
        logger.exception(f"[OTT] cb_movie: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — NOTIFY (SUBSCRIBE / UNSUBSCRIBE)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:sub:(\d+)$"), group=-470)
async def cb_sub(client: Client, q: CallbackQuery):
    tmdb_id = int(q.matches[0].group(1))
    uid = q.from_user.id

    try:
        exists = await _sub_exists(uid, tmdb_id)
        if exists:
            await _sub_remove(uid, tmdb_id)
            await q.answer("🔕 ɴᴏᴛɪꜰɪᴄᴀᴛɪᴏɴ ᴏꜰꜰ")
        else:
            # Get movie title from cache
            m = await _meta_get(tmdb_id) or {}
            title = m.get("title") or "?"
            year = (m.get("release_date") or "")[:4]
            rel_date = m.get("release_date") or ""
            ok = await _sub_add(uid, tmdb_id, title, year, rel_date)
            if ok:
                await q.answer("🔔 ʏᴏᴜ'ʟʟ ʙᴇ ɴᴏᴛɪꜰɪᴇᴅ!")
            else:
                return await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)

        # Refresh the card
        r = await _view_movie(tmdb_id, uid)
        if r:
            text, kb, poster = r
            await _safe_edit_or_resend(
                client, q, text, kb, poster_url=poster,
                chat_id=q.message.chat.id,
            )
    except Exception as e:
        logger.exception(f"[OTT] cb_sub: {e}")


@Client.on_callback_query(filters.regex(r"^ott:mysubs$"), group=-470)
async def cb_mysubs(client: Client, q: CallbackQuery):
    try:
        text, kb = await _view_mysubs(q.from_user.id)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[OTT] cb_mysubs: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 15 — ADMIN: EDIT CAPTION / BUTTONS FOR A MOVIE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:cap:(\d+)$"), group=-470)
async def cb_edit_caption(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "edit_ott_caption", tmdb_id=tmdb_id)

    m = await _meta_get(tmdb_id) or {}
    cur = m.get("custom_caption")
    cur_disp = cur if cur else "(using default caption)"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION FOR MOVIE')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(m.get('title'))}</b>",
        "", DIV2, "",
        f"<b>{sc('current')}:</b>",
        f"<code>{_esc(cur_disp[:200])}</code>",
        "", DIV2, "",
        f"📌 {sc('send the new caption as next message')}",
        f"📌 {sc('placeholders')}: <code>{{file_name}}</code>, <code>{{year}}</code>,",
        f"   <code>{{rating}}</code>, <code>{{provider}}</code>, <code>{{release_date}}</code>",
        f"📌 {sc('send')} <code>-</code> {sc('to reset to default')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data=f"ott:mv:{tmdb_id}"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:btn:(\d+)$"), group=-470)
async def cb_edit_buttons(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    m = await _meta_get(tmdb_id) or {}
    custom = m.get("custom_buttons")

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('CUSTOM BUTTONS')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(m.get('title'))}</b>",
        "", DIV2, "",
    ]
    if custom is None:
        lines.append(f"🌐 {sc('using global default buttons')}")
    elif not custom:
        lines.append(f"⚪ {sc('no custom buttons set')}")
    else:
        for i, b in enumerate(custom, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")

    rows = []
    if custom is not None:
        for i, b in enumerate(custom, 1):
            rows.append([InlineKeyboardButton(
                f"🗑️ {i}. {(b.get('name') or '?')[:30]}",
                callback_data=f"ott:btn_rm:{tmdb_id}:{i-1}")])
        rows.append([InlineKeyboardButton("➕ ADD BUTTON",
                                          callback_data=f"ott:btn_add:{tmdb_id}")])
        rows.append([InlineKeyboardButton("♻️ RESET TO DEFAULT",
                                          callback_data=f"ott:btn_rst:{tmdb_id}")])
    else:
        rows.append([InlineKeyboardButton("✏️ SET CUSTOM BUTTONS",
                                          callback_data=f"ott:btn_custom:{tmdb_id}")])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"ott:mv:{tmdb_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ])
    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:btn_custom:(\d+)$"), group=-470)
async def cb_btn_custom(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    c = _movies_coll()
    if c is not None:
        await c.update_one({"tmdb_id": tmdb_id},
                           {"$set": {"custom_buttons": []}})
    await q.answer("✏️ ᴇᴍᴘᴛʏ ᴄᴜꜱᴛᴏᴍ ꜱᴇᴛ")
    await cb_edit_buttons(client, q)


@Client.on_callback_query(filters.regex(r"^ott:btn_rst:(\d+)$"), group=-470)
async def cb_btn_rst(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    c = _movies_coll()
    if c is not None:
        await c.update_one({"tmdb_id": tmdb_id},
                           {"$unset": {"custom_buttons": ""}})
    await q.answer("♻️ ʀᴇꜱᴇᴛ")
    await cb_edit_buttons(client, q)


@Client.on_callback_query(filters.regex(r"^ott:btn_add:(\d+)$"), group=-470)
async def cb_btn_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    _new_session(q.from_user.id, "add_ott_button", tmdb_id=tmdb_id)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
        "", f"📌 {sc('example')}:",
        f"<code>Join Channel | https://t.me/mychannel</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data=f"ott:btn:{tmdb_id}"),
    ]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:btn_rm:(\d+):(\d+)$"), group=-470)
async def cb_btn_rm(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    idx = int(q.matches[0].group(2))
    m = await _meta_get(tmdb_id) or {}
    btns = list(m.get("custom_buttons") or [])
    if 0 <= idx < len(btns):
        btns.pop(idx)
        c = _movies_coll()
        if c is not None:
            await c.update_one({"tmdb_id": tmdb_id},
                               {"$set": {"custom_buttons": btns}})
    await q.answer("🗑️ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_edit_buttons(client, q)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — SETTINGS CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:set_file_ttl$"), group=-470)
async def cb_set_file_ttl(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    rows = []
    row = []
    for h, label in [(1, "1H"), (3, "3H"), (5, "5H"), (12, "12H"),
                     (24, "24H"), (48, "48H"), (72, "72H"), (0, "NEVER")]:
        row.append(InlineKeyboardButton(
            f"⏱️ {label}", callback_data=f"ott:set_file_ttl_save:{h}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ott:settings")])
    text = f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n⏱️ <b>{fb('FILE TTL')}</b>\n{DIV}\n\n" \
           f"📌 {sc('how long files stay in user DM after Get File')}"
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:set_file_ttl_save:(\d+)$"), group=-470)
async def cb_set_file_ttl_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    h = int(q.matches[0].group(1))
    await _save_cfg(file_ttl_hours=h)
    await q.answer(f"✅ {h}h")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:set_notify_ttl$"), group=-470)
async def cb_set_notify_ttl(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    rows = []
    row = []
    for h, label in [(6, "6H"), (12, "12H"), (24, "24H"),
                     (48, "48H"), (72, "72H"), (0, "NEVER")]:
        row.append(InlineKeyboardButton(
            f"⏱️ {label}", callback_data=f"ott:set_notify_ttl_save:{h}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ott:settings")])
    text = f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n⏱️ <b>{fb('NOTIFY MSG TTL')}</b>\n{DIV}\n\n" \
           f"📌 {sc('how long pre-release msg stays if user does nothing')}"
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:set_notify_ttl_save:(\d+)$"), group=-470)
async def cb_set_notify_ttl_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    h = int(q.matches[0].group(1))
    await _save_cfg(notify_ttl_hours=h)
    await q.answer(f"✅ {h}h")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:set_region$"), group=-470)
async def cb_set_region(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    regions = [("IN", "🇮🇳 India"), ("US", "🇺🇸 USA"),
               ("GB", "🇬🇧 UK"), ("AU", "🇦🇺 Australia"),
               ("CA", "🇨🇦 Canada"), ("AE", "🇦🇪 UAE")]
    rows = [[InlineKeyboardButton(label,
                                  callback_data=f"ott:set_region_save:{code}")]
            for code, label in regions]
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ott:settings")])
    text = f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n🌍 <b>{fb('REGION')}</b>\n{DIV}\n\n" \
           f"📌 {sc('which region for release dates & providers')}"
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:set_region_save:(\w+)$"), group=-470)
async def cb_set_region_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    code = q.matches[0].group(1)
    await _save_cfg(region=code)
    await q.answer(f"✅ {code}")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:set_reltime$"), group=-470)
async def cb_set_reltime(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    times = ["00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00"]
    rows = [[InlineKeyboardButton(f"🕐 {t} IST",
                                  callback_data=f"ott:set_reltime_save:{t}")]
            for t in times]
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ott:settings")])
    text = f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n🕐 <b>{fb('RELEASE TIME')}</b>\n{DIV}\n\n" \
           f"📌 {sc('default release time shown to users (IST)')}"
    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:set_reltime_save:(\d+:\d+)$"), group=-470)
async def cb_set_reltime_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    t = q.matches[0].group(1)
    await _save_cfg(release_time=t)
    await q.answer(f"✅ {t} IST")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:tog_share$"), group=-470)
async def cb_tog_share(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cfg = await _get_cfg()
    new_val = not cfg.get("share_button", True)
    await _save_cfg(share_button=new_val)
    await q.answer("🟢 ᴏɴ" if new_val else "🔴 ᴏꜰꜰ")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:tog_notify$"), group=-470)
async def cb_tog_notify(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cfg = await _get_cfg()
    new_val = not cfg.get("notify_button", True)
    await _save_cfg(notify_button=new_val)
    await q.answer("🟢 ᴏɴ" if new_val else "🔴 ᴏꜰꜰ")
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)


@Client.on_callback_query(filters.regex(r"^ott:settings$"), group=-470)
async def cb_settings(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await _view_settings()
    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17 — TEXT INPUT HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=-468)
async def ott_session_input(client: Client, message: Message):
    if not message.from_user: return
    session = _get_session(message.from_user.id)
    if not session: return

    action = session["action"]
    text = (message.text or "").strip()
    logger.info(f"[OTT] input action={action}")

    try: message.stop_propagation()
    except Exception: pass

    # ─── EDIT MOVIE CAPTION ───
    if action == "edit_ott_caption":
        tmdb_id = session["data"].get("tmdb_id")
        if not tmdb_id:
            _clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇꜱꜱɪᴏɴ.")

        new_cap = None if text == "-" else text
        if new_cap is not None and len(new_cap) < 3:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ. ꜱᴇɴᴅ '-' ᴛᴏ ʀᴇꜱᴇᴛ.")

        c = _movies_coll()
        if c is not None:
            if new_cap is None:
                await c.update_one({"tmdb_id": tmdb_id},
                                   {"$unset": {"custom_caption": ""}})
            else:
                await c.update_one({"tmdb_id": tmdb_id},
                                   {"$set": {"custom_caption": new_cap}})

        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n<code>{_esc(new_cap or '(default)')[:200]}</code>",
            parse_mode=ParseMode.HTML)
        return

    # ─── ADD MOVIE BUTTON ───
    if action == "add_ott_button":
        tmdb_id = session["data"].get("tmdb_id")
        if not tmdb_id:
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

        m = await _meta_get(tmdb_id) or {}
        btns = list(m.get("custom_buttons") or [])
        if len(btns) >= 6:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 6 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({"name": name[:60], "url": url, "position": len(btns) + 1})
        c = _movies_coll()
        if c is not None:
            await c.update_one({"tmdb_id": tmdb_id},
                               {"$set": {"custom_buttons": btns}})

        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ</b>\n\n"
            f"📛 <b>{_esc(name)}</b>\n🔗 <code>{_esc(url)}</code>",
            parse_mode=ParseMode.HTML)
        return

    _clear_session(message.from_user.id)
    await message.reply_text("⚠️ ᴜɴᴋɴᴏᴡɴ ꜱᴇꜱꜱɪᴏɴ.")



# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18 — TARGET PICKER (CHANNELS / GROUPS / USERS / BOTH)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:tgt:(\d+):(channels|groups|users|both)$"), group=-470)
async def cb_target(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)

    tmdb_id = int(q.matches[0].group(1))
    mode = q.matches[0].group(2)

    # CHANNELS → show channel list
    if mode == "channels":
        channels = await _get_saved_channels() if BROADCAST_OK else []
        if not channels:
            return await q.answer("⚠️ ɴᴏ ꜱᴀᴠᴇᴅ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
        m = await _meta_get(tmdb_id) or {}
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📢 <b>{fb('PICK CHANNEL')}</b>",
            DIV, "",
            f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
            "", DIV2, "",
            f"📌 {sc('which channel should receive this?')}",
        ])
        await _safe_edit(q, text, kb_channels_pick(tmdb_id, channels))
        return await q.answer()

    # USERS → show when-to-send picker
    if mode == "users":
        m = await _meta_get(tmdb_id) or {}
        rel_date = m.get("release_date") or "—"
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"⏰ <b>{fb('WHEN TO SEND?')}</b>",
            DIV, "",
            f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
            f"📅 {sc('releases')} · <code>{rel_date}</code>",
            "", DIV2, "",
            f"🚀 {sc('send now')} — ɪᴍᴍᴇᴅɪᴀᴛᴇ",
            f"📅 {sc('schedule')} — ᴀᴛ ʀᴇʟᴇᴀꜱᴇ ᴅᴀᴛᴇ",
            f"⏱️ {sc('custom')} — ᴘɪᴄᴋ ᴛɪᴍᴇ",
        ])
        await _safe_edit(q, text, kb_when_picker(tmdb_id, rel_date))
        return await q.answer()

    # GROUPS or BOTH → straight to auto-delete picker (file TTL)
    target_count = 0
    try:
        if mode == "groups" and BROADCAST_OK:
            target_count = len(await _get_all_groups())
        elif mode == "both" and BROADCAST_OK:
            u = len(await _get_all_users())
            g = len(await _get_all_groups())
            target_count = u + g
    except Exception: pass

    m = await _meta_get(tmdb_id) or {}
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('FILE AUTO-DELETE')}</b>",
        DIV, "",
        f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
        f"🎯 {sc('target')} · <b>{mode.upper()}</b> · <code>{_fmt_int(target_count)}</code>",
        "", DIV2, "",
        f"📌 {sc('files auto-delete after this time')}",
        f"📌 {sc('pick NEVER to keep forever')}",
    ])
    await _safe_edit(q, text, kb_autodelete_picker(tmdb_id, mode, window="file"))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:send_ch:(\d+):(-?\d+)$"), group=-470)
async def cb_send_ch_single(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    cid = int(q.matches[0].group(2))
    # File TTL picker with channel id
    m = await _meta_get(tmdb_id) or {}
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('FILE AUTO-DELETE')}</b>",
        DIV, "",
        f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
        f"📢 {sc('channel')} · <code>{cid}</code>",
        "", DIV2, "",
        f"📌 {sc('files auto-delete after this time')}",
    ])
    await _safe_edit(q, text, kb_autodelete_picker(tmdb_id, "channel", cid=cid, window="file"))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^ott:send_ch_all:(\d+)$"), group=-470)
async def cb_send_ch_all(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    m = await _meta_get(tmdb_id) or {}
    channels = await _get_saved_channels() if BROADCAST_OK else []
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('FILE AUTO-DELETE')}</b>",
        DIV, "",
        f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
        f"📢 {sc('all channels')} · <code>{len(channels)}</code>",
        "", DIV2, "",
        f"📌 {sc('files auto-delete after this time')}",
    ])
    await _safe_edit(q, text, kb_autodelete_picker(tmdb_id, "channels", window="file"))
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 19 — WHEN-TO-SEND PICKER (USERS ONLY)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:when:(\d+):(now|sched|custom)$"), group=-470)
async def cb_when(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    tmdb_id = int(q.matches[0].group(1))
    when = q.matches[0].group(2)

    if when == "now":
        # Straight to auto-delete picker (file TTL)
        m = await _meta_get(tmdb_id) or {}
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"⏱️ <b>{fb('FILE AUTO-DELETE')}</b>",
            DIV, "",
            f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
            f"⏰ {sc('send')} · <code>NOW</code>",
            "", DIV2, "",
            f"📌 {sc('files auto-delete after this time')}",
        ])
        await _safe_edit(q, text, kb_autodelete_picker(tmdb_id, "users",
                                                        window="file"))
        await q.answer()
        return

    if when == "sched":
        # Auto-delete picker first, then schedule automatically
        _new_session(q.from_user.id, "ott_sched_mode", tmdb_id=tmdb_id,
                     when="sched")
        m = await _meta_get(tmdb_id) or {}
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"⏱️ <b>{fb('FILE AUTO-DELETE')}</b>",
            DIV, "",
            f"🎬 {sc('movie')} · <b>{_esc(m.get('title'))}</b>",
            f"📅 {sc('schedule')} · <code>RELEASE DATE</code>",
            "", DIV2, "",
            f"📌 {sc('files auto-delete after this time')}",
        ])
        await _safe_edit(q, text, kb_autodelete_picker(tmdb_id, "users",
                                                        window="file"))
        await q.answer()
        return

    if when == "custom":
        # Ask for custom date+time via text session
        _new_session(q.from_user.id, "ott_custom_time", tmdb_id=tmdb_id)
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"⏱️ <b>{fb('CUSTOM SCHEDULE TIME')}</b>",
            DIV, "",
            f"📝 {sc('send date & time in this format')}:",
            "",
            f"<code>YYYY-MM-DD HH:MM</code>",
            "", f"📌 {sc('example')}:",
            f"<code>2026-12-15 18:30</code>",
            "", f"📌 {sc('timezone')} · <code>IST</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL", callback_data=f"ott:tgt:{tmdb_id}:users"),
        ]])
        await _safe_edit(q, text, kb)
        await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 20 — AUTO-DELETE PICKER → CONFIRM
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^ott:adt:(\d+):(users|groups|both|channel|channels):(file|notify):(\d+)(?::(-?\d+))?$"),
    group=-470)
async def cb_autodelete(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    tmdb_id = int(q.matches[0].group(1))
    mode = q.matches[0].group(2)
    window = q.matches[0].group(3)   # file | notify
    hours = int(q.matches[0].group(4))
    cid_raw = q.matches[0].group(5)
    cid = int(cid_raw) if cid_raw else None

    m = await _meta_get(tmdb_id) or {}
    title = m.get("title") or "?"
    rel_date = m.get("release_date") or "—"

    # Which "when" did admin pick?
    sess = _get_session(q.from_user.id) or {}
    when = (sess.get("data") or {}).get("when", "now")
    if when not in ("now", "sched", "custom"):
        when = "now"

    # Auto-delete label
    if window == "file":
        ad_label = "♾️ NEVER" if hours == 0 else f"⏱️ {hours}H"
    else:
        ad_label = "♾️ NEVER" if hours == 0 else f"⏱️ {hours}H"

    when_label = {
        "now": "🚀 NOW",
        "sched": f"📅 {rel_date} @ 12:00 IST",
        "custom": "⏱️ CUSTOM (see next step)",
    }.get(when, "🚀 NOW")

    target_count = 0
    try:
        if mode == "users" and BROADCAST_OK:
            target_count = len(await _get_all_users())
        elif mode == "groups" and BROADCAST_OK:
            target_count = len(await _get_all_groups())
        elif mode == "both" and BROADCAST_OK:
            target_count = (len(await _get_all_users())
                            + len(await _get_all_groups()))
        elif mode == "channels" and BROADCAST_OK:
            target_count = len(await _get_saved_channels())
        elif mode == "channel" and cid:
            target_count = 1
    except Exception: pass

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"🎬 {sc('movie')} · <b>{_esc(title)}</b>",
        f"🎯 {sc('target')} · <b>{mode.upper()}</b> · <code>{_fmt_int(target_count)}</code>",
        f"⏰ {sc('when')} · {when_label}",
        f"⏱️ {sc('file ttl')} · {ad_label}",
        "",
        DIV2, "",
        f"📌 {sc('files auto-delete after this time')}",
        f"📌 {sc('uses custom caption & buttons if set')}",
        f"📌 {sc('or global default otherwise')}",
    ])

    await _safe_edit(q, text, kb_confirm(tmdb_id, mode, hours, cid=cid, when=when))
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 21 — CONFIRM → RUN BROADCAST
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^ott:send_go:(\d+):(users|groups|both|channel|channels):(\d+):(now|sched|custom)(?::(-?\d+))?$"),
    group=-470)
async def cb_send_go(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    tmdb_id = int(q.matches[0].group(1))
    mode = q.matches[0].group(2)
    file_h = int(q.matches[0].group(3))
    when = q.matches[0].group(4)
    cid_raw = q.matches[0].group(5)
    cid = int(cid_raw) if cid_raw else None

    if when == "custom":
        # Need to collect time first
        _new_session(q.from_user.id, "ott_custom_time_final",
                     tmdb_id=tmdb_id, mode=mode, file_h=file_h, cid=cid)
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"⏱️ <b>{fb('CUSTOM SCHEDULE TIME')}</b>",
            DIV, "",
            f"📝 {sc('send date & time in this format')}:",
            "",
            f"<code>YYYY-MM-DD HH:MM</code>",
            "", f"📌 {sc('example')}: <code>2026-12-15 18:30</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL",
                                 callback_data=f"ott:mv:{tmdb_id}"),
        ]])
        await _safe_edit(q, text, kb)
        return await q.answer()

    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    await _run_ott_broadcast(
        client, q, tmdb_id=tmdb_id, mode=mode,
        cid=cid, file_hours=file_h, when=when,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 22 — CAPTION / BUTTONS FOR MOVIE (effective)
# ═══════════════════════════════════════════════════════════════════════════
async def _effective_movie_caption(tmdb_id: int, movie: Dict[str, Any]) -> str:
    """Return the caption for this movie (custom > channel > global > fallback)."""
    # 1. Movie custom
    custom = movie.get("custom_caption")
    if custom:
        return custom

    # 2. Global (or channel) from broadcast plugin
    if BROADCAST_OK:
        try:
            global_cap = await _get_broadcast_caption()
        except Exception:
            global_cap = None
    else:
        global_cap = None

    if not global_cap:
        global_cap = (
            "🎬 <b>{file_name}</b>\n"
            "📦 <code>{file_size}</code>\n"
            "⭐ {rating}"
        )
    return global_cap


def _build_movie_button_kb(movie: Dict[str, Any],
                           custom_buttons: Optional[List[Dict]] = None,
                           share_enabled: bool = True) -> Optional[InlineKeyboardMarkup]:
    """Build KB for the movie. Priority: movie custom > global default."""
    btns = custom_buttons
    if btns is None:
        btns = movie.get("custom_buttons")

    rows: List[List[InlineKeyboardButton]] = []

    if btns:
        for b in btns:
            name = (b.get("name") or "").strip()
            url = (b.get("url") or "").strip()
            if name and url:
                rows.append([InlineKeyboardButton(name[:60], url=url)])
    elif BROADCAST_OK:
        try:
            if _build_kb_from_list:
                # fall through to global
                pass
        except Exception: pass

    if share_enabled:
        rows.append([InlineKeyboardButton("📤 SHARE",
                                          callback_data="ott:share:auto")])

    if not rows:
        return None
    return InlineKeyboardMarkup(rows)


async def _effective_movie_buttons(tmdb_id: int,
                                    movie: Dict[str, Any]) -> Optional[List[Dict]]:
    """Get the effective button list (movie custom > global default)."""
    custom = movie.get("custom_buttons")
    if custom is not None:
        return custom
    if BROADCAST_OK:
        try:
            return await _get_broadcast_buttons()
        except Exception: pass
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 23 — THE BROADCAST ENGINE
# ═══════════════════════════════════════════════════════════════════════════
async def _run_ott_broadcast(
    client: Client,
    q: CallbackQuery,
    tmdb_id: int,
    mode: str,                     # users | groups | both | channel | channels
    cid: Optional[int] = None,
    file_hours: int = 5,
    when: str = "now",
    custom_ts: Optional[float] = None,
    notify_mode: bool = True,      # True → include Notify button (pre-release)
):
    """
    Broadcast a movie with the selected target/timing.
    notify_mode = True → 'Notify + Get File' buttons (pre-release)
    notify_mode = False → 'Get File' only (files already available)
    """
    movie = await _meta_get(tmdb_id)
    if not movie:
        try:
            details = await _tmdb_movie_details(tmdb_id)
            if details:
                movie = await _enrich_movie({
                    "tmdb_id": tmdb_id,
                    "title": details.get("title") or "",
                    "release_date": details.get("release_date") or "",
                    "poster_path": details.get("poster_path"),
                    "overview": details.get("overview") or "",
                    "vote_average": details.get("vote_average", 0),
                    "vote_count": details.get("vote_count", 0),
                    "original_language": details.get("original_language", ""),
                })
        except Exception: pass
    if not movie:
        return await q.answer("⚠️ ᴍᴇᴛᴀ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

    # Resolve targets
    targets: List[int] = []
    try:
        if mode == "channel" and cid:
            targets = [cid]
        elif mode == "channels" and BROADCAST_OK:
            chans = await _get_saved_channels()
            targets = [c.get("chat_id") for c in chans if c.get("chat_id")]
        elif mode == "users" and BROADCAST_OK:
            targets = await _get_all_users()
        elif mode == "groups" and BROADCAST_OK:
            targets = await _get_all_groups()
        elif mode == "both" and BROADCAST_OK:
            u = await _get_all_users()
            g = await _get_all_groups()
            targets = u + g
    except Exception as e:
        logger.warning(f"[OTT] resolve targets: {e}")

    if not targets:
        return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)

    # Find files
    year = (movie.get("release_date") or "")[:4]
    files = await _find_local_files(movie.get("title", ""), year)
    files_available = len(files) > 0

    # Build caption
    cap_tmpl = await _effective_movie_caption(tmdb_id, movie)
    rating = movie.get("vote_average", 0) or "—"
    provider = movie.get("provider") or "—"
    overview = (movie.get("overview") or "")[:250]
    title_str = movie.get("title") or "?"
    rel_date = movie.get("release_date") or "—"
    cfg = await _get_cfg()
    rel_time = cfg.get("release_time", "12:00")

    try:
        caption = cap_tmpl.format(
            file_name=title_str,
            file_size="—",
            rating=rating,
            year=year,
            file_caption=title_str,
            provider=provider,
            release_date=rel_date,
        )
    except Exception:
        caption = f"🎬 <b>{_esc(title_str)}</b>"

    # Append extra OTT info
    caption += (
        f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        f"\n📅 <b>Release</b> · <code>{rel_date} · {rel_time} IST</code>"
        f"\n📺 <b>Streaming on</b> · <b>{_esc(provider)}</b>"
    )
    if overview:
        caption += f"\n\n<i>{_esc(overview)}</i>"

    # Buttons
    share_enabled = cfg.get("share_button", True)
    notify_enabled = cfg.get("notify_button", True) and notify_mode

    movie_btns = await _effective_movie_buttons(tmdb_id, movie)
    btn_rows: List[List[InlineKeyboardButton]] = []
    if movie_btns:
        for b in movie_btns:
            name = (b.get("name") or "").strip()
            url = (b.get("url") or "").strip()
            if name and url:
                btn_rows.append([InlineKeyboardButton(name[:60], url=url)])

    if notify_enabled:
        btn_rows.append([InlineKeyboardButton(
            "🔔 NOTIFY ME", callback_data=f"ott:sub:{tmdb_id}")])
    if files_available:
        btn_rows.append([InlineKeyboardButton(
            "📥 GET FILE", callback_data=f"ott:getfile:{tmdb_id}")])
    if share_enabled:
        btn_rows.append([InlineKeyboardButton(
            "📤 SHARE", callback_data=f"ott:share:{tmdb_id}")])

    kb = InlineKeyboardMarkup(btn_rows) if btn_rows else None

    # Progress message
    progress_chat = q.message.chat.id
    try:
        progress = await q.message.edit_text(
            f"🏨 <b>{fb('BROADCAST STARTED')}</b>\n{DIV}\n\n"
            f"📤 {sc('sending to')} <b>{_fmt_int(len(targets))}</b>...",
            parse_mode=ParseMode.HTML)
    except MessageNotModified:
        progress = q.message
    except Exception:
        progress = q.message

    # Poster URL — need big poster
    poster_url = _poster_url(movie.get("poster_path"), size="w500")

    # Send loop
    start_ts = time.time()
    sent = 0; failed = 0; blocked = 0
    file_ttl_seconds = file_hours * 3600 if file_hours > 0 else 0
    notify_ttl_seconds = cfg.get("notify_ttl_hours", 12) * 3600

    for i, tid in enumerate(targets):
        try:
            sent_msg = None
            # If files exist → send them directly; else send poster (pre-release)
            if files_available and mode in ("channel", "channels"):
                for f in files[:3]:
                    fc = f.get("chat_id") or f.get("source_chat_id")
                    fm = f.get("message_id") or f.get("msg_id")
                    if not (fc and fm):
                        continue
                    try:
                        sent_msg = await client.copy_message(
                            chat_id=tid, from_chat_id=fc, message_id=fm,
                            caption=caption, reply_markup=kb)
                    except Exception as e:
                        logger.debug(f"[OTT] copy file: {e}")
            elif poster_url:
                # Send as photo with caption
                try:
                    sent_msg = await client.send_photo(
                        chat_id=tid, photo=poster_url,
                        caption=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML)
                except Exception:
                    # fallback text
                    sent_msg = await client.send_message(
                        chat_id=tid, text=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True)
            else:
                sent_msg = await client.send_message(
                    chat_id=tid, text=caption, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)

            sent += 1
            await asyncio.sleep(0.05)

            # Auto-delete pre-release / files
            if sent_msg:
                ttl = file_ttl_seconds if files_available else notify_ttl_seconds
                if ttl > 0:
                    try:
                        await _pending_add(tid, sent_msg.id, ttl)
                    except Exception: pass
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            failed += 1
            logger.debug(f"[OTT] send {tid}: {type(e).__name__}: {e}")

        # Progress update (throttled)
        if i % max(1, len(targets) // 10) == 0 or i + 1 >= len(targets):
            elapsed = max(0.001, time.time() - start_ts)
            speed = (i + 1) / elapsed
            pct = (i + 1) / len(targets) * 100
            filled = int(14 * pct / 100)
            bar = "🟩" * filled + "⬛" * (14 - filled)
            try:
                await client.edit_message_text(
                    chat_id=progress_chat, message_id=progress.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"📢 <b>{fb('BROADCAST IN PROGRESS')}</b>",
                        DIV, "",
                        f"🎬 <b>{_esc(title_str)}</b>",
                        "", f"{bar} {pct:.1f}%", "",
                        f"✅ {sc('sent')} · <code>{_fmt_int(sent)}</code>",
                        f"❌ {sc('failed')} · <code>{_fmt_int(failed)}</code>",
                        f"📊 {sc('progress')} · <code>{i+1}/{len(targets)}</code>",
                        f"⚡ {sc('speed')} · <code>{speed:.1f}/s</code>",
                    ]),
                    parse_mode=ParseMode.HTML)
            except Exception: pass

    # Final
    elapsed = time.time() - start_ts
    try:
        await client.edit_message_text(
            chat_id=progress_chat, message_id=progress.id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"✅ <b>{fb('BROADCAST COMPLETE')}</b>",
                DIV, "",
                f"🎬 <b>{_esc(title_str)}</b>",
                "",
                f"✅ {sc('sent')} · <code>{_fmt_int(sent)}</code>",
                f"❌ {sc('failed')} · <code>{_fmt_int(failed)}</code>",
                f"🕒 {sc('time')} · <code>{_fmt_dur(elapsed)}</code>",
            ]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")]]),
            parse_mode=ParseMode.HTML)
    except Exception: pass

    # Log
    if BROADCAST_OK:
        try:
            await _log_broadcast({
                "job_id": f"ott-{tmdb_id}",
                "kind": mode,
                "admin_id": q.from_user.id,
                "total": len(targets), "sent": sent, "failed": failed,
                "blocked": blocked, "deleted": 0,
                "elapsed": elapsed, "status": "completed",
                "autodelete_seconds": file_ttl_seconds,
            })
        except Exception: pass



# ═══════════════════════════════════════════════════════════════════════════
# SECTION 24 — CUSTOM TIME INPUT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=-467)
async def ott_custom_time_input(client: Client, message: Message):
    if not message.from_user: return
    session = _get_session(message.from_user.id)
    if not session: return

    action = session["action"]
    if action not in ("ott_custom_time", "ott_custom_time_final"):
        return

    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()
    # Parse YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    except Exception:
        return await message.reply_text(
            "❌ ɪɴᴠᴀʟɪᴅ ꜰᴏʀᴍᴀᴛ.\n\n"
            "📌 ꜰᴏʀᴍᴀᴛ: <code>YYYY-MM-DD HH:MM</code>\n"
            "📌 ᴇxᴀᴍᴘʟᴇ: <code>2026-12-15 18:30</code>",
            parse_mode=ParseMode.HTML)

    if dt.timestamp() <= time.time():
        return await message.reply_text("❌ ᴛɪᴍᴇ ᴍᴜꜱᴛ ʙᴇ ɪɴ ᴛʜᴇ ꜰᴜᴛᴜʀᴇ.")

    data = session.get("data") or {}
    tmdb_id = data.get("tmdb_id")
    _clear_session(message.from_user.id)

    if not tmdb_id:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇꜱꜱɪᴏɴ.")

    # If this is the "final" flow, we already have mode + file_hours
    if action == "ott_custom_time_final":
        mode = data.get("mode", "users")
        file_h = data.get("file_h", 5)
        cid = data.get("cid")
        await message.reply_text(
            f"✅ <b>ꜱᴄʜᴇᴅᴜʟᴇᴅ</b>\n\n"
            f"📅 <code>{dt.strftime('%d %b %Y · %H:%M IST')}</code>\n\n"
            f"📌 ᴛʜᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴡɪʟʟ ꜰɪʀᴇ ᴀᴛ ᴛʜᴀᴛ ᴛɪᴍᴇ.",
            parse_mode=ParseMode.HTML)
        # (Scheduling queue would go here — for now, immediate send)
        await _run_ott_broadcast(
            client, None, tmdb_id=tmdb_id, mode=mode,
            cid=cid, file_hours=file_h, when="custom",
            custom_ts=dt.timestamp())
    else:
        # Just show the picker again with custom timestamp
        m = await _meta_get(tmdb_id) or {}
        await message.reply_text(
            f"✅ ᴛɪᴍᴇ ꜱᴀᴠᴇᴅ: <code>{dt.strftime('%d %b %Y · %H:%M IST')}</code>\n\n"
            f"📌 ɴᴏᴡ ᴄʜᴏᴏꜱᴇ ᴛᴀʀɢᴇᴛ & ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ.",
            reply_markup=kb_targets(tmdb_id),
            parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 25 — SHARE BUTTON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:share:(\d+|auto)$"), group=-470)
async def cb_share(client: Client, q: CallbackQuery):
    """Copy the current message to a user-specified chat."""
    try:
        # Simple: prompt user to forward manually, or use copy to saved messages
        await q.answer("📤 ʟᴏɴɢ-ᴘʀᴇꜱꜱ ᴛʜᴇ ᴍᴇꜱꜱᴀɢᴇ ᴀɴᴅ ꜰᴏʀᴡᴀʀᴅ ɪᴛ.", show_alert=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 26 — GET FILE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ott:getfile:(\d+)$"), group=-470)
async def cb_get_file(client: Client, q: CallbackQuery):
    """Send the files for a movie to the user."""
    tmdb_id = int(q.matches[0].group(1))
    uid = q.from_user.id
    await q.answer("🔎 ꜰɪɴᴅɪɴɢ ꜰɪʟᴇꜱ...")

    try:
        movie = await _meta_get(tmdb_id)
        if not movie:
            return await q.answer("⚠️ ᴍᴇᴛᴀ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        year = (movie.get("release_date") or "")[:4]
        files = await _find_local_files(movie.get("title", ""), year)
        if not files:
            return await q.answer(
                "⏳ ꜰɪʟᴇꜱ ɴᴏᴛ ʏᴇᴛ ᴀᴠᴀɪʟᴀʙʟᴇ · ʏᴏᴜ'ʟʟ ʙᴇ ɴᴏᴛɪꜰɪᴇᴅ",
                show_alert=True)

        cfg = await _get_cfg()
        file_h = cfg.get("file_ttl_hours", 5)
        file_ttl = file_h * 3600 if file_h > 0 else 0
        share_enabled = cfg.get("share_button", True)

        sent_count = 0
        for f in files[:3]:
            fc = f.get("chat_id") or f.get("source_chat_id")
            fm = f.get("message_id") or f.get("msg_id")
            if not (fc and fm):
                continue
            try:
                sent = await client.copy_message(
                    chat_id=uid, from_chat_id=fc, message_id=fm,
                    reply_markup=kb_sent_file(tmdb_id, share_enabled))
                sent_count += 1
                if sent and file_ttl > 0:
                    try:
                        await _pending_add(uid, sent.id, file_ttl)
                    except Exception: pass
            except Exception as e:
                logger.debug(f"[OTT] get file: {e}")

        if sent_count == 0:
            return await q.answer("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ", show_alert=True)

        await _sent_log(uid, tmdb_id, mode="getfile")
    except Exception as e:
        logger.exception(f"[OTT] get_file: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 27 — FILE CHECKER LOOP (only 00-06 & 12-18 IST, every 30 min)
# ═══════════════════════════════════════════════════════════════════════════
async def _file_checker_loop(client: Client):
    """Check pending subscriptions; notify if files now available."""
    await asyncio.sleep(120)
    while True:
        try:
            if not _in_check_window():
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            # Get distinct tmdb_ids with pending subscribers (batched)
            pending = await _pending_movies_to_notify(limit=30)
            if not pending:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for item in pending:
                tmdb_id = item.get("_id")
                if not tmdb_id: continue

                movie = await _meta_get(tmdb_id)
                if not movie: continue

                year = (movie.get("release_date") or "")[:4]
                files = await _find_local_files(movie.get("title", ""), year)
                if not files:
                    continue   # still not available

                # Files available → notify all subscribers
                await _notify_subscribers(client, tmdb_id, movie, files)

        except asyncio.CancelledError: break
        except Exception as e:
            logger.warning(f"[OTT] checker loop: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 28 — NOTIFY SUBSCRIBERS
# ═══════════════════════════════════════════════════════════════════════════
async def _notify_subscribers(client: Client, tmdb_id: int,
                               movie: Dict[str, Any],
                               files: List[Dict[str, Any]]) -> None:
    """Send the notify message to all subscribers of a movie."""
    subs = await _subs_for_movie(tmdb_id, limit=5000)
    if not subs:
        return

    cfg = await _get_cfg()
    notify_ttl = cfg.get("notify_ttl_hours", 12) * 3600
    share_enabled = cfg.get("share_button", True)

    # Build caption
    cap_tmpl = await _effective_movie_caption(tmdb_id, movie)
    rating = movie.get("vote_average", 0) or "—"
    provider = movie.get("provider") or "—"
    overview = (movie.get("overview") or "")[:250]
    title_str = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rel_date = movie.get("release_date") or "—"
    rel_time = cfg.get("release_time", "12:00")

    try:
        caption = cap_tmpl.format(
            file_name=title_str, file_size="—", rating=rating,
            year=year, file_caption=title_str,
            provider=provider, release_date=rel_date)
    except Exception:
        caption = f"🎬 <b>{_esc(title_str)}</b>"

    caption += (
        f"\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
        f"\n✅ <b>Now Available!</b>"
        f"\n📅 <code>{rel_date} · {rel_time} IST</code>"
        f"\n📺 <b>{_esc(provider)}</b>"
    )
    if overview:
        caption += f"\n\n<i>{_esc(overview)}</i>"

    # Notify KB
    kb_rows: List[List[InlineKeyboardButton]] = []

    movie_btns = await _effective_movie_buttons(tmdb_id, movie)
    if movie_btns:
        for b in movie_btns:
            name = (b.get("name") or "").strip()
            url = (b.get("url") or "").strip()
            if name and url:
                kb_rows.append([InlineKeyboardButton(name[:60], url=url)])

    kb_rows.append([InlineKeyboardButton("📥 GET FILE",
                                          callback_data=f"ott:getfile:{tmdb_id}")])
    if share_enabled:
        kb_rows.append([InlineKeyboardButton("📤 SHARE",
                                              callback_data=f"ott:share:{tmdb_id}")])
    kb_rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="ott:close")])
    kb = InlineKeyboardMarkup(kb_rows)

    poster_url = _poster_url(movie.get("poster_path"), size="w500")

    sent = 0; failed = 0
    for s in subs:
        uid = int(s.get("user_id"))
        try:
            sent_msg = None
            if poster_url:
                try:
                    sent_msg = await client.send_photo(
                        chat_id=uid, photo=poster_url,
                        caption=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML)
                except Exception:
                    sent_msg = await client.send_message(
                        chat_id=uid, text=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True)
            else:
                sent_msg = await client.send_message(
                    chat_id=uid, text=caption, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)

            sent += 1
            await asyncio.sleep(0.05)

            if sent_msg and notify_ttl > 0:
                try:
                    await _pending_add(uid, sent_msg.id, notify_ttl)
                except Exception: pass
            try:
                await _sent_log(uid, tmdb_id, mode="notify")
            except Exception: pass
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            failed += 1
            logger.debug(f"[OTT] notify {uid}: {type(e).__name__}: {e}")

    await _mark_subs_notified(tmdb_id)
    logger.info(f"[OTT] notified {sent} subs of '{title_str}' (failed={failed})")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 29 — PENDING AUTO-DELETE LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _pending_delete_loop(client: Client):
    """Delete expired pre-release / file messages."""
    await asyncio.sleep(180)
    while True:
        try:
            due = await _pending_due(limit=200)
            if due:
                deleted = 0; failed = 0
                for doc in due:
                    cid = doc.get("chat_id"); mid = doc.get("message_id")
                    if not (cid and mid):
                        await _pending_remove(doc.get("_id")); continue
                    try:
                        await client.delete_messages(int(cid), int(mid))
                        deleted += 1
                    except Exception:
                        failed += 1
                    await _pending_remove(doc.get("_id"))
                if deleted or failed:
                    logger.info(f"[OTT-AD] deleted={deleted} failed={failed}")
        except asyncio.CancelledError: break
        except Exception as e:
            logger.warning(f"[OTT-AD] loop: {e}")
        await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 30 — WEEKLY POST LOOP (Monday 10 AM IST)
# ═══════════════════════════════════════════════════════════════════════════
_LAST_POST_KEY: Optional[str] = None


async def _post_weekly(client: Client, force: bool = False) -> bool:
    global _LAST_POST_KEY
    if not BROADCAST_CHANNEL_ID:
        logger.warning("[OTT] BROADCAST_CHANNEL_ID not set")
        return False

    cfg = await _get_cfg()
    if not cfg.get("weekly_enabled", True) and not force:
        return False

    week_key = _week_key()
    if not force and _LAST_POST_KEY == week_key:
        return False

    # Fetch
    try:
        by_day = await _tmdb_weekly_releases()
    except Exception as e:
        logger.warning(f"[OTT] weekly fetch: {e}")
        return False

    days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
    await _week_save(week_key, days, posted=True)

    counts = [len(by_day.get(i, [])) for i in range(7)]
    text = _build_weekly_message(week_key, by_day)
    kb = kb_weekly(counts)

    try:
        await client.send_message(
            chat_id=BROADCAST_CHANNEL_ID,
            text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
        _LAST_POST_KEY = week_key
        logger.info(f"[OTT] weekly posted: {week_key}")
        return True
    except Exception as e:
        logger.warning(f"[OTT] weekly post: {e}")
        return False


async def _weekly_loop(client: Client):
    """Fires Monday 10:00 AM IST."""
    await asyncio.sleep(60)
    last_trigger: Optional[str] = None
    while True:
        try:
            now = datetime.now(IST)
            today_key = now.strftime("%Y-%m-%d")

            if (now.weekday() == WEEKLY_DAY
                    and now.hour == WEEKLY_HOUR
                    and now.minute < 5
                    and last_trigger != today_key):
                last_trigger = today_key
                await _post_weekly(client)
        except asyncio.CancelledError: break
        except Exception as e:
            logger.warning(f"[OTT] weekly loop: {e}")
        await asyncio.sleep(SCHEDULER_INTERVAL)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 31 — CLEANUP LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL)
            _cleanup_sessions()
        except asyncio.CancelledError: break
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 32 — BOOT
# ═══════════════════════════════════════════════════════════════════════════
_BOOTED = False


@Client.on_message(filters.private, group=-466)
async def _capture_bot(client: Client, message: Message):
    global _BOOTED
    if _BOOTED: return
    _BOOTED = True
    try:
        # Create TTL indexes
        await _ensure_indexes()
        # Start loops
        loop = asyncio.get_event_loop()
        loop.create_task(_weekly_loop(client))
        loop.create_task(_file_checker_loop(client))
        loop.create_task(_pending_delete_loop(client))
        loop.create_task(_cleanup_loop())
        logger.info("[OTT] background loops started")
    except Exception as e:
        logger.warning(f"[OTT] boot: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════
logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  📅 OTT WEEKLY SYSTEM LOADED ✅                                ║")
logger.info("║                                                                ║")
logger.info("║  Commands:                                                     ║")
logger.info("║    /ott            — open weekly releases (anyone)             ║")
logger.info("║    /releases       — same                                      ║")
logger.info("║    /weekly         — same                                      ║")
logger.info("║    /mysubs         — my subscriptions (anyone)                 ║")
logger.info("║    /ott_settings   — admin settings                            ║")
logger.info("║    /ott_post       — admin: post weekly now                    ║")
logger.info("║    /ott_subs       — admin: subscriber counts                  ║")
logger.info("║                                                                ║")
logger.info("║  Auto:                                                         ║")
logger.info("║    Mon 10:00 IST    — weekly post to channel                   ║")
logger.info("║    00-06 / 12-18 IST — file checker every 30 min               ║")
logger.info("║    Every 60s        — auto-delete expired messages             ║")
logger.info("║                                                                ║")
logger.info("║  Storage:                                                      ║")
logger.info("║    TTL indexes auto-clean subscriptions, msgs, weeks           ║")
logger.info("║                                                                ║")
logger.info("║  Env:                                                          ║")
logger.info("║    TMDB_API_KEY=xxx                                            ║")
logger.info("║    BROADCAST_CHANNEL_ID=-100xxx                                ║")
logger.info("║    OTT_REGION=IN (optional)                                    ║")
logger.info("║    OTT_RELEASE_TIME=12:00 (optional)                           ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
