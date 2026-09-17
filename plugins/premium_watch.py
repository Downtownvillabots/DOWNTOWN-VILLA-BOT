# plugins/premium_watch.py
"""
💎 PREMIUM WATCH COMPANION v1
Part A — DB schema, helpers, reminder engine, cleanup
"""
import asyncio
import logging
import os
import re
import time
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

REMINDER_DAYS = [10, 5, 1]
GRACE_PERIOD_DAYS = 30
INACTIVITY_DAYS = 180
REMINDER_HOUR = 10
REPORT_HOUR = 11

PLAN_OPTIONS = [
    ("1 MONTH",  1),
    ("3 MONTHS", 3),
    ("5 MONTHS", 5),
    ("6 MONTHS", 6),
    ("12 MONTHS", 12),
]

DIV = "━" * 26
DIV2 = "─" * 26


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
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

def _date_ist(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
    except Exception:
        return "?"

def _slug(s: str) -> str:
    if not s: return ""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


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


def _premium_coll():
    d = _get_db()
    return d["premium_users"] if d is not None else None


def _sessions_coll():
    d = _get_db()
    return d["watch_sessions"] if d is not None else None


def _settings_coll():
    d = _get_db()
    return d["premium_settings"] if d is not None else None


# ═══════════════════════════════════════════════════════════════════════════
# PREMIUM USER CRUD
# ═══════════════════════════════════════════════════════════════════════════
async def add_premium_user(user_id: int, username: str, months: int,
                            added_by: int, notes: str = "") -> bool:
    c = _premium_coll()
    if c is None: return False
    try:
        now = time.time()
        expires_at = now + (months * 30 * 86400)
        await c.update_one(
            {"user_id": int(user_id)},
            {"$set": {
                "user_id": int(user_id),
                "username": username or "",
                "plan_months": int(months),
                "added_at": now,
                "added_by": int(added_by),
                "expires_at": expires_at,
                "notes": notes or "",
                "status": "active",
                "reminders_sent": [],
            }},
            upsert=True,
        )
        logger.info(f"[PREM] added user={user_id} months={months}")
        return True
    except Exception as e:
        logger.exception(f"[PREM] add failed: {e}")
        return False


async def get_premium_user(user_id: int) -> Optional[Dict[str, Any]]:
    c = _premium_coll()
    if c is None: return None
    try:
        return await c.find_one({"user_id": int(user_id)})
    except Exception: return None


async def is_premium(user_id: int) -> bool:
    doc = await get_premium_user(user_id)
    if not doc: return False
    if doc.get("status") != "active": return False
    return doc.get("expires_at", 0) > time.time()


async def is_premium_or_grace(user_id: int) -> bool:
    doc = await get_premium_user(user_id)
    if not doc: return False
    if doc.get("status") == "active":
        return True
    expires_at = doc.get("expires_at", 0)
    if not expires_at: return False
    grace_end = expires_at + (GRACE_PERIOD_DAYS * 86400)
    return grace_end > time.time()


async def remove_premium_user(user_id: int) -> bool:
    c = _premium_coll()
    if c is None: return False
    try:
        r = await c.delete_one({"user_id": int(user_id)})
        return r.deleted_count > 0
    except Exception: return False


async def list_premium_users(limit: int = 500) -> List[Dict[str, Any]]:
    c = _premium_coll()
    if c is None: return []
    try:
        return await c.find({}).sort("expires_at", 1).to_list(limit)
    except Exception: return []


async def count_premium_users() -> Dict[str, int]:
    c = _premium_coll()
    if c is None: return {"active": 0, "expiring_10d": 0,
                          "expiring_5d": 0, "expiring_1d": 0, "expired": 0}
    try:
        now = time.time()
        d10 = now + (10 * 86400)
        d5 = now + (5 * 86400)
        d1 = now + (1 * 86400)
        active = await c.count_documents({"status": "active",
                                           "expires_at": {"$gt": now}})
        exp10 = await c.count_documents({"status": "active",
                                          "expires_at": {"$gt": now, "$lte": d10}})
        exp5 = await c.count_documents({"status": "active",
                                         "expires_at": {"$gt": now, "$lte": d5}})
        exp1 = await c.count_documents({"status": "active",
                                         "expires_at": {"$gt": now, "$lte": d1}})
        expired = await c.count_documents({"expires_at": {"$lte": now}})
        return {"active": active, "expiring_10d": exp10,
                "expiring_5d": exp5, "expiring_1d": exp1, "expired": expired}
    except Exception as e:
        logger.warning(f"[PREM] count: {e}")
        return {"active": 0, "expiring_10d": 0, "expiring_5d": 0,
                "expiring_1d": 0, "expired": 0}


async def mark_reminder_sent(user_id: int, reminder: str) -> bool:
    c = _premium_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$addToSet": {"reminders_sent": reminder}}
        )
        return True
    except Exception: return False


async def was_reminder_sent(user_id: int, reminder: str) -> bool:
    doc = await get_premium_user(user_id)
    if not doc: return False
    return reminder in (doc.get("reminders_sent") or [])


async def find_premium_by_username(username: str) -> Optional[Dict[str, Any]]:
    c = _premium_coll()
    if c is None: return None
    try:
        uname = username.lstrip("@").lower()
        return await c.find_one({"username": {"$regex": f"^{uname}$",
                                                "$options": "i"}})
    except Exception: return None


# ═══════════════════════════════════════════════════════════════════════════
# WATCH SESSION CRUD
# ═══════════════════════════════════════════════════════════════════════════
async def create_session(user_id: int, series_slug: str,
                          series_title: str, poster: Optional[str],
                          tmdb_id: Optional[int],
                          tmdb_seasons: List[Dict[str, Any]],
                          language: str = "") -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        now = time.time()
        seasons_doc = {}
        for s in (tmdb_seasons or []):
            sn = s.get("season")
            if sn is None: continue
            seasons_doc[str(sn)] = {
                "total_eps": s.get("episodes", 0),
                "watched": [],
                "current_ep": 1,
            }
        if not seasons_doc:
            seasons_doc["1"] = {"total_eps": 0, "watched": [], "current_ep": 1}

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
                "started_at": now,
                "last_activity_at": now,
                "status": "watching",
                "completed_at": None,
                "poster_chat_id": int(user_id),
                "poster_msg_id": None,
                "current_file_msg_id": None,
                "current_season": 1,
                "current_episode": 1,
            }},
            upsert=True,
        )
        logger.info(f"[PREM] session created u={user_id} s={series_slug}")
        return True
    except Exception as e:
        logger.exception(f"[PREM] create session: {e}")
        return False


async def get_session(user_id: int,
                       series_slug: str) -> Optional[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None: return None
    try:
        return await c.find_one({"user_id": int(user_id),
                                  "series_slug": series_slug})
    except Exception: return None


async def list_user_sessions(user_id: int) -> List[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None: return []
    try:
        return await c.find({"user_id": int(user_id),
                              "status": "watching"}
                             ).sort("last_activity_at", -1).to_list(50)
    except Exception: return []


async def mark_watched(user_id: int, series_slug: str,
                        season: int, episode: int) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        key = f"seasons.{season}.watched"
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$addToSet": {key: int(episode)},
             "$set": {"last_activity_at": time.time()}}
        )
        sess = await get_session(user_id, series_slug)
        if sess:
            s_data = (sess.get("seasons") or {}).get(str(season)) or {}
            total = s_data.get("total_eps", 0)
            next_ep = int(episode) + 1
            if total and next_ep > total:
                next_ep = total
            await c.update_one(
                {"user_id": int(user_id), "series_slug": series_slug},
                {"$set": {f"seasons.{season}.current_ep": next_ep}}
            )
        return True
    except Exception as e:
        logger.exception(f"[PREM] mark watched: {e}")
        return False


async def update_poster_msg(user_id: int, series_slug: str,
                              msg_id: int) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"poster_msg_id": int(msg_id)}}
        )
        return True
    except Exception: return False


async def update_current_file_msg(user_id: int, series_slug: str,
                                    msg_id: int) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"current_file_msg_id": int(msg_id)}}
        )
        return True
    except Exception: return False


async def set_current_position(user_id: int, series_slug: str,
                                 season: int, episode: int) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"current_season": int(season),
                      "current_episode": int(episode),
                      "last_activity_at": time.time()}}
        )
        return True
    except Exception: return False


async def set_language(user_id: int, series_slug: str,
                        language: str) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"language": language,
                      "last_activity_at": time.time()}}
        )
        return True
    except Exception: return False


async def mark_session_completed(user_id: int,
                                   series_slug: str) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": series_slug},
            {"$set": {"status": "completed",
                      "completed_at": time.time()}}
        )
        return True
    except Exception: return False


async def delete_session(user_id: int, series_slug: str) -> bool:
    c = _sessions_coll()
    if c is None: return False
    try:
        r = await c.delete_one({"user_id": int(user_id),
                                 "series_slug": series_slug})
        return r.deleted_count > 0
    except Exception: return False


async def count_sessions() -> int:
    c = _sessions_coll()
    if c is None: return 0
    try:
        return await c.count_documents({"status": "watching"})
    except Exception: return 0


# ═══════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════
async def get_setting(key: str, default=None):
    c = _settings_coll()
    if c is None: return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception: return default


