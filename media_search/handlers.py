"""
🏨 DOWNTOWN VILLA — Auto-filter handlers
Full interactive flow:
  Movie: Title → Language → Quality → Release → Deliver
  Series: Title → Language → Season → Episode → Quality → Release → Deliver
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from media_search.delivery import delivery
from media_search.engine import engine
from media_search.models import FileHit
from media_search.normalizer import parse_query, normalize
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from media_search.sessions import sessions
from media_search.subscription import subscription

logger = logging.getLogger(__name__)

DIV = "━" * 26


# ═══════════════════════ HELPERS ═══════════════════════
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


def _display_title(t: str, year: Optional[int]) -> str:
    """Pretty title for buttons."""
    base = (t or "?").strip().title()
    return f"{base} ({year})" if year else base


# ═══════════════════════ MAIN ENTRY (called from plugins/auto_filter.py) ═══════════════════════
async def _handle_search(client: Client, message: Message, raw_query: str, is_group: bool = False):
    logger.info(f"[SEARCH] START for {raw_query!r} is_group={is_group}")

    try:
        status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
    except Exception as e:
        logger.exception(f"[SEARCH] reply failed: {e}")
        return

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        await _edit(status, "❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        return

    # ── Search all shards ──
    if is_series:
        result = await engine.search_series(norm, year=year)
    else:
        r_movie, r_series = await asyncio.gather(
            engine.search_movie(norm, year=year),
            engine.search_series(norm, year=year),
        )
        result = r_movie if r_movie.hits else r_series
        if not is_series and not result.hits:
            result = await engine.search_any(norm, year=year)

    hits = result.hits
    logger.info(f"[SEARCH] got {len(hits)} hits complete={result.complete}")

    # ── No results ──
    if not hits:
        if not result.complete:
            await _edit(
                status,
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ. ᴛʀʏ ᴀɢᴀɪɴ.",
            )
            return
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

    # ── Group by (title, year) ──
    groups = _group_hits(hits)
    logger.info(f"[SEARCH] grouped into {len(groups)} title(s)")

    # ── Save session ──
    candidates = []
    for (t, y), th in groups.items():
        candidates.append({
            "title": t,
            "year": y,
            "type": th[0].type,
            "count": len(th),
        })

    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode="series" if is_series else "movie",
        candidates=candidates,
    )
    if not session:
        await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        return

    # ── ONE title → jump straight to language ──
    if len(candidates) == 1:
        c = candidates[0]
        await sessions.update(
            session.session_id,
            selected_title=c["title"],
            selected_year=c["year"],
        )
        await _show_languages(status, session.session_id)
        return

    # ── MULTIPLE → title picker ──
    rows: List[List[InlineKeyboardButton]] = []
    for i, c in enumerate(candidates[:10]):
        label = _display_title(c["title"], c["year"])
        rows.append([InlineKeyboardButton(
            label.upper(),
            callback_data=f"sr:pick:{session.session_id}:{i}",
        )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        status,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🔎 <b>{len(candidates)} ᴛɪᴛʟᴇꜱ ꜰᴏᴜɴᴅ</b>",
            DIV, "",
            f"🔍 Qᴜᴇʀʏ: <code>{raw_query}</code>",
            "",
            "ꜱᴇʟᴇᴄᴛ ᴀ ᴛɪᴛʟᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ GROUPING ═══════════════════════
def _group_hits(hits: List[FileHit]) -> Dict[tuple, List[FileHit]]:
    """
    Group files by (display_title, year).
    Merges "KGF Chapter" + "KGF Chapter" with same year into one group.
    Splits by year so Chapter 1 (2018) and Chapter 2 (2022) stay separate.
    """
    groups: Dict[tuple, List[FileHit]] = {}
    for h in hits:
        base = (h.series_title or h.title or "?").strip()
        # Remove trailing numbers from base (e.g. "KGF Chapter 1" → "KGF Chapter")
        import re
        base_clean = re.sub(r"\s+\d+\s*$", "", base).strip()
        key = (base_clean or base, h.year)
        groups.setdefault(key, []).append(h)
    return groups


# ═══════════════════════ LANGUAGE SCREEN ═══════════════════════
async def _show_languages(message_or_msg, session_id: str):
    session = await sessions.get(session_id)
    if not session:
        return
    title = session.selected_title
    year = session.selected_year

    # Re-search this exact title
    norm = normalize(title)
    result = await engine.search_any(norm, year=year)
    hits = _filter_by_title(result.hits, title, year)
    if not hits:
        await _edit(message_or_msg, "❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ᴛɪᴛʟᴇ.")
        return

    langs = sorted({l for h in hits for l in (h.audio_languages or [])})
    if not langs:
        # No language info → skip straight to quality
        await sessions.update(session_id, selected_language="")
        await _show_qualities(message_or_msg, session_id)
        return

    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for i, lang in enumerate(langs[:12]):
        pair.append(InlineKeyboardButton(
            lang.upper(), callback_data=f"sr:lang:{session_id}:{i}",
        ))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:back:{session_id}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        message_or_msg,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🎬 <b>{_display_title(title, year)}</b>",
            f"📦 ꜰɪʟᴇꜱ: <code>{len(hits)}</code>",
            DIV, "",
            "🌐 ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ QUALITY SCREEN (movies) ═══════════════════════
async def _show_qualities(message_or_msg, session_id: str):
    session = await sessions.get(session_id)
    if not session:
        return
    title = session.selected_title
    year = session.selected_year
    lang = session.selected_language

    norm = normalize(title)
    result = await engine.search_any(norm, year=year)
    hits = _filter_by_title(result.hits, title, year)
    if lang:
        hits = [h for h in hits if lang in (h.audio_languages or [])]

    quals = sorted({(h.quality or "").upper() for h in hits if h.quality})
    if not quals:
        await _edit(message_or_msg, "❌ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for i, q in enumerate(quals[:10]):
        pair.append(InlineKeyboardButton(
            q, callback_data=f"sr:q:{session_id}:{i}",
        ))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:lang_back:{session_id}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        message_or_msg,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🎬 <b>{_display_title(title, year)}</b>",
            f"🌐 ʟᴀɴɢᴜᴀɢᴇ: <code>{lang or '—'}</code>",
            f"📦 ꜰɪʟᴇꜱ: <code>{len(hits)}</code>",
            DIV, "",
            "🎞️ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ FILE LIST ═══════════════════════
async def _show_files(message_or_msg, session_id: str):
    session = await sessions.get(session_id)
    if not session:
        return
    title = session.selected_title
    year = session.selected_year
    lang = session.selected_language
    qual = session.selected_quality

    norm = normalize(title)
    result = await engine.search_any(norm, year=year)
    hits = _filter_by_title(result.hits, title, year)
    if lang:
        hits = [h for h in hits if lang in (h.audio_languages or [])]
    if qual:
        hits = [h for h in hits if (h.quality or "").upper() == qual.upper()]

    hits = ranker.rank(hits)
    # Dedupe by file_unique_id (fallback file_id)
    seen = set()
    uniq = []
    for h in hits:
        k = h.file_unique_id or h.file_id
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)

    if not uniq:
        await _edit(message_or_msg, "❌ ɴᴏ ʀᴇʟᴇᴀꜱᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    # Store the exact hit list in the session for later retrieval
    await sessions.update(
        session_id,
        candidates=session.candidates,  # keep original
    )

    rows: List[List[InlineKeyboardButton]] = []
    for i, h in enumerate(uniq[:10]):
        label = f"📦 {_human_size(h.file_size)} • {(h.codec or '?').upper()}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"sr:file:{session_id}:{i}",
        )])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:q_back:{session_id}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        message_or_msg,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🎬 <b>{_display_title(title, year)}</b>",
            f"🌐 ʟᴀɴɢᴜᴀɢᴇ: <code>{lang or '—'}</code>",
            f"🎞️ Qᴜᴀʟɪᴛʏ: <code>{qual or '—'}</code>",
            f"📦 ʀᴇʟᴇᴀꜱᴇꜱ: <code>{len(uniq)}</code>",
            DIV, "",
            "ᴘɪᴄᴋ ᴀ ʀᴇʟᴇᴀꜱᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ FILTER HELPER ═══════════════════════
def _filter_by_title(hits: List[FileHit], title: str, year: Optional[int]) -> List[FileHit]:
    norm = normalize(title)
    import re
    out = []
    for h in hits:
        base = (h.series_title or h.title or "").strip()
        base_clean = re.sub(r"\s+\d+\s*$", "", base).strip()
        if normalize(base_clean) != norm:
            continue
        if year and h.year != year:
            continue
        out.append(h)
    if not out:
        # Fallback: looser match
        for h in hits:
            if year and h.year != year:
                continue
            bn = normalize(h.series_title or h.title or "")
            if bn.startswith(norm) or norm.startswith(bn):
                out.append(h)
    return out


# ═══════════════════════ EDIT HELPER ═══════════════════════
async def _edit(target, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    """Edit a Message or CallbackQuery.message."""
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[SEARCH] edit failed: {type(e).__name__}: {e}")


# ═══════════════════════ CALLBACKS (handled in plugins/auto_filter.py) ═══════════════════════
# Callbacks are registered in plugins/auto_filter.py so Pyrogram finds them at top level.
# We expose helper functions here for those handlers to call.
