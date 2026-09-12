# plugins/auto_filter.py
"""
🏨 DOWNTOWN VILLA — AUTO-FILTER PLUGIN
======================================
PM Search handlers + all search callbacks, registered at top level
so Pyrogram's plugin loader finds them.
"""
import logging

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)

# Handler implementations live here for top-level registration
_handlers_mod = None


def _h():
    """Lazy import to avoid load-order issues."""
    global _handlers_mod
    if _handlers_mod is None:
        from media_search import handlers as h
        _handlers_mod = h
    return _handlers_mod


# ═══════════════════════ PM TEXT HANDLER ═══════════════════════
@Client.on_message(
    filters.private
    & filters.text
    & filters.incoming
    & ~filters.regex(r"^/")
    & ~filters.regex(r"https?://")
)
async def pm_text(client: Client, message: Message):
    """Every PM text (not command, not URL) triggers a search."""
    try:
        query = (message.text or "").strip()
        if not query:
            return
        logger.info(f"[PM] from={message.from_user.id} text={query[:60]!r}")
        if len(query) < 2 or len(query) > 120:
            return
        h = _h()
        try:
            await h._handle_search(client, message, query, is_group=False)
        except TypeError:
            await h._handle_search(client, message, query)
    except Exception as e:
        logger.exception(f"[PM] handler failed: {type(e).__name__}: {e}")


# ═══════════════════════ /pm_search TOGGLE ═══════════════════════
@Client.on_message(filters.private & filters.command("pm_search"))
async def cmd_pm_search(client: Client, message: Message):
    """Admin toggle: /pm_search on | off"""
    try:
        from core.config import ADMINS
        is_admin = int(message.from_user.id) in [
            int(a) for a in ADMINS if str(a).lstrip("-").isdigit()
        ]
    except Exception:
        is_admin = False
    if not is_admin:
        await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower().strip() not in ("on", "off", "true", "false"):
        await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/pm_search on</code> ᴏʀ <code>/pm_search off</code>",
            parse_mode="html",
        )
        return
    enable = parts[1].lower().strip() in ("on", "true")
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        await db["bot_settings"].update_one(
            {"bot_id": client.me.id},
            {"$set": {"pm_search": enable}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"[PM] toggle failed: {e}")
    await message.reply_text(
        f"✅ ᴘᴍ ꜱᴇᴀʀᴄʜ: <b>{'ᴏɴ' if enable else 'ᴏꜰꜰ'}</b>",
        parse_mode="html",
    )


# ═══════════════════════ /autofilter STATUS ═══════════════════════
@Client.on_message(filters.private & filters.command("autofilter"))
async def cmd_autofilter(client: Client, message: Message):
    try:
        from core.config import ADMINS
        if int(message.from_user.id) not in [
            int(a) for a in ADMINS if str(a).lstrip("-").isdigit()
        ]:
            await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
            return
    except Exception:
        await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
        return
    await message.reply_text(
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        "🔎 <b>AUTO-FILTER: ONLINE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "ᴛʏᴘᴇ ᴀɴʏ ᴛɪᴛʟᴇ ɪɴ ᴘᴍ ᴛᴏ ꜱᴇᴀʀᴄʜ.",
        parse_mode="html",
    )


# ═══════════════════════ CALLBACK — Title picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:pick:([a-f0-9]+):(\d+)$"))
async def cb_pick(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_title(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] pick failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Language picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:lang:([a-f0-9]+):(\d+)$"))
async def cb_lang(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_lang(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] lang failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Season picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:seas:([a-f0-9]+):(\d+)$"))
async def cb_season(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_season(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] season failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Episode picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:ep:([a-f0-9]+):(\d+)$"))
async def cb_episode(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_episode(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] episode failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Episode page ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:ep_page:([a-f0-9]+):(\d+)$"))
async def cb_ep_page(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        page = int(q.matches[0].group(2))
        await _h()._episode_page(client, q, sid, page)
    except Exception as e:
        logger.exception(f"[CB] ep_page failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Quality picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:q:([a-f0-9]+):(\d+)$"))
async def cb_quality(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_quality(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] quality failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — File picker (deliver) ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:file:([a-f0-9]+):(\d+)$"))
async def cb_file(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_file(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] file failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Back navigation ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:back:([a-f0-9]+)$"))
async def cb_back(client: Client, q: CallbackQuery):
    try:
        await _h()._back_to_titles(client, q, q.matches[0].group(1))
    except Exception as e:
        logger.exception(f"[CB] back failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^sr:lang_back:([a-f0-9]+)$"))
async def cb_lang_back(client: Client, q: CallbackQuery):
    try:
        await _h()._back_to_langs(client, q, q.matches[0].group(1))
    except Exception as e:
        logger.exception(f"[CB] lang_back failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^sr:q_back:([a-f0-9]+)$"))
async def cb_q_back(client: Client, q: CallbackQuery):
    try:
        await _h()._back_to_quality(client, q, q.matches[0].group(1))
    except Exception as e:
        logger.exception(f"[CB] q_back failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^sr:seas_back:([a-f0-9]+)$"))
async def cb_seas_back(client: Client, q: CallbackQuery):
    try:
        await _h()._back_to_seasons(client, q, q.matches[0].group(1))
    except Exception as e:
        logger.exception(f"[CB] seas_back failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ CALLBACK — Close + Sub check ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:close$"))
async def cb_close(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sr:check_sub$"))
async def cb_check_sub(client: Client, q: CallbackQuery):
    try:
        from media_search.subscription import subscription
        ok, _ = await subscription.is_subscribed(client, q.from_user.id)
        if ok:
            await q.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ! ꜱᴇɴᴅ ʏᴏᴜʀ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ.", show_alert=True)
            try:
                await q.message.delete()
            except Exception:
                pass
        else:
            await q.answer("❌ ꜱᴛɪʟʟ ᴍɪꜱꜱɪɴɢ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
    except Exception as e:
        logger.warning(f"[CB] check_sub failed: {e}")
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)

# ═══════════════════════ CALLBACK — Spell suggestion picker ═══════════════════════
@Client.on_callback_query(filters.regex(r"^spol:([a-f0-9]+):(\d+)$"))
async def cb_spol(client: Client, q: CallbackQuery):
    try:
        sid = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))
        await _h()._pick_suggestion(client, q, sid, idx)
    except Exception as e:
        logger.exception(f"[CB] spol failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ SAFETY NET HANDLER ═══════════════════════
# Fires if the main handler crashed. Diagnoses and reports.
@Client.on_message(filters.private & filters.text, group=100)
async def _safety_net(client: Client, message: Message):
    """Only fires if no other handler responded. Confirms we're alive."""
    try:
        txt = (message.text or "").strip()
        if not txt or txt.startswith("/"):
            return
        logger.info(f"[SAFETY] caught: {txt!r}")
        # Try to import handlers and report the exact failure
        try:
            from media_search import handlers as h
            # If we can import, call search
            try:
                await h._handle_search(client, message, txt, is_group=False)
            except TypeError:
                await h._handle_search(client, message, txt)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"[SAFETY] handlers import failed:\n{tb}")
            try:
                await message.reply_text(
                    f"⚠️ ᴀᴜᴛᴏ-ꜰɪʟᴛᴇʀ ᴇʀʀᴏʀ:\n<code>{type(e).__name__}: {e}</code>",
                    parse_mode="html",
                )
            except Exception:
                pass
    except Exception as e:
        logger.exception(f"[SAFETY] failed: {e}")


# ═══════════════════════ STARTUP ═══════════════════════
logger.info("[AUTO-FILTER] handlers registered (PM + callbacks)")