async def set_setting(key: str, value) -> bool:
    c = _settings_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {key: value, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception: return False


async def get_contact_admin() -> str:
    return await get_setting("contact_admin", "") or ""


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def compute_progress(session: Dict[str, Any]) -> Dict[str, Any]:
    seasons_raw = session.get("seasons") or {}
    seasons_out = {}
    total_watched = 0
    total_eps = 0

    for sn_str, s_data in seasons_raw.items():
        try: sn = int(sn_str)
        except Exception: continue
        watched = set(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)
        cnt = len(watched)
        seasons_out[sn] = {
            "watched": sorted(watched),
            "count": cnt,
            "total": total,
        }
        total_watched += cnt
        total_eps += total

    overall_pct = (total_watched / total_eps * 100) if total_eps else 0
    return {
        "seasons": seasons_out,
        "total_watched": total_watched,
        "total_eps": total_eps,
        "pct": round(overall_pct, 1),
    }


def render_progress_bar(pct: float, width: int = 12) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def find_next_episode(session: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    for sn in ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        total = s_data.get("total_eps", 0)
        if total == 0: continue
        watched = set(s_data.get("watched") or [])
        for ep in range(1, total + 1):
            if ep not in watched:
                return (sn, ep)
    return None


def is_series_complete(session: Dict[str, Any]) -> bool:
    p = compute_progress(session)
    if p["total_eps"] == 0: return False
    return p["total_watched"] >= p["total_eps"]


# ═══════════════════════════════════════════════════════════════════════════
# REMINDER LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _reminder_loop(client: Client):
    await asyncio.sleep(60)
    last_run_date = None

    while True:
        try:
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")

            if (now.hour == REMINDER_HOUR and now.minute < 30
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
    users = await list_premium_users(500)
    if not users: return

    now = time.time()

    for u in users:
        try:
            uid = u.get("user_id")
            expires = u.get("expires_at", 0)
            if not uid or not expires: continue

            if expires <= now:
                days_since = (now - expires) / 86400
                if days_since < 1 and not await was_reminder_sent(uid, "expired"):
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
            logger.debug(f"[PREM] reminder to {u.get('user_id')}: {e}")


async def _send_reminder(client: Client, uid: int, user: Dict[str, Any],
                          kind: str):
    contact = await get_contact_admin() or "@admin"
    expires = user.get("expires_at", 0)
    exp_date = _date_ist(expires)
    username = user.get("username") or "user"

    sessions = await list_user_sessions(uid)
    series_lines = []
    for s in sessions[:5]:
        title = s.get("series_title") or "?"
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        series_lines.append(
            f"• {_esc(title)}\n"
            f"  {bar} {p['total_watched']}/{p['total_eps']}"
        )
    series_block = "\n".join(series_lines) if series_lines else "⚪ ɴᴏ ᴀᴄᴛɪᴠᴇ ꜱᴇʀɪᴇꜱ"

    if kind == "10d":
        header = f"💎 <b>{fb('PREMIUM EXPIRING SOON')}</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium expires in:\n"
                f"📅 <b>{exp_date}</b> (10 days)")
        footer = f"To renew, contact: <b>{_esc(contact)}</b>"
    elif kind == "5d":
        header = f"⏰ <b>{fb('PREMIUM EXPIRING IN 5 DAYS')}</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your plan ends: <b>{exp_date}</b>\n\n"
                f"If you don't renew, you'll lose:\n"
                f"  ✗ Watch progress tracking\n"
                f"  ✗ Watch Order Assistant\n"
                f"  ✗ New episode deliveries\n\n"
                f"💾 <i>Already delivered files are yours to keep forever.</i>")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."
    elif kind == "1d":
        header = f"⚠️ <b>{fb('LAST DAY OF PREMIUM')}</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium expires <b>tomorrow</b> ({exp_date})\n\n"
                f"📊 Progress will be saved for 30 days after expiry.\n"
                f"After 30 days, tracking is removed — "
                f"files stay with you.")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."
    else:
        header = f"❌ <b>{fb('PREMIUM EXPIRED')}</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium membership ended today.\n\n"
                f"✅ Files you received: yours to keep forever\n"
                f"⏸️ Progress tracking: paused\n"
                f"⏸️ Watch companion: disabled\n\n"
                f"💾 Progress will be DELETED in 30 days "
                f"if not renewed.")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."

    text = "\n".join([
        header, DIV, "",
        body, "",
        DIV2,
        f"📊 <b>{sc('your active series')}</b>",
        series_block,
        "", DIV2,
        footer,
    ])

    kb_rows = []
    if contact and contact.startswith("@"):
        kb_rows.append([InlineKeyboardButton(
            "📩 MESSAGE ADMIN",
            url=f"https://t.me/{contact.lstrip('@')}"
        )])
    if kind != "expired":
        kb_rows.append([InlineKeyboardButton(
            "▶️ CONTINUE WATCHING", callback_data="pw:my_sessions"
        )])
    kb_rows.append([InlineKeyboardButton(
        "❌ DISMISS", callback_data="pw:dismiss_reminder"
    )])

    try:
        await client.send_message(
            chat_id=int(uid),
            text=text,
            reply_markup=InlineKeyboardMarkup(kb_rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[PREM] reminder {kind} → {uid}")
    except UserIsBlocked:
        logger.debug(f"[PREM] user {uid} blocked bot")
    except Exception as e:
        logger.warning(f"[PREM] send reminder: {e}")


async def _send_admin_report(client: Client):
    if not ADMINS: return
    stats = await count_premium_users()
    sessions = await count_sessions()

    users = await list_premium_users(500)
    exp_today = []
    exp_1d = []
    now = time.time()
    for u in users:
        if u.get("status") != "active": continue
        expires = u.get("expires_at", 0)
        if expires <= now: continue
        days = (expires - now) / 86400
        uname = u.get("username") or str(u.get("user_id"))
        if 0 < days <= 1:
            exp_1d.append(uname)

    lines = [
        f"💎 <b>{fb('PREMIUM DAILY REPORT')}</b>",
        DIV, "",
        f"📅 <code>{_now_ist()}</code>",
        "",
        f"👥 {sc('active')} · <code>{stats['active']}</code>",
        f"⏳ {sc('expiring 10d')} · <code>{stats['expiring_10d']}</code>",
        f"⏳ {sc('expiring 5d')} · <code>{stats['expiring_5d']}</code>",
        f"⏳ {sc('expiring 1d')} · <code>{stats['expiring_1d']}</code>",
        f"❌ {sc('expired')} · <code>{stats['expired']}</code>",
        "",
        f"🎬 {sc('active sessions')} · <code>{sessions}</code>",
    ]
    if exp_1d:
        lines += ["", DIV2, f"⚠️ {sc('expiring tomorrow')}:"]
        for u in exp_1d[:10]:
            lines.append(f"  • {_esc(u)}")

    text = "\n".join(lines)
    for a in ADMINS:
        try:
            aid = int(a) if str(a).lstrip("-").isdigit() else None
            if not aid: continue
            await client.send_message(
                aid, text, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP LOOP
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
        await asyncio.sleep(6 * 3600)  # every 6 hours


async def _cleanup_inactive_sessions():
    """Delete sessions inactive > 180 days (if user is still active premium)."""
    c = _sessions_coll()
    if c is None: return
    try:
        cutoff = time.time() - (INACTIVITY_DAYS * 86400)
        r = await c.delete_many({
            "status": "watching",
            "last_activity_at": {"$lt": cutoff},
        })
        if r.deleted_count > 0:
            logger.info(f"[PREM] cleanup: {r.deleted_count} inactive sessions")
    except Exception as e:
        logger.warning(f"[PREM] cleanup inactive: {e}")


async def _cleanup_expired_sessions():
    """Delete sessions of users whose grace period is over."""
    c = _sessions_coll()
    p = _premium_coll()
    if c is None or p is None: return
    try:
        now = time.time()
        # Find expired premium users past grace
        cursor = p.find({
            "expires_at": {"$lt": now - (GRACE_PERIOD_DAYS * 86400)}
        })
        expired_uids = []
        async for doc in cursor:
            uid = doc.get("user_id")
            if uid: expired_uids.append(uid)

        if not expired_uids: return

        r = await c.delete_many({"user_id": {"$in": expired_uids}})
        if r.deleted_count > 0:
            logger.info(f"[PREM] cleanup: {r.deleted_count} expired sessions "
                        f"for {len(expired_uids)} users")
    except Exception as e:
        logger.warning(f"[PREM] cleanup expired: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# BOOT — starts loops on first admin activity
# ═══════════════════════════════════════════════════════════════════════════
_BOOTED = False


@Client.on_message(filters.private, group=-427)
async def _pw_boot(client, message):
    global _BOOTED
    if _BOOTED:
        return
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    _BOOTED = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reminder_loop(client))
        loop.create_task(_cleanup_loop(client))
        logger.info("[PREM] reminder + cleanup loops started")
    except Exception as e:
        logger.warning(f"[PREM] boot: {e}")




logger.info("💎 PREMIUM WATCH — Part A loaded (DB + reminders + cleanup)")

# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════ PART B — ADMIN PANEL + PREMIUM MGMT ═══════════════════
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS (for admin input flows)
# ═══════════════════════════════════════════════════════════════════════════
_ADMIN_SESSIONS: Dict[int, Dict[str, Any]] = {}
_SESSION_TTL = 900


def _new_admin_session(uid: int, action: str, **data):
    _ADMIN_SESSIONS[uid] = {
        "action": action,
        "expires": time.time() + _SESSION_TTL,
        **data,
    }


def _get_admin_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _ADMIN_SESSIONS.get(uid)
    if not s: return None
    if time.time() > s.get("expires", 0):
        _ADMIN_SESSIONS.pop(uid, None)
        return None
    return s


def _clear_admin_session(uid: int):
    _ADMIN_SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# RENDER HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def _pw_safe_edit(q_or_msg, text: str, kb=None) -> bool:
    """Safely edit a message or callback query's message."""
    try:
        m = getattr(q_or_msg, "message", q_or_msg)
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            m = getattr(q_or_msg, "message", q_or_msg)
            await m.edit_text(text, reply_markup=kb,
                               parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
            return True
        except Exception:
            return False
    except Exception as e:
        logger.debug(f"[PREM] edit: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# PANEL KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_pw_main(active: int, expiring: int, sessions: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 PREMIUM MEMBERS",
                               callback_data="pw:members")],
        [InlineKeyboardButton(f"➕ ADD PREMIUM USER",
                               callback_data="pw:add"),
         InlineKeyboardButton(f"🔍 FIND USER",
                               callback_data="pw:find")],
        [InlineKeyboardButton("⏰ EXPIRING SOON",
                               callback_data="pw:expiring"),
         InlineKeyboardButton("❌ EXPIRED",
                               callback_data="pw:expired")],
        [InlineKeyboardButton("👤 SET CONTACT ADMIN",
                               callback_data="pw:contact"),
         InlineKeyboardButton("🔄 REFRESH",
                               callback_data="pw:main")],
        [InlineKeyboardButton("📊 STATS",
                               callback_data="pw:stats"),
         InlineKeyboardButton("❌ CLOSE",
                               callback_data="pw:close")],
    ])


def kb_pw_back(target: str = "pw:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="pw:close")]])


def kb_pw_plan_picker(user_id: int, username: str):
    """Plan options for the premium user being added."""
    rows = []
    row = []
    for label, months in PLAN_OPTIONS:
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"pw:plan:{user_id}:{months}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data="pw:add")])
    return InlineKeyboardMarkup(rows)


def kb_pw_member_actions(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 EXTEND",
                               callback_data=f"pw:extend:{user_id}"),
         InlineKeyboardButton("🗑️ REMOVE",
                               callback_data=f"pw:remove:{user_id}")],
        [InlineKeyboardButton("✏️ EDIT NOTES",
                               callback_data=f"pw:notes:{user_id}")],
        [InlineKeyboardButton("◀️ BACK TO LIST",
                               callback_data="pw:members"),
         InlineKeyboardButton("❌ CLOSE",
                               callback_data="pw:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_pw_main() -> Tuple[str, InlineKeyboardMarkup]:
    stats = await count_premium_users()
    sessions = await count_sessions()
    contact = await get_contact_admin() or "—"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"💎 <b>{fb('PREMIUM MANAGEMENT')}</b>",
        DIV, "",
        f"👥 {sc('active')} · <code>{stats['active']}</code>",
        f"⏳ {sc('expiring 10d')} · <code>{stats['expiring_10d']}</code>",
        f"⏳ {sc('expiring 5d')} · <code>{stats['expiring_5d']}</code>",
        f"⏳ {sc('expiring 1d')} · <code>{stats['expiring_1d']}</code>",
        f"❌ {sc('expired')} · <code>{stats['expired']}</code>",
        "",
        f"🎬 {sc('active sessions')} · <code>{sessions}</code>",
        "", DIV2, "",
        f"👤 {sc('contact admin')} · <code>{_esc(contact)}</code>",
        "",
        f"🕒 <code>{_now_ist()}</code>",
    ])

    return text, kb_pw_main(stats["active"],
                             stats["expiring_10d"],
                             sessions)


async def _view_pw_members(page: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    users = await list_premium_users(500)
    if not users:
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"💎 <b>{fb('PREMIUM MEMBERS')}</b>",
            DIV, "",
            "⚪ ɴᴏ ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ʏᴇᴛ.",
        ])
        return text, kb_pw_back()

    # Sort by expires_at (nearest first)
    now = time.time()
    users.sort(key=lambda u: u.get("expires_at", 0))

    per_page = 8
    total = len(users)
    start = page * per_page
    end = start + per_page
    page_users = users[start:end]

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"💎 <b>{fb('PREMIUM MEMBERS')}</b> · <code>{total}</code>",
        DIV, "",
    ]

    for i, u in enumerate(page_users, start=start + 1):
        uid = u.get("user_id")
        uname = u.get("username") or f"ID {uid}"
        expires = u.get("expires_at", 0)
        days = int((expires - now) / 86400) if expires else 0
        plan = u.get("plan_months", 0)

        if expires <= now:
            status = "❌ EXPIRED"
        elif days <= 1:
            status = f"🔴 {days}d"
        elif days <= 5:
            status = f"🟡 {days}d"
        elif days <= 10:
            status = f"🟠 {days}d"
        else:
            status = f"🟢 {days}d"

        lines.append(
            f"<b>{i}.</b> @{_esc(uname.lstrip('@'))}"
        )
        lines.append(
            f"   {status} · {plan}ᴍᴏ · <code>{uid}</code>"
        )
        lines.append("")

    rows = []
    # Action buttons per user (max 4 shown for compactness)
    for i, u in enumerate(page_users[:4], start=start + 1):
        uname = (u.get("username") or str(u.get("user_id")))[:20]
        rows.append([InlineKeyboardButton(
            f"⚙️ {i}. @{uname}",
            callback_data=f"pw:member:{u['user_id']}"
        )])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ PREV",
                                         callback_data=f"pw:members_p:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT ▶️",
                                         callback_data=f"pw:members_p:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("➕ ADD USER",
                                       callback_data="pw:add"),
                 InlineKeyboardButton("🔍 FIND",
                                       callback_data="pw:find")])
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data="pw:main"),
                 InlineKeyboardButton("❌ CLOSE",
                                       callback_data="pw:close")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _view_pw_member_detail(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    u = await get_premium_user(user_id)
    if not u:
        return ("⚠️ ᴜꜱᴇʀ ɴᴏᴛ ꜰᴏᴜɴᴅ.",
                kb_pw_back("pw:members"))

    uid = u.get("user_id")
    uname = u.get("username") or f"ID {uid}"
    expires = u.get("expires_at", 0)
    plan = u.get("plan_months", 0)
    added = u.get("added_at", 0)
    added_by = u.get("added_by", 0)
    notes = u.get("notes") or "—"
    now = time.time()
    days_left = int((expires - now) / 86400)

    # Get sessions
    sessions = await list_user_sessions(uid)
    session_lines = []
    for s in sessions[:5]:
        title = s.get("series_title") or "?"
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        session_lines.append(
            f"  • {_esc(title)}\n"
            f"    {bar} {p['total_watched']}/{p['total_eps']}"
        )
    sessions_block = "\n".join(session_lines) if session_lines else "  ⚪ ɴᴏɴᴇ"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{sc('premium user')}</b>",
        DIV, "",
        f"🆔 <code>{uid}</code>",
        f"📛 @{_esc(str(uname).lstrip('@'))}",
        "",
        f"📅 {sc('plan')} · <code>{plan} ᴍᴏɴᴛʜꜱ</code>",
        f"✅ {sc('added')} · <code>{_date_ist(added)}</code>",
        f"👤 {sc('by')} · <code>{added_by}</code>",
        f"⏳ {sc('expires')} · <code>{_date_ist(expires)}</code>",
        f"📊 {sc('days left')} · <code>{days_left}</code>",
        "",
        f"📝 {sc('notes')} · <i>{_esc(notes)}</i>",
        "", DIV2, "",
        f"🎬 <b>{sc('active sessions')}</b>",
        sessions_block,
    ])

    return text, kb_pw_member_actions(uid)


