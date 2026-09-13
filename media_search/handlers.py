"""
🏨 DOWNTOWN VILLA — Simplified Auto-filter handlers.
Search → file list (sorted small→big) → deliver.
Misspelled → IMDb picker → click → file list → deliver.
No language / quality / season / episode pickers.
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from media_search.delivery import delivery
from media_search.engine import engine
from media_search.models import FileHit
from media_search.normalizer import normalize, parse_query
from media_search.requests import requests as request_repo
from media_search.sessions import sessions
from media_search.subscription import subscription
from services.formatting import clean_filename, human_size_short

logger = logging.getLogger(__name__)

DIV = "━" * 26


# ═══════════════════════ HELPERS ═══════════════════════
def _display_title(t: str, year: Optional[int]) -> str:
    base = (t or "?").strip().title()
    return f"{base} ({year})" if year else base


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
        logger.warning(f"[SEARCH] edit failed: {type(e).__name__}: {e}")


def _sub_keyboard(missing: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for ch in missing[:5]:
        try:
            cid = str(ch).replace("-100", "").replace("-", "")
            url = f"https://t.me/c/{cid}/1"
        except Exception:
            url = "https://t.me/"
        rows.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=url)])
    rows.append([InlineKeyboardButton("🔄 CHECK AGAIN", callback_data="sr:check_sub")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
    return InlineKeyboardMarkup(rows)


def _dedupe_sorted_asc(hits: List[FileHit]) -> List[FileHit]:
    """Dedupe by file_unique_id, sort ascending by size (small → big)."""
    seen = set()
    uniq: List[FileHit] = []
    for h in hits:
        k = h.file_unique_id or h.file_id
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    uniq.sort(key=lambda h: (h.file_size is None, h.file_size or 0))
    return uniq


# ═══════════════════════ MAIN ENTRY ═══════════════════════
async def _handle_search(client: Client, message: Message, raw_query: str,
                         is_group: bool = False, _depth: int = 0):
    logger.info(f"[SEARCH] START for {raw_query!r} depth={_depth}")

    try:
        status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
    except Exception as e:
        logger.exception(f"[SEARCH] reply failed: {e}")
        return

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        await _edit(status, "❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        return

    # ── Search across all shards ──
    if is_series:
        result = await engine.search_series(norm, year=year)
    else:
        r_movie, r_series = await asyncio.gather(
            engine.search_movie(norm, year=year),
            engine.search_series(norm, year=year),
        )
        result = r_movie if r_movie.hits else r_series
        if not result.hits:
            result = await engine.search_any(norm, year=year)

    hits = result.hits
    logger.info(f"[SEARCH] {len(hits)} hits complete={result.complete}")

    # ── No results → suggestions ──
    if not hits:
        if not result.complete:
            await _edit(
                status,
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ. ᴛʀʏ ᴀɢᴀɪɴ.",
            )
            return
        await _handle_no_results(client, message, status, raw_query, norm, is_series)
        return

    # ── Directly show file list ──
    await _show_files(status, raw_query, hits)


# ═══════════════════════ NO-RESULTS → IMDb ═══════════════════════
async def _handle_no_results(client, message, status, raw_query, norm, is_series):
    try:
        from media_search.spell_check import get_suggestions, clean_query
    except Exception as e:
        logger.warning(f"[SEARCH] spell_check unavailable: {e}")
        await _edit(status, f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{raw_query}</code>")
        return

    cleaned = clean_query(raw_query)
    suggestions: List[Dict] = []
    try:
        suggestions = await get_suggestions(cleaned, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SEARCH] suggestions failed: {e}")

    if not suggestions and cleaned != raw_query:
        try:
            suggestions = await get_suggestions(raw_query, is_series=is_series)
        except Exception:
            pass

    if not suggestions:
        try:
            await request_repo.add(message.from_user.id, norm, raw_query,
                                   "series" if is_series else "movie")
        except Exception:
            pass
        await _edit(
            status,
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"❌ ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ꜰɪʟᴇ ꜰᴏʀ <code>{raw_query}</code>\n\n"
            f"📝 ʀᴇǫᴜᴇꜱᴛ ʀᴇᴄᴏʀᴅᴇᴅ.",
        )
        return

    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode="series" if is_series else "movie",
        candidates=suggestions,
    )
    if not session:
        await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        return

    rows = []
    for i, s in enumerate(suggestions[:10]):
        title = s.get("title") or "?"
        yr = s.get("year")
        label = f"🎬 {title}" + (f" ({yr})" if yr else "")
        rows.append([InlineKeyboardButton(
            label.upper(),
            callback_data=f"spol:{session.session_id}:{i}",
        )])
    rows.append([InlineKeyboardButton(
        "🔍 CHECK ON GOOGLE",
        url=f"https://www.google.com/search?q={raw_query}",
    )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        status,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            "🤔 <b>ᴅɪᴅ ʏᴏᴜ ᴍᴇᴀɴ?</b>",
            DIV, "",
            f"🔍 Yᴏᴜ ꜱᴇᴀʀᴄʜᴇᴅ: <code>{raw_query}</code>",
            f"📝 <b>{len(suggestions)}</b> ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ:",
            "",
            "ᴘɪᴄᴋ ᴛʜᴇ ᴏɴᴇ ʏᴏᴜ ᴍᴇᴀɴᴛ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ SPOL (IMDb PICK) ═══════════════════════
async def _pick_suggestion(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if idx >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    s = session.candidates[idx]
    title = s.get("title") or ""
    year = s.get("year")
    imdb_id = s.get("metadata_id")
    await q.answer(f"🔎 ꜱᴇᴀʀᴄʜɪɴɢ: {title[:30]}")

    norm = normalize(title)
    result = await engine.search_any(norm, year=year)
    hits = result.hits
    if not hits and year:
        result = await engine.search_any(norm, year=None)
        hits = result.hits

    # ── Not found → request channel ──
    if not hits:
        try:
            from services.request_service import post_request
            await post_request(
                client=client,
                user_id=q.from_user.id,
                username=getattr(q.from_user, "username", "") or "",
                full_name=getattr(q.from_user, "first_name", "") or "",
                movie_name=title,
                imdb_id=imdb_id,
                user_query=session.query or title,
            )
        except Exception as e:
            logger.warning(f"[SEARCH] request post failed: {e}")

        try:
            await request_repo.add(
                q.from_user.id, norm, title,
                "series" if session.mode == "series" else "movie",
            )
        except Exception:
            pass

        admin_url = "https://t.me/"
        try:
            from core.config import OWNER_LNK, SUPPORT_CHAT
            admin_url = OWNER_LNK or SUPPORT_CHAT or admin_url
        except Exception:
            pass

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔰 REQUEST TO ADMIN", url=admin_url)],
            [InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")],
        ])
        try:
            year_txt = f" ({year})" if year else ""
            await q.message.edit_text(
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"😌 <b>{title}</b>{year_txt} ɪꜱ ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.\n\n"
                "📝 ʀᴇǫᴜᴇꜱᴛ ꜱᴇɴᴛ — ᴀᴅᴍɪɴ ᴡɪʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ꜱᴏᴏɴ.",
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── Found → show file list directly ──
    title_line = title + (f" ({year})" if year else "")
    await _show_files(q.message, title_line, hits)


# ═══════════════════════ FILE LIST (SORTED SMALL → BIG) ═══════════════════════
async def _show_files(target, display_title: str, hits: List[FileHit]):
    """Show all matching files as buttons: size + clean name. Small → big."""
    uniq = _dedupe_sorted_asc(hits)
    if not uniq:
        await _edit(target, "❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ.")
        return

    # Create a session so we can reference hits later
    from pyrogram.types import Message as _Msg
    # We need user_id/chat_id — try to extract
    msg = getattr(target, "message", target)
    user_id = getattr(msg, "from_user", None)
    user_id = getattr(user_id, "id", None) if user_id else None
    chat_id = getattr(getattr(msg, "chat", None), "id", None)

    # Store the file list in a session-less key so we can retrieve on click
    # Simplest approach: encode the index into the callback; re-fetch on click
    sid = f"fl_{abs(hash(display_title + str(len(uniq)))):x}"

    # Create a minimal session with the hits stored
    session = await sessions.create(
        user_id=user_id or 0,
        chat_id=chat_id or 0,
        query=display_title,
        normalized_query=normalize(display_title),
        mode="movie",
        candidates=[{
            "file_id": h.file_id,
            "file_unique_id": h.file_unique_id,
            "file_name": h.file_name,
            "file_size": h.file_size,
            "title": h.title,
            "year": h.year,
            "quality": h.quality,
            "codec": h.codec,
            "audio_languages": h.audio_languages,
            "subtitle_languages": h.subtitle_languages,
            "has_subtitle": h.has_subtitle,
            "type": h.type,
            "series_title": h.series_title,
            "season": h.season,
            "episode": h.episode,
            "caption": h.caption,
        } for h in uniq[:30]],
    )
    if not session:
        await _edit(target, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ.")
        return

    sid = session.session_id

    display = uniq[:10]

    rows: List[List[InlineKeyboardButton]] = []
    for i, h in enumerate(display):
        size = human_size_short(h.file_size)
        clean = clean_filename(h.file_name, max_len=42)
        label = f"📦 {size} · {clean}"
        if len(label) > 62:
            label = label[:59] + "…"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"fl:{sid}:{i}",
        )])

    if len(uniq) > 10:
        rows.append([InlineKeyboardButton(
            f"➕ {len(uniq) - 10} ᴍᴏʀᴇ ʀᴇʟᴇᴀꜱᴇꜱ",
            callback_data=f"fl:{sid}:more",
        )])

    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        DIV, "",
        f"🎬 <b>{display_title}</b>",
        f"📦 <b>{len(uniq)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ",
        "",
        "ᴘɪᴄᴋ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ:",
    ]
    await _edit(target, "\n".join(lines), kb=InlineKeyboardMarkup(rows))


# ═══════════════════════ FILE CLICK → DELIVER ═══════════════════════
async def _pick_file_by_index(client, q, sid, idx):
    """User clicked a file button. Deliver to their PM."""
    session = await sessions.get(sid)
    if not session:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    # Determine index (ignore if `more` payload)
    try:
        i = int(idx)
    except (TypeError, ValueError):
        await q.answer("ᴜꜱᴇ ᴛʜᴇ ꜰɪʀꜱᴛ 10 ʀᴇʟᴇᴀꜱᴇꜱ", show_alert=True)
        return

    if i >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    # Force-sub check
    ok, missing = await subscription.is_subscribed(client, q.from_user.id)
    if not ok:
        await q.answer()
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

    await q.answer("📤 ꜱᴇɴᴅɪɴɢ ᴛᴏ ʏᴏᴜʀ ᴘᴍ...")

    data = session.candidates[i]
    # Rebuild a FileHit from the stored data
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

    ok, err = await delivery.send_file(client, q.from_user.id, hit)
    if not ok and err:
        try:
            await q.message.reply_text(err)
        except Exception:
            pass
