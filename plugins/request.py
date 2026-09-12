# plugins/request.py
"""
📢 Request channel callbacks.
Admin actions: MOVIE UPDATED / NOT RELEASED / NOT FOUND / CANCEL.
User actions: GET FILE.
"""
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core.config import ADMINS, OWNER_LNK, GRP_LNK, UPDATE_CHNL_LNK
from media_search.delivery import delivery
from media_search.engine import engine
from media_search.models import FileHit
from media_search.normalizer import normalize
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from services import imdb as imdb_service

logger = logging.getLogger(__name__)

DIV = "━" * 26


def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


# ═══════════════════════ MOVIE UPDATED ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:updated:([a-f0-9]+)$"))
async def cb_req_updated(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"
    imdb_id = req.get("imdb_id")

    # Fetch IMDb details for the poster DM
    details = None
    if imdb_id and imdb_service.is_available():
        try:
            details = await imdb_service.get_poster(id=imdb_id)
        except Exception as e:
            logger.warning(f"[REQ] IMDb details failed: {e}")

    title = (details or {}).get("title") or movie_name
    year = (details or {}).get("year")
    rating = (details or {}).get("rating")
    genres = (details or {}).get("genres") or []
    langs = (details or {}).get("languages") or []
    poster = (details or {}).get("poster")

    # Build user DM
    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🎉 <b>ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ!</b>",
        DIV,
        "",
        f"🎬 <b>{title}</b>" + (f" ({year})" if year else ""),
    ]
    if rating:
        lines.append(f"⭐ ʀᴀᴛɪɴɢ · <code>{rating}</code>")
    if genres:
        lines.append(f"🎭 ɢᴇɴʀᴇ · <code>{', '.join(genres[:3])}</code>")
    if langs:
        lines.append(f"🌐 ʟᴀɴɢᴜᴀɢᴇ · <code>{', '.join(langs[:4])}</code>")
    lines.extend([
        "",
        DIV,
        "",
        "ᴄʟɪᴄᴋ <b>ɢᴇᴛ ꜰɪʟᴇ</b> ʙᴇʟᴏᴡ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ.",
    ])
    text = "\n".join(lines)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 GET FILE", callback_data=f"req:getfile:{token_id}")],
        [InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK or "https://t.me/")],
    ])

    try:
        if poster:
            await client.send_photo(
                chat_id=user_id,
                photo=poster,
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.warning(f"[REQ] user DM failed: {e}")

    # Edit channel message to show status
    try:
        await q.message.edit_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ MOVIE UPDATED · NOTIFIED",
                                  callback_data=f"req:noop:{token_id}"),
        ]]))
    except Exception:
        pass

    await request_repo.update_token(token_id, "updated")
    await q.answer("✅ ᴜꜱᴇʀ ɴᴏᴛɪꜰɪᴇᴅ")


# ═══════════════════════ NOT RELEASED ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:notreleased:([a-f0-9]+)$"))
async def cb_req_notreleased(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "📅 <b>ɴᴏᴛ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ</b>",
        DIV,
        "",
        f"🎬 <b>{movie_name}</b>",
        "",
        "ᴛʜɪꜱ ᴍᴏᴠɪᴇ ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ.",
        "ᴡᴇ'ʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ᴡʜᴇɴ ɪᴛ ᴀʀʀɪᴠᴇꜱ.",
        "",
        DIV,
        "📢 ꜱᴛᴀʏ ᴛᴜɴᴇᴅ ɪɴ ᴏᴜʀ ᴜᴘᴅᴀᴛᴇꜱ ᴄʜᴀɴɴᴇʟ.",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 UPDATES CHANNEL", url=UPDATE_CHNL_LNK or "https://t.me/"),
    ]])
    try:
        await client.send_message(user_id, text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
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
    await request_repo.delete_token(token_id)   # clear cache
    await q.answer("✅ ɴᴏᴛɪꜰɪᴇᴅ")


# ═══════════════════════ NOT FOUND ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:notfound:([a-f0-9]+)$"))
async def cb_req_notfound(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    user_id = req.get("user_id")
    movie_name = req.get("movie_name") or "?"

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🔎 <b>ꜰɪʟᴇ ɴᴏᴛ ꜰᴏᴜɴᴅ</b>",
        DIV,
        "",
        f"🎬 <b>{movie_name}</b>",
        "",
        "ᴡᴇ ᴄᴏᴜʟᴅ ɴᴏᴛ ꜰɪɴᴅ ᴛʜɪꜱ ᴍᴏᴠɪᴇ ɪɴ ᴏᴜʀ ᴅᴀᴛᴀʙᴀꜱᴇ.",
        "ᴘʟᴇᴀꜱᴇ ᴛʀʏ ᴀɢᴀɪɴ ᴡɪᴛʜ ᴛʜᴇ ᴄᴏʀʀᴇᴄᴛ ꜱᴘᴇʟʟɪɴɢ.",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 SUPPORT", url=OWNER_LNK or "https://t.me/"),
    ]])
    try:
        await client.send_message(user_id, text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
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
        await q.answer("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ", show_alert=True)
        return

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


# ═══════════════════════ GET FILE (user) ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:getfile:([a-f0-9]+)$"))
async def cb_req_getfile(client: Client, q: CallbackQuery):
    token_id = q.matches[0].group(1)
    req = await request_repo.get_token(token_id)
    if not req:
        await q.answer("⏱️ ʀᴇǫᴜᴇꜱᴛ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    # Only the requesting user can get the file
    if q.from_user.id != int(req.get("user_id") or 0):
        await q.answer("⛔ ᴛʜɪꜱ ɪꜱ ɴᴏᴛ ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ", show_alert=True)
        return

    movie_name = req.get("movie_name") or ""
    await q.answer("📤 ꜱᴇɴᴅɪɴɢ...")

    # Search DB for the movie
    norm = normalize(movie_name)
    result = await engine.search_any(norm)
    hits = result.hits
    if not hits:
        # Try looser
        result = await engine.search_any(norm, year=None)
        hits = result.hits

    if not hits:
        try:
            await client.send_message(
                q.from_user.id,
                "😌 ꜱᴏʀʀʏ, ᴛʜᴇ ꜰɪʟᴇ ɪꜱ ɴᴏ ʟᴏɴɢᴇʀ ᴀᴠᴀɪʟᴀʙʟᴇ.",
            )
        except Exception:
            pass
        await request_repo.delete_token(token_id)
        return

    best = ranker.rank(hits)[0]
    ok, err = await delivery.send_file(client, q.from_user.id, best)
    if not ok and err:
        try:
            await client.send_message(q.from_user.id, err)
        except Exception:
            pass
    else:
        await request_repo.delete_token(token_id)


# ═══════════════════════ NOOP (already-notified button) ═══════════════════════
@Client.on_callback_query(filters.regex(r"^req:noop:([a-f0-9]+)$"))
async def cb_req_noop(client: Client, q: CallbackQuery):
    await q.answer()