async def _view_pw_expiring() -> Tuple[str, InlineKeyboardMarkup]:
    users = await list_premium_users(500)
    now = time.time()
    d10 = now + (10 * 86400)

    expiring = [u for u in users
                if u.get("status") == "active"
                and now < u.get("expires_at", 0) <= d10]

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏰ <b>{fb('EXPIRING SOON')}</b> · <code>{len(expiring)}</code>",
        DIV, "",
    ]

    if not expiring:
        lines.append("⚪ ɴᴏɴᴇ ᴇxᴘɪʀɪɴɢ ꜱᴏᴏɴ.")
    else:
        expiring.sort(key=lambda u: u.get("expires_at", 0))
        for u in expiring:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days = int((expires - now) / 86400)
            icon = "🔴" if days <= 1 else ("🟡" if days <= 5 else "🟠")
            lines.append(
                f"{icon} @{_esc(str(uname).lstrip('@'))}"
            )
            lines.append(
                f"   {days}ᴅ · {_date_ist(expires)} · "
                f"<code>{u.get('user_id')}</code>"
            )
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_expired() -> Tuple[str, InlineKeyboardMarkup]:
    users = await list_premium_users(500)
    now = time.time()
    expired = [u for u in users if u.get("expires_at", 0) <= now]

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"❌ <b>{fb('EXPIRED USERS')}</b> · <code>{len(expired)}</code>",
        DIV, "",
    ]

    if not expired:
        lines.append("⚪ ɴᴏ ᴇxᴘɪʀᴇᴅ ᴜꜱᴇʀꜱ.")
    else:
        expired.sort(key=lambda u: u.get("expires_at", 0), reverse=True)
        for u in expired[:20]:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days_ago = int((now - expires) / 86400)
            grace_end = expires + (GRACE_PERIOD_DAYS * 86400)
            grace_days = int((grace_end - now) / 86400)
            grace_icon = "🗑️" if grace_days <= 0 else "💾"
            lines.append(
                f"❌ @{_esc(str(uname).lstrip('@'))}"
            )
            lines.append(
                f"   {days_ago}ᴅ ᴀɢᴏ · {grace_icon} {max(0, grace_days)}ᴅ ɢʀᴀᴄᴇ · "
                f"<code>{u.get('user_id')}</code>"
            )
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_stats() -> Tuple[str, InlineKeyboardMarkup]:
    stats = await count_premium_users()
    sessions = await count_sessions()

    # Calculate revenue estimate
    users = await list_premium_users(500)
    total_months = sum(u.get("plan_months", 0) for u in users
                        if u.get("status") == "active")
    total_users = len([u for u in users if u.get("status") == "active"])

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('PREMIUM STATS')}</b>",
        DIV, "",
        f"👥 {sc('active members')} · <code>{stats['active']}</code>",
        f"❌ {sc('expired')} · <code>{stats['expired']}</code>",
        f"🎬 {sc('watch sessions')} · <code>{sessions}</code>",
        "", DIV2, "",
        f"⏳ {sc('expiring 10d')} · <code>{stats['expiring_10d']}</code>",
        f"⏳ {sc('expiring 5d')} · <code>{stats['expiring_5d']}</code>",
        f"⏳ {sc('expiring 1d')} · <code>{stats['expiring_1d']}</code>",
        "", DIV2, "",
        f"📈 {sc('total months sold')} · <code>{total_months}</code>",
        f"📊 {sc('avg plan')} · "
        f"<code>{round(total_months/total_users, 1) if total_users else 0}ᴍᴏ</code>",
        "", DIV2,
        f"🕒 <code>{_now_ist()}</code>",
    ])

    return text, kb_pw_back()


async def _view_pw_find() -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('FIND PREMIUM USER')}</b>",
        DIV, "",
        f"📝 {sc('send user id or @username')}",
        "",
        f"📌 {sc('examples')}:",
        f"<code>123456789</code>",
        f"<code>@john</code>",
    ])
    return text, kb_pw_back()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["seriesgroupsettings", "premium", "pw"]) & filters.private,
    group=-426,
)
async def cmd_pw_main(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_admin_session(message.from_user.id)
        text, kb = await _view_pw_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[PREM] /seriesgroupsettings: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CALLBACK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:main$"), group=-426)
async def cb_pw_main(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
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
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_admin_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# MEMBERS LIST
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:members$"), group=-426)
async def cb_pw_members(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] members: {e}")


@Client.on_callback_query(filters.regex(r"^pw:members_p:(\d+)$"), group=-426)
async def cb_pw_members_page(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        page = int(q.matches[0].group(1))
        text, kb = await _view_pw_members(page)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] members page: {e}")


@Client.on_callback_query(filters.regex(r"^pw:member:(\d+)$"), group=-426)
async def cb_pw_member(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = int(q.matches[0].group(1))
        text, kb = await _view_pw_member_detail(uid)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] member detail: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ADD PREMIUM — Flow
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:add$"), group=-426)
async def cb_pw_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _new_admin_session(q.from_user.id, "add_premium_user")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"➕ <b>{fb('ADD PREMIUM USER')}</b>",
            DIV, "",
            f"📝 {sc('send user id or @username')}",
            "",
            f"📌 {sc('examples')}:",
            f"<code>123456789</code>",
            f"<code>@john</code>",
            "",
            f"💡 {sc('or forward a message from the user')}",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL", callback_data="pw:main")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] add: {e}")


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/") & ~filters.regex(r"^pw:"),
    group=-425,
)
async def pw_admin_input(client, message):
    """Catch admin text inputs for premium flows."""
    if not message.from_user:
        return
    if not _is_admin(message.from_user.id):
        return

    s = _get_admin_session(message.from_user.id)
    if not s:
        return

    action = s.get("action")
    if action not in ("add_premium_user", "find_user", "edit_notes"):
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    text = (message.text or "").strip()
    if not text:
        return

    # ─── ADD PREMIUM USER — Step 1: Get user_id/username ───────────────
    if action == "add_premium_user":
        await _handle_add_user_input(client, message, text)
        return

    # ─── FIND USER ─────────────────────────────────────────────────────
    if action == "find_user":
        await _handle_find_user_input(client, message, text)
        return

    # ─── EDIT NOTES ────────────────────────────────────────────────────
    if action == "edit_notes":
        await _handle_edit_notes_input(client, message, text, s)
        return


async def _handle_add_user_input(client, message, text: str):
    """Parse the user ID or @username, then show plan picker."""
    uid_target = None
    username = ""

    # Case 1: numeric ID
    if text.lstrip("-").isdigit():
        uid_target = int(text)
    # Case 2: @username
    elif text.startswith("@"):
        username = text
        # Try to find in DB first
        doc = await find_premium_by_username(text)
        if doc:
            uid_target = doc.get("user_id")
        else:
            # Try resolving via Telegram
            try:
                u = await client.get_users(text)
                uid_target = u.id
                username = f"@{u.username}" if u.username else f"ID {u.id}"
            except Exception as e:
                _clear_admin_session(message.from_user.id)
                return await message.reply_text(
                    f"❌ ᴄᴏᴜʟᴅ ɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ <code>{_esc(text)}</code>\n"
                    f"<i>{_esc(str(e))[:100]}</i>",
                    parse_mode=ParseMode.HTML)
    else:
        # Plain username without @
        try:
            u = await client.get_users(text)
            uid_target = u.id
            username = f"@{u.username}" if u.username else f"ID {u.id}"
        except Exception:
            _clear_admin_session(message.from_user.id)
            return await message.reply_text(
                "❌ ɪɴᴠᴀʟɪᴅ. ꜱᴇɴᴅ ᴜꜱᴇʀ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.")

    if not uid_target:
        _clear_admin_session(message.from_user.id)
        return await message.reply_text("❌ ᴄᴏᴜʟᴅ ɴᴏᴛ ɪᴅᴇɴᴛɪꜰʏ ᴜꜱᴇʀ.")

    # Check if already premium
    existing = await get_premium_user(uid_target)
    if existing and existing.get("expires_at", 0) > time.time():
        _clear_admin_session(message.from_user.id)
        uname = existing.get("username") or uid_target
        exp = _date_ist(existing.get("expires_at", 0))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 EXTEND PLAN",
                                   callback_data=f"pw:member:{uid_target}")],
            [InlineKeyboardButton("◀️ BACK",
                                   callback_data="pw:main")],
        ])
        return await message.reply_text(
            f"⚠️ ᴜꜱᴇʀ ᴀʟʀᴇᴀᴅʏ ᴘʀᴇᴍɪᴜᴍ\n\n"
            f"👤 <code>{uid_target}</code>\n"
            f"📛 @{_esc(str(uname).lstrip('@'))}\n"
            f"📅 ᴇxᴘɪʀᴇꜱ: <b>{exp}</b>",
            reply_markup=kb, parse_mode=ParseMode.HTML)

    # Store pending target
    _new_admin_session(message.from_user.id, "pick_plan",
                       target_uid=uid_target,
                       target_username=username)

    # Get user display name if possible
    try:
        u = await client.get_users(uid_target)
        display = (u.first_name or "") + \
                  (f" {u.last_name}" if u.last_name else "")
        uname_display = f"@{u.username}" if u.username else f"ID {u.id}"
    except Exception:
        display = str(uid_target)
        uname_display = username or str(uid_target)

    text_out = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('PICK PLAN DURATION')}</b>",
        DIV, "",
        f"👤 {sc('user')} · <b>{_esc(display)}</b>",
        f"📛 {sc('username')} · <code>{_esc(uname_display)}</code>",
        f"🆔 {sc('id')} · <code>{uid_target}</code>",
        "", DIV2, "",
        f"📌 {sc('tap a plan duration below')}",
    ])

    await message.reply_text(
        text_out,
        reply_markup=kb_pw_plan_picker(uid_target, username),
        parse_mode=ParseMode.HTML)


async def _handle_find_user_input(client, message, text: str):
    _clear_admin_session(message.from_user.id)
    doc = None
    if text.lstrip("-").isdigit():
        doc = await get_premium_user(int(text))
    elif text.startswith("@"):
        doc = await find_premium_by_username(text)

    if not doc:
        return await message.reply_text(
            "⚪ ɴᴏᴛ ꜰᴏᴜɴᴅ ɪɴ ᴘʀᴇᴍɪᴜᴍ ᴅʙ.",
            reply_markup=kb_pw_back())

    text_out, kb = await _view_pw_member_detail(doc.get("user_id"))
    await message.reply_text(text_out, reply_markup=kb,
                              parse_mode=ParseMode.HTML)


async def _handle_edit_notes_input(client, message, text: str, s):
    target_uid = s.get("target_uid")
    _clear_admin_session(message.from_user.id)
    if not target_uid:
        return await message.reply_text("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛ.")

    c = _premium_coll()
    if c is None:
        return await message.reply_text("⚠️ ᴅʙ ᴇʀʀᴏʀ.")

    try:
        await c.update_one(
            {"user_id": int(target_uid)},
            {"$set": {"notes": text[:500]}}
        )
        await message.reply_text(
            f"✅ ɴᴏᴛᴇꜱ ꜱᴀᴠᴇᴅ.",
            reply_markup=kb_pw_back(f"pw:member:{target_uid}"))
    except Exception:
        await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")


# ═══════════════════════════════════════════════════════════════════════════
# PLAN PICK → ADD
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:plan:(\d+):(\d+)$"), group=-426,
)
async def cb_pw_plan(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        months = int(q.matches[0].group(2))

        s = _get_admin_session(q.from_user.id)
        if not s or s.get("action") != "pick_plan":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        target_username = s.get("target_username") or ""

        ok = await add_premium_user(
            user_id=target_uid,
            username=target_username,
            months=months,
            added_by=q.from_user.id,
        )

        if not ok:
            return await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)

        _clear_admin_session(q.from_user.id)

        # Get updated info
        doc = await get_premium_user(target_uid)
        expires = doc.get("expires_at", 0) if doc else 0

        await q.answer("✅ ᴀᴅᴅᴇᴅ")

        text_out = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('PREMIUM ADDED')}</b>",
            DIV, "",
            f"👤 {sc('user')} · <code>{target_uid}</code>",
            f"📛 {sc('username')} · <code>{_esc(target_username)}</code>",
            "",
            f"📅 {sc('plan')} · <code>{months} ᴍᴏɴᴛʜꜱ</code>",
            f"⏳ {sc('expires')} · <code>{_date_ist(expires)}</code>",
            "",
            f"🕒 {_now_ist()}",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ADD ANOTHER",
                                   callback_data="pw:add"),
             InlineKeyboardButton("👥 VIEW LIST",
                                   callback_data="pw:members")],
            [InlineKeyboardButton("◀️ BACK",
                                   callback_data="pw:main"),
             InlineKeyboardButton("❌ CLOSE",
                                   callback_data="pw:close")],
        ])

        await _pw_safe_edit(q, text_out, kb)

        # Notify user
        try:
            await client.send_message(
                chat_id=target_uid,
                text="\n".join([
                    f"💎 <b>{fb('PREMIUM ACTIVATED')}</b>",
                    DIV, "",
                    f"Hi! Your premium has been activated 🎉",
                    "",
                    f"📅 {sc('plan')} · <code>{months} ᴍᴏɴᴛʜꜱ</code>",
                    f"⏳ {sc('expires')} · <code>{_date_ist(expires)}</code>",
                    "", DIV2,
                    f"🎬 {sc('start watching')} · ꜱᴇᴀʀᴄʜ ᴀ ꜱᴇʀɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"[PREM] plan pick: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# EXTEND / REMOVE / NOTES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:extend:(\d+)$"), group=-426)
async def cb_pw_extend(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)
        if not doc:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        _new_admin_session(q.from_user.id, "pick_plan",
                           target_uid=target_uid,
                           target_username=doc.get("username") or "")

        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔄 <b>{fb('EXTEND PREMIUM')}</b>",
            DIV, "",
            f"👤 <code>{target_uid}</code>",
            f"📛 @{_esc(str(doc.get('username') or '').lstrip('@'))}",
            "",
            f"📅 {sc('current expires')} · "
            f"<code>{_date_ist(doc.get('expires_at', 0))}</code>",
            "", DIV2,
            f"📌 {sc('pick new plan duration')}",
        ])
        await _pw_safe_edit(q, text, kb_pw_plan_picker(target_uid,
                                                         doc.get("username") or ""))
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] extend: {e}")


