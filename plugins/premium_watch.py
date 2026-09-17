# plugins/premium_watch.py
"""
💎 PREMIUM WATCH COMPANION v5 — FINAL
- Premium-only PM watch experience
- Persistent poster with live progress bars
- One-tap send + MARK AS WATCHED (auto-delete after 30s)
- Watch Next + season/series completion
- Watch Order for franchises
- Expiry reminders (10d / 5d / 1d / expired)
- Auto-cleanup 180-day inactivity
- Admin panel /seriesgroupsettings
"""
import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    MessageNotModified, FloodWait, UserIsBlocked,
    MessageIdInvalid,
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

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))

GRACE_PERIOD_DAYS = 30      # after expiry, before deleting progress
INACTIVITY_DAYS = 180       # 6 months of inactivity → delete session
REMINDER_HOUR = 10          # daily reminder hour (IST)
FILE_DELETE_GRACE_SEC = 30  # grace period before deleting file

PLAN_OPTIONS = [
    ("1 MONTH",   1),
    ("3 MONTHS",  3),
    ("5 MONTHS",  5),
    ("6 MONTHS",  6),
    ("12 MONTHS", 12),
]

DIV  = "━" * 24
DIV2 = "─" * 24

# Emojis
EMO = {
    "crown":   "👑", "star":    "⭐", "fire":   "🔥", "clock":  "⏰",
    "warn":    "⚠️", "ok":      "✅", "cross":  "❌", "film":   "🎬",
    "tv":      "📺", "play":    "▶️", "pause":  "⏸️", "next":   "⏭️",
    "check":   "☑️", "box":     "⬜", "party":  "🎉", "trophy": "🏆",
    "rocket":  "🚀", "book":    "📖", "cal":    "📅", "user":   "👤",
    "id":      "🆔", "bell":    "🔔", "gift":   "🎁", "spark":  "✨",
    "chart":   "📊", "search":  "🔍", "back":   "◀️", "gear":   "⚙️",
    "lock":    "🔒", "send":    "📥", "done":   "☑️", "lang":   "🌍",
    "green":   "🟢", "yellow":  "🟡", "red":    "🔴", "white":  "⚪",
    "eye":     "👁️", "trash":   "🗑️", "plus":   "➕", "minus":  "➖",
}


# ═══════════════════════════════════════════════════════════════════════════
# UNICODE FONTS (bold serif / small caps)
# ═══════════════════════════════════════════════════════════════════════════
_BOLD_MAP = {}
for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _BOLD_MAP[c] = chr(0x1D400 + i)
for i, c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _BOLD_MAP[c] = chr(0x1D41A + i)
for i, c in enumerate("0123456789"):
    _BOLD_MAP[c] = chr(0x1D7CE + i)

_SC_MAP = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}


def fb(s) -> str:
    """Fancy bold serif."""
    return "".join(_BOLD_MAP.get(c, c) for c in str(s))


def sc(s) -> str:
    """Small caps."""
    return "".join(_SC_MAP.get(c, c) for c in str(s))


# ═══════════════════════════════════════════════════════════════════════════
# FORMATTING HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_size(b) -> str:
    if not b:
        return "0 B"
    try:
        s = float(b)
    except (TypeError, ValueError):
        return "0 B"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if s < 1024:
            return f"{s:.2f} {u}"
        s /= 1024
    return f"{s:.2f} PB"


def _esc(t) -> str:
    if t is None:
        return ""
    return (str(t)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS
                            if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y • %H:%M IST")


def _date_ist(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
    except Exception:
        return "?"


def _slug(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _days_left(expires_at: float) -> int:
    try:
        return int((expires_at - time.time()) / 86400)
    except Exception:
        return 0


def _status_badge(days: int) -> str:
    if days <= 0:
        return f"{EMO['cross']} EXPIRED"
    if days <= 1:
        return f"{EMO['fire']} {days}d"
    if days <= 5:
        return f"{EMO['warn']} {days}d"
    if days <= 10:
        return f"{EMO['clock']} {days}d"
    return f"{EMO['ok']} {days}d"


def _relative_time(ts: float) -> str:
    """Return human-readable relative time like '5 days ago'."""
    if not ts:
        return "?"
    delta = time.time() - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)} min ago"
    if delta < 86400:
        return f"{int(delta // 3600)} hours ago"
    days = int(delta // 86400)
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS BAR RENDERERS
# ═══════════════════════════════════════════════════════════════════════════
def render_progress_bar(pct: float, width: int = 12) -> str:
    """███░░░░░ style — 12 chars default."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(width * pct / 100))
    return "█" * filled + "░" * (width - filled)


def render_stars(rating: float) -> str:
    try:
        r = float(rating)
    except Exception:
        return ""
    full = int(r)
    half = 1 if (r - full) >= 0.5 else 0
    empty = 5 - full - half
    return "★" * full + ("⯨" if half else "") + "☆" * empty


def render_hours_label(total_eps: int, watched: int) -> str:
    """Estimate remaining watch time."""
    remaining = max(0, total_eps - watched)
    if remaining <= 0:
        return "0 hours"
    hours = remaining * 22 / 60
    if hours < 1:
        return "<1 hour"
    return f"~{int(hours)} hours"

# ═══════════════════════════════════════════════════════════════════════════
# DATABASE ACCESS
# ═══════════════════════════════════════════════════════════════════════════
def _get_db():
    """Best-effort DB handle. Tries multiple known access patterns."""
    try:
        for name in ("get_user_db", "get_system_db",
                     "get_media_db", "get_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                try:
                    d = fn()
                except Exception:
                    continue
                if d is not None:
                    return d
    except Exception:
        pass
    for attr in ("_db", "db", "_database"):
        try:
            d = getattr(db_manager, attr, None)
            if d is not None:
                return d
        except Exception:
            continue
    return None


def _premium_coll():
    """Collection: premium_users — one doc per premium member."""
    d = _get_db()
    return d["premium_users"] if d is not None else None


def _sessions_coll():
    """Collection: watch_sessions — one doc per (user, series)."""
    d = _get_db()
    return d["watch_sessions"] if d is not None else None


def _settings_coll():
    """Collection: premium_settings — singleton admin settings."""
    d = _get_db()
    return d["premium_settings"] if d is not None else None


def _ratings_coll():
    """Collection: watch_ratings — user ratings per series."""
    d = _get_db()
    return d["watch_ratings"] if d is not None else None


# ═══════════════════════════════════════════════════════════════════════════
# PREMIUM USER CRUD
# ═══════════════════════════════════════════════════════════════════════════
async def add_premium_user(user_id: int, username: str, months: int,
                            added_by: int, notes: str = "") -> bool:
    """
    Add or extend a premium user.
    If user already exists and is active → EXTEND (stack months).
    If user is new/expired → create new.
    """
    c = _premium_coll()
    if c is None:
        logger.warning("[PREM] add_premium_user: DB unavailable")
        return False
    try:
        now = time.time()
        expires_at = now + (months * 30 * 86400)

        # Stack on existing active plan
        existing = await c.find_one({"user_id": int(user_id)})
        if existing and existing.get("expires_at", 0) > now:
            base = existing.get("expires_at", now)
            expires_at = base + (months * 30 * 86400)

        await c.update_one(
            {"user_id": int(user_id)},
            {"$set": {
                "user_id": int(user_id),
                "username": (username or "").lstrip("@"),
                "plan_months": int(months),
                "added_at": now,
                "added_by": int(added_by),
                "expires_at": expires_at,
                "notes": notes or "",
                "status": "active",
            },
             "$setOnInsert": {"reminders_sent": []}},
            upsert=True,
        )
        logger.info(f"[PREM] added/extended user={user_id} months={months}")
        return True
    except Exception as e:
        logger.exception(f"[PREM] add failed: {e}")
        return False


async def get_premium_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a premium user doc by user_id."""
    c = _premium_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"user_id": int(user_id)})
    except Exception:
        return None


async def is_premium(user_id: int) -> bool:
    """True if user is premium AND not expired."""
    doc = await get_premium_user(user_id)
    if not doc:
        return False
    if doc.get("status") != "active":
        return False
    return doc.get("expires_at", 0) > time.time()


async def is_premium_or_grace(user_id: int) -> bool:
    """True if user is premium OR still inside grace period after expiry."""
    doc = await get_premium_user(user_id)
    if not doc:
        return False
    if doc.get("status") == "active":
        return True
    expires_at = doc.get("expires_at", 0)
    if not expires_at:
        return False
    grace_end = expires_at + (GRACE_PERIOD_DAYS * 86400)
    return grace_end > time.time()


async def remove_premium_user(user_id: int) -> bool:
    """Delete a premium user entirely."""
    c = _premium_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"user_id": int(user_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def list_premium_users(limit: int = 500) -> List[Dict[str, Any]]:
    """List all premium users, sorted by expiry (soonest first)."""
    c = _premium_coll()
    if c is None:
        return []
    try:
        return await c.find({}).sort("expires_at", 1).to_list(limit)
    except Exception:
        return []


async def count_premium_users() -> Dict[str, int]:
    """Return counts: active, expiring_10d, expiring_5d, expiring_1d, expired."""
    empty = {"active": 0, "expiring_10d": 0,
             "expiring_5d": 0, "expiring_1d": 0, "expired": 0}
    c = _premium_coll()
    if c is None:
        return empty
    try:
        now = time.time()
        d10 = now + (10 * 86400)
        d5  = now + (5 * 86400)
        d1  = now + (1 * 86400)

        active = await c.count_documents(
            {"status": "active", "expires_at": {"$gt": now}})
        exp10 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d10}})
        exp5 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d5}})
        exp1 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d1}})
        expired = await c.count_documents(
            {"expires_at": {"$lte": now}})

        return {"active": active, "expiring_10d": exp10,
                "expiring_5d": exp5, "expiring_1d": exp1,
                "expired": expired}
    except Exception as e:
        logger.warning(f"[PREM] count: {e}")
        return empty


async def mark_reminder_sent(user_id: int, reminder: str) -> bool:
    """Record that a specific reminder was sent (prevents duplicates)."""
    c = _premium_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$addToSet": {"reminders_sent": reminder}},
        )
        return True
    except Exception:
        return False


async def was_reminder_sent(user_id: int, reminder: str) -> bool:
    doc = await get_premium_user(user_id)
    if not doc:
        return False
    return reminder in (doc.get("reminders_sent") or [])


async def find_premium_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Lookup premium user by @username (case-insensitive)."""
    c = _premium_coll()
    if c is None:
        return None
    try:
        uname = username.lstrip("@").lower()
        return await c.find_one(
            {"username": {"$regex": f"^{re.escape(uname)}$",
                          "options": "i"}})
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS (singleton doc)
# ═══════════════════════════════════════════════════════════════════════════
async def get_setting(key: str, default=None):
    """Read a setting from premium_settings."""
    c = _settings_coll()
    if c is None:
        return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception:
        return default


async def set_setting(key: str, value) -> bool:
    """Write a setting to premium_settings."""
    c = _settings_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {key: value, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def get_contact_admin() -> str:
    """@username of admin to contact for renewals."""
    return await get_setting("contact_admin", "") or ""


logger.info("[PREM] Part 2 loaded — DB + premium CRUD + settings")

# ═══════════════════════════════════════════════════════════════════════════
# WATCH SESSION CRUD
# ═══════════════════════════════════════════════════════════════════════════
async def create_session(user_id: int, series_slug: str,
                          series_title: str, poster: Optional[str],
                          tmdb_id: Optional[int],
                          tmdb_seasons: List[Dict[str, Any]],
                          hits: List[Dict[str, Any]] = None,
                          language: str = "") -> bool:
    """
    Create or update a watch session.
    Stores CLEAN hits (no FileHit objects).
    """
    c = _sessions_coll()
    if c is None:
        return False
    try:
        now = time.time()

        # Build seasons doc from TMDB data
        seasons_doc: Dict[str, Dict[str, Any]] = {}
        for s in (tmdb_seasons or []):
            sn = s.get("season")
            if sn is None:
                continue
            seasons_doc[str(sn)] = {
                "total_eps": int(s.get("episodes", 0) or 0),
                "watched": [],
                "sent": [],
                "current_ep": 1,
            }
        if not seasons_doc:
            seasons_doc["1"] = {
                "total_eps": 0, "watched": [], "sent": [], "current_ep": 1,
            }

        # Strip FileHit objects from hits (MongoDB can't store them)
        clean_hits = _clean_hits(hits or [])

        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {
                "user_id": int(user_id),
                "series_slug": series_slug,
                "series_title": series_title,
                "poster": poster,
                "tmdb_id": tmdb_id,
                "language": language or "",
                "seasons": seasons_doc,
                "hits": clean_hits,
                "started_at": now,
                "last_activity_at": now,
                "status": "watching",
                "completed_at": None,
                "poster_chat_id": int(user_id),
                "poster_msg_id": None,
                "current_file_msg_id": None,
                "current_season": 1,
                "current_episode": 1,
                "rated": False,
            }},
            upsert=True,
        )
        logger.info(f"[PREM] session created u={user_id} s={series_slug}")
        return True
    except Exception as e:
        logger.exception(f"[PREM] create session: {e}")
        return False


def _clean_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip non-serializable objects (FileHit) from hit dicts."""
    clean = []
    for h in (hits or []):
        try:
            clean.append({
                "file_id": h.get("file_id") or "",
                "file_unique_id": h.get("file_unique_id"),
                "file_name": h.get("file_name") or "",
                "file_size": h.get("file_size") or 0,
                "season": h.get("season"),
                "episode": h.get("episode"),
                "quality": h.get("quality") or "UNKNOWN",
                "languages": list(h.get("languages") or []),
                "title": h.get("title") or "",
                "series_title": h.get("series_title") or "",
                "chat_id": h.get("chat_id"),
                "message_id": h.get("message_id"),
            })
        except Exception as e:
            logger.debug(f"[PREM] skip hit: {e}")
    return clean


async def get_session(user_id: int,
                       series_slug: str) -> Optional[Dict[str, Any]]:
    """Fetch a watch session for (user, series)."""
    c = _sessions_coll()
    if c is None:
        return None
    try:
        return await c.find_one(
            {"user_id": int(user_id), "series_slug": series_slug})
    except Exception:
        return None


async def list_user_sessions(user_id: int) -> List[Dict[str, Any]]:
    """List all active (watching) sessions for a user."""
    c = _sessions_coll()
    if c is None:
        return []
    try:
        return (await c.find({"user_id": int(user_id),
                              "status": "watching"})
                .sort("last_activity_at", -1)
                .to_list(50))
    except Exception:
        return []


async def list_all_sessions(user_id: int) -> List[Dict[str, Any]]:
    """List ALL sessions (watching + completed) for a user."""
    c = _sessions_coll()
    if c is None:
        return []
    try:
        return (await c.find({"user_id": int(user_id)})
                .sort("last_activity_at", -1)
                .to_list(100))
    except Exception:
        return []


async def mark_watched(user_id: int, series_slug: str,
                        season: int, episode: int) -> bool:
    """
    Mark an episode as watched.
    Adds to watched array + updates last_activity.
    """
    c = _sessions_coll()
    if c is None:
        return False
    try:
        key = f"seasons.{int(season)}.watched"
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$addToSet": {key: int(episode)},
             "$set": {"last_activity_at": time.time()}},
        )

        # Bump current_ep
        sess = await get_session(user_id, series_slug)
        if sess:
            s_data = (sess.get("seasons") or {}).get(str(season)) or {}
            total = int(s_data.get("total_eps", 0) or 0)
            next_ep = int(episode) + 1
            if total and next_ep > total:
                next_ep = total
            await c.update_one(
                {"user_id": int(user_id), "series_slug": series_slug},
                {"$set": {f"seasons.{season}.current_ep": next_ep}},
            )
        return True
    except Exception as e:
        logger.exception(f"[PREM] mark watched: {e}")
        return False


