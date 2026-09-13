# plugins/group_admin.py
"""
🏨 DOWNTOWN VILLA — GROUP ADMIN CONTROL CENTER
==============================================
Handles /settings and /reload in groups and PM.
All group-config UI lives here.
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import UserNotParticipant
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.config import ADMINS
from group_settings import (
    config_manager,
    permission_manager,
    session_manager,
    button_manager,
    caption_manager,
    link_manager,
    statistics_manager,
)
from group_settings.callbacks import NS, make, parse

logger = logging.getLogger(__name__)

# ═══════════════════════ FANCY FONTS ═══════════════════════
_M_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}
_M_BOLD = {
    **{chr(ord('A') + i): "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[i] for i in range(10)},
}


def fb(s: str) -> str: return "".join(_M_BOLD.get(c, c) for c in s)
def sc(s: str) -> str: return "".join(_M_SC.get(c, c) for c in s)


DIV = "━" * 26
DIV_S = "┄" * 26


# ═══════════════════════ HELPERS ═══════════════════════
def _on(status: bool) -> str:
    return "🟢 ᴏɴ" if status else "🔴 ᴏꜰꜰ"


def _toggle_label(name: str, status: bool) -> str:
    return f"{'🔴' if status else '🟢'} {name}: {'ᴏɴ' if status else 'ᴏꜰꜰ'}"


async def _edit(target, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.warning(f"[GADMIN] edit failed: {type(e).__name__}: {e}")


# ═══════════════════════ /settings COMMAND ═══════════════════════
@Client.on_message(filters.command("settings"))
async def cmd_settings(client: Client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat = message.chat

    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        ok = await permission_manager.can_manage(client, chat.id, user_id)
        if not ok:
            await message.reply_text(
                "❌ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ.\n"
                "ᴏɴʟʏ ɢʀᴏᴜᴘ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ.",
                parse_mode=ParseMode.HTML,
            )
            return

        await config_manager.connect_user_group(user_id, chat.id)
        await config_manager.register_group(chat.id, chat.title or "Group", chat.username)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 OPEN IN PRIVATE CHAT",
                                   callback_data=make(NS.OWNER, "pm_open", str(chat.id)))],
            [InlineKeyboardButton("👥 OPEN HERE",
                                   callback_data=make(NS.MAIN, "open", str(chat.id)))],
        ])
        await message.reply_text(
            "⚙️ <b>ᴡʜᴇʀᴇ ᴅᴏ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴏᴘᴇɴ ꜱᴇᴛᴛɪɴɢꜱ?</b>",
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        return

    if chat.type == ChatType.PRIVATE:
        await _show_connected_groups(client, message, user_id)


async def _show_connected_groups(client: Client, target, user_id: int):
    group_ids = await config_manager.get_connected_groups(user_id)
    if not group_ids:
        text = (
            "⚙️ <b>ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ</b>\n"
            f"{DIV}\n\n"
            "ʏᴏᴜ ʜᴀᴠᴇ ɴᴏ ᴄᴏɴɴᴇᴄᴛᴇᴅ ɢʀᴏᴜᴘꜱ ʏᴇᴛ.\n\n"
            "ᴛᴏ ᴄᴏɴɴᴇᴄᴛ ᴀ ɢʀᴏᴜᴘ:\n"
            "1️⃣ ɢᴏ ᴛᴏ ᴛʜᴀᴛ ɢʀᴏᴜᴘ\n"
            "2️⃣ ꜱᴇɴᴅ <code>/settings</code>\n"
            "3️⃣ ᴘɪᴄᴋ <b>ᴏᴘᴇɴ ɪɴ ᴘʀɪᴠᴀᴛᴇ ᴄʜᴀᴛ</b>"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))
        ]])
        await target.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True)
        return

    rows: List[List[InlineKeyboardButton]] = []
    for gid in group_ids[:10]:
        title = f"Group {gid}"
        try:
            chat = await client.get_chat(gid)
            title = chat.title or title
        except Exception:
            pass
        label = title.upper()[:40]
        rows.append([InlineKeyboardButton(
            f"👥 {label}", callback_data=make(NS.MAIN, "open", str(gid))
        )])

    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))])

    text = "\n".join([
        "⚙️ <b>ɢʀᴏᴜᴘ ꜱᴇᴛᴛɪɴɢꜱ</b>",
        DIV,
        "",
        "⚠️ ꜱᴇʟᴇᴄᴛ ᴛʜᴇ ɢʀᴏᴜᴘ ᴡʜᴏꜱᴇ ꜱᴇᴛᴛɪɴɢꜱ ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʜᴀɴɢᴇ.",
    ])
    await target.reply_text(text, reply_markup=InlineKeyboardMarkup(rows),
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)


# ═══════════════════════ /reload COMMAND ═══════════════════════
@Client.on_message(filters.command("reload"))
async def cmd_reload(client: Client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        ok = await permission_manager.can_manage(client, message.chat.id, user_id)
        if not ok:
            await message.reply_text("❌ ᴏɴʟʏ ᴀᴅᴍɪɴꜱ ᴄᴀɴ ᴜꜱᴇ ᴛʜɪꜱ.")
            return
        await config_manager.connect_user_group(user_id, message.chat.id)
        await config_manager.register_group(
            message.chat.id, message.chat.title or "Group", message.chat.username
        )
        await message.reply_text(
            "✅ ɢʀᴏᴜᴘ ʀᴇʟᴏᴀᴅᴇᴅ.\n"
            "ɴᴏᴡ ʏᴏᴜ ᴄᴀɴ ᴍᴀɴᴀɢᴇ ɪᴛ ꜰʀᴏᴍ ᴘᴍ ᴜꜱɪɴɢ /settings."
        )
        return

    if message.chat.type == ChatType.PRIVATE:
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.reply_text("ᴜꜱᴀɢᴇ: <code>/reload -100xxxxxxxxxx</code>",
                                     parse_mode=ParseMode.HTML)
            return
        try:
            gid = int(args[1].strip())
        except ValueError:
            await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɢʀᴏᴜᴘ ɪᴅ.")
            return
        ok = await permission_manager.can_manage(client, gid, user_id)
        if not ok:
            await message.reply_text("❌ ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀɴ ᴀᴅᴍɪɴ ᴏꜰ ᴛʜᴀᴛ ɢʀᴏᴜᴘ.")
            return
        await config_manager.connect_user_group(user_id, gid)
        try:
            chat = await client.get_chat(gid)
            title = chat.title or str(gid)
        except Exception:
            title = str(gid)
        await config_manager.register_group(gid, title)
        await message.reply_text(
            f"✅ ʟɪɴᴋᴇᴅ <b>{title}</b> ᴛᴏ ʏᴏᴜʀ ᴘᴍ.",
            parse_mode=ParseMode.HTML,
        )


# ═══════════════════════ MAIN SETTINGS MENU ═══════════════════════
async def render_main_menu(chat_id: int) -> tuple:
    cfg = await config_manager.get_config(chat_id)

    content_icon = {
        "movies": "🎬 ᴍᴏᴠɪᴇꜱ ᴏɴʟʏ",
        "series": "📺 ꜱᴇʀɪᴇꜱ ᴏɴʟʏ",
        "both": "🎬📺 ᴍᴏᴠɪᴇꜱ + ꜱᴇʀɪᴇꜱ",
    }.get(cfg.get("content_mode", "both"), "?")

    fsub_count = len(cfg.get("force_sub_settings", {}).get("channels") or [])

    text = "\n".join([
        "⚙️ <b>" + fb("GROUP SETTINGS") + "</b>",
        DIV, "",
        f"👥 {sc('group')} · <b>{cfg.get('title') or chat_id}</b>",
        f"🆔 {sc('id')} · <code>{chat_id}</code>",
        "",
        f"📚 {sc('content')} · {content_icon}",
        f"🔎 {sc('search')} · {_on(cfg['search_settings'].get('auto_filter', True))}",
        f"📦 {sc('result mode')} · 🔘 {cfg.get('result_mode', 'button').upper()}",
        f"📝 {sc('custom caption')} · {_on(bool(cfg.get('custom_caption')))}",
        f"📢 {sc('force sub')} · {fsub_count} ᴄʜᴀɴɴᴇʟꜱ",
        f"🔐 {sc('verification')} · {_on(cfg['verification_settings'].get('enabled'))}",
        f"👋 {sc('welcome')} · {_on(cfg['welcome_settings'].get('enabled'))}",
        f"🛡️ {sc('security')} · {_on(cfg['security_settings'].get('url_blocking'))}",
        f"📝 {sc('requests')} · {_on(cfg['request_settings'].get('enabled'))}",
        "",
        DIV_S,
        f"🔗 {sc('connected')} · 🟢",
    ])

    cid = str(chat_id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 CONTENT MODE", callback_data=make(NS.CONTENT, "open", cid))],
        [InlineKeyboardButton("🔎 SEARCH & FILTER", callback_data=make(NS.SEARCH, "open", cid))],
        [InlineKeyboardButton("📦 RESULT BUTTONS", callback_data=make(NS.BUTTONS, "open", cid))],
        [InlineKeyboardButton("📝 FILE CAPTION", callback_data=make(NS.CAPTIONS, "open", cid))],
        [InlineKeyboardButton("🎬 IMDB / METADATA", callback_data=make(NS.METADATA, "open", cid))],
        [InlineKeyboardButton("📢 FORCE SUBSCRIBE", callback_data=make(NS.FSUB, "open", cid))],
        [InlineKeyboardButton("🔐 VERIFICATION", callback_data=make(NS.VERIFY, "open", cid))],
        [InlineKeyboardButton("🛡️ SECURITY", callback_data=make(NS.SECURITY, "open", cid))],
        [InlineKeyboardButton("👋 WELCOME", callback_data=make(NS.WELCOME, "open", cid))],
        [InlineKeyboardButton("🗑️ AUTO DELETE", callback_data=make(NS.AUTODEL, "open", cid))],
        [InlineKeyboardButton("📝 REQUEST SYSTEM", callback_data=make(NS.REQ, "open", cid))],
        [InlineKeyboardButton("🔗 GROUP LINKS", callback_data=make(NS.LINKS, "open", cid))],
        [InlineKeyboardButton("📊 GROUP STATISTICS", callback_data=make(NS.STATS, "open", cid))],
        [InlineKeyboardButton("📋 VIEW ALL SETTINGS", callback_data=make(NS.VIEW, "all", cid))],
        [InlineKeyboardButton("♻️ RESET GROUP", callback_data=make(NS.RESET, "open", cid))],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=make(NS.MAIN, "open", cid)),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ])
    return text, kb


@Client.on_callback_query(filters.regex(r"^gs:main:(open|close)(?::(-?\d+))?$"))
async def cb_main(client: Client, q: CallbackQuery):
    _, action, extra = parse(q.data)
    if action == "close":
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
        return

    chat_id = int(extra) if extra else q.message.chat.id
    if chat_id == 0:
        chat_id = q.message.chat.id

    ok = await permission_manager.can_manage(client, chat_id, q.from_user.id)
    if not ok:
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

    text, kb = await render_main_menu(chat_id)
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:owner:pm_open:(-?\d+)$"))
async def cb_owner_pm_open(client: Client, q: CallbackQuery):
    _, _, gid_str = parse(q.data)
    try:
        chat_id = int(gid_str)
    except (TypeError, ValueError):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    ok = await permission_manager.can_manage(client, chat_id, q.from_user.id)
    if not ok:
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

    await config_manager.connect_user_group(q.from_user.id, chat_id)
    text, kb = await render_main_menu(chat_id)
    try:
        await client.send_message(
            chat_id=q.from_user.id, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[GADMIN] pm send failed: {e}")
    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("👤 OPENED IN PM",
                                   callback_data=make(NS.MAIN, "close"))
        ]]))
    except Exception:
        pass
    await q.answer("✅ ᴏᴘᴇɴᴇᴅ ɪɴ ᴘᴍ")


# ═══════════════════════ CONTENT MODE ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:content:open:(-?\d+)$"))
async def cb_content_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    current = cfg.get("content_mode", "both")
    label = {
        "movies": "🎬 ᴍᴏᴠɪᴇꜱ ᴏɴʟʏ",
        "series": "📺 ꜱᴇʀɪᴇꜱ ᴏɴʟʏ",
        "both": "🎬📺 ᴍᴏᴠɪᴇꜱ + ꜱᴇʀɪᴇꜱ",
    }.get(current, current)

    text = "\n".join([
        "📚 <b>" + fb("CONTENT MODE") + "</b>",
        DIV, "",
        f"ᴄᴜʀʀᴇɴᴛ · <b>{label}</b>",
        "",
        DIV_S,
        "ꜱᴇʟᴇᴄᴛ ᴀ ᴍᴏᴅᴇ:",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MOVIES ONLY",
                               callback_data=make(NS.CONTENT, "set", f"{chat_id}:movies"))],
        [InlineKeyboardButton("📺 SERIES ONLY",
                               callback_data=make(NS.CONTENT, "set", f"{chat_id}:series"))],
        [InlineKeyboardButton("🎬📺 MOVIES + SERIES",
                               callback_data=make(NS.CONTENT, "set", f"{chat_id}:both"))],
        [InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:content:set:(-?\d+):(movies|series|both)$"))
async def cb_content_set(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    mode = parts[4]

    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    await config_manager.set_field(chat_id, "content_mode", mode)
    label = {
        "movies": "🎬 ᴍᴏᴠɪᴇꜱ ᴏɴʟʏ",
        "series": "📺 ꜱᴇʀɪᴇꜱ ᴏɴʟʏ",
        "both": "🎬📺 ᴍᴏᴠɪᴇꜱ + ꜱᴇʀɪᴇꜱ",
    }.get(mode, mode)

    cfg = await config_manager.get_config(chat_id)
    text = "\n".join([
        "✅ <b>" + fb("CONTENT MODE UPDATED") + "</b>",
        DIV, "",
        f"ɢʀᴏᴜᴘ · <b>{cfg.get('title') or chat_id}</b>",
        f"ɴᴇᴡ ᴍᴏᴅᴇ · <b>{label}</b>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.CONTENT, "open", str(chat_id))),
        InlineKeyboardButton("🏠 HOME", callback_data=make(NS.MAIN, "open", str(chat_id))),
    ]])
    await _edit(q, text, kb)
    await q.answer("✅ ᴜᴘᴅᴀᴛᴇᴅ")


# ═══════════════════════ SEARCH & FILTER ═══════════════════════
SEARCH_TOGGLES = [
    ("auto_filter", "AUTO FILTER"),
    ("spell_check", "SPELL CHECK"),
    ("query_cleaning", "QUERY CLEANING"),
    ("quality_filter", "QUALITY FILTER"),
    ("language_filter", "LANGUAGE FILTER"),
    ("season_filter", "SEASON FILTER"),
]


@Client.on_callback_query(filters.regex(r"^gs:search:open:(-?\d+)$"))
async def cb_search_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    ss = cfg.get("search_settings", {})

    lines = ["🔎 <b>" + fb("SEARCH & FILTER") + "</b>", DIV, ""]
    for key, label in SEARCH_TOGGLES:
        lines.append(f"{sc(label.lower())} · {_on(ss.get(key, True))}")
    lines.append("")
    lines.append(f"📊 ʀᴇꜱᴜʟᴛꜱ ᴘᴇʀ ᴘᴀɢᴇ · <code>{ss.get('results_per_page', 10)}</code>")
    lines.append(f"⏱️ ꜱᴇᴀʀᴄʜ ᴄᴏᴏʟᴅᴏᴡɴ · <code>{ss.get('search_cooldown', 2)}s</code>")
    lines.append("")
    lines.append(DIV_S)
    lines.append("ᴛᴏɢɢʟᴇ ᴀɴʏ ꜱᴇᴛᴛɪɴɢ:")

    rows: List[List[InlineKeyboardButton]] = []
    for key, label in SEARCH_TOGGLES:
        val = ss.get(key, True)
        rows.append([InlineKeyboardButton(
            _toggle_label(label, val),
            callback_data=make(NS.SEARCH, "toggle", f"{chat_id}:{key}"),
        )])
    rows.append([
        InlineKeyboardButton("🔢 RESULTS PER PAGE",
                              callback_data=make(NS.SEARCH, "rpp_menu", cid)),
        InlineKeyboardButton("⏱️ SEARCH COOLDOWN",
                              callback_data=make(NS.SEARCH, "cd_menu", cid)),
    ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:search:toggle:(-?\d+):(\w+)$"))
async def cb_search_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    key = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    current = cfg.get("search_settings", {}).get(key, True)
    await config_manager.set_field(chat_id, f"search_settings.{key}", not current)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_search_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:search:rpp_menu:(-?\d+)$"))
async def cb_search_rpp_menu(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("search_settings", {}).get("results_per_page", 10)

    options = [5, 10, 15, 20]
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if o == cur else ''}{o}",
        callback_data=make(NS.SEARCH, "set_rpp", f"{chat_id}:{o}")
    )] for o in options]
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=make(NS.SEARCH, "open", cid))])
    await _edit(
        q,
        f"🔢 <b>{fb('RESULTS PER PAGE')}</b>\n{DIV}\n\nᴄᴜʀʀᴇɴᴛ · <b>{cur}</b>\n\nᴄʜᴏᴏꜱᴇ:",
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:search:set_rpp:(-?\d+):(\d+)$"))
async def cb_search_set_rpp(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await config_manager.set_field(chat_id, "search_settings.results_per_page", value)
    await q.answer(f"✅ {value}")
    await cb_search_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:search:cd_menu:(-?\d+)$"))
async def cb_search_cd_menu(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("search_settings", {}).get("search_cooldown", 2)

    options = [0, 1, 2, 3, 5, 10]
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if o == cur else ''}{o}ꜱ",
        callback_data=make(NS.SEARCH, "set_cd", f"{chat_id}:{o}")
    )] for o in options]
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=make(NS.SEARCH, "open", cid))])
    await _edit(
        q,
        f"⏱️ <b>{fb('SEARCH COOLDOWN')}</b>\n{DIV}\n\nᴄᴜʀʀᴇɴᴛ · <b>{cur}s</b>\n\nᴄʜᴏᴏꜱᴇ:",
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:search:set_cd:(-?\d+):(\d+)$"))
async def cb_search_set_cd(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    value = int(parts[4])
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await config_manager.set_field(chat_id, "search_settings.search_cooldown", value)
    await q.answer(f"✅ {value}s")
    await cb_search_open(client, q)


# ═══════════════════════ RESULT BUTTONS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:buttons:open:(-?\d+)$"))
async def cb_buttons_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    lines = ["📦 <b>" + fb("RESULT BUTTONS") + "</b>", DIV, ""]
    if not buttons:
        lines.append("⚪ ɴᴏ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ.")
    else:
        for i, b in enumerate(buttons, 1):
            status = "🟢" if b.get("enabled", True) else "🔴"
            lines.append(f"{i}. {status} <b>{b.get('name', '?')}</b>")
    lines.append("")
    lines.append(f"ᴛᴏᴛᴀʟ · <code>{len(buttons)}</code>")
    lines.append("")
    lines.append(DIV_S)

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("➕ ADD RESULT BUTTON",
                               callback_data=make(NS.BUTTONS, "add", cid))],
    ]
    if buttons:
        rows += [
            [InlineKeyboardButton("✏️ EDIT RESULT BUTTON",
                                   callback_data=make(NS.BUTTONS, "edit_pick", cid))],
            [InlineKeyboardButton("🗑️ REMOVE RESULT BUTTON",
                                   callback_data=make(NS.BUTTONS, "remove_pick", cid))],
            [InlineKeyboardButton("🔀 REORDER BUTTONS",
                                   callback_data=make(NS.BUTTONS, "reorder", cid))],
            [InlineKeyboardButton("👁️ PREVIEW",
                                   callback_data=make(NS.BUTTONS, "preview", cid))],
        ]
    rows += [
        [InlineKeyboardButton("♻️ RESET BUTTONS",
                               callback_data=make(NS.BUTTONS, "reset_confirm", cid))],
        [InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ]
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:add:(-?\d+)$"))
async def cb_buttons_add(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "add_button",
        {"chat_id": chat_id},
        prompt_msg_id=q.message.id,
    )
    if not token:
        await q.answer("❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ", show_alert=True)
        return

    text = "\n".join([
        "➕ <b>" + fb("ADD RESULT BUTTON") + "</b>",
        DIV, "",
        "ꜱᴛᴇᴘ <b>1/2</b>",
        "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ɴᴀᴍᴇ.",
        "",
        f"<i>ᴇxᴀᴍᴘʟᴇ: 📥 ꜱʜᴀʀᴇ ꜰɪʟᴇ</i>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:edit_pick:(-?\d+)$"))
async def cb_buttons_edit_pick(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    if not buttons:
        await q.answer("ɴᴏ ʙᴜᴛᴛᴏɴꜱ", show_alert=True); return

    rows = [[InlineKeyboardButton(
        f"✏️ {b.get('name', '?')}",
        callback_data=make(NS.BUTTONS, "edit_pick_btn", f"{chat_id}:{b.get('id')}")
    )] for b in buttons]
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "open", cid))])

    await _edit(
        q,
        f"✏️ <b>{fb('EDIT RESULT BUTTON')}</b>\n{DIV}\n\nꜱᴇʟᴇᴄᴛ ᴀ ʙᴜᴛᴛᴏɴ:",
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:edit_pick_btn:(-?\d+):(\w+)$"))
async def cb_buttons_edit_pick_btn(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    btn = next((b for b in buttons if b.get("id") == btn_id), None)
    if not btn:
        await q.answer("ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True); return

    text = "\n".join([
        "✏️ <b>" + fb("EDIT BUTTON") + "</b>",
        DIV, "",
        f"ᴄᴜʀʀᴇɴᴛ ɴᴀᴍᴇ · <b>{btn.get('name', '?')}</b>",
        f"ᴄᴜʀʀᴇɴᴛ ᴜʀʟ · <code>{btn.get('url', '?')}</code>",
        f"ᴇɴᴀʙʟᴇᴅ · {_on(btn.get('enabled', True))}",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ CHANGE NAME",
                               callback_data=make(NS.BUTTONS, "edit_name", f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("🔗 CHANGE LINK",
                               callback_data=make(NS.BUTTONS, "edit_url", f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("🔄 ENABLE / DISABLE",
                               callback_data=make(NS.BUTTONS, "edit_toggle", f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("◀️ BACK",
                               callback_data=make(NS.BUTTONS, "edit_pick", str(chat_id))),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:edit_name:(-?\d+):(\w+)$"))
async def cb_buttons_edit_name(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "edit_button_name",
        {"chat_id": chat_id, "btn_id": btn_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "✏️ <b>" + fb("CHANGE BUTTON NAME") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ɴᴇᴡ ɴᴀᴍᴇ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:edit_url:(-?\d+):(\w+)$"))
async def cb_buttons_edit_url(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "edit_button_url",
        {"chat_id": chat_id, "btn_id": btn_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "🔗 <b>" + fb("CHANGE BUTTON LINK") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ɴᴇᴡ ᴜʀʟ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:edit_toggle:(-?\d+):(\w+)$"))
async def cb_buttons_edit_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    res = await button_manager.toggle_enabled(chat_id, btn_id)
    if res is None:
        await q.answer("ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True); return
    await q.answer("✅ ᴛᴏɢɢʟᴇᴅ")
    await cb_buttons_edit_pick_btn(client, q)


@Client.on_callback_query(filters.regex(r"^gs:buttons:remove_pick:(-?\d+)$"))
async def cb_buttons_remove_pick(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    if not buttons:
        await q.answer("ɴᴏ ʙᴜᴛᴛᴏɴꜱ", show_alert=True); return

    rows = [[InlineKeyboardButton(
        f"🗑️ {b.get('name', '?')}",
        callback_data=make(NS.BUTTONS, "remove_btn", f"{chat_id}:{b.get('id')}")
    )] for b in buttons]
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "open", cid))])
    await _edit(
        q,
        f"🗑️ <b>{fb('REMOVE RESULT BUTTON')}</b>\n{DIV}\n\nꜱᴇʟᴇᴄᴛ ᴀ ʙᴜᴛᴛᴏɴ:",
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:remove_btn:(-?\d+):(\w+)$"))
async def cb_buttons_remove_btn(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    btn = next((b for b in buttons if b.get("id") == btn_id), None)
    if not btn:
        await q.answer("ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True); return

    text = "\n".join([
        "⚠️ <b>" + fb("CONFIRM REMOVAL") + "</b>",
        DIV, "",
        "ʀᴇᴍᴏᴠᴇ:",
        f"<b>{btn.get('name', '?')}</b>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ REMOVE",
                               callback_data=make(NS.BUTTONS, "remove_confirm",
                                                  f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.BUTTONS, "open", str(chat_id)))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:remove_confirm:(-?\d+):(\w+)$"))
async def cb_buttons_remove_confirm(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    ok = await button_manager.remove_button(chat_id, btn_id)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
    await cb_buttons_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:buttons:reorder:(-?\d+)$"))
async def cb_buttons_reorder(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    lines = ["🔀 <b>" + fb("REORDER BUTTONS") + "</b>", DIV, ""]
    for i, b in enumerate(buttons, 1):
        lines.append(f"{i}. {b.get('name', '?')}")
    lines.append("")
    lines.append("ꜱᴇʟᴇᴄᴛ ᴀ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴍᴏᴠᴇ:")

    rows = [[InlineKeyboardButton(
        f"↕️ {b.get('name', '?')}",
        callback_data=make(NS.BUTTONS, "move", f"{chat_id}:{b.get('id')}")
    )] for b in buttons]
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=make(NS.BUTTONS, "open", cid))])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:move:(-?\d+):(\w+)$"))
async def cb_buttons_move(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    btn = next((b for b in buttons if b.get("id") == btn_id), None)
    if not btn:
        await q.answer("ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True); return

    text = "\n".join([
        "🔀 <b>" + fb("MOVE BUTTON") + "</b>",
        DIV, "",
        f"<b>{btn.get('name', '?')}</b>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬆️ MOVE UP",
                               callback_data=make(NS.BUTTONS, "up", f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("⬇️ MOVE DOWN",
                               callback_data=make(NS.BUTTONS, "down", f"{chat_id}:{btn_id}"))],
        [InlineKeyboardButton("◀️ BACK",
                               callback_data=make(NS.BUTTONS, "reorder", str(chat_id)))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:(up|down):(-?\d+):(\w+)$"))
async def cb_buttons_move_do(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    action = parts[2]
    chat_id = int(parts[3])
    btn_id = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    if action == "up":
        ok = await button_manager.move_up(chat_id, btn_id)
    else:
        ok = await button_manager.move_down(chat_id, btn_id)

    await q.answer("✅" if ok else "ᴄᴀɴɴᴏᴛ ᴍᴏᴠᴇ")
    await cb_buttons_reorder(client, q)


@Client.on_callback_query(filters.regex(r"^gs:buttons:preview:(-?\d+)$"))
async def cb_buttons_preview(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    buttons = await button_manager.list_buttons(chat_id)
    rows = [[InlineKeyboardButton(b.get("name", "?"), url=b.get("url", "https://t.me/"))
             for b in buttons[i:i+2]]
            for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=make(NS.BUTTONS, "open", cid))])

    text = "\n".join([
        "👁️ <b>" + fb("BUTTON PREVIEW") + "</b>",
        DIV, "",
        "🎬 <b>SAMPLE FILE</b>",
        "",
        "🎞️ Qᴜᴀʟɪᴛʏ · <code>1080P</code>",
        "🧬 Cᴏᴅᴇᴄ · <code>HEVC</code>",
        "🔊 Aᴜᴅɪᴏ · <code>MALAYALAM</code>",
        "📝 Sᴜʙᴛɪᴛʟᴇ · <code>ENGLISH</code>",
        "💾 Sɪᴢᴇ · <code>2.4 GB</code>",
    ])
    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:reset_confirm:(-?\d+)$"))
async def cb_buttons_reset_confirm(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    text = "\n".join([
        "♻️ <b>" + fb("RESET RESULT BUTTONS") + "</b>",
        DIV, "",
        "ᴛʜɪꜱ ᴡɪʟʟ ʀᴇꜱᴛᴏʀᴇ ᴅᴇꜰᴀᴜʟᴛ ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ RESET",
                               callback_data=make(NS.BUTTONS, "reset_do", cid))],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=make(NS.BUTTONS, "open", cid))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:buttons:reset_do:(-?\d+)$"))
async def cb_buttons_reset_do(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await button_manager.reset_buttons(chat_id)
    await q.answer("✅ ʀᴇꜱᴇᴛ")
    await cb_buttons_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:buttons:cancel:(\w+)$"))
async def cb_buttons_cancel(client: Client, q: CallbackQuery):
    _, _, token = parse(q.data)
    session = await session_manager.get(token)
    if session:
        chat_id = session.get("chat_id")
        await session_manager.cancel(token)
    else:
        chat_id = q.message.chat.id

    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    text, kb = await render_main_menu(chat_id)
    await _edit(q, text, kb)


# ═══════════════════════ CAPTIONS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:captions:open:(-?\d+)$"))
async def cb_captions_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    custom = await caption_manager.get_caption(chat_id)
    mode = "🟢 ᴄᴜꜱᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ" if custom else "⚪ ɢʟᴏʙᴀʟ ᴄᴀᴘᴛɪᴏɴ"
    text = "\n".join([
        "📝 <b>" + fb("FILE CAPTION") + "</b>",
        DIV, "",
        f"ᴍᴏᴅᴇ · <b>{mode}</b>",
        "",
        DIV_S,
    ])
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✏️ SET CAPTION",
                               callback_data=make(NS.CAPTIONS, "set", cid))],
        [InlineKeyboardButton("👁️ PREVIEW CAPTION",
                               callback_data=make(NS.CAPTIONS, "preview", cid))],
        [InlineKeyboardButton("📋 AVAILABLE VARIABLES",
                               callback_data=make(NS.CAPTIONS, "vars", cid))],
    ]
    if custom:
        rows.append([InlineKeyboardButton("♻️ USE GLOBAL CAPTION",
                                           callback_data=make(NS.CAPTIONS, "remove", cid))])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(text), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:captions:set:(-?\d+)$"))
async def cb_captions_set(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "set_caption",
        {"chat_id": chat_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "✏️ <b>" + fb("SET CAPTION") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ ᴛᴇᴍᴘʟᴀᴛᴇ.",
        "",
        "<i>ᴜꜱᴇ ᴠᴀʀɪᴀʙʟᴇꜱ ʟɪᴋᴇ {ᴛɪᴛʟᴇ}, {Qᴜᴀʟɪᴛʏ} ᴇᴛᴄ.</i>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 VARIABLES",
                               callback_data=make(NS.CAPTIONS, "vars", cid))],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=make(NS.CAPTIONS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:captions:preview:(-?\d+)$"))
async def cb_captions_preview(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    preview = await caption_manager.preview(chat_id)
    text = "\n".join([
        "👁️ <b>" + fb("CAPTION PREVIEW") + "</b>",
        DIV, "",
        preview,
        "",
        DIV_S,
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.CAPTIONS, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ]])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:captions:vars:(-?\d+)$"))
async def cb_captions_vars(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    from group_settings.captions import AVAILABLE_VARIABLES
    lines = ["📋 <b>" + fb("AVAILABLE VARIABLES") + "</b>", DIV, ""]
    for v in AVAILABLE_VARIABLES:
        lines.append(f"• <code>{{{v}}}</code>")
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.CAPTIONS, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ]])
    await _edit(q, "\n".join(lines), kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:captions:remove:(-?\d+)$"))
async def cb_captions_remove(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await caption_manager.remove_caption(chat_id)
    await q.answer("✅ ɢʟᴏʙᴀʟ ᴄᴀᴘᴛɪᴏɴ ᴀᴄᴛɪᴠᴇ")
    await cb_captions_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:captions:cancel:(\w+)$"))
async def cb_captions_cancel(client: Client, q: CallbackQuery):
    _, _, token = parse(q.data)
    session = await session_manager.get(token)
    if session:
        chat_id = session.get("chat_id")
        await session_manager.cancel(token)
    else:
        chat_id = q.message.chat.id
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    await cb_captions_open(client, q)


# ═══════════════════════ LINKS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:links:open:(-?\d+)$"))
async def cb_links_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    movie = await link_manager.get_movie_link(chat_id)
    series = await link_manager.get_series_link(chat_id)

    text = "\n".join([
        "🔗 <b>" + fb("GROUP LINKS") + "</b>",
        DIV, "",
        f"🎬 ᴍᴏᴠɪᴇ ɢʀᴏᴜᴘ · {movie or '—'}",
        f"📺 ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ · {series or '—'}",
    ])
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🎬 SET MOVIE GROUP",
                               callback_data=make(NS.LINKS, "set_movie", cid))],
        [InlineKeyboardButton("📺 SET SERIES GROUP",
                               callback_data=make(NS.LINKS, "set_series", cid))],
    ]
    if movie:
        rows.append([InlineKeyboardButton("🗑️ REMOVE MOVIE LINK",
                                           callback_data=make(NS.LINKS, "rm_movie", cid))])
    if series:
        rows.append([InlineKeyboardButton("🗑️ REMOVE SERIES LINK",
                                           callback_data=make(NS.LINKS, "rm_series", cid))])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:links:set_movie:(-?\d+)$"))
async def cb_links_set_movie(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "set_movie_link",
        {"chat_id": chat_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "🎬 <b>" + fb("SET MOVIE GROUP") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ᴍᴏᴠɪᴇ ɢʀᴏᴜᴘ ʟɪɴᴋ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.LINKS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:links:set_series:(-?\d+)$"))
async def cb_links_set_series(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    token = await session_manager.start(
        q.from_user.id, chat_id, "set_series_link",
        {"chat_id": chat_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "📺 <b>" + fb("SET SERIES GROUP") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ ʟɪɴᴋ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.LINKS, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:links:rm_movie:(-?\d+)$"))
async def cb_links_rm_movie(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await link_manager.remove_movie_link(chat_id)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_links_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:links:rm_series:(-?\d+)$"))
async def cb_links_rm_series(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    await link_manager.remove_series_link(chat_id)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_links_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:links:cancel:(\w+)$"))
async def cb_links_cancel(client: Client, q: CallbackQuery):
    _, _, token = parse(q.data)
    session = await session_manager.get(token)
    if session:
        await session_manager.cancel(token)
        chat_id = session.get("chat_id")
    else:
        chat_id = q.message.chat.id
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    await cb_links_open(client, q)


# ═══════════════════════ METADATA ═══════════════════════
METADATA_TOGGLES = [
    ("poster", "POSTER"),
    ("rating", "RATING"),
    ("genre", "GENRE"),
    ("year", "YEAR"),
    ("language", "LANGUAGE"),
]


@Client.on_callback_query(filters.regex(r"^gs:metadata:open:(-?\d+)$"))
async def cb_metadata_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    ms = cfg.get("metadata_settings", {})

    lines = ["🎬 <b>" + fb("IMDB / METADATA") + "</b>", DIV, ""]
    for k, label in METADATA_TOGGLES:
        lines.append(f"{sc(label.lower())} · {_on(ms.get(k, True))}")

    rows = [[InlineKeyboardButton(
        _toggle_label(label, ms.get(k, True)),
        callback_data=make(NS.METADATA, "toggle", f"{chat_id}:{k}")
    )] for k, label in METADATA_TOGGLES]
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:metadata:toggle:(-?\d+):(\w+)$"))
async def cb_metadata_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    key = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("metadata_settings", {}).get(key, True)
    await config_manager.set_field(chat_id, f"metadata_settings.{key}", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_metadata_open(client, q)


# ═══════════════════════ FORCE SUBSCRIBE ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:fsub:open:(-?\d+)$"))
async def cb_fsub_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    fs = cfg.get("force_sub_settings", {})
    chans = fs.get("channels") or []
    enabled = fs.get("enabled", False)

    lines = [
        "📢 <b>" + fb("FORCE SUBSCRIBE") + "</b>",
        DIV, "",
        f"ꜱᴛᴀᴛᴜꜱ · {_on(enabled)}",
        "",
    ]
    if not chans:
        lines.append("⚪ ɴᴏ ᴄʜᴀɴɴᴇʟꜱ ʏᴇᴛ.")
    else:
        for i, ch in enumerate(chans, 1):
            lines.append(f"{i}. <code>{ch}</code>")
    lines.append("")
    lines.append(f"ᴛᴏᴛᴀʟ · <code>{len(chans)}</code>")

    rows = [
        [InlineKeyboardButton(
            "🔴 DISABLE" if enabled else "🟢 ENABLE",
            callback_data=make(NS.FSUB, "toggle", cid)
        )],
        [InlineKeyboardButton("➕ ADD CHANNEL",
                               callback_data=make(NS.FSUB, "add", cid))],
    ]
    if chans:
        rows.append([InlineKeyboardButton("🗑️ REMOVE CHANNEL",
                                           callback_data=make(NS.FSUB, "rm_pick", cid))])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:fsub:toggle:(-?\d+)$"))
async def cb_fsub_toggle(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("force_sub_settings", {}).get("enabled", False)
    await config_manager.set_field(chat_id, "force_sub_settings.enabled", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_fsub_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:fsub:add:(-?\d+)$"))
async def cb_fsub_add(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    token = await session_manager.start(
        q.from_user.id, chat_id, "fsub_add",
        {"chat_id": chat_id},
        prompt_msg_id=q.message.id,
    )
    text = "\n".join([
        "➕ <b>" + fb("ADD FORCE SUB CHANNEL") + "</b>",
        DIV, "",
        "📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ CANCEL", callback_data=make(NS.FSUB, "cancel", token))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:fsub:rm_pick:(-?\d+)$"))
async def cb_fsub_rm_pick(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    chans = cfg.get("force_sub_settings", {}).get("channels") or []
    rows = [[InlineKeyboardButton(
        f"🗑️ {ch}",
        callback_data=make(NS.FSUB, "rm", f"{chat_id}:{ch}")
    )] for ch in chans]
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=make(NS.FSUB, "open", cid))])
    await _edit(
        q,
        f"🗑️ <b>{fb('REMOVE CHANNEL')}</b>\n{DIV}\n\nꜱᴇʟᴇᴄᴛ:",
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:fsub:rm:(-?\d+):(-?\d+)$"))
async def cb_fsub_rm(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    target = int(parts[4])
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    chans = list(cfg.get("force_sub_settings", {}).get("channels") or [])
    if target in chans:
        chans.remove(target)
        await config_manager.set_field(chat_id, "force_sub_settings.channels", chans)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_fsub_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:fsub:cancel:(\w+)$"))
async def cb_fsub_cancel(client: Client, q: CallbackQuery):
    _, _, token = parse(q.data)
    session = await session_manager.get(token)
    if session:
        await session_manager.cancel(token)
        chat_id = session.get("chat_id")
    else:
        chat_id = q.message.chat.id
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")
    await cb_fsub_open(client, q)


# ═══════════════════════ VERIFICATION ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:verify:open:(-?\d+)$"))
async def cb_verify_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    vs = cfg.get("verification_settings", {})

    lines = [
        "🔐 <b>" + fb("VERIFICATION") + "</b>",
        DIV, "",
        f"ꜱᴛᴀᴛᴜꜱ · {_on(vs.get('enabled'))}",
        "",
        f"ꜱʜᴏʀᴛᴇɴᴇʀ 1 · {'✅ ᴄᴏɴꜰɪɢᴜʀᴇᴅ' if vs.get('shortener_1') else '❌ ɴᴏᴛ ꜱᴇᴛ'}",
        f"ꜱʜᴏʀᴛᴇɴᴇʀ 2 · {'✅ ᴄᴏɴꜰɪɢᴜʀᴇᴅ' if vs.get('shortener_2') else '❌ ɴᴏᴛ ꜱᴇᴛ'}",
        f"ꜱʜᴏʀᴛᴇɴᴇʀ 3 · {'✅ ᴄᴏɴꜰɪɢᴜʀᴇᴅ' if vs.get('shortener_3') else '❌ ɴᴏᴛ ꜱᴇᴛ'}",
        "",
        f"ᴛᴜᴛᴏʀɪᴀʟ 1 · {'✅' if vs.get('tutorial_1') else '❌'}",
        f"ᴛᴜᴛᴏʀɪᴀʟ 2 · {'✅' if vs.get('tutorial_2') else '❌'}",
        f"ᴛᴜᴛᴏʀɪᴀʟ 3 · {'✅' if vs.get('tutorial_3') else '❌'}",
    ]
    rows = [
        [InlineKeyboardButton(
            "🔴 DISABLE" if vs.get("enabled") else "🟢 ENABLE",
            callback_data=make(NS.VERIFY, "toggle", cid)
        )],
        [InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ]
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:verify:toggle:(-?\d+)$"))
async def cb_verify_toggle(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("verification_settings", {}).get("enabled", False)
    await config_manager.set_field(chat_id, "verification_settings.enabled", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_verify_open(client, q)


# ═══════════════════════ SECURITY ═══════════════════════
SECURITY_TOGGLES = [
    ("url_blocking", "URL BLOCKING"),
    ("telegram_links", "TELEGRAM LINKS"),
    ("admin_bypass", "ADMIN BYPASS"),
    ("search_flood_control", "SEARCH FLOOD CONTROL"),
    ("request_flood_control", "REQUEST FLOOD CONTROL"),
]


@Client.on_callback_query(filters.regex(r"^gs:security:open:(-?\d+)$"))
async def cb_security_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    ss = cfg.get("security_settings", {})

    lines = ["🛡️ <b>" + fb("SECURITY") + "</b>", DIV, ""]
    for k, label in SECURITY_TOGGLES:
        lines.append(f"{sc(label.lower())} · {_on(ss.get(k, True))}")

    rows = [[InlineKeyboardButton(
        _toggle_label(label, ss.get(k, True)),
        callback_data=make(NS.SECURITY, "toggle", f"{chat_id}:{k}")
    )] for k, label in SECURITY_TOGGLES]
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:security:toggle:(-?\d+):(\w+)$"))
async def cb_security_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    key = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("security_settings", {}).get(key, True)
    await config_manager.set_field(chat_id, f"security_settings.{key}", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_security_open(client, q)


# ═══════════════════════ WELCOME ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:welcome:open:(-?\d+)$"))
async def cb_welcome_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    ws = cfg.get("welcome_settings", {})

    lines = [
        "👋 <b>" + fb("WELCOME SETTINGS") + "</b>",
        DIV, "",
        f"ᴡᴇʟᴄᴏᴍᴇ · {_on(ws.get('enabled'))}",
        f"ᴘʜᴏᴛᴏ · {_on(ws.get('photo_url'))}",
        f"ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ · {_on(ws.get('auto_delete', True))}",
        f"ᴅᴇʟᴇᴛᴇ ᴀꜰᴛᴇʀ · <code>{ws.get('delete_after_seconds', 600)}s</code>",
    ]
    rows = [
        [InlineKeyboardButton(
            "🔴 DISABLE" if ws.get("enabled") else "🟢 ENABLE",
            callback_data=make(NS.WELCOME, "toggle", cid)
        )],
        [InlineKeyboardButton(
            "🔴 AUTO-DELETE OFF" if ws.get("auto_delete") else "🟢 AUTO-DELETE ON",
            callback_data=make(NS.WELCOME, "toggle_autodel", cid)
        )],
        [InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
         InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close"))],
    ]
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:welcome:toggle:(-?\d+)$"))
async def cb_welcome_toggle(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("welcome_settings", {}).get("enabled", False)
    await config_manager.set_field(chat_id, "welcome_settings.enabled", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_welcome_open(client, q)


@Client.on_callback_query(filters.regex(r"^gs:welcome:toggle_autodel:(-?\d+)$"))
async def cb_welcome_toggle_autodel(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("welcome_settings", {}).get("auto_delete", True)
    await config_manager.set_field(chat_id, "welcome_settings.auto_delete", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_welcome_open(client, q)


# ═══════════════════════ AUTO DELETE ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:autodel:open:(-?\d+)$"))
async def cb_autodel_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    ads = cfg.get("auto_delete_settings", {})

    lines = [
        "🗑️ <b>" + fb("AUTO DELETE") + "</b>",
        DIV, "",
        f"ᴡᴇʟᴄᴏᴍᴇ · {_on(ads.get('welcome', True))}",
        f"ʀᴇꜱᴜʟᴛ · {_on(ads.get('result', True))}",
        f"ꜱᴇᴀʀᴄʜ · {_on(ads.get('search', True))}",
        f"ꜰɪʟᴇ · {_on(ads.get('file', True))}",
        "",
        f"ᴅᴇʟᴇᴛᴇ ᴀꜰᴛᴇʀ · <code>{ads.get('delete_after_seconds', 600)}s</code>",
    ]
    rows = []
    for k in ("welcome", "result", "search", "file"):
        rows.append([InlineKeyboardButton(
            _toggle_label(k.upper(), ads.get(k, True)),
            callback_data=make(NS.AUTODEL, "toggle", f"{chat_id}:{k}")
        )])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:autodel:toggle:(-?\d+):(\w+)$"))
async def cb_autodel_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    key = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("auto_delete_settings", {}).get(key, True)
    await config_manager.set_field(chat_id, f"auto_delete_settings.{key}", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_autodel_open(client, q)


# ═══════════════════════ REQUEST SYSTEM ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:req:open:(-?\d+)$"))
async def cb_req_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    rs = cfg.get("request_settings", {})

    lines = [
        "📝 <b>" + fb("REQUEST SYSTEM") + "</b>",
        DIV, "",
        f"ʀᴇǫᴜᴇꜱᴛꜱ · {_on(rs.get('enabled'))}",
        f"ɴᴏ-ʀᴇꜱᴜʟᴛ ʟᴏɢ · {_on(rs.get('no_result_log'))}",
        f"ᴜꜱᴇʀ ᴘᴍ ᴜᴘᴅᴀᴛᴇ · {_on(rs.get('user_pm_update'))}",
        f"ᴅᴜᴘʟɪᴄᴀᴛᴇ ᴄʜᴇᴄᴋ · {_on(rs.get('duplicate_check'))}",
    ]
    rows = []
    for k, label in [
        ("enabled", "REQUESTS"),
        ("no_result_log", "NO-RESULT LOG"),
        ("user_pm_update", "USER PM UPDATE"),
        ("duplicate_check", "DUPLICATE CHECK"),
    ]:
        rows.append([InlineKeyboardButton(
            _toggle_label(label, rs.get(k, True)),
            callback_data=make(NS.REQ, "toggle", f"{chat_id}:{k}")
        )])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ])
    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:req:toggle:(-?\d+):(\w+)$"))
async def cb_req_toggle(client: Client, q: CallbackQuery):
    parts = q.data.split(":")
    chat_id = int(parts[3])
    key = parts[4]
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    cfg = await config_manager.get_config(chat_id)
    cur = cfg.get("request_settings", {}).get(key, True)
    await config_manager.set_field(chat_id, f"request_settings.{key}", not cur)
    await q.answer("ᴛᴏɢɢʟᴇᴅ")
    await cb_req_open(client, q)


# ═══════════════════════ STATISTICS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:stats:open:(-?\d+)$"))
async def cb_stats_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    stats = await statistics_manager.get_stats(chat_id)

    lines = [
        "📊 <b>" + fb("GROUP STATISTICS") + "</b>",
        DIV, "",
        f"🔍 ꜱᴇᴀʀᴄʜᴇꜱ ᴛᴏᴅᴀʏ · <code>{stats.get('searches_today', 0)}</code>",
        f"🎬 ᴍᴏᴠɪᴇ ꜱᴇᴀʀᴄʜᴇꜱ · <code>{stats.get('movie_searches', 0)}</code>",
        f"📺 ꜱᴇʀɪᴇꜱ ꜱᴇᴀʀᴄʜᴇꜱ · <code>{stats.get('series_searches', 0)}</code>",
        f"✅ ʀᴇꜱᴜʟᴛꜱ ꜰᴏᴜɴᴅ · <code>{stats.get('results_found', 0)}</code>",
        f"❌ ɴᴏᴛ ꜰᴏᴜɴᴅ · <code>{stats.get('not_found', 0)}</code>",
        f"📦 ꜰɪʟᴇꜱ ꜱᴇɴᴛ · <code>{stats.get('files_sent', 0)}</code>",
        f"📝 ʀᴇǫᴜᴇꜱᴛꜱ · <code>{stats.get('requests', 0)}</code>",
        "",
        f"🔥 ᴛᴏᴘ ꜱᴇᴀʀᴄʜ · <code>{stats.get('top_search', '—')}</code>",
        f"🌐 ᴛᴏᴘ ʟᴀɴɢᴜᴀɢᴇ · <code>{stats.get('top_language', '—')}</code>",
        f"🎞️ ᴛᴏᴘ ǫᴜᴀʟɪᴛʏ · <code>{stats.get('top_quality', '—')}</code>",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 REFRESH", callback_data=make(NS.STATS, "open", cid)),
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
    ]])
    await _edit(q, "\n".join(lines), kb)
    await q.answer()


# ═══════════════════════ VIEW ALL ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:view:all:(-?\d+)$"))
async def cb_view_all(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    ss = cfg.get("search_settings", {})
    fs = cfg.get("force_sub_settings", {})
    vs = cfg.get("verification_settings", {})
    ws = cfg.get("welcome_settings", {})
    ads = cfg.get("auto_delete_settings", {})
    rs = cfg.get("request_settings", {})
    sec = cfg.get("security_settings", {})
    buttons = await button_manager.list_buttons(chat_id)

    lines = [
        "📋 <b>" + fb("GROUP CONFIGURATION") + "</b>",
        DIV, "",
        f"ɢʀᴏᴜᴘ · <b>{cfg.get('title')}</b>",
        f"ɪᴅ · <code>{chat_id}</code>",
        "",
        f"ᴄᴏɴᴛᴇɴᴛ · <b>{cfg.get('content_mode', 'both').upper()}</b>",
        f"ꜱᴇᴀʀᴄʜ · {_on(ss.get('auto_filter', True))}",
        f"ʀᴇꜱᴜʟᴛ ᴍᴏᴅᴇ · <b>{cfg.get('result_mode', 'button').upper()}</b>",
        f"ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴꜱ · <code>{len(buttons)}</code>",
        f"ᴄᴜꜱᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ · {'✅' if cfg.get('custom_caption') else '❌'}",
        f"ᴍᴏᴠɪᴇ ɢʀᴏᴜᴘ · {'✅' if cfg.get('movie_group_link') else '❌'}",
        f"ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ · {'✅' if cfg.get('series_group_link') else '❌'}",
        f"ɪᴍᴅʙ · {_on(cfg.get('metadata_settings', {}).get('poster', True))}",
        f"ꜰᴏʀᴄᴇ ꜱᴜʙ · <code>{len(fs.get('channels') or [])} ᴄʜᴀɴɴᴇʟꜱ</code>",
        f"ᴠᴇʀɪꜰɪᴄᴀᴛɪᴏɴ · {_on(vs.get('enabled'))}",
        f"ᴡᴇʟᴄᴏᴍᴇ · {_on(ws.get('enabled'))}",
        f"ᴀᴜᴛᴏ ᴅᴇʟᴇᴛᴇ · {_on(ads.get('welcome', True))}",
        f"ꜱᴇᴄᴜʀɪᴛʏ · {_on(sec.get('url_blocking', True))}",
        f"ʀᴇǫᴜᴇꜱᴛꜱ · {_on(rs.get('enabled', True))}",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=make(NS.MAIN, "open", cid)),
        InlineKeyboardButton("❌ CLOSE", callback_data=make(NS.MAIN, "close")),
    ]])
    await _edit(q, "\n".join(lines), kb)
    await q.answer()


# ═══════════════════════ RESET GROUP ═══════════════════════
@Client.on_callback_query(filters.regex(r"^gs:reset:open:(-?\d+)$"))
async def cb_reset_open(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    cfg = await config_manager.get_config(chat_id)
    text = "\n".join([
        "⚠️ <b>" + fb("RESET GROUP SETTINGS") + "</b>",
        DIV, "",
        "ᴛʜɪꜱ ᴡɪʟʟ ʀᴇᴍᴏᴠᴇ ᴀʟʟ ᴄᴜꜱᴛᴏᴍ ɢʀᴏᴜᴘ ᴏᴠᴇʀʀɪᴅᴇꜱ.",
        "",
        f"ɢʀᴏᴜᴘ · <b>{cfg.get('title')}</b>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ RESET GROUP",
                               callback_data=make(NS.RESET, "do", cid))],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=make(NS.MAIN, "open", cid))],
    ])
    await _edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^gs:reset:do:(-?\d+)$"))
async def cb_reset_do(client: Client, q: CallbackQuery):
    _, _, cid = parse(q.data)
    chat_id = int(cid)
    if not await permission_manager.can_manage(client, chat_id, q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    await config_manager.reset_config(chat_id)
    await q.answer("✅ ɢʀᴏᴜᴘ ʀᴇꜱᴇᴛ")
    text, kb = await render_main_menu(chat_id)
    await _edit(q, text, kb)


# ═══════════════════════ /groupsettings (OWNER) ═══════════════════════
@Client.on_message(filters.command("groupsettings") & filters.private)
async def cmd_groupsettings(client: Client, message: Message):
    """Owner-only command to manage ALL registered groups from PM."""
    if not message.from_user:
        return
    logger.info(f"[GADMIN] /groupsettings from={message.from_user.id} "
                f"is_owner={permission_manager.is_bot_owner(message.from_user.id)}")
    if not permission_manager.is_bot_owner(message.from_user.id):
        await message.reply_text(
            "⛔ ᴛʜɪꜱ ᴄᴏᴍᴍᴀɴᴅ ɪꜱ ꜰᴏʀ ᴛʜᴇ ʙᴏᴛ ᴏᴡɴᴇʀ ᴏɴʟʏ.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _render_owner_group_list(message)


async def _render_owner_group_list(target):
    """Render the owner group list. `target` must be a Message."""
    try:
        total = await config_manager.count_groups()
        groups = await config_manager.list_groups(0, 10)
    except Exception as e:
        logger.exception(f"[GADMIN] owner list fetch failed: {e}")
        try:
            await target.reply_text(
                f"⚠️ ꜰᴀɪʟᴇᴅ ᴛᴏ ʟᴏᴀᴅ ɢʀᴏᴜᴘꜱ: <code>{e}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    rows: List[List[InlineKeyboardButton]] = []
    for g in groups:
        gid = g.get("chat_id")
        title = (g.get("title") or str(gid))[:40]
        status = "🟢" if g.get("enabled", True) else "🔴"
        rows.append([InlineKeyboardButton(
            f"{status} {title.upper()}",
            callback_data=make(NS.MAIN, "open", str(gid)),
        )])

    rows.append([
        InlineKeyboardButton("➕ ADD GROUP",
                              callback_data=make(NS.ADD, "start", "0")),
    ])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH",
                              callback_data=make(NS.OWNER, "refresh", "0")),
        InlineKeyboardButton("❌ CLOSE",
                              callback_data=make(NS.MAIN, "close")),
    ])

    text = "\n".join([
        "⚙️ <b>" + fb("GROUP MANAGEMENT") + "</b>",
        DIV, "",
        f"📊 ʀᴇɢɪꜱᴛᴇʀᴇᴅ ɢʀᴏᴜᴘꜱ · <b>{total}</b>",
        "",
        DIV_S,
        "ꜱᴇʟᴇᴄᴛ ᴀ ɢʀᴏᴜᴘ ᴛᴏ ᴍᴀɴᴀɢᴇ:",
    ])

    try:
        await target.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[GADMIN] owner group list shown to {target.from_user.id}")
    except Exception as e:
        logger.exception(f"[GADMIN] failed to send owner group list: {e}")


@Client.on_callback_query(filters.regex(r"^gs:owner:refresh:(\d+)$"))
async def cb_owner_refresh(client: Client, q: CallbackQuery):
    if not permission_manager.is_bot_owner(q.from_user.id):
        await q.answer("⛔", show_alert=True); return

    total = await config_manager.count_groups()
    groups = await config_manager.list_groups(0, 10)
    rows: List[List[InlineKeyboardButton]] = []
    for g in groups:
        gid = g.get("chat_id")
        title = (g.get("title") or str(gid))[:40]
        status = "🟢" if g.get("enabled", True) else "🔴"
        rows.append([InlineKeyboardButton(
            f"{status} {title.upper()}",
            callback_data=make(NS.MAIN, "open", str(gid)),
        )])
    rows.append([
        InlineKeyboardButton("➕ ADD GROUP",
                              callback_data=make(NS.ADD, "start", "0")),
    ])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH",
                              callback_data=make(NS.OWNER, "refresh", "0")),
        InlineKeyboardButton("❌ CLOSE",
                              callback_data=make(NS.MAIN, "close")),
    ])
    text = "\n".join([
        "⚙️ <b>" + fb("GROUP MANAGEMENT") + "</b>",
        DIV, "",
        f"📊 ʀᴇɢɪꜱᴛᴇʀᴇᴅ ɢʀᴏᴜᴘꜱ · <b>{total}</b>",
        "",
        DIV_S,
        "ꜱᴇʟᴇᴄᴛ ᴀ ɢʀᴏᴜᴘ ᴛᴏ ᴍᴀɴᴀɢᴇ:",
    ])
    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer("🔄 ʀᴇꜰʀᴇꜱʜᴇᴅ")


# ═══════════════════════ TEXT HANDLERS (REPLY-ONLY) ═══════════════════════
@Client.on_message(
    filters.private & filters.text & ~filters.command([
        "start", "settings", "reload", "database", "index", "pm_search",
        "autofilter", "stats", "groupsettings", "request", "s",
    ]),
    group=-50,   # runs BEFORE auto_filter so replies don't leak into search
)
async def session_text_handler(client: Client, message: Message):
    """
    Handle text input for active sessions.
    Requires the user to REPLY to the bot's prompt.
    """
    if not message.from_user or not message.text:
        return

    # Require reply to bot
    if not message.reply_to_message:
        return
    if not message.reply_to_message.from_user:
        return
    if not message.reply_to_message.from_user.is_self:
        return

    uid = message.from_user.id
    reply_id = message.reply_to_message.id

    try:
        from database import db_registry
        db = db_registry.get_system_db()
    except Exception:
        return
    if db is None:
        return

    session = None
    try:
        session = await db["group_sessions"].find_one(
            {
                "user_id": uid,
                "expires_at": {"$gt": time.time()},
                "prompt_msg_id": reply_id,
            },
            sort=[("created_at", -1)],
        )
    except Exception:
        return

    if not session:
        return

    # ── We have an active session bound to this reply — consume the message ──
    message.stop_propagation()

    action = session.get("action")
    chat_id = session.get("chat_id")
    token = session.get("token")
    payload = session.get("payload", {}) or {}

    ok = await permission_manager.can_manage(client, chat_id, uid)
    if not ok:
        await session_manager.cancel(token)
        await message.reply_text("⛔ ʏᴏᴜ ᴀʀᴇ ɴᴏ ʟᴏɴɢᴇʀ ᴀɴ ᴀᴅᴍɪɴ ᴏꜰ ᴛʜᴀᴛ ɢʀᴏᴜᴘ.")
        return

    text = message.text.strip()

    # ── ADD BUTTON (2 steps) ──
    if action == "add_button":
        step = session.get("step", 1)
        if step == 1:
            if not (1 <= len(text) <= 60):
                await message.reply_text("❌ ɴᴀᴍᴇ ᴍᴜꜱᴛ ʙᴇ 1-60 ᴄʜᴀʀꜱ.")
                return
            await session_manager.advance(token, {"name": text})
            prompt = await message.reply_text(
                f"➕ <b>ꜱᴛᴇᴘ 2/2</b>\n\n"
                f"ɴᴀᴍᴇ · <b>{text}</b>\n\n"
                f"📝 <b>ʀᴇᴘʟʏ ᴛᴏ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ</b> ᴡɪᴛʜ ᴛʜᴇ ᴜʀʟ.",
                parse_mode=ParseMode.HTML,
            )
            try:
                await db["group_sessions"].update_one(
                    {"token": token},
                    {"$set": {"prompt_msg_id": prompt.id}},
                )
            except Exception:
                pass
            return

        url = text
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
            await message.reply_text("❌ ᴜʀʟ ᴍᴜꜱᴛ ꜱᴛᴀʀᴛ ᴡɪᴛʜ http:// ᴏʀ https:// ᴏʀ tg://")
            return
        btn = await button_manager.add_button(chat_id, payload.get("name", "Button"), url)
        await session_manager.cancel(token)
        if btn:
            await message.reply_text(
                f"✅ ʀᴇꜱᴜʟᴛ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ:\n\n"
                f"ɴᴀᴍᴇ · <b>{btn['name']}</b>\n"
                f"ᴜʀʟ · <code>{btn['url']}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ (ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ ᴏʀ ɪɴᴠᴀʟɪᴅ).")
        return

    # ── EDIT BUTTON NAME ──
    if action == "edit_button_name":
        btn_id = payload.get("btn_id")
        if not btn_id:
            await session_manager.cancel(token)
            return
        ok2 = await button_manager.edit_button(chat_id, btn_id, new_name=text)
        await session_manager.cancel(token)
        await message.reply_text("✅ ᴜᴘᴅᴀᴛᴇᴅ" if ok2 else "❌ ꜰᴀɪʟᴇᴅ")
        return

    # ── EDIT BUTTON URL ──
    if action == "edit_button_url":
        btn_id = payload.get("btn_id")
        if not btn_id:
            await session_manager.cancel(token)
            return
        if not (text.startswith("http://") or text.startswith("https://") or text.startswith("tg://")):
            await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
            return
        ok2 = await button_manager.edit_button(chat_id, btn_id, new_url=text)
        await session_manager.cancel(token)
        await message.reply_text("✅ ᴜᴘᴅᴀᴛᴇᴅ" if ok2 else "❌ ꜰᴀɪʟᴇᴅ")
        return

    # ── SET CAPTION ──
    if action == "set_caption":
        if len(text) < 3:
            await message.reply_text("❌ ᴄᴀᴘᴛɪᴏɴ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
            return
        ok2 = await caption_manager.set_caption(chat_id, text)
        await session_manager.cancel(token)
        await message.reply_text("✅ ᴄᴀᴘᴛɪᴏɴ ꜱᴀᴠᴇᴅ" if ok2 else "❌ ꜰᴀɪʟᴇᴅ")
        return

    # ── SET MOVIE LINK ──
    if action == "set_movie_link":
        ok2 = await link_manager.set_movie_link(chat_id, text)
        await session_manager.cancel(token)
        await message.reply_text(
            "✅ ᴍᴏᴠɪᴇ ɢʀᴏᴜᴘ ʟɪɴᴋ ꜱᴀᴠᴇᴅ" if ok2 else "❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ"
        )
        return

    # ── SET SERIES LINK ──
    if action == "set_series_link":
        ok2 = await link_manager.set_series_link(chat_id, text)
        await session_manager.cancel(token)
        await message.reply_text(
            "✅ ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ ʟɪɴᴋ ꜱᴀᴠᴇᴅ" if ok2 else "❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ"
        )
        return

    # ── FSUB ADD CHANNEL ──
    if action == "fsub_add":
        target = None
        if text.startswith("@"):
            try:
                chat_obj = await client.get_chat(text)
                target = chat_obj.id
            except Exception:
                await message.reply_text("❌ ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ ᴛʜᴀᴛ ᴜꜱᴇʀɴᴀᴍᴇ.")
                return
        else:
            try:
                target = int(text)
            except ValueError:
                await message.reply_text("❌ ꜱᴇɴᴅ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ.")
                return
        cfg = await config_manager.get_config(chat_id)
        chans = list(cfg.get("force_sub_settings", {}).get("channels") or [])
        if target in chans:
            await message.reply_text("⚠️ ᴀʟʀᴇᴀᴅʏ ɪɴ ᴛʜᴇ ʟɪꜱᴛ.")
            await session_manager.cancel(token)
            return
        chans.append(target)
        await config_manager.set_field(chat_id, "force_sub_settings.channels", chans)
        await session_manager.cancel(token)
        await message.reply_text(f"✅ ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ · <code>{target}</code>",
                                 parse_mode=ParseMode.HTML)
        return

    await session_manager.cancel(token)


# ═══════════════════════ STARTUP LOG ═══════════════════════
logger.info("[GADMIN] group admin plugin loaded")