@Client.on_callback_query(filters.regex(r"^pw:remove:(\d+)$"), group=-426)
async def cb_pw_remove(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)

        text = "\n".join([
            f"⚠️ <b>{fb('REMOVE PREMIUM?')}</b>",
            DIV, "",
            f"👤 <code>{target_uid}</code>",
        ])
        if doc:
            text += f"\n📛 @{_esc(str(doc.get('username') or '').lstrip('@'))}"

        text += "\n\n❌ ᴛʜɪꜱ ᴄᴀɴɴᴏᴛ ʙᴇ ᴜɴᴅᴏɴᴇ."

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ YES, REMOVE",
                                   callback_data=f"pw:remove_go:{target_uid}")],
            [InlineKeyboardButton("❌ CANCEL",
                                   callback_data=f"pw:member:{target_uid}")],
        ])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] remove: {e}")


@Client.on_callback_query(filters.regex(r"^pw:remove_go:(\d+)$"), group=-426)
async def cb_pw_remove_go(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        ok = await remove_premium_user(target_uid)
        await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ" if ok else "❌ ɴᴏᴛ ꜰᴏᴜɴᴅ")

        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[PREM] remove_go: {e}")


@Client.on_callback_query(filters.regex(r"^pw:notes:(\d+)$"), group=-426)
async def cb_pw_notes(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        _new_admin_session(q.from_user.id, "edit_notes", target_uid=target_uid)

        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✏️ <b>{fb('EDIT NOTES')}</b>",
            DIV, "",
            f"👤 <code>{target_uid}</code>",
            "",
            f"📝 {sc('send notes (or /skip to clear)')}",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL",
                                   callback_data=f"pw:member:{target_uid}")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] notes: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FIND / EXPIRING / EXPIRED / STATS / CONTACT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:find$"), group=-426)
async def cb_pw_find(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _new_admin_session(q.from_user.id, "find_user")
        text, kb = await _view_pw_find()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] find: {e}")