async def mark_sent(user_id: int, series_slug: str,
                     season: int, episode: int) -> bool:
    """Track that a file was sent (so we can show delivered count)."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        key = f"seasons.{int(season)}.sent"
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$addToSet": {key: int(episode)},
             "$set": {"last_activity_at": time.time()}},
        )
        return True
    except Exception:
        return False


async def update_poster_msg(user_id: int, series_slug: str,
                              msg_id: int) -> bool:
    """Save the poster message id."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"poster_msg_id": int(msg_id)}},
        )
        return True
    except Exception:
        return False


async def update_current_file_msg(user_id: int, series_slug: str,
                                    msg_id: int) -> bool:
    """Save the most recent file message id."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"current_file_msg_id": int(msg_id)}},
        )
        return True
    except Exception:
        return False


async def set_current_position(user_id: int, series_slug: str,
                                 season: int, episode: int) -> bool:
    """Set the current watching position."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"current_season": int(season),
                      "current_episode": int(episode),
                      "last_activity_at": time.time()}},
        )
        return True
    except Exception:
        return False


async def set_language(user_id: int, series_slug: str,
                        language: str) -> bool:
    """Set the chosen language for a session."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"language": language,
                      "last_activity_at": time.time()}},
        )
        return True
    except Exception:
        return False


async def mark_session_completed(user_id: int, series_slug: str) -> bool:
    """Mark the whole session as completed."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"status": "completed",
                      "completed_at": time.time()}},
        )
        return True
    except Exception:
        return False


async def mark_session_rated(user_id: int, series_slug: str) -> bool:
    """Mark that this session has been rated."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"rated": True}},
        )
        return True
    except Exception:
        return False


async def delete_session(user_id: int, series_slug: str) -> bool:
    """Delete a session entirely."""
    c = _sessions_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"user_id": int(user_id),
                                 "series_slug": series_slug})
        return r.deleted_count > 0
    except Exception:
        return False


async def count_sessions() -> int:
    """Count of all active watching sessions."""
    c = _sessions_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"status": "watching"})
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# RATINGS
# ═══════════════════════════════════════════════════════════════════════════
async def save_rating(user_id: int, series_slug: str,
                       stars: int) -> bool:
    """Save a user's rating for a series."""
    c = _ratings_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {
                "user_id": int(user_id),
                "series_slug": series_slug,
                "rating": int(stars),
                "rated_at": time.time(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS ENGINE
# ═══════════════════════════════════════════════════════════════════════════
def compute_progress(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute per-season and overall progress.
    Returns:
      {
        "seasons": {sn: {watched: [...], count, total, sent_count}},
        "total_watched": int,
        "total_eps": int,
        "pct": float,
      }
    """
    seasons_raw = session.get("seasons") or {}
    seasons_out: Dict[int, Dict[str, Any]] = {}
    total_watched = 0
    total_eps = 0

    for sn_str, s_data in seasons_raw.items():
        try:
            sn = int(sn_str)
        except Exception:
            continue

        watched = set(s_data.get("watched") or [])
        sent = set(s_data.get("sent") or [])
        total = int(s_data.get("total_eps", 0) or 0)
        cnt = len(watched)

        seasons_out[sn] = {
            "watched": sorted(watched),
            "sent": sorted(sent),
            "count": cnt,
            "sent_count": len(sent),
            "total": total,
        }
        total_watched += cnt
        total_eps += total

    overall_pct = (total_watched / total_eps * 100) if total_eps else 0.0
    return {
        "seasons": seasons_out,
        "total_watched": total_watched,
        "total_eps": total_eps,
        "pct": round(overall_pct, 1),
    }


def find_next_episode(session: Dict[str, Any]
                       ) -> Optional[Tuple[int, int]]:
    """Find the next unwatched episode in sequence."""
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    for sn in ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        total = int(s_data.get("total_eps", 0) or 0)
        if total == 0:
            continue
        watched = set(s_data.get("watched") or [])
        for ep in range(1, total + 1):
            if ep not in watched:
                return (sn, ep)
    return None


def is_season_complete(session: Dict[str, Any], season: int) -> bool:
    """True if all episodes in a season are watched."""
    seasons_raw = session.get("seasons") or {}
    s_data = seasons_raw.get(str(season)) or {}
    total = int(s_data.get("total_eps", 0) or 0)
    if total == 0:
        return False
    watched = set(s_data.get("watched") or [])
    return len(watched) >= total


def is_series_complete(session: Dict[str, Any]) -> bool:
    """True if all episodes across all seasons are watched."""
    p = compute_progress(session)
    if p["total_eps"] == 0:
        return False
    return p["total_watched"] >= p["total_eps"]


def season_progress_pct(session: Dict[str, Any], season: int) -> float:
    """Per-season completion percentage."""
    seasons_raw = session.get("seasons") or {}
    s_data = seasons_raw.get(str(season)) or {}
    total = int(s_data.get("total_eps", 0) or 0)
    if total == 0:
        return 0.0
    watched = len(set(s_data.get("watched") or []))
    return round(watched / total * 100, 1)


logger.info("[PREM] Part 3 loaded — session CRUD + progress engine")

# ═══════════════════════════════════════════════════════════════════════════
# REMINDER LOOP — sends 10d/5d/1d/expired reminders to premium users
# ═══════════════════════════════════════════════════════════════════════════
async def _reminder_loop(client: Client):
    """Runs every 10 min; fires reminders at REMINDER_HOUR IST."""
    await asyncio.sleep(90)
    last_run_date = None

    while True:
        try:
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")

            if (now.hour == REMINDER_HOUR
                    and now.minute < 30
                    and last_run_date != today):
                last_run_date = today
                await _send_all_reminders(client)
                await _send_admin_report(client)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[PREM] reminder loop: {e}")
        await asyncio.sleep(600)


async def _send_all_reminders(client: Client):
    """Send expiry reminders to users expiring in 10/5/1 days."""
    users = await list_premium_users(500)
    if not users:
        return

    now = time.time()

    for u in users:
        try:
            uid = u.get("user_id")
            expires = u.get("expires_at", 0)
            if not uid or not expires:
                continue

            # Expired case
            if expires <= now:
                days_since = (now - expires) / 86400
                if (days_since <= 2
                        and not await was_reminder_sent(uid, "expired")):
                    await _send_reminder(client, uid, u, "expired")
                    await mark_reminder_sent(uid, "expired")
                continue

            days_left = (expires - now) / 86400

            if 9 < days_left <= 10 and not await was_reminder_sent(uid, "10d"):
                await _send_reminder(client, uid, u, "10d")
                await mark_reminder_sent(uid, "10d")
            elif 4 < days_left <= 5 and not await was_reminder_sent(uid, "5d"):
                await _send_reminder(client, uid, u, "5d")
                await mark_reminder_sent(uid, "5d")
            elif 0 < days_left <= 1 and not await was_reminder_sent(uid, "1d"):
                await _send_reminder(client, uid, u, "1d")
                await mark_reminder_sent(uid, "1d")
        except Exception as e:
            logger.debug(f"[PREM] reminder {u.get('user_id')}: {e}")


async def _send_reminder(client: Client, uid: int,
                          user: Dict[str, Any], kind: str):
    """Send a single reminder message to a user's PM."""
    contact = await get_contact_admin() or "@admin"
    expires = user.get("expires_at", 0)
    exp_date = _date_ist(expires)
    username = user.get("username") or "user"

    # Active series block
    sessions = await list_user_sessions(uid)
    series_lines = []
    for s in sessions[:5]:
        title = s.get("series_title") or "?"
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        series_lines.append(
            f"{EMO['tv']} <b>{_esc(title)}</b>\n"
            f"   {bar}  <code>{p['total_watched']}/"
            f"{p['total_eps']}</code>"
        )
    series_block = ("\n".join(series_lines)
                    if series_lines
                    else f"{EMO['box']} <i>No active series</i>")

    # Compose based on reminder kind
    if kind == "10d":
        header = f"{EMO['bell']} <b>PREMIUM EXPIRING SOON</b>"
        body = (
            f"Hi <b>{_esc(username)}</b>! {EMO['spark']}\n\n"
            f"Your premium expires in:\n"
            f"{EMO['cal']} <b>{exp_date}</b> <code>(10 days)</code>"
        )
        footer = f"{EMO['crown']} Renew with: <b>{_esc(contact)}</b>"
    elif kind == "5d":
        header = f"{EMO['warn']} <b>PREMIUM EXPIRING IN 5 DAYS</b>"
        body = (
            f"Hi <b>{_esc(username)}</b>! {EMO['spark']}\n\n"
            f"{EMO['cal']} Your plan ends: <b>{exp_date}</b>\n\n"
            f"{EMO['warn']} <b>If you don't renew, you'll lose:</b>\n"
            f"   {EMO['cross']} Watch progress tracking\n"
            f"   {EMO['cross']} Watch Order Assistant\n"
            f"   {EMO['cross']} New episode deliveries\n\n"
            f"{EMO['ok']} <i>Already delivered files are yours "
            f"forever.</i>"
        )
        footer = (f"{EMO['crown']} Contact <b>{_esc(contact)}</b> "
                  f"to renew.")
    elif kind == "1d":
        header = f"{EMO['fire']} <b>LAST DAY OF PREMIUM</b>"
        body = (
            f"Hi <b>{_esc(username)}</b>! {EMO['spark']}\n\n"
            f"{EMO['clock']} Your premium expires <b>tomorrow</b>\n"
            f"{EMO['cal']} <code>{exp_date}</code>\n\n"
            f"{EMO['ok']} Progress saved for <b>30 days</b> "
            f"after expiry.\n"
            f"{EMO['ok']} After 30 days, tracking removed — "
            f"files stay with you."
        )
        footer = (f"{EMO['crown']} Contact <b>{_esc(contact)}</b> "
                  f"to renew.")
    else:  # expired
        header = f"{EMO['cross']} <b>PREMIUM EXPIRED</b>"
        body = (
            f"Hi <b>{_esc(username)}</b>!\n\n"
            f"{EMO['warn']} Your premium membership ended today.\n\n"
            f"{EMO['ok']} Files you received: <b>yours forever</b>\n"
            f"{EMO['pause']} Progress tracking: <b>paused</b>\n"
            f"{EMO['cross']} Watch companion: <b>disabled</b>\n\n"
            f"{EMO['fire']} <b>Progress DELETED in 30 days "
            f"if not renewed.</b>"
        )
        footer = (f"{EMO['crown']} Contact <b>{_esc(contact)}</b> "
                  f"to renew.")

    text = "\n".join([
        f"{EMO['crown']} <b>{fb('DOWNTOWN VILLA')}</b>",
        header,
        DIV, "",
        body,
        "",
        DIV2,
        f"{EMO['chart']} <b>YOUR ACTIVE SERIES</b>",
        "",
        series_block,
        "", DIV2,
        footer,
    ])

    # Buttons
    kb_rows = []
    if contact and contact.startswith("@"):
        kb_rows.append([InlineKeyboardButton(
            f"{EMO['crown']} MESSAGE ADMIN",
            url=f"https://t.me/{contact.lstrip('@')}",
        )])
    if kind != "expired":
        kb_rows.append([InlineKeyboardButton(
            f"{EMO['play']} CONTINUE WATCHING",
            callback_data="pw:my_sessions",
        )])
    kb_rows.append([InlineKeyboardButton(
        f"{EMO['cross']} DISMISS",
        callback_data="pw:dismiss_reminder",
    )])

    try:
        await client.send_message(
            chat_id=int(uid),
            text=text,
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[PREM] reminder {kind} -> {uid}")
    except UserIsBlocked:
        logger.debug(f"[PREM] user {uid} blocked bot")
    except Exception as e:
        logger.warning(f"[PREM] send reminder: {e}")


async def _send_admin_report(client: Client):
    """Send daily premium report to all admins."""
    if not ADMINS:
        return
    stats = await count_premium_users()
    sessions = await count_sessions()

    # Find expiring tomorrow
    users = await list_premium_users(500)
    exp_1d = []
    now = time.time()
    for u in users:
        if u.get("status") != "active":
            continue
        expires = u.get("expires_at", 0)
        if expires <= now:
            continue
        days = (expires - now) / 86400
        uname = u.get("username") or str(u.get("user_id"))
        if 0 < days <= 1:
            exp_1d.append(uname)

    lines = [
        f"{EMO['crown']} <b>{fb('PREMIUM DAILY REPORT')}</b>",
        DIV, "",
        f"{EMO['clock']} <code>{_now_ist()}</code>",
        "",
        f"{EMO['ok']} Active       - <code>{stats['active']}</code>",
        f"{EMO['clock']} Expiring 10d - <code>{stats['expiring_10d']}</code>",
        f"{EMO['warn']} Expiring 5d  - <code>{stats['expiring_5d']}</code>",
        f"{EMO['fire']} Expiring 1d  - <code>{stats['expiring_1d']}</code>",
        f"{EMO['cross']} Expired      - <code>{stats['expired']}</code>",
        "",
        f"{EMO['chart']} Active sessions - <code>{sessions}</code>",
    ]
    if exp_1d:
        lines += ["", DIV2, f"{EMO['fire']} Expiring tomorrow:"]
        for u in exp_1d[:10]:
            lines.append(f"   {EMO['user']} {_esc(u)}")

    text = "\n".join(lines)
    for a in ADMINS:
        try:
            aid = int(a) if str(a).lstrip("-").isdigit() else None
            if not aid:
                continue
            await client.send_message(
                aid, text, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP LOOP — runs every 6 hours
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop(client: Client):
    await asyncio.sleep(180)

    while True:
        try:
            await _cleanup_inactive_sessions()
            await _cleanup_expired_sessions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[PREM] cleanup: {e}")
        await asyncio.sleep(6 * 3600)


async def _cleanup_inactive_sessions():
    """Delete sessions with no activity for INACTIVITY_DAYS (180d)."""
    c = _sessions_coll()
    if c is None:
        return
    try:
        cutoff = time.time() - (INACTIVITY_DAYS * 86400)
        r = await c.delete_many({
            "status": "watching",
            "last_activity_at": {"$lt": cutoff},
        })
        if r.deleted_count > 0:
            logger.info(
                f"[PREM] cleanup: {r.deleted_count} inactive sessions"
            )
    except Exception as e:
        logger.warning(f"[PREM] cleanup inactive: {e}")


async def _cleanup_expired_sessions():
    """Delete sessions for users whose grace period (30d) is over."""
    c = _sessions_coll()
    p = _premium_coll()
    if c is None or p is None:
        return
    try:
        now = time.time()
        cutoff = now - (GRACE_PERIOD_DAYS * 86400)

        expired_uids = []
        async for doc in p.find({"expires_at": {"$lt": cutoff}}):
            uid = doc.get("user_id")
            if uid:
                expired_uids.append(uid)

        if not expired_uids:
            return

        r = await c.delete_many({"user_id": {"$in": expired_uids}})
        if r.deleted_count > 0:
            logger.info(
                f"[PREM] cleanup: {r.deleted_count} expired sessions "
                f"for {len(expired_uids)} users"
            )
    except Exception as e:
        logger.warning(f"[PREM] cleanup expired: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# BOOT — start background loops once
# ═══════════════════════════════════════════════════════════════════════════
_BOOT_LOCK = asyncio.Lock()
_BOOTED = False


async def _ensure_loops(client: Client):
    global _BOOTED
    async with _BOOT_LOCK:
        if _BOOTED:
            return
        _BOOTED = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reminder_loop(client))
        loop.create_task(_cleanup_loop(client))
        logger.info("[PREM] reminder + cleanup loops started")
    except Exception as e:
        logger.warning(f"[PREM] boot: {e}")
        _BOOTED = False


# ═══════════════════════════════════════════════════════════════════════════
# SAFE EDIT HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def _pw_safe_edit(q_or_msg, text: str, kb=None,
                         is_caption: bool = False) -> bool:
    """Edit text or caption, handling all edge cases gracefully."""
    try:
        m = getattr(q_or_msg, "message", q_or_msg)

        if is_caption:
            try:
                await m.edit_caption(
                    caption=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML)
                return True
            except MessageNotModified:
                return True
            except Exception:
                pass

        try:
            await m.edit_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
            return True
        except MessageNotModified:
            return True
        except Exception:
            if not is_caption:
                try:
                    await m.edit_caption(
                        caption=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML)
                    return True
                except MessageNotModified:
                    return True
                except Exception:
                    pass
            return False
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        return await _pw_safe_edit(q_or_msg, text, kb, is_caption)
    except Exception as e:
        logger.debug(f"[PREM] edit: {e}")
        return False


async def _pw_safe_edit_by_id(client, chat_id: int, msg_id: int,
                                text: str, kb=None) -> bool:
    """Edit a message by chat_id + msg_id (for background tasks)."""
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified:
        return True
    except MessageIdInvalid:
        return False
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            return False
    except Exception as e:
        logger.debug(f"[PREM] edit_by_id: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# LOCK HELPER (prevent double-clicks)
# ═══════════════════════════════════════════════════════════════════════════
_PW_LOCKS: Dict[int, float] = {}


def _pw_acquire_lock(uid: int, secs: float = 3.0) -> bool:
    """Rate-limit per-user actions."""
    now = time.time()
    last = _PW_LOCKS.get(int(uid), 0)
    if now - last < secs:
        return False
    _PW_LOCKS[int(uid)] = now
    return True


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN SESSION (in-memory state for multi-step admin flows)
# ═══════════════════════════════════════════════════════════════════════════
_ADMIN_SESSIONS: Dict[int, Dict[str, Any]] = {}
_SESSION_TTL = 900


def _new_admin_session(uid: int, action: str, **data):
    _ADMIN_SESSIONS[int(uid)] = {
        "action": action,
        "expires": time.time() + _SESSION_TTL,
        **data,
    }


def _get_admin_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _ADMIN_SESSIONS.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _ADMIN_SESSIONS.pop(int(uid), None)
        return None
    return s


def _clear_admin_session(uid: int):
    _ADMIN_SESSIONS.pop(int(uid), None)


logger.info("[PREM] Part 4 loaded — reminders + cleanup + boot + helpers")

# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PANEL KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_pw_main():
    """Main admin panel keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMO['crown']} PREMIUM MEMBERS",
                              callback_data="pw:members")],
        [InlineKeyboardButton(f"{EMO['plus']} ADD USER",
                              callback_data="pw:add"),
         InlineKeyboardButton(f"{EMO['search']} FIND USER",
                              callback_data="pw:find")],
        [InlineKeyboardButton(f"{EMO['clock']} EXPIRING SOON",
                              callback_data="pw:expiring"),
         InlineKeyboardButton(f"{EMO['cross']} EXPIRED",
                              callback_data="pw:expired")],
        [InlineKeyboardButton(f"{EMO['gear']} SET CONTACT",
                              callback_data="pw:contact"),
         InlineKeyboardButton(f"{EMO['chart']} STATS",
                              callback_data="pw:stats")],
        [InlineKeyboardButton(f"{EMO['spark']} REFRESH",
                              callback_data="pw:main"),
         InlineKeyboardButton(f"{EMO['cross']} CLOSE",
                              callback_data="pw:close")],
    ])


def kb_pw_back(target: str = "pw:main"):
    """Back + Close row."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{EMO['back']} BACK", callback_data=target),
        InlineKeyboardButton(f"{EMO['cross']} CLOSE",
                             callback_data="pw:close"),
    ]])


def kb_pw_plan_picker(user_id: int, username: str):
    """Plan duration picker (1/3/5/6/12 months)."""
    rows = []
    row = []
    for label, months in PLAN_OPTIONS:
        row.append(InlineKeyboardButton(
            f"{EMO['crown']} {label}",
            callback_data=f"pw:plan:{user_id}:{months}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        f"{EMO['back']} CANCEL",
        callback_data="pw:add",
    )])
    return InlineKeyboardMarkup(rows)


