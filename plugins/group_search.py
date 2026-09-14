# plugins/group_search.py
"""
DOWNTOWN VILLA — Group auto-filter + redirect-to-PM.

Does NOT modify media_search. Only adds:
  1) Group text handler   → calls media_search.handlers._handle_search
  2) File-click intercept → redirects user to bot PM (deep link)
  3) /start in PM         → delivers the file

Flow:
  [GROUP]  user types movie → file list shown
  [GROUP]  user clicks file → Telegram switches to bot PM
  [PM]     /start file_{sid}_{idx} → file delivered + auto-delete
"""

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded")


# ═══════════════════════════════════════════════════════════
# 1) GROUP TEXT → run media_search
# ═══════════════════════════════════════════════════════════
@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-10,
)
async def group_search_handler(client: Client, message):
    logger.info(
        f"[GROUP-SEARCH] chat={message.chat.id} "
        f"user={message.from_user.id if message.from_user else '?'} "
        f"text={message.text!r}"
    )

    try:
        # per-group toggle check
        try:
            from services.settings_service import get_settings
            s = await get_settings(message.chat.id)
            if not s.get("auto_ffilter", True):
                logger.info("[GROUP-SEARCH] auto_ffilter OFF — skipping")
                return
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] settings check failed: {e}")

        from media_search.handlers import _handle_search
        await _handle_search(client, message, message.text, is_group=True)
        logger.info("[GROUP-SEARCH] handed off to _handle_search ✅")

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════
# 2) FILE CLICK IN GROUP → redirect to bot PM
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^fl:"), group=-100)
async def fl_redirect_to_pm(client: Client, q):
    """
    Intercept file-button clicks. If they came from a GROUP,
    redirect the user to the bot's PM via deep link.
    In PM, do nothing — let the original handler deliver normally.
    """
    try:
        chat_type = q.message.chat.type
    except Exception:
        chat_type = None

    # If not in a group → leave it to media_search's own callback
    if chat_type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    # callback data: fl:{sid}:{idx}
    try:
        _, sid, idx = q.data.split(":", 2)
    except Exception:
        return

    try:
        me = await client.get_me()
        deep_link = f"https://t.me/{me.username}?start=file_{sid}_{idx}"
        logger.info(
            f"[GROUP-SEARCH] file click in GROUP by user={q.from_user.id} "
            f"→ redirect to PM: {deep_link}"
        )

        # Stop propagation so media_search's own callback does NOT also fire
        try:
            q.stop_propagation()
        except Exception:
            pass

        # This is what actually switches Telegram to the bot PM
        await q.answer(url=deep_link)

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] redirect failed: {e}")
        try:
            await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 3) /start IN PM → deliver file if payload is present
# ═══════════════════════════════════════════════════════════
@Client.on_message(filters.command("start") & filters.private)
async def start_pm_handler(client: Client, message):
    if len(message.command) < 2:
        return await _send_welcome(client, message)

    payload = message.command[1]

    if payload.startswith("file_"):
        return await _deliver_file(client, message, payload)

    # other payloads (reff_, etc.) → welcome
    return await _send_welcome(client, message)


async def _send_welcome(client: Client, message):
    await message.reply_text(
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 ꜱᴇᴀʀᴄʜ ᴍᴏᴠɪᴇꜱ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ,\n"
        "ᴛʜᴇɴ ᴄʟɪᴄᴋ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ʜᴇʀᴇ.",
        parse_mode=ParseMode.HTML,
    )


async def _deliver_file(client: Client, message, payload: str):
    """
    payload = file_{session_id}_{index}
    """
    logger.info(f"[START-DELIVERY] payload={payload!r} user={message.from_user.id}")

    # ── Parse payload ──
    try:
        _, sid, idx_str = payload.split("_", 2)
        idx = int(idx_str)
    except Exception:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ʟɪɴᴋ.")

    # ── Get session ──
    try:
        from media_search.sessions import sessions
    except Exception as e:
        logger.exception(f"[START-DELIVERY] sessions import failed: {e}")
        return await message.reply_text("⚠️ ꜱᴇʀᴠɪᴄᴇ ᴇʀʀᴏʀ.")

    session = await sessions.get(sid)
    if not session:
        return await message.reply_text(
            "⚠️ <b>ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.</b>\n"
            "ᴘʟᴇᴀꜱᴇ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ.",
            parse_mode=ParseMode.HTML,
        )

    if idx < 0 or idx >= len(session.candidates):
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ ɪɴᴅᴇx.")

    # ── Force-sub check ──
    try:
        from media_search.subscription import subscription
        ok, missing = await subscription.is_subscribed(client, message.from_user.id)
        if not ok:
            rows = []
            for ch in missing[:5]:
                try:
                    cid = str(ch).replace("-100", "").replace("-", "")
                    url = f"https://t.me/c/{cid}/1"
                except Exception:
                    url = "https://t.me/"
                rows.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=url)])
            rows.append([InlineKeyboardButton("🔄 CHECK AGAIN",
                                               callback_data="sr:check_sub")])
            rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
            return await message.reply_text(
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ.",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.warning(f"[START-DELIVERY] sub check failed: {e}")

    # ── Rebuild FileHit from stored candidate ──
    data = session.candidates[idx]
    try:
        from media_search.models import FileHit
        from media_search.normalizer import normalize
        from media_search.delivery import delivery

        hit = FileHit(
            file_id=data.get("file_id", ""),
            file_unique_id=data.get("file_unique_id"),
            file_name=data.get("file_name"),
            file_size=data.get("file_size"),
            title=data.get("title", ""),
            normalized_title=normalize(data.get("title") or ""),
            year=data.get("year"),
            type=data.get("type", "movie"),
            quality=data.get("quality"),
            codec=data.get("codec"),
            audio_languages=list(data.get("audio_languages") or []),
            subtitle_languages=list(data.get("subtitle_languages") or []),
            has_subtitle=bool(data.get("has_subtitle")),
            series_title=data.get("series_title"),
            season=data.get("season"),
            episode=data.get("episode"),
            caption=data.get("caption"),
        )

        ok, err = await delivery.send_file(client, message.from_user.id, hit)
        if not ok and err:
            await message.reply_text(err)
        else:
            logger.info(f"[START-DELIVERY] ✅ delivered to {message.from_user.id}")

    except Exception as e:
        logger.exception(f"[START-DELIVERY] delivery crashed: {e}")
        await message.reply_text("❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ᴅᴇʟɪᴠᴇʀ ꜰɪʟᴇ.")