@Client.on_callback_query(filters.regex(r"^pw:expiring$"), group=-426)
async def cb_pw_expiring(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        text, kb = await _view_pw_expiring()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expiring: {e}")


@Client.on_callback_query(filters.regex(r"^pw:expired$"), group=-426)
async def cb_pw_expired(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        text, kb = await _view_pw_expired()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expired: {e}")


@Client.on_callback_query(filters.regex(r"^pw:stats$"), group=-426)
async def cb_pw_stats(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        text, kb = await _view_pw_stats()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] stats: {e}")


@Client.on_callback_query(filters.regex(r"^pw:contact$"), group=-426)
async def cb_pw_contact(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        current = await get_contact_admin() or "—"
        _new_admin_session(q.from_user.id, "set_contact")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"👤 <b>{fb('SET CONTACT ADMIN')}</b>",
            DIV, "",
            f"📌 {sc('current')} · <code>{_esc(current)}</code>",
            "",
            f"📝 {sc('send @username of admin to contact')}",
            f"📌 {sc('example')}: <code>@your_username</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL", callback_data="pw:main")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] contact: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CONTACT SETTING HANDLER (extends pw_admin_input)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text & filters.regex(r"^@\w+$"),
    group=-424,
)
async def pw_contact_input(client, message):
    """Handle @username input for contact admin."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    s = _get_admin_session(message.from_user.id)
    if not s or s.get("action") != "set_contact":
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    text = (message.text or "").strip()
    if not re.match(r"^@\w+$", text):
        return await message.reply_text("❌ ꜰᴏʀᴍᴀᴛ: @ᴜꜱᴇʀɴᴀᴍᴇ")

    ok = await set_setting("contact_admin", text)
    _clear_admin_session(message.from_user.id)

    if ok:
        await message.reply_text(
            f"✅ ᴄᴏɴᴛᴀᴄᴛ ꜱᴀᴠᴇᴅ: <code>{_esc(text)}</code>",
            reply_markup=kb_pw_back(),
            parse_mode=ParseMode.HTML)
    else:
        await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")


logger.info("💎 PREMIUM WATCH — Part B loaded (admin panel + premium mgmt)")


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════ PART C — GROUP → PM REDIRECT ══════════════════
# ═══════════════════════════════════════════════════════════════════════════

# Session store: tracks premium "handoff" from group → PM
_HANDOFFS: Dict[str, Dict[str, Any]] = {}
_HANDOFF_TTL = 600  # 10 minutes


def _new_handoff(user_id: int, series_data: Dict[str, Any]) -> str:
    """Create a handoff token pointing to a series."""
    import secrets
    token = secrets.token_urlsafe(10)
    _HANDOFFS[token] = {
        "user_id": int(user_id),
        "data": series_data,
        "expires": time.time() + _HANDOFF_TTL,
    }
    return token


def _get_handoff(token: str) -> Optional[Dict[str, Any]]:
    h = _HANDOFFS.get(token)
    if not h: return None
    if time.time() > h.get("expires", 0):
        _HANDOFFS.pop(token, None)
        return None
    return h


def _pop_handoff(token: str) -> Optional[Dict[str, Any]]:
    h = _get_handoff(token)
    if h:
        _HANDOFFS.pop(token, None)
    return h


def _cleanup_handoffs():
    now = time.time()
    for t in list(_HANDOFFS.keys()):
        if _HANDOFFS[t].get("expires", 0) < now:
            _HANDOFFS.pop(t, None)


# ═══════════════════════════════════════════════════════════════════════════
# GROUP SEARCH HOOK — detects premium + redirects
# ═══════════════════════════════════════════════════════════════════════════
async def handle_premium_group_search(client: Client, message,
                                       query: str,
                                       db_result: Optional[Dict[str, Any]],
                                       tmdb_results: List[Dict[str, Any]]
                                       ) -> bool:
    """
    Called from series_group.py when a premium user searches.

    Returns True if handled (redirect flow triggered).
    Returns False if caller should run normal flow.

    Parameters:
      query        — what user typed
      db_result    — {"matched_title": str, "hits": [...]} or None
      tmdb_results — TMDB suggestions list
    """
    try:
        uid = message.from_user.id
        # Only for premium users
        if not await is_premium(uid):
            return False

        # Case 1: DB has it — go straight to PM
        if db_result and db_result.get("hits"):
            matched_title = db_result.get("matched_title") or query
            return await _premium_redirect_to_pm(
                client, message, uid, matched_title,
                db_result.get("hits") or [],
                tmdb_results
            )

        # Case 2: No DB match — show suggestions as normal
        # (caller handles suggestions normally)
        return False
    except Exception as e:
        logger.exception(f"[PREM] group search hook: {e}")
        return False


async def _premium_redirect_to_pm(client: Client, message,
                                    uid: int, title: str,
                                    hits: List[Dict[str, Any]],
                                    tmdb_results: List[Dict[str, Any]]
                                    ) -> bool:
    """Send a compact redirect message in the group, and prepare PM session."""
    try:
        # Find the best TMDB entry
        tmdb_id = None
        poster = None
        year = ""
        rating = 0
        display_title = title

        # Match by title if possible
        for t in (tmdb_results or []):
            t_title = (t.get("title") or "").lower().strip()
            if t_title == title.lower().strip():
                tmdb_id = t.get("tmdb_id")
                poster = t.get("poster")
                year = t.get("year") or ""
                rating = t.get("rating", 0)
                display_title = t.get("title") or title
                break

        if not tmdb_id and tmdb_results:
            ch = tmdb_results[0]
            tmdb_id = ch.get("tmdb_id")
            poster = ch.get("poster")
            year = ch.get("year") or ""
            rating = ch.get("rating", 0)
            display_title = ch.get("title") or title

        # Fetch TMDB season details
        tmdb_seasons = []
        if tmdb_id:
            try:
                from plugins.series_group import _tmdb_series_details, _tmdb_seasons
                details = await _tmdb_series_details(tmdb_id)
                if details:
                    tmdb_seasons = _tmdb_seasons(details)
            except Exception as e:
                logger.debug(f"[PREM] tmdb details: {e}")

        # Build the handoff data
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

        token = _new_handoff(uid, series_data)

        # Try to get bot username
        try:
            me = await client.get_me()
            bot_username = me.username or "your_bot"
        except Exception:
            bot_username = "your_bot"

        deep_link = f"https://t.me/{bot_username}?start=watch_{token}"

        # Delete the original user message + bot status
        try:
            await message.delete()
        except Exception:
            pass

        # Send redirect message in group
        poster_line = f"📺 {len(tmdb_seasons)} ꜱᴇᴀꜱᴏɴꜱ" if tmdb_seasons else ""

        group_text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"💎 <b>{fb('PREMIUM')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(display_title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            (f"⭐ {rating:.1f}" if rating else ""),
            (poster_line if poster_line else ""),
            "",
            DIV2, "",
            f"📩 {sc('check your pm to start watching')}",
            f"🚀 {sc('tap below to open')}",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 OPEN IN PM", url=deep_link)],
            [InlineKeyboardButton("❌ CANCEL",
                                   callback_data=f"pw:g_cancel:{token}")],
        ])

        # Delete previous bot message if replying
        try:
            await message.reply_text(
                "\n".join(line for line in group_text.split("\n") if line),
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[PREM] group reply: {e}")

        logger.info(f"[PREM] redirect token={token} user={uid} "
                     f"title={display_title!r}")

        # ─────────────────────────────────────────────────────────────
        # Pre-create the PM session poster — send NOW so user sees it
        # ─────────────────────────────────────────────────────────────
        try:
            await _prepare_pm_session(client, uid, token, series_data)
        except Exception as e:
            logger.warning(f"[PREM] prepare PM: {e}")

        return True
    except Exception as e:
        logger.exception(f"[PREM] redirect: {e}")
        return False


async def _prepare_pm_session(client: Client, uid: int, token: str,
                               series_data: Dict[str, Any]):
    """
    Send the initial PM poster to the user.
    This is the persistent message that stays until they finish the series.
    """
    try:
        title = series_data.get("title") or "?"
        year = series_data.get("year") or ""
        rating = series_data.get("rating", 0)
        tmdb_seasons = series_data.get("tmdb_seasons") or []
        poster_path = series_data.get("poster")

        # Compose poster URL
        poster_url = None
        if poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

        # Season summary
        total_eps = sum(s.get("episodes", 0) for s in tmdb_seasons)
        seasons_count = len(tmdb_seasons)

        # Text body
        text = "\n".join([
            f"🎬 <b>{_esc(title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            (f"⭐ {rating:.1f}" if rating else ""),
            f"📺 <code>{seasons_count} ꜱᴇᴀꜱᴏɴꜱ</code> · "
            f"<code>{total_eps} ᴇᴘɪꜱᴏᴅᴇꜱ</code>",
            "",
            DIV, "",
            f"💎 <b>{fb('PREMIUM MODE')}</b>",
            "",
            f"🌍 {sc('pick language to start')}",
        ])

        # Language buttons — fetch available languages
        langs = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]
        # Filter by what's actually available
        try:
            available_langs = set()
            for h in (series_data.get("hits") or [])[:50]:
                for lang in (h.get("languages") or []):
                    if lang: available_langs.add(lang)
        except Exception:
            available_langs = set()

        if available_langs:
            langs = [l for l in langs if l in available_langs] or list(available_langs)[:5]

        if not langs:
            langs = ["English"]

        # Build keyboard with languages
        kb_rows = []
        row = []
        for i, lang in enumerate(langs[:6]):
            row.append(InlineKeyboardButton(
                f"🌍 {lang}",
                callback_data=f"pw:lang:{token}:{i}"
            ))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        kb_rows.append([InlineKeyboardButton(
            "🎬 WATCH ORDER",
            callback_data=f"pw:wo:{token}"
        )])
        kb_rows.append([InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"pw:cancel:{token}"
        )])

        kb = InlineKeyboardMarkup(kb_rows)

        # Send poster with photo
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
                logger.debug(f"[PREM] poster send_photo fail: {e}")
                # Fallback: text only
                msg = await client.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        else:
            msg = await client.send_message(
                chat_id=uid,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        # Store the message ID in the handoff for later retrieval
        h = _HANDOFFS.get(token)
        if h:
            h["poster_msg_id"] = msg.id
            h["poster_chat_id"] = uid

        logger.info(f"[PREM] PM poster sent to {uid} msg={msg.id}")

    except Exception as e:
        logger.exception(f"[PREM] prepare PM: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DEEP LINK HANDLER — /start watch_<token>
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command("start") & filters.private,
    group=-423,
)
async def pw_start_handler(client, message):
    """Handle /start watch_<token> deep link for premium handoff."""
    try:
        if not message.from_user:
            return
        uid = message.from_user.id
        if len(message.command) < 2:
            return

        payload = message.command[1]

        # Only handle watch_* tokens
        if not payload.startswith("watch_"):
            return

        try:
            message.stop_propagation()
        except Exception:
            pass

        token = payload[6:]
        handoff = _get_handoff(token)

        # ── Not premium? ────────────────────────────────────────────
        if not await is_premium(uid):
            await message.reply_text(
                "\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('PREMIUM ONLY')}</b>",
                    DIV, "",
                    f"📌 {sc('this feature is for premium members')}",
                    f"📌 {sc('contact admin to subscribe')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return

        # ── No handoff found ────────────────────────────────────────
        if not handoff:
            # Session expired — but user is premium. Show list of sessions.
            sessions = await list_user_sessions(uid)
            if sessions:
                await _show_session_list(client, message.chat.id, uid)
            else:
                await message.reply_text(
                    "\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"⚠️ <b>{fb('SESSION EXPIRED')}</b>",
                        DIV, "",
                        f"📌 {sc('please search again in the group')}",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            return

        # ── Handoff expired but user premium ────────────────────────
        if handoff.get("user_id") != uid:
            await message.reply_text("❌ ᴛʜɪꜱ ʟɪɴᴋ ɪꜱ ɴᴏᴛ ꜰᴏʀ ʏᴏᴜ.")
            return

        # If poster was already sent, just notify
        if handoff.get("poster_msg_id"):
            logger.info(f"[PREM] user {uid} re-opened token {token}")
            # Poster already exists, no need to duplicate
            return

        # Send the poster now
        data = handoff.get("data") or {}
        await _prepare_pm_session(client, uid, token, data)

    except Exception as e:
        logger.exception(f"[PREM] start handler: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# GROUP CANCEL BUTTON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:g_cancel:([A-Za-z0-9_-]+)$"),
    group=-422,
)
async def cb_pw_g_cancel(client, q):
    """Cancel premium redirect (called from group message)."""
    try:
        token = q.matches[0].group(1)
        handoff = _pop_handoff(token)
        if handoff:
            try: await q.message.delete()
            except Exception: pass
        await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    except Exception as e:
        logger.debug(f"[PREM] g_cancel: {e}")
        try: await q.answer("✅")
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# SESSION LIST — shown when user opens /start or /my
# ═══════════════════════════════════════════════════════════════════════════
async def _show_session_list(client: Client, chat_id: int, uid: int):
    """Show list of active watch sessions."""
    sessions = await list_user_sessions(uid)
    if not sessions:
        await client.send_message(
            chat_id=chat_id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📺 <b>{fb('YOUR SESSIONS')}</b>",
                DIV, "",
                f"⚪ {sc('no active sessions')}",
                "",
                f"📌 {sc('search a series in the group to start')}",
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📺 <b>{fb('YOUR SESSIONS')}</b> · <code>{len(sessions)}</code>",
        DIV, "",
    ]

    rows = []
    for s in sessions[:10]:
        title = s.get("series_title") or "?"
        slug = s.get("series_slug") or ""
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        lines.append(f"🎬 <b>{_esc(title)}</b>")
        lines.append(f"   {bar} {p['total_watched']}/{p['total_eps']}")
        lines.append("")

        rows.append([InlineKeyboardButton(
            f"▶️ {title[:30]} · {p['total_watched']}/{p['total_eps']}",
            callback_data=f"pw:resume:{slug}"
        )])

    rows.append([InlineKeyboardButton(
        "❌ CLOSE", callback_data="pw:close_session_list"
    )])

    await client.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command(["my", "myseries", "watchlist"]) & filters.private,
    group=-422,
)
async def cmd_my_sessions(client, message):
    """Show user's active watch sessions."""
    if not message.from_user:
        return
    uid = message.from_user.id
    if not await is_premium(uid):
        return await message.reply_text("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ.")
    try:
        await _show_session_list(client, message.chat.id, uid)
    except Exception as e:
        logger.exception(f"[PREM] /my: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:my_sessions$"), group=-422,
)
async def cb_pw_my_sessions(client, q):
    """Show user's sessions from reminder message."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)
        await q.answer()
        await _show_session_list(client, q.message.chat.id, uid)
    except Exception as e:
        logger.debug(f"[PREM] my_sessions: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:dismiss_reminder$"), group=-422,
)
async def cb_pw_dismiss(client, q):
    try:
        try: await q.message.delete()
        except Exception: pass
        await q.answer("✅")
    except Exception:
        pass


@Client.on_callback_query(
    filters.regex(r"^pw:close_session_list$"), group=-422,
)
async def cb_pw_close_list(client, q):
    try:
        try: await q.message.delete()
        except Exception: pass
        await q.answer("✅")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# HANDOFF CLEANUP
# ═══════════════════════════════════════════════════════════════════════════
async def _handoff_cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_handoffs()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


# Add to boot
_HANDOFF_BOOTED = False


@Client.on_message(filters.private, group=-421)
async def _pw_handoff_boot(client, message):
    global _HANDOFF_BOOTED
    if _HANDOFF_BOOTED:
        return
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    _HANDOFF_BOOTED = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_handoff_cleanup_loop())
        logger.info("[PREM] handoff cleanup loop started")
    except Exception:
        pass


logger.info("💎 PREMIUM WATCH — Part C loaded (group→PM redirect + handoffs)")

# ═══════════════════════════════════════════════════════════════════════════
# ═════════════════ PART D — PM SESSION FLOW + WATCHED TRACKING ═════════════
# ═══════════════════════════════════════════════════════════════════════════

# Session store: temp data per user (language → season → episode)
_PW_SESSIONS: Dict[int, Dict[str, Any]] = {}
_PW_SESSION_TTL = 3600  # 1 hour


def _pw_new(uid: int, action: str, **data):
    _PW_SESSIONS[uid] = {
        "action": action,
        "expires": time.time() + _PW_SESSION_TTL,
        **data,
    }


def _pw_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _PW_SESSIONS.get(uid)
    if not s: return None
    if time.time() > s.get("expires", 0):
        _PW_SESSIONS.pop(uid, None)
        return None
    return s


def _pw_clear(uid: int):
    _PW_SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# LOCK (prevent double-click)
# ═══════════════════════════════════════════════════════════════════════════
_PW_LOCKS: Dict[int, float] = {}


def _pw_acquire_lock(uid: int, secs: float = 3.0) -> bool:
    """Return True if lock acquired, False if user clicked too fast."""
    now = time.time()
    last = _PW_LOCKS.get(uid, 0)
    if now - last < secs:
        return False
    _PW_LOCKS[uid] = now
    return True


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
def _build_poster_text(session: Dict[str, Any],
                       title: str, year: str = "",
                       rating: float = 0) -> str:
    """Build the poster message body (persistent)."""
    p = compute_progress(session)
    seasons_raw = session.get("seasons") or {}
    seasons_ordered = sorted(int(k) for k in seasons_raw.keys()
                              if k.isdigit())

    lines = [
        f"🎬 <b>{_esc(title)}</b>"
        + (f" <code>({year})</code>" if year else ""),
    ]
    if rating:
        lines.append(f"⭐ {rating:.1f}")

    lines += ["", DIV, "", f"📊 <b>{fb('YOUR PROGRESS')}</b>", ""]

    # Per-season bars
    for sn in seasons_ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        watched = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)
        if total == 0:
            bar = render_progress_bar(0)
            status = "⚪"
        else:
            pct = watched / total * 100
            bar = render_progress_bar(pct)
            if watched >= total:
                status = "✅"
            elif watched > 0:
                status = "🟡"
            else:
                status = "⚪"
        lines.append(
            f"S{sn:02d} {bar} {watched}/{total} {status}"
        )

    lines += ["", DIV2, ""]
    lines.append(
        f"📁 <b>{p['total_watched']}/{p['total_eps']}</b> "
        f"({p['pct']}%)"
    )

    # Time estimate (22 min per episode)
    remaining_eps = p["total_eps"] - p["total_watched"]
    if remaining_eps > 0:
        hours_left = remaining_eps * 22 / 60
        lines.append(f"⏳ ~{int(hours_left)} ʜᴏᴜʀꜱ ʟᴇꜰᴛ")

    return "\n".join(lines)


def _build_poster_kb(session: Dict[str, Any], slug: str):
    """Build poster keyboard with action buttons."""
    p = compute_progress(session)
    next_ep = find_next_episode(session)
    complete = is_series_complete(session)

    rows = []

    if complete:
        rows.append([InlineKeyboardButton(
            "🎉 MARK COMPLETE",
            callback_data=f"pw:complete:{slug}"
        )])
    elif next_ep:
        sn, ep = next_ep
        rows.append([InlineKeyboardButton(
            f"▶️ WATCH NEXT · S{sn:02d}E{ep:02d}",
            callback_data=f"pw:play:{slug}:{sn}:{ep}"
        )])

    rows.append([
        InlineKeyboardButton("🎬 SEASONS",
                              callback_data=f"pw:seasons:{slug}"),
        InlineKeyboardButton("🎬 WATCH ORDER",
                              callback_data=f"pw:wo:{slug}"),
    ])

    rows.append([InlineKeyboardButton(
        "⏸️ PAUSE",
        callback_data=f"pw:pause:{slug}"
    )])

    return InlineKeyboardMarkup(rows)


def _build_seasons_view(session: Dict[str, Any], slug: str,
                         title: str) -> Tuple[str, InlineKeyboardMarkup]:
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    lines = [
        f"🎬 <b>{_esc(title)}</b>",
        DIV, "",
        f"📺 <b>{fb('PICK A SEASON')}</b>",
        "",
    ]

    rows = []
    for sn in ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        watched = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)

        if total > 0 and watched >= total:
            icon = "✅"
        elif watched > 0:
            icon = "🟡"
        else:
            icon = "⚪"

        label = f"{icon} S{sn:02d} · {watched}/{total}"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"pw:season:{slug}:{sn}"
        )])

    rows.append([InlineKeyboardButton(
        "◀️ BACK", callback_data=f"pw:poster:{slug}"
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _build_episodes_view(session: Dict[str, Any], slug: str,
                          title: str, season: int
                          ) -> Tuple[str, InlineKeyboardMarkup]:
    s_data = (session.get("seasons") or {}).get(str(season)) or {}
    total = s_data.get("total_eps", 0)
    watched = set(s_data.get("watched") or [])

    lines = [
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {season:02d}</b>",
        DIV, "",
        f"📊 {sc('progress')} · "
        f"<code>{len(watched)}/{total}</code>",
        "",
        f"📌 {sc('pick an episode to watch')}",
        "",
    ]

    rows = []
    # 4 buttons per row
    row = []
    for ep in range(1, total + 1):
        mark = "✅" if ep in watched else "📥"
        row.append(InlineKeyboardButton(
            f"{mark} E{ep:02d}",
            callback_data=f"pw:play:{slug}:{season}:{ep}"
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        "◀️ BACK",
        callback_data=f"pw:seasons:{slug}"
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# RENDER — edit the poster message
# ═══════════════════════════════════════════════════════════════════════════
async def _render_poster(client: Client, session: Dict[str, Any]):
    """Edit the poster message with fresh content + buttons."""
    try:
        uid = session.get("user_id")
        chat_id = session.get("poster_chat_id") or uid
        msg_id = session.get("poster_msg_id")
        if not msg_id:
            return False

        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        year = session.get("year") or ""

        text = _build_poster_text(session, title, year)
        kb = _build_poster_kb(session, slug)

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
        except Exception as e:
            # If photo caption fails, try text edit (in case poster is text-only)
            logger.debug(f"[PREM] edit_caption failed: {e}")
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


# ═══════════════════════════════════════════════════════════════════════════
# LANGUAGE PICK
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:lang:([A-Za-z0-9_-]+):(\d+)$"),
    group=-420,
)
async def cb_pw_lang(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid):
            return await q.answer("⏳ ᴡᴀɪᴛ")

        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        token = q.matches[0].group(1)
        lang_idx = int(q.matches[0].group(2))

        handoff = _get_handoff(token)
        if not handoff:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        data = handoff.get("data") or {}
        title = data.get("title") or "?"
        tmdb_seasons = data.get("tmdb_seasons") or []
        hits = data.get("hits") or []

        # Determine which language was picked
        # (repopulate the same order as when we built the keyboard)
        langs = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]
        try:
            available_langs = set()
            for h in hits[:50]:
                for lang in (h.get("languages") or []):
                    if lang: available_langs.add(lang)
        except Exception:
            available_langs = set()

        if available_langs:
            langs = [l for l in langs if l in available_langs] or list(available_langs)[:5]
        if not langs:
            langs = ["English"]

        if lang_idx < 0 or lang_idx >= len(langs):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen_lang = langs[lang_idx]

        # ── Re-search DB with language filter ────────────────────────
        try:
            from plugins.series_group import _engine_search
            fresh_hits = await _engine_search(title, language=chosen_lang)
        except Exception as e:
            logger.warning(f"[PREM] lang search: {e}")
            fresh_hits = hits

        if not fresh_hits:
            # Try without language filter
            fresh_hits = hits

        # ── Recompute seasons from actual DB files ───────────────────
        db_seasons: Dict[int, Set[int]] = defaultdict(set)
        for f in fresh_hits:
            sn = f.get("season")
            ep = f.get("episode")
            if sn is not None:
                db_seasons[sn].add(ep if ep is not None else 0)

        # Use TMDB seasons as primary count, but adjust to what's in DB
        seasons_doc = {}
        for s in tmdb_seasons:
            sn = s.get("season")
            eps = s.get("episodes", 0)
            if sn is None: continue
            # If DB has more episodes than TMDB count, use DB count
            db_count = len(db_seasons.get(sn, set()))
            final_count = max(eps, db_count)
            seasons_doc[str(sn)] = {
                "total_eps": final_count,
                "watched": [],
                "current_ep": 1,
                "language": chosen_lang,
            }

        if not seasons_doc and db_seasons:
            for sn, eps_set in db_seasons.items():
                seasons_doc[str(sn)] = {
                    "total_eps": len(eps_set),
                    "watched": [],
                    "current_ep": 1,
                    "language": chosen_lang,
                }

        # ── Create/update watch session ──────────────────────────────
        slug = _slug(title)
        # Check if session already exists
        existing = await get_session(uid, slug)

        poster_chat_id = q.message.chat.id
        poster_msg_id = q.message.id

        if existing:
            # Update existing (keep watched progress, change language)
            c = _sessions_coll()
            if c:
                # Merge watched progress
                old_seasons = existing.get("seasons") or {}
                for sn_str, s_data in old_seasons.items():
                    if sn_str in seasons_doc:
                        seasons_doc[sn_str]["watched"] = s_data.get("watched") or []
                await c.update_one(
                    {"user_id": uid, "series_slug": slug},
                    {"$set": {
                        "seasons": seasons_doc,
                        "language": chosen_lang,
                        "last_activity_at": time.time(),
                        "poster_chat_id": poster_chat_id,
                        "poster_msg_id": poster_msg_id,
                        "poster": data.get("poster"),
                        "year": data.get("year") or "",
                        "tmdb_seasons": tmdb_seasons,
                        "hits": fresh_hits,
                    }}
                )
        else:
            # Create new
            now = time.time()
            c = _sessions_coll()
            if c:
                await c.insert_one({
                    "user_id": uid,
                    "series_slug": slug,
                    "series_title": title,
                    "poster": data.get("poster"),
                    "year": data.get("year") or "",
                    "tmdb_id": data.get("tmdb_id"),
                    "tmdb_seasons": tmdb_seasons,
                    "hits": fresh_hits,
                    "language": chosen_lang,
                    "seasons": seasons_doc,
                    "started_at": now,
                    "last_activity_at": now,
                    "status": "watching",
                    "completed_at": None,
                    "poster_chat_id": poster_chat_id,
                    "poster_msg_id": poster_msg_id,
                    "current_file_msg_id": None,
                    "current_season": 1,
                    "current_episode": 1,
                })

        # Clear handoff
        _HANDOFFS.pop(token, None)

        # Fetch fresh session
        session = await get_session(uid, slug)

        # Show seasons view
        seasons_view_text, seasons_kb = _build_seasons_view(
            session, slug, title
        )

        try:
            await q.message.edit_caption(
                caption=seasons_view_text,
                reply_markup=seasons_kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await q.message.edit_text(
                text=seasons_view_text,
                reply_markup=seasons_kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        await q.answer(f"🌍 {chosen_lang}")
        logger.info(f"[PREM] lang picked: u={uid} s={slug} lang={chosen_lang}")
    except Exception as e:
        logger.exception(f"[PREM] cb_pw_lang: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# SEASONS VIEW
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:seasons:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_seasons(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        text, kb = _build_seasons_view(session, slug, title)

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] seasons: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# EPISODES VIEW (per season)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:season:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_season(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        text, kb = _build_episodes_view(session, slug, title, season)

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] season: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# BACK TO POSTER
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
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        year = session.get("year") or ""

        text = _build_poster_text(session, title, year)
        kb = _build_poster_kb(session, slug)

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] poster: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PLAY EPISODE — Send file + Mark Watched button
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:play:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_play(client, q):
    """
    Send file + "Mark Watched" button.
    The poster edits to reflect new current position.
    """
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer("⏳")

        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        lang = session.get("language") or ""
        hits = session.get("hits") or []

        await q.answer("📥 ꜱᴇɴᴅɪɴɢ...")

        # ── Find matching file ───────────────────────────────────────
        chosen_file = None
        for f in hits:
            if f.get("season") == season and f.get("episode") == episode:
                # prefer higher quality
                chosen_file = f
                break

        if not chosen_file:
            await q.answer("⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
            return

        # ── Build file caption ───────────────────────────────────────
        quality = chosen_file.get("quality") or "?"
        size = _fmt_size(chosen_file.get("file_size", 0))
        langs = "+".join(chosen_file.get("languages") or []) or lang or "?"

        file_caption = "\n".join([
            f"🎬 <b>{_esc(title)}</b>",
            f"📺 <b>S{season:02d}E{episode:02d}</b>",
            f"🎯 <code>{quality}</code> · 🌍 <code>{langs}</code>",
            f"📦 {size}",
            "",
            f"💎 <i>ᴘʀᴇᴍɪᴜᴍ · ɴᴏ ᴇxᴘɪʀʏ</i>",
        ])

        # ── Send file ────────────────────────────────────────────────
        sent_msg = None
        fid = chosen_file.get("file_id")
        src_chat = chosen_file.get("chat_id")
        src_msg = chosen_file.get("message_id")
        fh = chosen_file.get("file_hit")
        if fh:
            if not src_chat: src_chat = getattr(fh, "chat_id", None)
            if not src_msg: src_msg = getattr(fh, "message_id", None) or \
                                       getattr(fh, "msg_id", None)
            if not fid: fid = getattr(fh, "file_id", "") or ""

        # Try cached first
        if fid:
            try:
                sent_msg = await client.send_cached_media(
                    chat_id=uid, file_id=fid,
                    caption=file_caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] cached send: {e}")

        # Try copy
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
            await q.answer("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ꜰɪʟᴇ", show_alert=True)
            return

        # ── Attach "Mark Watched" + "Watch Next" buttons to file ─────
        await _attach_watched_buttons(
            client, uid, sent_msg.id, slug, season, episode
        )

        # ── Update session current position ──────────────────────────
        await set_current_position(uid, slug, season, episode)
        await update_current_file_msg(uid, slug, sent_msg.id)

        # ── Update poster (progress bar, next button) ────────────────
        fresh = await get_session(uid, slug)
        if fresh:
            fresh["poster_chat_id"] = q.message.chat.id
            fresh["poster_msg_id"] = q.message.id
            await _render_poster(client, fresh)

        # Advance current cursor for next time
        await _advance_cursor(uid, slug, season, episode)

    except Exception as e:
        logger.exception(f"[PREM] play: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


async def _attach_watched_buttons(client: Client, uid: int, msg_id: int,
                                    slug: str, season: int, episode: int):
    """Add [Mark Watched] + [Watch Next] buttons to a file message."""
    rows = [
        [InlineKeyboardButton(
            "✅ MARK AS WATCHED",
            callback_data=f"pw:watched:{slug}:{season}:{episode}:{msg_id}"
        )],
        [InlineKeyboardButton(
            "▶️ WATCH NEXT",
            callback_data=f"pw:next:{slug}:{season}:{episode}"
        )],
    ]
    try:
        await client.edit_message_reply_markup(
            chat_id=uid,
            message_id=msg_id,
            reply_markup=InlineKeyboardMarkup(rows),
        )
    except Exception as e:
        logger.debug(f"[PREM] attach buttons: {e}")


async def _advance_cursor(uid: int, slug: str, season: int, episode: int):
    """Not used directly — cursor auto-advances on Mark Watched."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