def kb_pw_member_actions(user_id: int):
    """Actions for a specific premium member."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMO['spark']} EXTEND",
                              callback_data=f"pw:extend:{user_id}"),
         InlineKeyboardButton(f"{EMO['cross']} REMOVE",
                              callback_data=f"pw:remove:{user_id}")],
        [InlineKeyboardButton(f"{EMO['gear']} EDIT NOTES",
                              callback_data=f"pw:notes:{user_id}")],
        [InlineKeyboardButton(f"{EMO['back']} BACK TO LIST",
                              callback_data="pw:members"),
         InlineKeyboardButton(f"{EMO['cross']} CLOSE",
                              callback_data="pw:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_pw_main() -> Tuple[str, InlineKeyboardMarkup]:
    """Main admin panel view."""
    stats = await count_premium_users()
    sessions = await count_sessions()
    contact = await get_contact_admin() or "-"

    text = "\n".join([
        f"{EMO['crown']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"{EMO['gear']} <b>{fb('PREMIUM MANAGEMENT')}</b>",
        DIV, "",
        f"{EMO['ok']} Active       - <code>{stats['active']}</code>",
        f"{EMO['clock']} Expiring 10d - <code>{stats['expiring_10d']}</code>",
        f"{EMO['warn']} Expiring 5d  - <code>{stats['expiring_5d']}</code>",
        f"{EMO['fire']} Expiring 1d  - <code>{stats['expiring_1d']}</code>",
        f"{EMO['cross']} Expired      - <code>{stats['expired']}</code>",
        "",
        f"{EMO['chart']} Active sessions - <code>{sessions}</code>",
        "",
        DIV2, "",
        f"{EMO['crown']} Contact - <code>{_esc(contact)}</code>",
        "",
        f"{EMO['clock']} <code>{_now_ist()}</code>",
    ])
    return text, kb_pw_main()


async def _view_pw_members(page: int = 0
                             ) -> Tuple[str, InlineKeyboardMarkup]:
    """Paginated premium member list (8 per page)."""
    users = await list_premium_users(500)
    if not users:
        text = "\n".join([
            f"{EMO['crown']} <b>{fb('PREMIUM MEMBERS')}</b>",
            DIV, "",
            f"{EMO['box']} <i>No premium users yet.</i>",
        ])
        return text, kb_pw_back()

    now = time.time()
    users.sort(key=lambda u: u.get("expires_at", 0))

    per_page = 8
    total = len(users)
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]

    lines = [
        f"{EMO['crown']} <b>{fb('PREMIUM MEMBERS')}</b> "
        f"- <code>{total}</code>",
        DIV, "",
    ]

    for i, u in enumerate(page_users, start=start + 1):
        uid = u.get("user_id")
        uname = u.get("username") or f"ID {uid}"
        expires = u.get("expires_at", 0)
        days = _days_left(expires)
        plan = u.get("plan_months", 0)
        badge = _status_badge(days)

        lines.append(
            f"<b>{i}.</b> {EMO['user']} "
            f"@{_esc(str(uname).lstrip('@'))}"
        )
        lines.append(
            f"   {badge}  •  {plan}mo  •  <code>{uid}</code>"
        )
        lines.append("")

    rows = []
    for i, u in enumerate(page_users[:6], start=start + 1):
        uname = (u.get("username") or str(u.get("user_id")))[:20]
        rows.append([InlineKeyboardButton(
            f"{i}. @{uname}",
            callback_data=f"pw:member:{u['user_id']}",
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            f"{EMO['back']} PREV",
            callback_data=f"pw:members_p:{page - 1}",
        ))
    if end < total:
        nav.append(InlineKeyboardButton(
            f"NEXT {EMO['back']}",
            callback_data=f"pw:members_p:{page + 1}",
        ))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(f"{EMO['plus']} ADD",
                             callback_data="pw:add"),
        InlineKeyboardButton(f"{EMO['search']} FIND",
                             callback_data="pw:find"),
    ])
    rows.append([
        InlineKeyboardButton(f"{EMO['back']} BACK",
                             callback_data="pw:main"),
        InlineKeyboardButton(f"{EMO['cross']} CLOSE",
                             callback_data="pw:close"),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _view_pw_member_detail(user_id: int
                                   ) -> Tuple[str, InlineKeyboardMarkup]:
    """Show detailed info about a single premium member."""
    u = await get_premium_user(user_id)
    if not u:
        return (f"{EMO['cross']} <b>User not found.</b>",
                kb_pw_back("pw:members"))

    uid = u.get("user_id")
    uname = u.get("username") or f"ID {uid}"
    expires = u.get("expires_at", 0)
    plan = u.get("plan_months", 0)
    added = u.get("added_at", 0)
    added_by = u.get("added_by", 0)
    notes = u.get("notes") or "-"
    days = _days_left(expires)
    badge = _status_badge(days)

    # Active sessions for this user
    sessions = await list_user_sessions(uid)
    session_lines = []
    for s in sessions[:5]:
        title = s.get("series_title") or "?"
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        session_lines.append(
            f"   {EMO['tv']} <b>{_esc(title)}</b>\n"
            f"      {bar}  <code>{p['total_watched']}/"
            f"{p['total_eps']}</code>"
        )
    sessions_block = ("\n".join(session_lines)
                      if session_lines
                      else f"   {EMO['box']} <i>None</i>")

    text = "\n".join([
        f"{EMO['crown']} <b>{fb('PREMIUM USER')}</b>",
        DIV, "",
        f"{EMO['id']} ID: <code>{uid}</code>",
        f"{EMO['user']} @{_esc(str(uname).lstrip('@'))}",
        "",
        f"{EMO['crown']} Plan    - <code>{plan} months</code>",
        f"{EMO['cal']} Added   - <code>{_date_ist(added)}</code>",
        f"{EMO['user']} By      - <code>{added_by}</code>",
        f"{EMO['clock']} Expires - <code>{_date_ist(expires)}</code>",
        f"{badge}",
        "",
        f"{EMO['gear']} Notes - <i>{_esc(notes)}</i>",
        "",
        DIV2, "",
        f"{EMO['chart']} <b>ACTIVE SESSIONS</b>",
        sessions_block,
    ])

    return text, kb_pw_member_actions(uid)


async def _view_pw_expiring() -> Tuple[str, InlineKeyboardMarkup]:
    """List users expiring within 10 days."""
    users = await list_premium_users(500)
    now = time.time()
    d10 = now + (10 * 86400)

    expiring = [u for u in users
                if u.get("status") == "active"
                and now < u.get("expires_at", 0) <= d10]

    lines = [
        f"{EMO['clock']} <b>{fb('EXPIRING SOON')}</b> "
        f"- <code>{len(expiring)}</code>",
        DIV, "",
    ]

    if not expiring:
        lines.append(f"{EMO['ok']} <i>None expiring soon.</i>")
    else:
        expiring.sort(key=lambda u: u.get("expires_at", 0))
        for u in expiring:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days = _days_left(expires)
            badge = _status_badge(days)
            lines.append(
                f"{badge} @{_esc(str(uname).lstrip('@'))}"
            )
            lines.append(
                f"   {EMO['cal']} {_date_ist(expires)}  •  "
                f"<code>{u.get('user_id')}</code>"
            )
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_expired() -> Tuple[str, InlineKeyboardMarkup]:
    """List expired users (up to 20)."""
    users = await list_premium_users(500)
    now = time.time()
    expired = [u for u in users if u.get("expires_at", 0) <= now]

    lines = [
        f"{EMO['cross']} <b>{fb('EXPIRED USERS')}</b> "
        f"- <code>{len(expired)}</code>",
        DIV, "",
    ]

    if not expired:
        lines.append(f"{EMO['ok']} <i>No expired users.</i>")
    else:
        expired.sort(key=lambda u: u.get("expires_at", 0), reverse=True)
        for u in expired[:20]:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days_ago = int((now - expires) / 86400)
            grace_end = expires + (GRACE_PERIOD_DAYS * 86400)
            grace_days = int((grace_end - now) / 86400)
            grace_icon = (EMO["fire"] if grace_days <= 0
                          else EMO["ok"])
            lines.append(
                f"{EMO['cross']} @{_esc(str(uname).lstrip('@'))}"
            )
            lines.append(
                f"   {days_ago}d ago  •  {grace_icon} "
                f"{max(0, grace_days)}d grace  •  "
                f"<code>{u.get('user_id')}</code>"
            )
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_stats() -> Tuple[str, InlineKeyboardMarkup]:
    """Premium statistics."""
    stats = await count_premium_users()
    sessions = await count_sessions()

    users = await list_premium_users(500)
    active_users = [u for u in users if u.get("status") == "active"]
    total_months = sum(u.get("plan_months", 0) for u in active_users)
    total_users = len(active_users)
    avg_plan = round(total_months / total_users, 1) if total_users else 0

    text = "\n".join([
        f"{EMO['chart']} <b>{fb('PREMIUM STATS')}</b>",
        DIV, "",
        f"{EMO['ok']} Active members   - <code>{stats['active']}</code>",
        f"{EMO['cross']} Expired       - <code>{stats['expired']}</code>",
        f"{EMO['tv']} Watch sessions - <code>{sessions}</code>",
        "", DIV2, "",
        f"{EMO['clock']} Expiring 10d - "
        f"<code>{stats['expiring_10d']}</code>",
        f"{EMO['warn']} Expiring 5d  - "
        f"<code>{stats['expiring_5d']}</code>",
        f"{EMO['fire']} Expiring 1d  - "
        f"<code>{stats['expiring_1d']}</code>",
        "", DIV2, "",
        f"{EMO['crown']} Total months sold - "
        f"<code>{total_months}</code>",
        f"{EMO['spark']} Avg plan          - <code>{avg_plan}mo</code>",
        "", DIV2,
        f"{EMO['clock']} <code>{_now_ist()}</code>",
    ])

    return text, kb_pw_back()


async def _view_pw_find() -> Tuple[str, InlineKeyboardMarkup]:
    """Prompt to find a user."""
    text = "\n".join([
        f"{EMO['search']} <b>{fb('FIND PREMIUM USER')}</b>",
        DIV, "",
        f"{EMO['spark']} <i>Send user id or @username</i>",
        "",
        f"{EMO['id']} <b>Examples:</b>",
        "   <code>123456789</code>",
        "   <code>@john</code>",
    ])
    return text, kb_pw_back()


logger.info("[PREM] Part 5 loaded — admin keyboards + view builders")

# ═══════════════════════════════════════════════════════════════════════════
# MAIN COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["seriesgroupsettings", "premium", "pw"])
    & filters.private,
    group=-426,
)
async def cmd_pw_main(client, message):
    """Admin command to open premium management panel."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{EMO['lock']} <b>Admins only.</b>",
            parse_mode=ParseMode.HTML,
        )
    try:
        await _ensure_loops(client)
        _clear_admin_session(message.from_user.id)
        text, kb = await _view_pw_main()
        await message.reply_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[PREM] /seriesgroupsettings: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:main$"), group=-426)
