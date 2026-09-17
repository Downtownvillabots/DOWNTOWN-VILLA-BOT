# plugins/premium_watch.py
"""
💎 PREMIUM WATCH COMPANION v2
Auto-redirect premium users from group → PM
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

GRACE_PERIOD_DAYS = 30
INACTIVITY_DAYS = 180
REMINDER_HOUR = 10

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
                if days_since <= 2 and not await was_reminder_sent(uid, "expired"):
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
        await asyncio.sleep(6 * 3600)


async def _cleanup_inactive_sessions():
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
    c = _sessions_coll()
    p = _premium_coll()
    if c is None or p is None: return
    try:
        now = time.time()
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
# BOOT
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


logger.info("💎 PREMIUM WATCH — Part 1 loaded")


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN SESSIONS (input flows)
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
def kb_pw_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 PREMIUM MEMBERS",
                               callback_data="pw:members")],
        [InlineKeyboardButton("➕ ADD PREMIUM USER",
                               callback_data="pw:add"),
         InlineKeyboardButton("🔍 FIND USER",
                               callback_data="pw:find")],
        [InlineKeyboardButton("⏰ EXPIRING SOON",
                               callback_data="pw:expiring"),
         InlineKeyboardButton("❌ EXPIRED",
                               callback_data="pw:expired")],
        [InlineKeyboardButton("👤 SET CONTACT ADMIN",
                               callback_data="pw:contact"),
         InlineKeyboardButton("📊 STATS",
                               callback_data="pw:stats")],
        [InlineKeyboardButton("🔄 REFRESH",
                               callback_data="pw:main"),
         InlineKeyboardButton("❌ CLOSE",
                               callback_data="pw:close")],
    ])


def kb_pw_back(target: str = "pw:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="pw:close")]])


def kb_pw_plan_picker(user_id: int, username: str):
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

    return text, kb_pw_main()


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

        lines.append(f"<b>{i}.</b> @{_esc(str(uname).lstrip('@'))}")
        lines.append(f"   {status} · {plan}ᴍᴏ · <code>{uid}</code>")
        lines.append("")

    rows = []
    for i, u in enumerate(page_users[:6], start=start + 1):
        uname = (u.get("username") or str(u.get("user_id")))[:20]
        rows.append([InlineKeyboardButton(
            f"⚙️ {i}. @{uname}",
            callback_data=f"pw:member:{u['user_id']}"
        )])

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
            lines.append(f"{icon} @{_esc(str(uname).lstrip('@'))}")
            lines.append(f"   {days}ᴅ · {_date_ist(expires)} · "
                          f"<code>{u.get('user_id')}</code>")
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
            lines.append(f"❌ @{_esc(str(uname).lstrip('@'))}")
            lines.append(f"   {days_ago}ᴅ ᴀɢᴏ · {grace_icon} "
                          f"{max(0, grace_days)}ᴅ ɢʀᴀᴄᴇ · "
                          f"<code>{u.get('user_id')}</code>")
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_stats() -> Tuple[str, InlineKeyboardMarkup]:
    stats = await count_premium_users()
    sessions = await count_sessions()

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


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN TEXT INPUT HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^pw:"),
    group=-425,
)
async def pw_admin_input(client, message):
    if not message.from_user:
        return
    if not _is_admin(message.from_user.id):
        return

    s = _get_admin_session(message.from_user.id)
    if not s:
        return

    action = s.get("action")
    if action not in ("add_premium_user", "find_user", "edit_notes",
                      "set_contact"):
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
        return

    if action == "find_user":
        await _handle_find_user_input(client, message, text)
        return

    if action == "edit_notes":
        await _handle_edit_notes_input(client, message, text, s)
        return

    if action == "set_contact":
        await _handle_set_contact_input(client, message, text)
        return


async def _handle_add_user_input(client, message, text: str):
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
                username = f"@{u.username}" if u.username else f"ID {u.id}"
            except Exception as e:
                _clear_admin_session(message.from_user.id)
                return await message.reply_text(
                    f"❌ ᴄᴏᴜʟᴅ ɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ <code>{_esc(text)}</code>\n"
                    f"<i>{_esc(str(e))[:100]}</i>",
                    parse_mode=ParseMode.HTML)
    else:
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

    _new_admin_session(message.from_user.id, "pick_plan",
                       target_uid=uid_target,
                       target_username=username)

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


async def _handle_set_contact_input(client, message, text: str):
    _clear_admin_session(message.from_user.id)
    if not re.match(r"^@\w+$", text):
        return await message.reply_text(
            "❌ ꜰᴏʀᴍᴀᴛ: @ᴜꜱᴇʀɴᴀᴍᴇ")
    ok = await set_setting("contact_admin", text)
    if ok:
        await message.reply_text(
            f"✅ ᴄᴏɴᴛᴀᴄᴛ ꜱᴀᴠᴇᴅ: <code>{_esc(text)}</code>",
            reply_markup=kb_pw_back(),
            parse_mode=ParseMode.HTML)
    else:
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
                    f"🎬 {sc('start watching')} · "
                    f"ꜱᴇᴀʀᴄʜ ᴀ ꜱᴇʀɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ",
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
        await _pw_safe_edit(q, text,
                             kb_pw_plan_picker(target_uid,
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
            f"📝 {sc('send notes')}",
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
# ⭐⭐⭐ GROUP SEARCH HOOK — AUTO-REDIRECT TO PM ⭐⭐⭐
# ═══════════════════════════════════════════════════════════════════════════
async def handle_premium_group_search(client: Client, message,
                                       status_msg,
                                       query: str,
                                       db_result: Optional[Dict[str, Any]],
                                       tmdb_results: List[Dict[str, Any]]
                                       ) -> bool:
    """
    Called from series_group.py when a premium user searches.

    Returns True if handled (redirect flow triggered).
    Returns False if caller should run normal flow.

    Parameters:
      status_msg   — the "searching..." message to delete
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
            ok = await _premium_redirect_to_pm(
                client, message, status_msg, uid, matched_title,
                db_result.get("hits") or [],
                tmdb_results
            )
            return ok

        # Case 2: No DB match — show suggestions as normal
        return False
    except Exception as e:
        logger.exception(f"[PREM] group search hook: {e}")
        return False