# MARK AS WATCHED — file button
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:watched:([a-z0-9_]+):(\d+):(\d+):(\d+)$"),
    group=-420,
)
async def cb_pw_watched(client, q):
    """
    User taps ✅ MARK AS WATCHED on a file.
    Actions:
      1. Update DB (add ep to watched)
      2. Remove buttons from the file message
      3. Update poster (progress bar)
      4. Check if season/series complete
    """
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 1.5):
            return await q.answer("⏳")

        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))
        file_msg_id = int(q.matches[0].group(4))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        # ── Update DB ────────────────────────────────────────────────
        await mark_watched(uid, slug, season, episode)
        await set_current_position(uid, slug, season, episode)

        # ── Update the file message ──────────────────────────────────
        title = session.get("series_title") or "?"
        try:
            # Edit the caption to show ✅ WATCHED
            from pyrogram.types import InputMediaVideo
            # Just remove reply markup and add a ✅ indicator
            await client.edit_message_reply_markup(
                chat_id=uid,
                message_id=file_msg_id,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "✅ WATCHED",
                        callback_data=f"pw:already_watched:{slug}:{season}:{episode}"
                    )
                ]])
            )
        except Exception as e:
            logger.debug(f"[PREM] edit file: {e}")

        # ── Update poster ────────────────────────────────────────────
        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)

        # ── Check season completion ─────────────────────────────────
        s_data = (fresh.get("seasons") or {}).get(str(season)) or {}
        watched_count = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)

        if total > 0 and watched_count >= total:
            # Season complete
            await _season_complete_notify(client, uid, fresh, season)

        # ── Check series completion ─────────────────────────────────
        if is_series_complete(fresh):
            await _series_complete_notify(client, uid, fresh)

        await q.answer("✅ ᴡᴀᴛᴄʜᴇᴅ")

        logger.info(f"[PREM] watched u={uid} s={slug} S{season:02d}E{episode:02d}")

    except Exception as e:
        logger.exception(f"[PREM] watched: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:already_watched:([a-z0-9_]+):(\d+):(\d+)$"),
    group=-420,
)
async def cb_pw_already_watched(client, q):
    try:
        await q.answer("✅ ᴀʟʀᴇᴀᴅʏ ᴡᴀᴛᴄʜᴇᴅ")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# WATCH NEXT — file button
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:next:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_next(client, q):
    """User taps ▶️ WATCH NEXT on a file — auto-send next episode."""
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer("⏳")

        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        # Auto-mark current as watched
        await mark_watched(uid, slug, season, episode)

        # Determine next episode
        s_data = (session.get("seasons") or {}).get(str(season)) or {}
        total = s_data.get("total_eps", 0)
        next_ep = episode + 1

        if next_ep > total:
            # Season complete — find next season
            seasons_raw = session.get("seasons") or {}
            ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())
            next_season_found = None
            for sn in ordered:
                if sn > season:
                    next_season_found = sn
                    break

            if next_season_found:
                # Move to next season ep 1
                await q.answer("🎬 ɴᴇxᴛ ꜱᴇᴀꜱᴏɴ!")
                await cb_pw_play_direct(client, q, slug, next_season_found, 1)
                return
            else:
                await q.answer("🎉 ꜱᴇʀɪᴇꜱ ᴄᴏᴍᴘʟᴇᴛᴇ!")
                await _series_complete_notify(client, uid, session)
                return
        else:
            # Auto-send next episode
            await q.answer("📥 ɴᴇxᴛ ᴇᴘɪꜱᴏᴅᴇ")
            await cb_pw_play_direct(client, q, slug, season, next_ep)
    except Exception as e:
        logger.exception(f"[PREM] next: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


async def cb_pw_play_direct(client: Client, q, slug: str,
                              season: int, episode: int):
    """Directly trigger the play flow (used by Watch Next)."""
    try:
        uid = q.from_user.id
        session = await get_session(uid, slug)
        if not session:
            return

        title = session.get("series_title") or "?"
        lang = session.get("language") or ""
        hits = session.get("hits") or []

        # Find file
        chosen_file = None
        for f in hits:
            if f.get("season") == season and f.get("episode") == episode:
                chosen_file = f
                break

        if not chosen_file:
            await q.answer("⚠️ ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
            return

        quality = chosen_file.get("quality") or "?"
        size = _fmt_size(chosen_file.get("file_size", 0))
        langs = "+".join(chosen_file.get("languages") or []) or lang or "?"

        file_caption = "\n".join([
            f"🎬 <b>{_esc(title)}</b>",
            f"📺 <b>S{season:02d}E{episode:02d}</b>",
            f"🎯 <code>{quality}</code> · 🌍 <code>{langs}</code>",
            f"📦 {size}",
            "",
            f"💎 <i>ᴘʀᴇᴍɪᴜᴍ · ɴᴏ ᴇxᴘɪʀʏ</i>",
        ])

        fid = chosen_file.get("file_id")
        src_chat = chosen_file.get("chat_id")
        src_msg = chosen_file.get("message_id")
        fh = chosen_file.get("file_hit")
        if fh:
            if not src_chat: src_chat = getattr(fh, "chat_id", None)
            if not src_msg: src_msg = getattr(fh, "message_id", None) or \
                                       getattr(fh, "msg_id", None)
            if not fid: fid = getattr(fh, "file_id", "") or ""

        sent_msg = None
        if fid:
            try:
                sent_msg = await client.send_cached_media(
                    chat_id=uid, file_id=fid,
                    caption=file_caption, parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.debug(f"[PREM] direct cached: {e}")

        if not sent_msg and src_chat and src_msg:
            try:
                sent_msg = await client.copy_message(
                    chat_id=uid, from_chat_id=src_chat,
                    message_id=src_msg, caption=file_caption,
                    parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.debug(f"[PREM] direct copy: {e}")

        if not sent_msg:
            await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)
            return

        await _attach_watched_buttons(client, uid, sent_msg.id,
                                       slug, season, episode)
        await set_current_position(uid, slug, season, episode)
        await update_current_file_msg(uid, slug, sent_msg.id)

        # Update poster
        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] play_direct: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SEASON / SERIES COMPLETE NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════
async def _season_complete_notify(client: Client, uid: int,
                                    session: Dict[str, Any], season: int):
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        seasons_raw = session.get("seasons") or {}
        ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

        # Next season?
        next_season = None
        for sn in ordered:
            if sn > season:
                next_season = sn
                break

        if next_season:
            text = "\n".join([
                f"🎉 <b>{fb(f'SEASON {season} COMPLETE!')}</b>",
                DIV, "",
                f"🎬 <b>{_esc(title)}</b>",
                "",
                f"✅ Season {season:02d} done!",
                "",
                f"📌 Ready for Season {next_season}?",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"▶️ START S{next_season:02d}E01",
                    callback_data=f"pw:season:{slug}:{next_season}"
                )],
                [InlineKeyboardButton(
                    "🎬 ALL SEASONS",
                    callback_data=f"pw:seasons:{slug}"
                )],
            ])
        else:
            text = "\n".join([
                f"🎉 <b>{fb('SEASON COMPLETE!')}</b>",
                DIV, "",
                f"🎬 <b>{_esc(title)}</b>",
                f"✅ Season {season:02d} done!",
                "",
                f"📌 Almost done with the series!",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "▶️ CONTINUE",
                    callback_data=f"pw:poster:{slug}"
                )
            ]])

        await client.send_message(
            chat_id=uid, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"[PREM] season notify: {e}")