async def cb_pw_main(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        _clear_admin_session(q.from_user.id)
        text, kb = await _view_pw_main()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] cb_pw_main: {e}")


@Client.on_callback_query(filters.regex(r"^pw:close$"), group=-426)
async def cb_pw_close(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        _clear_admin_session(q.from_user.id)
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer(f"{EMO['ok']} Closed")
    except Exception:
        try:
            await q.answer("Closed")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# MEMBERS LIST / DETAIL
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:members$"), group=-426)
async def cb_pw_members(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] members: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:members_p:(\d+)$"), group=-426,
)
async def cb_pw_members_page(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        page = int(q.matches[0].group(1))
        text, kb = await _view_pw_members(page)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] members page: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:member:(\d+)$"), group=-426,
)
async def cb_pw_member(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        uid = int(q.matches[0].group(1))
        text, kb = await _view_pw_member_detail(uid)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] member detail: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ADD USER FLOW
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:add$"), group=-426)
async def cb_pw_add(client, q):
    """Start add-user flow: ask for user id or @username."""
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        _new_admin_session(q.from_user.id, "add_premium_user")
        text = "\n".join([
            f"{EMO['user']} <b>{fb('ADD PREMIUM USER')}</b>",
            DIV, "",
            f"{EMO['spark']} <i>Send user id or @username</i>",
            "",
            f"{EMO['id']} <b>Examples:</b>",
            "   <code>123456789</code>",
            "   <code>@john</code>",
            "",
            f"{EMO['gift']} <i>Or forward a message from the user</i>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"{EMO['back']} CANCEL",
                                 callback_data="pw:main"),
        ]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] add: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TEXT INPUT HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^pw:"),
    group=-425,
)
async def pw_admin_input(client, message):
    """Handle text input for admin multi-step flows."""
    if not message.from_user:
        return
    if not _is_admin(message.from_user.id):
        return

    s = _get_admin_session(message.from_user.id)
    if not s:
        return

    action = s.get("action")
    if action not in ("add_premium_user", "find_user",
                      "edit_notes", "set_contact"):
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    text = (message.text or "").strip()
    if not text:
        return

    if action == "add_premium_user":
        await _handle_add_user_input(client, message, text)
    elif action == "find_user":
        await _handle_find_user_input(client, message, text)
    elif action == "edit_notes":
        await _handle_edit_notes_input(client, message, text, s)
    elif action == "set_contact":
        await _handle_set_contact_input(client, message, text)


async def _handle_add_user_input(client, message, text: str):
    """Resolve the target user (by id/@username) and show plan picker."""
    uid_target = None
    username = ""

    if text.lstrip("-").isdigit():
        uid_target = int(text)
    elif text.startswith("@"):
        username = text
        doc = await find_premium_by_username(text)
        if doc:
            uid_target = doc.get("user_id")
        else:
            try:
                u = await client.get_users(text)
                uid_target = u.id
                username = (f"@{u.username}"
                            if u.username else f"ID {u.id}")
            except Exception as e:
                _clear_admin_session(message.from_user.id)
                return await message.reply_text(
                    f"{EMO['cross']} Could not resolve "
                    f"<code>{_esc(text)}</code>\n"
                    f"<i>{_esc(str(e))[:100]}</i>",
                    parse_mode=ParseMode.HTML,
                )
    else:
        try:
            u = await client.get_users(text)
            uid_target = u.id
            username = (f"@{u.username}"
                        if u.username else f"ID {u.id}")
        except Exception:
            _clear_admin_session(message.from_user.id)
            return await message.reply_text(
                f"{EMO['cross']} Invalid. "
                f"Send user id or @username.",
                parse_mode=ParseMode.HTML,
            )

    if not uid_target:
        _clear_admin_session(message.from_user.id)
        return await message.reply_text(
            f"{EMO['cross']} Could not identify user.",
            parse_mode=ParseMode.HTML,
        )

    # Already premium?
    existing = await get_premium_user(uid_target)
    if existing and existing.get("expires_at", 0) > time.time():
        _clear_admin_session(message.from_user.id)
        uname = existing.get("username") or uid_target
        exp = _date_ist(existing.get("expires_at", 0))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{EMO['spark']} EXTEND PLAN",
                callback_data=f"pw:member:{uid_target}")],
            [InlineKeyboardButton(
                f"{EMO['back']} BACK", callback_data="pw:main")],
        ])
        return await message.reply_text(
            "\n".join([
                f"{EMO['warn']} <b>User already premium</b>",
                DIV, "",
                f"{EMO['id']} <code>{uid_target}</code>",
                f"{EMO['user']} @{_esc(str(uname).lstrip('@'))}",
                f"{EMO['clock']} Expires: <b>{exp}</b>",
            ]),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    # Save to admin session + show plan picker
    _new_admin_session(message.from_user.id, "pick_plan",
                       target_uid=uid_target,
                       target_username=username)

    try:
        u = await client.get_users(uid_target)
        display = (u.first_name or "") + \
                  (f" {u.last_name}" if u.last_name else "")
        uname_display = (f"@{u.username}"
                         if u.username else f"ID {u.id}")
    except Exception:
        display = str(uid_target)
        uname_display = username or str(uid_target)

    text_out = "\n".join([
        f"{EMO['crown']} <b>{fb('PICK PLAN DURATION')}</b>",
        DIV, "",
        f"{EMO['user']} User     - <b>{_esc(display)}</b>",
        f"{EMO['id']} Username - <code>{_esc(uname_display)}</code>",
        f"{EMO['id']} ID       - <code>{uid_target}</code>",
        "", DIV2, "",
        f"{EMO['spark']} <i>Tap a plan duration below</i>",
    ])

    await message.reply_text(
        text_out,
        reply_markup=kb_pw_plan_picker(uid_target, username),
        parse_mode=ParseMode.HTML,
    )


async def _handle_find_user_input(client, message, text: str):
    """Search for a premium user by id or @username."""
    _clear_admin_session(message.from_user.id)
    doc = None
    if text.lstrip("-").isdigit():
        doc = await get_premium_user(int(text))
    elif text.startswith("@"):
        doc = await find_premium_by_username(text)

    if not doc:
        return await message.reply_text(
            f"{EMO['cross']} <b>Not found in premium DB.</b>",
            reply_markup=kb_pw_back(),
            parse_mode=ParseMode.HTML,
        )

    text_out, kb = await _view_pw_member_detail(doc.get("user_id"))
    await message.reply_text(
        text_out, reply_markup=kb, parse_mode=ParseMode.HTML,
    )


async def _handle_edit_notes_input(client, message, text: str, s):
    """Save admin notes about a user."""
    target_uid = s.get("target_uid")
    _clear_admin_session(message.from_user.id)
    if not target_uid:
        return await message.reply_text(
            f"{EMO['cross']} No target.",
            parse_mode=ParseMode.HTML,
        )

    c = _premium_coll()
    if c is None:
        return await message.reply_text(
            f"{EMO['cross']} DB error.",
            parse_mode=ParseMode.HTML,
        )

    try:
        await c.update_one(
            {"user_id": int(target_uid)},
            {"$set": {"notes": text[:500]}},
        )
        await message.reply_text(
            f"{EMO['ok']} <b>Notes saved.</b>",
            reply_markup=kb_pw_back(f"pw:member:{target_uid}"),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await message.reply_text(
            f"{EMO['cross']} Failed.",
            parse_mode=ParseMode.HTML,
        )


async def _handle_set_contact_input(client, message, text: str):
    """Save contact admin username."""
    _clear_admin_session(message.from_user.id)
    if not re.match(r"^@\w+$", text):
        return await message.reply_text(
            f"{EMO['cross']} <b>Format: @username</b>",
            parse_mode=ParseMode.HTML,
        )
    ok = await set_setting("contact_admin", text)
    if ok:
        await message.reply_text(
            f"{EMO['ok']} Contact saved: <code>{_esc(text)}</code>",
            reply_markup=kb_pw_back(),
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            f"{EMO['cross']} Failed.",
            parse_mode=ParseMode.HTML,
        )


# ═══════════════════════════════════════════════════════════════════════════
# PLAN PICKER (final step of add/extend flow)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:plan:(\d+):(\d+)$"), group=-426,
)
async def cb_pw_plan(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        months = int(q.matches[0].group(2))

        s = _get_admin_session(q.from_user.id)
        if not s or s.get("action") != "pick_plan":
            return await q.answer(
                f"{EMO['warn']} Session expired", show_alert=True,
            )

        target_username = s.get("target_username") or ""

        ok = await add_premium_user(
            user_id=target_uid,
            username=target_username,
            months=months,
            added_by=q.from_user.id,
        )
        if not ok:
            return await q.answer(
                f"{EMO['cross']} Failed", show_alert=True,
            )

        _clear_admin_session(q.from_user.id)

        doc = await get_premium_user(target_uid)
        expires = doc.get("expires_at", 0) if doc else 0

        await q.answer(f"{EMO['ok']} Added")

        text_out = "\n".join([
            f"{EMO['party']} <b>{fb('PREMIUM ADDED')}</b>",
            DIV, "",
            f"{EMO['id']} User     - <code>{target_uid}</code>",
            f"{EMO['user']} Username - "
            f"<code>{_esc(target_username)}</code>",
            "",
            f"{EMO['crown']} Plan    - <code>{months} months</code>",
            f"{EMO['clock']} Expires - "
            f"<code>{_date_ist(expires)}</code>",
            "",
            f"{EMO['spark']} <code>{_now_ist()}</code>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{EMO['plus']} ADD ANOTHER", callback_data="pw:add"),
             InlineKeyboardButton(
                f"{EMO['crown']} VIEW LIST", callback_data="pw:members")],
            [InlineKeyboardButton(
                f"{EMO['back']} BACK", callback_data="pw:main"),
             InlineKeyboardButton(
                f"{EMO['cross']} CLOSE", callback_data="pw:close")],
        ])

        await _pw_safe_edit(q, text_out, kb)

        # Notify the user
        try:
            await client.send_message(
                chat_id=target_uid,
                text="\n".join([
                    f"{EMO['party']} <b>PREMIUM ACTIVATED</b>",
                    DIV, "",
                    f"Hi! Your premium has been activated "
                    f"{EMO['spark']}",
                    "",
                    f"{EMO['crown']} Plan    - "
                    f"<code>{months} months</code>",
                    f"{EMO['clock']} Expires - "
                    f"<code>{_date_ist(expires)}</code>",
                    "", DIV2,
                    f"{EMO['rocket']} <i>Start watching — search a "
                    f"series in the group</i>",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"[PREM] plan pick: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


logger.info("[PREM] Part 6 loaded — admin command + callbacks + input")

# ═══════════════════════════════════════════════════════════════════════════
# EXTEND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:extend:(\d+)$"), group=-426,
)
async def cb_pw_extend(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)
        if not doc:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        _new_admin_session(
            q.from_user.id, "pick_plan",
            target_uid=target_uid,
            target_username=doc.get("username") or "",
        )

        text = "\n".join([
            f"{EMO['spark']} <b>{fb('EXTEND PREMIUM')}</b>",
            DIV, "",
            f"{EMO['id']} <code>{target_uid}</code>",
            f"{EMO['user']} "
            f"@{_esc(str(doc.get('username') or '').lstrip('@'))}",
            "",
            f"{EMO['clock']} Current expires - "
            f"<code>{_date_ist(doc.get('expires_at', 0))}</code>",
            "", DIV2,
            f"{EMO['crown']} <i>Pick new plan duration to stack</i>",
        ])
        await _pw_safe_edit(
            q, text,
            kb_pw_plan_picker(target_uid,
                              doc.get("username") or ""),
        )
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] extend: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# REMOVE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:remove:(\d+)$"), group=-426,
)
async def cb_pw_remove(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)

        text_lines = [
            f"{EMO['warn']} <b>REMOVE PREMIUM?</b>",
            DIV, "",
            f"{EMO['id']} ID - <code>{target_uid}</code>",
        ]
        if doc:
            text_lines.append(
                f"{EMO['user']} "
                f"@{_esc(str(doc.get('username') or '').lstrip('@'))}"
            )
        text_lines += [
            "",
            f"{EMO['fire']} <b>This cannot be undone.</b>",
        ]

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{EMO['cross']} YES, REMOVE",
                callback_data=f"pw:remove_go:{target_uid}")],
            [InlineKeyboardButton(
                f"{EMO['back']} CANCEL",
                callback_data=f"pw:member:{target_uid}")],
        ])
        await _pw_safe_edit(q, "\n".join(text_lines), kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] remove: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:remove_go:(\d+)$"), group=-426,
)
async def cb_pw_remove_go(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        ok = await remove_premium_user(target_uid)
        await q.answer(
            f"{EMO['ok']} Removed" if ok
            else f"{EMO['cross']} Not found"
        )
        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[PREM] remove_go: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EDIT NOTES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:notes:(\d+)$"), group=-426,
)
async def cb_pw_notes(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        _new_admin_session(
            q.from_user.id, "edit_notes", target_uid=target_uid,
        )

        text = "\n".join([
            f"{EMO['gear']} <b>{fb('EDIT NOTES')}</b>",
            DIV, "",
            f"{EMO['id']} ID - <code>{target_uid}</code>",
            "",
            f"{EMO['spark']} <i>Send notes (max 500 chars)</i>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{EMO['back']} CANCEL",
                callback_data=f"pw:member:{target_uid}"),
        ]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] notes: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FIND USER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:find$"), group=-426)
async def cb_pw_find(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        _new_admin_session(q.from_user.id, "find_user")
        text, kb = await _view_pw_find()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] find: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EXPIRING / EXPIRED / STATS / CONTACT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:expiring$"), group=-426)