async def _premium_redirect_to_pm(client: Client, message,
                                    status_msg,
                                    uid: int, title: str,
                                    hits: List[Dict[str, Any]],
                                    tmdb_results: List[Dict[str, Any]]
                                    ) -> bool:
    """
    Directly send poster to user's PM.
    Shows a small "check PM" card in the group, then deletes it
    after a short delay (to keep the group clean).
    """
    try:
        # Find best TMDB entry
        tmdb_id = None
        poster = None
        year = ""
        rating = 0
        display_title = title

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
                from plugins.series_group import (
                    _tmdb_series_details, _tmdb_seasons
                )
                details = await _tmdb_series_details(tmdb_id)
                if details:
                    tmdb_seasons = _tmdb_seasons(details)
            except Exception as e:
                logger.debug(f"[PREM] tmdb details: {e}")

        # Build the series_data payload
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

        # Delete the group status message
        try:
            if status_msg:
                await status_msg.delete()
        except Exception:
            pass

        # Delete the user's original search message
        try:
            await message.delete()
        except Exception:
            pass

        # Send small notice in group
        group_text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"💎 <b>{fb('PREMIUM')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(display_title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            "",
            DIV2, "",
            f"📩 {sc('sent to your pm')}",
            f"🚀 {sc('open the bot to start watching')}",
        ])

        try:
            await client.send_message(
                chat_id=message.chat.id,
                text="\n".join(line for line in group_text.split("\n")
                                if line),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[PREM] group reply: {e}")

        logger.info(f"[PREM] redirect user={uid} title={display_title!r}")

        # ⭐ SEND POSTER DIRECTLY TO PM ⭐
        await _prepare_pm_session(client, uid, series_data)

        return True
    except Exception as e:
        logger.exception(f"[PREM] redirect: {e}")
        return False


async def _prepare_pm_session(client: Client, uid: int,
                               series_data: Dict[str, Any]):
    """Send the poster to the user's PM (persistent message)."""
    try:
        title = series_data.get("title") or "?"
        year = series_data.get("year") or ""
        rating = series_data.get("rating", 0)
        tmdb_seasons = series_data.get("tmdb_seasons") or []
        poster_path = series_data.get("poster")
        hits = series_data.get("hits") or []

        poster_url = None
        if poster_path:
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"

        total_eps = sum(s.get("episodes", 0) for s in tmdb_seasons)
        seasons_count = len(tmdb_seasons)

        # Check if session already exists
        slug = _slug(title)
        existing = await get_session(uid, slug)

        # Body text
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

        # Compute available languages
        langs = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]
        try:
            available_langs = set()
            for h in hits[:50]:
                for lang in (h.get("languages") or []):
                    if lang: available_langs.add(lang)
        except Exception:
            available_langs = set()

        if available_langs:
            ordered = [l for l in langs if l in available_langs]
            extra = [l for l in available_langs if l not in ordered]
            langs = (ordered + extra)[:5]

        if not langs:
            langs = ["English"]

        # Keyboard — language buttons
        kb_rows = []
        row = []
        for i, lang in enumerate(langs[:6]):
            row.append(InlineKeyboardButton(
                f"🌍 {lang}",
                callback_data=f"pw:lang:{slug}:{i}"
            ))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        kb_rows.append([InlineKeyboardButton(
            "🎬 WATCH ORDER",
            callback_data=f"pw:wo:{slug}"
        )])
        kb_rows.append([InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"pw:cancel:{slug}"
        )])

        kb = InlineKeyboardMarkup(kb_rows)

        # Send poster
        msg = None
        if poster_url:
            try:
                msg = await client.send_photo(
                    chat_id=uid, photo=poster_url,
                    caption=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] send_photo failed: {e}")

        if not msg:
            msg = await client.send_message(
                chat_id=uid, text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

        # Save/update session with poster info + languages cache
        c = _sessions_coll()
        if c is not None:
            await c.update_one(
                {"user_id": uid, "series_slug": slug},
                {"$set": {
                    "user_id": uid,
                    "series_slug": slug,
                    "series_title": title,
                    "poster": poster_path,
                    "year": year,
                    "tmdb_id": series_data.get("tmdb_id"),
                    "tmdb_seasons": tmdb_seasons,
                    "hits": hits,
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
                 }},
                upsert=True,
            )

        logger.info(f"[PREM] PM poster sent to {uid} msg={msg.id}")

    except Exception as e:
        logger.exception(f"[PREM] prepare PM: {e}")


logger.info("💎 PREMIUM WATCH — Part 2 loaded")

💎 PREMIUM WATCH — Part 1 loaded
💎 PREMIUM WATCH — Part 2 loaded
💎 PREMIUM WATCH — Part 3 loaded
╔════════════════════════════════════════════════════════════════╗
║  💎 PREMIUM WATCH COMPANION v2 — LOADED ✅                     ║
╚════════════════════════════════════════════════════════════════╝
