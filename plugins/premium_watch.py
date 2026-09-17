# plugins/premium_watch.py
"""
PREMIUM WATCH COMPANION v2
Auto-redirect premium users from group to PM
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

DIV = "-" * 26
DIV2 = "_" * 26


_M_BOLD = {
    **{chr(ord('A') + i): "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[i] for i in range(26)},
    **{chr(ord('a') + i): "abcdefghijklmnopqrstuvwxyz"[i] for i in range(26)},
    **{chr(ord('0') + i): "0123456789"[i] for i in range(10)},
}
_M_SC = {c: c for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"}


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
    return datetime.now(IST).strftime("%d %b %Y %H:%M IST")


def _date_ist(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
    except Exception:
        return "?"


def _slug(s: str) -> str:
    if not s: return ""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _get_db():
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                d = fn()
                if d is not None: return d
    except Exception:
        pass
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
    except Exception:
        return None


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
    except Exception:
        return False


async def list_premium_users(limit: int = 500) -> List[Dict[str, Any]]:
    c = _premium_coll()
    if c is None: return []
    try:
        return await c.find({}).sort("expires_at", 1).to_list(limit)
    except Exception:
        return []


async def count_premium_users() -> Dict[str, int]:
    empty = {"active": 0, "expiring_10d": 0,
             "expiring_5d": 0, "expiring_1d": 0, "expired": 0}
    c = _premium_coll()
    if c is None: return empty
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
        return empty


async def mark_reminder_sent(user_id: int, reminder: str) -> bool:
    c = _premium_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$addToSet": {"reminders_sent": reminder}}
        )
        return True
    except Exception:
        return False


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
    except Exception:
        return None


async def get_session(user_id: int,
                       series_slug: str) -> Optional[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None: return None
    try:
        return await c.find_one({"user_id": int(user_id),
                                  "series_slug": series_slug})
    except Exception:
        return None


async def list_user_sessions(user_id: int) -> List[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None: return []
    try:
        return await c.find({"user_id": int(user_id),
                              "status": "watching"}
                             ).sort("last_activity_at", -1).to_list(50)
    except Exception:
        return []


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
    except Exception:
        return False


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
    except Exception:
        return False


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
    except Exception:
        return False


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
    except Exception:
        return False


async def count_sessions() -> int:
    c = _sessions_coll()
    if c is None: return 0
    try:
        return await c.count_documents({"status": "watching"})
    except Exception:
        return 0


logger.info("[PREM] Part 1 loaded")


async def get_setting(key: str, default=None):
    c = _settings_coll()
    if c is None: return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception:
        return default


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
    except Exception:
        return False


async def get_contact_admin() -> str:
    return await get_setting("contact_admin", "") or ""


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
    return "#" * filled + "." * (width - filled)


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
            f"{title}\n"
            f"  {bar} {p['total_watched']}/{p['total_eps']}"
        )
    series_block = "\n".join(series_lines) if series_lines else "No active series"

    if kind == "10d":
        header = "<b>PREMIUM EXPIRING SOON</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium expires in:\n"
                f"<b>{exp_date}</b> (10 days)")
        footer = f"To renew, contact: <b>{_esc(contact)}</b>"
    elif kind == "5d":
        header = "<b>PREMIUM EXPIRING IN 5 DAYS</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your plan ends: <b>{exp_date}</b>\n\n"
                f"If you don't renew, you'll lose:\n"
                f"  x Watch progress tracking\n"
                f"  x Watch Order Assistant\n"
                f"  x New episode deliveries\n\n"
                f"<i>Already delivered files are yours to keep forever.</i>")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."
    elif kind == "1d":
        header = "<b>LAST DAY OF PREMIUM</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium expires <b>tomorrow</b> ({exp_date})\n\n"
                f"Progress will be saved for 30 days after expiry.\n"
                f"After 30 days, tracking is removed - files stay with you.")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."
    else:
        header = "<b>PREMIUM EXPIRED</b>"
        body = (f"Hi {_esc(username)}!\n\n"
                f"Your premium membership ended today.\n\n"
                f"Files you received: yours to keep forever\n"
                f"Progress tracking: paused\n"
                f"Watch companion: disabled\n\n"
                f"Progress will be DELETED in 30 days if not renewed.")
        footer = f"Contact <b>{_esc(contact)}</b> to renew."

    text = "\n".join([
        f"<b>DOWNTOWN VILLA</b>",
        header,
        DIV, "",
        body, "",
        DIV2,
        f"<b>YOUR ACTIVE SERIES</b>",
        series_block,
        "", DIV2,
        footer,
    ])

    kb_rows = []
    if contact and contact.startswith("@"):
        kb_rows.append([InlineKeyboardButton(
            "MESSAGE ADMIN",
            url=f"https://t.me/{contact.lstrip('@')}"
        )])
    if kind != "expired":
        kb_rows.append([InlineKeyboardButton(
            "CONTINUE WATCHING", callback_data="pw:my_sessions"
        )])
    kb_rows.append([InlineKeyboardButton(
        "DISMISS", callback_data="pw:dismiss_reminder"
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
        "<b>PREMIUM DAILY REPORT</b>",
        DIV, "",
        f"<code>{_now_ist()}</code>",
        "",
        f"Active - <code>{stats['active']}</code>",
        f"Expiring 10d - <code>{stats['expiring_10d']}</code>",
        f"Expiring 5d - <code>{stats['expiring_5d']}</code>",
        f"Expiring 1d - <code>{stats['expiring_1d']}</code>",
        f"Expired - <code>{stats['expired']}</code>",
        "",
        f"Active sessions - <code>{sessions}</code>",
    ]
    if exp_1d:
        lines += ["", DIV2, "Expiring tomorrow:"]
        for u in exp_1d[:10]:
            lines.append(f"  {_esc(u)}")

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
            logger.info(f"[PREM] cleanup: {r.deleted_count} inactive")
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
            logger.info(f"[PREM] cleanup: {r.deleted_count} expired sessions")
    except Exception as e:
        logger.warning(f"[PREM] cleanup expired: {e}")


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


def kb_pw_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PREMIUM MEMBERS",
                               callback_data="pw:members")],
        [InlineKeyboardButton("ADD PREMIUM USER",
                               callback_data="pw:add"),
         InlineKeyboardButton("FIND USER",
                               callback_data="pw:find")],
        [InlineKeyboardButton("EXPIRING SOON",
                               callback_data="pw:expiring"),
         InlineKeyboardButton("EXPIRED",
                               callback_data="pw:expired")],
        [InlineKeyboardButton("SET CONTACT ADMIN",
                               callback_data="pw:contact"),
         InlineKeyboardButton("STATS",
                               callback_data="pw:stats")],
        [InlineKeyboardButton("REFRESH",
                               callback_data="pw:main"),
         InlineKeyboardButton("CLOSE",
                               callback_data="pw:close")],
    ])


def kb_pw_back(target: str = "pw:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("BACK", callback_data=target),
        InlineKeyboardButton("CLOSE", callback_data="pw:close")]])


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
        "CANCEL", callback_data="pw:add")])
    return InlineKeyboardMarkup(rows)


def kb_pw_member_actions(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("EXTEND",
                               callback_data=f"pw:extend:{user_id}"),
         InlineKeyboardButton("REMOVE",
                               callback_data=f"pw:remove:{user_id}")],
        [InlineKeyboardButton("EDIT NOTES",
                               callback_data=f"pw:notes:{user_id}")],
        [InlineKeyboardButton("BACK TO LIST",
                               callback_data="pw:members"),
         InlineKeyboardButton("CLOSE",
                               callback_data="pw:close")],
    ])


async def _view_pw_main() -> Tuple[str, InlineKeyboardMarkup]:
    stats = await count_premium_users()
    sessions = await count_sessions()
    contact = await get_contact_admin() or "-"

    text = "\n".join([
        "<b>DOWNTOWN VILLA</b>",
        "<b>PREMIUM MANAGEMENT</b>",
        DIV, "",
        f"Active - <code>{stats['active']}</code>",
        f"Expiring 10d - <code>{stats['expiring_10d']}</code>",
        f"Expiring 5d - <code>{stats['expiring_5d']}</code>",
        f"Expiring 1d - <code>{stats['expiring_1d']}</code>",
        f"Expired - <code>{stats['expired']}</code>",
        "",
        f"Active sessions - <code>{sessions}</code>",
        "", DIV2, "",
        f"Contact admin - <code>{_esc(contact)}</code>",
        "",
        f"<code>{_now_ist()}</code>",
    ])

    return text, kb_pw_main()


logger.info("[PREM] Part 2 loaded")


async def _view_pw_members(page: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    users = await list_premium_users(500)
    if not users:
        text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>PREMIUM MEMBERS</b>",
            DIV, "",
            "No premium users yet.",
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
        "<b>DOWNTOWN VILLA</b>",
        f"<b>PREMIUM MEMBERS</b> - <code>{total}</code>",
        DIV, "",
    ]

    for i, u in enumerate(page_users, start=start + 1):
        uid = u.get("user_id")
        uname = u.get("username") or f"ID {uid}"
        expires = u.get("expires_at", 0)
        days = int((expires - now) / 86400) if expires else 0
        plan = u.get("plan_months", 0)

        if expires <= now:
            status = "EXPIRED"
        elif days <= 1:
            status = f"RED {days}d"
        elif days <= 5:
            status = f"YELLOW {days}d"
        elif days <= 10:
            status = f"ORANGE {days}d"
        else:
            status = f"GREEN {days}d"

        lines.append(f"<b>{i}.</b> @{_esc(str(uname).lstrip('@'))}")
        lines.append(f"   {status} - {plan}mo - <code>{uid}</code>")
        lines.append("")

    rows = []
    for i, u in enumerate(page_users[:6], start=start + 1):
        uname = (u.get("username") or str(u.get("user_id")))[:20]
        rows.append([InlineKeyboardButton(
            f"{i}. @{uname}",
            callback_data=f"pw:member:{u['user_id']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("PREV",
                                         callback_data=f"pw:members_p:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("NEXT",
                                         callback_data=f"pw:members_p:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton("ADD USER",
                                       callback_data="pw:add"),
                 InlineKeyboardButton("FIND",
                                       callback_data="pw:find")])
    rows.append([InlineKeyboardButton("BACK",
                                       callback_data="pw:main"),
                 InlineKeyboardButton("CLOSE",
                                       callback_data="pw:close")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _view_pw_member_detail(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    u = await get_premium_user(user_id)
    if not u:
        return ("User not found.",
                kb_pw_back("pw:members"))

    uid = u.get("user_id")
    uname = u.get("username") or f"ID {uid}"
    expires = u.get("expires_at", 0)
    plan = u.get("plan_months", 0)
    added = u.get("added_at", 0)
    added_by = u.get("added_by", 0)
    notes = u.get("notes") or "-"
    now = time.time()
    days_left = int((expires - now) / 86400)

    sessions = await list_user_sessions(uid)
    session_lines = []
    for s in sessions[:5]:
        title = s.get("series_title") or "?"
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        session_lines.append(
            f"  {title}\n"
            f"    {bar} {p['total_watched']}/{p['total_eps']}"
        )
    sessions_block = "\n".join(session_lines) if session_lines else "  None"

    text = "\n".join([
        "<b>DOWNTOWN VILLA</b>",
        "<b>PREMIUM USER</b>",
        DIV, "",
        f"ID: <code>{uid}</code>",
        f"Username: @{_esc(str(uname).lstrip('@'))}",
        "",
        f"Plan - <code>{plan} months</code>",
        f"Added - <code>{_date_ist(added)}</code>",
        f"By - <code>{added_by}</code>",
        f"Expires - <code>{_date_ist(expires)}</code>",
        f"Days left - <code>{days_left}</code>",
        "",
        f"Notes - <i>{_esc(notes)}</i>",
        "", DIV2, "",
        f"<b>ACTIVE SESSIONS</b>",
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
        "<b>DOWNTOWN VILLA</b>",
        f"<b>EXPIRING SOON</b> - <code>{len(expiring)}</code>",
        DIV, "",
    ]

    if not expiring:
        lines.append("None expiring soon.")
    else:
        expiring.sort(key=lambda u: u.get("expires_at", 0))
        for u in expiring:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days = int((expires - now) / 86400)
            icon = "RED" if days <= 1 else ("YELLOW" if days <= 5 else "ORANGE")
            lines.append(f"{icon} @{_esc(str(uname).lstrip('@'))}")
            lines.append(f"   {days}d - {_date_ist(expires)} - "
                          f"<code>{u.get('user_id')}</code>")
            lines.append("")

    return "\n".join(lines), kb_pw_back()


async def _view_pw_expired() -> Tuple[str, InlineKeyboardMarkup]:
    users = await list_premium_users(500)
    now = time.time()
    expired = [u for u in users if u.get("expires_at", 0) <= now]

    lines = [
        "<b>DOWNTOWN VILLA</b>",
        f"<b>EXPIRED USERS</b> - <code>{len(expired)}</code>",
        DIV, "",
    ]

    if not expired:
        lines.append("No expired users.")
    else:
        expired.sort(key=lambda u: u.get("expires_at", 0), reverse=True)
        for u in expired[:20]:
            uname = u.get("username") or f"ID {u.get('user_id')}"
            expires = u.get("expires_at", 0)
            days_ago = int((now - expires) / 86400)
            grace_end = expires + (GRACE_PERIOD_DAYS * 86400)
            grace_days = int((grace_end - now) / 86400)
            grace_icon = "DELETE" if grace_days <= 0 else "KEEP"
            lines.append(f"X @{_esc(str(uname).lstrip('@'))}")
            lines.append(f"   {days_ago}d ago - {grace_icon} "
                          f"{max(0, grace_days)}d grace - "
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

    avg_plan = round(total_months / total_users, 1) if total_users else 0

    text = "\n".join([
        "<b>DOWNTOWN VILLA</b>",
        "<b>PREMIUM STATS</b>",
        DIV, "",
        f"Active members - <code>{stats['active']}</code>",
        f"Expired - <code>{stats['expired']}</code>",
        f"Watch sessions - <code>{sessions}</code>",
        "", DIV2, "",
        f"Expiring 10d - <code>{stats['expiring_10d']}</code>",
        f"Expiring 5d - <code>{stats['expiring_5d']}</code>",
        f"Expiring 1d - <code>{stats['expiring_1d']}</code>",
        "", DIV2, "",
        f"Total months sold - <code>{total_months}</code>",
        f"Avg plan - <code>{avg_plan}mo</code>",
        "", DIV2,
        f"<code>{_now_ist()}</code>",
    ])

    return text, kb_pw_back()


async def _view_pw_find() -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        "<b>DOWNTOWN VILLA</b>",
        "<b>FIND PREMIUM USER</b>",
        DIV, "",
        "Send user id or @username",
        "",
        "Examples:",
        "<code>123456789</code>",
        "<code>@john</code>",
    ])
    return text, kb_pw_back()


@Client.on_message(
    filters.command(["seriesgroupsettings", "premium", "pw"]) & filters.private,
    group=-426,
)
async def cmd_pw_main(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("Admins only.")
    try:
        _clear_admin_session(message.from_user.id)
        text, kb = await _view_pw_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[PREM] /seriesgroupsettings: {e}")


@Client.on_callback_query(filters.regex(r"^pw:main$"), group=-426)
async def cb_pw_main(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
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
        return await q.answer("X", show_alert=True)
    try:
        _clear_admin_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("Closed")
    except Exception:
        try: await q.answer("Closed")
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^pw:members$"), group=-426)
async def cb_pw_members(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] members: {e}")


@Client.on_callback_query(filters.regex(r"^pw:members_p:(\d+)$"), group=-426)
async def cb_pw_members_page(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
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
        return await q.answer("X", show_alert=True)
    try:
        uid = int(q.matches[0].group(1))
        text, kb = await _view_pw_member_detail(uid)
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] member detail: {e}")


@Client.on_callback_query(filters.regex(r"^pw:add$"), group=-426)
async def cb_pw_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        _new_admin_session(q.from_user.id, "add_premium_user")
        text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>ADD PREMIUM USER</b>",
            DIV, "",
            "Send user id or @username",
            "",
            "Examples:",
            "<code>123456789</code>",
            "<code>@john</code>",
            "",
            "Or forward a message from the user",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("CANCEL", callback_data="pw:main")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] add: {e}")


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
                    f"Could not resolve <code>{_esc(text)}</code>\n"
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
                "Invalid. Send user id or @username.")

    if not uid_target:
        _clear_admin_session(message.from_user.id)
        return await message.reply_text("Could not identify user.")

    existing = await get_premium_user(uid_target)
    if existing and existing.get("expires_at", 0) > time.time():
        _clear_admin_session(message.from_user.id)
        uname = existing.get("username") or uid_target
        exp = _date_ist(existing.get("expires_at", 0))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("EXTEND PLAN",
                                   callback_data=f"pw:member:{uid_target}")],
            [InlineKeyboardButton("BACK",
                                   callback_data="pw:main")],
        ])
        return await message.reply_text(
            f"User already premium\n\n"
            f"ID <code>{uid_target}</code>\n"
            f"@{_esc(str(uname).lstrip('@'))}\n"
            f"Expires: <b>{exp}</b>",
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
        "<b>DOWNTOWN VILLA</b>",
        "<b>PICK PLAN DURATION</b>",
        DIV, "",
        f"User - <b>{_esc(display)}</b>",
        f"Username - <code>{_esc(uname_display)}</code>",
        f"ID - <code>{uid_target}</code>",
        "", DIV2, "",
        "Tap a plan duration below",
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
            "Not found in premium DB.",
            reply_markup=kb_pw_back())

    text_out, kb = await _view_pw_member_detail(doc.get("user_id"))
    await message.reply_text(text_out, reply_markup=kb,
                              parse_mode=ParseMode.HTML)


async def _handle_edit_notes_input(client, message, text: str, s):
    target_uid = s.get("target_uid")
    _clear_admin_session(message.from_user.id)
    if not target_uid:
        return await message.reply_text("No target.")

    c = _premium_coll()
    if c is None:
        return await message.reply_text("DB error.")

    try:
        await c.update_one(
            {"user_id": int(target_uid)},
            {"$set": {"notes": text[:500]}}
        )
        await message.reply_text(
            "Notes saved.",
            reply_markup=kb_pw_back(f"pw:member:{target_uid}"))
    except Exception:
        await message.reply_text("Failed.")


async def _handle_set_contact_input(client, message, text: str):
    _clear_admin_session(message.from_user.id)
    if not re.match(r"^@\w+$", text):
        return await message.reply_text("Format: @username")
    ok = await set_setting("contact_admin", text)
    if ok:
        await message.reply_text(
            f"Contact saved: <code>{_esc(text)}</code>",
            reply_markup=kb_pw_back(),
            parse_mode=ParseMode.HTML)
    else:
        await message.reply_text("Failed.")


@Client.on_callback_query(
    filters.regex(r"^pw:plan:(\d+):(\d+)$"), group=-426,
)
async def cb_pw_plan(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        months = int(q.matches[0].group(2))

        s = _get_admin_session(q.from_user.id)
        if not s or s.get("action") != "pick_plan":
            return await q.answer("Session expired", show_alert=True)

        target_username = s.get("target_username") or ""

        ok = await add_premium_user(
            user_id=target_uid,
            username=target_username,
            months=months,
            added_by=q.from_user.id,
        )

        if not ok:
            return await q.answer("Failed", show_alert=True)

        _clear_admin_session(q.from_user.id)

        doc = await get_premium_user(target_uid)
        expires = doc.get("expires_at", 0) if doc else 0

        await q.answer("Added")

        text_out = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>PREMIUM ADDED</b>",
            DIV, "",
            f"User - <code>{target_uid}</code>",
            f"Username - <code>{_esc(target_username)}</code>",
            "",
            f"Plan - <code>{months} months</code>",
            f"Expires - <code>{_date_ist(expires)}</code>",
            "",
            f"<code>{_now_ist()}</code>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("ADD ANOTHER",
                                   callback_data="pw:add"),
             InlineKeyboardButton("VIEW LIST",
                                   callback_data="pw:members")],
            [InlineKeyboardButton("BACK",
                                   callback_data="pw:main"),
             InlineKeyboardButton("CLOSE",
                                   callback_data="pw:close")],
        ])

        await _pw_safe_edit(q, text_out, kb)

        try:
            await client.send_message(
                chat_id=target_uid,
                text="\n".join([
                    "<b>PREMIUM ACTIVATED</b>",
                    DIV, "",
                    "Hi! Your premium has been activated",
                    "",
                    f"Plan - <code>{months} months</code>",
                    f"Expires - <code>{_date_ist(expires)}</code>",
                    "", DIV2,
                    "Start watching - search a series in the group",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception(f"[PREM] plan pick: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^pw:extend:(\d+)$"), group=-426)
async def cb_pw_extend(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)
        if not doc:
            return await q.answer("Not found", show_alert=True)

        _new_admin_session(q.from_user.id, "pick_plan",
                           target_uid=target_uid,
                           target_username=doc.get("username") or "")

        text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>EXTEND PREMIUM</b>",
            DIV, "",
            f"ID - <code>{target_uid}</code>",
            f"@{_esc(str(doc.get('username') or '').lstrip('@'))}",
            "",
            f"Current expires - "
            f"<code>{_date_ist(doc.get('expires_at', 0))}</code>",
            "", DIV2,
            "Pick new plan duration",
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
        return await q.answer("X", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        doc = await get_premium_user(target_uid)

        text = "\n".join([
            "<b>REMOVE PREMIUM?</b>",
            DIV, "",
            f"ID - <code>{target_uid}</code>",
        ])
        if doc:
            text += f"\n@{_esc(str(doc.get('username') or '').lstrip('@'))}"

        text += "\n\nThis cannot be undone."

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("YES, REMOVE",
                                   callback_data=f"pw:remove_go:{target_uid}")],
            [InlineKeyboardButton("CANCEL",
                                   callback_data=f"pw:member:{target_uid}")],
        ])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] remove: {e}")


@Client.on_callback_query(filters.regex(r"^pw:remove_go:(\d+)$"), group=-426)
async def cb_pw_remove_go(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        ok = await remove_premium_user(target_uid)
        await q.answer("Removed" if ok else "Not found")

        text, kb = await _view_pw_members(0)
        await _pw_safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[PREM] remove_go: {e}")


@Client.on_callback_query(filters.regex(r"^pw:notes:(\d+)$"), group=-426)
async def cb_pw_notes(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        target_uid = int(q.matches[0].group(1))
        _new_admin_session(q.from_user.id, "edit_notes", target_uid=target_uid)

        text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>EDIT NOTES</b>",
            DIV, "",
            f"ID - <code>{target_uid}</code>",
            "",
            "Send notes",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("CANCEL",
                                   callback_data=f"pw:member:{target_uid}")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] notes: {e}")


@Client.on_callback_query(filters.regex(r"^pw:find$"), group=-426)
async def cb_pw_find(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
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
        return await q.answer("X", show_alert=True)
    try:
        text, kb = await _view_pw_expiring()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expiring: {e}")


@Client.on_callback_query(filters.regex(r"^pw:expired$"), group=-426)
async def cb_pw_expired(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        text, kb = await _view_pw_expired()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] expired: {e}")


@Client.on_callback_query(filters.regex(r"^pw:stats$"), group=-426)
async def cb_pw_stats(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        text, kb = await _view_pw_stats()
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] stats: {e}")


@Client.on_callback_query(filters.regex(r"^pw:contact$"), group=-426)
async def cb_pw_contact(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("X", show_alert=True)
    try:
        current = await get_contact_admin() or "-"
        _new_admin_session(q.from_user.id, "set_contact")
        text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>SET CONTACT ADMIN</b>",
            DIV, "",
            f"Current - <code>{_esc(current)}</code>",
            "",
            "Send @username of admin to contact",
            "Example: <code>@your_username</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("CANCEL", callback_data="pw:main")]])
        await _pw_safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[PREM] contact: {e}")


logger.info("[PREM] Part 3 loaded")


async def handle_premium_group_search(client: Client, message,
                                       status_msg,
                                       query: str,
                                       db_result: Optional[Dict[str, Any]],
                                       tmdb_results: List[Dict[str, Any]]
                                       ) -> bool:
    try:
        uid = message.from_user.id

        if not await is_premium(uid):
            return False

        if db_result and db_result.get("hits"):
            matched_title = db_result.get("matched_title") or query
            ok = await _premium_redirect_to_pm(
                client, message, status_msg, uid, matched_title,
                db_result.get("hits") or [],
                tmdb_results
            )
            return ok

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
    try:
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

        try:
            if status_msg:
                await status_msg.delete()
        except Exception:
            pass

        try:
            await message.delete()
        except Exception:
            pass

        group_text = "\n".join([
            "<b>DOWNTOWN VILLA</b>",
            "<b>PREMIUM</b>",
            DIV, "",
            f"<b>{_esc(display_title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            "",
            DIV2, "",
            "Sent to your PM",
            "Open the bot to start watching",
        ])

        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=group_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[PREM] group reply: {e}")

        logger.info(f"[PREM] redirect user={uid} title={display_title!r}")

        await _prepare_pm_session(client, uid, series_data)

        return True
    except Exception as e:
        logger.exception(f"[PREM] redirect: {e}")
        return False


async def _prepare_pm_session(client: Client, uid: int,
                               series_data: Dict[str, Any]):
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

        slug = _slug(title)

        text = "\n".join([
            f"<b>{_esc(title)}</b>"
            + (f" <code>({year})</code>" if year else ""),
            (f"Rating: {rating:.1f}" if rating else ""),
            f"<code>{seasons_count} seasons</code> - "
            f"<code>{total_eps} episodes</code>",
            "",
            DIV, "",
            "<b>PREMIUM MODE</b>",
            "",
            "Pick language to start",
        ])

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

        kb_rows = []
        row = []
        for i, lang in enumerate(langs[:6]):
            row.append(InlineKeyboardButton(
                f"Lang: {lang}",
                callback_data=f"pw:lang:{slug}:{i}"
            ))
            if len(row) == 2:
                kb_rows.append(row)
                row = []
        if row:
            kb_rows.append(row)

        kb_rows.append([InlineKeyboardButton(
            "WATCH ORDER",
            callback_data=f"pw:wo:{slug}"
        )])
        kb_rows.append([InlineKeyboardButton(
            "CANCEL",
            callback_data=f"pw:cancel:{slug}"
        )])

        kb = InlineKeyboardMarkup(kb_rows)

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
                    "rating": rating,
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


_PW_LOCKS: Dict[int, float] = {}


def _pw_acquire_lock(uid: int, secs: float = 3.0) -> bool:
    now = time.time()
    last = _PW_LOCKS.get(uid, 0)
    if now - last < secs:
        return False
    _PW_LOCKS[uid] = now
    return True


def _build_poster_text(session: Dict[str, Any],
                       title: str, year: str = "",
                       rating: float = 0) -> str:
    p = compute_progress(session)
    seasons_raw = session.get("seasons") or {}
    seasons_ordered = sorted(int(k) for k in seasons_raw.keys()
                              if k.isdigit())

    lines = [
        f"<b>{_esc(title)}</b>"
        + (f" <code>({year})</code>" if year else ""),
    ]
    if rating:
        lines.append(f"Rating: {rating:.1f}")

    lines += ["", DIV, "", "<b>YOUR PROGRESS</b>", ""]

    if not seasons_ordered:
        lines.append("Pick a language to start")

    for sn in seasons_ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        watched = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)
        if total == 0:
            bar = render_progress_bar(0)
            status = "O"
        else:
            pct = watched / total * 100
            bar = render_progress_bar(pct)
            if watched >= total:
                status = "DONE"
            elif watched > 0:
                status = "PART"
            else:
                status = "NEW"
        lines.append(f"S{sn:02d} [{bar}] {watched}/{total} {status}")

    if seasons_ordered:
        lines += ["", DIV2, ""]
        lines.append(
            f"{p['total_watched']}/{p['total_eps']} "
            f"({p['pct']}%)"
        )
        remaining_eps = p["total_eps"] - p["total_watched"]
        if remaining_eps > 0:
            hours_left = remaining_eps * 22 / 60
            lines.append(f"~{int(hours_left)} hours left")

    return "\n".join(lines)


def _build_poster_kb(session: Dict[str, Any], slug: str):
    p = compute_progress(session)
    next_ep = find_next_episode(session)
    complete = is_series_complete(session)
    has_lang = bool(session.get("language"))
    has_seasons = bool(session.get("seasons"))

    rows = []

    if not has_lang and not has_seasons:
        return None

    if complete:
        rows.append([InlineKeyboardButton(
            "MARK COMPLETE",
            callback_data=f"pw:complete:{slug}"
        )])
    elif next_ep:
        sn, ep = next_ep
        rows.append([InlineKeyboardButton(
            f"WATCH NEXT - S{sn:02d}E{ep:02d}",
            callback_data=f"pw:play:{slug}:{sn}:{ep}"
        )])

    if has_seasons:
        rows.append([
            InlineKeyboardButton("SEASONS",
                                  callback_data=f"pw:seasons:{slug}"),
            InlineKeyboardButton("WATCH ORDER",
                                  callback_data=f"pw:wo:{slug}"),
        ])
        rows.append([InlineKeyboardButton(
            "PAUSE",
            callback_data=f"pw:pause:{slug}"
        )])

    return InlineKeyboardMarkup(rows)


def _build_seasons_view(session: Dict[str, Any], slug: str,
                         title: str) -> Tuple[str, InlineKeyboardMarkup]:
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    lines = [
        f"<b>{_esc(title)}</b>",
        DIV, "",
        "<b>PICK A SEASON</b>",
        "",
    ]

    rows = []
    for sn in ordered:
        s_data = seasons_raw.get(str(sn)) or {}
        watched = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)

        if total > 0 and watched >= total:
            icon = "DONE"
        elif watched > 0:
            icon = "PART"
        else:
            icon = "NEW"

        label = f"{icon} S{sn:02d} - {watched}/{total}"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"pw:season:{slug}:{sn}"
        )])

    rows.append([InlineKeyboardButton(
        "BACK", callback_data=f"pw:poster:{slug}"
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _build_episodes_view(session: Dict[str, Any], slug: str,
                          title: str, season: int
                          ) -> Tuple[str, InlineKeyboardMarkup]:
    s_data = (session.get("seasons") or {}).get(str(season)) or {}
    total = s_data.get("total_eps", 0)
    watched = set(s_data.get("watched") or [])

    lines = [
        f"<b>{_esc(title)}</b>",
        f"<b>Season {season:02d}</b>",
        DIV, "",
        f"Progress - <code>{len(watched)}/{total}</code>",
        "",
        "Pick an episode to watch",
        "",
    ]

    rows = []
    row = []
    for ep in range(1, total + 1):
        mark = "OK" if ep in watched else "NEW"
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
        "BACK", callback_data=f"pw:seasons:{slug}"
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _render_poster(client: Client, session: Dict[str, Any]):
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

        text = _build_poster_text(session, title, year, rating)
        kb = _build_poster_kb(session, slug)

        if kb is None:
            return False

        try:
            await client.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return True
        except MessageNotModified:
            return True
        except Exception as e:
            logger.debug(f"[PREM] caption edit failed: {e}")
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
            except Exception as e2:
                logger.warning(f"[PREM] render_poster: {e2}")
                return False
    except Exception as e:
        logger.exception(f"[PREM] render_poster: {e}")
        return False


@Client.on_callback_query(
    filters.regex(r"^pw:lang:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_lang(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid):
            return await q.answer("Wait")

        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        lang_idx = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

        langs = session.get("available_langs") or ["English"]
        if lang_idx < 0 or lang_idx >= len(langs):
            return await q.answer("Invalid", show_alert=True)

        chosen_lang = langs[lang_idx]

        await q.answer(f"{chosen_lang}")

        title = session.get("series_title") or "?"
        tmdb_seasons = session.get("tmdb_seasons") or []

        fresh_hits = []
        try:
            from plugins.series_group import _engine_search
            fresh_hits = await _engine_search(title, language=chosen_lang)
        except Exception as e:
            logger.warning(f"[PREM] lang search: {e}")

        if not fresh_hits:
            fresh_hits = session.get("hits") or []

        db_seasons: Dict[int, Set[int]] = defaultdict(set)
        for f in fresh_hits:
            sn = f.get("season")
            ep = f.get("episode")
            if sn is not None:
                db_seasons[sn].add(ep if ep is not None else 0)

        seasons_doc = {}
        for s in tmdb_seasons:
            sn = s.get("season")
            eps = s.get("episodes", 0)
            if sn is None: continue
            db_count = len(db_seasons.get(sn, set()))
            final_count = max(eps, db_count)
            seasons_doc[str(sn)] = {
                "total_eps": final_count,
                "watched": [],
                "current_ep": 1,
            }

        if not seasons_doc and db_seasons:
            for sn, eps_set in db_seasons.items():
                seasons_doc[str(sn)] = {
                    "total_eps": len(eps_set),
                    "watched": [],
                    "current_ep": 1,
                }

        old_seasons = session.get("seasons") or {}
        for sn_str, s_data in old_seasons.items():
            if sn_str in seasons_doc:
                seasons_doc[sn_str]["watched"] = s_data.get("watched") or []

        c = _sessions_coll()
        if c is not None:
            await c.update_one(
                {"user_id": uid, "series_slug": slug},
                {"$set": {
                    "seasons": seasons_doc,
                    "language": chosen_lang,
                    "hits": fresh_hits,
                    "last_activity_at": time.time(),
                }},
            )

        fresh = await get_session(uid, slug)
        if not fresh:
            return

        seasons_view_text, seasons_kb = _build_seasons_view(
            fresh, slug, title
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

        logger.info(f"[PREM] lang picked: u={uid} s={slug} lang={chosen_lang}")
    except Exception as e:
        logger.exception(f"[PREM] cb_pw_lang: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:seasons:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_seasons(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

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


@Client.on_callback_query(
    filters.regex(r"^pw:season:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_season(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

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


@Client.on_callback_query(
    filters.regex(r"^pw:poster:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_poster(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or "?"
        year = session.get("year") or ""
        rating = session.get("rating") or 0

        text = _build_poster_text(session, title, year, rating)
        kb = _build_poster_kb(session, slug)

        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("CLOSE",
                                       callback_data="pw:close_session")]])

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


@Client.on_callback_query(
    filters.regex(r"^pw:play:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_play(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer("Wait")

        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

        await q.answer("Sending...")

        await _send_episode_file(client, uid, session, season, episode)

        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] play: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


async def _send_episode_file(client: Client, uid: int,
                              session: Dict[str, Any],
                              season: int, episode: int) -> bool:
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        lang = session.get("language") or ""
        hits = session.get("hits") or []

        chosen_file = None
        for f in hits:
            if f.get("season") == season and f.get("episode") == episode:
                chosen_file = f
                break

        if not chosen_file:
            logger.warning(f"[PREM] no file for {slug} S{season}E{episode}")
            return False

        quality = chosen_file.get("quality") or "?"
        size = _fmt_size(chosen_file.get("file_size", 0))
        langs = "+".join(chosen_file.get("languages") or []) or lang or "?"

        file_caption = "\n".join([
            f"<b>{_esc(title)}</b>",
            f"<b>S{season:02d}E{episode:02d}</b>",
            f"<code>{quality}</code> - <code>{langs}</code>",
            f"Size: {size}",
            "",
            "<i>Premium - No Expiry</i>",
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
                    caption=file_caption,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM] cached send: {e}")

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
            return False

        try:
            await client.edit_message_reply_markup(
                chat_id=uid, message_id=sent_msg.id,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "MARK AS WATCHED",
                        callback_data=f"pw:watched:{slug}:{season}:"
                                       f"{episode}:{sent_msg.id}"
                    )],
                    [InlineKeyboardButton(
                        "WATCH NEXT",
                        callback_data=f"pw:next:{slug}:{season}:{episode}"
                    )],
                ]),
            )
        except Exception as e:
            logger.debug(f"[PREM] attach buttons: {e}")

        await set_current_position(uid, slug, season, episode)
        await update_current_file_msg(uid, slug, sent_msg.id)

        return True
    except Exception as e:
        logger.exception(f"[PREM] send episode: {e}")
        return False


@Client.on_callback_query(
    filters.regex(r"^pw:watched:([a-z0-9_]+):(\d+):(\d+):(\d+)$"),
    group=-420,
)
async def cb_pw_watched(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 1.5):
            return await q.answer("Wait")

        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))
        file_msg_id = int(q.matches[0].group(4))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

        await mark_watched(uid, slug, season, episode)
        await set_current_position(uid, slug, season, episode)

        try:
            await client.edit_message_reply_markup(
                chat_id=uid, message_id=file_msg_id,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "WATCHED",
                        callback_data=f"pw:already_watched:{slug}:"
                                       f"{season}:{episode}"
                    )
                ]]),
            )
        except Exception as e:
            logger.debug(f"[PREM] file edit: {e}")

        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)

        s_data = (fresh.get("seasons") or {}).get(str(season)) or {}
        watched_count = len(s_data.get("watched") or [])
        total = s_data.get("total_eps", 0)

        if total > 0 and watched_count >= total:
            await _season_complete_notify(client, uid, fresh, season)

        if is_series_complete(fresh):
            await _series_complete_notify(client, uid, fresh)

        await q.answer("Watched")
        logger.info(f"[PREM] watched u={uid} {slug} S{season:02d}E{episode:02d}")
    except Exception as e:
        logger.exception(f"[PREM] watched: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:already_watched:([a-z0-9_]+):(\d+):(\d+)$"),
    group=-420,
)
async def cb_pw_already_watched(client, q):
    try:
        await q.answer("Already watched")
    except Exception:
        pass


@Client.on_callback_query(
    filters.regex(r"^pw:next:([a-z0-9_]+):(\d+):(\d+)$"), group=-420,
)
async def cb_pw_next(client, q):
    try:
        uid = q.from_user.id

        if not _pw_acquire_lock(uid, 2.0):
            return await q.answer("Wait")

        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode = int(q.matches[0].group(3))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Session not found", show_alert=True)

        await mark_watched(uid, slug, season, episode)

        s_data = (session.get("seasons") or {}).get(str(season)) or {}
        total = s_data.get("total_eps", 0)
        next_ep = episode + 1

        if next_ep > total:
            seasons_raw = session.get("seasons") or {}
            ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())
            next_season = None
            for sn in ordered:
                if sn > season:
                    next_season = sn
                    break

            if next_season:
                await q.answer("Next season")
                await _send_episode_file(client, uid, session,
                                          next_season, 1)
                fresh = await get_session(uid, slug)
                if fresh:
                    await _render_poster(client, fresh)
                return
            else:
                await q.answer("Series complete")
                fresh = await get_session(uid, slug)
                if fresh:
                    await _render_poster(client, fresh)
                    await _series_complete_notify(client, uid, fresh)
                return

        await q.answer("Next")
        await _send_episode_file(client, uid, session, season, next_ep)

        fresh = await get_session(uid, slug)
        if fresh:
            await _render_poster(client, fresh)
    except Exception as e:
        logger.exception(f"[PREM] next: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


async def _season_complete_notify(client: Client, uid: int,
                                    session: Dict[str, Any], season: int):
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        seasons_raw = session.get("seasons") or {}
        ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

        next_season = None
        for sn in ordered:
            if sn > season:
                next_season = sn
                break

        if next_season:
            text = "\n".join([
                f"<b>SEASON {season} COMPLETE!</b>",
                DIV, "",
                f"<b>{_esc(title)}</b>",
                "",
                f"Season {season:02d} done!",
                "",
                f"Ready for Season {next_season}?",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"START S{next_season:02d}E01",
                    callback_data=f"pw:season:{slug}:{next_season}"
                )],
            ])
        else:
            text = "\n".join([
                "<b>SEASON COMPLETE!</b>",
                DIV, "",
                f"<b>{_esc(title)}</b>",
                f"Season {season:02d} done!",
                "",
                "Almost done!",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("CONTINUE",
                                       callback_data=f"pw:poster:{slug}")
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
            "<b>CONGRATULATIONS!</b>",
            DIV, "",
            f"<b>{_esc(title)}</b>",
            "",
            "<b>SERIES COMPLETE</b>",
            "",
            f"{p['total_watched']}/{p['total_eps']} episodes",
            f"~{int(p['total_eps'] * 22 / 60)} hours",
            "",
            DIV2, "",
            "Rate this series",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("1 Star",
                                   callback_data=f"pw:rate:{slug}:1"),
             InlineKeyboardButton("2 Stars",
                                   callback_data=f"pw:rate:{slug}:2"),
             InlineKeyboardButton("3 Stars",
                                   callback_data=f"pw:rate:{slug}:3"),
             InlineKeyboardButton("4 Stars",
                                   callback_data=f"pw:rate:{slug}:4"),
             InlineKeyboardButton("5 Stars",
                                   callback_data=f"pw:rate:{slug}:5")],
            [InlineKeyboardButton(
                "MARK COMPLETE",
                callback_data=f"pw:complete:{slug}"
            )],
        ])

        await client.send_message(
            chat_id=uid, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"[PREM] series notify: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:rate:([a-z0-9_]+):(\d)$"), group=-420,
)
async def cb_pw_rate(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        stars = int(q.matches[0].group(2))

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

        await q.answer(f"{stars}/5")
        try:
            await q.message.edit_text(
                (q.message.text or "") +
                f"\n\nThanks for rating ({stars} stars)",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[PREM] rate: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:complete:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_complete(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or "?"
        p = compute_progress(session)

        await mark_session_completed(uid, slug)
        await q.answer("Completed")

        text = "\n".join([
            "<b>SERIES COMPLETED!</b>",
            DIV, "",
            f"<b>{_esc(title)}</b>",
            "",
            f"{p['total_watched']}/{p['total_eps']}",
            "",
            "Session archived",
            "Search in group to start new series",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("MY SESSIONS",
                                   callback_data="pw:my_sessions")],
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


@Client.on_callback_query(
    filters.regex(r"^pw:pause:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_pause(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or "?"
        p = compute_progress(session)

        await q.answer("Paused")
        text = "\n".join([
            "<b>PAUSED</b>",
            DIV, "",
            f"<b>{_esc(title)}</b>",
            f"{p['total_watched']}/{p['total_eps']}",
            "",
            "Progress saved",
            "Use /my to resume anytime",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("RESUME",
                                   callback_data=f"pw:poster:{slug}")],
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


async def _show_session_list(client: Client, chat_id: int, uid: int):
    sessions = await list_user_sessions(uid)
    if not sessions:
        await client.send_message(
            chat_id=chat_id,
            text="\n".join([
                "<b>DOWNTOWN VILLA</b>",
                "<b>YOUR SESSIONS</b>",
                DIV, "",
                "No active sessions",
                "",
                "Search a series in the group",
            ]),
            parse_mode=ParseMode.HTML,
        )
        return

    lines = [
        "<b>DOWNTOWN VILLA</b>",
        f"<b>YOUR SESSIONS</b> - <code>{len(sessions)}</code>",
        DIV, "",
    ]

    rows = []
    for s in sessions[:10]:
        title = s.get("series_title") or "?"
        slug = s.get("series_slug") or ""
        p = compute_progress(s)
        bar = render_progress_bar(p["pct"])
        lines.append(f"<b>{_esc(title)}</b>")
        lines.append(f"   [{bar}] {p['total_watched']}/{p['total_eps']}")
        lines.append("")

        rows.append([InlineKeyboardButton(
            f"{title[:30]} - {p['total_watched']}/{p['total_eps']}",
            callback_data=f"pw:resume:{slug}"
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
    if not message.from_user:
        return
    uid = message.from_user.id
    if not await is_premium(uid):
        return await message.reply_text("Premium only.")
    try:
        await _show_session_list(client, message.chat.id, uid)
    except Exception as e:
        logger.exception(f"[PREM] /my: {e}")


@Client.on_callback_query(
    filters.regex(r"^pw:my_sessions$"), group=-422,
)
async def cb_pw_my_sessions(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)
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
        await q.answer("OK")
    except Exception:
        pass


@Client.on_callback_query(
    filters.regex(r"^pw:resume:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_resume(client, q):
    try:
        uid = q.from_user.id
        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or "?"
        year = session.get("year") or ""
        rating = session.get("rating") or 0

        text = _build_poster_text(session, title, year, rating)
        kb = _build_poster_kb(session, slug)

        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("CLOSE",
                                       callback_data="pw:close_session")]])

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


@Client.on_callback_query(
    filters.regex(r"^pw:cancel:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_cancel(client, q):
    try:
        try: await q.message.delete()
        except Exception: pass
        await q.answer("Cancelled")
    except Exception:
        try: await q.answer("OK")
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:close_session$"), group=-420,
)
async def cb_pw_close_session(client, q):
    try:
        try: await q.message.delete()
        except Exception: pass
        await q.answer("Closed")
    except Exception:
        pass


FRANCHISES: Dict[str, Dict[str, Any]] = {
    "breaking_bad_universe": {
        "name": "Breaking Bad Universe",
        "items": [
            {"title": "Breaking Bad", "year": "2008", "type": "series"},
            {"title": "El Camino", "year": "2019", "type": "movie"},
            {"title": "Better Call Saul", "year": "2015", "type": "series"},
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
            {"title": "Spider-Man: Homecoming", "year": "2017", "type": "movie"},
            {"title": "Thor: Ragnarok", "year": "2017", "type": "movie"},
            {"title": "Black Panther", "year": "2018", "type": "movie"},
            {"title": "Avengers: Infinity War", "year": "2018", "type": "movie"},
            {"title": "Captain Marvel", "year": "2019", "type": "movie"},
            {"title": "Avengers: Endgame", "year": "2019", "type": "movie"},
            {"title": "Spider-Man: Far From Home", "year": "2019", "type": "movie"},
        ],
    },
    "star_wars": {
        "name": "Star Wars Skywalker Saga",
        "items": [
            {"title": "Star Wars: Episode I - The Phantom Menace", "year": "1999", "type": "movie"},
            {"title": "Star Wars: Episode II - Attack of the Clones", "year": "2002", "type": "movie"},
            {"title": "Star Wars: Episode III - Revenge of the Sith", "year": "2005", "type": "movie"},
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
            {"title": "Wonder Woman", "year": "2017", "type": "movie"},
            {"title": "Justice League", "year": "2017", "type": "movie"},
            {"title": "Aquaman", "year": "2018", "type": "movie"},
            {"title": "Shazam!", "year": "2019", "type": "movie"},
        ],
    },
    "the_boys_universe": {
        "name": "The Boys Universe",
        "items": [
            {"title": "The Boys", "year": "2019", "type": "series"},
            {"title": "Gen V", "year": "2023", "type": "series"},
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
        "name": "Fast and Furious",
        "items": [
            {"title": "The Fast and the Furious", "year": "2001", "type": "movie"},
            {"title": "2 Fast 2 Furious", "year": "2003", "type": "movie"},
            {"title": "The Fast and the Furious: Tokyo Drift", "year": "2006", "type": "movie"},
            {"title": "Fast and Furious", "year": "2009", "type": "movie"},
            {"title": "Fast Five", "year": "2011", "type": "movie"},
            {"title": "Fast and Furious 6", "year": "2013", "type": "movie"},
            {"title": "Furious 7", "year": "2015", "type": "movie"},
            {"title": "The Fate of the Furious", "year": "2017", "type": "movie"},
            {"title": "F9", "year": "2021", "type": "movie"},
            {"title": "Fast X", "year": "2023", "type": "movie"},
        ],
    },
    "lotr": {
        "name": "Middle-earth",
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
        "name": "Wizarding World",
        "items": [
            {"title": "Harry Potter and the Sorcerer's Stone", "year": "2001", "type": "movie"},
            {"title": "Harry Potter and the Chamber of Secrets", "year": "2002", "type": "movie"},
            {"title": "Harry Potter and the Prisoner of Azkaban", "year": "2004", "type": "movie"},
            {"title": "Harry Potter and the Goblet of Fire", "year": "2005", "type": "movie"},
            {"title": "Harry Potter and the Order of the Phoenix", "year": "2007", "type": "movie"},
            {"title": "Harry Potter and the Half-Blood Prince", "year": "2009", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 1", "year": "2010", "type": "movie"},
            {"title": "Harry Potter and the Deathly Hallows Part 2", "year": "2011", "type": "movie"},
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
}


def _find_franchise_by_title(title: str) -> Optional[Dict[str, Any]]:
    if not title: return None
    t_lower = title.lower().strip()

    for fkey, fdata in FRANCHISES.items():
        for item in fdata.get("items") or []:
            item_title = (item.get("title") or "").lower().strip()
            if item_title == t_lower:
                return {"key": fkey, **fdata}
            if len(t_lower) > 6:
                if t_lower in item_title or item_title in t_lower:
                    return {"key": fkey, **fdata}
    return None


async def _build_watch_order_view(uid: int, franchise: Dict[str, Any],
                                    slug: str
                                    ) -> Tuple[str, InlineKeyboardMarkup]:
    items = franchise.get("items") or []
    fname = franchise.get("name") or "?"

    lines = [
        "<b>WATCH ORDER</b>",
        f"<b>{_esc(fname)}</b>",
        DIV, "",
        "Recommended order:",
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
            if p["total_eps"] > 0 and p["total_watched"] >= p["total_eps"]:
                icon = "DONE"
                progress_str = "COMPLETE"
            else:
                icon = "PART"
                progress_str = f"{p['total_watched']}/{p['total_eps']}"
        else:
            icon = "NEW"
            progress_str = "Not started"

        type_icon = "MOV" if itype == "movie" else "SER"
        lines.append(
            f"<b>{i}.</b> {icon} {type_icon} <b>{_esc(title)}</b> "
            f"<code>({year})</code>"
        )
        lines.append(f"   <i>{progress_str}</i>")

        rows.append([InlineKeyboardButton(
            f"{icon} {i}. {title[:30]}",
            callback_data=f"pw:wo_open:{slug}:{i-1}"
        )])

    rows.append([InlineKeyboardButton(
        "BACK", callback_data=f"pw:poster:{slug}"
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


@Client.on_callback_query(
    filters.regex(r"^pw:wo:([a-z0-9_]+)$"), group=-420,
)
async def cb_pw_watch_order(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or ""
        franchise = _find_franchise_by_title(title)
        if not franchise:
            return await q.answer(
                "No watch order for this series",
                show_alert=True
            )

        text, kb = await _build_watch_order_view(uid, franchise, slug)

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
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^pw:wo_open:([a-z0-9_]+):(\d+)$"), group=-420,
)
async def cb_pw_wo_open(client, q):
    try:
        uid = q.from_user.id
        if not await is_premium(uid):
            return await q.answer("Premium only", show_alert=True)

        slug = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))

        session = await get_session(uid, slug)
        if not session:
            return await q.answer("Not found", show_alert=True)

        title = session.get("series_title") or ""
        franchise = _find_franchise_by_title(title)
        if not franchise:
            return await q.answer("Error", show_alert=True)

        items = franchise.get("items") or []
        if idx < 0 or idx >= len(items):
            return await q.answer("Invalid", show_alert=True)

        item = items[idx]
        item_title = item.get("title") or ""
        item_year = item.get("year") or ""

        await q.answer(f"{item_title}")

        tmdb_id = None
        poster = None
        tmdb_seasons = []
        hits = []
        try:
            from plugins.series_group import (
                _engine_search, _tmdb_search_series,
                _tmdb_series_details, _tmdb_seasons
            )
            hits = await _engine_search(item_title)
            suggestions = await _tmdb_search_series(item_title)
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
            return await q.answer("Not in library", show_alert=True)

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
        await q.answer("Sent to PM!", show_alert=True)
    except Exception as e:
        logger.exception(f"[PREM] wo_open: {e}")
        try: await q.answer("Error", show_alert=True)
        except Exception: pass


_PW_FINAL_BOOTED = False


@Client.on_message(filters.private, group=-419)
async def _pw_final_boot(client, message):
    global _PW_FINAL_BOOTED
    if _PW_FINAL_BOOTED:
        return
    _PW_FINAL_BOOTED = True
    logger.info("[PREM] final boot - all parts loaded")


logger.info("================================================================")
logger.info("[PREM] PREMIUM WATCH COMPANION v2 - LOADED")
logger.info("[PREM] Parts 1-4 loaded")
logger.info("[PREM] Panel: /seriesgroupsettings")
logger.info("[PREM] Premium to PM auto-redirect")
logger.info("[PREM] Watch sessions + progress tracking")
logger.info("[PREM] Expiry reminders (10d/5d/1d/expired)")
logger.info("[PREM] Watch Order for franchises")
logger.info("[PREM] Cleanup 30d grace / 180d inactive")
logger.info("================================================================")