async def cb_pw_expiring(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        text, kb = await _view_pw_expiring()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expiring: {e}")


@Client.on_callback_query(filters.regex(r"^pw:expired$"), group=-426)
async def cb_pw_expired(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        text, kb = await _view_pw_expired()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expired: {e}")


@Client.on_callback_query(filters.regex(r"^pw:stats$"), group=-426)
async def cb_pw_stats(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        text, kb = await _view_pw_stats()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] stats: {e}")


@Client.on_callback_query(filters.regex(r"^pw:contact$"), group=-426)
async def cb_pw_contact(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer(f"{EMO['lock']} Admin only", show_alert=True)
    try:
        current = await get_contact_admin() or "-"
        _new_admin_session(q.from_user.id, "set_contact")
        text = "\n".join([
            f"{EMO['gear']} <b>{fb('SET CONTACT ADMIN')}</b>",
            DIV, "",
            f"{EMO['crown']} Current - <code>{_esc(current)}</code>",
            "",
            f"{EMO['spark']} <i>Send @username of admin to contact</i>",
            f"{EMO['id']} Example: <code>@your_username</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{EMO['back']} CANCEL", callback_data="pw:main"),
        ]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] contact: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DISMISS REMINDER (from user's expiry reminders)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:dismiss_reminder$"), group=-426,
)
async def cb_pw_dismiss(client, q):
    try:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer(f"{EMO['ok']} OK")
    except Exception:
        pass


logger.info("[PREM] Part 7 loaded — admin callbacks complete")

# ═══════════════════════════════════════════════════════════════════════════
# GROUP → PM REDIRECT (called from series_group.py hook)
# ═══════════════════════════════════════════════════════════════════════════
async def handle_premium_group_search(
    client: Client,
    message,
    query: str,
    db_result: Optional[Dict[str, Any]],
    tmdb_results: List[Dict[str, Any]],
    status_msg=None,
) -> bool:
    """
    Called from series_group.py when a search happens in the group.
    If the user is premium AND we have DB hits → redirect to PM.
    Returns True if handled, False to fall through to normal flow.

    Signature matches series_group.py call:
        (client, message, query, db_result, tmdb_results)
    """
    try:
        if not message or not message.from_user:
            return False
        uid = message.from_user.id

        if not await is_premium(uid):
            return False

        if not (db_result and db_result.get("hits")):
            return False

        matched_title = db_result.get("matched_title") or query

        ok = await _premium_redirect_to_pm(
            client, message, status_msg, uid, matched_title,
            db_result.get("hits") or [],
            tmdb_results or [],
        )
        return ok
    except Exception as e:
        logger.exception(f"[PREM] group search hook: {e}")
        return False


async def _premium_redirect_to_pm(
    client: Client,
    message,
    status_msg,
    uid: int,
    title: str,
    hits: List[Dict[str, Any]],
    tmdb_results: List[Dict[str, Any]],
) -> bool:
    """Send redirect message in group + prep PM session."""
    try:
        tmdb_id = None
        poster = None
        year = ""
        rating = 0
        display_title = title

        # Try exact title match first
        for t in (tmdb_results or []):
            t_title = (t.get("title") or "").lower().strip()
            if t_title == title.lower().strip():
                tmdb_id = t.get("tmdb_id")
                poster = t.get("poster")
                year = t.get("year") or ""
                rating = t.get("rating", 0) or 0
                display_title = t.get("title") or title
                break

        # Fallback to first result
        if not tmdb_id and tmdb_results:
            ch = tmdb_results[0]
            tmdb_id = ch.get("tmdb_id")
            poster = ch.get("poster")
            year = ch.get("year") or ""
            rating = ch.get("rating", 0) or 0
            display_title = ch.get("title") or title

        # Fetch full TMDB season data
        tmdb_seasons: List[Dict[str, Any]] = []
        if tmdb_id:
            try:
                from plugins.series_group import (
                    _tmdb_series_details, _tmdb_seasons,
                )
                details = await _tmdb_series_details(tmdb_id)
                if details:
                    tmdb_seasons = _tmdb_seasons(details)
            except Exception as e:
                logger.debug(f"[PREM] tmdb details: {e}")

        # Get bot username for deep link
        try:
            me = await client.get_me()
            bot_username = me.username or "Downtown_Villa_Bot"
        except Exception:
            bot_username = "Downtown_Villa_Bot"

        series_data = {
            "title": display_title,
            "tmdb_id": tmdb_id,
            "poster": poster,
            "year": year,
            "rating": rating,
            "tmdb_seasons": tmdb_seasons,
            "hits": hits,
            "search_query": title,
        }

        # Delete status message
        try:
            if status_msg:
                await status_msg.delete()
        except Exception:
            pass

        # Delete original search
        try:
            await message.delete()
        except Exception:
            pass

        # Build group reply
        group_text = "\n".join([
            f"{EMO['crown']} <b>{fb('DOWNTOWN VILLA')}</b>",
            f"{EMO['spark']} <b>PREMIUM</b>",
            DIV, "",
            f"{EMO['film']} <b>{_esc(display_title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            "",
            DIV2, "",
            f"{EMO['rocket']} <b>Sent to your PM</b>",
            f"{EMO['spark']} <i>Open the bot to start watching</i>",
        ])

        # Send group message with deep link button
        deep_link = f"https://t.me/{bot_username}?start=prem_start"
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=group_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{EMO['rocket']} OPEN IN PM",
                        url=deep_link,
                    ),
                ]]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[PREM] group reply: {e}")

        logger.info(
            f"[PREM] redirect user={uid} title={display_title!r}"
        )

        # Now prep PM session
        await _prepare_pm_session(client, uid, series_data)
        return True
    except Exception as e:
        logger.exception(f"[PREM] redirect: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# PM SESSION PREP — creates poster + saves session
# ═══════════════════════════════════════════════════════════════════════════
async def _prepare_pm_session(client: Client, uid: int,
                                series_data: Dict[str, Any]):
    """
    Send a NEW poster with language picker to user's PM.
    Saves session in DB.
    """
    try:
        title = series_data.get("title") or "?"
        year = series_data.get("year") or ""
        rating = series_data.get("rating", 0) or 0
        tmdb_seasons = series_data.get("tmdb_seasons") or []
        poster_path = series_data.get("poster")
        hits = series_data.get("hits") or []

        # Poster URL
        poster_url = None
        if poster_path:
            if poster_path.startswith("http"):
                poster_url = poster_path
            else:
                poster_url = (
                    f"https://image.tmdb.org/t/p/w500{poster_path}"
                )

        total_eps = sum(int(s.get("episodes", 0) or 0)
                        for s in tmdb_seasons)
        seasons_count = len(tmdb_seasons)
        slug = _slug(title)

        # Check if session already exists
        existing = await get_session(uid, slug)
        if existing and existing.get("poster_msg_id"):
            # Session exists — re-send a fresh language picker
            logger.info(f"[PREM] session exists for {uid} {slug}")

        # Available languages
        langs_default = ["English", "Hindi", "Tamil",
                         "Telugu", "Malayalam"]
        available_langs: Set[str] = set()
        try:
            for h in hits[:50]:
                hl = h.get("languages") or []
                for lang in hl:
                    if lang:
                        # Normalize to Title Case
                        lang_norm = str(lang).strip().title()
                        available_langs.add(lang_norm)
        except Exception:
            pass

        if available_langs:
            ordered = [l for l in langs_default
                       if l in available_langs]
            extra = sorted(l for l in available_langs
                           if l not in ordered)
            langs = (ordered + extra)[:6]
        else:
            langs = ["English"]

        # Build text
        rating_line = ""
        if rating:
            rating_line = (
                f"{render_stars(rating)} <code>{rating:.1f}</code>"
            )

        text = "\n".join([
            f"{EMO['film']} <b>{_esc(title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            rating_line,
            f"{EMO['tv']} <code>{seasons_count} seasons</code>  •  "
            f"<code>{total_eps} episodes</code>",
            "",
            DIV, "",
            f"{EMO['crown']} <b>PREMIUM MODE</b>",
            "",
            f"{EMO['spark']} <i>Pick language to start</i>",
        ])

        # Build language keyboard
        kb_rows = []
        row = []
        for i, lang in enumerate(langs):
            row.append(InlineKeyboardButton(
                f"{EMO['spark']} {lang}",
                callback_data=f"pw:lang:{slug}:{i}",
            ))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        kb_rows.append([InlineKeyboardButton(
            f"{EMO['book']} WATCH ORDER",
            callback_data=f"pw:wo:{slug}",
        )])
        kb_rows.append([InlineKeyboardButton(
            f"{EMO['cross']} CANCEL",
            callback_data=f"pw:cancel:{slug}",
        )])

        kb = InlineKeyboardMarkup(kb_rows)

        # Send photo or text
        msg = None
        if poster_url:
            try:
                msg = await client.send_photo(
                    chat_id=uid,
                    photo=poster_url,
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] send_photo failed: {e}")

        if not msg:
            msg = await client.send_message(
                chat_id=uid,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        # Persist session (CLEAN hits — no FileHit objects)
        c = _sessions_coll()
        if c is not None:
            clean_hits = _clean_hits(hits)
            await c.update_one(
                {"user_id": uid, "series_slug": slug},
                {"$set": {
                    "user_id": uid,
                    "series_slug": slug,
                    "series_title": title,
                    "poster": poster_path,
                    "year": year,
                    "rating": rating,
                    "tmdb_id": series_data.get("tmdb_id"),
                    "tmdb_seasons": tmdb_seasons,
                    "hits": clean_hits,
                    "available_langs": langs,
                    "poster_chat_id": uid,
                    "poster_msg_id": msg.id,
                    "last_activity_at": time.time(),
                },
                 "$setOnInsert": {
                    "seasons": {},
                    "language": "",
                    "started_at": time.time(),
                    "status": "watching",
                    "completed_at": None,
                    "current_file_msg_id": None,
                    "current_season": 1,
                    "current_episode": 1,
                    "rated": False,
                }},
                upsert=True,
            )

        logger.info(f"[PREM] PM poster sent to {uid} msg={msg.id}")
    except Exception as e:
        logger.exception(f"[PREM] prepare PM: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# POSTER RENDERING — live update the persistent poster
# ═══════════════════════════════════════════════════════════════════════════
def build_poster_text(session: Dict[str, Any], title: str,
                       year: str = "", rating: float = 0) -> str:
    """
    THE persistent poster text.
    Shows the classic progress bar format.
    """
    p = compute_progress(session)
    seasons_raw = session.get("seasons") or {}
    seasons_ordered = sorted(int(k) for k in seasons_raw.keys()
                              if k.isdigit())
    is_complete = (p["total_eps"] > 0
                   and p["total_watched"] >= p["total_eps"])

    lines = [
        f"{EMO['film']} <b>{_esc(title)}</b>"
        + (f" <code>({year})</code>" if year else ""),
    ]

    if rating:
        lines.append(
            f"{render_stars(rating)} <code>{rating:.1f}</code>"
        )

    if is_complete:
        lines.append("")
        lines.append(f"{EMO['ok']} <b>COMPLETED</b>")

    lines += ["", f"{EMO['chart']} <b>YOUR PROGRESS</b>", ""]

    if not seasons_ordered:
        lines.append(f"{EMO['spark']} <i>Pick a language to start</i>")
    else:
        for sn in seasons_ordered:
            s_data = seasons_raw.get(str(sn)) or {}
            watched = len(s_data.get("watched") or [])
            total = int(s_data.get("total_eps", 0) or 0)

            if total == 0:
                bar = render_progress_bar(0)
                icon = EMO["box"]
            else:
                pct = watched / total * 100
                bar = render_progress_bar(pct)
                if watched >= total:
                    icon = EMO["ok"]
                elif watched > 0:
                    icon = EMO["yellow"]
                else:
                    icon = EMO["box"]

            lines.append(
                f"S{sn:02d} {bar} "
                f"<code>{watched}/{total}</code>  {icon}"
            )

    if seasons_ordered:
        lines += ["", DIV2, ""]
        lines.append(
            f"{EMO['chart']} Delivered: "
            f"<b>{p['total_watched']}/{p['total_eps']}</b> "
            f"<code>({p['pct']}%)</code>"
        )

        if is_complete:
            started = session.get("started_at", 0)
            completed = session.get("completed_at", 0) or time.time()
            total_hours = int(p["total_eps"] * 22 / 60)

            lines.append(
                f"{EMO['clock']} Total time: "
                f"<code>~{total_hours} hours</code>"
            )
            if started:
                lines.append(
                    f"{EMO['cal']} Started: "
                    f"<code>{_relative_time(started)}</code>"
                )
            lines.append(
                f"{EMO['cal']} Finished: "
                f"<code>{_relative_time(completed)}</code>"
            )
            lines.append("")
            lines.append(f"{EMO['party']} <b>CONGRATULATIONS!</b>")
        else:
            remaining = p["total_eps"] - p["total_watched"]
            hours_left = remaining * 22 / 60
            lines.append(
                f"{EMO['clock']} Time left: "
                f"<code>~{int(hours_left)} hours</code>"
            )

    lines += ["", f"<code>{_now_ist()}</code>"]
    return "\n".join(lines)


def build_poster_kb(session: Dict[str, Any], slug: str):
    """
    Poster action keyboard.
    Logic:
      - If complete → [MARK COMPLETE] + [RATE]
      - If has next ep → [Resume SxxExx]
      - Always: [Seasons] [Watch Order] (if applicable)
    """
    next_ep = find_next_episode(session)
    complete = is_series_complete(session)
    has_lang = bool(session.get("language"))
    has_seasons = bool(session.get("seasons"))
    rated = session.get("rated", False)

    if not has_lang and not has_seasons:
        return None

    rows = []

    # Complete → mark complete + rate
    if complete:
        if not rated:
            rows.append([InlineKeyboardButton(
                f"{EMO['star']} RATE SERIES",
                callback_data=f"pw:rate_menu:{slug}",
            )])
        rows.append([InlineKeyboardButton(
            f"{EMO['trophy']} MARK COMPLETE",
            callback_data=f"pw:complete:{slug}",
        )])
    elif next_ep:
        sn, ep = next_ep
        rows.append([InlineKeyboardButton(
            f"{EMO['play']} Resume S{sn:02d}E{ep:02d}",
            callback_data=f"pw:play:{slug}:{sn}:{ep}",
        )])

    if has_seasons:
        rows.append([
            InlineKeyboardButton(
                f"{EMO['tv']} Seasons",
                callback_data=f"pw:seasons:{slug}"),
            InlineKeyboardButton(
                f"{EMO['book']} Watch Order",
                callback_data=f"pw:wo:{slug}"),
        ])
        if not complete:
            rows.append([InlineKeyboardButton(
                f"{EMO['chart']} Missing episodes",
                callback_data=f"pw:missing:{slug}",
            )])
    else:
        # Not started yet — show language picker
        langs = session.get("available_langs") or ["English"]
        row = []
        for i, lang in enumerate(langs[:6]):
            row.append(InlineKeyboardButton(
                f"{EMO['spark']} {lang}",
                callback_data=f"pw:lang:{slug}:{i}",
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

    return InlineKeyboardMarkup(rows)


async def _render_poster(client: Client, session: Dict[str, Any]) -> bool:
    """
    Edit the persistent poster message with latest progress.
    Tries caption first, then text.
    """
    try:
        uid = session.get("user_id")
        chat_id = session.get("poster_chat_id") or uid
        msg_id = session.get("poster_msg_id")
        if not msg_id:
            return False

        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        year = session.get("year") or ""
        rating = session.get("rating") or 0

        text = build_poster_text(session, title, year, rating)
        kb = build_poster_kb(session, slug)

        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{EMO['cross']} CLOSE",
                    callback_data="pw:close_session"),
            ]])

        # Try caption first
        try:
            await client.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return True
        except MessageNotModified:
            return True
        except MessageIdInvalid:
            logger.debug(f"[PREM] poster msg invalid: {msg_id}")
            return False
        except Exception as e:
            logger.debug(f"[PREM] caption edit failed: {e}")

        # Fallback to text edit
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except MessageNotModified:
            return True
        except Exception as e2:
            logger.warning(f"[PREM] render_poster: {e2}")
            return False
    except Exception as e:
        logger.exception(f"[PREM] render_poster: {e}")
        return False


logger.info("[PREM] Part 8 loaded — group redirect + PM prep + poster")

# ═══════════════════════════════════════════════════════════════════════════
# LANGUAGE PICKER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:lang:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_lang(client, q):
    """Handle user picking a language."""
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        lang_idx = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        langs = session.get("available_langs") or ["English"]
        if lang_idx < 0 or lang_idx >= len(langs):
            return await q.answer(
                f"{EMO['cross']} Invalid", show_alert=True,
            )

        chosen_lang = langs[lang_idx]
        await q.answer(f"{EMO['spark']} {chosen_lang}")

        title = session.get("series_title") or "?"
        tmdb_seasons = session.get("tmdb_seasons") or []

        # Fresh search with chosen language
        fresh_hits = []
        try:
            from plugins.series_group import _engine_search
            fresh_hits = await _engine_search(
                title, language=chosen_lang,
            ) or []
        except Exception as e:
            logger.warning(f"[PREM] lang search: {e}")

        if not fresh_hits:
            # Try searching with alternative title variants
            for alt in [title, session.get("search_query", "")]:
                if not alt:
                    continue
                try:
                    from plugins.series_group import _engine_search
                    fresh_hits = await _engine_search(alt) or []
                    if fresh_hits:
                        break
                except Exception:
                    continue

        if not fresh_hits:
            fresh_hits = session.get("hits") or []

        # Build seasons doc from TMDB + hits
        db_seasons: Dict[int, Set[int]] = defaultdict(set)
        for f in fresh_hits:
            sn = f.get("season")
            ep = f.get("episode")
            if sn is not None:
                db_seasons[sn].add(ep if ep is not None else 0)

        seasons_doc: Dict[str, Dict[str, Any]] = {}
        for s in tmdb_seasons:
            sn = s.get("season")
            eps = int(s.get("episodes", 0) or 0)
            if sn is None:
                continue
            db_count = len(db_seasons.get(sn, set()))
            final_count = max(eps, db_count)
            seasons_doc[str(sn)] = {
                "total_eps": final_count,
                "watched": [],
                "sent": [],
                "current_ep": 1,
            }

        if not seasons_doc and db_seasons:
            for sn, eps_set in db_seasons.items():
                seasons_doc[str(sn)] = {
                    "total_eps": len(eps_set),
                    "watched": [],
                    "sent": [],
                    "current_ep": 1,
                }

        # Preserve existing watched progress
        old_seasons = session.get("seasons") or {}
        for sn_str, s_data in old_seasons.items():
            if sn_str in seasons_doc:
                seasons_doc[sn_str]["watched"] = (
                    s_data.get("watched") or []
                )
                seasons_doc[sn_str]["sent"] = (
                    s_data.get("sent") or []
                )

        # Save cleaned hits (MongoDB-safe)
        clean_hits = _clean_hits(fresh_hits)

        c = _sessions_coll()
        if c is not None:
            await c.update_one(
                {"user_id": uid, "series_slug": slug},
                {"$set": {
                    "seasons": seasons_doc,
                    "language": chosen_lang,
                    "hits": clean_hits,
                    "last_activity_at": time.time(),
                }},
            )

        fresh = await get_session(uid, slug)
        if not fresh:
            return

        # Show seasons view
        seasons_view_text, seasons_kb = build_seasons_view(
            fresh, slug, title,
        )

        await _pw_safe_edit(q, seasons_view_text, seasons_kb,
                             is_caption=True)

        logger.info(
            f"[PREM] lang picked: u={uid} s={slug} lang={chosen_lang}"
        )
    except Exception as e:
        logger.exception(f"[PREM] cb_pw_lang: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SEASONS VIEW BUILDER
# ═══════════════════════════════════════════════════════════════════════════
def build_seasons_view(session: Dict[str, Any], slug: str,
                        title: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Show list of seasons with progress."""
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    lang = session.get("language") or "?"
    p = compute_progress(session)

    lines = [
        f"{EMO['tv']} <b>{_esc(title)}</b>",
        f"{EMO['lang']} <code>{_esc(lang)}</code>",
        DIV, "",
        f"{EMO['spark']} <b>PICK A SEASON</b>",
        "",
        f"{EMO['chart']} Overall: <code>{p['total_watched']}/"
        f"{p['total_eps']}</code> <code>({p['pct']}%)</code>",
        "",
    ]

    rows = []
    for sn in ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        watched = len(s_data.get("watched") or [])
        total = int(s_data.get("total_eps", 0) or 0)

        if total > 0 and watched >= total:
            icon = EMO["ok"]
        elif watched > 0:
            icon = EMO["yellow"]
        else:
            icon = EMO["box"]

        label = f"{icon} S{sn:02d}  •  {watched}/{total}"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"pw:season:{slug}:{sn}",
        )])

    rows.append([InlineKeyboardButton(
        f"{EMO['chart']} Full Progress",
        callback_data=f"pw:poster:{slug}",
    )])
    rows.append([InlineKeyboardButton(
        f"{EMO['back']} Back",
        callback_data=f"pw:poster:{slug}",
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SEASONS VIEW CALLBACK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:seasons:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_seasons(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        text, kb = build_seasons_view(session, slug, title)

        await _pw_safe_edit(q, text, kb, is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] seasons: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EPISODES GRID VIEW BUILDER
# ═══════════════════════════════════════════════════════════════════════════
def build_episodes_view(session: Dict[str, Any], slug: str,
                          title: str, season: int
                          ) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Show episode grid for a specific season.
    ✅ = watched | ▶️ = tap to send | 📥 = Send All
    """
    s_data = (session.get("seasons") or {}).get(str(season)) or {}
    total = int(s_data.get("total_eps", 0) or 0)
    watched = set(s_data.get("watched") or [])
    sent = set(s_data.get("sent") or [])

    pct = (len(watched) / total * 100) if total else 0
    bar = render_progress_bar(pct)

    lines = [
        f"{EMO['tv']} <b>{_esc(title)}</b>",
        f"{EMO['film']} <b>Season {season:02d}</b>",
        DIV, "",
        f"{bar}  <code>{len(watched)}/{total}</code>",
        "",
        f"{EMO['spark']} <i>Tap an episode to receive it</i>",
        "",
        f"{EMO['ok']} = already watched  •  "
        f"{EMO['play']} = tap to send",
        "",
    ]

    rows = []
    row = []
    for ep in range(1, total + 1):
        mark = EMO["ok"] if ep in watched else EMO["play"]
        row.append(InlineKeyboardButton(
            f"{mark} E{ep:02d}",
            callback_data=f"pw:play:{slug}:{season}:{ep}",
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Send-all button
    if total > 0:
        rows.append([InlineKeyboardButton(
            f"{EMO['send']} SEND ALL {total} EPISODES",
            callback_data=f"pw:sendall:{slug}:{season}",
        )])

    # Navigation
    rows.append([
        InlineKeyboardButton(
            f"{EMO['back']} Seasons",
            callback_data=f"pw:seasons:{slug}"),
        InlineKeyboardButton(
            f"{EMO['chart']} Progress",
            callback_data=f"pw:poster:{slug}"),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# EPISODES VIEW CALLBACK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:season:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_season(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        text, kb = build_episodes_view(session, slug, title, season)

        await _pw_safe_edit(q, text, kb, is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] season: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# POSTER NAV (from any sub-view back to main poster)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:poster:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_poster(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        year = session.get("year") or ""
        rating = session.get("rating") or 0

        text = build_poster_text(session, title, year, rating)
        kb = build_poster_kb(session, slug)

        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{EMO['cross']} CLOSE",
                    callback_data="pw:close_session"),
            ]])

        await _pw_safe_edit(q, text, kb, is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] poster: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CANCEL (delete the preview message before starting)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:cancel:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_cancel(client, q):
    try:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer(f"{EMO['cross']} Cancelled")
    except Exception:
        try:
            await q.answer("OK")
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# MISSING EPISODES VIEW
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:missing:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_missing(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        seasons_raw = session.get("seasons") or {}
        ordered = sorted(
            int(k) for k in seasons_raw.keys() if k.isdigit()
        )

        lines = [
            f"{EMO['chart']} <b>{_esc(title)}</b>",
            f"{EMO['search']} <b>MISSING EPISODES</b>",
            DIV, "",
        ]

        rows = []
        total_missing = 0
        for sn in ordered:
            s_data = seasons_raw.get(str(sn)) or {}
            total = int(s_data.get("total_eps", 0) or 0)
            watched = set(s_data.get("watched") or [])
            missing = [ep for ep in range(1, total + 1)
                       if ep not in watched]

            if not missing:
                continue

            total_missing += len(missing)
            short = ", ".join(f"E{e:02d}" for e in missing[:8])
            if len(missing) > 8:
                short += f" +{len(missing) - 8} more"

            lines.append(f"{EMO['tv']} <b>S{sn:02d}</b> — "
                         f"<code>{short}</code>")
            rows.append([InlineKeyboardButton(
                f"{EMO['send']} Send missing S{sn:02d} "
                f"({len(missing)})",
                callback_data=f"pw:sendmissing:{slug}:{sn}",
            )])

        if total_missing == 0:
            lines.append(f"{EMO['party']} <b>All caught up!</b>")

        lines += ["", DIV2, "", f"<code>{_now_ist()}</code>"]
        rows.append([InlineKeyboardButton(
            f"{EMO['back']} Back",
            callback_data=f"pw:poster:{slug}",
        )])

        await _pw_safe_edit(q, "\n".join(lines),
                             InlineKeyboardMarkup(rows),
                             is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] missing: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CLOSE SESSION MESSAGE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:close_session$"), group=-420,
)
async def cb_pw_close_session(client, q):
    try:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer(f"{EMO['ok']} Closed")
    except Exception:
        pass


logger.info("[PREM] Part 9 loaded — language + seasons + episodes grid")

# ═══════════════════════════════════════════════════════════════════════════
# PLAY ONE EPISODE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:play:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_play(client, q):
    """Send a single episode file."""
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        await q.answer(f"{EMO['rocket']} Sending...")

        # Send the file
        sent = await _send_episode_file(
            client, uid, session, season, episode,
        )

        # Mark as sent + update position
        if sent:
            await mark_sent(uid, slug, season, episode)
            await set_current_position(uid, slug, season, episode)

        # Update poster with new stats
        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] play: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SEND ALL EPISODES IN A SEASON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:sendall:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_sendall(client, q):
    """Send ALL episodes in a season (unwatched only)."""
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 5.0):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        s_data = (session.get("seasons") or {}).get(str(season)) or {}
        total = int(s_data.get("total_eps", 0) or 0)
        if total == 0:
            return await q.answer(
                f"{EMO['cross']} No episodes", show_alert=True,
            )

        # Only send episodes not already watched
        watched = set(s_data.get("watched") or [])
        to_send = [ep for ep in range(1, total + 1)
                   if ep not in watched]

        if not to_send:
            return await q.answer(
                f"{EMO['ok']} All watched already", show_alert=True,
            )

        await q.answer(
            f"{EMO['rocket']} Sending {len(to_send)} episodes..."
        )

        for ep in to_send:
            try:
                sent = await _send_episode_file(
                    client, uid, session, season, ep,
                )
                if sent:
                    await mark_sent(uid, slug, season, ep)
                await asyncio.sleep(0.6)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    sent = await _send_episode_file(
                        client, uid, session, season, ep,
                    )
                    if sent:
                        await mark_sent(uid, slug, season, ep)
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[PREM] batch S{season}E{ep}: {e}")

        # Update poster
        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] sendall: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SEND MISSING EPISODES (across seasons)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:sendmissing:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_sendmissing(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 5.0):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        s_data = (session.get("seasons") or {}).get(str(season)) or {}
        total = int(s_data.get("total_eps", 0) or 0)
        watched = set(s_data.get("watched") or [])
        missing = [ep for ep in range(1, total + 1)
                   if ep not in watched]

        if not missing:
            return await q.answer(
                f"{EMO['ok']} Nothing missing", show_alert=True,
            )

        await q.answer(
            f"{EMO['rocket']} Sending {len(missing)} missing..."
        )

        for ep in missing:
            try:
                sent = await _send_episode_file(
                    client, uid, session, season, ep,
                )
                if sent:
                    await mark_sent(uid, slug, season, ep)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[PREM] missing S{season}E{ep}: {e}")

        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] sendmissing: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# EPISODE FILE SENDER
