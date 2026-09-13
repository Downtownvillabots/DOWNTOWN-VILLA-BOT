# plugins/request.py
"""
Request channel admin buttons.
MOVIE UPDATED → DM user with poster + GET FILE, auto-delete 10 min.
"""
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.config import ADMINS, OWNER_LNK, UPDATE_CHNL_LNK
from media_search.delivery import delivery
from media_search.engine import engine
from media_search.normalizer import normalize
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from services import imdb as imdb_service

logger = logging.getLogger(__name__)

DIV = "━" * 26
POSTER_DELETE_SECONDS = 600   # 10 minutes


def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


# ═══════════════════════ MOVIE UPDATED ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:updated:([a-f0-9]+)$"))
async def cb_req_updated(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True); return

    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"
    imdb_id = req.get("imdb_id")

    # Fetch IMDb details for the poster
    details = None
    if imdb_id and imdb_service.is_available():
        try:
            details = await imdb_service.get_poster(id=imdb_id)
        except Exception as e:
            logger.warning(f"[REQ] IMDb details failed: {e}")

    title = (details or {}).get("title") or movie_name
    year = (details or {}).get("year")
    rating = (details or {}).get("rating")
    poster = (details or {}).get("poster")

    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🎉 <b>ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ!</b>",
        DIV, "",
        f"🎬 <b>{title}</b>" + (f" ({year})" if year else ""),
    ]
    if rating:
        lines.append(f"⭐ ʀᴀᴛɪɴɢ · <code>{rating}</code>")
    lines += [
        "",
        DIV,
        "",
        "ᴄʟɪᴄᴋ <b>ɢᴇᴛ ꜰɪʟᴇ</b> ʙᴇʟᴏᴡ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ.",
        "",
        f"⏳ ᴛʜɪꜱ ᴍᴇꜱꜱᴀɢᴇ ᴡɪʟʟ ᴅᴇʟᴇᴛᴇ ɪɴ 10 ᴍɪɴᴜᴛᴇꜱ.",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 GET FILE", callback_data=f"req:getfile:{token_id}")],
        [InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK or "https://t.me/")],
    ])

    sent = None
    try:
        if poster:
            sent = await client.send_photo(
                chat_id=user_id, photo=poster, caption="\n".join(lines),
                reply_markup=kb, parse_mode=ParseMode.HTML,
            )
        else:
            sent = await client.send_message(
                chat_id=user_id, text="\n".join(lines),
                reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.warning(f"[REQ] user DM failed: {e}")

    # Auto-delete the poster DM after 10 min
    if sent:
        asyncio.create_task(_auto_delete(client, user_id, sent.id, POSTER_DELETE_SECONDS))

    # Edit channel message
    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ MOVIE UPDATED · NOTIFIED",
                                  callback_data=f"req:noop:{token_id}"),
        ]]))
    except Exception:
        pass

    await request_repo.update_token(token_id, "updated")
    await q.answer("✅ ᴜꜱᴇʀ ɴᴏᴛɪꜰɪᴇᴅ")


async def _auto_delete(client, chat_id: int, msg_id: int, seconds: int):
    try:
        await asyncio.sleep(seconds)
        await client.delete_messages(chat_id, msg_id)
        logger.info(f"[REQ] poster deleted chat={chat_id} msg={msg_id}")
    except Exception:
        pass


# ═══════════════════════ NOT RELEASED ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:notreleased:([a-f0-9]+)$"))
async def cb_req_notreleased(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"

    try:
        await client.send_message(
            user_id,
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"📅 <b>{movie_name}</b> ɪꜱ ɴᴏᴛ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ.\n\n"
            "ᴡᴇ'ʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ᴡʜᴇɴ ɪᴛ ᴀʀʀɪᴠᴇꜱ.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK or "https://t.me/"),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[REQ] DM failed: {e}")

    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("📅 NOT RELEASED · NOTIFIED",
                                  callback_data=f"req:noop:{token_id}"),
        ]]))
    except Exception:
        pass

    await request_repo.update_token(token_id, "not_released")
    await request_repo.delete_token(token_id)
    await q.answer("✅ ɴᴏᴛɪꜰɪᴇᴅ")


# ═══════════════════════ NOT FOUND ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:notfound:([a-f0-9]+)$"))
async def cb_req_notfound(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"

    try:
        await client.send_message(
            user_id,
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"🔎 ɴᴏ ꜰɪʟᴇ ꜰᴏᴜɴᴅ ꜰᴏʀ <b>{movie_name}</b>.\n\n"
            "ᴘʟᴇᴀꜱᴇ ᴛʀʏ ᴡɪᴛʜ ᴛʜᴇ ᴄᴏʀʀᴇᴄᴛ ꜱᴘᴇʟʟɪɴɢ.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💬 SUPPORT", url=OWNER_LNK or "https://t.me/"),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[REQ] DM failed: {e}")

    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("🔎 NOT FOUND · NOTIFIED",
                                  callback_data=f"req:noop:{token_id}"),
        ]]))
    except Exception:
        pass

    await request_repo.update_token(token_id, "not_found")
    await request_repo.delete_token(token_id)
    await q.answer("✅ ɴᴏᴛɪꜰɪᴇᴅ")


# ═══════════════════════ CANCEL ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:cancel:([a-f0-9]+)$"))
async def cb_req_cancel(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔", show_alert=True); return
    token_id = q.matches[0].group(1)
    ok = await request_repo.delete_token(token_id)
    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ REQUEST CANCELLED",
                                  callback_data=f"req:noop:{token_id}"),
        ]]))
    except Exception:
        pass
    await q.answer("✅ ᴛᴏᴋᴇɴ ᴄʟᴇᴀʀᴇᴅ" if ok else "⚠️ ᴀʟʀᴇᴀᴅʏ ᴄʟᴇᴀʀᴇᴅ")


# ═══════════════════════ GET FILE ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:getfile:([a-f0-9]+)$"))
async def cb_req_getfile(client: Client, q: CallbackQuery):
    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return

    if q.from_user.id != int(req.get("user_id") or 0):
        await q.answer("⛔ ᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ", show_alert=True); return

    movie_name = req.get("movie_name") or ""
    await q.answer("📤 ꜱᴇɴᴅɪɴɢ...")

    norm = normalize(movie_name)
    result = await engine.search_any(norm)
    hits = result.hits
    if not hits:
        result = await engine.search_any(norm, year=None)
        hits = result.hits

    if not hits:
        try:
            await client.send_message(q.from_user.id, "😌 ꜰɪʟᴇ ɴᴏ ʟᴏɴɢᴇʀ ᴀᴠᴀɪʟᴀʙʟᴇ.")
        except Exception:
            pass
        await request_repo.delete_token(token_id)
        return

    best = ranker.rank(hits)[0]
    ok, err = await delivery.send_file(client, q.from_user.id, best)
    if ok:
        await request_repo.delete_token(token_id)
    elif err:
        try:
            await client.send_message(q.from_user.id, err)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^req:noop:([a-f0-9]+)$"))
async def cb_req_noop(client: Client, q: CallbackQuery):
    await q.answer()