async def _series_complete_notify(client: Client, uid: int,
                                    session: Dict[str, Any]):
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        p = compute_progress(session)

        text = "\n".join([
            f"🎉🎉 <b>{fb('CONGRATULATIONS!')}</b> 🎉🎉",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            "",
            f"✅ <b>{fb('SERIES COMPLETE')}</b>",
            "",
            f"📁 <b>{p['total_watched']}/{p['total_eps']}</b> ᴇᴘɪꜱᴏᴅᴇꜱ",
            f"⏱️ ~{int(p['total_eps'] * 22 / 60)} ʜᴏᴜʀꜱ ᴡᴀᴛᴄʜᴇᴅ",
            "",
            DIV2,
            "",
            f"⭐ {sc('rate this series')}",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⭐ 1",
                                   callback_data=f"pw:rate:{slug}:1"),
             InlineKeyboardButton("⭐ 2",
                                   callback_data=f"pw:rate:{slug}:2"),
             InlineKeyboardButton("⭐ 3",
                                   callback_data=f"pw:rate:{slug}:3"),
             InlineKeyboardButton("⭐ 4",
                                   callback_data=f"pw:rate:{slug}:4"),
             InlineKeyboardButton("⭐ 5",
                                   callback_data=f"pw:rate:{slug}:5")],
            [InlineKeyboardButton(
                "🎬 WATCH ANOTHER",
                callback_data=f"pw:complete:{slug}"
            )],
        ])

        await client.send_message(
            chat_id=uid, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"[PREM] series notify: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# RATING
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:rate:([a-z0-9_]+):(\d)$"), group=-420,
)
async def cb_pw_rate(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        stars = int(q.matches[0].group(2))

        # Store rating (best effort)
        try:
            c = _get_db()
            if c is not None:
                await c["watch_ratings"].update_one(
                    {"user_id": uid, "series_slug": slug},
                    {"$set": {"user_id": uid, "series_slug": slug,
                              "rating": stars, "rated_at": time.time()}},
                    upsert=True,
                )
        except Exception:
            pass

        await q.answer(f"⭐ {stars}/5")
        try:
            await q.message.edit_text(
                q.message.text + f"\n\n✅ ᴛʜᴀɴᴋꜱ ꜰᴏʀ ʀᴀᴛɪɴɢ ({stars}⭐)",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[PREM] rate: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MARK SERIES COMPLETE (from poster)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:complete:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_complete(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        p = compute_progress(session)

        await mark_session_completed(uid, slug)

        await q.answer("🎉 ᴄᴏᴍᴘʟᴇᴛᴇᴅ")

        text = "\n".join([
            f"🎉 <b>{fb('SERIES COMPLETED!')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            "",
            f"📁 <b>{p['total_watched']}/{p['total_eps']}</b>",
            "",
            f"📌 {sc('session archived')}",
            f"📌 {sc('search in group to start new series')}",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📺 MY SESSIONS",
                                   callback_data="pw:my_sessions")],
            [InlineKeyboardButton("❌ CLOSE",
                                   callback_data="pw:close_session_list")],
        ])
        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await q.message.edit_text(
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception:
                pass

        logger.info(f"[PREM] series completed u={uid} s={slug}")
    except Exception as e:
        logger.exception(f"[PREM] complete: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PAUSE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:pause:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_pause(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        p = compute_progress(session)

        await q.answer("⏸️ ᴘᴀᴜꜱᴇᴅ")
        text = "\n".join([
            f"⏸️ <b>{fb('PAUSED')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            f"📊 {p['total_watched']}/{p['total_eps']}",
            "",
            f"📌 {sc('your progress is saved')}",
            f"📌 {sc('use /my to resume anytime')}",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ RESUME",
                                   callback_data=f"pw:poster:{slug}")],
            [InlineKeyboardButton("📺 MY SESSIONS",
                                   callback_data="pw:my_sessions")],
        ])
        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            await q.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"[PREM] pause: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# RESUME FROM SESSION LIST
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:resume:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_resume(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = session.get("series_title") or "?"
        year = session.get("year") or ""

        text = _build_poster_text(session, title, year)
        kb = _build_poster_kb(session, slug)

        try:
            await q.message.edit_text(
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception:
            await client.send_message(
                chat_id=q.message.chat.id, text=text,
                reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)

        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] resume: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CANCEL FROM POSTER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^pw:cancel:([A-Za-z0-9_-]+)$"), group=-420,
)
async def cb_pw_cancel(client, q):
    try:
        uid = q.from_user.id
        token = q.matches[0].group(1)
        _HANDOFFS.pop(token, None)
        _pw_clear(uid)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    except Exception:
        try: await q.answer("✅")
        except Exception: pass


logger.info("💎 PREMIUM WATCH — Part D loaded (PM session + watched tracking)")


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════ PART E — WATCH ORDER ══════════════════════════
# ═══════════════════════════════════════════════════════════════════════════

# Franchises and their correct watch order (title → ordered list of series/movies)
# Curated list — most popular franchises
FRANCHISES: Dict[str, Dict[str, Any]] = {
    "breaking_bad_universe": {
        "name": "Breaking Bad Universe",
        "items": [
            {"title": "Breaking Bad", "year": "2008", "type": "series"},
            {"title": "El Camino", "year": "2019", "type": "movie"},
            {"title": "Better Call Saul", "year": "2015", "type": "series"},
            {"title": "Slippin' Jimmy", "year": "2022", "type": "series"},
        ],
    },
    "mcu": {
        "name": "Marvel Cinematic Universe",
        "items": [
            {"title": "Iron Man", "year": "2008", "type": "movie"},
            {"title": "The Incredible Hulk", "year": "2008", "type": "movie"},
            {"title": "Iron Man 2", "year": "2010", "type": "movie"},
            {"title": "Thor", "year": "2011", "type": "movie"},
            {"title": "Captain America: The First Avenger", "year": "2011", "type": "movie"},
            {"title": "The Avengers", "year": "2012", "type": "movie"},
            {"title": "Iron Man 3", "year": "2013", "type": "movie"},
            {"title": "Thor: The Dark World", "year": "2013", "type": "movie"},
            {"title": "Captain America: The Winter Soldier", "year": "2014", "type": "movie"},
            {"title": "Guardians of the Galaxy", "year": "2014", "type": "movie"},
            {"title": "Avengers: Age of Ultron", "year": "2015", "type": "movie"},
            {"title": "Ant-Man", "year": "2015", "type": "movie"},
            {"title": "Captain America: Civil War", "year": "2016", "type": "movie"},
            {"title": "Doctor Strange", "year": "2016", "type": "movie"},
            {"title": "Guardians of the Galaxy Vol. 2", "year": "2017", "type": "movie"},
            {"title": "Spider-Man: Homecoming", "year": "2017", "type": "movie"},
            {"title": "Thor: Ragnarok", "year": "2017", "type": "movie"},
            {"title": "Black Panther", "year": "2018", "type": "movie"},
            {"title": "Avengers: Infinity War", "year": "2018", "type": "movie"},
            {"title": "Ant-Man and the Wasp", "year": "2018", "type": "movie"},
            {"title": "Captain Marvel", "year": "2019", "type": "movie"},
            {"title": "Avengers: Endgame", "year": "2019", "type": "movie"},
            {"title": "Spider-Man: Far From Home", "year": "2019", "type": "movie"},
        ],
    },
    "star_wars": {
        "name": "Star Wars (Skywalker Saga)",
        "items": [
            {"title": "Star Wars: Episode I - The Phantom Menace", "year": "1999", "type": "movie"},
            {"title": "Star Wars: Episode II - Attack of the Clones", "year": "2002", "type": "movie"},
            {"title": "Star Wars: The Clone Wars", "year": "2008", "type": "movie"},
            {"title": "Star Wars: Episode III - Revenge of the Sith", "year": "2005", "type": "movie"},
            {"title": "Solo: A Star Wars Story", "year": "2018", "type": "movie"},
            {"title": "Rogue One: A Star Wars Story", "year": "2016", "type": "movie"},
            {"title": "Star Wars: Episode IV - A New Hope", "year": "1977", "type": "movie"},
            {"title": "Star Wars: Episode V - The Empire Strikes Back", "year": "1980", "type": "movie"},
            {"title": "Star Wars: Episode VI - Return of the Jedi", "year": "1983", "type": "movie"},
            {"title": "Star Wars: Episode VII - The Force Awakens", "year": "2015", "type": "movie"},
            {"title": "Star Wars: Episode VIII - The Last Jedi", "year": "2017", "type": "movie"},
            {"title": "Star Wars: Episode IX - The Rise of Skywalker", "year": "2019", "type": "movie"},
        ],
    },
    "dc_universe": {
        "name": "DC Extended Universe",
        "items": [
            {"title": "Man of Steel", "year": "2013", "type": "movie"},
            {"title": "Batman v Superman: Dawn of Justice", "year": "2016", "type": "movie"},
            {"title": "Suicide Squad", "year": "2016", "type": "movie"},
            {"title": "Wonder Woman", "year": "2017", "type": "movie"},
            {"title": "Justice League", "year": "2017", "type": "movie"},
            {"title": "Aquaman", "year": "2018", "type": "movie"},
            {"title": "Shazam!", "year": "2019", "type": "movie"},
            {"title": "Birds of Prey", "year": "2020", "type": "movie"},
            {"title": "Wonder Woman 1984", "year": "2020", "type": "movie"},
            {"title": "The Suicide Squad", "year": "2021", "type": "movie"},
        ],
    },
    "the_boys_universe": {
        "name": "The Boys Universe",
        "items": [
            {"title": "The Boys", "year": "2019", "type": "series"},
            {"title": "The Boys Presents: Diabolical", "year": "2022", "type": "series"},
            {"title": "Gen V", "year": "2023", "type": "series"},
        ],
    },
    "monsterverse": {
        "name": "MonsterVerse",
        "items": [
            {"title": "Godzilla", "year": "2014", "type": "movie"},
            {"title": "Kong: Skull Island", "year": "2017", "type": "movie"},
            {"title": "Godzilla: King of the Monsters", "year": "2019", "type": "movie"},
            {"title": "Godzilla vs. Kong", "year": "2021", "type": "movie"},
            {"title": "Godzilla x Kong: The New Empire", "year": "2024", "type": "movie"},
        ],
    },
    "john_wick": {
        "name": "John Wick",
        "items": [
            {"title": "John Wick", "year": "2014", "type": "movie"},
            {"title": "John Wick: Chapter 2", "year": "2017", "type": "movie"},
            {"title": "John Wick: Chapter 3 - Parabellum", "year": "2019", "type": "movie"},
            {"title": "John Wick: Chapter 4", "year": "2023", "type": "movie"},
        ],
    },
    "fast_furious": {
        "name": "Fast & Furious",
        "items": [
            {"title": "The Fast and the Furious", "year": "2001", "type": "movie"},
            {"title": "2 Fast 2 Furious", "year": "2003", "type": "movie"},
            {"title": "The Fast and the Furious: Tokyo Drift", "year": "2006", "type": "movie"},
            {"title": "Fast & Furious", "year": "2009", "type": "movie"},
            {"title": "Fast Five", "year": "2011", "type": "movie"},
            {"title": "Fast & Furious 6", "year": "2013", "type": "movie"},
            {"title": "Furious 7", "year": "2015", "type": "movie"},
            {"title": "The Fate of the Furious", "year": "2017", "type": "movie"},
            {"title": "F9", "year": "2021", "type": "movie"},
            {"title": "Fast X", "year": "2023", "type": "movie"},
        ],
    },
    "lotr": {
        "name": "Middle-earth (LOTR + Hobbit)",
        "items": [
            {"title": "The Hobbit: An Unexpected Journey", "year": "2012", "type": "movie"},
            {"title": "The Hobbit: The Desolation of Smaug", "year": "2013", "type": "movie"},
            {"title": "The Hobbit: The Battle of the Five Armies", "year": "2014", "type": "movie"},
            {"title": "The Lord of the Rings: The Fellowship of the Ring", "year": "2001", "type": "movie"},
            {"title": "The Lord of the Rings: The Two Towers", "year": "2002", "type": "movie"},
            {"title": "The Lord of the Rings: The Return of the King", "year": "2003", "type": "movie"},
        ],
    },
    "harry_potter": {
        "name": "Harry Potter (Wizarding World)",
        "items": [
            {"title": "Harry Potter and the Sorcerer's Stone", "year": "2001", "type": "movie"},
            {"title": "Harry Potter and the Chamber of Secrets", "year": "2002", "type": "movie"},
            {"title": "Harry Potter and the Prisoner of Azkaban", "year": "2004", "type": "movie"},
            {"title": "Harry Potter and the Goblet of Fire", "year": "2005", "type": "movie"},
            {"title": "Harry Potter and the Order of the Phoenix", "year": "2007", "type": "movie"},
            {"title": "Harry Potter and the Half-Blood Prince", "year": "2009", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 1", "year": "2010", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 2", "year": "2011", "type": "movie"},
            {"title": "Fantastic Beasts and Where to Find Them", "year": "2016", "type": "movie"},
            {"title": "Fantastic Beasts: The Crimes of Grindelwald", "year": "2018", "type": "movie"},
            {"title": "Fantastic Beasts: The Secrets of Dumbledore", "year": "2022", "type": "movie"},
        ],
    },
    "mission_impossible": {
        "name": "Mission: Impossible",
        "items": [
            {"title": "Mission: Impossible", "year": "1996", "type": "movie"},
            {"title": "Mission: Impossible II", "year": "2000", "type": "movie"},
            {"title": "Mission: Impossible III", "year": "2006", "type": "movie"},
            {"title": "Mission: Impossible - Ghost Protocol", "year": "2011", "type": "movie"},
            {"title": "Mission: Impossible - Rogue Nation", "year": "2015", "type": "movie"},
            {"title": "Mission: Impossible - Fallout", "year": "2018", "type": "movie"},
            {"title": "Mission: Impossible - Dead Reckoning", "year": "2023", "type": "movie"},
        ],
    },
    "the_conjuring": {
        "name": "The Conjuring Universe",
        "items": [
            {"title": "The Conjuring", "year": "2013", "type": "movie"},
            {"title": "Annabelle", "year": "2014", "type": "movie"},
            {"title": "The Conjuring 2", "year": "2016", "type": "movie"},
            {"title": "Annabelle: Creation", "year": "2017", "type": "movie"},
            {"title": "The Nun", "year": "2018", "type": "movie"},
            {"title": "Annabelle Comes Home", "year": "2019", "type": "movie"},
            {"title": "The Conjuring: The Devil Made Me Do It", "year": "2021", "type": "movie"},
        ],
    },
    "pirates_caribbean": {
        "name": "Pirates of the Caribbean",
        "items": [
            {"title": "Pirates of the Caribbean: The Curse of the Black Pearl", "year": "2003", "type": "movie"},
            {"title": "Pirates of the Caribbean: Dead Man's Chest", "year": "2006", "type": "movie"},
            {"title": "Pirates of the Caribbean: At World's End", "year": "2007", "type": "movie"},
            {"title": "Pirates of the Caribbean: On Stranger Tides", "year": "2011", "type": "movie"},
            {"title": "Pirates of the Caribbean: Dead Men Tell No Tales", "year": "2017", "type": "movie"},
        ],
    },
    "planet_of_apes": {
        "name": "Planet of the Apes",
        "items": [
            {"title": "Rise of the Planet of the Apes", "year": "2011", "type": "movie"},
            {"title": "Dawn of the Planet of the Apes", "year": "2014", "type": "movie"},
            {"title": "War for the Planet of the Apes", "year": "2017", "type": "movie"},
            {"title": "Kingdom of the Planet of the Apes", "year": "2024", "type": "movie"},
        ],
    },
}


def _find_franchise_by_title(title: str) -> Optional[Dict[str, Any]]:
    """Given a series/movie title, find which franchise it belongs to."""
    if not title: return None
    t_lower = title.lower().strip()

    for fkey, fdata in FRANCHISES.items():
        for item in fdata.get("items") or []:
            item_title = (item.get("title") or "").lower().strip()
            # Exact or partial match
            if item_title == t_lower:
                return {"key": fkey, **fdata}
            if t_lower in item_title or item_title in t_lower:
                if len(t_lower) > 4:
                    return {"key": fkey, **fdata}
    return None


async def _check_local_availability(title: str) -> Dict[str, Any]:
    """Check if a title is available in local DB + get progress."""
    try:
        from plugins.series_group import _engine_search
        hits = await _engine_search(title)
        return {
            "available": bool(hits),
            "count": len(hits),
            "hits": hits,
        }
    except Exception as e:
        logger.debug(f"[PREM] check local: {e}")
        return {"available": False, "count": 0, "hits": []}


async def _build_watch_order_view(uid: int, franchise: Dict[str, Any],
                                    slug: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Build the watch order view with progress markers."""
    items = franchise.get("items") or []
    fname = franchise.get("name") or "?"

    lines = [
        f"🎬 <b>{fb('WATCH ORDER')}</b>",
        f"🎞️ <b>{_esc(fname)}</b>",
        DIV, "",
        f"📖 {sc('recommended order')}:",
        "",
    ]

    rows = []
    for i, item in enumerate(items, 1):
        title = item.get("title") or "?"
        year = item.get("year") or ""
        itype = item.get("type") or "series"

        # Check if user has a session for this
        item_slug = _slug(title)
        session = await get_session(uid, item_slug)

        if session:
            p = compute_progress(session)
            if p["total_eps"] > 0 and p["total_watched"] >= p["total_eps"]:
                icon = "✅"
                progress_str = "COMPLETE"
            else:
                icon = "🟡"
                progress_str = f"{p['total_watched']}/{p['total_eps']}"
        else:
            icon = "⚪"
            progress_str = "Not started"

        type_icon = "🎬" if itype == "movie" else "📺"
        lines.append(
            f"<b>{i}.</b> {icon} {type_icon} <b>{_esc(title)}</b> "
            f"<code>({year})</code>"
        )
        lines.append(f"   <i>{progress_str}</i>")

        # Button to open this item
        rows.append([InlineKeyboardButton(
            f"{icon} {i}. {title[:32]}",
            callback_data=f"pw:wo_open:{slug}:{i-1}"
        )])

    rows.append([InlineKeyboardButton(
        "◀️ BACK TO POSTER",
        callback_data=f"pw:poster:{slug}"
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


@Client.on_callback_query(
    filters.regex(r"^pw:wo:([A-Za-z0-9_-]+)$"), group=-420,
)
async def cb_pw_watch_order(client, q):
    """Show watch order for the franchise this series belongs to."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        token_or_slug = q.matches[0].group(1)

        # If it's a handoff token, get from handoff; else treat as slug
        session = None
        title = ""

        handoff = _get_handoff(token_or_slug)
        if handoff:
            title = (handoff.get("data") or {}).get("title") or ""
        else:
            session = await get_session(uid, token_or_slug)
            if session:
                title = session.get("series_title") or ""

        if not title:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        # Find franchise
        franchise = _find_franchise_by_title(title)
        if not franchise:
            return await q.answer(
                "ℹ️ ɴᴏ ᴡᴀᴛᴄʜ ᴏʀᴅᴇʀ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʀɪᴇꜱ",
                show_alert=True
            )

        text, kb = await _build_watch_order_view(
            uid, franchise, token_or_slug
        )

        try:
            await q.message.edit_caption(
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
        except Exception:
            try:
                await q.message.edit_text(
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception:
                pass

        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] wo: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:wo_open:([A-Za-z0-9_-]+):(\d+)$"), group=-420,
)
async def cb_pw_wo_open(client, q):
    """Open a specific item from the watch order list."""
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("💎 ᴘʀᴇᴍɪᴜᴍ ᴏɴʟʏ", show_alert=True)

        token_or_slug = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))

        # Get current title from handoff or session
        title = ""
        handoff = _get_handoff(token_or_slug)
        if handoff:
            title = (handoff.get("data") or {}).get("title") or ""
        else:
            session = await get_session(uid, token_or_slug)
            if session:
                title = session.get("series_title") or ""

        if not title:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        franchise = _find_franchise_by_title(title)
        if not franchise:
            return await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)

        items = franchise.get("items") or []
        if idx < 0 or idx >= len(items):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        item = items[idx]
        item_title = item.get("title") or ""
        item_year = item.get("year") or ""
        item_type = item.get("type") or "series"

        await q.answer(f"🔍 {item_title}")

        # Check local availability
        loc = await _check_local_availability(item_title)

        if not loc.get("available"):
            text = "\n".join([
                f"🎬 <b>{_esc(item_title)}</b> ({item_year})",
                DIV, "",
                f"❌ {sc('not in library yet')}",
                "",
                f"📌 {sc('contact admin to request')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "◀️ BACK",
                    callback_data=f"pw:wo:{token_or_slug}"
                )],
            ])
            try:
                await q.message.edit_caption(
                    caption=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await q.message.edit_text(
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True)
                except Exception:
                    pass
            return

        # If series and available, start a session
        if item_type == "series":
            # Create handoff and mimic the lang flow
            # Get TMDB info
            tmdb_id = None
            poster = None
            tmdb_seasons = []
            try:
                from plugins.series_group import (
                    _tmdb_search_series, _tmdb_series_details, _tmdb_seasons
                )
                suggestions = await _tmdb_search_series(item_title)
                if suggestions:
                    tmdb_id = suggestions[0].get("tmdb_id")
                    poster = suggestions[0].get("poster")
                    if tmdb_id:
                        details = await _tmdb_series_details(tmdb_id)
                        if details:
                            tmdb_seasons = _tmdb_seasons(details)
            except Exception as e:
                logger.debug(f"[PREM] wo tmdb: {e}")

            series_data = {
                "title": item_title,
                "tmdb_id": tmdb_id,
                "poster": poster,
                "year": item_year,
                "rating": 0,
                "tmdb_seasons": tmdb_seasons,
                "hits": loc.get("hits") or [],
                "search_query": item_title,
            }
            token = _new_handoff(uid, series_data)
            await _prepare_pm_session(client, uid, token, series_data)

            await q.answer("📩 ꜱᴇɴᴛ ᴛᴏ ᴘᴍ!", show_alert=True)
        else:
            # Movie — just show info
            text = "\n".join([
                f"🎬 <b>{_esc(item_title)}</b> ({item_year})",
                DIV, "",
                f"✅ {sc('available in library')}",
                f"📁 <code>{loc['count']}</code> ꜰɪʟᴇꜱ",
                "",
                f"📌 {sc('search in group to get this movie')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "◀️ BACK",
                    callback_data=f"pw:wo:{token_or_slug}"
                )],
            ])
            try:
                await q.message.edit_caption(
                    caption=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML)
            except Exception:
                try:
                    await q.message.edit_text(
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True)
                except Exception:
                    pass
    except Exception as e:
        logger.exception(f"[PREM] wo_open: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN: LIST FRANCHISES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^pw:franchises$"), group=-426)