# ═══════════════════════════════════════════════════════════════════════════
async def _send_episode_file(client: Client, uid: int,
                               session: Dict[str, Any],
                               season: int, episode: int) -> bool:
    """
    Send a single episode file to user's PM.
    Attaches [✅ MARK AS WATCHED] + [▶️ WATCH NEXT] buttons.
    """
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        lang = session.get("language") or ""
        hits = session.get("hits") or []

        # Find matching file
        chosen_file = None
        for f in hits:
            if (f.get("season") == season
                    and f.get("episode") == episode):
                chosen_file = f
                break

        if not chosen_file:
            try:
                await client.send_message(
                    chat_id=uid,
                    text="\n".join([
                        f"{EMO['cross']} <b>File not found</b>",
                        DIV, "",
                        f"{EMO['film']} S{season:02d}E{episode:02d}",
                        "",
                        f"{EMO['warn']} <i>This episode isn't "
                        f"available in the selected language.</i>",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return False

        quality = chosen_file.get("quality") or "?"
        size = _fmt_size(chosen_file.get("file_size", 0))
        langs = "+".join(chosen_file.get("languages") or []) or \
                lang or "?"

        # File caption
        file_caption = "\n".join([
            f"{EMO['film']} <b>{_esc(title)}</b>",
            f"{EMO['tv']} <b>S{season:02d}E{episode:02d}</b>",
            f"{EMO['spark']} <code>{quality}</code>  •  "
            f"<code>{langs}</code>",
            f"{EMO['chart']} Size: <code>{size}</code>",
            "",
            f"{EMO['crown']} <i>Premium • No Auto-Delete</i>",
        ])

        # Get file_id / chat_id / message_id
        fid = chosen_file.get("file_id")
        src_chat = chosen_file.get("chat_id")
        src_msg = chosen_file.get("message_id")
        fh = chosen_file.get("file_hit")
        if fh:
            if not src_chat:
                src_chat = getattr(fh, "chat_id", None)
            if not src_msg:
                src_msg = (getattr(fh, "message_id", None)
                           or getattr(fh, "msg_id", None))
            if not fid:
                fid = getattr(fh, "file_id", "") or ""

        sent_msg = None

        # Method 1: cached media (uses file_id)
        if fid:
            try:
                sent_msg = await client.send_cached_media(
                    chat_id=uid,
                    file_id=fid,
                    caption=file_caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] cached send: {e}")

        # Method 2: copy from source chat
        if not sent_msg and src_chat and src_msg:
            try:
                sent_msg = await client.copy_message(
                    chat_id=uid,
                    from_chat_id=src_chat,
                    message_id=src_msg,
                    caption=file_caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] copy send: {e}")

        if not sent_msg:
            logger.warning(f"[PREM] failed to send file u={uid}")
            try:
                await client.send_message(
                    chat_id=uid,
                    text="\n".join([
                        f"{EMO['cross']} <b>Delivery failed</b>",
                        DIV, "",
                        f"{EMO['warn']} <i>Please try again or "
                        f"contact support.</i>",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return False

        # Attach [✅ MARK AS WATCHED] + [▶️ WATCH NEXT]
        try:
            await client.edit_message_reply_markup(
                chat_id=uid,
                message_id=sent_msg.id,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"{EMO['check']} MARK AS WATCHED",
                        callback_data=(
                            f"pw:watched:{slug}:{season}:"
                            f"{episode}:{sent_msg.id}"
                        ),
                    )],
                    [InlineKeyboardButton(
                        f"{EMO['next']} WATCH NEXT",
                        callback_data=(
                            f"pw:next:{slug}:{season}:{episode}"
                        ),
                    )],
                ]),
            )
        except Exception as e:
            logger.debug(f"[PREM] attach buttons: {e}")

        await update_current_file_msg(uid, slug, sent_msg.id)
        return True
    except Exception as e:
        logger.exception(f"[PREM] send episode: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# MARK AS WATCHED — core action
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(
        r"^pw:watched:([a-z0-9_]+):(\d+):(\d+):(\d+)$"
    ),
    group=-420,
)
async def cb_pw_watched(client, q):
    """
    Mark episode as watched:
    1. Add to watched array
    2. Update file button → ✅ WATCHED
    3. Schedule file delete (30s grace)
    4. Update poster
    5. Notify season/series complete
    """
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 1.5):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))
        file_msg_id = int(q.matches[0].group(4))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        # 1. Mark watched
        await mark_watched(uid, slug, season, episode)
        await set_current_position(uid, slug, season, episode)

        # 2. Update file message button → ✅ WATCHED (no action)
        try:
            await client.edit_message_reply_markup(
                chat_id=uid,
                message_id=file_msg_id,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{EMO['ok']} WATCHED",
                        callback_data=(
                            f"pw:already_watched:{slug}:"
                            f"{season}:{episode}"
                        ),
                    ),
                ]]),
            )
        except Exception as e:
            logger.debug(f"[PREM] file edit: {e}")

        # 3. Schedule auto-delete after grace period
        asyncio.create_task(
            _auto_delete_file(client, uid, file_msg_id,
                              FILE_DELETE_GRACE_SEC)
        )

        # 4. Update poster
        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)

        # 5. Season complete notification
        if fresh and is_season_complete(fresh, season):
            await _season_complete_notify(
                client, uid, fresh, season,
            )

        # 6. Series complete notification
        if fresh and is_series_complete(fresh):
            await _series_complete_notify(client, uid, fresh)

        await q.answer(f"{EMO['ok']} Watched")
        logger.info(
            f"[PREM] watched u={uid} {slug} "
            f"S{season:02d}E{episode:02d}"
        )
    except Exception as e:
        logger.exception(f"[PREM] watched: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(
    filters.regex(
        r"^pw:already_watched:([a-z0-9_]+):(\d+):(\d+)$"
    ),
    group=-420,
)
async def cb_pw_already_watched(client, q):
    try:
        await q.answer(f"{EMO['ok']} Already watched")
    except Exception:
        pass


