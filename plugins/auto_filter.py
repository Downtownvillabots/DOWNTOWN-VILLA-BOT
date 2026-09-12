# plugins/auto_filter.py
"""
🏨 DOWNTOWN VILLA — AUTO-FILTER PLUGIN
======================================
PM Search + Auto-Filter.
Handlers are declared AT TOP LEVEL so Pyrogram's plugin loader finds them.
"""
import logging
import re

from pyrogram import Client, filters
from pyrogram.types import Message

logger = logging.getLogger(__name__)

# ── Lazy-imported at handler runtime to avoid load-time circular issues ──
_handle_search = None


def _get_search_fn():
    global _handle_search
    if _handle_search is None:
        from media_search.handlers import _handle_search as fn
        _handle_search = fn
    return _handle_search


# ═══════════════════════ PM SEARCH HANDLER ═══════════════════════
@Client.on_message(
    filters.private
    & filters.text
    & filters.incoming
    & ~filters.regex(r"^/")
    & ~filters.regex(r"https?://")
)
async def pm_text(client: Client, message: Message):
    """Every incoming PM text (not command, not URL) triggers a search."""
    try:
        query = (message.text or "").strip()
        if not query:
            return

        logger.info(f"[PM] from={message.from_user.id} text={query[:60]!r}")

        if len(query) < 2 or len(query) > 120:
            logger.info(f"[PM] skipped length={len(query)}")
            return

        fn = _get_search_fn()
        try:
            await fn(client, message, query, is_group=False)
        except TypeError:
            # Older signature without is_group — fall back
            await fn(client, message, query)

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


# ═══════════════════════ SUBSCRIPTION CHECK BUTTON ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:check_sub$"))
async def cb_check_sub(client: Client, q):
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
        logger.warning(f"[PM] check_sub failed: {e}")
        await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^sr:close$"))
async def cb_close(client: Client, q):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sr:pick:([a-f0-9]+):(\d+)$"))
async def cb_pick(client: Client, q):
    """Multi-match picker callback → re-search that exact title and deliver."""
    try:
        session_id = q.matches[0].group(1)
        idx = int(q.matches[0].group(2))

        from media_search.sessions import sessions
        from media_search.engine import engine
        from media_search.ranker import ranker
        from media_search.delivery import delivery
        from media_search.normalizer import parse_query
        from media_search.subscription import subscription

        session = await sessions.get(session_id)
        if not session or session.user_id != q.from_user.id:
            await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
            return
        if idx >= len(session.candidates):
            await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
            return

        candidate = session.candidates[idx]
        title = candidate["title"]
        await q.answer("📤 ꜱᴇɴᴅɪɴɢ...")

        norm, _, is_series = parse_query(title)
        if candidate.get("type") == "series":
            result = await engine.search_series(norm, year=candidate.get("year"))
        else:
            result = await engine.search_movie(norm, year=candidate.get("year"))

        if not result.hits:
            await q.message.edit_text("❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ.")
            return

        # Force-sub
        ok, missing = await subscription.is_subscribed(client, q.from_user.id)
        if not ok:
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            rows = []
            for ch in missing[:5]:
                try:
                    cid = str(ch).replace("-100", "").replace("-", "")
                    rows.append([InlineKeyboardButton("📢 JOIN CHANNEL",
                                                      url=f"https://t.me/c/{cid}/1")])
                except Exception:
                    pass
            rows.append([InlineKeyboardButton("🔄 CHECK AGAIN", callback_data="sr:check_sub")])
            rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
            await q.message.edit_text(
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ.",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode="html",
            )
            return

        best = (
            ranker.best_for_episode(result.hits) if is_series
            else ranker.rank(result.hits)[0]
        )

        ok, err = await delivery.send_file(client, q.from_user.id, best)
        if ok:
            try:
                await q.message.delete()
            except Exception:
                pass
        elif err:
            await q.message.edit_text(err)

    except Exception as e:
        logger.exception(f"[PM] pick failed: {e}")
        try:
            await q.answer("❌ ᴇʀʀᴏʀ", show_alert=True)
        except Exception:
            pass


# ═══════════════════════ STARTUP LOG ═══════════════════════
logger.info("[AUTO-FILTER] PM search handlers registered")



# ═══════════════════════ DIAGNOSTIC — count indexed files ═══════════════════════
@Client.on_message(filters.private & filters.command("dbstats"))
async def cmd_dbstats(client: Client, message: Message):
    try:
        from core.config import ADMINS
        uid = message.from_user.id
        if int(uid) not in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]:
            await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
            return
    except Exception:
        await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
        return

    try:
        from database import db_registry
        entries = db_registry.media_entries()
        lines = [f"🗄️ ᴍᴇᴅɪᴀ ꜱʜᴀʀᴅꜱ: {len(entries)}", ""]
        total = 0
        for e in entries:
            try:
                count = await e.db["media_files"].estimated_document_count()
                total += count
                lines.append(f"  DB{e.index:02d} ({e.label}): <code>{count}</code>")
            except Exception as ex:
                lines.append(f"  DB{e.index:02d}: ⚠️ {type(ex).__name__}")
        lines.append("")
        lines.append(f"📦 ᴛᴏᴛᴀʟ: <code>{total}</code>")

        # Show a few sample titles
        if total > 0:
            lines.append("")
            lines.append("📋 ꜱᴀᴍᴘʟᴇ ᴛɪᴛʟᴇꜱ:")
            shown = 0
            for e in entries:
                if shown >= 10:
                    break
                try:
                    cursor = e.db["media_files"].find({}, {"title": 1, "type": 1}).limit(10)
                    async for doc in cursor:
                        if shown >= 10:
                            break
                        title = doc.get("title") or "?"
                        t = doc.get("type") or "?"
                        lines.append(f"  • <code>{title}</code> [{t}]")
                        shown += 1
                except Exception:
                    pass

        await message.reply_text("\n".join(lines), parse_mode="html")
    except Exception as e:
        await message.reply_text(f"❌ {type(e).__name__}: {e}")
