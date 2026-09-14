# plugins/group_admin.py
"""
🏨 DOWNTOWN VILLA — GROUP ADMIN (Self-contained)

No dependency on group_settings/ package.
Uses existing db_manager + in-memory sessions.
Buttons + text input (old bot logic).
"""

import time
import secrets
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from database import db_manager
from info import ADMINS

logger = logging.getLogger(__name__)
logger.info("[GADMIN] module import starting")


# ═══════════════════════════════════════════════════════════
# DB HELPERS — use whatever db_manager exposes
# ═══════════════════════════════════════════════════════════
def _get_user_db():
    """Return user DB (or fallback)."""
    for name in ("get_user_db", "get_system_db", "get_media_db"):
        try:
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None:
                    return db
        except Exception:
            continue
    # last resort
    try:
        return db_manager._db  # noqa
    except Exception:
        return None


def _get_system_db():
    for name in ("get_system_db", "get_user_db", "get_media_db"):
        try:
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None:
                    return db
        except Exception:
            continue
    try:
        return db_manager._db  # noqa
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# PERMISSIONS
# ═══════════════════════════════════════════════════════════
def _is_owner(user_id: int) -> bool:
    try:
        return int(user_id) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


async def _is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    if _is_owner(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception as e:
        logger.debug(f"[GADMIN] admin check failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# CONFIG HELPERS
# ═══════════════════════════════════════════════════════════
def _defaults() -> Dict[str, Any]:
    return {
        "enabled": True,
        "content_mode": "both",
        "result_mode": "button",
        "custom_caption": None,
        "result_buttons": [],
        "movie_group_link": None,
        "series_group_link": None,
        "search_settings": {
            "auto_filter": True,
            "spell_check": True,
            "results_per_page": 10,
            "search_cooldown": 2,
        },
        "metadata_settings": {
            "poster": True, "rating": True, "genre": True,
            "year": True, "language": True,
        },
        "force_sub_settings": {"enabled": False, "channels": []},
        "verification_settings": {"enabled": False},
        "welcome_settings": {"enabled": False, "auto_delete": True},
        "auto_delete_settings": {
            "welcome": True, "result": True, "search": True, "file": True,
        },
        "security_settings": {
            "url_blocking": True, "telegram_links": True, "admin_bypass": True,
        },
        "request_settings": {
            "enabled": True, "no_result_log": True, "user_pm_update": True,
        },
    }


async def _get_config(chat_id: int) -> Dict[str, Any]:
    db = _get_user_db()
    if db is None:
        return _defaults()
    try:
        doc = await db["groups"].find_one({"chat_id": chat_id})
    except Exception as e:
        logger.warning(f"[GADMIN] get_config failed: {e}")
        return _defaults()
    if not doc:
        return _defaults()
    doc.pop("_id", None)
    merged = _defaults()
    for k, v in doc.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = {**merged[k], **v}
        else:
            merged[k] = v
    return merged


async def _save_field(chat_id: int, field: str, value: Any) -> bool:
    """Atomic nested $set."""
    db = _get_user_db()
    if db is None:
        return False
    try:
        set_dict: Dict[str, Any] = {}
        if isinstance(value, dict):
            for k, v in value.items():
                set_dict[f"{field}.{k}"] = v
        else:
            set_dict[field] = value
        set_dict["updated_at"] = datetime.utcnow()
        await db["groups"].update_one(
            {"chat_id": chat_id},
            {"$set": set_dict},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[GADMIN] save failed: {e}")
        return False


async def _register_group(chat_id: int, title: str) -> bool:
    db = _get_user_db()
    if db is None:
        return False
    try:
        await db["groups"].update_one(
            {"chat_id": chat_id},
            {
                "$setOnInsert": {"chat_id": chat_id, "created_at": datetime.utcnow()},
                "$set": {"title": title or "Group", "updated_at": datetime.utcnow()},
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[GADMIN] register failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# IN-MEMORY SESSIONS
# ═══════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}
SESSION_TTL = 300


def _new_session(user_id: int, chat_id: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[user_id] = {
        "token": tok, "action": action, "chat_id": chat_id,
        "step": 1, "data": data, "expires": time.time() + SESSION_TTL,
    }
    return tok


def _get_session(user_id: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(user_id)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(user_id, None)
        return None
    return s


def _clear_session(user_id: int) -> None:
    _SESSIONS.pop(user_id, None)


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
def _on(v) -> str:
    return "🟢 ON" if v else "🔴 OFF"


def _div() -> str:
    return "━━━━━━━━━━━━━━━━━━"


def _back(chat_id: int) -> List[List[InlineKeyboardButton]]:
    return [[
        InlineKeyboardButton("◀️ BACK", callback_data=f"gs:refresh:{chat_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="gs:close"),
    ]]


# ═══════════════════════════════════════════════════════════
# /groupsettings — OWNER (PM)
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("groupsettings") & filters.private)
async def cmd_groupsettings(client: Client, message: Message):
    logger.info(f"[GADMIN] /groupsettings from {message.from_user.id}")
    if not message.from_user or not _is_owner(message.from_user.id):
        return await message.reply_text("⛔ ᴛʜɪꜱ ɪꜱ ꜰᴏʀ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.")

    db = _get_user_db()
    if db is None:
        return await message.reply_text("❌ ᴅᴀᴛᴀʙᴀꜱᴇ ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.")

    try:
        cur = db["groups"].find({}).sort("title", 1).limit(10)
        groups = await cur.to_list(length=10)
        total = await db["groups"].count_documents({})
    except Exception as e:
        logger.exception(f"[GADMIN] list failed: {e}")
        return await message.reply_text(f"❌ ꜰᴀɪʟᴇᴅ: {e}")

    rows: List[List[InlineKeyboardButton]] = []
    for g in groups:
        gid = g.get("chat_id")
        title = (g.get("title") or str(gid))[:40].upper()
        st = "🟢" if g.get("enabled", True) else "🔴"
        rows.append([InlineKeyboardButton(f"{st} {title}", callback_data=f"gs:open:{gid}")])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH", callback_data="gs:owner_refresh"),
        InlineKeyboardButton("❌ CLOSE", callback_data="gs:close"),
    ])
    await message.reply_text(
        f"⚙️ <b>ɢʀᴏᴜᴘ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n{_div()}\n\n"
        f"📊 ʀᴇɢɪꜱᴛᴇʀᴇᴅ · <b>{total}</b>\n\nꜱᴇʟᴇᴄᴛ ᴀ ɢʀᴏᴜᴘ:",
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=enums.ParseMode.HTML,
    )


# ═══════════════════════════════════════════════════════════
# /settings — GROUP
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("settings"))
async def cmd_settings(client: Client, message: Message):
    if not message.from_user:
        return

    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        await _register_group(message.chat.id, message.chat.title or "Group")
        await message.reply_text(
            "⚙️ <b>ᴡʜᴇʀᴇ ᴛᴏ ᴏᴘᴇɴ ꜱᴇᴛᴛɪɴɢꜱ?</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 IN PM", callback_data=f"gs:open_pm:{message.chat.id}")],
                [InlineKeyboardButton("👥 HERE", callback_data=f"gs:open:{message.chat.id}")],
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
        return

    # PM without group → owner list
    await cmd_groupsettings(client, message)


# ═══════════════════════════════════════════════════════════
# /reload
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("reload"))
async def cmd_reload(client: Client, message: Message):
    if not message.from_user:
        return
    if message.chat.type in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        if not await _is_group_admin(client, message.chat.id, message.from_user.id):
            return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        await _register_group(message.chat.id, message.chat.title or "Group")
        await message.reply_text("✅ ɢʀᴏᴜᴘ ʀᴇʟᴏᴀᴅᴇᴅ. ᴜꜱᴇ /settings.")
        return


# ═══════════════════════════════════════════════════════════
# MAIN MENU RENDER
# ═══════════════════════════════════════════════════════════
async def _render_main(chat_id: int) -> str:
    cfg = await _get_config(chat_id)
    ss = cfg.get("search_settings", {})
    fs = cfg.get("force_sub_settings", {})
    vs = cfg.get("verification_settings", {})
    ws = cfg.get("welcome_settings", {})
    mode = {"movies": "🎬 ᴍᴏᴠɪᴇꜱ", "series": "📺 ꜱᴇʀɪᴇꜱ", "both": "🎬📺 ʙᴏᴛʜ"}.get(
        cfg.get("content_mode", "both"), "?"
    )
    return "\n".join([
        "⚙️ <b>ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ</b>",
        _div(), "",
        f"👥 <b>{cfg.get('title') or chat_id}</b>",
        f"🆔 <code>{chat_id}</code>", "",
        f"📚 ᴄᴏɴᴛᴇɴᴛ · {mode}",
        f"🔎 ꜱᴇᴀʀᴄʜ · {_on(ss.get('auto_filter', True))}",
        f"📦 ʀᴇꜱᴜʟᴛ · {cfg.get('result_mode', 'button').upper()}",
        f"📝 ᴄᴀᴘᴛɪᴏɴ · {_on(bool(cfg.get('custom_caption')))}",
        f"📢 ꜰꜱᴜʙ · {len(fs.get('channels') or [])} ᴄʜᴀɴɴᴇʟꜱ",
        f"🔐 ᴠᴇʀɪꜰʏ · {_on(vs.get('enabled', False))}",
        f"👋 ᴡᴇʟᴄᴏᴍᴇ · {_on(ws.get('enabled', False))}",
        "", "ꜱᴇʟᴇᴄᴛ ᴀ ꜱᴇᴄᴛɪᴏɴ:",
    ])


def _main_kb(chat_id: int) -> InlineKeyboardMarkup:
    c = str(chat_id)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 CONTENT MODE", callback_data=f"gs:content:{c}")],
        [InlineKeyboardButton("🔎 SEARCH & FILTER", callback_data=f"gs:search:{c}")],
        [InlineKeyboardButton("📦 RESULT BUTTONS", callback_data=f"gs:buttons:{c}")],
        [InlineKeyboardButton("📝 FILE CAPTION", callback_data=f"gs:caption:{c}")],
        [InlineKeyboardButton("🎬 METADATA", callback_data=f"gs:metadata:{c}")],
        [InlineKeyboardButton("📢 FORCE SUB", callback_data=f"gs:fsub:{c}")],
        [InlineKeyboardButton("🔐 VERIFICATION", callback_data=f"gs:verify:{c}")],
        [InlineKeyboardButton("🛡️ SECURITY", callback_data=f"gs:security:{c}")],
        [InlineKeyboardButton("👋 WELCOME", callback_data=f"gs:welcome:{c}")],
        [InlineKeyboardButton("🗑️ AUTO DELETE", callback_data=f"gs:autodel:{c}")],
        [InlineKeyboardButton("📝 REQUESTS", callback_data=f"gs:req:{c}")],
        [InlineKeyboardButton("📊 STATISTICS", callback_data=f"gs:stats:{c}")],
        [InlineKeyboardButton("📋 VIEW ALL", callback_data=f"gs:view:{c}")],
        [InlineKeyboardButton("♻️ RESET", callback_data=f"gs:reset:{c}")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=f"gs:refresh:{c}"),
         InlineKeyboardButton("❌ CLOSE", callback_data="gs:close")],
    ])