async def cb_pw_franchises(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🎬 <b>{fb('FRANCHISES')}</b> · <code>{len(FRANCHISES)}</code>",
            DIV, "",
        ]
        for fkey, fdata in FRANCHISES.items():
            count = len(fdata.get("items") or [])
            lines.append(f"• <b>{_esc(fdata.get('name'))}</b> · "
                          f"<code>{count}</code> items")
        await _pw_safe_edit(q, "\n".join(lines), kb_pw_back())
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] franchises: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FINAL BOOT — make sure all loops start
# ═══════════════════════════════════════════════════════════════════════════
_PW_FINAL_BOOTED = False


@Client.on_message(filters.private, group=-419)
async def _pw_final_boot(client, message):
    global _PW_FINAL_BOOTED
    if _PW_FINAL_BOOTED:
        return
    _PW_FINAL_BOOTED = True
    try:
        logger.info("[PREM] final boot — all parts loaded")
    except Exception:
        pass


logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  💎 PREMIUM WATCH COMPANION v1 — LOADED ✅                     ║")
logger.info("║                                                                ║")
logger.info("║  📦 Parts A-E all loaded                                       ║")
logger.info("║  🎛️ Panel: /seriesgroupsettings                                ║")
logger.info("║  💎 Premium detection + redirect                                ║")
logger.info("║  🎬 Watch sessions + progress tracking                          ║")
logger.info("║  🔔 Expiry reminders (10d/5d/1d/expired)                        ║")
logger.info("║  🎞️ Watch Order Assistant for franchises                        ║")
logger.info("║  🧹 Auto-cleanup after 30d grace / 180d inactive                ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
