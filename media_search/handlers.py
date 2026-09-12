"""
Auto-filter handlers — pure text search.
No commands. User types movie/series name → bot searches → sends file.
PM: always search.
Group: search only on title-like messages (prevents chatter spam).
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from media_search.config import SEARCH_PAGE_SIZE
from media_search.delivery import delivery
from media_search.engine import engine
from media_search.models import FileHit
from media_search.normalizer import parse_query
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from media_search.sessions import sessions
from media_search.subscription import subscription

logger = logging.getLogger(__name__)

DIV = "━" * 26

# ───────── Noise / stop phrases for group messages ─────────
_GROUP_STOP_WORDS = {
    "hi", "hello", "hey", "yo", "sup", "ok", "okay", "k", "yes", "no",
    "yep", "nope", "thanks", "thank you", "thx", "ty", "bye", "goodbye",
    "good morning", "good night", "gm", "gn", "lol", "lmao", "haha",
    "nice", "cool", "great", "wow", "omg", "wtf", "what", "why", "how",
    "who", "when", "where", "help", "sure", "please", "pls", "np",
    "sorry", "done", "stop", "go", "come", "wait", "hmm", "umm",
}

# Only letters, digits, spaces, and common title punctuation
_TITLE_CHARS = re.compile(r"^[A-Za-z0-9\s\.\-_:,'!&]+$")


def _human_size(size: Optional[int]) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def _looks_like_title(text: str) -> bool:
    """Decide if a group message is likely a movie/series search."""
    if not text:
        return False
    t = text.strip()
    if len(t) < 2 or len(t) > 60:
        return False
    # Reject URLs
    if "http://" in t.lower() or "https://" in t.lower() or "t.me/" in t.lower():
        return False
    # Reject @mentions (except if it's just the bot mention — handled separately)
    if "@" in t:
        return False
    # Reject common chatter
    if t.lower() in _GROUP_STOP_WORDS:
        return False
    # Reject messages with too many words
    words = t.split()
    if len(words) > 6:
        return False
    # Reject messages with emojis or weird chars
    if not _TITLE_CHARS.match(t):
        return False
    # Reject single character
    if len(t) == 1:
        return False
    # Reject if it's just punctuation
    if not any(c.isalnum() for c in t):
        return False
    return True


# # ═══════════════════════ PRIVATE TEXT → SEARCH ═══════════════════════
@Client.on_message(filters.private & filters.text & ~filters.service)
async def handle_private_text(client: Client, message: Message):
    """Any text in PM triggers a search. Command names are skipped inside."""
    if not message.text:
        return

    query = message.text.strip()
    logger.info(f"[SEARCH] PM hit from={message.from_user.id} text={query[:60]!r}")

    # Skip commands (unified check inside the handler — more reliable than filter)
    if query.startswith("/"):
        logger.info(f"[SEARCH] skipping command: {query.split()[0]}")
        return

    if len(query) < 2 or len(query) > 120:
        logger.info(f"[SEARCH] length out of range: {len(query)}")
        return

    await _handle_search(client, message, query)


# ═══════════════════════ GROUP / CHANNEL — SMART TRIGGER ═══════════════════════
@Client.on_message(filters.text & (filters.group | filters.channel) & ~filters.service)
async def handle_group_text(client: Client, message: Message):
    """Group: only search when message looks like a title OR bot is mentioned/replied."""
    if not message.text:
        return

    text = message.text.strip()
    me = (getattr(client, "username", "") or "").lower()

    # ── Trigger 1: reply to bot's message ──
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.is_self and _looks_like_title(text):
            await _handle_search(client, message, text, is_group=True)
            return

    # ── Trigger 2: @mention of bot ──
    if me and f"@{me}" in text.lower():
        cleaned = re.sub(rf"@{re.escape(me)}", "", text, flags=re.IGNORECASE).strip()
        if len(cleaned) >= 2:
            await _handle_search(client, message, cleaned, is_group=True)
            return

    # ── Trigger 3: message itself looks like a title ──
    if _looks_like_title(text):
        await _handle_search(client, message, text, is_group=True)
        return


# ═══════════════════════ CORE SEARCH ═══════════════════════
async def _handle_search(client: Client, message: Message, raw_query: str, is_group: bool):
    """Search and send the best file, or picker if multiple titles."""
    logger.info(f"[SEARCH] starting search for {raw_query!r}")
    try:
        status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
        logger.info(f"[SEARCH] status message sent id={status.id}")
    except Exception as e:
        logger.exception(f"[SEARCH] failed to send status: {e}")
        return

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        try:
            await status.edit_text("❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        except Exception:
            pass
        return

    # Search all shards
    if is_series:
        result = await engine.search_series(norm, year=year)
    else:
        r_movie, r_series = await asyncio.gather(
            engine.search_movie(norm, year=year),
            engine.search_series(norm, year=year),
        )
        result = r_movie if r_movie.hits else r_series

    hits = result.hits

    # ── No results ──
    if not hits:
        if not result.complete:
            try:
                await status.edit_text(
                    "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                    "⚠️ ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ.\n"
                    "ᴘʟᴇᴀꜱᴇ ᴛʀʏ ᴀɢᴀɪɴ ɪɴ ᴀ ᴍᴏᴍᴇɴᴛ.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

        # Log request
        try:
            await request_repo.add(
                message.from_user.id, norm, raw_query,
                "series" if is_series else "movie",
            )
        except Exception:
            pass

        try:
            await status.edit_text(
                f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"❌ ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ꜰɪʟᴇ ꜰᴏʀ <code>{raw_query}</code>\n\n"
                f"📝 ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ ʜᴀꜱ ʙᴇᴇɴ ʀᴇᴄᴏʀᴅᴇᴅ.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── Group titles ──
    titles: Dict[str, List[FileHit]] = {}
    for h in hits:
        key = (h.series_title or h.title or "?").strip()
        titles.setdefault(key, []).append(h)

    # ── ONE TITLE → send best file directly ──
    if len(titles) == 1:
        title_hits = list(titles.values())[0]
        best = (
            ranker.best_for_episode(title_hits) if is_series
            else ranker.rank(title_hits)[0]
        )

        # Force-sub (private only)
        if not is_group:
            ok, missing = await subscription.is_subscribed(client, message.from_user.id)
            if not ok:
                try:
                    await status.edit_text(
                        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                        "⚠️ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ.",
                        reply_markup=_sub_keyboard(missing),
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
                return

        # Delete the "searching..." message
        try:
            await status.delete()
        except Exception:
            pass

        # Send to whoever triggered (PM → user; group → the group so everyone sees)
        target_chat = message.chat.id if is_group else message.from_user.id
        group_id = message.chat.id if is_group else None

        ok, err = await delivery.send_file(client, target_chat, best, group_id=group_id)
        if not ok and err:
            try:
                await message.reply_text(err)
            except Exception:
                pass
        return

    # ── MULTIPLE TITLES → picker ──
    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode="series" if is_series else "movie",
        candidates=[
            {
                "title": t,
                "year": v[0].year,
                "type": v[0].type,
                "count": len(v),
            }
            for t, v in titles.items()
        ][:10],
    )
    if not session:
        try:
            await status.edit_text("❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        except Exception:
            pass
        return

    rows: List[List[InlineKeyboardButton]] = []
    for i, (title, th) in enumerate(list(titles.items())[:10]):
        year = th[0].year
        label = f"🎬 {title}" + (f" ({year})" if year else "")
        rows.append([
            InlineKeyboardButton(
                label.upper(),
                callback_data=f"sr:pick:{session.session_id}:{i}",
            )
        ])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"🔎 <b>{len(titles)} ᴍᴀᴛᴄʜᴇꜱ ꜰᴏᴜɴᴅ</b>",
        DIV, "",
        f"🔍 Qᴜᴇʀʏ: <code>{raw_query}</code>",
        "",
        "ꜱᴇʟᴇᴄᴛ ᴏɴᴇ:",
    ])
    try:
        await status.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[SEARCH] picker render failed: {e}")


# ═══════════════════════ SUBSCRIPTION KEYBOARD ═══════════════════════
def _sub_keyboard(missing_channels: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for ch in missing_channels[:5]:
        try:
            cid = str(ch).replace("-100", "").replace("-", "")
            url = f"https://t.me/c/{cid}/1"
        except Exception:
            url = "https://t.me/"
        rows.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=url)])
    rows.append([InlineKeyboardButton("🔄 CHECK AGAIN", callback_data="sr:check_sub")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════ CALLBACKS ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:close$"))
async def cb_close(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sr:check_sub$"))
async def cb_check_sub(client: Client, q: CallbackQuery):
    ok, missing = await subscription.is_subscribed(client, q.from_user.id)
    if ok:
        await q.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ! ꜱᴇɴᴅ ʏᴏᴜʀ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ.", show_alert=True)
        try:
            await q.message.delete()
        except Exception:
            pass
    else:
        await q.answer("❌ ꜱᴛɪʟʟ ᴍɪꜱꜱɪɴɢ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^sr:pick:([a-f0-9]+):(\d+)$"))
async def cb_pick(client: Client, q: CallbackQuery):
    """User picked one title from the picker."""
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
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
        try:
            await q.message.edit_text("❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ.")
        except Exception:
            pass
        return

    # Force-sub check (private only)
    is_group = q.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
    if not is_group:
        ok, missing = await subscription.is_subscribed(client, q.from_user.id)
        if not ok:
            try:
                await q.message.edit_text(
                    "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                    "⚠️ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ.",
                    reply_markup=_sub_keyboard(missing),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return

    best = (
        ranker.best_for_episode(result.hits) if is_series
        else ranker.rank(result.hits)[0]
    )

    target_chat = q.message.chat.id if is_group else q.from_user.id
    group_id = q.message.chat.id if is_group else None

    ok, err = await delivery.send_file(client, target_chat, best, group_id=group_id)
    if ok:
        try:
            await q.message.delete()
        except Exception:
            pass
    elif err:
        try:
            await q.message.edit_text(err)
        except Exception:
            pass