async def _auto_delete_file(client: Client, uid: int,
                              msg_id: int, grace_sec: int = 30):
    """Delete a file after grace_sec (with cancel if user is fast)."""
    try:
        await asyncio.sleep(grace_sec)
        try:
            await client.delete_messages(uid, msg_id)
            logger.info(f"[PREM] auto-deleted file {msg_id} for {uid}")
        except Exception as e:
            logger.debug(f"[PREM] auto-delete: {e}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.debug(f"[PREM] auto-delete task: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# WATCH NEXT — send next episode
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:next:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_next(client, q):
    """Mark current as watched + send next episode."""
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer(f"{EMO['clock']} Wait")

        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Session not found", show_alert=True,
            )

        # Mark current as watched
        await mark_watched(uid, slug, season, episode)

        # Compute next
        s_data = (session.get("seasons") or {}).get(str(season)) or {}
        total = int(s_data.get("total_eps", 0) or 0)
        next_ep = episode + 1

        if next_ep > total:
            # Look for next season
            seasons_raw = session.get("seasons") or {}
            ordered = sorted(
                int(k) for k in seasons_raw.keys() if k.isdigit()
            )
            next_season = None
            for sn in ordered:
                if sn > season:
                    next_season = sn
                    break

            if next_season:
                await q.answer(f"{EMO['rocket']} Next season")
                await _send_episode_file(
                    client, uid, session, next_season, 1,
                )
                await set_current_position(
                    uid, slug, next_season, 1,
                )
                fresh = await get_session(uid, slug)
                if fresh:
                    await _render_poster(client, fresh)
                return
            else:
                # Series complete
                await q.answer(f"{EMO['trophy']} Series complete!")
                fresh = await get_session(uid, slug)
                if fresh:
                    await _render_poster(client, fresh)
                    await _series_complete_notify(
                        client, uid, fresh,
                    )
                return

        await q.answer(f"{EMO['next']} Next")
        sent = await _send_episode_file(
            client, uid, session, season, next_ep,
        )
        if sent:
            await mark_sent(uid, slug, season, next_ep)
        await set_current_position(uid, slug, season, next_ep)

        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] next: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SEASON COMPLETE NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════
async def _season_complete_notify(client: Client, uid: int,
                                    session: Dict[str, Any],
                                    season: int):
    """Send notification when a season is 100% complete."""
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        seasons_raw = session.get("seasons") or {}
        ordered = sorted(
            int(k) for k in seasons_raw.keys() if k.isdigit()
        )

        next_season = None
        for sn in ordered:
            if sn > season:
                next_season = sn
                break

        if next_season:
            text = "\n".join([
                f"{EMO['party']} <b>SEASON {season} COMPLETE!</b>",
                DIV, "",
                f"{EMO['film']} <b>{_esc(title)}</b>",
                "",
                f"{EMO['trophy']} Season {season:02d} done!",
                "",
                f"{EMO['rocket']} <b>Ready for Season "
                f"{next_season}?</b>",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{EMO['play']} START S{next_season:02d}E01",
                    callback_data=(
                        f"pw:season:{slug}:{next_season}"
                    ),
                )],
            ])
        else:
            text = "\n".join([
                f"{EMO['party']} <b>SEASON COMPLETE!</b>",
                DIV, "",
                f"{EMO['film']} <b>{_esc(title)}</b>",
                f"{EMO['trophy']} Season {season:02d} done!",
                "",
                f"{EMO['spark']} <b>Almost done!</b>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{EMO['play']} CONTINUE",
                    callback_data=f"pw:poster:{slug}",
                ),
            ]])

        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PREM] season notify: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SERIES COMPLETE NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════
async def _series_complete_notify(client: Client, uid: int,
                                    session: Dict[str, Any]):
    """Send notification when whole series is done."""
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        p = compute_progress(session)

        text = "\n".join([
            f"{EMO['trophy']} <b>CONGRATULATIONS!</b>",
            DIV, "",
            f"{EMO['film']} <b>{_esc(title)}</b>",
            "",
            f"{EMO['party']} <b>SERIES COMPLETE</b>",
            "",
            f"{EMO['spark']} <code>{p['total_watched']}/"
            f"{p['total_eps']}</code> episodes",
            f"{EMO['clock']} ~{int(p['total_eps'] * 22 / 60)} hours",
            "",
            DIV2, "",
            f"{EMO['star']} <b>Rate this series</b>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "⭐ 1",
                callback_data=f"pw:rate:{slug}:1"),
             InlineKeyboardButton(
                "⭐⭐ 2",
                callback_data=f"pw:rate:{slug}:2"),
             InlineKeyboardButton(
                "⭐⭐⭐ 3",
                callback_data=f"pw:rate:{slug}:3"),
             InlineKeyboardButton(
                "⭐⭐⭐⭐ 4",
                callback_data=f"pw:rate:{slug}:4"),
             InlineKeyboardButton(
                "⭐⭐⭐⭐⭐ 5",
                callback_data=f"pw:rate:{slug}:5")],
            [InlineKeyboardButton(
                f"{EMO['trophy']} MARK COMPLETE",
                callback_data=f"pw:complete:{slug}",
            )],
        ])

        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PREM] series notify: {e}")


logger.info("[PREM] Part 10 loaded — play + send + watched + next + auto-delete")