# ═══════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gs:"))
async def gs_router(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    action = parts[1]
    extra = parts[2] if len(parts) > 2 else ""

    # CLOSE
    if action == "close":
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("ᴄʟᴏꜱᴇᴅ")

    # OWNER REFRESH
    if action == "owner_refresh":
        if not _is_owner(q.from_user.id):
            return await q.answer("⛔", show_alert=True)
        db = _get_user_db()
        if db is None:
            return await q.answer("❌ ᴅʙ ᴇʀʀᴏʀ", show_alert=True)
        try:
            cur = db["groups"].find({}).sort("title", 1).limit(10)
            groups = await cur.to_list(length=10)
            total = await db["groups"].count_documents({})
        except Exception:
            groups, total = [], 0
        rows = []
        for g in groups:
            gid = g.get("chat_id")
            title = (g.get("title") or str(gid))[:40].upper()
            st = "🟢" if g.get("enabled", True) else "🔴"
            rows.append([InlineKeyboardButton(f"{st} {title}", callback_data=f"gs:open:{gid}")])
        rows.append([
            InlineKeyboardButton("🔄 REFRESH", callback_data="gs:owner_refresh"),
            InlineKeyboardButton("❌ CLOSE", callback_data="gs:close"),
        ])
        try:
            await q.message.edit_text(
                f"⚙️ <b>ɢʀᴏᴜᴘ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ</b>\n{_div()}\n\n"
                f"📊 ʀᴇɢɪꜱᴛᴇʀᴇᴅ · <b>{total}</b>",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        return await q.answer("🔄 ʀᴇꜰʀᴇꜱʜᴇᴅ")

    # OPEN IN PM
    if action == "open_pm":
        try:
            chat_id = int(extra)
        except ValueError:
            return await q.answer("❌", show_alert=True)
        if not await _is_group_admin(client, chat_id, q.from_user.id):
            return await q.answer("⛔", show_alert=True)
        try:
            await client.send_message(
                chat_id=q.from_user.id,
                text=await _render_main(chat_id),
                reply_markup=_main_kb(chat_id),
                parse_mode=enums.ParseMode.HTML,
            )
            await q.answer("✅ ᴏᴘᴇɴᴇᴅ ɪɴ ᴘᴍ")
        except Exception as e:
            await q.answer(f"❌ {e}", show_alert=True)
        return

    # OPEN / REFRESH
    if action in ("open", "refresh"):
        try:
            chat_id = int(extra)
        except ValueError:
            return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        if not await _is_group_admin(client, chat_id, q.from_user.id):
            return await q.answer("⛔ ɴᴏᴛ ᴀᴜᴛʜ", show_alert=True)
        try:
            await q.message.edit_text(
                await _render_main(chat_id),
                reply_markup=_main_kb(chat_id),
                parse_mode=enums.ParseMode.HTML,
            )
        except Exception:
            pass
        return await q.answer()

    # Need chat_id
    try:
        chat_id = int(extra)
    except (ValueError, TypeError):
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    if not await _is_group_admin(client, chat_id, q.from_user.id):
        return await q.answer("⛔ ɴᴏᴛ ᴀᴜᴛʜ", show_alert=True)

    # ── CONTENT ──
    if action == "content":
        cfg = await _get_config(chat_id)
        cur = cfg.get("content_mode", "both")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{'✅ ' if cur=='movies' else ''}🎬 MOVIES",
                                   callback_data=f"gs:set_content:{chat_id}:movies")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='series' else ''}📺 SERIES",
                                   callback_data=f"gs:set_content:{chat_id}:series")],
            [InlineKeyboardButton(f"{'✅ ' if cur=='both' else ''}🎬📺 BOTH",
                                   callback_data=f"gs:set_content:{chat_id}:both")],
            *_back(chat_id),
        ])
        await q.message.edit_text(
            f"📚 <b>ᴄᴏɴᴛᴇɴᴛ ᴍᴏᴅᴇ</b>\n{_div()}\n\nᴄᴜʀʀᴇɴᴛ · <b>{cur.upper()}</b>\n\nᴄʜᴏᴏꜱᴇ:",
            reply_markup=kb, parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "set_content":
        # callback_data = gs:set_content:<chat_id>:<mode>
        p = q.data.split(":")
        mode = p[3]
        await _save_field(chat_id, "content_mode", mode)
        await q.answer(f"✅ {mode}")
        q.data = f"gs:content:{chat_id}"
        return await gs_router(client, q)

    # ── SEARCH ──
    if action == "search":
        cfg = await _get_config(chat_id)
        ss = cfg.get("search_settings", {})
        rows = []
        for k, label in [("auto_filter", "AUTO FILTER"), ("spell_check", "SPELL CHECK")]:
            v = ss.get(k, True)
            rows.append([InlineKeyboardButton(
                f"{'🟢' if v else '🔴'} {label}",
                callback_data=f"gs:toggle_search:{chat_id}:{k}",
            )])
        rows.extend(_back(chat_id))
        await q.message.edit_text(
            f"🔎 <b>ꜱᴇᴀʀᴄʜ & ꜰɪʟᴛᴇʀ</b>\n{_div()}\n\n"
            f"📊 ʀᴇꜱᴜʟᴛꜱ/ᴘᴀɢᴇ · <code>{ss.get('results_per_page', 10)}</code>\n"
            f"⏱️ ᴄᴏᴏʟᴅᴏᴡɴ · <code>{ss.get('search_cooldown', 2)}s</code>",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "toggle_search":
        p = q.data.split(":")
        key = p[3]
        cfg = await _get_config(chat_id)
        cur = cfg.get("search_settings", {}).get(key, True)
        await _save_field(chat_id, f"search_settings.{key}", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:search:{chat_id}"
        return await gs_router(client, q)

    # ── CAPTION ──
    if action == "caption":
        cfg = await _get_config(chat_id)
        cur = cfg.get("custom_caption")
        text = (
            f"📝 <b>ꜰɪʟᴇ ᴄᴀᴘᴛɪᴏɴ</b>\n{_div()}\n\n"
            f"ᴍᴏᴅᴇ · {'🟢 ᴄᴜꜱᴛᴏᴍ' if cur else '⚪ ɢʟᴏʙᴀʟ'}\n\n"
            f"ᴠᴀʀꜱ: <code>{{file_name}}</code> <code>{{file_size}}</code> <code>{{file_caption}}</code>"
        )
        rows = [[InlineKeyboardButton("✏️ SET CAPTION",
                                       callback_data=f"gs:set_caption_start:{chat_id}")]]
        if cur:
            rows.append([InlineKeyboardButton("♻️ USE GLOBAL",
                                               callback_data=f"gs:rm_caption:{chat_id}")])
        rows.extend(_back(chat_id))
        await q.message.edit_text(text, reply_markup=InlineKeyboardMarkup(rows),
                                   parse_mode=enums.ParseMode.HTML)
        return await q.answer()

    if action == "set_caption_start":
        _new_session(q.from_user.id, chat_id, "set_caption")
        await q.message.edit_text(
            f"✏️ <b>ꜱᴇᴛ ᴄᴀᴘᴛɪᴏɴ</b>\n{_div()}\n\n📝 ꜱᴇɴᴅ ᴛʜᴇ ᴄᴀᴘᴛɪᴏɴ ᴀꜱ ɴᴇxᴛ ᴍᴇꜱꜱᴀɢᴇ.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ CANCEL",
                                       callback_data=f"gs:cancel_session:{chat_id}")],
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "rm_caption":
        await _save_field(chat_id, "custom_caption", None)
        await q.answer("✅ ɢʟᴏʙᴀʟ ᴄᴀᴘᴛɪᴏɴ")
        q.data = f"gs:caption:{chat_id}"
        return await gs_router(client, q)

    if action == "cancel_session":
        _clear_session(q.from_user.id)
        await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
        q.data = f"gs:refresh:{chat_id}"
        return await gs_router(client, q)

    # ── METADATA ──
    if action == "metadata":
        cfg = await _get_config(chat_id)
        ms = cfg.get("metadata_settings", {})
        rows = []
        for k, label in [("poster", "POSTER"), ("rating", "RATING"), ("genre", "GENRE"),
                          ("year", "YEAR"), ("language", "LANGUAGE")]:
            v = ms.get(k, True)
            rows.append([InlineKeyboardButton(
                f"{'🟢' if v else '🔴'} {label}",
                callback_data=f"gs:toggle_meta:{chat_id}:{k}",
            )])
        rows.extend(_back(chat_id))
        await q.message.edit_text(
            f"🎬 <b>ᴍᴇᴛᴀᴅᴀᴛᴀ</b>\n{_div()}",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "toggle_meta":
        p = q.data.split(":")
        key = p[3]
        cfg = await _get_config(chat_id)
        cur = cfg.get("metadata_settings", {}).get(key, True)
        await _save_field(chat_id, f"metadata_settings.{key}", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:metadata:{chat_id}"
        return await gs_router(client, q)

    # ── FSUB ──
    if action == "fsub":
        cfg = await _get_config(chat_id)
        fs = cfg.get("force_sub_settings", {})
        chans = fs.get("channels") or []
        enabled = fs.get("enabled", False)
        rows = [
            [InlineKeyboardButton(f"{'🔴 DISABLE' if enabled else '🟢 ENABLE'}",
                                   callback_data=f"gs:fsub_toggle:{chat_id}")],
            [InlineKeyboardButton("➕ ADD CHANNEL",
                                   callback_data=f"gs:fsub_add_start:{chat_id}")],
        ]
        if chans:
            rows.append([InlineKeyboardButton("🗑️ REMOVE",
                                               callback_data=f"gs:fsub_rm_menu:{chat_id}")])
        rows.extend(_back(chat_id))
        await q.message.edit_text(
            f"📢 <b>ꜰᴏʀᴄᴇ ꜱᴜʙ</b>\n{_div()}\n\n"
            f"ꜱᴛᴀᴛᴜꜱ · {_on(enabled)}\nᴄʜᴀɴɴᴇʟꜱ · <code>{len(chans)}</code>",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "fsub_toggle":
        cfg = await _get_config(chat_id)
        cur = cfg.get("force_sub_settings", {}).get("enabled", False)
        await _save_field(chat_id, "force_sub_settings.enabled", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:fsub:{chat_id}"
        return await gs_router(client, q)

    if action == "fsub_add_start":
        _new_session(q.from_user.id, chat_id, "fsub_add")
        await q.message.edit_text(
            f"➕ <b>ᴀᴅᴅ ꜰꜱᴜʙ ᴄʜᴀɴɴᴇʟ</b>\n{_div()}\n\n📝 ꜱᴇɴᴅ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ CANCEL",
                                       callback_data=f"gs:cancel_session:{chat_id}")],
            ]),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "fsub_rm_menu":
        cfg = await _get_config(chat_id)
        chans = cfg.get("force_sub_settings", {}).get("channels") or []
        rows = [[InlineKeyboardButton(f"🗑️ {c}",
                                       callback_data=f"gs:fsub_rm:{chat_id}:{c}")] for c in chans]
        rows.extend(_back(chat_id))
        await q.message.edit_text(
            f"🗑️ <b>ʀᴇᴍᴏᴠᴇ</b>\n{_div()}",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=enums.ParseMode.HTML,
        )
        return await q.answer()

    if action == "fsub_rm":
        p = q.data.split(":")
        target = p[3]
        cfg = await _get_config(chat_id)
        chans = list(cfg.get("force_sub_settings", {}).get("channels") or [])
        try:
            ti = int(target)
        except ValueError:
            ti = target
        if ti in chans:
            chans.remove(ti)
        await _save_field(chat_id, "force_sub_settings.channels", chans)
        await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
        q.data = f"gs:fsub:{chat_id}"
        return await gs_router(client, q)

    # ── GENERIC SECTIONS ──
    if action in ("buttons", "verify", "security", "welcome", "autodel",
                  "req", "stats", "view", "reset"):
        cfg = await _get_config(chat_id)

        if action == "buttons":
            await q.message.edit_text(
                f"📦 <b>ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ</b>\n{_div()}\n\n"
                f"ᴜꜱᴇ ᴛʜᴇꜱᴇ ɢʀᴏᴜᴘ ᴄᴏᴍᴍᴀɴᴅꜱ:\n"
                f"<code>/add_button NAME | URL</code>\n"
                f"<code>/list_buttons</code>\n"
                f"<code>/remove_button NUMBER</code>",
                reply_markup=InlineKeyboardMarkup(_back(chat_id)),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "verify":
            v = cfg.get("verification_settings", {}).get("enabled", False)
            await q.message.edit_text(
                f"🔐 <b>ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ</b>\n{_div()}\n\nꜱᴛᴀᴛᴜꜱ · {_on(v)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"{'🔴 DISABLE' if v else '🟢 ENABLE'}",
                                           callback_data=f"gs:verify_toggle:{chat_id}")],
                    *_back(chat_id),
                ]),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "security":
            sec = cfg.get("security_settings", {})
            rows = []
            for k, label in [("url_blocking", "URL BLOCKING"),
                              ("telegram_links", "TELEGRAM LINKS"),
                              ("admin_bypass", "ADMIN BYPASS")]:
                v = sec.get(k, True)
                rows.append([InlineKeyboardButton(
                    f"{'🟢' if v else '🔴'} {label}",
                    callback_data=f"gs:toggle_sec:{chat_id}:{k}",
                )])
            rows.extend(_back(chat_id))
            await q.message.edit_text(
                f"🛡️ <b>ꜱᴇᴄᴜʀɪᴛʏ</b>\n{_div()}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "welcome":
            w = cfg.get("welcome_settings", {})
            en = w.get("enabled", False)
            ad = w.get("auto_delete", True)
            rows = [
                [InlineKeyboardButton(f"{'🔴 DISABLE' if en else '🟢 ENABLE'}",
                                       callback_data=f"gs:welcome_toggle:{chat_id}")],
                [InlineKeyboardButton(f"{'🔴 AUTODEL OFF' if ad else '🟢 AUTODEL ON'}",
                                       callback_data=f"gs:welcome_autodel:{chat_id}")],
                *_back(chat_id),
            ]
            await q.message.edit_text(
                f"👋 <b>ᴡᴇʟᴄᴏᴍᴇ</b>\n{_div()}\n\n"
                f"ᴇɴᴀʙʟᴇᴅ · {_on(en)}\nᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ · {_on(ad)}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "autodel":
            ads = cfg.get("auto_delete_settings", {})
            rows = []
            for k in ("welcome", "result", "search", "file"):
                v = ads.get(k, True)
                rows.append([InlineKeyboardButton(
                    f"{'🟢' if v else '🔴'} {k.upper()}",
                    callback_data=f"gs:toggle_ad:{chat_id}:{k}",
                )])
            rows.extend(_back(chat_id))
            await q.message.edit_text(
                f"🗑️ <b>ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ</b>\n{_div()}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "req":
            r = cfg.get("request_settings", {})
            rows = []
            for k, label in [("enabled", "REQUESTS"), ("no_result_log", "NO-RESULT LOG"),
                              ("user_pm_update", "USER PM UPDATE")]:
                v = r.get(k, True)
                rows.append([InlineKeyboardButton(
                    f"{'🟢' if v else '🔴'} {label}",
                    callback_data=f"gs:toggle_req:{chat_id}:{k}",
                )])
            rows.extend(_back(chat_id))
            await q.message.edit_text(
                f"📝 <b>ʀᴇǫᴜᴇꜱᴛꜱ</b>\n{_div()}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "stats":
            db = _get_user_db()
            s = {}
            if db is not None:
                try:
                    s = await db["group_statistics"].find_one({"_id": chat_id}) or {}
                except Exception:
                    s = {}
            await q.message.edit_text(
                f"📊 <b>ꜱᴛᴀᴛɪꜱᴛɪᴄꜱ</b>\n{_div()}\n\n"
                f"🔍 ᴛᴏᴅᴀʏ · <code>{s.get('searches_today', 0)}</code>\n"
                f"✅ ꜰᴏᴜɴᴅ · <code>{s.get('results_found', 0)}</code>\n"
                f"❌ ɴᴏᴛ ꜰᴏᴜɴᴅ · <code>{s.get('not_found', 0)}</code>\n"
                f"📦 ꜰɪʟᴇꜱ · <code>{s.get('files_sent', 0)}</code>",
                reply_markup=InlineKeyboardMarkup(_back(chat_id)),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "view":
            ss = cfg.get("search_settings", {})
            await q.message.edit_text(
                f"📋 <b>ᴀʟʟ ꜱᴇᴛᴛɪɴɢꜱ</b>\n{_div()}\n\n"
                f"ᴄᴏɴᴛᴇɴᴛ · <b>{cfg.get('content_mode', 'both').upper()}</b>\n"
                f"ꜱᴇᴀʀᴄʜ · {_on(ss.get('auto_filter', True))}\n"
                f"ᴄᴀᴘᴛɪᴏɴ · {'✅' if cfg.get('custom_caption') else '❌'}\n"
                f"ꜰꜱᴜʙ · <code>{len(cfg.get('force_sub_settings', {}).get('channels') or [])}</code>",
                reply_markup=InlineKeyboardMarkup(_back(chat_id)),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

        if action == "reset":
            await q.message.edit_text(
                f"⚠️ <b>ʀᴇꜱᴇᴛ</b>\n{_div()}\n\nᴛʜɪꜱ ᴡɪʟʟ ʀᴇꜱᴛᴏʀᴇ ᴅᴇꜰᴀᴜʟᴛꜱ.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ RESET",
                                           callback_data=f"gs:reset_do:{chat_id}")],
                    *_back(chat_id),
                ]),
                parse_mode=enums.ParseMode.HTML,
            )
            return await q.answer()

    # ── TOGGLE HANDLERS ──
    if action == "toggle_sec":
        p = q.data.split(":")
        key = p[3]
        cfg = await _get_config(chat_id)
        cur = cfg.get("security_settings", {}).get(key, True)
        await _save_field(chat_id, f"security_settings.{key}", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:security:{chat_id}"
        return await gs_router(client, q)

    if action == "toggle_ad":
        p = q.data.split(":")
        key = p[3]
        cfg = await _get_config(chat_id)
        cur = cfg.get("auto_delete_settings", {}).get(key, True)
        await _save_field(chat_id, f"auto_delete_settings.{key}", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:autodel:{chat_id}"
        return await gs_router(client, q)

    if action == "toggle_req":
        p = q.data.split(":")
        key = p[3]
        cfg = await _get_config(chat_id)
        cur = cfg.get("request_settings", {}).get(key, True)
        await _save_field(chat_id, f"request_settings.{key}", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:req:{chat_id}"
        return await gs_router(client, q)

    if action == "welcome_toggle":
        cfg = await _get_config(chat_id)
        cur = cfg.get("welcome_settings", {}).get("enabled", False)
        await _save_field(chat_id, "welcome_settings.enabled", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:welcome:{chat_id}"
        return await gs_router(client, q)

    if action == "welcome_autodel":
        cfg = await _get_config(chat_id)
        cur = cfg.get("welcome_settings", {}).get("auto_delete", True)
        await _save_field(chat_id, "welcome_settings.auto_delete", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:welcome:{chat_id}"
        return await gs_router(client, q)

    if action == "verify_toggle":
        cfg = await _get_config(chat_id)
        cur = cfg.get("verification_settings", {}).get("enabled", False)
        await _save_field(chat_id, "verification_settings.enabled", not cur)
        await q.answer("ᴛᴏɢɢʟᴇᴅ")
        q.data = f"gs:verify:{chat_id}"
        return await gs_router(client, q)

    if action == "reset_do":
        await _save_field(chat_id, "content_mode", "both")
        await _save_field(chat_id, "custom_caption", None)
        await _save_field(chat_id, "force_sub_settings.enabled", False)
        await _save_field(chat_id, "force_sub_settings.channels", [])
        await q.answer("✅ ʀᴇꜱᴇᴛ")
        q.data = f"gs:refresh:{chat_id}"
        return await gs_router(client, q)

    await q.answer("⚙️ ᴜɴᴋɴᴏᴡɴ ᴀᴄᴛɪᴏɴ", show_alert=True)


# ═══════════════════════════════════════════════════════════
# SESSION TEXT INPUT
# ═══════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-50,
)
async def session_text_handler(client: Client, message: Message):
    if not message.from_user:
        return
    session = _get_session(message.from_user.id)
    if not session:
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    action = session["action"]
    chat_id = session["chat_id"]
    text = (message.text or "").strip()
    logger.info(f"[GADMIN] session input: {action} chat={chat_id} text={text[:40]!r}")

    if action == "set_caption":
        if len(text) < 3:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await _save_field(chat_id, "custom_caption", text)
        _clear_session(message.from_user.id)
        if ok:
            await message.reply_text(f"✅ <b>ᴄᴀᴘᴛɪᴏɴ ꜱᴀᴠᴇᴅ</b>\n\n<code>{text}</code>",
                                      parse_mode=enums.ParseMode.HTML)
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
        return

    if action == "fsub_add":
        target = None
        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target = chat.id
            except Exception as e:
                return await message.reply_text(f"❌ {e}")
        else:
            try:
                target = int(text)
            except ValueError:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")
        cfg = await _get_config(chat_id)
        chans = list(cfg.get("force_sub_settings", {}).get("channels") or [])
        if target in chans:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴀʟʀᴇᴀᴅʏ ᴀᴅᴅᴇᴅ.")
        chans.append(target)
        await _save_field(chat_id, "force_sub_settings.channels", chans)
        _clear_session(message.from_user.id)
        await message.reply_text(f"✅ ᴀᴅᴅᴇᴅ · <code>{target}</code>",
                                  parse_mode=enums.ParseMode.HTML)
        return

    _clear_session(message.from_user.id)


# ═══════════════════════════════════════════════════════════
# BUTTON COMMANDS (in-group)
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("add_button"))
async def cmd_add_button(client: Client, message: Message):
    if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ:\n<code>/add_button NAME | URL</code>",
            parse_mode=enums.ParseMode.HTML,
        )
    name, url = [p.strip() for p in args[1].split("|", 1)]
    cfg = await _get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    btns.append({"name": name[:60], "url": url, "position": len(btns) + 1})
    await _save_field(message.chat.id, "result_buttons", btns)
    await message.reply_text(f"✅ ᴀᴅᴅᴇᴅ · <b>{name}</b>", parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("list_buttons"))
async def cmd_list_buttons(client: Client, message: Message):
    if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return
    cfg = await _get_config(message.chat.id)
    btns = cfg.get("result_buttons") or []
    if not btns:
        return await message.reply_text("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ.")
    lines = ["📦 <b>ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ</b>", _div(), ""]
    for i, b in enumerate(btns, 1):
        lines.append(f"{i}. <b>{b.get('name')}</b> → <code>{b.get('url')}</code>")
    await message.reply_text("\n".join(lines), parse_mode=enums.ParseMode.HTML)


@Client.on_message(filters.command("remove_button"))
async def cmd_remove_button(client: Client, message: Message):
    if message.chat.type not in (enums.ChatType.GROUP, enums.ChatType.SUPERGROUP):
        return
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    args = message.text.split()
    if len(args) < 2:
        return await message.reply_text("ᴜꜱᴀɢᴇ: <code>/remove_button NUMBER</code>",
                                         parse_mode=enums.ParseMode.HTML)
    try:
        idx = int(args[1]) - 1
    except ValueError:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")
    cfg = await _get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    if idx < 0 or idx >= len(btns):
        return await message.reply_text("❌ ᴏᴜᴛ ᴏꜰ ʀᴀɴɢᴇ.")
    removed = btns.pop(idx)
    for i, b in enumerate(btns, 1):
        b["position"] = i
    await _save_field(message.chat.id, "result_buttons", btns)
    await message.reply_text(f"✅ ʀᴇᴍᴏᴠᴇᴅ · <b>{removed.get('name')}</b>",
                              parse_mode=enums.ParseMode.HTML)


logger.info("[GADMIN] plugin loaded successfully")