# ═══════════════════════════════════════════════════════════════════════════
# RATING MENU (full 5-button menu from poster)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:rate_menu:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_rate_menu(client, q):
    """Show rating menu when user taps RATE SERIES."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        current_rating = session.get("user_rating", 0)

        text = "\n".join([
            f"{EMO['star']} <b>RATE THIS SERIES</b>",
            DIV, "",
            f"{EMO['film']} <b>{_esc(title)}</b>",
            "",
            f"{EMO['spark']} <i>How would you rate it?</i>",
            "",
            f"<code>1 = Poor  •  5 = Excellent</code>",
        ])

        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⭐ 1",
                    callback_data=f"pw:rate:{slug}:1"),
                InlineKeyboardButton("⭐⭐ 2",
                    callback_data=f"pw:rate:{slug}:2"),
                InlineKeyboardButton("⭐⭐⭐ 3",
                    callback_data=f"pw:rate:{slug}:3"),
            ],
            [
                InlineKeyboardButton("⭐⭐⭐⭐ 4",
                    callback_data=f"pw:rate:{slug}:4"),
                InlineKeyboardButton("⭐⭐⭐⭐⭐ 5",
                    callback_data=f"pw:rate:{slug}:5"),
            ],
            [InlineKeyboardButton(
                f"{EMO['back']} Skip",
                callback_data=f"pw:poster:{slug}",
            )],
        ])

        await _pw_safe_edit(q, text, kb, is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] rate_menu: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SAVE RATING
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:rate:([a-z0-9_]+):(\d)$"), group=-420,
)
async def cb_pw_rate(client, q):
    """Save a user's rating."""
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        stars = int(q.matches[0].group(2))

        if stars < 1 or stars > 5:
            return await q.answer(
                f"{EMO['cross']} Invalid", show_alert=True,
            )

        # Save to DB
        await save_rating(uid, slug, stars)
        await mark_session_rated(uid, slug)

        await q.answer(f"{EMO['star']} {stars}/5 saved")

        # Show confirmation
        session = await get_session(uid, slug)
        title = (session or {}).get("series_title") or "?"

        text = "\n".join([
            f"{EMO['star']} <b>Thanks for rating!</b>",
            DIV, "",
            f"{EMO['film']} <b>{_esc(title)}</b>",
            f"{render_stars(stars)} <code>{stars}/5</code>",
            "",
            f"{EMO['spark']} <i>Your feedback helps us improve</i>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{EMO['back']} Back to Poster",
                callback_data=f"pw:poster:{slug}",
            )],
        ])

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            try:
                await q.message.edit_text(
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass

        logger.info(f"[PREM] rated u={uid} {slug} {stars}/5")
    except Exception as e:
        logger.exception(f"[PREM] rate: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MARK COMPLETE (archive series)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:complete:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_complete(client, q):
    """User taps MARK COMPLETE → archive the session."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        p = compute_progress(session)

        # Mark as completed in DB
        await mark_session_completed(uid, slug)
        await q.answer(f"{EMO['trophy']} Completed")

        # Show final message
        text = "\n".join([
            f"{EMO['trophy']} <b>SERIES COMPLETED!</b>",
            DIV, "",
            f"{EMO['film']} <b>{_esc(title)}</b>",
            "",
            f"{EMO['spark']} <code>{p['total_watched']}/"
            f"{p['total_eps']}</code> episodes",
            f"{EMO['clock']} ~{int(p['total_eps'] * 22 / 60)} hours",
            "",
            f"{EMO['ok']} <i>Session archived</i>",
            f"{EMO['search']} <i>Search a new series in the group "
            f"to start fresh</i>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{EMO['tv']} MY SESSIONS",
                callback_data="pw:my_sessions",
            )],
        ])

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            try:
                await q.message.edit_text(
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass

        logger.info(f"[PREM] series completed u={uid} s={slug}")
    except Exception as e:
        logger.exception(f"[PREM] complete: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MY SESSIONS (list)
# ═══════════════════════════════════════════════════════════════════════════
async def _show_session_list(client: Client, chat_id: int, uid: int):
    """Show all active sessions for a user."""
    sessions = await list_user_sessions(uid)

    if not sessions:
        await client.send_message(
            chat_id=chat_id,
            text="\n".join([
                f"{EMO['tv']} <b>{fb('YOUR SESSIONS')}</b>",
                DIV, "",
                f"{EMO['box']} <i>No active sessions</i>",
                "",
                f"{EMO['search']} <i>Search a series in the "
                f"group to start watching</i>",
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [
        f"{EMO['tv']} <b>{fb('YOUR SESSIONS')}</b> "
        f"- <code>{len(sessions)}</code>",
        DIV, "",
    ]

    rows = []
    for s in sessions[:10]:
        title = s.get("series_title") or "?"
        slug = s.get("series_slug") or ""
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])

        lines.append(f"{EMO['film']} <b>{_esc(title)}</b>")
        lines.append(
            f"   {bar}  <code>{p['total_watched']}/"
            f"{p['total_eps']}</code>  <code>({p['pct']}%)</code>"
        )
        lines.append("")

        rows.append([InlineKeyboardButton(
            f"{EMO['play']} {title[:30]} — "
            f"{p['total_watched']}/{p['total_eps']}",
            callback_data=f"pw:resume:{slug}",
        )])

    rows.append([InlineKeyboardButton(
        f"{EMO['cross']} CLOSE",
        callback_data="pw:close_session",
    )])

    await client.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command(["my", "myseries"]) & filters.private,
    group=-422,
)
async def cmd_my_sessions(client, message):
    """User command: /my → show sessions."""
    if not message.from_user:
        return
    uid = message.from_user.id
    if not await is_premium(uid):
        return await message.reply_text(
            f"{EMO['crown']} <b>Premium only.</b>",
            parse_mode=ParseMode.HTML,
        )
    try:
        await _ensure_loops(client)
        await _show_session_list(client, message.chat.id, uid)
    except Exception as e:
        logger.exception(f"[PREM] /my: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:my_sessions$"), group=-422,
)
async def cb_pw_my_sessions(client, q):
    """Callback: show sessions."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )
        await q.answer()
        await _show_session_list(client, q.message.chat.id, uid)
    except Exception as e:
        logger.debug(f"[PREM] my_sessions: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# RESUME SESSION
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:resume:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_resume(client, q):
    """Resume a session — re-send the poster."""
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or "?"
        year = session.get("year") or ""
        rating = session.get("rating") or 0

        text = build_poster_text(session, title, year, rating)
        kb = build_poster_kb(session, slug)

        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{EMO['cross']} CLOSE",
                    callback_data="pw:close_session",
                ),
            ]])

        # Send as a new message (with poster image if available)
        poster_path = session.get("poster")
        poster_url = None
        if poster_path:
            if poster_path.startswith("http"):
                poster_url = poster_path
            else:
                poster_url = (
                    f"https://image.tmdb.org/t/p/w500{poster_path}"
                )

        sent = None
        if poster_url:
            try:
                sent = await client.send_photo(
                    chat_id=q.message.chat.id,
                    photo=poster_url,
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                sent = None

        if not sent:
            sent = await client.send_message(
                chat_id=q.message.chat.id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        # Update poster_msg_id to this new message
        if sent:
            await update_poster_msg(uid, slug, sent.id)

        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] resume: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# WATCH ORDER FRANCHISES — compact DB
# ═══════════════════════════════════════════════════════════════════════════
FRANCHISES: Dict[str, Dict[str, Any]] = {
    "breaking_bad_universe": {
        "name": "Breaking Bad Universe",
        "items": [
            {"title": "Breaking Bad", "year": "2008", "type": "series"},
            {"title": "El Camino", "year": "2019", "type": "movie"},
            {"title": "Better Call Saul", "year": "2015",
             "type": "series"},
        ],
    },
    "mcu": {
        "name": "Marvel Cinematic Universe",
        "items": [
            {"title": "Iron Man", "year": "2008", "type": "movie"},
            {"title": "The Incredible Hulk", "year": "2008",
             "type": "movie"},
            {"title": "Iron Man 2", "year": "2010", "type": "movie"},
            {"title": "Thor", "year": "2011", "type": "movie"},
            {"title": "Captain America: The First Avenger",
             "year": "2011", "type": "movie"},
            {"title": "The Avengers", "year": "2012", "type": "movie"},
            {"title": "Iron Man 3", "year": "2013", "type": "movie"},
            {"title": "Thor: The Dark World", "year": "2013",
             "type": "movie"},
            {"title": "Captain America: The Winter Soldier",
             "year": "2014", "type": "movie"},
            {"title": "Guardians of the Galaxy", "year": "2014",
             "type": "movie"},
            {"title": "Avengers: Age of Ultron", "year": "2015",
             "type": "movie"},
            {"title": "Ant-Man", "year": "2015", "type": "movie"},
            {"title": "Captain America: Civil War", "year": "2016",
             "type": "movie"},
            {"title": "Doctor Strange", "year": "2016",
             "type": "movie"},
            {"title": "Spider-Man: Homecoming", "year": "2017",
             "type": "movie"},
            {"title": "Thor: Ragnarok", "year": "2017",
             "type": "movie"},
            {"title": "Black Panther", "year": "2018",
             "type": "movie"},
            {"title": "Avengers: Infinity War", "year": "2018",
             "type": "movie"},
            {"title": "Captain Marvel", "year": "2019",
             "type": "movie"},
            {"title": "Avengers: Endgame", "year": "2019",
             "type": "movie"},
            {"title": "Spider-Man: Far From Home", "year": "2019",
             "type": "movie"},
        ],
    },
    "star_wars": {
        "name": "Star Wars Skywalker Saga",
        "items": [
            {"title": "Star Wars: Episode I - The Phantom Menace",
             "year": "1999", "type": "movie"},
            {"title": "Star Wars: Episode II - Attack of the Clones",
             "year": "2002", "type": "movie"},
            {"title": "Star Wars: Episode III - Revenge of the Sith",
             "year": "2005", "type": "movie"},
            {"title": "Rogue One: A Star Wars Story",
             "year": "2016", "type": "movie"},
            {"title": "Star Wars: Episode IV - A New Hope",
             "year": "1977", "type": "movie"},
            {"title": "Star Wars: Episode V - The Empire Strikes Back",
             "year": "1980", "type": "movie"},
            {"title": "Star Wars: Episode VI - Return of the Jedi",
             "year": "1983", "type": "movie"},
            {"title": "Star Wars: Episode VII - The Force Awakens",
             "year": "2015", "type": "movie"},
            {"title": "Star Wars: Episode VIII - The Last Jedi",
             "year": "2017", "type": "movie"},
            {"title": "Star Wars: Episode IX - The Rise of Skywalker",
             "year": "2019", "type": "movie"},
        ],
    },
    "john_wick": {
        "name": "John Wick",
        "items": [
            {"title": "John Wick", "year": "2014", "type": "movie"},
            {"title": "John Wick: Chapter 2", "year": "2017",
             "type": "movie"},
            {"title": "John Wick: Chapter 3 - Parabellum",
             "year": "2019", "type": "movie"},
            {"title": "John Wick: Chapter 4", "year": "2023",
             "type": "movie"},
        ],
    },
    "the_boys_universe": {
        "name": "The Boys Universe",
        "items": [
            {"title": "The Boys", "year": "2019", "type": "series"},
            {"title": "Gen V", "year": "2023", "type": "series"},
        ],
    },
    "lotr": {
        "name": "Middle-earth",
        "items": [
            {"title": "The Hobbit: An Unexpected Journey",
             "year": "2012", "type": "movie"},
            {"title": "The Hobbit: The Desolation of Smaug",
             "year": "2013", "type": "movie"},
            {"title": "The Hobbit: The Battle of the Five Armies",
             "year": "2014", "type": "movie"},
            {"title": "The Lord of the Rings: The Fellowship of "
                      "the Ring", "year": "2001", "type": "movie"},
            {"title": "The Lord of the Rings: The Two Towers",
             "year": "2002", "type": "movie"},
            {"title": "The Lord of the Rings: The Return of the "
                      "King", "year": "2003", "type": "movie"},
        ],
    },
    "harry_potter": {
        "name": "Wizarding World",
        "items": [
            {"title": "Harry Potter and the Sorcerer's Stone",
             "year": "2001", "type": "movie"},
            {"title": "Harry Potter and the Chamber of Secrets",
             "year": "2002", "type": "movie"},
            {"title": "Harry Potter and the Prisoner of Azkaban",
             "year": "2004", "type": "movie"},
            {"title": "Harry Potter and the Goblet of Fire",
             "year": "2005", "type": "movie"},
            {"title": "Harry Potter and the Order of the Phoenix",
             "year": "2007", "type": "movie"},
            {"title": "Harry Potter and the Half-Blood Prince",
             "year": "2009", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 1",
             "year": "2010", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 2",
             "year": "2011", "type": "movie"},
        ],
    },
}


def _find_franchise_by_title(title: str) -> Optional[Dict[str, Any]]:
    """Find matching franchise for a title."""
    if not title:
        return None

    t_lower = title.lower().strip()

    # Exact match
    for fkey, fdata in FRANCHISES.items():
        for item in fdata.get("items") or []:
            item_title = (item.get("title") or "").lower().strip()
            if item_title == t_lower:
                return {"key": fkey, **fdata}

    # Partial match (for long titles like "Breaking Bad ORG ...")
    for fkey, fdata in FRANCHISES.items():
        for item in fdata.get("items") or []:
            item_title = (item.get("title") or "").lower().strip()
            if len(item_title) > 6 and item_title in t_lower:
                return {"key": fkey, **fdata}
            if len(t_lower) > 6 and t_lower in item_title:
                return {"key": fkey, **fdata}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# WATCH ORDER VIEW
# ═══════════════════════════════════════════════════════════════════════════
async def _build_watch_order_view(
    uid: int,
    franchise: Dict[str, Any],
    slug: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    items = franchise.get("items") or []
    fname = franchise.get("name") or "?"

    lines = [
        f"{EMO['book']} <b>{fb('WATCH ORDER')}</b>",
        f"{EMO['crown']} <b>{_esc(fname)}</b>",
        DIV, "",
        f"{EMO['spark']} <i>Recommended viewing order:</i>",
        "",
    ]

    rows = []
    for i, item in enumerate(items, 1):
        title = item.get("title") or "?"
        year = item.get("year") or ""
        itype = item.get("type") or "series"

        item_slug = _slug(title)
        session = await get_session(uid, item_slug)

        if session:
            p = compute_progress(session)
            if p["total_eps"] > 0 and \
                    p["total_watched"] >= p["total_eps"]:
                icon = EMO["ok"]
                progress_str = "COMPLETE"
            else:
                icon = EMO["play"]
                progress_str = (
                    f"{p['total_watched']}/{p['total_eps']}"
                )
        else:
            icon = EMO["box"]
            progress_str = "Not started"

        type_icon = EMO["film"] if itype == "movie" else EMO["tv"]

        lines.append(
            f"<b>{i}.</b> {icon} {type_icon} "
            f"<b>{_esc(title)}</b> <code>({year})</code>"
        )
        lines.append(f"   <i>{progress_str}</i>")

        rows.append([InlineKeyboardButton(
            f"{icon} {i}. {title[:32]}",
            callback_data=f"pw:wo_open:{slug}:{i - 1}",
        )])

    rows.append([InlineKeyboardButton(
        f"{EMO['back']} BACK",
        callback_data=f"pw:poster:{slug}",
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# WATCH ORDER CALLBACK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:wo:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_watch_order(client, q):
    """Show watch order for a franchise."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or ""
        franchise = _find_franchise_by_title(title)

        if not franchise:
            return await q.answer(
                f"{EMO['warn']} No watch order for this series",
                show_alert=True,
            )

        text, kb = await _build_watch_order_view(uid, franchise, slug)

        await _pw_safe_edit(q, text, kb, is_caption=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] wo: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# WATCH ORDER OPEN ITEM
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:wo_open:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_wo_open(client, q):
    """Open a specific item from watch order."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer(
                f"{EMO['crown']} Premium only", show_alert=True,
            )

        slug = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer(
                f"{EMO['cross']} Not found", show_alert=True,
            )

        title = session.get("series_title") or ""
        franchise = _find_franchise_by_title(title)
        if not franchise:
            return await q.answer(
                f"{EMO['cross']} Error", show_alert=True,
            )

        items = franchise.get("items") or []
        if idx < 0 or idx >= len(items):
            return await q.answer(
                f"{EMO['cross']} Invalid", show_alert=True,
            )

        item = items[idx]
        item_title = item.get("title") or ""
        item_year = item.get("year") or ""

        await q.answer(f"{EMO['rocket']} {item_title}")

        # Search for this title
        tmdb_id = None
        poster = None
        tmdb_seasons: List[Dict[str, Any]] = []
        hits: List[Dict[str, Any]] = []

        try:
            from plugins.series_group import (
                _engine_search, _tmdb_search_series,
                _tmdb_series_details, _tmdb_seasons,
            )
            hits = await _engine_search(item_title) or []
            suggestions = await _tmdb_search_series(item_title) or []
            if suggestions:
                tmdb_id = suggestions[0].get("tmdb_id")
                poster = suggestions[0].get("poster")
                if tmdb_id:
                    details = await _tmdb_series_details(tmdb_id)
                    if details:
                        tmdb_seasons = _tmdb_seasons(details)
        except Exception as e:
            logger.debug(f"[PREM] wo_open tmdb: {e}")

        if not hits:
            return await q.answer(
                f"{EMO['cross']} Not in library", show_alert=True,
            )

        series_data = {
            "title": item_title,
            "tmdb_id": tmdb_id,
            "poster": poster,
            "year": item_year,
            "rating": 0,
            "tmdb_seasons": tmdb_seasons,
            "hits": hits,
            "search_query": item_title,
        }

        await _prepare_pm_session(client, uid, series_data)
        await q.answer(
            f"{EMO['ok']} Sent to PM!", show_alert=True,
        )
    except Exception as e:
        logger.exception(f"[PREM] wo_open: {e}")
        try:
            await q.answer(f"{EMO['cross']} Error", show_alert=True)
        except Exception:
            pass


logger.info("[PREM] Part 11 loaded — rating + complete + watch order + sessions")

# ═══════════════════════════════════════════════════════════════════════════
# FINAL BOOT HOOK — starts loops on first private message
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private, group=-419)
async def _pw_final_boot(client, message):
    """Fallback boot — makes sure reminder + cleanup loops are running."""
    try:
        await _ensure_loops(client)
    except Exception as e:
        logger.debug(f"[PREM] final boot: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC EXPORTS — for use by other plugins (e.g. series_group.py)
# ═══════════════════════════════════════════════════════════════════════════
__all__ = [
    # User CRUD
    "add_premium_user",
    "get_premium_user",
    "is_premium",
    "is_premium_or_grace",
    "remove_premium_user",
    "list_premium_users",
    "count_premium_users",
    "find_premium_by_username",
    # Sessions
    "create_session",
    "get_session",
    "list_user_sessions",
    "list_all_sessions",
    "mark_watched",
    "mark_sent",
    "set_current_position",
    "set_language",
    "mark_session_completed",
    "mark_session_rated",
    "delete_session",
    "count_sessions",
    "update_poster_msg",
    "update_current_file_msg",
    # Ratings
    "save_rating",
    # Settings
    "get_setting",
    "set_setting",
    "get_contact_admin",
    # Progress helpers
    "compute_progress",
    "render_progress_bar",
    "find_next_episode",
    "is_series_complete",
    "is_season_complete",
    # Main hook — called from series_group.py
    "handle_premium_group_search",
    # Reminders
    "mark_reminder_sent",
    "was_reminder_sent",
]


# ═══════════════════════════════════════════════════════════════════════════
# VERSION + BANNER
# ═══════════════════════════════════════════════════════════════════════════
__version__ = "5.0.0"

logger.info("=" * 68)
logger.info(f"  {EMO['crown']}  PREMIUM WATCH COMPANION  v{__version__}")
logger.info("=" * 68)
logger.info(f"  {EMO['ok']}  Part 1  — config, fonts, helpers")
logger.info(f"  {EMO['ok']}  Part 2  — DB layer + premium CRUD + settings")
logger.info(f"  {EMO['ok']}  Part 3  — session CRUD + progress engine")
logger.info(f"  {EMO['ok']}  Part 4  — reminders + cleanup + boot + helpers")
logger.info(f"  {EMO['ok']}  Part 5  — admin keyboards + view builders")
logger.info(f"  {EMO['ok']}  Part 6  — admin command + callbacks + input")
logger.info(f"  {EMO['ok']}  Part 7  — extend + remove + notes + stats")
logger.info(f"  {EMO['ok']}  Part 8  — group→PM redirect + poster")
logger.info(f"  {EMO['ok']}  Part 9  — language + seasons + episodes grid")
logger.info(f"  {EMO['ok']}  Part 10 — play + send + watched + next + autodel")
logger.info(f"  {EMO['ok']}  Part 11 — rating + complete + watch order")
logger.info(f"  {EMO['ok']}  Part 12 — boot hook + exports + banner")
logger.info("-" * 68)
logger.info(f"  {EMO['gear']}  Admin panel : /seriesgroupsettings")
logger.info(f"  {EMO['tv']}  User panel  : /my  /myseries")
logger.info(f"  {EMO['rocket']}  Auto group→PM redirect for premium users")
logger.info(f"  {EMO['bell']}  Expiry reminders: 10d / 5d / 1d / expired")
logger.info(f"  {EMO['book']}  Watch Order for franchises")
logger.info(f"  {EMO['clock']}  Cleanup: 30d grace  •  180d inactive")
logger.info(f"  {EMO['fire']}  File auto-delete: 30s after MARK WATCHED")
logger.info("=" * 68)


# ═══════════════════════════════════════════════════════════════════════════
# SELF-CHECK (non-fatal)
# ═══════════════════════════════════════════════════════════════════════════
async def _pw_self_check():
    """Non-fatal DB probe — warns if collections are missing."""
    try:
        p = _premium_coll()
        s = _sessions_coll()
        st = _settings_coll()
        if p is None:
            logger.warning(
                "[PREM] premium_users collection unavailable — "
                "check database manager"
            )
        if s is None:
            logger.warning(
                "[PREM] watch_sessions collection unavailable"
            )
        if st is None:
            logger.warning(
                "[PREM] premium_settings collection unavailable"
            )
    except Exception as e:
        logger.debug(f"[PREM] self-check: {e}")


try:
    _loop = asyncio.get_event_loop()
    if _loop.is_running():
        _loop.create_task(_pw_self_check())
except Exception:
    pass


logger.info(f"  {EMO['spark']}  [PREM] Module ready — v{__version__}")
logger.info("=" * 68)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION GUIDE — HOW TO HOOK INTO series_group.py
# ═══════════════════════════════════════════════════════════════════════════
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  INTEGRATION WITH series_group.py                                        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  You only need 2 SMALL EDITS in plugins/series_group.py:                 ║
║                                                                          ║
║  ── EDIT 1 — at the TOP of series_group.py ──                            ║
║                                                                          ║
║    try:                                                                  ║
║        from plugins.premium_watch import handle_premium_group_search     ║
║    except ImportError:                                                   ║
║        handle_premium_group_search = None                                ║
║                                                                          ║
║  ── EDIT 2 — inside the group search handler ──                          ║
║                                                                          ║
║    After you have db_match (with .hits) and tmdb_pre results,            ║
║    add this block BEFORE the normal flow continues:                      ║
║                                                                          ║
║    if handle_premium_group_search is not None:                           ║
║        try:                                                              ║
║            from plugins.premium_watch import is_premium                  ║
║            _is_prem = await is_premium(message.from_user.id)             ║
║            if _is_prem and db_match and db_match.get("hits"):            ║
║                handled = await handle_premium_group_search(              ║
║                    client, message, txt, db_match, tmdb_pre or []        ║
║                )                                                         ║
║                if handled:                                               ║
║                    return                                                ║
║        except Exception as e:                                            ║
║            logger.debug(f"[SGROUP] premium hook: {e}")                   ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

